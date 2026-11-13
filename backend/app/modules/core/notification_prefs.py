"""Per-category notification CHANNEL preferences (owner item
12, 2026-10-24).

The bell (the in-app inbox) is the base layer — always on,
never modeled here. On top of it, each notification CATEGORY
carries channel choices; today the only live channel is
"email", and the model/API are channel-shaped so push and
SMS slot in later without a rebuild (no provider is wired for
them and nothing sends on them yet).

A category's email default: ON for the categories a user is
plausibly WAITING on — support answers, new messages, claim
deadlines, and account/system events (a failed cloud backup,
a finished manual hunt, a removed rating, plus every future
unmapped kind) — and OFF for the routine traffic (borrowing,
sharing, maintenance reminders, community, truck-account
ledger noise, crew, dealer workday events). A stored row
(models.NotificationChannelPref) exists only where the user
flipped a category away from its default; the effective
value is resolved at SEND time, in the inbox creation path,
so a flip takes effect on the next event — including events
already in flight.

Disaster Vault system mail (the weekly digest + failure
alerts to the operator) is NOT a user notification and never
passes through here: the backup job calls the mailer
directly, outside the inbox entirely.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import inbox, models

CHANNEL_EMAIL = "email"
SUPPORTED_CHANNELS = (CHANNEL_EMAIL,)

CATEGORY_SUPPORT = "support"
CATEGORY_MESSAGES = "messages"
CATEGORY_CLAIMS = "claims"
CATEGORY_ACCOUNT = "account"
CATEGORY_BORROWING = "borrowing"
CATEGORY_SHARING = "sharing"
CATEGORY_MAINTENANCE = "maintenance"
CATEGORY_COMMUNITY = "community"
CATEGORY_TRUCK_ACCOUNTS = "truck_accounts"
CATEGORY_CREW = "crew"
CATEGORY_DEALERS = "dealers"
# Flyers (2026-11-06): the EMAIL channel's category for the
# flyer_posted kind. The inbox alert itself carries its own
# per-user switch in the flyers module (flyer_alert_prefs) —
# this category governs only the email twin, like every other
# category here governs its kinds' twins.
CATEGORY_FLYERS = "flyers"
# Feature announcements (release machinery, 2026-11-08): the
# operator broadcast to all users gets its own category so the
# inbox labels it as what it is ("New features"). The email
# twin's default is OFF — an announcement is an inbox event;
# emailing the whole user base on every release is the Resend
# quota burn the email discipline rule exists to prevent. A
# user who flips it on is honored by the fan-out job, which
# creates rows through the central inbox path like any event.
CATEGORY_ANNOUNCEMENTS = "announcements"
# Content alerts (sweep E4, 2026-11-12): the email-twin
# categories for the opt-in new-content kinds. The INBOX
# opt-in itself lives in core content_alerts (default OFF);
# these categories govern only the email twins, and their
# email defaults are OFF like the flyers' — an opted-in user
# gets the inbox note, not an email, unless they also flip
# the email toggle here.
CATEGORY_DOWNLOADS = "downloads"
CATEGORY_PRINTS = "prints"

# Display order on Settings -> Notifications.
CATEGORIES: tuple[str, ...] = (
    CATEGORY_SUPPORT,
    CATEGORY_MESSAGES,
    CATEGORY_CLAIMS,
    CATEGORY_BORROWING,
    CATEGORY_SHARING,
    CATEGORY_MAINTENANCE,
    CATEGORY_COMMUNITY,
    CATEGORY_TRUCK_ACCOUNTS,
    CATEGORY_CREW,
    CATEGORY_DEALERS,
    CATEGORY_FLYERS,
    CATEGORY_ANNOUNCEMENTS,
    CATEGORY_DOWNLOADS,
    CATEGORY_PRINTS,
    CATEGORY_ACCOUNT,
)

CATEGORY_EMAIL_DEFAULTS: dict[str, bool] = {
    CATEGORY_SUPPORT: True,
    CATEGORY_MESSAGES: True,
    CATEGORY_CLAIMS: True,
    CATEGORY_ACCOUNT: True,
    CATEGORY_BORROWING: False,
    CATEGORY_SHARING: False,
    CATEGORY_MAINTENANCE: False,
    CATEGORY_COMMUNITY: False,
    CATEGORY_TRUCK_ACCOUNTS: False,
    CATEGORY_CREW: False,
    CATEGORY_DEALERS: False,
    CATEGORY_FLYERS: False,
    CATEGORY_ANNOUNCEMENTS: False,
    CATEGORY_DOWNLOADS: False,
    CATEGORY_PRINTS: False,
}

# Kind -> category. Kinds NOT listed here land in CATEGORY_ACCOUNT
# (the account/system bucket) — a new kind can never fall out of
# the preference system by accident.
KIND_CATEGORY: dict[str, str] = {
    inbox.KIND_SUPPORT_REPLY: CATEGORY_SUPPORT,
    inbox.KIND_SUPPORT_STATUS: CATEGORY_SUPPORT,
    inbox.KIND_SUPPORT_TICKET_NEW: CATEGORY_SUPPORT,
    inbox.KIND_SUPPORT_TICKET_REPLY: CATEGORY_SUPPORT,
    inbox.KIND_MESSAGE_RECEIVED: CATEGORY_MESSAGES,
    inbox.KIND_MESSAGE_REQUEST_ACCEPTED: CATEGORY_MESSAGES,
    inbox.KIND_CLAIM_DEADLINE: CATEGORY_CLAIMS,
    inbox.KIND_CLAIM_READINESS: CATEGORY_CLAIMS,
    inbox.KIND_WARRANTY_CLAIM_NEW: CATEGORY_CLAIMS,
    inbox.KIND_WARRANTY_CLAIM_UPDATE: CATEGORY_CLAIMS,
    inbox.KIND_CLAIM_BACKORDER: CATEGORY_CLAIMS,
    inbox.KIND_BORROW_REQUESTED: CATEGORY_BORROWING,
    inbox.KIND_BORROW_APPROVED: CATEGORY_BORROWING,
    inbox.KIND_BORROW_DECLINED: CATEGORY_BORROWING,
    inbox.KIND_BORROW_REQUEST_CANCELLED: CATEGORY_BORROWING,
    inbox.KIND_BORROW_RETURNED: CATEGORY_BORROWING,
    inbox.KIND_PEER_INVITE_RECEIVED: CATEGORY_SHARING,
    inbox.KIND_PEER_INVITE_ACCEPTED: CATEGORY_SHARING,
    inbox.KIND_PEER_INVITE_DECLINED: CATEGORY_SHARING,
    inbox.KIND_MAINTENANCE_OVERDUE: CATEGORY_MAINTENANCE,
    inbox.KIND_FORUM_REPLY: CATEGORY_COMMUNITY,
    inbox.KIND_FEEDBACK_STATUS: CATEGORY_COMMUNITY,
    inbox.KIND_FEEDBACK_COMMENT: CATEGORY_COMMUNITY,
    # The admin-tier new-post alert rides the community
    # category too — its email default is OFF, so the alert
    # is an inbox/bell note unless an admin opts into email.
    inbox.KIND_FEEDBACK_NEW_POST: CATEGORY_COMMUNITY,
    # Community moderation (admin lane, owner 2026-11-06): the
    # flag alert to the moderation team and the block/unblock
    # notices to the member ride the community category too —
    # inbox-first, email only for members who opt in.
    inbox.KIND_COMMUNITY_FLAG: CATEGORY_COMMUNITY,
    inbox.KIND_COMMUNITY_BLOCKED: CATEGORY_COMMUNITY,
    inbox.KIND_COMMUNITY_UNBLOCKED: CATEGORY_COMMUNITY,
    inbox.KIND_TRUCK_INVITE: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_ACCEPTED: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_DECLINED: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_CHARGE: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_PAYMENT: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_CLOSED: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_DUE: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_OVERDUE: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_PAYMENT_REQUESTED: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_PAYMENT_REQUEST_APPROVED: CATEGORY_TRUCK_ACCOUNTS,
    inbox.KIND_TRUCK_PAYMENT_REQUEST_DECLINED: CATEGORY_TRUCK_ACCOUNTS,
    # The truck module's transfer kind (2026-10-31) — a literal
    # key: the constant lives with the truck service that emits
    # it (truck_accounts.service.KIND_TRUCK_TRANSFERRED).
    "truck_account_transferred": CATEGORY_TRUCK_ACCOUNTS,
    # Agent takeover (2026-11-03): an account-linking event —
    #    the Account bucket, with the crew invites' family.
    inbox.KIND_AGENT_TAKEOVER_REQUESTED: CATEGORY_ACCOUNT,
    inbox.KIND_AGENT_TAKEOVER_ACCEPTED: CATEGORY_ACCOUNT,
    inbox.KIND_AGENT_TAKEOVER_DECLINED: CATEGORY_ACCOUNT,
    inbox.KIND_CREW_INVITE: CATEGORY_CREW,
    inbox.KIND_CREW_ACCEPTED: CATEGORY_CREW,
    inbox.KIND_CREW_DECLINED: CATEGORY_CREW,
    inbox.KIND_CREW_LEFT: CATEGORY_CREW,
    inbox.KIND_CREW_GRACE_ENDING: CATEGORY_CREW,
    inbox.KIND_CREW_GRACE_EXPIRED: CATEGORY_CREW,
    inbox.KIND_DEALER_ROUTE_DAY: CATEGORY_DEALERS,
    # The 30-day agent invite reminder (2026-11-07) rides the
    # dealers category like the route-day note: inbox-first —
    # the category's email default is OFF, so the reminder is
    # an inbox note unless the owner opted into dealer email.
    inbox.KIND_AGENT_INVITE_REMINDER: CATEGORY_DEALERS,
    inbox.KIND_FLYER_POSTED: CATEGORY_FLYERS,
    inbox.KIND_DOWNLOAD_FILE_NEW: CATEGORY_DOWNLOADS,
    inbox.KIND_PRINT_FILE_NEW: CATEGORY_PRINTS,
    inbox.KIND_PRINT_FILE_UPDATED: CATEGORY_PRINTS,
    inbox.KIND_FEATURE_ANNOUNCEMENT: CATEGORY_ANNOUNCEMENTS,
    "warranty_request_received": CATEGORY_DEALERS,
    "warranty_request_claimed": CATEGORY_DEALERS,
    "warranty_request_status": CATEGORY_DEALERS,
    inbox.KIND_CLOUD_BACKUP_FAILED: CATEGORY_ACCOUNT,
    inbox.KIND_CLOUD_BACKUP_RECOVERED: CATEGORY_ACCOUNT,
    inbox.KIND_MANUAL_SAVED: CATEGORY_ACCOUNT,
    inbox.KIND_MANUAL_NOT_FOUND: CATEGORY_ACCOUNT,
    inbox.KIND_RATING_REMOVED: CATEGORY_ACCOUNT,
}


def category_for_kind(kind: str) -> str:
    return KIND_CATEGORY.get(kind, CATEGORY_ACCOUNT)


def _stored_pref(
    db: Session, user_id: uuid.UUID, category: str, channel: str
) -> models.NotificationChannelPref | None:
    return db.scalar(
        select(models.NotificationChannelPref).where(
            models.NotificationChannelPref.user_id == user_id,
            models.NotificationChannelPref.category == category,
            models.NotificationChannelPref.channel == channel,
        )
    )


def channel_enabled(
    db: Session, user_id: uuid.UUID, category: str, channel: str
) -> bool:
    """The effective value: the stored flip when one exists,
    else the category default (email is the only channel with
    defaults today; any future channel defaults OFF until it
    ships)."""
    row = _stored_pref(db, user_id, category, channel)
    if row is not None:
        return bool(row.enabled)
    if channel == CHANNEL_EMAIL:
        return CATEGORY_EMAIL_DEFAULTS.get(category, False)
    return False


def email_enabled_for_kind(db: Session, user_id: uuid.UUID, kind: str) -> bool:
    """The send-time question the inbox email hook asks."""
    return channel_enabled(db, user_id, category_for_kind(kind), CHANNEL_EMAIL)


def set_channel_pref(
    db: Session,
    user_id: uuid.UUID,
    *,
    category: str,
    channel: str,
    enabled: bool,
) -> models.NotificationChannelPref:
    row = _stored_pref(db, user_id, category, channel)
    if row is None:
        row = models.NotificationChannelPref(
            user_id=user_id, category=category, channel=channel, enabled=enabled
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def preferences_view(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Every category with its effective channel states, in
    display order — the Settings -> Notifications payload."""
    return [
        {
            "category": category,
            "email_enabled": channel_enabled(
                db, user_id, category, CHANNEL_EMAIL
            ),
        }
        for category in CATEGORIES
    ]
