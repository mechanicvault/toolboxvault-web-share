"""New-content inbox opt-ins (sweep E4, busy-work #6,
2026-11-12): "tell me when NEW file downloads / NEW 3D print
files appear", plus the fan-outs behind them.

Pattern decision (recorded in the lane INDEX): this mirrors
the flyers precedent — a module-owned pref table read/written
by its own service, an inbox kind per event, the fan-out in
the event's own commit (commit=False) — with ONE deliberate
inversion: flyer alerts default ON (absence reads as on);
Ryan's spec for THIS lane is that every opt-in defaults OFF,
so absence reads as opted OUT and these functions return
False for a user with no row.

Language (owner rule, 2026-11-10): every notice is rendered
per recipient from the copy tables below, in that recipient's
resolved locale ONLY (app.core.i18n.resolve_locale — the
announcements lane's recipient_copy_for posture). One
language per inbox row, never a stacked pair; the email twin
inherits the row's words through the central inbox path.

The downloads "new file" detection lives in the downloads
service (ensure_catalog): a catalog key counts as new only
when its first appearance is observed while the
`downloads_catalog_seen_at` watermark row already exists in
content_alert_state. The first sync an environment ever runs
stamps the watermark and notifies NOBODY — the existing shelf
is baseline, not news — so no deploy can announce the whole
shelf. See notify_new_download_file below for the fan-out.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import i18n
from app.modules.core import inbox, models

WATERMARK_DOWNLOADS_CATALOG = "downloads_catalog_seen_at"

# -- copy (per-recipient locale; EN + ES, the shipped pair) ----

_NEW_PRINT_COPY = {
    "en": (
        "New 3D print file",
        "“{title}” was just published in 3D Print Files.",
    ),
    "es": (
        "Archivo de impresión 3D nuevo",
        "«{title}» se acaba de publicar en Archivos de impresión 3D.",
    ),
}

_NEW_DOWNLOAD_COPY = {
    "en": (
        "New file download",
        "“{name}” was just added to Downloads.",
    ),
    "es": (
        "Descarga de archivo nueva",
        "«{name}» se acaba de agregar a Descargas.",
    ),
}


def _copy(table: dict, user, **fmt) -> tuple[str, str]:
    title, body = table[i18n.resolve_locale(user)]
    return title, body.format(**fmt)


# -- preferences ------------------------------------------------


def get_prefs(db: Session, user_id: uuid.UUID) -> dict:
    """The two new-content boxes for one user. Default OFF:
    no row (or a False flag) means opted out."""
    row = db.get(models.NewContentAlertPref, user_id)
    if row is None:
        return {"downloads": False, "prints": False}
    return {
        "downloads": bool(row.downloads_enabled),
        "prints": bool(row.prints_enabled),
    }


def set_pref(db: Session, user_id: uuid.UUID, *, kind: str, enabled: bool) -> dict:
    """Flip ONE box ("downloads" | "prints"); the other box's
    stored value is untouched. Commits (the settings write is
    its own event, like the flyers set_alerts_enabled)."""
    if kind not in ("downloads", "prints"):
        raise ValueError(f"unknown content-alert kind: {kind}")
    row = db.get(models.NewContentAlertPref, user_id)
    if row is None:
        row = models.NewContentAlertPref(user_id=user_id)
        db.add(row)
    if kind == "downloads":
        row.downloads_enabled = enabled
    else:
        row.prints_enabled = enabled
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_prefs(db, user_id)


def _audience(db: Session, *, flag: str, exclude_id=None) -> list:
    """Active users who opted IN to one box (flag is the
    NewContentAlertPref column name), minus the excluded id
    (the publisher — nobody is told about their own publish)."""
    column = getattr(models.NewContentAlertPref, flag)
    user_ids = db.scalars(
        select(models.NewContentAlertPref.user_id).where(column.is_(True))
    ).all()
    audience = []
    for user_id in user_ids:
        if exclude_id is not None and user_id == exclude_id:
            continue
        user = db.get(models.User, user_id)
        if user is not None and user.is_active:
            audience.append(user)
    return audience


# -- fan-outs (all commit=False: the event's commit carries) ---


def notify_new_print_file(db: Session, *, file_id, title: str, publisher_id) -> int:
    """A NEW print file was published: tell the prints-box
    audience (minus the publisher), each in their own
    language. Called by prints.create_file before its commit."""
    sent = 0
    for user in _audience(db, flag="prints_enabled", exclude_id=publisher_id):
        t, b = _copy(_NEW_PRINT_COPY, user, title=title)
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_PRINT_FILE_NEW,
            title=t,
            body=b,
            data={"file_id": str(file_id)},
            commit=False,
        )
        sent += 1
    return sent


def notify_new_download_file(db: Session, *, key: str, filename: str) -> int:
    """A downloads document appeared on the shelf for the
    first time (post-watermark — see the module docstring):
    tell the downloads-box audience, each in their own
    language. Downloads documents are operator/catalog
    content, so there is no publisher to exclude. Called by
    downloads.ensure_catalog inside its own commit."""
    sent = 0
    for user in _audience(db, flag="downloads_enabled"):
        t, b = _copy(_NEW_DOWNLOAD_COPY, user, name=filename)
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_DOWNLOAD_FILE_NEW,
            title=t,
            body=b,
            data={"key": key},
            commit=False,
        )
        sent += 1
    return sent


# -- downloads watermark ----------------------------------------


def downloads_watermark_seen(db: Session) -> bool:
    return db.get(models.ContentAlertState, WATERMARK_DOWNLOADS_CATALOG) is not None


def stamp_downloads_watermark(db: Session) -> None:
    """Record that the catalog sync has run at least once in
    this environment (flush only — the caller's commit
    carries it)."""
    if downloads_watermark_seen(db):
        return
    db.add(
        models.ContentAlertState(
            key=WATERMARK_DOWNLOADS_CATALOG,
            value=datetime.now(timezone.utc).isoformat(),
        )
    )
    db.flush()
