"""Community Forum service (community suite build 3, 2026-10-20).

The forum is the suite's third surface and reuses its shared
machinery instead of forking it:

- POSTING rides the paid-contribution gate (marketplace's
  can_publish — the pool's rule: enforcement OFF → open; ON →
  a paid plan from a paying source, a TRIAL never counts).
- Every post body passes the messaging SPAM FIREWALL's content
  screen (spam.screen_body: blocklisted domains + lure patterns
  hold the post for moderation; an ordinary link passes flagged),
  and posting budgets come from the firewall's trust tiers
  (spam.tier_caps) counted against the forum's own tables.
- Author reputation badges come from the ONE aggregate function
  (marketplace.reputation.summary_for) — the numbers can never
  disagree between the forum, the board, and seller profiles.
- Reports feed a moderation queue shaped exactly like the
  messaging queue; every moderator action writes a core audit
  row, like message moderation.
- A reply to your thread lands ONE inbox notification
  (core.inbox, kind forum_reply) — the first unread only, the
  message_received pattern.

READING IS PUBLIC: categories, threads and search answer the
identical exact-key payload to signed-in users and to anonymous
visitors (the /public twins in routes.py). No email ever appears;
author identity is the public profile fields only (display name,
account number, member since, role, reputation).

REPLIES ARE FLAT with one-quote snapshots (build choice): a
reply may quote ONE earlier post in the same thread; the quoted
author + excerpt are copied onto the reply, so the quote reads
correctly even after the original is edited or removed.

SERVICE INTERFACE (stable; bump the forum manifest version on
change):
  - forum_enabled(db) / can_post(db, user_id)
  - list_categories / category_view / list_threads /
    thread_view / search_threads — the public reads.
  - create_thread / create_reply / edit_post / delete_post /
    report_post — the member writes.
  - list_reports / dismiss_report / list_held / release_post /
    discard_post / remove_post / set_thread_pinned /
    set_thread_locked / wipe_posts_from_user — the queue.
  - delete_thread — the ADMIN-tier hard delete (operators +
    community admins only; plain moderators never see it).
  - create_category / update_category — operator furniture.
  - export_rows(db, owner_id) — the data export's forum.json.
  - tombstone_author(db, user_id) — the account-deletion seam.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.forum import models

FORUM_ENABLED_KEY = "community.forum_enabled"

# The exact public payload contracts (see the serializers).
CATEGORY_KEYS = (
    "id",
    "name",
    "description",
    "sort_order",
    "is_active",
    "system_key",
    "thread_count",
    "post_count",
    "last_thread_id",
    "last_thread_title",
    "last_activity_at",
)

# Built-in rooms (migration 0070): the system seeds these rows
# and every consumer finds them by key, never by a hard-coded
# id. site_help is the dedicated "using Toolbox Vault" room the
# Help & Support page's community tab embeds. The other two are
# the PERMANENT boards (owner directive 2026-11-02): the Bug
# Reports and Feature Requests boards are fixtures of the
# forum — the board rows themselves can never be deleted or
# edited by anyone (update_category refuses them outright, and
# no delete route exists for categories at all). Their POSTS
# stay powered by the feedback module — statuses, votes,
# comments, moderation and the roadmap tie-in are the boards'
# approved mechanics, unchanged; the feedback board name each
# system key presents is BOARD_FEEDBACK_NAMES.
SYSTEM_KEY_SITE_HELP = "site_help"
SYSTEM_KEY_BUG_BOARD = "bug_reports"
SYSTEM_KEY_FEATURE_BOARD = "feature_requests"
PERMANENT_BOARD_KEYS = (SYSTEM_KEY_BUG_BOARD, SYSTEM_KEY_FEATURE_BOARD)

# Board-list order (owner 2026-11-06): Bug Reports first,
# Feature Requests second, General third, then every other
# room in its operator order. The boards pin by system key.
# The General room carries no system key — it is the room
# migration 0034 seeded, found by its fixed seed id (the same
# fixed-id doctrine the seed itself uses; a rename can't move
# it, and if the room is ever archived or deleted there is
# simply no General to rank). list_categories applies this
# rank over the operator's (sort_order, name); the operator's
# own management list (list_all_categories) keeps the raw
# order — this is a reading-surface rule, not a data rewrite.
GENERAL_CATEGORY_ID = uuid.UUID("0f0e0d0c-0001-4000-8000-000000000001")
_BOARD_RANK = {SYSTEM_KEY_BUG_BOARD: 0, SYSTEM_KEY_FEATURE_BOARD: 1}


def _board_rank(row: models.ForumCategory) -> int:
    if row.system_key in _BOARD_RANK:
        return _BOARD_RANK[row.system_key]
    if row.id == GENERAL_CATEGORY_ID:
        return 2
    return 3
BOARD_FEEDBACK_NAMES = {
    SYSTEM_KEY_BUG_BOARD: "bug",
    SYSTEM_KEY_FEATURE_BOARD: "feature",
}
AUTHOR_KEYS = (
    "user_id",
    "display_name",
    "account_number",
    "member_since",
    "role",
    "reputation",
)
THREAD_KEYS = (
    "id",
    "category_id",
    "title",
    "author",
    "pinned",
    "locked",
    "held",
    "reply_count",
    "post_count",
    "excerpt",
    "created_at",
    "last_post_at",
)
POST_KEYS = (
    "id",
    "thread_id",
    "author",
    "body",
    "status",
    "removed_by",
    "is_opener",
    "quote",
    "link",
    "flags",
    "edited_at",
    "created_at",
    "mine",
)
LINK_CARD_KEYS = ("type", "id", "title", "price", "photo_url", "available")

_EXCERPT_CHARS = 240
_QUOTE_CHARS = 280
_THREAD_CAP = 100
_POST_CAP = 500

FORMER_MEMBER = "Former member"


class ForumError(ValueError):
    """Friendly refusal. Routes -> 422."""


class ForumNotFound(ForumError):
    """Missing OR not visible to you — ids never leak. -> 404."""


class RateLimited(ForumError):
    """The firewall's posting budget is spent. -> 429."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# -- switches + the posting gate ------------------------------------------------


def forum_enabled(db: Session) -> bool:
    """The forum's master switch: the operator's community
    setting AND the module's global switch (either off hides the
    forum entirely — the pool/board posture)."""
    from app.modules.billing import entitlements
    from app.modules.core import module_control

    if not module_control.globally_enabled(db, "forum"):
        return False
    return bool(entitlements.get_setting(db, FORUM_ENABLED_KEY, True))


def can_post(db: Session, user_id: uuid.UUID) -> bool:
    """May this account contribute RIGHT NOW? The suite's one
    rule, read from the marketplace copy (which states the pool's
    rule verbatim): enforcement OFF → everyone; ON → paid plan,
    trial never counts."""
    from app.modules.marketplace import service as marketplace_service

    return marketplace_service.can_publish(db, user_id)


def _require_not_blocked(db: Session, user_id: uuid.UUID) -> None:
    """The community-block door (admin lane, owner ruling
    2026-11-06): a member blocked from the forums by a god /
    moderator_admin seat can't start threads or reply — the
    refusal carries the plain-words reason and the support-
    ticket road back (forum.blocks owns the copy)."""
    from app.modules.forum import blocks as community_blocks

    try:
        community_blocks.require_not_blocked(db, user_id, "forums")
    except community_blocks.BlockError as exc:
        raise ForumError(str(exc)) from exc


# -- authors ----------------------------------------------------------------------


def author_block(
    db: Session, user_id: uuid.UUID, *, gone: bool = False
) -> dict:
    """The public author identity: display name, account number,
    member since, role-ladder role, and the reputation summary
    from the ONE aggregate function. A deleted account renders as
    Former member with an empty identity — never an error, never
    a stale name."""
    from app.modules.marketplace import reputation

    user = None if gone else core_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        return {
            "user_id": user_id,
            "display_name": FORMER_MEMBER,
            "account_number": "",
            "member_since": None,
            "role": "user",
            "reputation": {"average": None, "count": 0, "completed_deals": 0},
        }
    return {
        "user_id": user.id,
        "display_name": user.name,
        "account_number": user.account_number,
        "member_since": user.created_at,
        "role": user.role or "user",
        "reputation": reputation.summary_for(db, user.id),
    }


# -- lookups ------------------------------------------------------------------------


def get_category(db: Session, category_id: uuid.UUID) -> models.ForumCategory | None:
    return db.get(models.ForumCategory, category_id)


def get_thread(db: Session, thread_id: uuid.UUID) -> models.ForumThread | None:
    return db.get(models.ForumThread, thread_id)


def get_post(db: Session, post_id: uuid.UUID) -> models.ForumPost | None:
    return db.get(models.ForumPost, post_id)


def _opener(db: Session, thread_id: uuid.UUID) -> models.ForumPost | None:
    return db.scalars(
        select(models.ForumPost)
        .where(models.ForumPost.thread_id == thread_id)
        .order_by(models.ForumPost.created_at, models.ForumPost.id)
        .limit(1)
    ).first()


def _thread_posts(db: Session, thread_id: uuid.UUID) -> list[models.ForumPost]:
    return list(
        db.scalars(
            select(models.ForumPost)
            .where(models.ForumPost.thread_id == thread_id)
            .order_by(models.ForumPost.created_at, models.ForumPost.id)
        ).all()
    )


def _can_see_thread(
    thread: models.ForumThread,
    viewer_id: uuid.UUID | None,
    viewer_is_mod: bool,
) -> bool:
    if not thread.held:
        return True
    return viewer_is_mod or viewer_id == thread.author_id


def _post_visible_to(
    post: models.ForumPost,
    viewer_id: uuid.UUID | None,
    viewer_is_mod: bool,
) -> bool:
    """Held posts are the only ones ever hidden outright —
    removed posts stay as tombstones so threads keep their
    shape. A held post reads only for its author + moderators."""
    if post.status != "held":
        return True
    return viewer_is_mod or viewer_id == post.author_id


# -- link cards ---------------------------------------------------------------------


def _resolve_link(
    db: Session, link_type: str, link_id: uuid.UUID | None
) -> tuple[str, object | None]:
    """Post-time validation through the OWNING module's service
    interface (the messaging-anchor pattern): the target must be
    a LIVE public listing/part right now. Returns (title, card
    source) or raises ForumError."""
    from app.modules.marketplace import service as marketplace_service
    from app.modules.parts import pool as parts_pool

    if link_type == "listing":
        listing = marketplace_service.get_public_listing(db, link_id)
        if listing is None:
            raise ForumError(
                "That listing isn't public right now — it may have "
                "sold or been removed."
            )
        return listing.title, listing
    part = parts_pool.get_public_listing_part(db, link_id)
    if part is None:
        raise ForumError(
            "That part isn't public right now — it may have been "
            "unlisted or removed."
        )
    return part[0].title, part


def link_card(db: Session, post: models.ForumPost) -> dict | None:
    """The attached reference, resolved LIVE at read time: a
    live target renders its current title/price/photo; a dead
    one renders the honest unavailable card with the title the
    post snapshotted — never a dangling id, never an error."""
    if not post.link_type or post.link_id is None:
        return None
    from app.modules.marketplace import service as marketplace_service
    from app.modules.parts import pool as parts_pool

    title = post.link_title
    price = None
    seller_currency = None
    photo_url = None
    available = False
    if post.link_type == "listing":
        listing = marketplace_service.get_public_listing(db, post.link_id)
        if listing is not None:
            seller = core_service.get_user_by_id(db, listing.owner_id)
            if seller is not None:
                view = marketplace_service.serialize_public(db, listing, seller)
                title = view["title"]
                price = view["price"]
                # Wave 3 currency: the price is in the SELLER's
                # currency; the card labels + hints from this code,
                # exactly like the board the listing lives on.
                seller_currency = view["seller_currency"]
                photos = view["photos"]
                photo_url = photos[0]["url"] if photos else None
                available = True
    else:
        found = parts_pool.get_public_listing_part(db, post.link_id)
        if found is not None:
            part, settings = found
            seller = core_service.get_user_by_id(db, part.owner_id)
            if seller is not None:
                view = parts_pool.serialize_listing(part, seller, settings)
                title = view["title"]
                price = view["asking_price"]
                seller_currency = view["seller_currency"]
                photos = view["photos"]
                photo_url = photos[0]["url"] if photos else None
                available = True
    return {
        "type": post.link_type,
        "id": post.link_id,
        "title": title,
        "price": price,
        "seller_currency": seller_currency,
        "photo_url": photo_url,
        "available": available,
    }


# -- serializers ----------------------------------------------------------------------


def _board_counts(
    db: Session, board: str, *, include_held: bool = False
) -> tuple[int, int, object | None]:
    """A permanent board's live counts, read from the feedback
    engine that powers its posts: thread_count = its posts,
    post_count = posts + comments, latest = the newest post
    (its id/title/activity ride the category payload's
    last_thread_* fields, which the frontend links to the
    post's own page for board rows)."""
    from app.modules.feedback import models as feedback_models

    visibilities = ["visible", "held"] if include_held else ["visible"]
    post_count_rows = int(
        db.scalar(
            select(func.count(feedback_models.FeedbackPost.id)).where(
                feedback_models.FeedbackPost.board == board,
                feedback_models.FeedbackPost.visibility.in_(visibilities),
            )
        )
        or 0
    )
    comment_rows = int(
        db.scalar(
            select(func.count(feedback_models.FeedbackComment.id))
            .join(
                feedback_models.FeedbackPost,
                feedback_models.FeedbackPost.id
                == feedback_models.FeedbackComment.post_id,
            )
            .where(
                feedback_models.FeedbackPost.board == board,
                feedback_models.FeedbackComment.visibility.in_(visibilities),
            )
        )
        or 0
    )
    latest = db.scalars(
        select(feedback_models.FeedbackPost)
        .where(
            feedback_models.FeedbackPost.board == board,
            feedback_models.FeedbackPost.visibility.in_(visibilities),
        )
        .order_by(feedback_models.FeedbackPost.created_at.desc())
        .limit(1)
    ).first()
    return post_count_rows, post_count_rows + comment_rows, latest


def serialize_category(
    db: Session,
    category: models.ForumCategory,
    *,
    include_held: bool = False,
    anonymous: bool = False,
) -> dict:
    thread_stmt = select(func.count(models.ForumThread.id)).where(
        models.ForumThread.category_id == category.id
    )
    if not include_held:
        thread_stmt = thread_stmt.where(models.ForumThread.held.is_(False))
    thread_count = int(db.scalar(thread_stmt) or 0)
    post_count = int(
        db.scalar(
            select(func.count(models.ForumPost.id))
            .join(
                models.ForumThread,
                models.ForumThread.id == models.ForumPost.thread_id,
            )
            .where(
                models.ForumThread.category_id == category.id,
                models.ForumPost.status == "visible",
            )
        )
        or 0
    )
    latest_stmt = (
        select(models.ForumThread)
        .where(models.ForumThread.category_id == category.id)
        .order_by(models.ForumThread.last_post_at.desc())
    )
    if not include_held:
        latest_stmt = latest_stmt.where(models.ForumThread.held.is_(False))
    latest = db.scalars(latest_stmt.limit(1)).first()
    last_id = latest.id if latest else None
    last_title = latest.title if latest else None
    last_at = latest.last_post_at if latest else None
    board = BOARD_FEEDBACK_NAMES.get(category.system_key or "")
    if board is not None and anonymous:
        # Members-only boards (owner 2026-11-10): an anonymous
        # audience gets the board's NAME and description — the
        # fixtures are public knowledge — but none of the
        # boards' content signals: no counts, no latest-post
        # title or activity. The row reads exactly like a board
        # with nothing on it yet.
        thread_count, post_count = 0, 0
        last_id = last_title = last_at = None
    elif board is not None:
        # A permanent board carries no forum threads of its own:
        # its counts and latest activity are the feedback posts'.
        thread_count, post_count, fb_latest = _board_counts(
            db, board, include_held=include_held
        )
        last_id = fb_latest.id if fb_latest else None
        last_title = fb_latest.title if fb_latest else None
        last_at = fb_latest.created_at if fb_latest else None
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "sort_order": category.sort_order,
        "is_active": category.is_active,
        "system_key": category.system_key,
        "thread_count": thread_count,
        "post_count": post_count,
        "last_thread_id": last_id,
        "last_thread_title": last_title,
        "last_activity_at": last_at,
    }


def serialize_thread(
    db: Session,
    thread: models.ForumThread,
    viewer_id: uuid.UUID | None,
    *,
    viewer_is_mod: bool = False,
) -> dict:
    posts = _thread_posts(db, thread.id)
    visible = [
        p for p in posts if _post_visible_to(p, viewer_id, viewer_is_mod)
    ]
    opener = posts[0] if posts else None
    live = [p for p in visible if p.status == "visible"]
    excerpt = ""
    if opener is not None and opener.status == "visible":
        excerpt = opener.body[:_EXCERPT_CHARS]
    return {
        "id": thread.id,
        "category_id": thread.category_id,
        "title": thread.title,
        "author": author_block(db, thread.author_id, gone=thread.author_gone),
        "pinned": thread.pinned,
        "locked": thread.locked,
        "held": thread.held,
        "reply_count": max(0, len(live) - 1),
        "post_count": len(live),
        "excerpt": excerpt,
        "created_at": thread.created_at,
        "last_post_at": thread.last_post_at,
    }


def serialize_post(
    db: Session,
    post: models.ForumPost,
    viewer_id: uuid.UUID | None,
    *,
    viewer_is_mod: bool = False,
    mod_detail: bool = False,
    opener_id: uuid.UUID | None = None,
) -> dict:
    removed = post.status in ("removed_author", "removed_mod")
    mine = viewer_id is not None and viewer_id == post.author_id
    show_flags = viewer_is_mod or mine
    quote = None
    if post.quote_post_id is not None:
        quote = {
            "author_name": post.quote_author_name,
            "excerpt": post.quote_excerpt,
        }
    return {
        "id": post.id,
        "thread_id": post.thread_id,
        "author": author_block(db, post.author_id, gone=post.author_gone),
        # Removed bodies blank on the reading surfaces for
        # everyone; only the moderator's thread view (mod_detail)
        # shows true state, the messaging queue's posture.
        "body": post.body if (not removed or mod_detail) else "",
        "status": (
            "removed" if removed else post.status
        ),
        "removed_by": (
            "author"
            if post.status == "removed_author"
            else "moderator"
            if post.status == "removed_mod"
            else None
        ),
        "is_opener": opener_id is not None and post.id == opener_id,
        "quote": quote,
        "link": None if removed else link_card(db, post),
        "flags": (
            [f for f in post.flags.split(",") if f] if show_flags else []
        ),
        "edited_at": post.edited_at,
        "created_at": post.created_at,
        "mine": mine,
    }


# -- public reads ---------------------------------------------------------------------


def list_categories(
    db: Session, *, viewer_is_mod: bool = False, anonymous: bool = False
) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumCategory)
            .where(models.ForumCategory.is_active.is_(True))
            .order_by(
                models.ForumCategory.sort_order, models.ForumCategory.name
            )
        ).all()
    )
    if any(row.system_key in BOARD_FEEDBACK_NAMES for row in rows):
        # The permanent boards are powered by the feedback
        # module: while that module is globally off, the boards
        # leave the board list too (their tabs on Help & Support
        # follow the same switch) — never a listed door onto a
        # switched-off area. The operator's full list
        # (list_all_categories) keeps every row regardless.
        from app.modules.core import module_control

        if not module_control.globally_enabled(db, "feedback"):
            rows = [
                row for row in rows if row.system_key not in BOARD_FEEDBACK_NAMES
            ]
    # The owner's board order rides over the operator order
    # (stable sort: within a rank, (sort_order, name) from the
    # query stands). Every board list reads through here —
    # the forum index, the Help community tab's room lookup,
    # the public twin — so the order holds everywhere at once.
    rows.sort(key=_board_rank)
    return [
        serialize_category(
            db, row, include_held=viewer_is_mod, anonymous=anonymous
        )
        for row in rows
    ]


def list_threads(
    db: Session,
    category_id: uuid.UUID,
    viewer_id: uuid.UUID | None,
    *,
    viewer_is_mod: bool = False,
    limit: int = _THREAD_CAP,
    offset: int = 0,
) -> list[dict]:
    category = get_category(db, category_id)
    if category is None or not category.is_active:
        raise ForumNotFound("That category isn't available.")
    if category.system_key in BOARD_FEEDBACK_NAMES:
        # A permanent board's posts live on the board's own
        # pages (the feedback engine), never as forum threads.
        raise ForumNotFound("That board lives on its own page.")
    rows = list(
        db.scalars(
            select(models.ForumThread)
            .where(models.ForumThread.category_id == category_id)
            .order_by(
                models.ForumThread.pinned.desc(),
                models.ForumThread.last_post_at.desc(),
            )
        ).all()
    )
    visible = [
        t for t in rows if _can_see_thread(t, viewer_id, viewer_is_mod)
    ]
    cap = max(1, min(limit, _THREAD_CAP))
    return [
        serialize_thread(db, t, viewer_id, viewer_is_mod=viewer_is_mod)
        for t in visible[offset : offset + cap]
    ]


def thread_view(
    db: Session,
    thread_id: uuid.UUID,
    viewer_id: uuid.UUID | None,
    *,
    viewer_is_mod: bool = False,
) -> dict:
    thread = get_thread(db, thread_id)
    if thread is None or not _can_see_thread(thread, viewer_id, viewer_is_mod):
        raise ForumNotFound("That thread isn't available.")
    category = get_category(db, thread.category_id)
    if category is None or not category.is_active:
        raise ForumNotFound("That thread isn't available.")
    posts = _thread_posts(db, thread.id)
    opener_id = posts[0].id if posts else None
    view = serialize_thread(db, thread, viewer_id, viewer_is_mod=viewer_is_mod)
    view["posts"] = [
        serialize_post(
            db, p, viewer_id, viewer_is_mod=viewer_is_mod, opener_id=opener_id
        )
        for p in posts
        if _post_visible_to(p, viewer_id, viewer_is_mod)
    ]
    return view


def search_threads(
    db: Session,
    q: str,
    viewer_id: uuid.UUID | None,
    *,
    viewer_is_mod: bool = False,
    limit: int = _THREAD_CAP,
) -> list[dict]:
    """Forum-wide search over thread titles + visible post
    bodies. Held threads/posts never match for the public."""
    needle = (q or "").strip()
    if not needle:
        return []
    like = f"%{needle}%"
    title_hits = list(
        db.scalars(
            select(models.ForumThread).where(
                models.ForumThread.title.ilike(like)
            )
        ).all()
    )
    body_hits = list(
        db.scalars(
            select(models.ForumThread)
            .join(models.ForumPost, models.ForumPost.thread_id == models.ForumThread.id)
            .where(
                models.ForumPost.body.ilike(like),
                models.ForumPost.status == "visible",
            )
            .distinct()
        ).all()
    )
    by_id: dict[uuid.UUID, models.ForumThread] = {}
    for thread in [*title_hits, *body_hits]:
        if not _can_see_thread(thread, viewer_id, viewer_is_mod):
            continue
        category = get_category(db, thread.category_id)
        if category is None or not category.is_active:
            continue
        by_id[thread.id] = thread
    rows = sorted(
        by_id.values(),
        key=lambda t: _aware(t.last_post_at) or _now(),
        reverse=True,
    )
    cap = max(1, min(limit, _THREAD_CAP))
    return [
        serialize_thread(db, t, viewer_id, viewer_is_mod=viewer_is_mod)
        for t in rows[:cap]
    ]


# -- posting -------------------------------------------------------------------------


def _check_thread_budget(db: Session, user) -> None:
    from app.modules.messaging import spam

    caps = spam.tier_caps(db, user)
    now = _now()
    base = select(func.count(models.ForumThread.id)).where(
        models.ForumThread.author_id == user.id
    )
    hour = int(
        db.scalar(base.where(models.ForumThread.created_at >= now - timedelta(hours=1)))
        or 0
    )
    if hour >= caps["new_threads_per_hour"]:
        _raise_budget(
            "You're starting threads too quickly — please wait a bit "
            "before opening another."
        )
    day = int(
        db.scalar(base.where(models.ForumThread.created_at >= now - timedelta(days=1)))
        or 0
    )
    if day >= caps["new_threads_per_day"]:
        _raise_budget(
            "You've reached today's limit for new threads. It resets "
            "tomorrow."
        )


def _check_post_budget(db: Session, user) -> None:
    from app.modules.messaging import spam

    caps = spam.tier_caps(db, user)
    now = _now()
    base = select(func.count(models.ForumPost.id)).where(
        models.ForumPost.author_id == user.id,
        models.ForumPost.status != "removed_mod",
    )
    hour = int(
        db.scalar(base.where(models.ForumPost.created_at >= now - timedelta(hours=1)))
        or 0
    )
    if hour >= caps["messages_per_hour"]:
        _raise_budget(
            "You're posting too quickly — please slow down a little."
        )
    day = int(
        db.scalar(base.where(models.ForumPost.created_at >= now - timedelta(days=1)))
        or 0
    )
    if day >= caps["messages_per_day"]:
        _raise_budget("You've reached today's post limit. It resets tomorrow.")


def _raise_budget(message: str) -> None:
    raise RateLimited(message)


def _screen(db: Session, author_id: uuid.UUID, *bodies: str) -> tuple[str, list[str]]:
    """The firewall's content screen over the given bodies
    (title + body for a new thread). No recipient — the blast
    check is a messaging shape; the forum's volume brake is the
    tier budget above."""
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


def create_thread(
    db: Session,
    user,
    *,
    category_id: uuid.UUID,
    title: str,
    body: str,
    link_type: str = "",
    link_id: uuid.UUID | None = None,
) -> dict:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise ForumError("Give your thread a title.")
    if not body:
        raise ForumError("Write something for the opening post.")
    _require_not_blocked(db, user.id)
    category = get_category(db, category_id)
    if category is None:
        raise ForumNotFound("That category isn't available.")
    if category.system_key in BOARD_FEEDBACK_NAMES:
        # The permanent boards take posts through the feedback
        # boards, not as forum threads (their one write door).
        raise ForumError(
            "That board takes posts on its own page — "
            "this room can't hold forum threads."
        )
    if not category.is_active:
        raise ForumError("That category is archived — pick another one.")
    if link_type and link_type not in models.LINK_TYPES:
        raise ForumError("That kind of link can't be attached.")
    link_title = ""
    if link_type:
        link_title, _ = _resolve_link(db, link_type, link_id)
    _check_thread_budget(db, user)
    status, flags = _screen(db, user.id, title, body)
    thread = models.ForumThread(
        category_id=category.id,
        author_id=user.id,
        title=title[:300],
        held=status == "held",
        last_post_at=_now(),
    )
    db.add(thread)
    db.flush()
    post = models.ForumPost(
        thread_id=thread.id,
        author_id=user.id,
        body=body,
        status="held" if status == "held" else "visible",
        flags=",".join(flags),
        link_type=link_type if link_type else "",
        link_id=link_id if link_type else None,
        link_title=link_title,
    )
    db.add(post)
    db.flush()
    thread.last_post_id = post.id
    thread.updated_at = _now()
    db.commit()
    db.refresh(thread)
    return thread_view(db, thread.id, user.id)


def _notify_reply(
    db: Session, thread: models.ForumThread, replier, post: models.ForumPost
) -> None:
    """One inbox note to the thread's author for a reply — the
    FIRST unread only (the message_received pattern): while an
    earlier forum_reply note for this thread sits unread, later
    replies stay quiet. Built inside the caller's transaction."""
    if thread.author_id == replier.id or thread.author_gone:
        return
    author = core_service.get_user_by_id(db, thread.author_id)
    if author is None or not author.is_active:
        return
    unread = list(
        db.scalars(
            select(core_models.Notification)
            .where(
                core_models.Notification.user_id == thread.author_id,
                core_models.Notification.kind == inbox.KIND_FORUM_REPLY,
                core_models.Notification.read_at.is_(None),
            )
            .order_by(core_models.Notification.created_at.desc())
            .limit(50)
        ).all()
    )
    for note in unread:
        if (note.data or {}).get("thread_id") == str(thread.id):
            return
    inbox.create_notification(
        db,
        thread.author_id,
        kind=inbox.KIND_FORUM_REPLY,
        title="New reply to your thread",
        body=f"{replier.name} replied to “{thread.title}”.",
        data={"thread_id": str(thread.id), "post_id": str(post.id)},
        commit=False,
    )


def create_reply(
    db: Session,
    user,
    *,
    thread_id: uuid.UUID,
    body: str,
    quote_post_id: uuid.UUID | None = None,
    link_type: str = "",
    link_id: uuid.UUID | None = None,
) -> dict:
    body = (body or "").strip()
    if not body:
        raise ForumError("Write something for your reply.")
    _require_not_blocked(db, user.id)
    thread = get_thread(db, thread_id)
    if thread is None or thread.held:
        raise ForumNotFound("That thread isn't available.")
    category = get_category(db, thread.category_id)
    if category is None or not category.is_active:
        raise ForumNotFound("That thread isn't available.")
    if thread.locked:
        raise ForumError(
            "This thread is locked — it can be read, but no new "
            "replies can be posted."
        )
    quote_name = ""
    quote_excerpt = ""
    if quote_post_id is not None:
        quoted = get_post(db, quote_post_id)
        if (
            quoted is None
            or quoted.thread_id != thread.id
            or quoted.status != "visible"
        ):
            raise ForumError("That post can't be quoted.")
        quote_name = author_block(db, quoted.author_id, gone=quoted.author_gone)[
            "display_name"
        ]
        quote_excerpt = quoted.body[:_QUOTE_CHARS]
    if link_type and link_type not in models.LINK_TYPES:
        raise ForumError("That kind of link can't be attached.")
    link_title = ""
    if link_type:
        link_title, _ = _resolve_link(db, link_type, link_id)
    _check_post_budget(db, user)
    status, flags = _screen(db, user.id, body)
    post = models.ForumPost(
        thread_id=thread.id,
        author_id=user.id,
        body=body,
        status="held" if status == "held" else "visible",
        flags=",".join(flags),
        quote_post_id=quote_post_id,
        quote_author_name=quote_name,
        quote_excerpt=quote_excerpt,
        link_type=link_type if link_type else "",
        link_id=link_id if link_type else None,
        link_title=link_title,
    )
    db.add(post)
    db.flush()
    if post.status == "visible":
        thread.last_post_at = _now()
        thread.last_post_id = post.id
        thread.updated_at = _now()
        _notify_reply(db, thread, user, post)
    db.commit()
    db.refresh(post)
    return serialize_post(
        db, post, user.id, opener_id=_opener(db, thread.id).id
    )


def edit_post(db: Session, user, *, post_id: uuid.UUID, body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise ForumError("A post can't be empty.")
    post = get_post(db, post_id)
    if post is None or post.author_id != user.id:
        raise ForumNotFound("That post isn't available.")
    if post.status in ("removed_author", "removed_mod"):
        raise ForumError("A removed post can't be edited.")
    if post.status == "held":
        raise ForumError(
            "That post is waiting for moderation — it can't be "
            "edited until it's released."
        )
    # An edit re-runs the screen on the new body: editing spam
    # INTO a clean post must not dodge the firewall.
    status, flags = _screen(db, user.id, body)
    if status == "held":
        post.status = "held"
        thread = get_thread(db, post.thread_id)
        opener = _opener(db, post.thread_id)
        if thread is not None and opener is not None and opener.id == post.id:
            thread.held = True
    post.body = body
    post.flags = ",".join(flags)
    post.edited_at = _now()
    post.updated_at = _now()
    db.commit()
    db.refresh(post)
    return serialize_post(
        db, post, user.id, opener_id=_opener(db, post.thread_id).id
    )


def delete_post(db: Session, user, *, post_id: uuid.UUID) -> dict:
    """The author's own delete: a soft tombstone — the thread
    keeps its shape and the replies under it keep their context."""
    post = get_post(db, post_id)
    if post is None or post.author_id != user.id:
        raise ForumNotFound("That post isn't available.")
    if post.status in ("removed_author", "removed_mod"):
        raise ForumError("That post is already removed.")
    post.status = "removed_author"
    post.updated_at = _now()
    db.commit()
    db.refresh(post)
    return serialize_post(
        db, post, user.id, opener_id=_opener(db, post.thread_id).id
    )


def my_posts(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumPost)
            .where(models.ForumPost.author_id == user_id)
            .order_by(models.ForumPost.created_at.desc())
            .limit(_POST_CAP)
        ).all()
    )
    return [
        serialize_post(db, p, user_id, opener_id=_opener(db, p.thread_id).id)
        for p in rows
    ]


def my_threads(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumThread)
            .where(models.ForumThread.author_id == user_id)
            .order_by(models.ForumThread.last_post_at.desc())
            .limit(_THREAD_CAP)
        ).all()
    )
    return [serialize_thread(db, t, user_id) for t in rows]


# -- favorites (widget options Wave 3) --------------------------------------------------
#
# A member's starred conversations (owner design 2026-11-02,
# Decision 2 — favorites as a real forum feature). PRIVATE by
# construction: every function here is keyed to ONE member's own
# rows; there is no other reader, no counts, no public display.
#
# A favorite resolves LIVE at read time, through the exact
# visibility rules of the surface it points at: a thread through
# thread_view's rules (exists, not held for this viewer, its
# category still active), a board post through the feedback
# read path's rules (the feedback module globally on, the post
# exists, held only for its author + moderators; removed posts
# still resolve — their pages render as tombstones carrying the
# title, like everywhere else). A target that fails its rules
# drops out of the list SILENTLY — never an error, never a stale
# title. The row itself is kept, so if the door reopens (a board
# switched back on, a held thread released) the star is still
# there, the link-card doctrine applied to a whole conversation.

_BOARD_CATEGORY_KEYS = {name: key for key, name in BOARD_FEEDBACK_NAMES.items()}
_BOARD_FALLBACK_NAMES = {"bug": "Bug Reports", "feature": "Feature Requests"}


def _favorite_thread_view(
    db: Session,
    fav: models.ForumFavorite,
    viewer_is_mod: bool,
) -> dict | None:
    thread = get_thread(db, fav.target_id)
    if thread is None or not _can_see_thread(thread, fav.user_id, viewer_is_mod):
        return None
    category = get_category(db, thread.category_id)
    if category is None or not category.is_active:
        return None
    view = serialize_thread(db, thread, fav.user_id, viewer_is_mod=viewer_is_mod)
    return {
        "kind": "thread",
        "target_id": thread.id,
        "title": thread.title,
        "board_name": category.name,
        "reply_count": view["reply_count"],
        "last_activity_at": thread.last_post_at,
        "starred_at": fav.created_at,
    }


def _favorite_post_view(
    db: Session,
    fav: models.ForumFavorite,
    viewer_is_mod: bool,
) -> dict | None:
    from app.modules.core import module_control
    from app.modules.feedback import models as feedback_models

    # The boards' posts live behind the feedback module's own
    # switch (its read path 404s while globally off — the same
    # rule list_categories applies to the board rows themselves).
    if not module_control.globally_enabled(db, "feedback"):
        return None
    post = db.get(feedback_models.FeedbackPost, fav.target_id)
    if post is None:
        return None
    # The feedback read path's visibility rule, restated (the
    # forum never imports another module's service internals):
    # held posts read only for their author + moderators;
    # everything else (removed tombstones included) reads.
    if post.visibility == "held" and not (
        viewer_is_mod or post.author_id == fav.user_id
    ):
        return None
    visible_comments = (
        select(feedback_models.FeedbackComment)
        .where(
            feedback_models.FeedbackComment.post_id == post.id,
            feedback_models.FeedbackComment.visibility == "visible",
        )
        .order_by(feedback_models.FeedbackComment.created_at.desc())
    )
    comment_count = int(
        db.scalar(
            select(func.count(feedback_models.FeedbackComment.id)).where(
                feedback_models.FeedbackComment.post_id == post.id,
                feedback_models.FeedbackComment.visibility == "visible",
            )
        )
        or 0
    )
    latest_comment = db.scalars(visible_comments.limit(1)).first()
    last_activity = post.created_at
    if latest_comment is not None and (
        _aware(latest_comment.created_at) or _now()
    ) > (_aware(last_activity) or _now()):
        last_activity = latest_comment.created_at
    category = db.scalars(
        select(models.ForumCategory).where(
            models.ForumCategory.system_key
            == _BOARD_CATEGORY_KEYS.get(post.board, "")
        )
    ).first()
    return {
        "kind": "post",
        "target_id": post.id,
        "title": post.title,
        "board_name": (
            category.name
            if category is not None
            else _BOARD_FALLBACK_NAMES.get(post.board, "Feedback")
        ),
        "reply_count": comment_count,
        "last_activity_at": last_activity,
        "starred_at": fav.created_at,
    }


def _resolve_favorite(
    db: Session,
    fav: models.ForumFavorite,
    viewer_is_mod: bool,
) -> dict | None:
    if fav.kind == "thread":
        return _favorite_thread_view(db, fav, viewer_is_mod)
    if fav.kind == "post":
        return _favorite_post_view(db, fav, viewer_is_mod)
    return None


def list_favorites(
    db: Session, user_id: uuid.UUID, *, viewer_is_mod: bool = False
) -> list[dict]:
    """The member's favorites, resolved live, most recent
    activity first (the widget's featured default: the favorite
    that moved most recently). Invisible targets are absent —
    see the section note above."""
    rows = list(
        db.scalars(
            select(models.ForumFavorite).where(
                models.ForumFavorite.user_id == user_id
            )
        ).all()
    )
    views = [
        view
        for fav in rows
        if (view := _resolve_favorite(db, fav, viewer_is_mod)) is not None
    ]
    views.sort(
        key=lambda v: _aware(v["last_activity_at"]) or _now(), reverse=True
    )
    return views


def star_favorite(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    target_id: uuid.UUID,
    viewer_is_mod: bool = False,
) -> dict:
    """Star a conversation. The target must be visible to the
    member RIGHT NOW under the same rules the reads apply —
    anything else is the surface's own 404 (ids never leak).
    Starring twice is the same star (the unique row stands)."""
    if kind not in models.FAVORITE_KINDS:
        raise ForumError("Favorites point at a thread or a board post.")
    existing = db.scalars(
        select(models.ForumFavorite).where(
            models.ForumFavorite.user_id == user_id,
            models.ForumFavorite.kind == kind,
            models.ForumFavorite.target_id == target_id,
        )
    ).first()
    fav = existing
    if fav is None:
        fav = models.ForumFavorite(
            user_id=user_id, kind=kind, target_id=target_id
        )
        view = _resolve_favorite(db, fav, viewer_is_mod)
        if view is None:
            raise ForumNotFound(
                "That thread isn't available."
                if kind == "thread"
                else "That post isn't available."
            )
        db.add(fav)
        db.commit()
        db.refresh(fav)
        return _resolve_favorite(db, fav, viewer_is_mod) or view
    view = _resolve_favorite(db, fav, viewer_is_mod)
    if view is None:
        raise ForumNotFound(
            "That thread isn't available."
            if kind == "thread"
            else "That post isn't available."
        )
    return view


def unstar_favorite(
    db: Session, user_id: uuid.UUID, *, kind: str, target_id: uuid.UUID
) -> None:
    """Unstar — idempotent on purpose (a toggle racing itself
    must never error): no row is a successful no-op."""
    if kind not in models.FAVORITE_KINDS:
        raise ForumError("Favorites point at a thread or a board post.")
    db.query(models.ForumFavorite).filter(
        models.ForumFavorite.user_id == user_id,
        models.ForumFavorite.kind == kind,
        models.ForumFavorite.target_id == target_id,
    ).delete(synchronize_session=False)
    db.commit()


# -- reports + moderation --------------------------------------------------------------


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


def report_post(db: Session, user, *, post_id: uuid.UUID, reason: str) -> dict:
    post = get_post(db, post_id)
    if post is None or post.status == "held":
        raise ForumNotFound("That post isn't available.")
    if post.status in ("removed_author", "removed_mod"):
        raise ForumError("That post has already been removed.")
    existing = db.scalars(
        select(models.ForumReport).where(
            models.ForumReport.post_id == post.id,
            models.ForumReport.reporter_id == user.id,
            models.ForumReport.status == "open",
        )
    ).first()
    if existing is not None:
        raise ForumError(
            "You've already reported this post — it's in the "
            "moderation queue."
        )
    row = models.ForumReport(
        post_id=post.id,
        thread_id=post.thread_id,
        reporter_id=user.id,
        reason=(reason or "").strip()[:500],
    )
    db.add(row)
    db.flush()
    # A flag tells the whole moderation team (admin lane, owner
    # ruling 2026-11-06: moderators, moderator admins AND god)
    # — in the flag's own commit, so the note can never announce
    # a flag that didn't land.
    from app.modules.core import inbox

    thread = get_thread(db, post.thread_id)
    inbox.notify_moderation_team(
        db,
        kind=inbox.KIND_COMMUNITY_FLAG,
        title="New flag: forum post",
        body=(
            f"{user.name} flagged a post in "
            f"“{thread.title if thread is not None else ''}”: "
            f"{row.reason or 'no notes given'}"
        ),
        data={
            "surface": "forum",
            "report_id": str(row.id),
            "post_id": str(post.id),
            "thread_id": str(post.thread_id),
        },
        exclude_id=user.id,
    )
    db.commit()
    db.refresh(row)
    return _report_view(db, row)


def _report_view(db: Session, row: models.ForumReport) -> dict:
    post = get_post(db, row.post_id)
    thread = get_thread(db, row.thread_id)
    reporter = core_service.get_user_by_id(db, row.reporter_id)
    return {
        "id": row.id,
        "post_id": row.post_id,
        "thread_id": row.thread_id,
        "thread_title": thread.title if thread is not None else "",
        "post_status": post.status if post is not None else "",
        "post_excerpt": (
            "" if post is None or post.status.startswith("removed")
            else post.body[:_EXCERPT_CHARS]
        ),
        "post_author_id": post.author_id if post is not None else None,
        "post_author_name": (
            author_block(db, post.author_id, gone=post.author_gone)["display_name"]
            if post is not None
            else ""
        ),
        "reporter_id": row.reporter_id,
        "reporter_name": reporter.name if reporter is not None else "",
        "reason": row.reason,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_by_id": row.resolved_by_id,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
    }


def list_reports(db: Session, status: str = "open") -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumReport)
            .where(models.ForumReport.status == status)
            .order_by(models.ForumReport.created_at)
        ).all()
    )
    return [_report_view(db, row) for row in rows]


def dismiss_report(
    db: Session, actor, report_id: uuid.UUID, resolution: str = ""
) -> dict:
    row = db.get(models.ForumReport, report_id)
    if row is None:
        raise ForumNotFound("That report isn't available.")
    row.status = "dismissed"
    row.resolution = (resolution or "")[:500]
    row.resolved_by_id = actor.id
    row.resolved_at = _now()
    db.commit()
    _audit(db, actor, "forum.report_dismiss", row.post_id, {"report_id": str(row.id)})
    return _report_view(db, row)


def _held_view(db: Session, row: models.ForumPost) -> dict:
    thread = get_thread(db, row.thread_id)
    opener = _opener(db, row.thread_id)
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "thread_title": thread.title if thread is not None else "",
        "author_id": row.author_id,
        "author_name": author_block(db, row.author_id, gone=row.author_gone)[
            "display_name"
        ],
        "body": row.body,
        "flags": [f for f in row.flags.split(",") if f],
        "is_opener": opener is not None and opener.id == row.id,
        "created_at": row.created_at,
    }


def list_held(db: Session) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumPost)
            .where(models.ForumPost.status == "held")
            .order_by(models.ForumPost.created_at)
        ).all()
    )
    return [_held_view(db, row) for row in rows]


def _mod_post(db: Session, post_id: uuid.UUID) -> models.ForumPost:
    row = get_post(db, post_id)
    if row is None:
        raise ForumNotFound("That post isn't available.")
    return row


def _action_reports(db: Session, post_id: uuid.UUID, resolution: str) -> None:
    for report in db.scalars(
        select(models.ForumReport).where(
            models.ForumReport.post_id == post_id,
            models.ForumReport.status == "open",
        )
    ).all():
        report.status = "actioned"
        report.resolution = resolution[:500]


def release_post(db: Session, actor, post_id: uuid.UUID) -> dict:
    """A moderator lets a held post through: it becomes visible,
    a held thread un-hides, and a held reply notifies like a
    fresh one."""
    post = _mod_post(db, post_id)
    if post.status != "held":
        raise ForumError("That post isn't waiting for moderation.")
    post.status = "visible"
    post.flags = ""
    post.updated_at = _now()
    thread = get_thread(db, post.thread_id)
    if thread is not None:
        opener = _opener(db, thread.id)
        if opener is not None and opener.id == post.id and thread.held:
            thread.held = False
        thread.last_post_at = _now()
        thread.last_post_id = post.id
        thread.updated_at = _now()
        author = core_service.get_user_by_id(db, post.author_id)
        if author is not None and (opener is None or opener.id != post.id):
            _notify_reply(db, thread, author, post)
    db.commit()
    _audit(db, actor, "forum.post_release", post.id, {"thread_id": str(post.thread_id)})
    db.refresh(post)
    return _held_view(db, post)


def discard_post(db: Session, actor, post_id: uuid.UUID) -> dict:
    """A moderator throws a held post away — it was never
    delivered; the row tombstones as a moderator removal so the
    author sees an honest outcome, not a silent vanish."""
    post = _mod_post(db, post_id)
    if post.status != "held":
        raise ForumError("That post isn't waiting for moderation.")
    post.status = "removed_mod"
    post.removed_reason = "Discarded from the moderation queue."
    post.updated_at = _now()
    _action_reports(db, post.id, "Held post discarded by moderation.")
    db.commit()
    _audit(db, actor, "forum.post_discard", post.id, {"thread_id": str(post.thread_id)})
    db.refresh(post)
    return _held_view(db, post)


def remove_post(
    db: Session, actor, post_id: uuid.UUID, reason: str = ""
) -> dict:
    post = _mod_post(db, post_id)
    if post.status in ("removed_author", "removed_mod"):
        raise ForumError("That post is already removed.")
    post.status = "removed_mod"
    post.removed_reason = (reason or "")[:500] or "Removed by moderation."
    post.updated_at = _now()
    _action_reports(db, post.id, "Post removed by moderation.")
    db.commit()
    _audit(db, actor, "forum.post_remove", post.id, {"thread_id": str(post.thread_id)})
    db.refresh(post)
    return serialize_post(db, post, actor.id, viewer_is_mod=True)


def set_thread_pinned(db: Session, actor, thread_id: uuid.UUID, pinned: bool) -> dict:
    thread = get_thread(db, thread_id)
    if thread is None:
        raise ForumNotFound("That thread isn't available.")
    thread.pinned = pinned
    thread.updated_at = _now()
    db.commit()
    _audit(
        db,
        actor,
        "forum.thread_pin" if pinned else "forum.thread_unpin",
        thread.id,
        {},
    )
    return serialize_thread(db, thread, actor.id, viewer_is_mod=True)


def set_thread_locked(db: Session, actor, thread_id: uuid.UUID, locked: bool) -> dict:
    thread = get_thread(db, thread_id)
    if thread is None:
        raise ForumNotFound("That thread isn't available.")
    thread.locked = locked
    thread.updated_at = _now()
    db.commit()
    _audit(
        db,
        actor,
        "forum.thread_lock" if locked else "forum.thread_unlock",
        thread.id,
        {},
    )
    return serialize_thread(db, thread, actor.id, viewer_is_mod=True)


def delete_thread(db: Session, actor, thread_id: uuid.UUID) -> None:
    """HARD-delete a whole thread (admin tier — owner directive
    2026-10-22: an admin must be able to remove a thread outright,
    not just tombstone its posts one by one).

    The thread row, every post in it, and every report filed on
    those posts go in one transaction — reports reference the
    posts AND the thread by FK, so they are deleted first (an
    open report must never dangle into the moderation queue
    pointing at a post that no longer exists; resolved history
    dies with the content it judged). Quotes are text snapshots
    on same-thread replies only, so nothing outside the thread
    references its posts by value or by FK.

    Journal posture: posts/threads are visibility-only specs, so
    the ORM deletes journal as history entries for their authors
    and a restore never resurrects the thread; the journal drops
    entries whose owner is already gone (the D6 rule), and the
    author tombstone seam afterwards finds nothing to trip on.
    Notifications that referenced the thread carry its id in a
    JSON blob (no FK) — clicking one lands on the thread view's
    ordinary 404.

    The audit row snapshots the title + post count + category
    BEFORE the rows go — after commit, the row is the only place
    the thread's name survives."""
    thread = get_thread(db, thread_id)
    if thread is None:
        raise ForumNotFound("That thread isn't available.")
    title = thread.title
    category_id = thread.category_id
    posts = _thread_posts(db, thread.id)
    db.query(models.ForumReport).filter(
        models.ForumReport.thread_id == thread.id
    ).delete(synchronize_session=False)
    for post in posts:
        db.delete(post)
    db.delete(thread)
    db.commit()
    _audit(
        db,
        actor,
        "forum.thread_delete",
        thread_id,
        {
            "title": title,
            "posts": len(posts),
            "category_id": str(category_id),
        },
    )


def wipe_posts_from_user(db: Session, actor, target_user_id: uuid.UUID) -> dict:
    """Every post the target ever made tombstones as a moderator
    removal (threads keep their shape; openers keep their titles
    on the thread row). Open reports on those posts action out."""
    target = core_service.get_user_by_id(db, target_user_id)
    if target is None:
        raise ForumNotFound("That account isn't available.")
    rows = list(
        db.scalars(
            select(models.ForumPost).where(
                models.ForumPost.author_id == target_user_id,
                models.ForumPost.status.in_(("visible", "held")),
            )
        ).all()
    )
    for post in rows:
        post.status = "removed_mod"
        post.removed_reason = "Removed by moderation (all posts by this member)."
        post.updated_at = _now()
        _action_reports(db, post.id, "Author's posts removed by moderation.")
    db.commit()
    _audit(
        db, actor, "forum.posts_wipe", target_user_id, {"posts": len(rows)}
    )
    return {"user_id": target_user_id, "posts_removed": len(rows)}


def mod_thread_view(db: Session, thread_id: uuid.UUID) -> dict:
    """The moderator's thread view: everything, including held
    posts and removed bodies' existence (bodies of removed posts
    stay on the row for review context)."""
    thread = get_thread(db, thread_id)
    if thread is None:
        raise ForumNotFound("That thread isn't available.")
    posts = _thread_posts(db, thread.id)
    opener_id = posts[0].id if posts else None
    view = serialize_thread(db, thread, None, viewer_is_mod=True)
    view["posts"] = [
        serialize_post(
            db, p, None, viewer_is_mod=True, mod_detail=True, opener_id=opener_id
        )
        for p in posts
    ]
    return view


# -- operator categories -------------------------------------------------------------


def create_category(
    db: Session, *, name: str, description: str = "", sort_order: int = 0
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ForumError("A category needs a name.")
    row = models.ForumCategory(
        name=name[:120],
        description=(description or "").strip(),
        sort_order=int(sort_order),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_category(db, row)


def update_category(
    db: Session,
    category_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> dict:
    row = get_category(db, category_id)
    if row is None:
        raise ForumNotFound("That category isn't available.")
    if row.system_key in PERMANENT_BOARD_KEYS:
        # PERMANENT (owner directive 2026-11-02): the Bug
        # Reports and Feature Requests boards are fixtures of
        # the forum. No rename, no re-describe, no reorder, no
        # archive — for anyone, the operator path included.
        # They are structure, not content; their POSTS stay
        # ordinary, editable, moderatable posts.
        raise ForumError(
            "That board is a permanent part of the forum — "
            "it can't be edited or removed."
        )
    if name is not None:
        name = name.strip()
        if not name:
            raise ForumError("A category needs a name.")
        row.name = name[:120]
    if description is not None:
        row.description = description.strip()
    if sort_order is not None:
        row.sort_order = int(sort_order)
    if is_active is not None:
        row.is_active = bool(is_active)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return serialize_category(db, row, include_held=True)


def list_all_categories(db: Session) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.ForumCategory).order_by(
                models.ForumCategory.sort_order, models.ForumCategory.name
            )
        ).all()
    )
    return [serialize_category(db, row, include_held=True) for row in rows]


# -- export + deletion -------------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The data export's forum.json: my threads and every post I
    wrote (any status — it's MY data; the blind/held rules govern
    what other people see, not my own backup)."""
    threads = list(
        db.scalars(
            select(models.ForumThread)
            .where(models.ForumThread.author_id == owner_id)
            .order_by(models.ForumThread.created_at)
        ).all()
    )
    posts = list(
        db.scalars(
            select(models.ForumPost)
            .where(models.ForumPost.author_id == owner_id)
            .order_by(models.ForumPost.created_at)
        ).all()
    )
    return {
        "threads": [
            {
                "id": str(t.id),
                "category_id": str(t.category_id),
                "title": t.title,
                "pinned": t.pinned,
                "locked": t.locked,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in threads
        ],
        "posts": [
            {
                "id": str(p.id),
                "thread_id": str(p.thread_id),
                "body": p.body,
                "status": p.status,
                "link_type": p.link_type,
                "link_title": p.link_title,
                "edited_at": p.edited_at.isoformat() if p.edited_at else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in posts
        ],
    }


def tombstone_author(db: Session, user_id: uuid.UUID) -> None:
    """The account-deletion seam: my posts stay as Former-member
    tombstones (bodies wiped, threads unbroken — the two-party
    history posture), my threads keep their titles under the
    same tombstone, and reports I filed go with the account.
    Caller commits (the core deletion cascade's transaction)."""
    for post in db.scalars(
        select(models.ForumPost).where(models.ForumPost.author_id == user_id)
    ).all():
        post.author_gone = True
        post.body = ""
        post.quote_author_name = ""
        post.quote_excerpt = ""
    for thread in db.scalars(
        select(models.ForumThread).where(models.ForumThread.author_id == user_id)
    ).all():
        thread.author_gone = True
    db.query(models.ForumReport).filter(
        models.ForumReport.reporter_id == user_id
    ).delete(synchronize_session=False)
    # Favorites are the member's private stars — they go with
    # the account, like the reports they filed.
    db.query(models.ForumFavorite).filter(
        models.ForumFavorite.user_id == user_id
    ).delete(synchronize_session=False)
    db.flush()
