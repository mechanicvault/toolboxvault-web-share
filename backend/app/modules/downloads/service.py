"""Downloads service — subscriber list logic.

The subscribe endpoint answers the same whether the address is new
or already on the list (no list-membership oracle). Subscribing an
address that previously unsubscribed quietly reactivates it.

The catalog half (2026-11-08) serves the Documents shelf: rows
seeded from catalog.py, bytes carried by the storage service
(seeded from the packaged files on first use — in an environment
with no reachable storage the packaged bytes serve directly, so
the shelf never depends on storage being up to answer).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.downloads import catalog as catalog_def
from app.modules.downloads.models import (
    DownloadEvent,
    DownloadFile,
    DownloadsSubscriber,
)

_FILES_DIR = Path(__file__).resolve().parent / "files"


def get_by_email(db: Session, email: str) -> DownloadsSubscriber | None:
    return db.scalars(
        select(DownloadsSubscriber).where(DownloadsSubscriber.email == email)
    ).first()


def get_by_token(db: Session, token: str) -> DownloadsSubscriber | None:
    return db.scalars(
        select(DownloadsSubscriber).where(
            DownloadsSubscriber.unsubscribe_token == token
        )
    ).first()


def subscribe(
    db: Session, email: str, source: str = "downloads"
) -> DownloadsSubscriber:
    row = get_by_email(db, email)
    if row is not None:
        if row.unsubscribed_at is not None:
            row.unsubscribed_at = None
            db.commit()
            db.refresh(row)
        return row
    row = DownloadsSubscriber(email=email, source=source)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def unsubscribe(db: Session, token: str) -> str | None:
    """Returns "done", "already", or None when the token is unknown."""
    row = get_by_token(db, token)
    if row is None:
        return None
    if row.unsubscribed_at is not None:
        return "already"
    row.unsubscribed_at = datetime.now(timezone.utc)
    db.commit()
    return "done"


# ------------------------------------------------------------------
# The documents catalog
# ------------------------------------------------------------------

def ensure_catalog(db: Session) -> None:
    """Upsert the catalog rows from catalog.py. The migration
    seeds them; this keeps any environment honest (a fresh dev
    database, a catalog entry added in a later lane) without a
    data migration per file. Existing rows keep their counts —
    only the descriptive fields follow the definition.

    New-file detection (sweep E4, busy-work #6): a catalog key
    whose row is MISSING here is a first appearance — but only
    a first appearance observed while the content-alert
    watermark already exists counts as NEWS. The first sync an
    environment ever runs stamps the watermark and treats the
    whole shelf as baseline (a fresh database, the migration
    seed, this lane's own deploy), so no deploy can announce
    the whole shelf; a key added to catalog.py afterwards is
    announced exactly once, in this sync's own commit, to the
    users who opted in (core content_alerts)."""
    from app.modules.core import content_alerts

    watermark_seen = content_alerts.downloads_watermark_seen(db)
    existing = {
        row.key: row
        for row in db.scalars(select(DownloadFile)).all()
    }
    changed = False
    new_entries = []
    for entry in catalog_def.CATALOG:
        row = existing.get(entry.key)
        if row is None:
            db.add(
                DownloadFile(
                    key=entry.key,
                    file_format=entry.file_format,
                    filename=entry.filename,
                    storage_key=catalog_def.storage_key(entry),
                    sort_order=entry.sort_order,
                    is_active=True,
                    download_count=0,
                )
            )
            changed = True
            if watermark_seen:
                new_entries.append(entry)
        else:
            for attr, value in (
                ("file_format", entry.file_format),
                ("filename", entry.filename),
                ("storage_key", catalog_def.storage_key(entry)),
                ("sort_order", entry.sort_order),
            ):
                if getattr(row, attr) != value:
                    setattr(row, attr, value)
                    changed = True
    if not watermark_seen:
        # Baseline sync: stamp the watermark in the same commit
        # (or its own, when nothing else changed) and announce
        # nothing — everything on the shelf right now is the
        # starting world, not news.
        content_alerts.stamp_downloads_watermark(db)
        changed = True
    for entry in new_entries:
        content_alerts.notify_new_download_file(
            db, key=entry.key, filename=entry.filename
        )
    if changed:
        db.commit()


def list_files(db: Session) -> list[DownloadFile]:
    """The Documents shelf only: the wallpaper sizes live in
    the same table (they ride the same counted download path)
    but they are not documents and never list here."""
    ensure_catalog(db)
    return list(
        db.scalars(
            select(DownloadFile)
            .where(
                DownloadFile.is_active.is_(True),
                DownloadFile.key.in_([e.key for e in catalog_def.CATALOG]),
            )
            .order_by(DownloadFile.sort_order, DownloadFile.key)
        ).all()
    )


def ensure_wallpapers(db: Session) -> None:
    """Upsert the wallpaper size rows from catalog.py — the
    same keep-any-environment-honest rule as ensure_catalog,
    for the wallpaper shelf (Part 3). One row per artwork per
    device size; an artwork's displayed count is the sum of its
    rows. Existing rows keep their counts."""
    existing = {
        row.key: row
        for row in db.scalars(select(DownloadFile)).all()
    }
    changed = False
    for entry in catalog_def.WALLPAPER_SIZE_ENTRIES:
        row = existing.get(entry.key)
        if row is None:
            db.add(
                DownloadFile(
                    key=entry.key,
                    file_format=entry.file_format,
                    filename=entry.filename,
                    storage_key=catalog_def.storage_key(entry),
                    sort_order=entry.sort_order,
                    is_active=True,
                    download_count=0,
                )
            )
            changed = True
        else:
            for attr, value in (
                ("file_format", entry.file_format),
                ("filename", entry.filename),
                ("storage_key", catalog_def.storage_key(entry)),
                ("sort_order", entry.sort_order),
            ):
                if getattr(row, attr) != value:
                    setattr(row, attr, value)
                    changed = True
    if changed:
        db.commit()


def list_wallpapers(db: Session) -> list[dict]:
    """The Wallpaper shelf: every artwork with its per-size
    counts and their sum (the number the tile shows)."""
    ensure_wallpapers(db)
    rows = {
        row.key: row
        for row in db.scalars(
            select(DownloadFile).where(DownloadFile.is_active.is_(True))
        ).all()
    }
    shelf = []
    for wallpaper in catalog_def.WALLPAPERS:
        sizes = []
        total = 0
        for size in catalog_def.WALLPAPER_SIZES:
            row = rows.get(f"{wallpaper.key}-{size}")
            count = row.download_count if row is not None else 0
            total += count
            width, height = catalog_def.WALLPAPER_SIZE_DIMS[size]
            sizes.append(
                {
                    "size": size,
                    "width": width,
                    "height": height,
                    "download_count": count,
                }
            )
        shelf.append(
            {
                "key": wallpaper.key,
                "branded": wallpaper.branded,
                "category": wallpaper.category,
                "download_count": total,
                "sizes": sizes,
            }
        )
    return shelf


def record_download(db: Session, key: str) -> DownloadFile | None:
    """Increment the counter atomically, then hand back the row.
    The increment and the serve are one request (owner order:
    every download counts, signed-in or not). The dated event
    rides the SAME transaction (0098): the counter says how
    many, the event says when — neither can move without the
    other."""
    ensure_catalog(db)
    ensure_wallpapers(db)
    result = db.execute(
        update(DownloadFile)
        .where(DownloadFile.key == key, DownloadFile.is_active.is_(True))
        .values(
            download_count=DownloadFile.download_count + 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 0:
        db.rollback()
        return None
    db.add(DownloadEvent(file_key=key))
    db.commit()
    return db.scalars(
        select(DownloadFile).where(DownloadFile.key == key)
    ).first()


def top_downloads_window(
    db: Session, days: int = 7, limit: int = 10
) -> dict:
    """The shelf's top downloads over the last `days` days,
    from the dated event record (0098) — never from the
    cumulative counters, which cannot say what happened this
    week. Wallpaper size keys fold back onto their artwork
    (one artwork, one entry, counts summed across sizes);
    document keys stand as themselves. Keys no longer on the
    shelf are skipped — the ranking only names what a visitor
    can still download.

    `tracking_since` is the event record's first stamp (None
    while it is empty): the caller labels the window honestly
    while the record is younger than the window itself."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(DownloadEvent.file_key, func.count(DownloadEvent.id))
        .where(DownloadEvent.created_at >= since)
        .group_by(DownloadEvent.file_key)
    ).all()
    tracking_since = db.scalars(select(func.min(DownloadEvent.created_at))).first()

    document_keys = {entry.key for entry in catalog_def.CATALOG}
    # Exact by construction: a size key is "<artwork>-<size>"
    # for one of the catalog's own size words.
    size_key_to_artwork = {
        f"{w.key}-{size}": w.key
        for w in catalog_def.WALLPAPERS
        for size in catalog_def.WALLPAPER_SIZES
    }
    artwork_keys = {w.key for w in catalog_def.WALLPAPERS}

    totals: dict[tuple[str, str], int] = {}
    for file_key, n in rows:
        if file_key in document_keys:
            slot = (file_key, "document")
        elif file_key in size_key_to_artwork:
            artwork = size_key_to_artwork[file_key]
            if artwork not in artwork_keys:
                continue
            slot = (artwork, "wallpaper")
        else:
            continue
        totals[slot] = totals.get(slot, 0) + int(n)
    items = [
        {"key": key, "kind": kind, "count": n}
        for (key, kind), n in sorted(
            totals.items(), key=lambda kv: (-kv[1], kv[0][0])
        )[:limit]
    ]
    return {
        "window_days": days,
        "tracking_since": tracking_since,
        "items": items,
    }


def packaged_bytes(entry: catalog_def.CatalogEntry) -> bytes:
    return (_FILES_DIR / entry.packaged).read_bytes()


# Storage keys this process has confirmed present in the storage
# service. First use seeds the object from the packaged bytes
# (put_bytes is the storage service's server-originated write —
# the same path the manual-fetch flow uses); a failed seed is
# retried on a later call and never blocks a download.
_storage_ready: set[str] = set()


def _serve_bytes(key: str, package: bytes, media_type: str) -> bytes:
    """The storage dance, shared by every shelf: the object
    from the storage service when it holds it, else the
    packaged bytes (which are identical — the package is what
    seeds storage)."""
    if key not in _storage_ready:
        try:
            from app.core.storage import storage

            try:
                storage.head(key)
            except Exception:
                if package:
                    storage.put_bytes(key, package, media_type)
            _storage_ready.add(key)
        except Exception:
            pass
    if key in _storage_ready:
        try:
            from app.core.storage import storage

            return storage.fetch(key)
        except Exception:
            return package
    return package


def read_file_bytes(row: DownloadFile) -> bytes:
    """The file's bytes, from the storage service when it holds
    the object, else the packaged bytes (which are identical —
    the package is what seeds storage)."""
    entry = catalog_def.BY_KEY.get(row.key)
    package = packaged_bytes(entry) if entry is not None else b""
    return _serve_bytes(
        row.storage_key,
        package,
        catalog_def.MEDIA_TYPES.get(
            row.file_format, "application/octet-stream"
        ),
    )


def read_view_bytes(key: str, size: str) -> bytes | None:
    """Bytes for the Wallpaper tab's UNCOUNTED views — a tile
    thumbnail or the preview at a device size. Looking is not
    downloading: only the /files/{key} path moves a counter.
    Returns None for an unknown artwork or size (or a missing
    thumbnail), so the route answers a plain 404."""
    wallpaper = catalog_def.WALLPAPERS_BY_KEY.get(key)
    if wallpaper is None:
        return None
    if size == "thumb":
        packaged = f"wallpapers/{key}-thumb.jpg"
        package_path = _FILES_DIR / packaged
        if not package_path.exists():
            return None
        return _serve_bytes(
            f"downloads/{packaged}",
            package_path.read_bytes(),
            "image/jpeg",
        )
    if size not in catalog_def.WALLPAPER_SIZES:
        return None
    entry = wallpaper.size_entry(size)
    if not (_FILES_DIR / entry.packaged).exists():
        return None
    return _serve_bytes(
        catalog_def.storage_key(entry),
        packaged_bytes(entry),
        "image/jpeg",
    )
