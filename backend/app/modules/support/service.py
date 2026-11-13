"""Support ticket service (support module, 2026-10-24).

The Help & Support page's ticket system. A member opens a ticket
(subject + first message), the support team (operators) answers
from the admin surface, and the ticket walks a small lifecycle
(owner steer 2026-10-24: exactly three statuses):

  open → under_review → (member replies) → open → … → closed

Status rules, enforced here so both faces agree:

  - A member reply on an "under_review" ticket moves it back to
    "open" (the ball is in the team's court again).
  - An operator reply sets "under_review" (the team has it in
    hand — including on a closed ticket, where a reply is the
    team picking it back up).
  - "closed" refuses member replies (422) — the team can reopen
    it from the admin surface by setting the status.
  - Only operators set status directly (the routes gate it).

Ownership is strict: the member face only ever sees the caller's
own tickets — a foreign id answers exactly like a missing one
(404, no oracle). The operator face sees everything, with the
owner's identity attached.

Cross-party events notify through the core inbox, in the same
commit as the event (the inbox doctrine), never to the actor:
an operator reply raises `support_reply`, an operator status
change raises `support_status` — both to the ticket owner. And
the desk hears about arrivals the same way: a member opening a
ticket raises `support_ticket_new`, a member follow-up raises
`support_ticket_reply` — to EVERY operator (an operator who is
the actor, e.g. on their own ticket, is skipped).

SERVICE INTERFACE (stable; bump the manifest version on change):
  - create_ticket / list_my_tickets / get_my_ticket /
    add_user_message — the member face.
  - list_all_tickets / get_ticket_admin / add_operator_message /
    set_status — the operator face.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.support import models

PREVIEW_CHARS = 120

# The display names the inbox copy uses (the stored values are
# the slugs in models.STATUSES; "under_review" must never reach
# a member's bell raw).
STATUS_LABELS = {
    "open": "Open",
    "under_review": "Under Review",
    "closed": "Closed",
}


class SupportError(ValueError):
    """Friendly refusal. Routes -> 422."""


class SupportNotFound(SupportError):
    """Missing OR not yours — ids never leak. -> 404."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- serializers ---------------------------------------------------------------------


def get_ticket(db: Session, ticket_id: uuid.UUID) -> models.SupportTicket | None:
    return db.get(models.SupportTicket, ticket_id)


def _message_count(db: Session, ticket_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(models.SupportMessage.id)).where(
                models.SupportMessage.ticket_id == ticket_id
            )
        )
        or 0
    )


def _last_message(db: Session, ticket_id: uuid.UUID) -> models.SupportMessage | None:
    return db.scalars(
        select(models.SupportMessage)
        .where(models.SupportMessage.ticket_id == ticket_id)
        .order_by(
            models.SupportMessage.created_at.desc(), models.SupportMessage.id.desc()
        )
        .limit(1)
    ).first()


def ticket_summary(db: Session, row: models.SupportTicket) -> dict:
    last = _last_message(db, row.id)
    return {
        "id": row.id,
        "subject": row.subject,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "message_count": _message_count(db, row.id),
        "last_message_preview": (last.body or "")[:PREVIEW_CHARS] if last else "",
        # Whose court the ball is in: the Help & Support status
        # strip reads a ticket whose newest message is the
        # team's as "waiting on you" (2026-11-02).
        "last_message_author_kind": last.author_kind if last else "",
    }


def _messages(db: Session, ticket_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(models.SupportMessage)
        .where(models.SupportMessage.ticket_id == ticket_id)
        .order_by(models.SupportMessage.created_at, models.SupportMessage.id)
    ).all()
    return [
        {
            "id": m.id,
            "author_kind": m.author_kind,
            "body": m.body,
            "created_at": m.created_at,
        }
        for m in rows
    ]


def ticket_detail(db: Session, row: models.SupportTicket) -> dict:
    view = ticket_summary(db, row)
    view["messages"] = _messages(db, row.id)
    return view


def _owner_fields(db: Session, row: models.SupportTicket) -> dict:
    owner = core_service.get_user_by_id(db, row.user_id)
    return {
        "user_id": row.user_id,
        "user_name": owner.name if owner else "",
        "user_email": owner.email if owner else "",
        "user_account_number": owner.account_number if owner else "",
    }


def admin_summary(db: Session, row: models.SupportTicket) -> dict:
    view = ticket_summary(db, row)
    view.update(_owner_fields(db, row))
    return view


def admin_detail(db: Session, row: models.SupportTicket) -> dict:
    view = ticket_detail(db, row)
    view.update(_owner_fields(db, row))
    return view


# -- member face ------------------------------------------------------------------------


def _clean_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise SupportError("Write something first.")
    return body


def _notify_operators(
    db: Session, *, actor_id: uuid.UUID, kind: str, title: str, body: str, ticket_id: uuid.UUID
) -> None:
    """Fan a member-side ticket event out to every operator's
    inbox, inside the caller's transaction (the caller commits).
    The actor is never notified about their own action — an
    operator who opens or answers their own ticket hears nothing
    from this path."""
    operators = db.scalars(
        select(core_models.User).where(core_models.User.is_operator.is_(True))
    ).all()
    for operator in operators:
        if operator.id == actor_id:
            continue
        inbox.create_notification(
            db,
            operator.id,
            kind=kind,
            title=title,
            body=body,
            data={"ticket_id": str(ticket_id)},
            commit=False,
        )


def create_ticket(db: Session, user, *, subject: str, body: str) -> dict:
    """Open a ticket: the ticket row + its first message land in
    one commit, so a ticket never exists without its opener —
    and every operator's inbox hears about it in the same
    commit (`support_ticket_new`)."""
    subject = (subject or "").strip()
    if not subject:
        raise SupportError("Give your ticket a subject.")
    body = _clean_body(body)
    row = models.SupportTicket(user_id=user.id, subject=subject[:200], status="open")
    db.add(row)
    db.flush()
    db.add(
        models.SupportMessage(
            ticket_id=row.id,
            author_id=user.id,
            author_kind="user",
            body=body,
        )
    )
    sender = user.name or user.email
    _notify_operators(
        db,
        actor_id=user.id,
        kind=inbox.KIND_SUPPORT_TICKET_NEW,
        title="New support ticket",
        body=f"{sender} opened a ticket: “{row.subject}”.",
        ticket_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return ticket_detail(db, row)


def stats(db: Session, user_id: uuid.UUID) -> dict:
    """The panel stat (Phase 3, 2026-10-24): the member's OPEN
    tickets — everything not closed, so "open" and
    "under_review" both count (a ticket under review is still
    an open matter between the member and the desk; only
    "closed" is finished)."""
    count = db.scalar(
        select(func.count(models.SupportTicket.id)).where(
            models.SupportTicket.user_id == user_id,
            models.SupportTicket.status != "closed",
        )
    )
    return {"open_tickets_count": int(count or 0)}


def list_my_tickets(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(models.SupportTicket)
        .where(models.SupportTicket.user_id == user_id)
        .order_by(
            models.SupportTicket.updated_at.desc(), models.SupportTicket.id.desc()
        )
    ).all()
    return [ticket_summary(db, row) for row in rows]


def _my_ticket(db: Session, user_id: uuid.UUID, ticket_id: uuid.UUID) -> models.SupportTicket:
    row = get_ticket(db, ticket_id)
    if row is None or row.user_id != user_id:
        raise SupportNotFound("That ticket isn't available.")
    return row


def get_my_ticket(db: Session, user_id: uuid.UUID, ticket_id: uuid.UUID) -> dict:
    return ticket_detail(db, _my_ticket(db, user_id, ticket_id))


def add_user_message(db: Session, user, ticket_id: uuid.UUID, *, body: str) -> dict:
    """Append the owner's reply. A closed ticket refuses (422);
    a reply on an under-review ticket hands it back to the team
    (status returns to "open"). Every operator hears about the
    follow-up in the same commit (`support_ticket_reply`)."""
    row = _my_ticket(db, user.id, ticket_id)
    if row.status == "closed":
        raise SupportError(
            "This ticket is closed. Open a new ticket if you still need help."
        )
    body = _clean_body(body)
    db.add(
        models.SupportMessage(
            ticket_id=row.id,
            author_id=user.id,
            author_kind="user",
            body=body,
        )
    )
    if row.status == "under_review":
        row.status = "open"
    row.updated_at = _now()
    sender = user.name or user.email
    _notify_operators(
        db,
        actor_id=user.id,
        kind=inbox.KIND_SUPPORT_TICKET_REPLY,
        title="New reply on a support ticket",
        body=f"{sender} replied to their ticket “{row.subject}”.",
        ticket_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return ticket_detail(db, row)


# -- operator face ------------------------------------------------------------------------


def list_all_tickets(db: Session, status_filter: str = "") -> list[dict]:
    stmt = select(models.SupportTicket).order_by(
        models.SupportTicket.updated_at.desc(), models.SupportTicket.id.desc()
    )
    if status_filter:
        if status_filter not in models.STATUSES:
            raise SupportError("Unknown status filter.")
        stmt = stmt.where(models.SupportTicket.status == status_filter)
    return [admin_summary(db, row) for row in db.scalars(stmt).all()]


def _any_ticket(db: Session, ticket_id: uuid.UUID) -> models.SupportTicket:
    row = get_ticket(db, ticket_id)
    if row is None:
        raise SupportNotFound("That ticket isn't available.")
    return row


def get_ticket_admin(db: Session, ticket_id: uuid.UUID) -> dict:
    return admin_detail(db, _any_ticket(db, ticket_id))


def add_operator_message(db: Session, operator, ticket_id: uuid.UUID, *, body: str) -> dict:
    """The team's reply: appends an operator message, moves the
    ticket to "under_review" (the team has it in hand), and
    notifies the owner — all in ONE commit (the notification
    rides commit=False into the reply's own transaction)."""
    row = _any_ticket(db, ticket_id)
    body = _clean_body(body)
    db.add(
        models.SupportMessage(
            ticket_id=row.id,
            author_id=operator.id,
            author_kind="operator",
            body=body,
        )
    )
    row.status = "under_review"
    row.updated_at = _now()
    db.flush()
    inbox.create_notification(
        db,
        row.user_id,
        kind=inbox.KIND_SUPPORT_REPLY,
        title="Support replied to your ticket",
        body=f"The support team replied to your ticket “{row.subject}”.",
        data={"ticket_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return admin_detail(db, row)


def set_status(db: Session, operator, ticket_id: uuid.UUID, *, status: str) -> dict:
    """Move a ticket's status. Only a CHANGE notifies the owner
    (a no-op re-set stays silent) and bumps activity."""
    if status not in models.STATUSES:
        raise SupportError("Unknown status.")
    row = _any_ticket(db, ticket_id)
    changed = row.status != status
    if changed:
        row.status = status
        row.updated_at = _now()
        db.flush()
        inbox.create_notification(
            db,
            row.user_id,
            kind=inbox.KIND_SUPPORT_STATUS,
            title="Your support ticket was updated",
            body=f"Your ticket “{row.subject}” is now {STATUS_LABELS[status]}.",
            data={"ticket_id": str(row.id)},
            commit=False,
        )
        db.commit()
        db.refresh(row)
    return admin_detail(db, row)


# -- how-to videos (Help & Support build, 2026-11-02) ------------------
#
# The smallest honest video library: operators keep a list of
# YouTube walkthroughs (hosted on the Toolbox Vault channel —
# nothing is stored or served from this server); members read
# the published ones. Drafts never leave the operator face.

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?[^#]*\bv=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})"),
)


def extract_youtube_id(raw: str) -> str:
    """Normalize what an operator pastes — a watch URL, a short
    link, an embed/shorts URL, or the bare id — to the video id.
    Anything else is a friendly refusal, never a stored guess."""
    value = (raw or "").strip()
    if _YOUTUBE_ID.match(value):
        return value
    for pattern in _YOUTUBE_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    raise SupportError(
        "That doesn't look like a YouTube video — paste the video's "
        "watch link or its id."
    )


def _video_public(row: models.HelpVideo) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "summary": row.summary,
        "youtube_id": row.youtube_id,
        "section": row.section,
        "sort_order": row.sort_order,
    }


def _video_admin(row: models.HelpVideo) -> dict:
    out = _video_public(row)
    out.update(
        {
            "is_published": row.is_published,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
    return out


def list_published_videos(db: Session) -> list[dict]:
    rows = db.scalars(
        select(models.HelpVideo)
        .where(models.HelpVideo.is_published.is_(True))
        .order_by(
            models.HelpVideo.section,
            models.HelpVideo.sort_order,
            models.HelpVideo.created_at,
        )
    ).all()
    return [_video_public(row) for row in rows]


def list_all_videos(db: Session) -> list[dict]:
    rows = db.scalars(
        select(models.HelpVideo).order_by(
            models.HelpVideo.section,
            models.HelpVideo.sort_order,
            models.HelpVideo.created_at,
        )
    ).all()
    return [_video_admin(row) for row in rows]


def _clean_video_fields(
    *, title: str, summary: str, youtube: str, section: str, sort_order: int
) -> dict:
    title = (title or "").strip()
    if not title:
        raise SupportError("A video needs a title.")
    if section not in models.VIDEO_SECTIONS:
        raise SupportError("A video belongs to the website or the app.")
    return {
        "title": title[:200],
        "summary": (summary or "").strip(),
        "youtube_id": extract_youtube_id(youtube),
        "section": section,
        "sort_order": int(sort_order),
    }


def create_video(
    db: Session,
    *,
    title: str,
    summary: str,
    youtube: str,
    section: str,
    sort_order: int,
    is_published: bool,
) -> dict:
    fields = _clean_video_fields(
        title=title, summary=summary, youtube=youtube,
        section=section, sort_order=sort_order,
    )
    row = models.HelpVideo(**fields, is_published=bool(is_published))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _video_admin(row)


def update_video(
    db: Session,
    video_id: uuid.UUID,
    *,
    title: str,
    summary: str,
    youtube: str,
    section: str,
    sort_order: int,
    is_published: bool,
) -> dict:
    row = db.get(models.HelpVideo, video_id)
    if row is None:
        raise SupportNotFound("That video isn't on the list.")
    fields = _clean_video_fields(
        title=title, summary=summary, youtube=youtube,
        section=section, sort_order=sort_order,
    )
    for key, value in fields.items():
        setattr(row, key, value)
    row.is_published = bool(is_published)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _video_admin(row)


def delete_video(db: Session, video_id: uuid.UUID) -> None:
    row = db.get(models.HelpVideo, video_id)
    if row is None:
        raise SupportNotFound("That video isn't on the list.")
    db.delete(row)
    db.commit()
