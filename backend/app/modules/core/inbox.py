"""In-app notifications service (core module) — the inbox behind
GET /api/core/notifications, which the header ticker and the home
Notifications block already read.

NOT the outbound mailer (app/core/notifications.py sends email;
this is the in-app inbox — different system, same word).

Generation rule (owner-facing honesty + scope): a notification is
created ONLY for a real cross-party event, in the same database
commit as the event, by the service that owns the event. Today the
only cross-party events in the system are the peer-sharing
lifecycle:

  - peer_invite_received → the INVITEE: "X invited you to see their
    tool list" (only when the invite names an existing account —
    a pre-signup email invite has nobody to notify yet; it surfaces
    in the recipient's pending list when they join).
  - peer_invite_accepted → the OWNER: "X accepted your invite".
  - peer_invite_declined → the OWNER: "X declined your invite".

The borrowing module's lifecycle (2026-10-18) is the second event
family, generated the same way — in the event's own commit, by the
borrowing service, exactly once per transition (transitions are
state-guarded, so a repeated action can never duplicate one):

  - borrow_requested → the OWNER: "X asked to borrow your Y".
  - borrow_approved → the BORROWER: "X approved your borrow
    request for Y" (never for owner-initiated checkouts — there was
    no request to answer; the lend simply exists for both parties).
  - borrow_declined → the BORROWER: "X declined …".
  - borrow_request_cancelled → the OWNER: "X cancelled …".
  - borrow_returned → the OTHER party: whoever didn't mark the
    return hears that it happened, and from whom.

No self-notifications, no system/marketing filler: when a user has
no cross-party events, their inbox is empty and both UI surfaces
render nothing / their caught-up state, exactly as designed.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.core import models

KIND_PEER_INVITE_RECEIVED = "peer_invite_received"
KIND_PEER_INVITE_ACCEPTED = "peer_invite_accepted"
KIND_PEER_INVITE_DECLINED = "peer_invite_declined"

KIND_BORROW_REQUESTED = "borrow_requested"
KIND_BORROW_APPROVED = "borrow_approved"
KIND_BORROW_DECLINED = "borrow_declined"
KIND_BORROW_REQUEST_CANCELLED = "borrow_request_cancelled"
KIND_BORROW_RETURNED = "borrow_returned"

# Maintenance (2026-10-19): the jobs seam notifies a schedule's
# owner when it slips overdue — one notification per (schedule,
# due date), created by app/scripts/run_maintenance_jobs.py via
# the maintenance service, never by a request path.
KIND_MAINTENANCE_OVERDUE = "maintenance_overdue"

# Claims (2026-10-19): the jobs seam notifies a claim's owner when
# a deadline (proof of loss / recoverable depreciation) is due
# within the warning window or overdue — one notification per
# (claim, deadline, due date), created by
# app/scripts/run_claims_jobs.py via the claims service, never by
# a request path. It reads as a warning on the ticker.
KIND_CLAIM_DEADLINE = "claim_deadline"

# Warranty claims (2026-10-25): the two-party claim speaks to the
# OTHER side on every event — a claim reported to a dealer
# company lands in its agents' inboxes (NEW), and status moves,
# notes and files added by either side notify the other (UPDATE).
# Created by the claims service in the event's own commit flow.
KIND_WARRANTY_CLAIM_NEW = "warranty_claim_new"
KIND_WARRANTY_CLAIM_UPDATE = "warranty_claim_update"

# Backorder reminders (claims overhaul, 2026-11-06): the monthly
# check-in a Backordered warranty claim owes BOTH of its seats.
# Created by the claims jobs seam (run_backorder_reminders), its
# own kind so the cadence bookkeeping (the claim's
# backorder_last_reminded_at stamp) and any future preference
# stay separable from ordinary claim activity.
KIND_CLAIM_BACKORDER = "claim_backorder_reminder"

# Messaging (2026-10-19): the messaging service notifies a
# recipient when a delivered message becomes their first unread
# in an accepted thread, and an opener when their message request
# is accepted. Request-stage sends NEVER notify (the quarantine:
# first contact must not blast alerts — see messaging/service).
KIND_MESSAGE_RECEIVED = "message_received"
KIND_MESSAGE_REQUEST_ACCEPTED = "message_request_accepted"

# Community Forum (2026-10-20): the forum service notifies a
# thread's author when a reply lands — one notification per
# thread while an earlier one sits unread (first-unread only,
# the message_received pattern), created by the forum service in
# the reply's own commit (and on a moderator's release of a held
# reply, which is when the reply truly arrives).
KIND_FORUM_REPLY = "forum_reply"

# Rating moderation (gap wave 1, 2026-10-20): when a moderator
# removes a member's rating through the moderation queue, the
# rating's author hears about it — the removal is never silent
# to the person it lands on.
KIND_RATING_REMOVED = "rating_removed"

# Truck accounts (wave 2, 2026-10-20): the two-party tab speaks
# to BOTH sides on every event — a charge or payment lands in
# both inboxes with the new balance, the lifecycle transitions
# (invite accepted/declined, account closed) reach the other
# party, and the scheduler's due/overdue reminders reach the
# customer (due) and the dealer (overdue summary per account).
# Agent takeover (owner model, 2026-11-03): an agent entered a
# private agent record's code and asked to take it over
# (requested → the record's owner), and the owner's answer
# (accepted / declined → the requesting agent).
KIND_AGENT_TAKEOVER_REQUESTED = "agent_takeover_requested"
KIND_AGENT_TAKEOVER_ACCEPTED = "agent_takeover_accepted"
KIND_AGENT_TAKEOVER_DECLINED = "agent_takeover_declined"

# Agent invite reminder (owner order, 2026-11-07): a private
# agent record still unclaimed 30 days after its owner created
# it earns the owner ONE inbox nudge — invite your agent to
# join the network and sign up himself. Created by the dealers
# jobs seam (dealers.invite_reminders), never by a request
# path; its once-ever dedupe is the record's own
# invite_reminded_at stamp, written in the same commit.
KIND_AGENT_INVITE_REMINDER = "agent_invite_reminder"

KIND_TRUCK_INVITE = "truck_invite_received"
KIND_TRUCK_ACCEPTED = "truck_account_accepted"
KIND_TRUCK_DECLINED = "truck_account_declined"
KIND_TRUCK_CHARGE = "truck_charge"
KIND_TRUCK_PAYMENT = "truck_payment"
KIND_TRUCK_CLOSED = "truck_account_closed"
KIND_TRUCK_DUE = "truck_payment_due"
KIND_TRUCK_OVERDUE = "truck_payment_overdue"
# Stage 2 (2026-11-05): an agent's payment request on a
# customer-kept shared account, and the customer's answer —
# requested speaks to the CUSTOMER (their move), approved /
# declined speak back to the requesting AGENT.
KIND_TRUCK_PAYMENT_REQUESTED = "truck_payment_requested"
KIND_TRUCK_PAYMENT_REQUEST_APPROVED = "truck_payment_request_approved"
KIND_TRUCK_PAYMENT_REQUEST_DECLINED = "truck_payment_request_declined"

# Shop crews (wave 3, 2026-10-20): the invite lifecycle speaks to
# the invited employee (invite received), the shop owner (accepted
# / declined), and the departed member hears the 30-day rule's
# clock — at the leave itself, at day 25 ("5 days left"), and at
# expiry (the crew job drives the last two).
KIND_CREW_INVITE = "crew_invite_received"
KIND_CREW_ACCEPTED = "crew_invite_accepted"
KIND_CREW_DECLINED = "crew_invite_declined"
KIND_CREW_LEFT = "crew_left"
KIND_CREW_GRACE_ENDING = "crew_grace_ending"
KIND_CREW_GRACE_EXPIRED = "crew_grace_expired"

# Tier conversion (owner order, 2026-11-10): a downloads-level
# account asks for full access. REQUESTED speaks to the god
# accounts (their approval queue is the destination); APPROVED /
# DENIED speak back to the requester. Copy is written per
# recipient in the recipient's locale by core/tier_conversion.py.
KIND_CONVERSION_REQUESTED = "conversion_requested"
KIND_CONVERSION_APPROVED = "conversion_approved"
KIND_CONVERSION_DENIED = "conversion_denied"

# Feedback boards (wave 3, 2026-10-20): a poster hears when a
# moderator moves their post's status, and (first-unread, the
# forum rule) when a comment lands on their post — commenters hear
# about later comments the same way.
KIND_FEEDBACK_STATUS = "feedback_status_changed"
KIND_FEEDBACK_COMMENT = "feedback_comment"
# Boards lane (owner 2026-11-06): a NEW post on either board
# tells the ADMIN tiers (god + moderator_admin) — created by
# the feedback service for those recipients only, in the
# post's own commit. Not a poster-facing kind: the filer
# never receives it about their own post. Marvin login lane
# (same night): the audience also carries the ONE designated
# assistant account named by the `feedback.assistant_user_id`
# setting — see feedback.service.designated_assistant.
KIND_FEEDBACK_NEW_POST = "feedback_new_post"

# Feature announcements (release machinery, owner rule
# 2026-11-08): an operator-composed announcement fanned out to
# EVERY active account by the announcements job (core/
# announcements.py) — the "notification to all current users"
# every feature release owes. Deliberately absent from
# KIND_MODULE below: it is an account/system note, not a
# module's, so no module switch can hide it. The title/body are
# the operator's own words (composed in Admin); the payload
# carries the optional in-app link the composer set.
KIND_FEATURE_ANNOUNCEMENT = "feature_announcement"

# Onboarding (owner design 2026-10-31, built 2026-11-07): a
# feature module became available to an account that had already
# settled its setup — "a new feature is available, do you want
# to set it up?" Minted exactly once per (account, module) by
# core/onboarding.get_plan; the progress row is the dedupe. An
# account/system note like the kinds around it: deliberately
# absent from KIND_MODULE below, so no module switch can hide it.
KIND_ONBOARDING_NEW_FEATURE = "onboarding_new_feature"

# Locate User Manual (wave 4, 2026-10-20): the outcome is
# notified BOTH ways (owner addendum) — a manual saved to the
# item's documents, or a completed search that found none.
KIND_MANUAL_SAVED = "manual_saved"
KIND_MANUAL_NOT_FOUND = "manual_not_found"
KIND_DEALER_ROUTE_DAY = "dealer_route_day"
KIND_CLAIM_READINESS = "claim_readiness"

# Flyers (2026-11-06): a dealer or agent the user is connected
# to posted a new flyer. Created by the flyers service in the
# post's own commit; the audience is the source's connected
# users (the flyers service's visibility predicate), minus
# anyone who flipped the flyer alert's own off switch.
KIND_FLYER_POSTED = "flyer_posted"

# Content alerts (sweep E4, busy-work #6, 2026-11-12): the
# OPT-IN new-content notices — every one defaults OFF and is
# created only for users who checked the box (core
# content_alerts.py owns the prefs + fan-outs). print_file_new
# = a new listing on the 3D print shelf (prints box);
# print_file_updated = a new version of a listing the user
# follows (the per-file door on the listing page);
# download_file_new = a document appearing on the Downloads
# shelf for the first time (downloads box).
KIND_PRINT_FILE_NEW = "print_file_new"
KIND_PRINT_FILE_UPDATED = "print_file_updated"
KIND_DOWNLOAD_FILE_NEW = "download_file_new"

# Cloud backups (wave 4, 2026-10-20): a scheduled (or manual)
# Drive backup that FAILED tells its owner — successes stay
# quiet and live in the Settings -> Cloud backup history.
# The alert POLICY (first failure, then at most one alert a
# day while the streak continues, one all-clear when it ends)
# lives in app/core/backup_alerts.py (2026-10-30).
KIND_CLOUD_BACKUP_FAILED = "cloud_backup_failed"
# The streak's other end: a backup that succeeds again after
# an ALERTED failure streak tells its owner once. Successes
# with no alerted streak before them stay quiet, as they
# always have.
KIND_CLOUD_BACKUP_RECOVERED = "cloud_backup_recovered"

# Support tickets (2026-10-24): the support desk speaks BOTH
# ways. To the ticket owner — an operator reply raises
# support_reply, an operator status change raises
# support_status. To EVERY operator — a member opening a
# ticket raises support_ticket_new, a member follow-up raises
# support_ticket_reply (the desk used to hear nothing when a
# ticket arrived; the owner caught the silence testing it
# himself). All created by the support service in the event's
# own commit, never to the actor.
KIND_SUPPORT_REPLY = "support_reply"
KIND_SUPPORT_STATUS = "support_status"
KIND_SUPPORT_TICKET_NEW = "support_ticket_new"
KIND_SUPPORT_TICKET_REPLY = "support_ticket_reply"

# Community moderation (admin lane, owner ruling 2026-11-06):
# a member's FLAG on community content tells the whole
# moderation team — moderators, moderator admins AND god (a
# deliberately wider audience than the boards' new-post alert,
# which is admins-only by the owner's word). A member who is
# BLOCKED from a community feature (or unblocked) hears it in
# their own inbox: the notice names the feature and the
# support-ticket road back. All created by the flagging /
# blocking services in the event's own commit.
KIND_COMMUNITY_FLAG = "community_flag"
KIND_COMMUNITY_BLOCKED = "community_blocked"
KIND_COMMUNITY_UNBLOCKED = "community_unblocked"

# Per-user module switches (2026-10-24): which module each kind
# belongs to. When a user switches a module off, that module's
# notifications hide with it (list_for_user excludes them in the
# query; mark_all_read leaves them unread, so they return unread
# when the module returns). Kinds NOT listed here — crew_*,
# cloud_backup_failed, support_* and anything unmapped — are
# account/system notifications, not a module's, and always show.
KIND_MODULE: dict[str, str] = {
    KIND_PEER_INVITE_RECEIVED: "shared_tools",
    KIND_PEER_INVITE_ACCEPTED: "shared_tools",
    KIND_PEER_INVITE_DECLINED: "shared_tools",
    KIND_BORROW_REQUESTED: "borrowing",
    KIND_BORROW_APPROVED: "borrowing",
    KIND_BORROW_DECLINED: "borrowing",
    KIND_BORROW_REQUEST_CANCELLED: "borrowing",
    KIND_BORROW_RETURNED: "borrowing",
    KIND_MAINTENANCE_OVERDUE: "maintenance",
    KIND_CLAIM_DEADLINE: "claims",
    KIND_CLAIM_READINESS: "claims",
    KIND_MESSAGE_RECEIVED: "messaging",
    KIND_MESSAGE_REQUEST_ACCEPTED: "messaging",
    KIND_FORUM_REPLY: "forum",
    KIND_RATING_REMOVED: "marketplace",
    KIND_TRUCK_INVITE: "truck_accounts",
    KIND_TRUCK_ACCEPTED: "truck_accounts",
    KIND_TRUCK_DECLINED: "truck_accounts",
    KIND_TRUCK_CHARGE: "truck_accounts",
    KIND_TRUCK_PAYMENT: "truck_accounts",
    KIND_TRUCK_CLOSED: "truck_accounts",
    KIND_TRUCK_DUE: "truck_accounts",
    KIND_TRUCK_OVERDUE: "truck_accounts",
    KIND_TRUCK_PAYMENT_REQUESTED: "truck_accounts",
    KIND_TRUCK_PAYMENT_REQUEST_APPROVED: "truck_accounts",
    KIND_TRUCK_PAYMENT_REQUEST_DECLINED: "truck_accounts",
    KIND_FEEDBACK_STATUS: "feedback",
    KIND_FEEDBACK_COMMENT: "feedback",
    KIND_FEEDBACK_NEW_POST: "feedback",
    KIND_MANUAL_SAVED: "catalog",
    KIND_MANUAL_NOT_FOUND: "catalog",
    KIND_DEALER_ROUTE_DAY: "dealers",
    KIND_AGENT_TAKEOVER_REQUESTED: "dealers",
    KIND_AGENT_TAKEOVER_ACCEPTED: "dealers",
    KIND_AGENT_TAKEOVER_DECLINED: "dealers",
    KIND_AGENT_INVITE_REMINDER: "dealers",
    KIND_FLYER_POSTED: "flyers",
    KIND_PRINT_FILE_NEW: "prints",
    KIND_PRINT_FILE_UPDATED: "prints",
    # KIND_DOWNLOAD_FILE_NEW is deliberately ABSENT: downloads
    # is an always-on module, not a feature module, so it never
    # appears in visible_module_ids — mapping the kind to it
    # would hide the notice from everyone. Unmapped kinds are
    # account/system notes and always show (see the KIND_MODULE
    # header comment), which is the correct posture for an
    # always-on shelf the user explicitly opted into.
}

# Two-seat kinds (deep audit round 2, C-01): a kind listed here is
# visible when ANY of its seat modules is effective for the user.
# The warranty-claim kinds are the case — a warranty claim has two
# parties, the owner (claims seat) and the dealer the claim is
# addressed to (dealers seat), and the notifications are created
# for BOTH. Mapping them to "claims" alone hid every one of them
# from dealer-only accounts, whose inboxes read empty while the
# rows (and their email twins) existed — the claim page itself
# has admitted the dealer seat since 66bb8ea; the inbox now
# mirrors that same two-seat rule. No other kind widens: every
# other kind stays bound to its single module in KIND_MODULE.
KIND_MODULE_ANY: dict[str, tuple[str, ...]] = {
    KIND_WARRANTY_CLAIM_NEW: ("claims", "dealers"),
    KIND_WARRANTY_CLAIM_UPDATE: ("claims", "dealers"),
    # The backorder reminder goes to BOTH seats of the claim too
    # (claims overhaul, 2026-11-06) — same two-seat rule.
    KIND_CLAIM_BACKORDER: ("claims", "dealers"),
}


def _hidden_kinds(db: Session, user_id: uuid.UUID) -> set[str]:
    """The notification kinds hidden for this user right now: the
    kinds whose module is not in the user's visible set. A missing
    user row means no filtering (nothing to resolve switches
    against). Imported locally — module_control resolves the
    feature registry lazily for the same cycle reason."""
    user = db.get(models.User, user_id)
    if user is None:
        return set()
    from app.modules.core import module_control, tiers

    visible = module_control.visible_module_ids(
        db,
        user_id,
        user.account_types or (),
        tier=tiers.resolved_tier(user),
        beta_tester=bool(getattr(user, "beta_tester", False)),
    )
    hidden = {
        kind for kind, module_id in KIND_MODULE.items() if module_id not in visible
    }
    hidden |= {
        kind
        for kind, module_ids in KIND_MODULE_ANY.items()
        if not any(module_id in visible for module_id in module_ids)
    }
    return hidden


# The ticker fetches a bare array and rolls through it; the block
# lists the same payload. Gap wave 1 (2026-10-20, owner ask): the
# window is TIME, not a count — everything from the past 30 days,
# newest first. The page size is a transport cap only (the ticker
# takes its newest slice off the front of the same array).
WINDOW_DAYS = 30
DEFAULT_LIMIT = 100
MAX_LIMIT = 200

# Ticker dot tones (NotificationItem.tone on the client). Kinds not
# listed serialize with tone=None → the client defaults to accent.
_KIND_TONES: dict[str, str] = {
    KIND_PEER_INVITE_ACCEPTED: "success",
    KIND_BORROW_APPROVED: "success",
    KIND_BORROW_RETURNED: "success",
    KIND_CLAIM_DEADLINE: "warning",
    KIND_CLAIM_BACKORDER: "warning",
    KIND_MESSAGE_REQUEST_ACCEPTED: "success",
    KIND_TRUCK_ACCEPTED: "success",
    KIND_TRUCK_PAYMENT: "success",
    KIND_TRUCK_DUE: "warning",
    KIND_TRUCK_OVERDUE: "warning",
    KIND_TRUCK_PAYMENT_REQUESTED: "warning",
    KIND_TRUCK_PAYMENT_REQUEST_APPROVED: "success",
    KIND_TRUCK_PAYMENT_REQUEST_DECLINED: "warning",
    KIND_CREW_ACCEPTED: "success",
    KIND_CREW_GRACE_ENDING: "warning",
    KIND_CREW_GRACE_EXPIRED: "warning",
    KIND_FEEDBACK_STATUS: "success",
    KIND_FEEDBACK_NEW_POST: "warning",
    KIND_MANUAL_SAVED: "success",
    KIND_MANUAL_NOT_FOUND: "warning",
    KIND_DEALER_ROUTE_DAY: "success",
    KIND_FLYER_POSTED: "success",
    KIND_PRINT_FILE_NEW: "success",
    KIND_PRINT_FILE_UPDATED: "success",
    KIND_DOWNLOAD_FILE_NEW: "success",
    KIND_CLOUD_BACKUP_FAILED: "warning",
    KIND_CLOUD_BACKUP_RECOVERED: "success",
    KIND_SUPPORT_REPLY: "success",
    KIND_SUPPORT_STATUS: "accent",
    KIND_SUPPORT_TICKET_NEW: "warning",
    KIND_SUPPORT_TICKET_REPLY: "warning",
    KIND_FEATURE_ANNOUNCEMENT: "accent",
    KIND_COMMUNITY_FLAG: "warning",
    KIND_COMMUNITY_BLOCKED: "warning",
    KIND_COMMUNITY_UNBLOCKED: "success",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- Email twins (owner item 12, 2026-10-24) -------------------
# Every inbox notification may ALSO go out as an email, decided
# per category at send time (notification_prefs). The dispatch
# hooks HERE, the central creation path, so all kinds behave
# consistently. Two timing rules keep it honest:
#   - the email goes only AFTER the event commits (an email
#     announcing a rolled-back event would be a lie), and
#   - the mailer's outbox write commits its session, so it is
#     never called mid-transaction: commit=True dispatches
#     after its own commit; commit=False queues the payload on
#     the session and an after_commit listener sends it (an
#     after_rollback listener drops it).
# Kinds whose service sends its OWN bespoke email are skipped
# here so nobody is emailed twice — the owner's send is gated
# by the same preference (messaging's content-free message
# announcement; see messaging._notify_message).
SELF_EMAILED_KINDS = {KIND_MESSAGE_RECEIVED}


def _send_email_twin(db: Session, *, user_id: uuid.UUID, kind: str,
                     title: str, body: str) -> None:
    """Check the recipient's preference and send the email
    twin on `db`. Best-effort: a mail failure is logged, never
    raised into the event's flow (send_email itself already
    never raises)."""
    import logging

    from app.core import i18n
    from app.core import notifications as mailer
    from app.modules.core import notification_prefs

    try:
        if not notification_prefs.email_enabled_for_kind(db, user_id, kind):
            return
        user = db.get(models.User, user_id)
        if user is None:
            return
        mailer.send_notification_email(
            db,
            user.email,
            title=title,
            body=body,
            locale=i18n.resolve_locale(user),
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "notification email twin failed (user=%s kind=%s)", user_id, kind
        )


def _send_email_twin_fresh(bind, payload: dict) -> None:
    """The after-commit path: the event's session is finished,
    so the twin sends on a fresh session bound to the SAME
    engine. Failure-isolated end to end — an email problem
    must never reach back into the commit that queued it."""
    import logging

    from sqlalchemy.orm import Session as _Session

    try:
        db = _Session(bind=bind)
        try:
            _send_email_twin(db, **payload)
        finally:
            db.close()
    except Exception:
        logging.getLogger(__name__).exception(
            "notification email twin dispatch failed (kind=%s)",
            payload.get("kind"),
        )


def _queue_email_twin(db: Session, row: models.Notification) -> None:
    from sqlalchemy import event

    queue = db.info.setdefault("notification_email_queue", [])
    queue.append(
        {
            "user_id": row.user_id,
            "kind": row.kind,
            "title": row.title,
            "body": row.body,
        }
    )
    if db.info.get("notification_email_listener"):
        return
    db.info["notification_email_listener"] = True
    bind = db.get_bind()

    @event.listens_for(db, "after_commit")
    def _drain(session: Session) -> None:
        for payload in session.info.pop("notification_email_queue", []):
            _send_email_twin_fresh(bind, payload)

    @event.listens_for(db, "after_rollback")
    def _drop(session: Session) -> None:
        session.info.pop("notification_email_queue", [])


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str,
    data: dict | None = None,
    commit: bool = True,
) -> models.Notification:
    """Append one notification to a user's inbox. Event services
    call this inside their own transaction flow (commit=False lets
    the caller fold it into the event's commit)."""
    row = models.Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        data=data or {},
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
        if kind not in SELF_EMAILED_KINDS:
            _send_email_twin(
                db, user_id=user_id, kind=kind, title=title, body=body
            )
    else:
        db.flush()
        if kind not in SELF_EMAILED_KINDS:
            _queue_email_twin(db, row)
    return row


def moderation_audience(
    db: Session, *, exclude_id: uuid.UUID | None = None
) -> list:
    """The moderation team, by the tier ladder: every ACTIVE
    account whose resolved rung is moderator, moderator_admin
    or god (community moderation, owner ruling 2026-11-06 —
    flags reach all three audiences, unlike the boards'
    admins-only new-post alert). Resolved through the ladder
    so a legacy role shadow can't drift the audience."""
    from app.modules.core import tiers

    return [
        candidate
        for candidate in db.scalars(
            select(models.User).where(models.User.is_active.is_(True))
        ).all()
        if candidate.id != exclude_id
        and tiers.resolved_tier(candidate)
        in ("moderator", "moderator_admin", "god")
    ]


def notify_moderation_team(
    db: Session,
    *,
    kind: str,
    title: str,
    body: str,
    data: dict | None = None,
    exclude_id: uuid.UUID | None = None,
) -> int:
    """Fan one note out to the moderation team in the CALLER's
    transaction (commit=False — the flag's own commit carries
    the notes, and the email twins queue behind it). Returns
    the recipient count."""
    recipients = moderation_audience(db, exclude_id=exclude_id)
    for recipient in recipients:
        create_notification(
            db,
            recipient.id,
            kind=kind,
            title=title,
            body=body,
            data=data or {},
            commit=False,
        )
    return len(recipients)


def notification_view(row: models.Notification, link: str | None = None) -> dict:
    """The wire shape. `text` is the one-line rendering the header
    ticker consumes (it requires id + text; see NotificationTicker);
    title/body serve the home block and future surfaces. `link`
    is the click-through destination resolved by inbox_links
    (owner spec 2026-10-25: a click marks read AND goes to the
    source); list_for_user supplies it, resolved per page."""
    return {
        "id": str(row.id),
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "text": row.body,
        "tone": _KIND_TONES.get(row.kind),
        "data": row.data or {},
        "link": link,
        "created_at": row.created_at,
        "read_at": row.read_at,
        "read": row.read_at is not None,
    }


def list_for_user(
    db: Session,
    user_id: uuid.UUID,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    now: datetime | None = None,
) -> list[dict]:
    """The caller's notifications from the past WINDOW_DAYS days,
    newest first, paged by limit/offset (a generous default page;
    the ticker reads the newest slice off the front). Older rows
    still exist — read state, history — they simply fall out of
    the window. Owner-scoped by construction — only the caller's
    own id is ever queried."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    cutoff = (now or _now()) - timedelta(days=WINDOW_DAYS)
    hidden = _hidden_kinds(db, user_id)
    query = select(models.Notification).where(
        models.Notification.user_id == user_id,
        models.Notification.created_at >= cutoff,
    )
    if hidden:
        # Excluded IN THE QUERY, not after paging — otherwise a
        # page full of hidden rows would read as an empty inbox.
        query = query.where(models.Notification.kind.notin_(sorted(hidden)))
    rows = list(
        db.scalars(
            query.order_by(
                models.Notification.created_at.desc(), models.Notification.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    )
    # Click-through links (owner spec 2026-10-25), resolved for
    # the whole page in one batched pass. A missing user row
    # resolves nothing (links stay None; clicks keep the old
    # mark-read-only behavior) rather than failing the list.
    links: dict[uuid.UUID, str | None] = {}
    user = db.get(models.User, user_id)
    if user is not None and rows:
        from app.modules.core import inbox_links

        links = inbox_links.resolve_links(db, user, rows)
    return [notification_view(r, link=links.get(r.id)) for r in rows]


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """Mark one of the CALLER's notifications read. A foreign or
    unknown id returns False (the route answers 404 — no oracle).
    Already-read is a no-op success (idempotent)."""
    row = db.scalars(
        select(models.Notification).where(
            models.Notification.id == notification_id,
            models.Notification.user_id == user_id,
        )
    ).first()
    if row is None:
        return False
    if row.read_at is None:
        row.read_at = _now()
        db.commit()
    return True


def delete_for_user(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """Delete one of the CALLER's notifications outright. A
    foreign or unknown id returns False (the route answers 404 —
    no oracle), mirroring mark_read's shape."""
    row = db.scalars(
        select(models.Notification).where(
            models.Notification.id == notification_id,
            models.Notification.user_id == user_id,
        )
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    """Mark everything in the caller's inbox read; returns how many
    rows changed. Notifications hidden by a switched-off module
    are NOT marked — they keep their unread state and return
    unread when the module returns (same exclusion as the list)."""
    hidden = _hidden_kinds(db, user_id)
    statement = update(models.Notification).where(
        models.Notification.user_id == user_id,
        models.Notification.read_at.is_(None),
    )
    if hidden:
        statement = statement.where(
            models.Notification.kind.notin_(sorted(hidden))
        )
    result = db.execute(statement.values(read_at=_now()))
    db.commit()
    return int(result.rowcount or 0)


# -- peer-sharing lifecycle events (called by peer_sharing.py) -----------------


def _actor_data(actor: models.User, grant_id: uuid.UUID) -> dict:
    return {
        "grant_id": str(grant_id),
        "actor_id": str(actor.id),
        "actor_name": actor.name,
        "actor_account_number": actor.account_number,
    }


def peer_invite_received(
    db: Session, *, owner: models.User, invitee_id: uuid.UUID, grant_id: uuid.UUID
) -> None:
    """The owner just invited `invitee_id`. Folded into the invite's
    own commit by the caller (commit=False)."""
    create_notification(
        db,
        invitee_id,
        kind=KIND_PEER_INVITE_RECEIVED,
        title="Tool list invite",
        body=f"{owner.name} invited you to see their tool list.",
        data=_actor_data(owner, grant_id),
        commit=False,
    )


def peer_invite_accepted(
    db: Session, *, invitee: models.User, owner_id: uuid.UUID, grant_id: uuid.UUID
) -> None:
    create_notification(
        db,
        owner_id,
        kind=KIND_PEER_INVITE_ACCEPTED,
        title="Invite accepted",
        body=f"{invitee.name} accepted your tool-list invite.",
        data=_actor_data(invitee, grant_id),
        commit=False,
    )


def peer_invite_declined(
    db: Session, *, invitee: models.User, owner_id: uuid.UUID, grant_id: uuid.UUID
) -> None:
    create_notification(
        db,
        owner_id,
        kind=KIND_PEER_INVITE_DECLINED,
        title="Invite declined",
        body=f"{invitee.name} declined your tool-list invite.",
        data=_actor_data(invitee, grant_id),
        commit=False,
    )


# -- borrowing lifecycle events (called by the borrowing service) --------------
#
# Users are passed as (id, name) pairs, not rows: the borrowing
# service works from its own ledger snapshots and shouldn't have to
# re-fetch accounts to phrase a sentence about them.


def _borrow_data(
    checkout_id: uuid.UUID,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> dict:
    """The deep-link payload: enough for a client to open the lend
    (or the item) from the notification. Names live in `body`."""
    return {
        "checkout_id": str(checkout_id),
        "item_kind": item_kind,
        "item_id": str(item_id),
        "item_name": item_name,
    }


def borrow_requested(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    owner_id: uuid.UUID,
    requester_name: str,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> None:
    """A linked borrower asked for an item. To the OWNER."""
    create_notification(
        db,
        owner_id,
        kind=KIND_BORROW_REQUESTED,
        title="Borrow request",
        body=f"{requester_name} asked to borrow your {item_name}.",
        data=_borrow_data(
            checkout_id,
            item_kind=item_kind,
            item_id=item_id,
            item_name=item_name,
        ),
        commit=False,
    )


def borrow_approved(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    borrower_id: uuid.UUID,
    owner_name: str,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> None:
    """The owner approved a request. To the BORROWER."""
    create_notification(
        db,
        borrower_id,
        kind=KIND_BORROW_APPROVED,
        title="Request approved",
        body=f"{owner_name} approved your borrow request for {item_name}.",
        data=_borrow_data(
            checkout_id,
            item_kind=item_kind,
            item_id=item_id,
            item_name=item_name,
        ),
        commit=False,
    )


def borrow_declined(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    borrower_id: uuid.UUID,
    owner_name: str,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> None:
    """The owner declined a request. To the BORROWER."""
    create_notification(
        db,
        borrower_id,
        kind=KIND_BORROW_DECLINED,
        title="Request declined",
        body=f"{owner_name} declined your borrow request for {item_name}.",
        data=_borrow_data(
            checkout_id,
            item_kind=item_kind,
            item_id=item_id,
            item_name=item_name,
        ),
        commit=False,
    )


def borrow_request_cancelled(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    owner_id: uuid.UUID,
    requester_name: str,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> None:
    """The borrower withdrew a pending request. To the OWNER —
    otherwise the request just vanishes from their queue silently."""
    create_notification(
        db,
        owner_id,
        kind=KIND_BORROW_REQUEST_CANCELLED,
        title="Request cancelled",
        body=f"{requester_name} cancelled their borrow request for {item_name}.",
        data=_borrow_data(
            checkout_id,
            item_kind=item_kind,
            item_id=item_id,
            item_name=item_name,
        ),
        commit=False,
    )


def borrow_returned(
    db: Session,
    *,
    checkout_id: uuid.UUID,
    notify_user_id: uuid.UUID,
    actor_name: str,
    actor_is_owner: bool,
    item_kind: str,
    item_id: uuid.UUID,
    item_name: str,
) -> None:
    """A checkout was marked returned. To the OTHER party — the one
    who didn't perform the return (the actor already knows)."""
    if actor_is_owner:
        body = f"{actor_name} marked {item_name} as returned."
    else:
        body = f"{actor_name} returned your {item_name}."
    create_notification(
        db,
        notify_user_id,
        kind=KIND_BORROW_RETURNED,
        title="Item returned",
        body=body,
        data=_borrow_data(
            checkout_id,
            item_kind=item_kind,
            item_id=item_id,
            item_name=item_name,
        ),
        commit=False,
    )


# -- rating moderation events (called by marketplace reputation) ---------------


def rating_removed(
    db: Session,
    *,
    rater_id: uuid.UUID,
    context_title: str = "",
    thread_id: uuid.UUID | None = None,
) -> None:
    """A moderator removed MY rating. To the rating's AUTHOR —
    their review no longer counts and its text is replaced; they
    should hear that from the platform, not discover it. The
    deal thread rides along (when the interaction has one) so
    the click-through can land on the conversation the review
    belonged to."""
    about = f" for “{context_title}”" if context_title else ""
    data: dict = {"context_title": context_title}
    if thread_id is not None:
        data["thread_id"] = str(thread_id)
    create_notification(
        db,
        rater_id,
        kind=KIND_RATING_REMOVED,
        title="Review removed",
        body=(
            f"A moderator removed your review{about}. It no longer "
            "counts toward the other member's rating."
        ),
        data=data,
    )


# -- truck account events (called by the truck_accounts module) -----------------


def _truck_data(account_id, **extra) -> dict:
    return {"account_id": str(account_id), **extra}


def truck_invite_received(
    db: Session, *, customer_id: uuid.UUID, account_id, dealer_name: str
) -> None:
    """A dealer opened a truck account FOR me — my move (accept
    the agreement or decline)."""
    create_notification(
        db,
        customer_id,
        kind=KIND_TRUCK_INVITE,
        title="Truck account invite",
        body=(
            f"{dealer_name} opened a truck account for you. Review "
            "the agreement to accept it, or decline to close it."
        ),
        data=_truck_data(account_id),
        commit=False,
    )


def truck_account_accepted(
    db: Session, *, dealer_id: uuid.UUID, account_id, customer_name: str
) -> None:
    create_notification(
        db,
        dealer_id,
        kind=KIND_TRUCK_ACCEPTED,
        title="Truck account accepted",
        body=f"{customer_name} accepted their truck account agreement.",
        data=_truck_data(account_id),
        commit=False,
    )


def truck_account_declined(
    db: Session, *, dealer_id: uuid.UUID, account_id, customer_name: str
) -> None:
    create_notification(
        db,
        dealer_id,
        kind=KIND_TRUCK_DECLINED,
        title="Truck account declined",
        body=f"{customer_name} declined the truck account. It is closed.",
        data=_truck_data(account_id),
        commit=False,
    )


def truck_entry_posted(
    db: Session,
    *,
    account_id,
    kind: str,
    amount_text: str,
    balance_text: str,
    dealer_id: uuid.UUID | None,
    customer_id: uuid.UUID | None,
    dealer_name: str,
    customer_name: str,
    by_customer: bool,
) -> None:
    """One ledger entry, BOTH inboxes (the wave-2 rule: every
    charge and every payment notifies both parties with the new
    balance). Adjustments notify too — a silent adjustment is
    how tabs go wrong. A side whose account was deleted gets
    nothing (their id is None / flagged by the caller)."""
    if kind == "charge":
        nkind = KIND_TRUCK_CHARGE
        to_customer = (
            f"You were charged {amount_text} by {dealer_name} — "
            f"balance {balance_text}."
        )
        to_dealer = (
            f"You charged {customer_name} {amount_text} — "
            f"balance {balance_text}."
        )
    elif kind == "payment":
        nkind = KIND_TRUCK_PAYMENT
        payer = customer_name if by_customer else dealer_name
        to_customer = (
            f"A payment of {amount_text} was recorded on your truck "
            f"account — balance {balance_text}."
        )
        to_dealer = (
            f"{payer} paid {amount_text} on the truck account — "
            f"balance {balance_text}."
        )
    else:  # adjustment
        nkind = KIND_TRUCK_CHARGE
        to_customer = (
            f"An adjustment of {amount_text} was recorded on your "
            f"truck account — balance {balance_text}."
        )
        to_dealer = (
            f"An adjustment of {amount_text} was recorded for "
            f"{customer_name} — balance {balance_text}."
        )
    if customer_id is not None:
        create_notification(
            db, customer_id, kind=nkind,
            title="Truck account",
            body=to_customer,
            data=_truck_data(account_id),
            commit=False,
        )
    if dealer_id is not None:
        create_notification(
            db, dealer_id, kind=nkind,
            title="Truck account",
            body=to_dealer,
            data=_truck_data(account_id),
            commit=False,
        )


def truck_account_closed(
    db: Session,
    *,
    account_id,
    notify_user_id: uuid.UUID | None,
    other_name: str,
) -> None:
    if notify_user_id is None:
        return
    create_notification(
        db,
        notify_user_id,
        kind=KIND_TRUCK_CLOSED,
        title="Truck account closed",
        body=(
            f"The truck account with {other_name} was closed. The "
            "ledger is frozen — its history stays on record."
        ),
        data=_truck_data(account_id),
        commit=False,
    )


def truck_payment_due(
    db: Session,
    *,
    customer_id: uuid.UUID,
    account_id,
    dealer_name: str,
    amount_text: str,
    due_text: str,
) -> None:
    create_notification(
        db,
        customer_id,
        kind=KIND_TRUCK_DUE,
        title="Truck payment coming due",
        body=(
            f"Your {amount_text} truck payment to {dealer_name} is "
            f"due {due_text}."
        ),
        data=_truck_data(account_id),
        commit=False,
    )


def truck_payment_overdue(
    db: Session,
    *,
    user_id: uuid.UUID,
    account_id,
    other_name: str,
    amount_text: str,
    balance_text: str,
    audience: str,
) -> None:
    """Overdue speaks to both sides (audience "customer" |
    "dealer" picks the wording)."""
    if audience == "customer":
        body = (
            f"Your truck payment to {other_name} is overdue — "
            f"balance {balance_text}. Please arrange payment."
        )
    else:
        body = (
            f"{other_name}'s truck payment of {amount_text} is "
            f"overdue — balance {balance_text}."
        )
    create_notification(
        db,
        user_id,
        kind=KIND_TRUCK_OVERDUE,
        title="Truck payment overdue",
        body=body,
        data=_truck_data(account_id),
        commit=False,
    )
