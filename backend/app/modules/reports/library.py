"""The reports library (Reports page redesign, 2026-11-06):
saved templates, generation, and the History.

Three jobs:

- TEMPLATES — the user's saved reports (catalog type + settings
  + area). The seven defaults are seeded lazily at the first
  templates read, once per user, behind the report_template_seeds
  marker: a default the user deletes never resurrects, and every
  account that already exists picks the defaults up the first
  time it opens the page.
- GENERATION — one seam that turns (type, settings, format) into
  file bytes through the SAME builders and renderers the rest of
  the system uses (the inventory spec pipeline for inventory;
  the activity builders for everything else), so a file the
  wizard makes can never disagree with any other surface.
- HISTORY — every generation through this seam stores its file
  in object storage and leaves a generated_reports row. Only
  this page's flows record history (coordinator call, 2026-11-06):
  the truck statement button, the claim packages and the
  downloads XLSX keep their own direct-download behavior and do
  not appear here.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import storage as storage_mod
from app.modules.core import models as core_models
from app.modules.reports import activity, catalog, exports, models, schemas
from app.modules.reports import service as report_service

ReportError = report_service.ReportError

# The full-inventory column set: the default template's promise
# ("names, model/serial numbers, qty, price, categories,
# totals") in catalog keys.
INVENTORY_COLUMNS = [
    "name",
    "kind",
    "brand",
    "models",
    "serials",
    "category",
    "dealer",
    "location",
    "quantity",
    "price_each",
    "price_total",
    "replacement",
]

_FORMATS = ("pdf", "csv", "xlsx")

# The "Email this file" size cap for a generated report — the
# same 25 MB the inventory document kinds carry
# (inventory/attachments.py DOCUMENT_MAX_BYTES).
_EMAIL_MAX_BYTES = 25 * 1024 * 1024


# -- settings validation ---------------------------------------------------


def validate_settings(report_type: str, settings: dict | None) -> dict:
    """Clean a settings bag for `report_type` or raise
    ReportError. Only the keys the type honestly supports
    survive; unknown keys are dropped, bad values refused."""
    spec = catalog.TYPES.get(report_type) or catalog.ADMIN_TYPES.get(
        report_type
    )
    if spec is None:
        raise ReportError(f"Unknown report type: {report_type}")
    raw = dict(settings or {})
    out: dict = {}
    fmt = raw.get("format")
    if fmt is not None:
        if fmt not in spec["formats"]:
            raise ReportError(
                f"Format {fmt} isn't available for this report."
            )
        out["format"] = fmt
    kind = spec["settings"]
    if kind in ("year", "year_or_all"):
        year = raw.get("year")
        if year is not None and year != "":
            try:
                year = int(year)
            except (TypeError, ValueError):
                raise ReportError("The year must be a number.")
            if not 1900 <= year <= 2100:
                raise ReportError("The year is out of range.")
            out["year"] = year
    elif kind == "period":
        for key in ("start", "end"):
            value = raw.get(key)
            if value:
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    raise ReportError("Dates must be YYYY-MM-DD.")
                out[key] = str(value)
        if out.get("start") and out.get("end") and out["start"] > out["end"]:
            raise ReportError("The start date is after the end date.")
    elif kind == "inventory":
        from app.modules.reports import columns as colmod

        grouping = raw.get("grouping") or "category"
        if grouping not in colmod.GROUPINGS:
            raise ReportError(f"Unknown grouping: {grouping}")
        sets_mode = raw.get("sets_mode") or "full"
        if sets_mode not in colmod.SETS_MODES:
            raise ReportError(f"Unknown sets mode: {sets_mode}")
        out["grouping"] = grouping
        out["sets_mode"] = sets_mode
    return out


def validate_format(report_type: str, fmt: str) -> str:
    if fmt not in _FORMATS:
        raise ReportError("Format must be pdf, csv or xlsx.")
    spec = catalog.TYPES.get(report_type) or catalog.ADMIN_TYPES[report_type]
    if fmt not in spec["formats"]:
        raise ReportError(f"Format {fmt} isn't available for this report.")
    return fmt


# -- generation --------------------------------------------------------------


def _parse_day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def generate_bytes(
    db: Session,
    owner: core_models.User,
    report_type: str,
    settings: dict,
    fmt: str,
    *,
    dealer_visible: bool = True,
) -> bytes:
    """Build the file for (type, settings, format) through the
    system's own builders/renderers. Raises ReportError for a
    combination the producers can't make."""
    validate_format(report_type, fmt)
    settings = validate_settings(report_type, settings)
    if report_type in catalog.ADMIN_TYPES:
        # Admin datasets (admin lane, 2026-11-06): tabular shape,
        # tabular renderers — same library door, same History.
        # The ROUTES gate these types to admin seats; the
        # library itself stays audience-blind like the rest of
        # the machinery.
        from app.modules.reports import admin_reports, tabular

        doc = admin_reports.BUILDERS[report_type](db, owner, settings)
        return tabular.render_tabular(doc, fmt, owner)
    if report_type == "inventory":
        spec = schemas.ReportSpec(
            columns=INVENTORY_COLUMNS,
            filters=schemas.ReportFilters(),
            grouping=settings.get("grouping", "category"),
            sets_mode=settings.get("sets_mode", "full"),
            sort=schemas.SortSpec(key="name", direction="asc"),
        )
        report = report_service.build_report(
            db,
            owner.id,
            spec,
            dealer_visible=dealer_visible,
            prepared_for=report_service.prepared_for_of(owner),
        )
        return exports.render(report, fmt, "Inventory report", owner)

    year = settings.get("year")
    start = _parse_day(settings.get("start"))
    end = _parse_day(settings.get("end"))
    if report_type == "year_end":
        report = activity.build_year_end(db, owner, year or date.today().year)
    elif report_type == "tax_179":
        report = activity.build_tax_year(db, owner, year or date.today().year)
    elif report_type == "repair_costs":
        if year:
            start, end = date(year, 1, 1), date(year, 12, 31)
        report = activity.build_repair_costs(db, owner, start=start, end=end)
    elif report_type == "sales":
        report = activity.build_sales(db, owner, start=start, end=end)
    elif report_type == "lost_stolen":
        report = activity.build_lost_stolen(db, owner, start=start, end=end)
    elif report_type == "warranty_claims":
        report = activity.build_warranty_claims(db, owner, start=start, end=end)
    elif report_type == "checked_out":
        report = activity.build_checked_out(db, owner)
    elif report_type == "open_claims":
        report = activity.build_open_claims(db, owner)
    elif report_type == "open_truck_accounts":
        report = activity.build_open_truck_accounts(db, owner)
    else:  # pragma: no cover — validate_settings already refused it
        raise ReportError(f"Unknown report type: {report_type}")
    return activity.render_activity(report, fmt, owner)


# -- templates -----------------------------------------------------------------


def serialize_template(
    row: models.ReportTemplate, owner: core_models.User | None = None
) -> dict:
    # A DEFAULT row's description is system-written text, composed
    # at seed time and never user-editable (templates have no
    # update path) — so when the caller passes the owner, the words
    # are recomposed from the CURRENT catalog instead of trusting
    # the stored copy. Stored copies seeded before the sweep fix
    # (05-F6) still end in "Saved as PDF." beside the row's own
    # PDF/CSV/XLSX buttons; recomposing is what makes the row
    # honest for every account that already exists, not just new
    # seeds. A user's own templates (is_default False) always keep
    # exactly the words they were saved with.
    description = row.description
    if owner is not None and row.is_default:
        description = catalog.default_description(
            row.report_type, row.settings or {}, owner
        )
    return {
        "id": str(row.id),
        "report_type": row.report_type,
        "name": row.name,
        "description": description,
        "area": row.area,
        "settings": row.settings or {},
        "is_default": bool(row.is_default),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def ensure_seeded(db: Session, owner: core_models.User) -> None:
    """Seed the seven defaults ONCE per user, lazily. The marker
    row is the whole trick: it exists from the first seed on, so
    a default the user deletes stays deleted, while an account
    that predates the redesign still receives its defaults the
    first time it opens the page."""
    if db.get(models.ReportTemplateSeed, owner.id) is not None:
        return
    # Stagger the defaults' timestamps by microseconds so the
    # seeded order (the spec's order) is the order every read
    # returns — one insert batch would otherwise share a single
    # clock value and leave the order to the id tiebreak.
    base = datetime.now(timezone.utc)
    for index, (report_type, area, settings) in enumerate(
        catalog.DEFAULT_TEMPLATES
    ):
        db.add(
            models.ReportTemplate(
                owner_id=owner.id,
                report_type=report_type,
                name=catalog.default_name(report_type, settings, owner),
                description=catalog.default_description(
                    report_type, settings, owner
                ),
                area=area,
                settings=dict(settings),
                is_default=True,
                created_at=base + timedelta(microseconds=index),
                updated_at=base + timedelta(microseconds=index),
            )
        )
    db.add(models.ReportTemplateSeed(user_id=owner.id))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first read seeded first — the marker's
        # primary key is the lock; the defaults now exist either
        # way.
        db.rollback()


def list_templates(
    db: Session, owner: core_models.User
) -> list[models.ReportTemplate]:
    ensure_seeded(db, owner)
    return list(
        db.scalars(
            select(models.ReportTemplate)
            .where(models.ReportTemplate.owner_id == owner.id)
            .order_by(models.ReportTemplate.created_at, models.ReportTemplate.id)
        )
    )


def get_template(
    db: Session, owner_id: uuid.UUID, template_id: uuid.UUID
) -> models.ReportTemplate | None:
    row = db.get(models.ReportTemplate, template_id)
    if row is None or row.owner_id != owner_id:
        return None
    return row


def create_template(
    db: Session,
    owner: core_models.User,
    *,
    report_type: str,
    name: str,
    description: str | None,
    area: str | None,
    settings: dict | None,
) -> models.ReportTemplate:
    spec = catalog.TYPES.get(report_type) or catalog.ADMIN_TYPES.get(
        report_type
    )
    if spec is None:
        raise ReportError(f"Unknown report type: {report_type}")
    cleaned = validate_settings(report_type, settings)
    home = spec["home"]
    if report_type in catalog.ADMIN_TYPES:
        # An admin template lives in the Admin tab, whatever
        # area the caller asked for (the tab is its home).
        area = "admin"
    if area is not None and area not in catalog.AREAS:
        raise ReportError("Area must be quick or accounting.")
    name = (name or "").strip()
    if not name:
        name = catalog.default_name(report_type, cleaned, owner)
    if description is None or not description.strip():
        description = catalog.default_description(report_type, cleaned, owner)
    row = models.ReportTemplate(
        owner_id=owner.id,
        report_type=report_type,
        name=name[:200],
        description=description.strip()[:1000],
        area=area or home,
        settings=cleaned,
        is_default=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_template(db: Session, owner_id: uuid.UUID, template_id: uuid.UUID) -> bool:
    row = get_template(db, owner_id, template_id)
    if row is None:
        return False
    # History rows that came from this template keep their file
    # and their record — only the link goes (the name snapshot
    # on the history row already says what ran).
    db.query(models.GeneratedReport).filter(
        models.GeneratedReport.template_id == row.id
    ).update({models.GeneratedReport.template_id: None}, synchronize_session=False)
    db.delete(row)
    db.commit()
    return True


# -- history -------------------------------------------------------------------


def serialize_history(row: models.GeneratedReport) -> dict:
    return {
        "id": str(row.id),
        "template_id": str(row.template_id) if row.template_id else None,
        "name": row.name,
        "report_type": row.report_type,
        "format": row.format,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "settings": row.settings or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def record_generation(
    db: Session,
    owner: core_models.User,
    *,
    report_type: str,
    name: str,
    fmt: str,
    content: bytes,
    settings: dict,
    template_id: uuid.UUID | None = None,
) -> models.GeneratedReport:
    """Store the file and leave its History row. The storage key
    lives in the owner's reports namespace; the row records the
    verified stored size."""
    row_id = uuid.uuid4()
    filename = exports.report_filename(name, fmt)
    key = storage_mod.storage.object_key(
        str(owner.id), str(row_id), "report", filename, collection="reports"
    )
    stored = storage_mod.storage.put_bytes(
        key, content, exports.MIME_TYPES[fmt]
    )
    row = models.GeneratedReport(
        id=row_id,
        owner_id=owner.id,
        template_id=template_id,
        name=name,
        report_type=report_type,
        format=fmt,
        storage_key=stored.key,
        content_type=exports.MIME_TYPES[fmt],
        size_bytes=stored.size_bytes,
        settings=dict(settings or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_history(
    db: Session,
    owner_id: uuid.UUID,
    *,
    day_from: date | None = None,
    day_to: date | None = None,
    fmt: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[models.GeneratedReport]:
    stmt = (
        select(models.GeneratedReport)
        .where(models.GeneratedReport.owner_id == owner_id)
        .order_by(
            models.GeneratedReport.created_at.desc(),
            models.GeneratedReport.id.desc(),
        )
    )
    if day_from is not None:
        stmt = stmt.where(
            models.GeneratedReport.created_at
            >= datetime.combine(day_from, time.min, tzinfo=timezone.utc)
        )
    if day_to is not None:
        stmt = stmt.where(
            models.GeneratedReport.created_at
            < datetime.combine(day_to, time.max, tzinfo=timezone.utc)
        )
    if fmt:
        stmt = stmt.where(models.GeneratedReport.format == fmt)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.GeneratedReport.name.ilike(needle),
                models.GeneratedReport.report_type.ilike(needle),
            )
        )
    return list(db.scalars(stmt.limit(limit)))


def get_history(
    db: Session, owner_id: uuid.UUID, history_id: uuid.UUID
) -> models.GeneratedReport | None:
    row = db.get(models.GeneratedReport, history_id)
    if row is None or row.owner_id != owner_id:
        return None
    return row


def delete_history(db: Session, owner_id: uuid.UUID, history_id: uuid.UUID) -> bool:
    row = get_history(db, owner_id, history_id)
    if row is None:
        return False
    try:
        storage_mod.storage.delete(row.storage_key)
    except storage_mod.StorageError:
        # Best-effort, the cascade precedent: the row is the
        # record the user asked to remove; a storage hiccup
        # leaves an orphan object, never a phantom list entry.
        pass
    db.delete(row)
    db.commit()
    return True


def history_view(row: models.GeneratedReport) -> dict:
    """The AttachmentViewer shape for one history file, with a
    fresh presigned read URL (the documents-area pattern)."""
    return {
        "key": row.storage_key,
        "filename": exports.report_filename(row.name, row.format),
        "kind": "report",
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "url": storage_mod.storage.presigned_get_url(row.storage_key),
    }


class EmailRateLimited(Exception):
    """The shared attachment-email budget is exhausted (the
    inventory "Email this file" limiter — one budget per user
    across every surface that emails a file)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many file emails — try again shortly.")
        self.retry_after = retry_after


def email_history_file(
    db: Session,
    user: core_models.User,
    entry_id: uuid.UUID,
    *,
    key: str,
    recipient: str,
) -> dict:
    """The viewer popup's "Email this file" for a generated
    report (Ryan, 2026-11-07: a finished generation lands in
    the same viewer a document on a tool opens, Email action
    included). Owner-scoped by construction — the entry
    resolves through get_history (another user's entry is a
    404-shaped refusal) and the key must be THAT entry's
    stored file. Mirrors the inventory attachment email's
    discipline: shared rate limiter, bytes read through the
    storage service, the document size cap, and the send rides
    the notifications seam (which records the outbox row)."""
    from app.core import notifications
    from app.core.rate_limit import attachment_email_rate_limiter

    entry = get_history(db, user.id, entry_id)
    if entry is None:
        raise LookupError("Report not found")
    if key != entry.storage_key:
        raise ReportError("That file isn't this report.")

    retry_after = attachment_email_rate_limiter.retry_after(str(user.id))
    if retry_after is not None:
        raise EmailRateLimited(retry_after)
    try:
        content = storage_mod.storage.fetch(entry.storage_key)
    except storage_mod.StorageError as exc:
        raise ReportError(f"Couldn't read the file from storage: {exc}") from exc
    if len(content) > _EMAIL_MAX_BYTES:
        raise ReportError("That file is too large to email.")

    filename = history_view(entry)["filename"]
    attachment_email_rate_limiter.record_hit(str(user.id))
    sent = notifications.send_email(
        db,
        recipient,
        f"{user.name} sent you a file from Toolbox Vault: {filename}",
        (
            f"{user.name} shared a report from their Toolbox Vault "
            f"with you.\n\n"
            f"Report: {entry.name}\n"
            f"File: {filename}\n\n"
            "The file is attached to this message."
        ),
        kind=notifications.KIND_ATTACHMENT_SHARE,
        attachment=(filename, content),
    )
    return {
        "sent": sent,
        "filename": filename,
        "kind": "report",
        "recipient": recipient,
    }
