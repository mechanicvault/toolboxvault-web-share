"""Feedback boards service (feedback module, wave 3, 2026-10-20).

Two boards — Bug Reports + Feature Requests — under ONE module
(build choice, documented in the manifest): a post names its
board; statuses, votes, comments and moderation are written
once and filtered by board. Routes: /feedback/bugs +
/feedback/features in the UI; the API carries `board` on the post.

DELIBERATE DEVIATION from the forum (owner decision 2026-10-20):
feedback is OPEN feedback. POSTING is open to ANY signed-in
account — free included; the forum's paid-contribution gate
does NOT apply here. Reading was open to everyone until
2026-11-10 (busy work #1): the boards are members-only reading
now — the routes refuse anonymous callers, and this layer just
serializes for a resolved member (exact-key payloads, no
emails ever). What still applies, on every write: the
messaging spam firewall's content screen (held posts wait for
a moderator) and its trust-tier budgets (volume brakes counted
against these tables).

Lifecycle status (open | acknowledged | planned | in_progress |
done | declined) is set by moderators / operators /
community_admins, with an optional public note; the poster is
notified on every change. Closure (sweep E5, busy-work #7): a
post whose status is done or declined is CLOSED — derived from
status via models.is_closed, carried as `closed` on every post
payload, and locked against new comments; moving the status
back to an active one reopens it in the same action. Comments are FLAT (the forum's reply
shape); the poster and earlier commenters are notified
first-unread style — while an unread feedback_comment note for
the post sits in their inbox, later comments stay quiet.

SERVICE INTERFACE (stable; bump the manifest version on change):
  - list_posts / post_view / get_post — the member reads
    (list_posts sorts newest-first, or most-upvoted with
    sort="top" — owner 2026-11-06).
  - create_post / toggle_vote / create_comment / delete_post /
    report_target — the member writes (any signed-in account).
    create_post also fans a `feedback_new_post` notification
    out to the admin tiers (god + moderator_admin) in its own
    commit (owner 2026-11-06) — plus the ONE designated
    assistant account, when one is designated (see
    designated_assistant; owner 2026-11-06, Marvin login lane).
  - set_status — the moderator lifecycle lever.
  - set_urgency — the moderator urgency lever: the filer's
    urgency (low | medium | high, chosen at filing, default
    medium) is locked to everyone else, the poster included.
  - list_reports / dismiss_report / list_held / release_target /
    discard_target / remove_target — the moderation queue.
  - export_rows(db, owner_id) — the data export's feedback.json.
  - tombstone_author(db, user_id) — the account-deletion seam.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import i18n
from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.feedback import models

# The exact public payload contracts (see the serializers).
AUTHOR_KEYS = (
    "user_id",
    "display_name",
    "account_number",
    "member_since",
    "role",
)
POST_KEYS = (
    "id",
    "board",
    "title",
    "body",
    "author",
    "status",
    "closed",
    "status_note",
    "urgency",
    "visibility",
    "vote_count",
    "comment_count",
    "voted_by_me",
    "mine",
    "created_at",
    "updated_at",
)
COMMENT_KEYS = (
    "id",
    "post_id",
    "author",
    "body",
    "visibility",
    "mine",
    "created_at",
)

FORMER_MEMBER = "Former member"
_POST_CAP = 500


class FeedbackError(ValueError):
    """Friendly refusal. Routes -> 422."""


class FeedbackNotFound(FeedbackError):
    """Missing OR not visible to you — ids never leak. -> 404."""


class RateLimited(FeedbackError):
    """The firewall's posting budget is spent. -> 429."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- authors ----------------------------------------------------------------------


def author_block(db: Session, user_id: uuid.UUID, *, gone: bool = False) -> dict:
    """The public author identity (the forum's shape, minus
    reputation — feedback carries no commerce standing): display
    name, account number, member since, role. Deleted accounts
    render as Former member — never an error, never a stale name,
    and NEVER an email."""
    user = None if gone else core_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        return {
            "user_id": user_id,
            "display_name": FORMER_MEMBER,
            "account_number": "",
            "member_since": None,
            "role": "user",
        }
    return {
        "user_id": user.id,
        "display_name": user.name,
        "account_number": user.account_number,
        "member_since": user.created_at,
        "role": user.role or "user",
    }


# -- firewall ------------------------------------------------------------------------


def _check_budget(db: Session, user, *, comments: bool) -> None:
    """Trust-tier volume brakes (the forum's budgets, counted
    against the feedback tables): new posts ride the thread caps,
    comments the message caps."""
    from app.modules.messaging import spam

    caps = spam.tier_caps(db, user)
    now = _now()
    if comments:
        model, hour_cap, day_cap = (
            models.FeedbackComment,
            caps["messages_per_hour"],
            caps["messages_per_day"],
        )
        wording = ("commenting", "comment")
    else:
        model, hour_cap, day_cap = (
            models.FeedbackPost,
            caps["new_threads_per_hour"],
            caps["new_threads_per_day"],
        )
        wording = ("posting", "post")
    base = select(func.count(model.id)).where(model.author_id == user.id)
    hour = int(db.scalar(base.where(model.created_at >= now - timedelta(hours=1))) or 0)
    if hour >= hour_cap:
        raise RateLimited(
            f"You're {wording[0]} too quickly — please wait a bit "
            f"before adding another {wording[1]}."
        )
    day = int(db.scalar(base.where(model.created_at >= now - timedelta(days=1))) or 0)
    if day >= day_cap:
        raise RateLimited(
            f"You've reached today's limit for new {wording[1]}s. "
            "It resets tomorrow."
        )


def _screen(db: Session, author_id: uuid.UUID, *bodies: str) -> tuple[str, list[str]]:
    """The firewall's content screen over the given bodies. A held
    body parks the write for moderators; flags record what the
    screen saw."""
    from app.modules.messaging import spam

    flags: list[str] = []
    for body in bodies:
        status, seen = spam.screen_body(db, author_id, body or "")
        for flag in seen:
            if flag not in flags:
                flags.append(flag)
        if status == "held":
            return "held", flags
    return "sent", flags


# -- reads ------------------------------------------------------------------------------


def get_post(db: Session, post_id: uuid.UUID) -> models.FeedbackPost | None:
    return db.get(models.FeedbackPost, post_id)


def _vote_count(db: Session, post_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(models.FeedbackVote.id)).where(
                models.FeedbackVote.post_id == post_id
            )
        )
        or 0
    )


def _comment_count(db: Session, post_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(models.FeedbackComment.id)).where(
                models.FeedbackComment.post_id == post_id,
                models.FeedbackComment.visibility == "visible",
            )
        )
        or 0
    )


def _voted(db: Session, post_id: uuid.UUID, viewer_id: uuid.UUID | None) -> bool:
    if viewer_id is None:
        return False
    return (
        db.scalars(
            select(models.FeedbackVote).where(
                models.FeedbackVote.post_id == post_id,
                models.FeedbackVote.user_id == viewer_id,
            )
        ).first()
        is not None
    )


def post_view(
    db: Session, row: models.FeedbackPost, viewer_id: uuid.UUID | None = None
) -> dict:
    """The exact post payload (POST_KEYS — both read faces ship
    byte-identical keys; `mine`/`voted_by_me` read False for a
    member who isn't the author / hasn't voted). A removed
    post's body never leaves: the tombstone carries the
    visibility, not the text."""
    removed = row.visibility in ("removed_author", "removed_mod")
    return {
        "id": row.id,
        "board": row.board,
        "title": row.title,
        "body": "" if removed else row.body,
        "author": author_block(db, row.author_id, gone=row.author_gone),
        "status": row.status,
        # Closure rides every post payload under this exact name
        # (sweep E5): the board assistant watcher keys on it.
        "closed": models.is_closed(row.status),
        "status_note": row.status_note,
        "urgency": row.urgency,
        "visibility": row.visibility,
        "vote_count": _vote_count(db, row.id),
        "comment_count": _comment_count(db, row.id),
        "voted_by_me": _voted(db, row.id, viewer_id),
        "mine": viewer_id is not None and row.author_id == viewer_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def comment_view(
    db: Session, row: models.FeedbackComment, viewer_id: uuid.UUID | None = None
) -> dict:
    removed = row.visibility in ("removed_author", "removed_mod")
    return {
        "id": row.id,
        "post_id": row.post_id,
        "author": author_block(db, row.author_id, gone=row.author_gone),
        "body": "" if removed else row.body,
        "visibility": row.visibility,
        "mine": viewer_id is not None and row.author_id == viewer_id,
        "created_at": row.created_at,
    }


def _visible_to(row, viewer_id: uuid.UUID | None, viewer_is_mod: bool) -> bool:
    """Held writes are visible to their author + moderators only;
    removed ones read as tombstones to everyone."""
    if row.visibility == "held":
        return viewer_is_mod or (viewer_id is not None and row.author_id == viewer_id)
    return True


def list_posts(
    db: Session,
    *,
    board: str,
    viewer_id: uuid.UUID | None = None,
    viewer_is_mod: bool = False,
    status_filter: str = "",
    mine_only: bool = False,
    sort: str = "new",
    limit: int = 100,
) -> list[dict]:
    if board not in models.BOARDS:
        raise FeedbackNotFound("That board doesn't exist.")
    if sort not in ("new", "top"):
        raise FeedbackError("Unknown sort.")
    stmt = select(models.FeedbackPost).where(models.FeedbackPost.board == board)
    if sort == "top":
        # Most upvoted first (owner 2026-11-06: so moderators
        # and admins see how many people agree, top asks
        # first). Votes are rows, never a stored counter, so
        # the order rides a correlated count; ties fall back
        # to newest, like the default view.
        vote_count = (
            select(func.count(models.FeedbackVote.id))
            .where(models.FeedbackVote.post_id == models.FeedbackPost.id)
            .correlate(models.FeedbackPost)
            .scalar_subquery()
        )
        stmt = stmt.order_by(vote_count.desc(), models.FeedbackPost.created_at.desc())
    else:
        stmt = stmt.order_by(models.FeedbackPost.created_at.desc())
    stmt = stmt.limit(min(limit, _POST_CAP))
    if status_filter:
        if status_filter not in models.STATUSES:
            raise FeedbackError("Unknown status filter.")
        stmt = stmt.where(models.FeedbackPost.status == status_filter)
    if mine_only:
        stmt = stmt.where(models.FeedbackPost.author_id == viewer_id)
    rows = list(db.scalars(stmt))
    return [
        post_view(db, row, viewer_id)
        for row in rows
        if _visible_to(row, viewer_id, viewer_is_mod)
    ]


def post_detail(
    db: Session,
    post_id: uuid.UUID,
    viewer_id: uuid.UUID | None = None,
    viewer_is_mod: bool = False,
) -> dict:
    row = get_post(db, post_id)
    if row is None or not _visible_to(row, viewer_id, viewer_is_mod):
        raise FeedbackNotFound("That post isn't available.")
    comments = list(
        db.scalars(
            select(models.FeedbackComment)
            .where(models.FeedbackComment.post_id == row.id)
            .order_by(models.FeedbackComment.created_at, models.FeedbackComment.id)
        )
    )
    view = post_view(db, row, viewer_id)
    view["comments"] = [
        comment_view(db, c, viewer_id)
        for c in comments
        if _visible_to(c, viewer_id, viewer_is_mod)
    ]
    return view


# -- writes ------------------------------------------------------------------------------


# The designated assistant (Marvin login lane, owner
# 2026-11-06): the system setting that names the site's ONE
# assistant account. The value is the account's user id (a
# string), written by the operator when the account is created
# (Admin -> Settings edits the same system_settings table for
# its own keys). Deliberately a per-account designation, NOT a
# tier, a role, or a flag any account can claim: exactly the
# named account hears about new board posts alongside the
# admins, so it can ask clarifying questions in the thread.
ASSISTANT_USER_ID_SETTING = "feedback.assistant_user_id"


def designated_assistant(db: Session) -> core_models.User | None:
    """Resolve the designated assistant account, fresh on every
    call so an operator re-designation takes effect on the very
    next post. Unset, malformed, or pointing at a missing or
    inactive account resolves to None — the fan-out then
    behaves exactly as it did before the assistant existed.
    A settings read failure resolves to None too: hearing about
    a post is worth less than the post itself landing."""
    from app.modules.billing import entitlements

    try:
        raw = entitlements.get_setting(db, ASSISTANT_USER_ID_SETTING)
    except Exception:  # noqa: BLE001 — never sink the post
        return None
    if not raw:
        return None
    try:
        user_id = uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None
    user = db.get(core_models.User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def _notify_admins_new_post(
    db: Session, row: models.FeedbackPost, *, actor_id: uuid.UUID
) -> None:
    """Fan a new board post out to the ADMIN tiers' inboxes
    (owner 2026-11-06: "Bug reports and feature requests
    should create a notification on the admins account") —
    god + moderator_admin, resolved through the tier ladder
    so a legacy role shadow can't drift the audience. The
    moderator rung is deliberately NOT in the audience (the
    owner said "admins"; widening it is his one word). Held
    posts notify too: a post waiting on review is exactly
    what the admins need to hear about. The actor never hears
    about their own post. commit=False — the caller folds the
    notes into the post's own commit, and the kind's email
    twin rides the community category, whose email default
    is off.

    PLUS the designated assistant account (Marvin login lane,
    owner 2026-11-06): the ONE account named by the
    `feedback.assistant_user_id` setting receives the same
    note, so it can open the thread and ask the poster
    clarifying questions. This is an audience of exactly one
    named account — not a tier widening (moderators stay out),
    and the assistant never hears about its OWN posts (the
    actor exclusion covers it, like everyone else)."""
    from app.modules.core import tiers

    board_word = "bug report" if row.board == "bug" else "feature request"
    title = f"New {board_word}: {row.title}"
    author_name = author_block(db, row.author_id)["display_name"]
    recipients = {
        candidate.id: candidate
        for candidate in db.scalars(
            select(core_models.User).where(core_models.User.is_active.is_(True))
        ).all()
        if candidate.id != actor_id
        and tiers.resolved_tier(candidate) in ("god", "moderator_admin")
    }
    assistant = designated_assistant(db)
    if assistant is not None and assistant.id != actor_id:
        recipients.setdefault(assistant.id, assistant)
    for recipient in recipients.values():
        inbox.create_notification(
            db,
            recipient.id,
            kind=inbox.KIND_FEEDBACK_NEW_POST,
            title=title,
            body=f"{author_name} posted a new {board_word} on the board.",
            data={"post_id": str(row.id), "board": row.board},
            commit=False,
        )


def _require_not_blocked(db: Session, user_id: uuid.UUID) -> None:
    """The community-block door (admin lane, owner ruling
    2026-11-06): a member blocked from the boards by a god /
    moderator_admin seat can't post or comment — the refusal
    carries the plain-words reason and the support-ticket road
    back (forum.blocks owns the copy; the boards' feature key
    is its own, so a forum block and a board block are separate
    acts)."""
    from app.modules.forum import blocks as community_blocks

    try:
        community_blocks.require_not_blocked(db, user_id, "feedback_boards")
    except community_blocks.BlockError as exc:
        raise FeedbackError(str(exc)) from exc


def create_post(
    db: Session, user, *, board: str, title: str, body: str, urgency: str = "medium"
) -> dict:
    """Any signed-in account may post (the deliberate deviation —
    see the module docstring). The firewall screens title + body;
    a held post exists for its author + moderators until released."""
    if board not in models.BOARDS:
        raise FeedbackError("Pick a board: Bug Reports or Feature Requests.")
    if urgency not in models.URGENCIES:
        raise FeedbackError("Pick an urgency: Low, Medium or High.")
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise FeedbackError("Give your post a title.")
    if not body:
        raise FeedbackError("Describe it — the more detail, the faster it moves.")
    _require_not_blocked(db, user.id)
    _check_budget(db, user, comments=False)
    status, flags = _screen(db, user.id, title, body)
    row = models.FeedbackPost(
        board=board,
        author_id=user.id,
        title=title[:300],
        body=body,
        urgency=urgency,
        visibility="held" if status == "held" else "visible",
        flags=",".join(flags),
    )
    db.add(row)
    db.flush()
    _notify_admins_new_post(db, row, actor_id=user.id)
    db.commit()
    db.refresh(row)
    return post_view(db, row, user.id)


def toggle_vote(db: Session, user, post_id: uuid.UUID) -> dict:
    """One vote per user per post; voting again withdraws it."""
    row = get_post(db, post_id)
    if row is None or row.visibility != "visible":
        raise FeedbackNotFound("That post isn't available.")
    existing = db.scalars(
        select(models.FeedbackVote).where(
            models.FeedbackVote.post_id == row.id,
            models.FeedbackVote.user_id == user.id,
        )
    ).first()
    if existing is not None:
        db.delete(existing)
    else:
        db.add(models.FeedbackVote(post_id=row.id, user_id=user.id))
    db.commit()
    return post_view(db, row, user.id)


def create_comment(db: Session, user, *, post_id: uuid.UUID, body: str) -> dict:
    post = get_post(db, post_id)
    if post is None or post.visibility != "visible":
        raise FeedbackNotFound("That post isn't available.")
    # Closed posts take no new comments (sweep E5, busy-work #7):
    # the decision is made, so the thread locks where it stands —
    # still fully readable, and a moderator reopens it by moving
    # the status back to an active one. The refusal applies to
    # everyone alike, moderators included: reopening is the one
    # deliberate way back in, never a quiet exception.
    if models.is_closed(post.status):
        raise FeedbackError(
            "This post is closed, so no new comments can be added."
        )
    body = (body or "").strip()
    if not body:
        raise FeedbackError("Write something first.")
    _require_not_blocked(db, user.id)
    _check_budget(db, user, comments=True)
    status, flags = _screen(db, user.id, body)
    row = models.FeedbackComment(
        post_id=post.id,
        author_id=user.id,
        body=body,
        visibility="held" if status == "held" else "visible",
        flags=",".join(flags),
    )
    db.add(row)
    db.flush()
    if status != "held":
        _notify_comment(db, post, row)
    db.commit()
    db.refresh(row)
    return comment_view(db, row, user.id)


def _notify_comment(
    db: Session, post: models.FeedbackPost, comment: models.FeedbackComment
) -> None:
    """First-unread notifications (the forum_reply pattern): the
    poster + every earlier commenter hear about a new comment —
    unless an unread feedback_comment note for this post already
    sits in their inbox."""
    recipients: list[uuid.UUID] = []
    if post.author_id != comment.author_id and not post.author_gone:
        recipients.append(post.author_id)
    earlier = db.scalars(
        select(models.FeedbackComment.author_id)
        .where(
            models.FeedbackComment.post_id == post.id,
            models.FeedbackComment.author_id != comment.author_id,
            models.FeedbackComment.author_gone.is_(False),
        )
        .distinct()
    ).all()
    for author_id in earlier:
        if author_id not in recipients:
            recipients.append(author_id)
    for user_id in recipients:
        target = core_service.get_user_by_id(db, user_id)
        if target is None or not target.is_active:
            continue
        unread = db.scalars(
            select(core_models.Notification)
            .where(
                core_models.Notification.user_id == user_id,
                core_models.Notification.kind == inbox.KIND_FEEDBACK_COMMENT,
                core_models.Notification.read_at.is_(None),
            )
            .order_by(core_models.Notification.created_at.desc())
            .limit(50)
        ).all()
        if any((n.data or {}).get("post_id") == str(post.id) for n in unread):
            continue
        inbox.create_notification(
            db,
            user_id,
            kind=inbox.KIND_FEEDBACK_COMMENT,
            title="New comment on feedback",
            body=f"“{post.title}” has a new comment.",
            data={"post_id": str(post.id), "board": post.board},
            commit=False,
        )


def delete_post(db: Session, user, post_id: uuid.UUID) -> dict:
    """The author's own delete: a tombstone (the thread of
    comments keeps its shape), never a hard delete."""
    row = get_post(db, post_id)
    if row is None or row.author_id != user.id:
        raise FeedbackNotFound("That post isn't yours to remove.")
    if row.visibility in ("removed_author", "removed_mod"):
        raise FeedbackError("That post has already been removed.")
    row.visibility = "removed_author"
    row.body = ""
    db.commit()
    return post_view(db, row, user.id)


def delete_comment(db: Session, user, comment_id: uuid.UUID) -> dict:
    row = db.get(models.FeedbackComment, comment_id)
    if row is None or row.author_id != user.id:
        raise FeedbackNotFound("That comment isn't yours to remove.")
    if row.visibility in ("removed_author", "removed_mod"):
        raise FeedbackError("That comment has already been removed.")
    row.visibility = "removed_author"
    row.body = ""
    db.commit()
    return comment_view(db, row, user.id)


# -- status (moderators) -------------------------------------------------------------------


# The status-change note's words, per language (the status words
# match the boards' own dictionary labels). ES quotes ride « »
# per the site's Spanish convention (content_alerts precedent).
_STATUS_WORDS = {
    "en": {
        "open": "open",
        "acknowledged": "acknowledged",
        "planned": "planned",
        "in_progress": "in progress",
        "done": "done",
        "declined": "declined",
    },
    "es": {
        "open": "abierto",
        "acknowledged": "recibido",
        "planned": "planeado",
        "in_progress": "en curso",
        "done": "hecho",
        "declined": "rechazado",
    },
}

_STATUS_NOTE_COPY = {
    "en": {
        "title": "Your feedback was updated",
        "body": "“{title}” is now {status}",
        "closed": " This post is closed.",
        "reopened": " This post is open again.",
    },
    "es": {
        "title": "Tu publicación fue actualizada",
        "body": "«{title}» ahora está {status}",
        "closed": " Esta publicación está cerrada.",
        "reopened": " Esta publicación está abierta de nuevo.",
    },
}


def _status_note_copy(
    author, *, post_title: str, status: str, note: str, was_closed: bool, now_closed: bool
) -> tuple[str, str]:
    locale = i18n.resolve_locale(author)
    copy = _STATUS_NOTE_COPY[locale]
    body = copy["body"].format(
        title=post_title, status=_STATUS_WORDS[locale][status]
    )
    if note:
        body += f" — {note}"
    if not body.endswith("."):
        body += "."
    if now_closed:
        body += copy["closed"]
    elif was_closed:
        body += copy["reopened"]
    return copy["title"], body


def set_status(
    db: Session,
    actor,
    post_id: uuid.UUID,
    *,
    status: str,
    note: str = "",
) -> dict:
    """The lifecycle lever: moderators / operators /
    community_admins move a post along the roadmap; the poster is
    notified of the change (with the note, when given). Moving
    to done/declined closes the post in this same action, and
    moving a closed post back to an active status reopens it —
    closure is derived from status, so there is no second step
    and no second state to keep in step."""
    if status not in models.STATUSES:
        raise FeedbackError("Unknown status.")
    row = get_post(db, post_id)
    if row is None or row.visibility == "removed_mod":
        raise FeedbackNotFound("That post isn't available.")
    changed = row.status != status
    was_closed = models.is_closed(row.status)
    row.status = status
    row.status_note = (note or "").strip()[:500]
    db.flush()
    if changed and not row.author_gone:
        author = core_service.get_user_by_id(db, row.author_id)
        if author is not None and author.is_active:
            # One language per note — the AUTHOR's resolved
            # locale only (single-language rule, 2026-11-10) —
            # and the wording says plainly when the move closes
            # the post, or reopens a closed one (sweep E5).
            title, body = _status_note_copy(
                author,
                post_title=row.title,
                status=status,
                note=row.status_note,
                was_closed=was_closed,
                now_closed=models.is_closed(status),
            )
            inbox.create_notification(
                db,
                row.author_id,
                kind=inbox.KIND_FEEDBACK_STATUS,
                title=title,
                body=body,
                data={"post_id": str(row.id), "board": row.board},
                commit=False,
            )
    db.commit()
    db.refresh(row)
    return post_view(db, row, actor.id)


def set_urgency(
    db: Session,
    actor,
    post_id: uuid.UUID,
    *,
    urgency: str,
) -> dict:
    """The urgency lever (owner 2026-11-06): the filer picked
    the urgency at submission and can NEVER edit it after —
    there is no member route to this function at all. The
    people who respond on the boards (moderators / operators /
    community_admins, the route's require_moderator) can move
    it as triage teaches them more. Quiet by design: unlike a
    status change this is internal triage, so the poster is
    not notified."""
    if urgency not in models.URGENCIES:
        raise FeedbackError("Pick an urgency: Low, Medium or High.")
    row = get_post(db, post_id)
    if row is None or row.visibility == "removed_mod":
        raise FeedbackNotFound("That post isn't available.")
    row.urgency = urgency
    db.commit()
    db.refresh(row)
    return post_view(db, row, actor.id)


# -- reports + the moderation queue ---------------------------------------------------------


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


def report_target(
    db: Session, user, *, target_kind: str, target_id: uuid.UUID, reason: str
) -> dict:
    if target_kind not in models.TARGET_KINDS:
        raise FeedbackError("That can't be reported.")
    if target_kind == "post":
        target = get_post(db, target_id)
    else:
        target = db.get(models.FeedbackComment, target_id)
    if target is None or target.visibility in ("held", "removed_author", "removed_mod"):
        raise FeedbackNotFound("That isn't available to report.")
    existing = db.scalars(
        select(models.FeedbackReport).where(
            models.FeedbackReport.target_kind == target_kind,
            models.FeedbackReport.target_id == target_id,
            models.FeedbackReport.reporter_id == user.id,
            models.FeedbackReport.status == "open",
        )
    ).first()
    if existing is not None:
        raise FeedbackError(
            "You've already reported this — it's in the moderation queue."
        )
    row = models.FeedbackReport(
        target_kind=target_kind,
        target_id=target_id,
        reporter_id=user.id,
        reason=(reason or "").strip()[:500],
    )
    db.add(row)
    db.flush()
    # A flag tells the whole moderation team (admin lane, owner
    # ruling 2026-11-06: moderators, moderator admins AND god)
    # — in the flag's own commit.
    snap = _target_snapshot(db, row)
    inbox.notify_moderation_team(
        db,
        kind=inbox.KIND_COMMUNITY_FLAG,
        title=(
            "New flag: bug report post"
            if target.board == "bug"
            else "New flag: feature request post"
        ) if target_kind == "post" else "New flag: board comment",
        body=(
            f"{user.name} flagged “{snap['title']}”: "
            f"{row.reason or 'no notes given'}"
        ),
        data={
            "surface": "feedback",
            "report_id": str(row.id),
            "post_id": str(snap["post_id"]) if snap["post_id"] else "",
            "board": target.board if target_kind == "post" else "",
        },
        exclude_id=user.id,
    )
    db.commit()
    db.refresh(row)
    return _report_view(db, row)


def _target_snapshot(db: Session, row: models.FeedbackReport) -> dict:
    """What the queue shows about the reported content: author,
    excerpt, and (for comments) the parent post's title."""
    if row.target_kind == "post":
        post = get_post(db, row.target_id)
        if post is None:
            return {"title": "", "excerpt": "", "author_name": "", "author_id": None, "post_id": row.target_id}
        return {
            "title": post.title,
            "excerpt": (post.body or "")[:240],
            "author_name": author_block(db, post.author_id, gone=post.author_gone)["display_name"],
            "author_id": None if post.author_gone else post.author_id,
            "post_id": post.id,
        }
    comment = db.get(models.FeedbackComment, row.target_id)
    if comment is None:
        return {"title": "", "excerpt": "", "author_name": "", "author_id": None, "post_id": None}
    post = get_post(db, comment.post_id)
    return {
        "title": post.title if post else "",
        "excerpt": (comment.body or "")[:240],
        "author_name": author_block(db, comment.author_id, gone=comment.author_gone)["display_name"],
        "author_id": None if comment.author_gone else comment.author_id,
        "post_id": comment.post_id,
    }


def _report_view(db: Session, row: models.FeedbackReport) -> dict:
    snap = _target_snapshot(db, row)
    reporter = core_service.get_user_by_id(db, row.reporter_id)
    return {
        "id": row.id,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "post_id": snap["post_id"],
        "post_title": snap["title"],
        "target_excerpt": snap["excerpt"],
        "target_author_name": snap["author_name"],
        "target_author_id": snap["author_id"],
        "reporter_name": reporter.name if reporter else FORMER_MEMBER,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at,
    }


def list_reports(db: Session, status: str = "open") -> list[dict]:
    rows = list(
        db.scalars(
            select(models.FeedbackReport)
            .where(models.FeedbackReport.status == status)
            .order_by(models.FeedbackReport.created_at)
        )
    )
    return [_report_view(db, row) for row in rows]


def dismiss_report(db: Session, actor, report_id: uuid.UUID, note: str = "") -> dict:
    row = db.get(models.FeedbackReport, report_id)
    if row is None:
        raise FeedbackNotFound("That report isn't available.")
    row.status = "dismissed"
    row.resolution_note = (note or "")[:500]
    db.commit()
    _audit(db, actor, "feedback.report_dismiss", row.target_id, {"report_id": str(row.id)})
    return _report_view(db, row)


def _held_view(db: Session, kind: str, row) -> dict:
    if kind == "post":
        post, title = row, row.title
    else:
        post = get_post(db, row.post_id)
        title = post.title if post else ""
    return {
        "id": row.id,
        "target_kind": kind,
        "post_id": row.id if kind == "post" else row.post_id,
        "post_title": title,
        "author_name": author_block(db, row.author_id, gone=row.author_gone)["display_name"],
        "author_id": row.author_id,
        "body": row.body,
        "flags": [f for f in (row.flags or "").split(",") if f],
        "created_at": row.created_at,
    }


def list_held(db: Session) -> list[dict]:
    posts = db.scalars(
        select(models.FeedbackPost)
        .where(models.FeedbackPost.visibility == "held")
        .order_by(models.FeedbackPost.created_at)
    ).all()
    comments = db.scalars(
        select(models.FeedbackComment)
        .where(models.FeedbackComment.visibility == "held")
        .order_by(models.FeedbackComment.created_at)
    ).all()
    views = [_held_view(db, "post", r) for r in posts]
    views += [_held_view(db, "comment", r) for r in comments]
    return sorted(views, key=lambda v: v["created_at"])


def _resolve_target(db: Session, target_kind: str, target_id: uuid.UUID):
    if target_kind == "post":
        return get_post(db, target_id)
    if target_kind == "comment":
        return db.get(models.FeedbackComment, target_id)
    raise FeedbackError("Unknown moderation target.")


def release_target(db: Session, actor, target_kind: str, target_id: uuid.UUID) -> dict:
    row = _resolve_target(db, target_kind, target_id)
    if row is None or row.visibility != "held":
        raise FeedbackNotFound("That isn't being held.")
    row.visibility = "visible"
    db.flush()
    if target_kind == "comment":
        post = get_post(db, row.post_id)
        if post is not None:
            _notify_comment(db, post, row)
    db.commit()
    _audit(db, actor, "feedback.release", target_id, {"kind": target_kind})
    return _held_view(db, target_kind, row)


def discard_target(db: Session, actor, target_kind: str, target_id: uuid.UUID) -> dict:
    row = _resolve_target(db, target_kind, target_id)
    if row is None or row.visibility != "held":
        raise FeedbackNotFound("That isn't being held.")
    view = _held_view(db, target_kind, row)
    row.visibility = "removed_mod"
    row.removed_reason = "Discarded from the moderation queue."
    row.body = ""
    db.commit()
    _audit(db, actor, "feedback.discard", target_id, {"kind": target_kind})
    return view


def remove_target(
    db: Session, actor, target_kind: str, target_id: uuid.UUID, reason: str = ""
) -> dict:
    """A moderator removes a visible post/comment: tombstone with
    the reason kept on the row; open reports on it action."""
    row = _resolve_target(db, target_kind, target_id)
    if row is None or row.visibility in ("removed_author", "removed_mod"):
        raise FeedbackNotFound("That isn't available.")
    view = _held_view(db, target_kind, row)
    row.visibility = "removed_mod"
    row.removed_reason = (reason or "")[:500]
    row.body = ""
    for report in db.scalars(
        select(models.FeedbackReport).where(
            models.FeedbackReport.target_kind == target_kind,
            models.FeedbackReport.target_id == target_id,
            models.FeedbackReport.status == "open",
        )
    ).all():
        report.status = "actioned"
    db.commit()
    _audit(db, actor, "feedback.remove", target_id, {"kind": target_kind})
    return view


# -- export + deletion seam ----------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The export's feedback.json: MY posts (any visibility — my
    own backup carries my words) + the posts I upvoted."""
    posts = list(
        db.scalars(
            select(models.FeedbackPost)
            .where(models.FeedbackPost.author_id == owner_id)
            .order_by(models.FeedbackPost.created_at)
        )
    )
    comments = list(
        db.scalars(
            select(models.FeedbackComment)
            .where(models.FeedbackComment.author_id == owner_id)
            .order_by(models.FeedbackComment.created_at)
        )
    )
    votes = list(
        db.scalars(
            select(models.FeedbackVote).where(models.FeedbackVote.user_id == owner_id)
        )
    )
    return {
        "posts": [
            {
                "id": str(p.id),
                "board": p.board,
                "title": p.title,
                "body": p.body,
                "status": p.status,
                "closed": models.is_closed(p.status),
                "status_note": p.status_note,
                "urgency": p.urgency,
                "visibility": p.visibility,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in posts
        ],
        "comments": [
            {
                "id": str(c.id),
                "post_id": str(c.post_id),
                "body": c.body,
                "visibility": c.visibility,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ],
        "voted_post_ids": [str(v.post_id) for v in votes],
    }


def tombstone_author(db: Session, user_id: uuid.UUID) -> None:
    """The account-deletion seam (the forum rule): my posts +
    comments stay as Former-member tombstones (bodies wiped,
    boards unbroken), my votes go (they were mine alone), and
    reports I filed go with the account. Caller commits."""
    for post in db.scalars(
        select(models.FeedbackPost).where(models.FeedbackPost.author_id == user_id)
    ).all():
        post.author_gone = True
        post.body = ""
    for comment in db.scalars(
        select(models.FeedbackComment).where(
            models.FeedbackComment.author_id == user_id
        )
    ).all():
        comment.author_gone = True
        comment.body = ""
    db.query(models.FeedbackVote).filter(
        models.FeedbackVote.user_id == user_id
    ).delete(synchronize_session=False)
    db.query(models.FeedbackReport).filter(
        models.FeedbackReport.reporter_id == user_id
    ).delete(synchronize_session=False)
    db.flush()
