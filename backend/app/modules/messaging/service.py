"""Messaging service: threads, the quarantine, blocks, reports,
the moderation queue, and the public seller profile.

SERVICE INTERFACE (stable; bump the messaging manifest version on
change):
  - open_thread(db, sender, recipient_id, body, anchor=...) —
    find-or-create the conversation and post the first message
    through the firewall.
  - post_message(db, sender, thread, body) — one send through the
    full pipeline (block shadow → rate budget → content screen).
  - list_threads(db, user, folder) / thread_view(db, user, thread)
    / mark_read / accept_request / decline_request.
  - block_user / unblock_user / list_blocks / is_blocked.
  - report_thread(db, user, thread, reason).
  - Moderation: list_reports / list_held / mod_thread_view /
    dismiss_report / release_message / discard_message /
    wipe_message / wipe_all_from_user / ban_user.
  - public_profile(db, user_id) — the seller profile payload
    (name, member since, area, opt-in phone, reputation
    placeholder the reputation build fills in).

QUARANTINE (owner, 2026-10-19): a first conversation with someone
you have never had an ACCEPTED thread with opens as a REQUEST: it
sits in the recipient's Message requests, fires NO inbox
notification and NO email, and the sender gets no read receipts
until the recipient accepts (explicitly, or by replying — a reply
IS an acceptance). Links inside a request-stage thread serialize
as links_disabled so the UI renders them inert behind a warning.

ALERTS: an accepted-thread message notifies the recipient (inbox
+ email seam) only when it is their FIRST unread in that thread —
the thread badge carries the rest, nobody's inbox gets blasted
per message. Email copy carries no message text and no links:
"you have a new message", signed-in reading only.

BLOCKING IS SILENT: a blocked sender's sends land as `shadow` —
visible in their own view exactly as if delivered, never present
in the recipient's. Their new threads exist only in their own
lists. Nothing anywhere tells them.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import i18n
from app.core import notifications as email_seam
from app.modules.core import inbox
from app.modules.core import notification_prefs
from app.modules.core import service as core_service
from app.modules.messaging import models, spam


class MessagingError(ValueError):
    """Friendly refusal. Routes -> 422."""


class MessagingNotFound(MessagingError):
    """Missing OR not yours — ids never leak existence. -> 404."""


class RateLimited(MessagingError):
    """The firewall's budget answer. Routes -> 429."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- pairs, states, blocks -----------------------------------------------------


def pair_of(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if str(a) < str(b) else (b, a)


def other_id(thread: models.MessageThread, user_id: uuid.UUID) -> uuid.UUID:
    return (
        thread.participant_high_id
        if thread.participant_low_id == user_id
        else thread.participant_low_id
    )


def is_blocked(db: Session, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(models.UserBlock.id).where(
                models.UserBlock.blocker_id == blocker_id,
                models.UserBlock.blocked_id == blocked_id,
            )
        )
        is not None
    )


def get_state(
    db: Session, thread_id: uuid.UUID, user_id: uuid.UUID
) -> models.MessageThreadState:
    state = db.scalars(
        select(models.MessageThreadState).where(
            models.MessageThreadState.thread_id == thread_id,
            models.MessageThreadState.user_id == user_id,
        )
    ).first()
    if state is None:
        state = models.MessageThreadState(thread_id=thread_id, user_id=user_id)
        db.add(state)
        db.flush()
    return state


def get_thread(db: Session, thread_id: uuid.UUID) -> models.MessageThread | None:
    return db.get(models.MessageThread, thread_id)


def participant_thread(
    db: Session, user_id: uuid.UUID, thread_id: uuid.UUID
) -> models.MessageThread:
    thread = get_thread(db, thread_id)
    if thread is None or user_id not in (
        thread.participant_low_id,
        thread.participant_high_id,
    ):
        raise MessagingNotFound("That conversation isn't available.")
    return thread


def _has_accepted_history(db: Session, a: uuid.UUID, b: uuid.UUID) -> bool:
    low, high = pair_of(a, b)
    return (
        db.scalar(
            select(models.MessageThread.id).where(
                models.MessageThread.participant_low_id == low,
                models.MessageThread.participant_high_id == high,
                models.MessageThread.status == "accepted",
            )
        )
        is not None
    )


# -- serialization ---------------------------------------------------------------


def _user_name(db: Session, user_id: uuid.UUID) -> str:
    user = core_service.get_user_by_id(db, user_id)
    return user.name if user is not None else ""


def visible_to_recipient(message: models.Message) -> bool:
    """What the NON-sender may see: delivered messages, plus the
    tombstone of a wiped one. Held, shadow and discarded messages
    are not theirs to know about."""
    return message.status in ("sent", "removed")


def serialize_message(
    viewer_id: uuid.UUID, thread: models.MessageThread, message: models.Message
) -> dict:
    mine = message.sender_id == viewer_id
    removed = message.status == "removed"
    discarded = message.status == "discarded"
    body = "" if (removed or discarded) else message.body
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender_id": message.sender_id,
        "mine": mine,
        "body": body,
        # The sender's own view normalizes shadow to "sent" (the
        # block is silent); held stays visible TO THE SENDER as
        # under review — their copy is honest, it just never
        # arrived.
        "status": "sent" if (mine and message.status == "shadow") else message.status,
        "held": bool(mine and message.status == "held"),
        "removed": removed,
        "flags": list(message.flags or []),
        "has_links": bool(spam.has_link(message.body)),
        # Quarantine: links in a request-stage thread render inert
        # for BOTH sides — the recipient hasn't vouched for this
        # sender yet.
        "links_disabled": thread.status == "request",
        "created_at": message.created_at,
        "seq": message.seq,
    }


def _unread_count(
    db: Session, thread: models.MessageThread, user_id: uuid.UUID
) -> int:
    state = get_state(db, thread.id, user_id)
    count = db.scalar(
        select(func.count(models.Message.id)).where(
            models.Message.thread_id == thread.id,
            models.Message.sender_id != user_id,
            models.Message.status.in_(("sent", "removed")),
            models.Message.seq > state.last_read_seq,
        )
    )
    return int(count or 0)


def _viewer_message_stats(
    db: Session, thread: models.MessageThread, viewer_id: uuid.UUID
) -> tuple[str, uuid.UUID | None, datetime | None, int]:
    """(preview, sender_id, at, visible_count) over the messages
    THIS viewer may see. Computed per viewer, never denormalized
    onto the thread row: a held or shadow message must not leak
    even its first 200 characters into the other side's inbox
    preview, and the two sides legitimately see different newest
    messages."""
    rows = list(
        db.scalars(
            select(models.Message)
            .where(
                models.Message.thread_id == thread.id,
                (models.Message.sender_id == viewer_id)
                | (models.Message.status.in_(("sent", "removed"))),
            )
            .order_by(models.Message.seq.desc())
        ).all()
    )
    if not rows:
        return "", None, None, 0
    newest = rows[0]
    if newest.status == "removed":
        preview = "Message removed"
    elif newest.status == "discarded":
        preview = "Message removed by moderators"
    else:
        preview = (newest.body or "")[:200]
    return preview, newest.sender_id, newest.created_at, len(rows)


def serialize_thread(
    db: Session, viewer_id: uuid.UUID, thread: models.MessageThread
) -> dict:
    other = other_id(thread, viewer_id)
    if thread.status == "request":
        direction = (
            "incoming" if thread.created_by_id != viewer_id else "outgoing"
        )
    else:
        direction = "accepted"
    # Read receipts exist only once a thread is accepted — and
    # only the OTHER side's marker is shown, masked to None while
    # the request is pending.
    other_read_seq: int | None = None
    if thread.status == "accepted":
        other_read_seq = get_state(db, thread.id, other).last_read_seq
    preview, preview_sender, preview_at, visible_count = _viewer_message_stats(
        db, thread, viewer_id
    )
    return {
        "id": thread.id,
        "other_user_id": other,
        "other_name": _user_name(db, other),
        "anchor_type": thread.anchor_type,
        "anchor_id": thread.anchor_id,
        "anchor_title": thread.anchor_title,
        "status": thread.status,
        "direction": direction,
        "unread_count": _unread_count(db, thread, viewer_id),
        "other_last_read_seq": other_read_seq,
        "last_message_at": preview_at,
        "last_message_preview": preview,
        "last_message_sender_id": preview_sender,
        "last_message_mine": preview_sender == viewer_id,
        "message_count": visible_count,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }


def thread_view(
    db: Session, user_id: uuid.UUID, thread: models.MessageThread
) -> dict:
    """Thread + the messages THIS viewer may see, oldest first."""
    rows = list(
        db.scalars(
            select(models.Message)
            .where(models.Message.thread_id == thread.id)
            .order_by(models.Message.seq)
        ).all()
    )
    messages = [
        serialize_message(user_id, thread, row)
        for row in rows
        if row.sender_id == user_id or visible_to_recipient(row)
    ]
    view = serialize_thread(db, user_id, thread)
    view["messages"] = messages
    return view


# -- alerts ------------------------------------------------------------------------


def _notify_message(
    db: Session, recipient_id: uuid.UUID, sender_name: str, *, thread_id: uuid.UUID
) -> None:
    """Inbox + email for a delivered message, built inside the
    send's transaction (the caller commits). The thread id
    rides the payload so the notification's click-through can
    land on this conversation (owner spec 2026-10-25)."""
    inbox.create_notification(
        db,
        recipient_id,
        kind=inbox.KIND_MESSAGE_RECEIVED,
        title="New message",
        body=f"{sender_name} sent you a message.",
        data={"thread_id": str(thread_id)},
        commit=False,
    )
    recipient = core_service.get_user_by_id(db, recipient_id)
    # The bespoke content-free email is this kind's email twin:
    # the central inbox hook skips message_received (it is in
    # inbox.SELF_EMAILED_KINDS) and THIS send answers to the
    # same category preference (owner item 12, 2026-10-24) —
    # turning Messages email off in Settings silences both.
    if recipient is not None and notification_prefs.email_enabled_for_kind(
        db, recipient_id, inbox.KIND_MESSAGE_RECEIVED
    ):
        email_seam.send_message_notification_email(db, recipient.email, sender_name, locale=i18n.resolve_locale(recipient))


def _notify_request_accepted(
    db: Session, opener_id: uuid.UUID, accepter_name: str, *, thread_id: uuid.UUID
) -> None:
    inbox.create_notification(
        db,
        opener_id,
        kind=inbox.KIND_MESSAGE_REQUEST_ACCEPTED,
        title="Message request accepted",
        body=f"{accepter_name} accepted your message request.",
        data={"thread_id": str(thread_id)},
        commit=False,
    )


# -- sending -------------------------------------------------------------------


def _touch_thread(thread: models.MessageThread) -> None:
    """Only the activity timestamp is denormalized (list ordering
    + the Unread sort). Previews are computed per viewer at read
    time — see _viewer_message_stats for why they must never live
    on the shared thread row."""
    thread.updated_at = _now()


def post_message(
    db: Session, sender, thread: models.MessageThread, body: str
) -> models.Message:
    """One send through the full pipeline. Commits."""
    body = (body or "").strip()
    if not body:
        raise MessagingError("Write a message first.")
    if len(body) > 5000:
        raise MessagingError("That message is too long — 5,000 characters max.")
    other = other_id(thread, sender.id)
    my_state = get_state(db, thread.id, sender.id)
    if my_state.hidden:
        # Messaging again after declining/dismissing reopens the
        # thread for me — and MY posting in a request thread is a
        # reply, which accepts it (handled below).
        my_state.hidden = False

    blocked_by_other = is_blocked(db, other, sender.id)

    refusal = spam.check_message_budget(db, sender)
    if refusal:
        raise RateLimited(refusal)

    accepted_now = False
    if thread.status == "request" and thread.created_by_id != sender.id:
        # The recipient replied — a reply IS an acceptance.
        thread.status = "accepted"
        accepted_now = True

    if blocked_by_other:
        status, flags = "shadow", []
    else:
        status, flags = spam.screen_body(
            db,
            sender.id,
            body,
            current_recipient_id=other,
            exclude_thread_id=thread.id,
        )

    recipient_state = get_state(db, thread.id, other)
    unread_before = _unread_count(db, thread, other)
    message = models.Message(
        thread_id=thread.id, sender_id=sender.id, body=body, status=status, flags=flags
    )
    db.add(message)
    db.flush()
    # Sending implies read-up-to-my-own-message: without this, a
    # conversation you are actively replying in still counts the
    # other side's earlier messages as your unread (and the
    # notify-once rule below never sees a clean slate).
    if message.seq is not None and message.seq > my_state.last_read_seq:
        my_state.last_read_seq = int(message.seq)
    _touch_thread(thread)

    if accepted_now:
        _notify_request_accepted(db, thread.created_by_id, sender.name, thread_id=thread.id)
    elif status == "sent" and thread.status == "accepted" and unread_before == 0:
        # First unread in an accepted thread: alert once. Request-
        # stage sends never reach this branch (status gate above).
        _notify_message(db, other, sender.name, thread_id=thread.id)
    db.commit()
    db.refresh(message)
    if recipient_state.hidden and status == "sent" and thread.status == "accepted":
        # A delivered message in an accepted thread un-hides it for
        # the recipient (they dismissed the thread, not the person).
        recipient_state.hidden = False
        db.commit()
    return message


def open_thread(
    db: Session,
    sender,
    recipient_id: uuid.UUID,
    body: str,
    *,
    anchor_type: str = "",
    anchor_id: uuid.UUID | None = None,
    anchor_title: str = "",
) -> models.MessageThread:
    """Find-or-create the conversation and post `body` into it.
    Commits. The anchor is validated by the caller (routes) — for
    "part" the caller resolves the public listing and its owner.
    """
    recipient = core_service.get_user_by_id(db, recipient_id)
    if recipient is None or not recipient.is_active:
        raise MessagingNotFound("That user isn't available.")
    if recipient.id == sender.id:
        raise MessagingError("You can't message yourself.")
    if is_blocked(db, sender.id, recipient.id):
        raise MessagingError(
            "You've blocked this user — unblock them (Messages → Blocked) "
            "before starting a conversation."
        )

    low, high = pair_of(sender.id, recipient.id)
    candidates = list(
        db.scalars(
            select(models.MessageThread).where(
                models.MessageThread.participant_low_id == low,
                models.MessageThread.participant_high_id == high,
                models.MessageThread.anchor_type == anchor_type,
                models.MessageThread.anchor_id == anchor_id,
            )
        ).all()
    )
    blocked_by_recipient = is_blocked(db, recipient.id, sender.id)
    thread: models.MessageThread | None = None
    for candidate in candidates:
        if blocked_by_recipient:
            thread = candidate  # shadow-append to any existing thread
            break
        state = get_state(db, candidate.id, recipient.id)
        if candidate.status == "request" and state.hidden:
            continue  # declined: a fresh request may be opened instead
        thread = candidate
        break

    if thread is None:
        refusal = spam.check_thread_budget(db, sender)
        if refusal:
            raise RateLimited(refusal)
        status = (
            "accepted"
            if _has_accepted_history(db, sender.id, recipient.id)
            else "request"
        )
        thread = models.MessageThread(
            participant_low_id=low,
            participant_high_id=high,
            created_by_id=sender.id,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            anchor_title=(anchor_title or "")[:300],
            status=status,
        )
        db.add(thread)
        db.flush()
        get_state(db, thread.id, sender.id)
        get_state(db, thread.id, recipient.id)
        db.commit()
        db.refresh(thread)

    post_message(db, sender, thread, body)
    db.refresh(thread)
    return thread


# -- lists, read markers, request answers ---------------------------------------


def list_threads(db: Session, user_id: uuid.UUID, folder: str) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.MessageThread).where(
                (models.MessageThread.participant_low_id == user_id)
                | (models.MessageThread.participant_high_id == user_id)
            )
        ).all()
    )
    views: list[dict] = []
    for thread in rows:
        state = get_state(db, thread.id, user_id)
        if state.hidden:
            continue
        other = other_id(thread, user_id)
        if (
            thread.created_by_id == other
            and thread.status == "request"
            and is_blocked(db, user_id, other)
        ):
            continue  # a blocked stranger's shadow request: never surfaces
        if folder == "requests":
            if thread.status != "request" or thread.created_by_id == user_id:
                continue
        else:  # inbox: accepted threads + my own outgoing requests
            if thread.status == "request" and thread.created_by_id != user_id:
                continue
        views.append(serialize_thread(db, user_id, thread))
    views.sort(
        key=lambda v: v["last_message_at"] or v["created_at"], reverse=True
    )
    db.commit()  # states materialized above
    return views


def unread_summary(db: Session, user_id: uuid.UUID) -> dict:
    inbox_views = list_threads(db, user_id, "inbox")
    request_views = list_threads(db, user_id, "requests")
    return {
        "inbox_unread": sum(v["unread_count"] for v in inbox_views),
        "requests_count": len(request_views),
    }


def mark_read(
    db: Session, user_id: uuid.UUID, thread: models.MessageThread
) -> models.MessageThreadState:
    """Advance my read marker to the newest message I can see."""
    state = get_state(db, thread.id, user_id)
    newest = db.scalar(
        select(func.max(models.Message.seq)).where(
            models.Message.thread_id == thread.id,
            (models.Message.sender_id == user_id)
            | (models.Message.status.in_(("sent", "removed"))),
        )
    )
    if newest is not None and newest > state.last_read_seq:
        state.last_read_seq = int(newest)
    db.commit()
    db.refresh(state)
    return state


def accept_request(
    db: Session, user, thread: models.MessageThread
) -> models.MessageThread:
    if thread.created_by_id == user.id:
        raise MessagingError("This is your own request — it waits on the other person.")
    if thread.status != "request":
        return thread
    thread.status = "accepted"
    state = get_state(db, thread.id, user.id)
    state.hidden = False
    _notify_request_accepted(db, thread.created_by_id, user.name, thread_id=thread.id)
    db.commit()
    db.refresh(thread)
    return thread


def decline_request(
    db: Session, user_id: uuid.UUID, thread: models.MessageThread
) -> None:
    """Silent: the thread leaves MY lists; the sender is never
    told, and no state they can read changes."""
    if thread.created_by_id == user_id:
        raise MessagingError("This is your own request — there's nothing to decline.")
    state = get_state(db, thread.id, user_id)
    state.hidden = True
    db.commit()


# -- blocks ---------------------------------------------------------------------


def block_user(db: Session, user_id: uuid.UUID, other_id_: uuid.UUID) -> dict:
    other = core_service.get_user_by_id(db, other_id_)
    if other is None:
        raise MessagingNotFound("That user isn't available.")
    if other.id == user_id:
        raise MessagingError("You can't block yourself.")
    row = db.scalars(
        select(models.UserBlock).where(
            models.UserBlock.blocker_id == user_id,
            models.UserBlock.blocked_id == other.id,
        )
    ).first()
    if row is None:
        row = models.UserBlock(blocker_id=user_id, blocked_id=other.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"user_id": other.id, "name": other.name, "created_at": row.created_at}


def unblock_user(db: Session, user_id: uuid.UUID, other_id_: uuid.UUID) -> bool:
    row = db.scalars(
        select(models.UserBlock).where(
            models.UserBlock.blocker_id == user_id,
            models.UserBlock.blocked_id == other_id_,
        )
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_blocks(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.UserBlock)
            .where(models.UserBlock.blocker_id == user_id)
            .order_by(models.UserBlock.created_at.desc())
        ).all()
    )
    views = []
    for row in rows:
        other = core_service.get_user_by_id(db, row.blocked_id)
        views.append(
            {
                "user_id": row.blocked_id,
                "name": other.name if other is not None else "",
                "created_at": row.created_at,
            }
        )
    return views


# -- reports + moderation ---------------------------------------------------------


def report_thread(
    db: Session, user_id: uuid.UUID, thread: models.MessageThread, reason: str
) -> models.MessageReport:
    existing = db.scalars(
        select(models.MessageReport).where(
            models.MessageReport.thread_id == thread.id,
            models.MessageReport.reporter_id == user_id,
            models.MessageReport.status == "open",
        )
    ).first()
    if existing is not None:
        raise MessagingError(
            "You've already reported this conversation — it's in the "
            "moderation queue."
        )
    row = models.MessageReport(
        thread_id=thread.id,
        reporter_id=user_id,
        reason=(reason or "").strip()[:500],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _report_view(db: Session, row: models.MessageReport) -> dict:
    thread = get_thread(db, row.thread_id)
    reporter = core_service.get_user_by_id(db, row.reporter_id)
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "reporter_id": row.reporter_id,
        "reporter_name": reporter.name if reporter is not None else "",
        "reason": row.reason,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_by_id": row.resolved_by_id,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
        "anchor_title": thread.anchor_title if thread is not None else "",
        "participant_names": (
            [
                _user_name(db, thread.participant_low_id),
                _user_name(db, thread.participant_high_id),
            ]
            if thread is not None
            else []
        ),
    }


def list_reports(db: Session, status: str = "open") -> list[dict]:
    rows = list(
        db.scalars(
            select(models.MessageReport)
            .where(models.MessageReport.status == status)
            .order_by(models.MessageReport.created_at)
        ).all()
    )
    return [_report_view(db, row) for row in rows]


def _held_view(db: Session, row: models.Message) -> dict:
    thread = get_thread(db, row.thread_id)
    sender = core_service.get_user_by_id(db, row.sender_id)
    recipient_id = (
        other_id(thread, row.sender_id) if thread is not None else None
    )
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "sender_id": row.sender_id,
        "sender_name": sender.name if sender is not None else "",
        "recipient_id": recipient_id,
        "recipient_name": _user_name(db, recipient_id) if recipient_id else "",
        "body": row.body,
        # The row's CURRENT status — the moderation actions return
        # this view after acting, and the queue needs the outcome
        # (held / sent / discarded / removed) on the response.
        "status": row.status,
        "flags": list(row.flags or []),
        "anchor_title": thread.anchor_title if thread is not None else "",
        "created_at": row.created_at,
    }


def list_held(db: Session) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.Message)
            .where(models.Message.status == "held")
            .order_by(models.Message.created_at)
        ).all()
    )
    return [_held_view(db, row) for row in rows]


def mod_thread_view(db: Session, thread_id: uuid.UUID) -> dict:
    """The moderator's unfiltered read: every message with its
    true status and flags — held and shadow included."""
    thread = get_thread(db, thread_id)
    if thread is None:
        raise MessagingNotFound("That conversation isn't available.")
    rows = list(
        db.scalars(
            select(models.Message)
            .where(models.Message.thread_id == thread.id)
            .order_by(models.Message.seq)
        ).all()
    )
    return {
        "id": thread.id,
        "participant_low_id": thread.participant_low_id,
        "participant_high_id": thread.participant_high_id,
        "participant_names": [
            _user_name(db, thread.participant_low_id),
            _user_name(db, thread.participant_high_id),
        ],
        "anchor_type": thread.anchor_type,
        "anchor_id": thread.anchor_id,
        "anchor_title": thread.anchor_title,
        "status": thread.status,
        "created_at": thread.created_at,
        "messages": [
            {
                "id": row.id,
                "sender_id": row.sender_id,
                "sender_name": _user_name(db, row.sender_id),
                "body": row.body,
                "status": row.status,
                "flags": list(row.flags or []),
                "created_at": row.created_at,
                "seq": row.seq,
            }
            for row in rows
        ],
    }


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


def dismiss_report(
    db: Session, actor, report_id: uuid.UUID, resolution: str = ""
) -> dict:
    row = db.get(models.MessageReport, report_id)
    if row is None:
        raise MessagingNotFound("That report isn't available.")
    row.status = "dismissed"
    row.resolution = (resolution or "")[:500]
    row.resolved_by_id = actor.id
    row.resolved_at = _now()
    db.commit()
    _audit(
        db, actor, "message.report_dismiss", row.thread_id, {"report_id": str(row.id)}
    )
    return _report_view(db, row)


def _get_message(db: Session, message_id: uuid.UUID) -> models.Message:
    row = db.get(models.Message, message_id)
    if row is None:
        raise MessagingNotFound("That message isn't available.")
    return row


def release_message(db: Session, actor, message_id: uuid.UUID) -> dict:
    """Held → delivered. The recipient is alerted when it becomes
    their first unread — the same alert a normal send would have
    produced."""
    row = _get_message(db, message_id)
    if row.status != "held":
        raise MessagingError("That message isn't being held.")
    row.status = "sent"
    thread = get_thread(db, row.thread_id)
    if thread is not None:
        _touch_thread(thread)
        recipient = other_id(thread, row.sender_id)
        db.flush()
        if _unread_count(db, thread, recipient) == 1:
            sender = core_service.get_user_by_id(db, row.sender_id)
            _notify_message(
                db,
                recipient,
                sender.name if sender is not None else "Someone",
                thread_id=thread.id,
            )
    db.commit()
    _audit(db, actor, "message.release", row.id, {"thread_id": str(row.thread_id)})
    return _held_view(db, row)


def discard_message(db: Session, actor, message_id: uuid.UUID) -> dict:
    row = _get_message(db, message_id)
    if row.status != "held":
        raise MessagingError("That message isn't being held.")
    row.status = "discarded"
    db.commit()
    _audit(db, actor, "message.discard", row.id, {"thread_id": str(row.thread_id)})
    return _held_view(db, row)


def wipe_message(db: Session, actor, message_id: uuid.UUID) -> dict:
    """Delivered → removed: the body is destroyed; both sides keep
    a tombstone so the conversation's shape stays honest."""
    row = _get_message(db, message_id)
    if row.status != "sent":
        raise MessagingError("Only a delivered message can be wiped.")
    row.status = "removed"
    row.body = ""
    db.commit()
    _audit(db, actor, "message.wipe", row.id, {"thread_id": str(row.thread_id)})
    return _held_view(db, row)


def wipe_all_from_user(db: Session, actor, target_user_id: uuid.UUID) -> dict:
    """Every message the account ever sent: delivered ones are
    wiped to tombstones, held ones discarded. One sweep, counted."""
    rows = list(
        db.scalars(
            select(models.Message).where(models.Message.sender_id == target_user_id)
        ).all()
    )
    wiped = 0
    discarded = 0
    for row in rows:
        if row.status == "sent":
            row.status = "removed"
            row.body = ""
            wiped += 1
        elif row.status == "held":
            row.status = "discarded"
            discarded += 1
    db.commit()
    _audit(
        db,
        actor,
        "message.wipe_all",
        target_user_id,
        {"wiped": wiped, "discarded": discarded},
    )
    return {"user_id": target_user_id, "wiped": wiped, "discarded": discarded}


def ban_user(db: Session, actor, target_user_id: uuid.UUID) -> dict:
    """The queue's ban: the platform's existing machinery — the
    address is banned (every door refuses it, live sessions are
    revoked by the ban itself) and the account is deactivated.
    Nothing is deleted; an operator can reverse both halves."""
    target = core_service.get_user_by_id(db, target_user_id)
    if target is None:
        raise MessagingNotFound("That user isn't available.")
    core_service.ban_email(
        db,
        target.email,
        reason="Banned from the moderation queue (messaging).",
        banned_by=actor.id,
    )
    core_service.set_user_active(db, target, False)
    _audit(db, actor, "message.ban", target.id, {"email": target.email})
    return {"user_id": target.id, "email": target.email, "banned": True}


def lookup_recipient(db: Session, account_number: str) -> dict:
    """Resolve an EXACT account number to a messageable user —
    the platform's no-enumeration pattern (the same one preferred
    agents use): no search, no partial matches, no existence
    oracle beyond the number you already hold. Deactivated
    accounts don't resolve."""
    from app.modules.core.service import get_user_by_account_number

    user = get_user_by_account_number(db, (account_number or "").strip())
    if user is None or not user.is_active:
        raise MessagingNotFound(
            "No account with that number — check the number and try again."
        )
    return {"user_id": user.id, "display_name": user.name}


# -- public seller profile ---------------------------------------------------------


def public_profile(db: Session, user_id: uuid.UUID) -> dict | None:
    """The public seller profile (community suite): display name,
    member since, the coarse area label, the phone ONLY while the
    owner opted in, and the reputation summary — REAL since the
    Tools For Sale build: marketplace's reputation engine is the
    one aggregate function (published ratings only), read lazily
    here so the two modules never import each other at module
    scope."""
    from app.modules.marketplace import reputation

    user = core_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        return None
    phone = (
        user.contact_phone
        if (user.show_phone and (user.contact_phone or "").strip())
        else None
    )
    return {
        "user_id": user.id,
        "display_name": user.name,
        "member_since": user.created_at,
        "area_label": (user.public_area_label or "") or None,
        "show_phone": bool(user.show_phone and phone),
        "phone": phone,
        "reputation": reputation.summary_for(db, user.id),
    }
