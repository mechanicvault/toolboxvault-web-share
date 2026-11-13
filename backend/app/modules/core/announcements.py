"""Feature announcements (release machinery, owner rule
2026-11-08): the "notification to ALL current users" every new
feature ships with.

Shape: an operator (god or a moderator admin — the user-manager
gate) composes a title, a few lines of body and an optional
in-app link in Admin -> Announcements. Composing writes ONE
feature_announcements row as "queued" — the request never fans
out itself. The announcements job (app/scripts/
run_announcement_jobs.py, on the scheduler's minute cadence)
picks queued rows up and creates one inbox notification per
recipient through the central inbox path, then flips the row to
"sent" with the recipient count and timestamp.

Inclusion rule: EVERY ACTIVE account (users.is_active) — all
tiers, all account-type groups, operators included. Deactivated
accounts are excluded: they cannot sign in to read an inbox,
and the moderation audience (inbox.moderation_audience) sets
the same is_active precedent. There is no machine notion of a
"test account" in the codebase — the smoke-test and assistant
accounts are ordinary user rows — so they are included like
anyone else's; the operator sees the recipient count on the
history row before it matters.

Scoped rows (2026-11-09): a row queued by a module tier flip
(module_release.py) carries release_module_id + an explicit
audience_user_ids list — the accounts that gained the module in
that flip. Its fan-out reaches exactly the listed accounts that
are still active, and its copy renders per recipient from the
release templates below. Rows without the scoping (every
operator-composed announcement) behave as they always have.

Language (owner rule, 2026-11-10, broadened same day):
NOTHING user-facing appears in a language other than the
user's own choice — inbox announcements included. A compose
therefore carries per-language parts (title_es / body_en /
body_es, migration 0102) and the fan-out renders EVERY
recipient's copy — inbox entry and email twin alike — from
recipient_copy_for below, in that recipient's resolved locale
only. The stored title/body are the English rendering (the
Admin history's record, the 0096 precedent). A compose with
no part for a recipient's locale falls back to the stored
words: one language, never a stacked pair.

Immutability: a created announcement is never edited and never
re-sent. There is deliberately no update/delete path — a
correction is a new announcement. The fan-out is idempotent by
status: only "queued" rows are picked up, and the flip to
"sent" commits in the same transaction as the last recipient
rows, so a job crash mid-fan-out rolls the whole send back to
"queued" and the next run retries it whole — nobody is
announced twice, nobody is half-announced.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import i18n
from app.modules.core import inbox, models

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


# -- module release announcements (owner order, 2026-11-09) -------
#
# When an admin's tier flip opens a module to accounts that didn't
# have it, the flip queues a SCOPED announcement (module_release.py
# does the queuing): release_module_id names the feature and
# audience_user_ids carries the exact accounts that gained it.
# The stored title/body are the English rendering below — the
# Admin history's record — and the fan-out renders each
# recipient's copy from these templates in the recipient's own
# language. The feature names mirror the client dictionary's
# modules.name.* entries (the same words the wizard's step titles
# wear); the manifest name is the fallback for a module the map
# doesn't know.

RELEASE_TITLES = {
    "en": "New feature: {name}",
    "es": "Función nueva: {name}",
}
RELEASE_BODIES = {
    "en": (
        "{name} is now open on your account — you'll find it in "
        "your menu, marked NEW. The first time you open it, a "
        "short setup walkthrough will help you make it yours."
    ),
    "es": (
        "{name} ya está disponible en su cuenta: lo encontrará "
        "en su menú, marcado como NUEVO. La primera vez que lo "
        "abra, un breve recorrido de configuración le ayudará a "
        "dejarlo a su manera."
    ),
}
RELEASE_MODULE_NAMES = {
    "en": {
        "inventory": "Inventory",
        "shared_tools": "Shared tools",
        "borrowing": "Borrowing",
        "dealers": "Dealer directory",
        "reports": "Reports",
        "maintenance": "Repairs & maintenance",
        "claims": "Claims",
        "parts": "My Parts",
        "messaging": "Messages",
        "marketplace": "Tools for sale",
        "forum": "Community Forum",
        "wishlist": "Wishlist",
        "tool_expansion": "Tool Expansion",
        "truck_accounts": "Truck accounts",
        "feedback": "Feedback",
        "catalog": "Product catalog",
        "support": "Help & Support",
        "ai_assistant": "AI assistant",
        "flyers": "Dealer flyers",
        "disaster_claims": "Disaster claims",
        "prints": "3D Print Files",
    },
    "es": {
        "inventory": "Inventario",
        "shared_tools": "Herramientas compartidas",
        "borrowing": "Préstamos",
        "dealers": "Directorio de distribuidores",
        "reports": "Informes",
        "maintenance": "Reparaciones y mantenimiento",
        "claims": "Reclamos",
        "parts": "Mis repuestos",
        "messaging": "Mensajes",
        "marketplace": "Herramientas en venta",
        "forum": "Foro de la comunidad",
        "wishlist": "Lista de deseos",
        "tool_expansion": "Expansión de herramientas",
        "truck_accounts": "Cuentas de camión de herramientas",
        "feedback": "Comentarios",
        "catalog": "Catálogo de productos",
        "support": "Ayuda y soporte",
        "ai_assistant": "Asistente de IA",
        "flyers": "Folletos de distribuidores",
        "disaster_claims": "Reclamos por desastre",
        "prints": "Archivos de impresión 3D",
    },
}


def release_copy(module_id: str, locale: str) -> tuple[str, str]:
    """The (title, body) of a module's release announcement in
    one shipped locale — the words the flip queues (English, for
    the stored row) and the fan-out renders per recipient."""
    locale = locale if locale in RELEASE_TITLES else "en"
    from app.modules.registry import FEATURE_MODULES

    manifest = FEATURE_MODULES.get(module_id)
    fallback = manifest.name if manifest is not None else module_id
    name = RELEASE_MODULE_NAMES[locale].get(module_id, fallback)
    return (
        RELEASE_TITLES[locale].format(name=name),
        RELEASE_BODIES[locale].format(name=name),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _part(value: str | None) -> str | None:
    """Normalize one per-language part for storage: stripped,
    and blank means absent (NULL — the fan-out then falls back
    to the stored title/body for that language)."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def queue_announcement(
    db: Session,
    *,
    author_id: uuid.UUID,
    author_name: str,
    title: str,
    body: str,
    link: str | None,
    release_module_id: str | None = None,
    audience_user_ids: list[str] | None = None,
    title_es: str | None = None,
    body_en: str | None = None,
    body_es: str | None = None,
) -> models.FeatureAnnouncement:
    """Land a composed announcement as queued. The caller (the
    admin route) validates the fields and audits the act; this
    writes the row and commits. The two release kwargs are the
    module flip's scoping (2026-11-09): both stay None for an
    operator-composed announcement, which keeps the original
    everyone-active audience. The three part kwargs are the
    per-language compose (2026-11-10): the fan-out renders each
    recipient's copy from the parts (recipient_copy_for). When
    body_en is composed, IT becomes the stored body — the
    stored title/body are the English rendering the Admin
    history reads, and nothing stacked is ever stored; `body`
    remains the compose text for single-language announcements
    (and the release rows' stored English rendering)."""
    body_en_part = _part(body_en)
    row = models.FeatureAnnouncement(
        title=title,
        body=body_en_part if body_en_part is not None else body,
        link=link or None,
        status=STATUS_QUEUED,
        created_by_id=author_id,
        created_by_name=author_name or "",
        release_module_id=release_module_id,
        audience_user_ids=list(audience_user_ids)
        if audience_user_ids is not None
        else None,
        title_es=_part(title_es),
        body_en=body_en_part,
        body_es=_part(body_es),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def announcement_view(row: models.FeatureAnnouncement) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "body": row.body,
        "title_es": row.title_es,
        "body_en": row.body_en,
        "body_es": row.body_es,
        "link": row.link,
        "status": row.status,
        "recipient_count": row.recipient_count,
        "created_by_id": str(row.created_by_id) if row.created_by_id else None,
        "created_by_name": row.created_by_name,
        "created_at": row.created_at,
        "sent_at": row.sent_at,
    }


def list_announcements(db: Session, *, limit: int = 50) -> list[dict]:
    """The Admin history, newest first."""
    limit = max(1, min(int(limit), 200))
    rows = list(
        db.scalars(
            select(models.FeatureAnnouncement)
            .order_by(
                models.FeatureAnnouncement.created_at.desc(),
                models.FeatureAnnouncement.id.desc(),
            )
            .limit(limit)
        )
    )
    return [announcement_view(r) for r in rows]


def active_recipients(db: Session) -> list[models.User]:
    """The announcement audience: every active account (see the
    module docstring for the inclusion rule)."""
    return list(
        db.scalars(
            select(models.User).where(models.User.is_active.is_(True))
        ).all()
    )


def _recipients_for(db: Session, row: models.FeatureAnnouncement) -> list[models.User]:
    """The fan-out's audience for one row. An unscoped row reaches
    every active account (the original rule). A release row
    (audience_user_ids set by the tier flip) reaches exactly the
    listed accounts that are still active at send time — the
    list is the flip's snapshot of who gained the module, and
    deactivation since then still excludes, like everyone else."""
    audience = active_recipients(db)
    if row.audience_user_ids is None:
        return audience
    wanted = {str(raw) for raw in row.audience_user_ids}
    return [user for user in audience if str(user.id) in wanted]


def recipient_copy_for(
    row: models.FeatureAnnouncement, recipient: models.User
) -> tuple[str, str]:
    """The (title, body) of one recipient's copy of this
    announcement — inbox entry and email twin alike (the
    single-language rule, owner 2026-11-10: nothing user-facing
    appears in a language other than the user's own choice).

    - A release row renders from the release templates in the
      recipient's locale.
    - An operator row renders the recipient-locale part when
      one was composed (body_es, with title_es, for Spanish;
      the stored title/body — the English rendering — for
      English) and falls back to the stored title/body when no
      part exists for that locale: one language, never both.
    """
    if row.release_module_id:
        return release_copy(
            row.release_module_id, i18n.resolve_locale(recipient)
        )
    if i18n.resolve_locale(recipient) == "es":
        return (row.title_es or row.title, row.body_es or row.body)
    return (row.title, row.body)


def send_announcement(db: Session, row: models.FeatureAnnouncement) -> int:
    """Fan one queued announcement out to its audience (everyone
    active, or the release row's scoped list — _recipients_for).
    Every recipient row is created through the central inbox
    path (commit=False) so module visibility, tones and the
    email-twin preference behave exactly like any other kind —
    the announcements category's email default is OFF, so the
    twin stays silent unless a user opted in. One commit lands
    the recipients and the sent flip together. Returns the
    recipient count.

    EVERY recipient's copy renders per recipient through
    recipient_copy_for — release rows from the release
    templates, operator rows from the composed per-language
    parts — in that recipient's resolved locale only (the
    single-language rule, 2026-11-10); the email twin then
    carries those same words. The stored title/body remain the
    English rendering the Admin history reads."""
    recipients = _recipients_for(db, row)
    data: dict = {"announcement_id": str(row.id)}
    if row.link:
        data["link"] = row.link
    if row.release_module_id:
        data["module"] = row.release_module_id
    for recipient in recipients:
        title, body = recipient_copy_for(row, recipient)
        inbox.create_notification(
            db,
            recipient.id,
            kind=inbox.KIND_FEATURE_ANNOUNCEMENT,
            title=title,
            body=body,
            data=data,
            commit=False,
        )
    row.status = STATUS_SENT
    row.sent_at = _now()
    row.recipient_count = len(recipients)
    db.commit()
    return len(recipients)


def run_pending_announcements(db: Session) -> int:
    """The job seam: send every queued announcement, oldest
    first. A failure on one row marks it failed and never blocks
    the rest of the queue; the summary line reports what
    happened. Returns how many announcements were sent."""
    queued = list(
        db.scalars(
            select(models.FeatureAnnouncement)
            .where(
                models.FeatureAnnouncement.status.in_(
                    (STATUS_QUEUED, STATUS_FAILED)
                )
            )
            .order_by(
                models.FeatureAnnouncement.created_at.asc(),
                models.FeatureAnnouncement.id.asc(),
            )
        )
    )
    sent = 0
    for row in queued:
        try:
            count = send_announcement(db, row)
            sent += 1
            logger.info(
                "feature announcement sent (id=%s recipients=%d)", row.id, count
            )
        except Exception:
            db.rollback()
            logger.exception(
                "feature announcement fan-out failed (id=%s)", row.id
            )
            try:
                row.status = STATUS_FAILED
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "could not mark announcement failed (id=%s)", row.id
                )
    return sent
