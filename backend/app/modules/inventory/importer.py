"""General CSV/XLSX importer (inventory module, 2026-10-19).

Blueprint: a general column-mapping importer — and the migration
fallback for app data. The flow:

  1. UPLOAD — the file is parsed server-side (stdlib csv / openpyxl)
     and its RAW BYTES are kept against an owner-scoped
     ImportSession (24h expiry). The client gets detected headers,
     sample rows, the row count, a field catalog for the chosen kind,
     and auto-suggested mappings. For .xlsx the header row is
     LOCATED, not assumed: a sheet whose top rows are a title /
     dashboard band (the /downloads sheet carries one) parses from
     the row that actually names the columns, and the active sheet
     is tried first, then the workbook's other sheets — files whose
     first row names the columns parse exactly as they always have.
  2. MAP — each file column (addressed by INDEX, never by name, so
     duplicate headers survive) maps to one asset field. Single-value
     fields take ONE column (a second is refused, never "last wins");
     multi-value list fields (model numbers, serial numbers, set
     serials) may take several columns at once and their values
     merge in column order, deduped case/whitespace-insensitively.
  3. DRY RUN — every row is transformed in memory and classified
     ok / warning / error / blank, with the entitlement-cap impact
     computed by billing's machinery when enforcement is on.
  4. CONFIRM — the SAME transform runs again from the stored bytes
     (a dry run can never disagree with its confirm), valid rows are
     created through inventory's own create service, the cap is
     respected row by row, and the session is consumed.

Dealer names — and brand, category, tag and location values — are
reconciled by the RESOLVE step (matching.py, smart matching
2026-10-19): normalized-exact matches and remembered answers apply
automatically and are LISTED in the run's mappings summary; fuzzy
lookalikes ALWAYS ask (Mac Tools is not Matco Tools) and an
unanswered value refuses the run. Creating a private company or a
location node happens only as the user's explicit answer —
importing still never creates anything silently.

Everything here is inventory-internal: routes live in import_routes.py
and are gated by the inventory module dependency like every other
inventory route.
"""

import csv
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import journal
from app.modules.inventory import custom_fields, matching, models, schemas, service

MAX_ROWS = 2000
MAX_COLUMNS = 100
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB — a 2,000-row sheet is small
SESSION_TTL = timedelta(hours=24)
SAMPLE_ROWS = 5
KINDS = ("tool", "battery")


def _remaining_slots(db: Session, owner_id: uuid.UUID) -> int | None:
    """Slots left under the plan's item limit, or None when nothing
    restricts imports (enforcement off or an unlimited plan). This
    is billing's machinery — the importer never re-derives the rule."""
    if not entitlements.enforcement_enabled(db):
        return None
    entitlement = entitlements.resolve_entitlement(db, owner_id)
    if entitlement.item_limit is None:
        return None
    return max(0, entitlement.item_limit - entitlements.asset_count(db, owner_id))


def cap_info(db: Session, owner_id: uuid.UUID, importable: int) -> dict:
    """The dry run's cap report: how many importable rows would NOT
    fit if the user confirmed right now. Enforcement off → no cap
    messaging at all."""
    if not entitlements.enforcement_enabled(db):
        return {"enforcement": False, "would_exceed": 0}
    entitlement = entitlements.resolve_entitlement(db, owner_id)
    current = entitlements.asset_count(db, owner_id)
    remaining = _remaining_slots(db, owner_id)
    return {
        "enforcement": True,
        "limit": entitlement.item_limit,
        "current_count": current,
        "remaining": remaining,
        "would_exceed": (
            0 if remaining is None else max(0, importable - remaining)
        ),
    }


def _decision_dicts(resolutions_raw) -> dict:
    """The client's resolutions ({field: {raw: decision}}) as plain
    dicts — the route layer hands over pydantic models; the
    matching engine works in dicts."""
    out: dict = {}
    for field, per_value in (resolutions_raw or {}).items():
        out[field] = {}
        for raw, decision in (per_value or {}).items():
            if hasattr(decision, "model_dump"):
                out[field][raw] = decision.model_dump(mode="json")
            else:
                out[field][raw] = dict(decision)
    return out


def _resolve(
    db: Session,
    owner_id: uuid.UUID,
    rows: list[list[str]],
    mapping: dict[int, str],
    resolutions_raw,
) -> tuple[dict, list[dict]]:
    """Resolve this run's values (smart matching): automatic tiers
    (normalized-exact, learned) plus the user's answers. Unanswered
    questions refuse the run — as a mapping error, so routes answer
    422 with the values named."""
    try:
        return matching.resolve_effective(
            db, owner_id, rows, mapping, _decision_dicts(resolutions_raw)
        )
    except (
        matching.UnresolvedValuesError,
        matching.ResolutionValidationError,
    ) as exc:
        raise ImportMappingError(str(exc)) from exc


def dry_run(
    db: Session,
    owner_id: uuid.UUID,
    session: models.ImportSession,
    kind: str,
    mapping_raw: dict,
    skip_duplicates: bool = True,
    resolutions_raw=None,
) -> dict:
    """Transform every row and report the outcome WITHOUT writing
    anything (besides re-stamping the session's kind)."""
    if kind not in KINDS:
        raise ImportMappingError("Pick Tools or Batteries for this import.")
    session.kind = kind
    db.commit()
    rows = session_rows(session)
    mapping = validate_mapping(
        db, owner_id, mapping_raw, kind, len(session.headers)
    )
    effective, applied = _resolve(db, owner_id, rows, mapping, resolutions_raw)
    results = transform_rows(
        db,
        owner_id,
        kind,
        rows,
        mapping,
        effective,
        header_row=session_header_row(session),
    )
    public_rows = []
    counts = {"ok": 0, "warning": 0, "error": 0, "blank": 0, "duplicates": 0}
    importable = 0
    for result in results:
        counts[result["status"]] += 1
        if result["duplicate"]:
            counts["duplicates"] += 1
        if result["status"] in ("ok", "warning") and not (
            result["duplicate"] and skip_duplicates
        ):
            importable += 1
        public_rows.append(
            {
                key: result[key]
                for key in ("row", "status", "name", "messages", "duplicate", "preview")
            }
        )
    return {
        "session_id": str(session.id),
        "kind": kind,
        "total_rows": len(results),
        "counts": counts,
        "importable": importable,
        "cap": cap_info(db, owner_id, importable),
        "rows": public_rows,
        "mappings": applied,
    }


def confirm_import(
    db: Session,
    owner_id: uuid.UUID,
    session: models.ImportSession,
    kind: str,
    mapping_raw: dict,
    skip_duplicates: bool = True,
    resolutions_raw=None,
) -> dict:
    """Run the import for real, then CONSUME the session.

    Rows import in file order. With enforcement on, imports stop at
    the plan cap; the rest are reported as skipped-over-cap with
    their row numbers — never a partial mystery. Each row creates
    through inventory's own create service, so imported items are
    ordinary assets (validation, tags, dealer checks all shared).
    """
    if kind not in KINDS:
        raise ImportMappingError("Pick Tools or Batteries for this import.")
    rows = session_rows(session)
    mapping = validate_mapping(
        db, owner_id, mapping_raw, kind, len(session.headers)
    )
    decisions = _decision_dicts(resolutions_raw)
    try:
        effective, applied = matching.resolve_effective(
            db, owner_id, rows, mapping, decisions
        )
    except (
        matching.UnresolvedValuesError,
        matching.ResolutionValidationError,
    ) as exc:
        raise ImportMappingError(str(exc)) from exc
    remaining = _remaining_slots(db, owner_id)

    # Audit trail (2026-10-19): a bulk operation gets a forced
    # restore point BEFORE the first row lands (and after the
    # mapping has validated, so a refused import leaves no stray
    # marker) — the whole import unwinds in one restore.
    journal.create_marker(
        db, owner_id, kind="pre_bulk", label="Before an import"
    )

    # The user's explicit "create" answers become real rows first
    # (a private dealer company, location tree nodes), so the
    # transform below only ever maps onto things that exist.
    matching.materialize_creates(db, owner_id, effective)
    results = transform_rows(
        db,
        owner_id,
        kind,
        rows,
        mapping,
        effective,
        header_row=session_header_row(session),
    )

    imported = 0
    skipped_duplicates = 0
    over_cap_rows: list[int] = []
    error_rows: list[dict] = []
    for result in results:
        if result["status"] == "blank":
            continue
        if result["status"] == "error":
            error_rows.append(
                {"row": result["row"], "messages": result["messages"]}
            )
            continue
        if result["duplicate"] and skip_duplicates:
            skipped_duplicates += 1
            continue
        if remaining is not None and remaining <= 0:
            over_cap_rows.append(result["row"])
            continue
        try:
            _create_from_values(db, owner_id, kind, result["values"])
        except (
            service.ToolValidationError,
            custom_fields.FieldValidationError,
        ) as exc:
            db.rollback()
            error_rows.append({"row": result["row"], "messages": [str(exc)]})
            continue
        except ValidationError as exc:
            # Schema bounds (deep audit F4-02/F4-03: column-mirroring
            # caps on names/money) reject a row's values at record
            # construction — that is a per-row import error with the
            # field's reason, never a crashed run.
            db.rollback()
            messages = [
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            ]
            error_rows.append({"row": result["row"], "messages": messages})
            continue
        imported += 1
        if remaining is not None:
            remaining -= 1

    # The answers the user gave are REMEMBERED (smart matching):
    # the next import carrying the same values is pre-answered.
    # Only a completed import teaches — an abandoned one doesn't.
    matching.learn_decisions(db, owner_id, decisions, effective)

    delete_session(db, session)
    return {
        "kind": kind,
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "skipped_over_cap": len(over_cap_rows),
        "over_cap_rows": over_cap_rows,
        "errors": len(error_rows),
        "error_rows": error_rows,
        "total_rows": len(results),
        "mappings": applied,
    }


class ImportFileError(ValueError):
    """The uploaded file can't be used (wrong type, empty, too big,
    unparseable). Routes turn this into a 400 with the message."""


class ImportMappingError(ValueError):
    """The submitted mapping is invalid (unknown field, duplicate
    field assignment, no Name column). Routes turn this into 422."""


class SessionExpiredError(ValueError):
    """The import session outlived its 24h. Routes -> 410."""


# ---------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def create_session(
    db: Session,
    owner_id: uuid.UUID,
    *,
    filename: str,
    kind: str,
    data: bytes,
) -> models.ImportSession:
    """Parse, validate and store an uploaded spreadsheet. Raises
    ImportFileError for anything the user should fix and re-upload."""
    if kind not in KINDS:
        raise ImportFileError("Pick Tools or Batteries for this import.")
    if len(data) == 0:
        raise ImportFileError("That file is empty — there's nothing to import.")
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError(
            f"That file is {len(data) // (1024 * 1024)} MB — imports are "
            "capped at 10 MB per file."
        )
    file_format, headers, rows = parse_spreadsheet(filename, data)
    # Housekeeping: the caller's expired sessions die on any upload.
    purge_expired_sessions(db, owner_id)
    now = datetime.now(timezone.utc)
    session = models.ImportSession(
        owner_id=owner_id,
        kind=kind,
        filename=filename[:255],
        file_format=file_format,
        data=data,
        headers=headers,
        row_count=len(rows),
        expires_at=now + SESSION_TTL,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_owned_session(
    db: Session, owner_id: uuid.UUID, session_id: uuid.UUID
) -> models.ImportSession | None:
    """The session if it belongs to the caller — a foreign id is
    indistinguishable from a missing one (404 discipline). An
    expired session is deleted and reported via SessionExpiredError."""
    session = db.get(models.ImportSession, session_id)
    if session is None or session.owner_id != owner_id:
        return None
    if _aware(session.expires_at) <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise SessionExpiredError(
            "This import session expired (uploads are kept for 24 hours) — "
            "upload the file again to pick up where you left off."
        )
    return session


def delete_session(db: Session, session: models.ImportSession) -> None:
    db.delete(session)
    db.commit()


def purge_expired_sessions(db: Session, owner_id: uuid.UUID) -> int:
    now = datetime.now(timezone.utc)
    stale = [
        s
        for s in db.scalars(
            select(models.ImportSession).where(
                models.ImportSession.owner_id == owner_id
            )
        )
        if _aware(s.expires_at) <= now
    ]
    for session in stale:
        db.delete(session)
    if stale:
        db.commit()
    return len(stale)


def session_rows(session: models.ImportSession) -> list[list[str]]:
    """Re-parse the stored bytes. The bytes parsed once at upload,
    so this cannot fail — but parsing again (rather than caching a
    transform) is what makes dry-run and confirm agree by
    construction."""
    _, _, rows = parse_spreadsheet(session.filename, bytes(session.data))
    return rows


def session_header_row(session: models.ImportSession) -> int:
    """The 1-based spreadsheet row the session's headers were found
    on (1 for ordinary files). A banded sheet reports its real
    header row, so the dry run's row numbers name the rows the user
    actually sees in their spreadsheet."""
    _, _, _, header_row = _parse_spreadsheet_full(
        session.filename, bytes(session.data)
    )
    return header_row


# ---------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------


def _cell_text(value) -> str:
    """One spreadsheet cell as text. Numbers lose their trailing
    .0, dates become ISO, booleans become true/false."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _finish_rows(raw_rows: list[list[str]], width: int) -> list[list[str]]:
    """Pad/truncate every row to the header width and drop trailing
    all-blank rows (spreadsheet padding). Interior blank rows stay —
    the transform classifies them so row numbers stay honest."""
    rows = [(row + [""] * width)[:width] for row in raw_rows]
    while rows and all(not cell.strip() for cell in rows[-1]):
        rows.pop()
    return rows


def parse_spreadsheet(filename: str, data: bytes) -> tuple[str, list[str], list[list[str]]]:
    """(file_format, headers, rows) from raw bytes. Headers are
    verbatim (duplicates kept — columns are indexed, not named)."""
    file_format, headers, rows, _header_row = _parse_spreadsheet_full(
        filename, data
    )
    return file_format, headers, rows


def _parse_spreadsheet_full(
    filename: str, data: bytes
) -> tuple[str, list[str], list[list[str]], int]:
    """parse_spreadsheet plus the 1-based row the headers were
    found on (1 unless an .xlsx header row sits below a band)."""
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        headers, rows, header_row = _parse_xlsx_full(data)
        return "xlsx", headers, rows, header_row
    if name.endswith(".csv"):
        headers, rows = _parse_csv(data)
        return "csv", headers, rows, 1
    raise ImportFileError(
        "Only .csv and .xlsx files can be imported — pick a spreadsheet "
        "in one of those formats."
    )


# ---------------------------------------------------------------------
# Header-row detection (.xlsx)
#
# A sheet may carry a title / dashboard band above its data (the
# free /downloads sheet does: logo, totals boxes, THEN the labels).
# The header row is the first row that actually names catalog
# columns — matched against every kind's labels and synonyms. A
# row qualifies when it names Name plus at least one more field,
# or when a strong majority of its cells name known fields. Row 1
# wins whenever it qualifies, so established files parse exactly
# as they always have; when no row qualifies, the caller falls
# back to the historic first-row parse untouched.
# ---------------------------------------------------------------------

_HEADER_SCAN_ROWS = 10
_KNOWN_HEADERS: dict[str, str] | None = None


def _known_header_fields() -> dict[str, str]:
    """{normalized header text: field key} over every kind's
    catalog — verbatim labels and the suggestion synonyms alike.
    The first field in catalog order wins a contested string."""
    global _KNOWN_HEADERS
    if _KNOWN_HEADERS is None:
        known: dict[str, str] = {}
        catalog = (*_COMMON_FIELDS, *_TOOL_FIELDS, *_BATTERY_FIELDS)
        for key, label, _type, _required in catalog:
            known.setdefault(_normalize_header(label), key)
            for synonym in _SYNONYMS.get(key, ()):
                known.setdefault(_normalize_header(synonym), key)
        _KNOWN_HEADERS = known
    return _KNOWN_HEADERS


def _matched_header_fields(cells: list[str]) -> set[str]:
    known = _known_header_fields()
    return {
        known[normalized]
        for cell in cells
        if (normalized := _normalize_header(cell)) in known
    }


def _header_row_index(raw: list[list[str]]) -> int | None:
    """The 0-based index of the row naming the columns, or None
    when no row in the scan window reads as a catalog header."""
    best_index: int | None = None
    best_score = 0
    for index, row in enumerate(raw[:_HEADER_SCAN_ROWS]):
        matched = _matched_header_fields(row)
        nonempty = sum(1 for cell in row if cell.strip())
        qualifies = ("name" in matched and len(matched) >= 2) or (
            len(matched) >= 4
            and nonempty > 0
            and len(matched) * 5 >= nonempty * 3  # a strong majority
        )
        if not qualifies:
            continue
        if index == 0:
            return 0
        if len(matched) > best_score:
            best_index, best_score = index, len(matched)
    return best_index


def _split_at_header(
    raw: list[list[str]], index: int
) -> tuple[list[str], list[list[str]]]:
    """(headers, data rows) split at the header row. Index 0 is
    the historic parse, byte for byte; a deeper header row also
    sheds trailing nameless columns the band may have spanned."""
    headers = [cell.strip() for cell in raw[index]]
    if index > 0:
        while headers and not headers[-1]:
            headers.pop()
    rows = _finish_rows(
        [[cell.strip() for cell in row] for row in raw[index + 1 :]],
        len(headers),
    )
    return headers, rows


def _check_shape(headers: list[str], rows: list[list[str]]) -> None:
    if not headers or all(not h.strip() for h in headers):
        raise ImportFileError(
            "That file has no header row — the first row should name each column."
        )
    if len(headers) > MAX_COLUMNS:
        raise ImportFileError(
            f"That file has {len(headers)} columns — imports are capped "
            f"at {MAX_COLUMNS} columns."
        )
    if len(rows) > MAX_ROWS:
        raise ImportFileError(
            f"That file has {len(rows):,} data rows — imports are capped at "
            f"{MAX_ROWS:,} rows per file. Split it and import in batches."
        )


def _parse_csv(data: bytes) -> tuple[list[str], list[list[str]]]:
    if data[:4] == b"PK\x03\x04":
        raise ImportFileError(
            "That file looks like an Excel workbook with a .csv name — "
            "rename it to .xlsx (or save it as a real CSV) and try again."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    raw = [row for row in reader]
    if not raw:
        raise ImportFileError("That file is empty — there's nothing to import.")
    headers = [cell.strip() for cell in raw[0]]
    rows = _finish_rows(
        [[cell.strip() for cell in row] for row in raw[1:]], len(headers)
    )
    _check_shape(headers, rows)
    return headers, rows


def _parse_xlsx_full(
    data: bytes,
) -> tuple[list[str], list[list[str]], int]:
    """(headers, rows, 1-based header row) for a workbook.

    The active sheet is home base: when it carries a recognizable
    header row — on row 1, as always, or below a band — it is the
    sheet that imports. Only when the active sheet names no
    columns at all (a cover sheet, say) do the workbook's other
    sheets get their chance, in order. When nothing anywhere
    qualifies, the historic parse stands: active sheet, first row
    as headers, and the usual shape errors."""
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportFileError(
            "That .xlsx file couldn't be read — it may be damaged, "
            "password-protected, or not really an Excel file."
        ) from None
    active = workbook.active
    if active is None:
        workbook.close()
        raise ImportFileError("That workbook has no sheets to import.")
    sheets = [active] + [ws for ws in workbook.worksheets if ws is not active]
    parsed: list[list[list[str]]] = []
    for sheet in sheets:
        parsed.append(
            [
                [_cell_text(cell) for cell in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        )
    workbook.close()
    active_raw = parsed[0]
    if not active_raw:
        raise ImportFileError("That sheet is empty — there's nothing to import.")
    for raw in parsed:
        if not raw:
            continue
        index = _header_row_index(raw)
        if index is not None:
            headers, rows = _split_at_header(raw, index)
            _check_shape(headers, rows)
            return headers, rows, index + 1
    headers, rows = _split_at_header(active_raw, 0)
    _check_shape(headers, rows)
    return headers, rows, 1


# ---------------------------------------------------------------------
# Field catalog + mapping suggestions
# ---------------------------------------------------------------------

_COMMON_FIELDS: list[tuple[str, str, str, bool]] = [
    ("name", "Name", "text", True),
    ("brand", "Brand", "text", False),
    ("model_numbers", "Model numbers", "multi", False),
    ("serial_numbers", "Serial numbers", "multi", False),
    ("upc", "UPC / barcode", "text", False),
    ("category", "Category", "text", False),
    ("condition", "Condition", "text", False),
    ("location", "Location", "text", False),
    ("dealer_name", "Dealer name", "dealer", False),
    ("quantity", "Quantity", "int", False),
    ("purchase_price", "Purchase price (each)", "money", False),
    ("msrp", "MSRP", "money", False),
    ("replacement_cost", "Replacement cost", "money", False),
    ("purchase_date", "Purchase date", "date", False),
    ("warranty_months", "Warranty term", "term", False),
    ("warranty_provider", "Warranty provider", "text", False),
    ("warranty_contact", "Warranty contact", "text", False),
    ("warranty_terms", "Warranty terms", "text", False),
    ("tags", "Tags", "tags", False),
    ("notes", "Notes / description", "text", False),
]

_TOOL_FIELDS: list[tuple[str, str, str, bool]] = [
    ("size", "Size", "text", False),
    ("consumable", "Consumable", "bool", False),
    ("is_set", "Is a set", "bool", False),
    ("set_serials", "Set serials", "multi", False),
    ("rebuy_store", "Re-buy store", "text", False),
    ("rebuy_url", "Re-buy website", "text", False),
    ("rebuy_sku", "Re-buy SKU", "text", False),
    ("rebuy_notes", "Re-buy notes", "text", False),
]

_BATTERY_FIELDS: list[tuple[str, str, str, bool]] = [
    ("platform", "Platform", "text", False),
    ("voltage", "Voltage", "decimal", False),
    ("capacity_ah", "Capacity (Ah)", "decimal", False),
    ("chemistry", "Chemistry", "text", False),
]


def field_catalog(db: Session, owner_id: uuid.UUID, kind: str) -> list[dict]:
    """The mappable fields for a kind: the standard asset fields
    plus the owner's custom field definitions for that kind."""
    base = list(_COMMON_FIELDS)
    base += _TOOL_FIELDS if kind == "tool" else _BATTERY_FIELDS
    fields = [
        {"key": key, "label": label, "type": ftype, "required": required}
        for key, label, ftype, required in base
    ]
    for definition in custom_fields.list_definitions(db, owner_id, kind):
        fields.append(
            {
                "key": f"cf:{definition.id}",
                "label": f"{definition.label} (custom)",
                "type": "custom",
                "custom_type": definition.field_type,
                "required": bool(definition.required),
            }
        )
    return fields


def _normalize_header(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


# Header synonyms per field (compared normalized). First field in
# catalog order wins a contested header; a single-value field is
# suggested for at most one column, while a multi-value field is
# suggested for EVERY column whose header matches it (a file's
# "Model" and "Model Number" columns both belong in Model numbers).
_SYNONYMS: dict[str, set[str]] = {
    "name": {"name", "item", "item name", "tool", "tool name", "asset", "asset name", "product", "title"},
    "brand": {"brand", "make", "manufacturer", "mfr"},
    "model_numbers": {"model", "model number", "model no", "model numbers", "models", "part", "part number", "part no", "mpn"},
    "serial_numbers": {"serial", "serial number", "serial no", "serial numbers", "serials", "s n", "sn"},
    "upc": {"upc", "barcode", "bar code", "ean", "gtin", "upc code"},
    "category": {"category", "type", "group", "class"},
    "condition": {"condition", "cond", "state"},
    "location": {"location", "loc", "bin", "shelf", "drawer", "storage", "stored in"},
    "dealer_name": {"dealer", "dealer name", "vendor", "supplier", "seller", "bought from", "purchased from"},
    "quantity": {"quantity", "qty", "count", "units", "stock"},
    "purchase_price": {"price", "cost", "purchase price", "purchase price each", "price each", "unit price", "unit cost", "paid", "purchase cost", "buy price"},
    "msrp": {"msrp", "list price", "list", "retail", "retail price"},
    "replacement_cost": {"replacement", "replacement cost", "replacement value", "replacement price", "insured value"},
    "purchase_date": {"purchase date", "date", "date purchased", "purchased", "bought", "acquired", "date acquired", "buy date"},
    "warranty_months": {"warranty", "warranty months", "warranty period", "warranty term", "warranty length", "warranty duration"},
    "warranty_provider": {"warranty provider", "warranty by", "warranted by", "warranty company", "warranty through"},
    "warranty_contact": {"warranty contact", "warranty phone", "warranty email", "claims contact", "warranty contact info"},
    "warranty_terms": {"warranty terms", "warranty notes", "warranty details"},
    "tags": {"tags", "tag", "labels", "keywords"},
    "notes": {"notes", "note", "notes description", "description", "desc", "comments", "comment", "details"},
    "size": {"size", "drive", "dimensions"},
    "consumable": {"consumable", "consumables", "is consumable"},
    "is_set": {"is set", "set", "is a set"},
    "set_serials": {"set serials", "piece serials", "set serial numbers", "piece serial numbers", "serials in set"},
    "rebuy_store": {"rebuy store", "re-buy store", "buy from", "store"},
    "rebuy_url": {"rebuy url", "re-buy website", "reorder link", "buy link"},
    "rebuy_sku": {"rebuy sku", "re-buy sku", "reorder sku", "store sku"},
    "rebuy_notes": {"rebuy notes", "re-buy notes", "reorder notes"},
    "platform": {"platform", "battery platform", "system"},
    "voltage": {"voltage", "volts", "v"},
    "capacity_ah": {"capacity", "capacity ah", "ah", "amp hours"},
    "chemistry": {"chemistry", "cell type", "battery chemistry"},
}


def suggest_mapping(headers: list[str], fields: list[dict]) -> dict[int, str]:
    """{column_index: field_key} auto-suggestions from header names.
    Custom fields match on their slug or label."""
    synonyms: dict[str, set[str]] = {}
    for field in fields:
        key = field["key"]
        if key.startswith("cf:"):
            synonyms[key] = {
                _normalize_header(field["label"].removesuffix(" (custom)"))
            }
        else:
            synonyms[key] = _SYNONYMS.get(key, set())
    taken: set[str] = set()
    suggestions: dict[int, str] = {}
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        if not normalized:
            continue
        for field in fields:
            key = field["key"]
            # Multi-value fields are exempt from the one-column rule:
            # every matching column is suggested the same list field.
            if field["type"] != "multi" and key in taken:
                continue
            if normalized in synonyms.get(key, set()):
                suggestions[index] = key
                taken.add(key)
                break
    return suggestions


# ---------------------------------------------------------------------
# Value coercion (the tolerance table)
#
#   dates:  YYYY-MM-DD, MM/DD/YYYY, MM/DD/YY, DD MMM YYYY,
#           DD Month YYYY, YYYY/MM/DD, ISO datetimes
#   money:  $ / € / £, thousands commas and spaces stripped
#   ints:   "3", "3.0"; blank quantity -> 1
#   bools:  yes/no, true/false, 1/0, y/n, on/off
#   multi:  split on ; or , (models, serials, tags)
#   warranty terms: a plain number is months, "N year(s)" is 12xN
#           months, "N days" is N/30 months and "N weeks" is
#           N*12/52 months (whole-month results only), "lifetime"
#           is the lifetime type (no end date)
#
# An unparseable OPTIONAL value is dropped with a warning, never
# silently and never fatal. Only a missing name is a row error.
# ---------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%b %d %Y",
    "%B %d %Y",
)

_TRUE_WORDS = {"yes", "y", "true", "t", "1", "on"}
_FALSE_WORDS = {"no", "n", "false", "f", "0", "off"}


def _parse_date(raw: str) -> date:
    text = raw.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        pass
    # "January 5, 2024" / "5 Jan, 2024": commas are punctuation noise.
    text = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{raw}'")


def _parse_money(raw: str) -> Decimal:
    text = re.sub(r"[$€£,\s]", "", raw.strip())
    if not text or text.startswith("("):
        raise ValueError(f"unrecognized amount '{raw}'")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"unrecognized amount '{raw}'") from None
    if value < 0:
        raise ValueError(f"negative amount '{raw}'")
    return value.quantize(Decimal("0.01"))


def _parse_decimal(raw: str) -> Decimal:
    match = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", raw.strip())
    if not match:
        raise ValueError(f"unrecognized number '{raw}'")
    value = Decimal(match.group(1))
    if value < 0:
        raise ValueError(f"negative number '{raw}'")
    return value


def _parse_int(raw: str) -> int:
    text = re.sub(r"[,\s]", "", raw.strip())
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"unrecognized whole number '{raw}'") from None
    if value != value.to_integral_value():
        raise ValueError(f"'{raw}' is not a whole number")
    return int(value)


def _parse_bool(raw: str) -> bool:
    text = raw.strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise ValueError(f"unrecognized yes/no value '{raw}'")


def _split_multi(raw: str) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[;,]", raw or ""):
        text = part.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _dedupe_multi(values: list[str]) -> list[str]:
    """Dedupe a merged multi-value list, case/whitespace-
    insensitively (the category-identity normalization): the first
    occurrence's own spelling wins, later lookalikes drop. This is
    what makes mapping both of a file's duplicate "Model" /
    "Model Number" columns land ONE copy of each number."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = re.sub(r"\s+", " ", value.strip()).casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


_LIFETIME_WORDS = {"lifetime", "life time", "for life", "lifetime warranty", "forever"}
_TERM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*-?\s*(months?|mos?|mo|years?|yrs?|yr|y|weeks?|days?)?"
)


def _parse_warranty_term(raw: str) -> tuple[int | None, str | None]:
    """A warranty term cell -> (months, warranty_type).

        "24" / "24.0"        -> (24, None)      plain number = months
        "24 months" / "6 mo" -> (24, None) / (6, None)
        "2 years" / "1 yr"   -> (24, None) / (12, None)   years x 12
        "1.5 years"          -> (18, None)      fractional, integral result
        "90 days" / "30 days" -> (3, None) / (1, None)    30 days = 1 month
        "13 weeks" / "52 weeks" -> (3, None) / (12, None) 52 weeks = 12 months
        "lifetime"           -> (None, "lifetime")
    Day/week terms land only when they convert to whole months —
    "45 days" raises like anything else unrecognized (the stored
    value is whole months; nothing is ever rounded into place).
    Anything else raises ValueError (the caller warns + drops)."""
    text = re.sub(r"\s+", " ", raw.strip()).casefold()
    if text in _LIFETIME_WORDS:
        return None, "lifetime"
    match = _TERM_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"unrecognized warranty term '{raw}'")
    number = Decimal(match.group(1))
    unit = match.group(2) or "months"
    if unit.startswith("y"):
        months = number * 12
    elif unit.startswith("w"):
        months = number * 3 / 13  # 52 weeks = 12 months, kept exact
    elif unit.startswith("d"):
        months = number / 30  # 30 days = 1 month
    else:
        months = number
    if months != months.to_integral_value() or months < 1:
        raise ValueError(f"unrecognized warranty term '{raw}'")
    return int(months), None


# ---------------------------------------------------------------------
# Mapping validation
# ---------------------------------------------------------------------


def validate_mapping(
    db: Session, owner_id: uuid.UUID, mapping_raw: dict, kind: str, column_count: int
) -> dict[int, str]:
    """{column_index: field_key} from the client's JSON shape.
    Refuses unknown columns/fields. Single-value fields take ONE
    column (hard rule, no silent last-wins); multi-value list fields
    (type "multi") may take several columns, whose values merge."""
    fields = {f["key"]: f for f in field_catalog(db, owner_id, kind)}
    mapping: dict[int, str] = {}
    for raw_index, field_key in (mapping_raw or {}).items():
        if field_key in (None, ""):
            continue
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ImportMappingError(
                f"'{raw_index}' is not a column number."
            ) from None
        if not 0 <= index < column_count:
            raise ImportMappingError(
                f"Column {index + 1} doesn't exist in this file."
            )
        if field_key not in fields:
            raise ImportMappingError(f"'{field_key}' is not an importable field.")
        if field_key in mapping.values() and fields[field_key]["type"] != "multi":
            other = next(i for i, k in mapping.items() if k == field_key)
            raise ImportMappingError(
                f"Columns {other + 1} and {index + 1} are both mapped to "
                f"'{fields[field_key]['label']}' — that field takes one "
                "column only. Only list fields (Model numbers, Serial "
                "numbers, Set serials) can combine several columns; for "
                "every other field, combine the values into a single "
                "column or unmap one of them."
            )
        mapping[index] = field_key
    if "name" not in mapping.values():
        raise ImportMappingError(
            "Map a column to Name first — every imported item needs a name."
        )
    return mapping


# ---------------------------------------------------------------------
# Row transformation (shared by dry run and confirm)
# ---------------------------------------------------------------------


def _dealer_index(db: Session, owner_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """{normalized company name: id} over the companies the user can
    see (directory + their private companies). Matching only — the
    importer never creates companies."""
    from app.modules.dealers import service as dealers_service

    index: dict[str, uuid.UUID] = {}
    for company in dealers_service.list_companies(db, owner_id):
        index.setdefault(company.name.strip().lower(), company.id)
        index.setdefault(_normalize_header(company.name), company.id)
    return index


def _coerce_custom(definition, raw: str, label: str):
    """Coerce one custom-field cell by the definition's type.
    Returns the value for custom_data; raises ValueError on garbage.
    Dropdowns match options exactly, then case-insensitively."""
    field_type = definition.field_type
    if field_type == "text":
        return raw.strip()
    if field_type == "number":
        value = _parse_decimal(raw)
        return int(value) if value == value.to_integral_value() else float(value)
    if field_type == "boolean":
        return _parse_bool(raw)
    if field_type == "date":
        return _parse_date(raw).isoformat()
    if field_type == "dropdown":
        text = raw.strip()
        for option in definition.options or []:
            if str(option) == text:
                return option
        for option in definition.options or []:
            if str(option).lower() == text.lower():
                return option
        raise ValueError(f"'{raw}' is not one of the '{label}' options")
    return raw.strip()


def transform_rows(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    rows: list[list[str]],
    mapping: dict[int, str],
    resolutions: dict | None = None,
    header_row: int = 1,
) -> list[dict]:
    """Classify every row and build its create-values.

    Returns one dict per data row: {row (spreadsheet number),
    status: ok|warning|error|blank, messages, duplicate, name,
    values}. `values` feeds _create_from_values at confirm time.
    `header_row` is the 1-based spreadsheet row the headers sit
    on — row numbers in the results are the rows the user sees
    in their spreadsheet (a banded sheet's first data row is
    honestly row header_row + 1, not row 2).

    `resolutions` is the smart-matching outcome ({field: {raw:
    resolution}} from matching.resolve_effective): every distinct
    dealer / brand / category / tag / location value in the file
    has one, and applying it here — identically for the dry run and
    the confirm — is what keeps the two in agreement.
    """
    fields = {f["key"]: f for f in field_catalog(db, owner_id, kind)}
    definitions = {
        str(d.id): d
        for d in custom_fields.list_definitions(db, owner_id, kind)
    }
    required_custom = [d for d in definitions.values() if d.required]
    dealer_index = _dealer_index(db, owner_id)

    # Existing-inventory duplicate index: name -> serial sets.
    existing_by_name: dict[str, list[set[str]]] = {}
    if kind == "tool":
        existing = db.scalars(
            select(models.Tool).where(models.Tool.owner_id == owner_id)
        )
        for record in existing:
            serials = {s.strip().lower() for s in (record.serial_numbers or []) if s.strip()}
            if record.serial_number.strip():
                serials.add(record.serial_number.strip().lower())
            existing_by_name.setdefault(record.name.strip().lower(), []).append(serials)
    else:
        existing_b = db.scalars(
            select(models.Battery).where(models.Battery.owner_id == owner_id)
        )
        for record in existing_b:
            serials = (
                {record.serial_number.strip().lower()}
                if record.serial_number.strip()
                else set()
            )
            existing_by_name.setdefault(record.name.strip().lower(), []).append(serials)

    results: list[dict] = []
    seen_in_file: dict[tuple[str, str], int] = {}
    for offset, raw_row in enumerate(rows):
        row_number = offset + header_row + 1  # first data row is header_row + 1
        cells = {
            index: (raw_row[index] if index < len(raw_row) else "")
            for index in mapping
        }
        if all(not (value or "").strip() for value in cells.values()):
            results.append(
                {
                    "row": row_number,
                    "status": "blank",
                    "messages": ["Blank row — skipped."],
                    "duplicate": False,
                    "name": "",
                    "values": {},
                    "preview": {
                        "models": [],
                        "serials": [],
                        "is_set": False,
                        "set_serials": [],
                    },
                }
            )
            continue

        values: dict = {"custom_data": {}}
        tag_names: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        # Column order is significant: when several columns feed one
        # multi-value field, their values merge in column order (the
        # first column's value is the headline entry).
        for index, field_key in sorted(mapping.items()):
            raw = (cells.get(index) or "").strip()
            field = fields[field_key]
            label = field["label"]
            if field["type"] == "custom":
                definition = definitions[field_key[3:]]
                if not raw:
                    continue
                try:
                    values["custom_data"][str(definition.id)] = _coerce_custom(
                        definition, raw, label
                    )
                except ValueError as exc:
                    warnings.append(f"{label}: {exc} — value dropped.")
                continue
            if field_key == "tags":
                tag_names = _split_multi(raw)
                continue
            if not raw:
                continue  # blank optional cell: the field just stays unset
            try:
                if field["type"] == "text":
                    values[field_key] = raw
                elif field["type"] in ("multi",):
                    # Accumulate across every column mapped to this
                    # list field; the dedupe pass below collapses
                    # repeats (incl. a file's duplicate columns).
                    values.setdefault(field_key, []).extend(_split_multi(raw))
                elif field["type"] == "term":
                    months, warranty_type = _parse_warranty_term(raw)
                    if months is not None:
                        values["warranty_months"] = months
                    if warranty_type is not None:
                        values["warranty_type"] = warranty_type
                elif field["type"] == "money":
                    values[field_key] = _parse_money(raw)
                elif field["type"] == "decimal":
                    values[field_key] = _parse_decimal(raw)
                elif field["type"] == "date":
                    values[field_key] = _parse_date(raw)
                elif field["type"] == "bool":
                    values[field_key] = _parse_bool(raw)
                elif field["type"] == "int":
                    values[field_key] = _parse_int(raw)
                elif field["type"] == "dealer":
                    values["dealer_name"] = raw
            except ValueError as exc:
                warnings.append(f"{label}: {exc} — value dropped.")

        # Quantity: blank means 1 (never an error); a garbage value
        # already warned + dropped above, so the default applies.
        if mapping and "quantity" in mapping.values():
            values.setdefault("quantity", 1)

        # Merged multi-value lists dedupe (case/whitespace-
        # insensitively) once all their columns have contributed.
        for multi_key in ("model_numbers", "serial_numbers", "set_serials"):
            if values.get(multi_key):
                values[multi_key] = _dedupe_multi(values[multi_key])

        # A row carrying piece serials IS a set, whether or not the
        # file also has an "is set" column saying so.
        if values.get("set_serials"):
            values["is_set"] = True

        # Batteries store ONE model/serial: extras are dropped loudly.
        if kind == "battery":
            for list_key in ("model_numbers", "serial_numbers"):
                entries = values.get(list_key) or []
                if len(entries) > 1:
                    warnings.append(
                        f"Batteries store one {'model' if list_key == 'model_numbers' else 'serial number'} "
                        f"— kept '{entries[0]}', dropped {len(entries) - 1} extra."
                    )

        # Smart matching (2026-10-19): the Resolve step's answers
        # rewrite this row's brand / category / location / tags to
        # their resolved forms BEFORE anything reads them, so every
        # downstream consumer (duplicate checks, creation) sees the
        # values the user approved.
        for text_field in ("brand", "category"):
            if text_field in values:
                resolution = (resolutions or {}).get(text_field, {}).get(
                    values[text_field]
                )
                if resolution is not None:
                    if resolution["action"] == "map":
                        values[text_field] = resolution["target_value"]
                    elif resolution["action"] == "unset":
                        values.pop(text_field)
        if "location" in values:
            resolution = (resolutions or {}).get("location", {}).get(
                values["location"]
            )
            if resolution is not None:
                if resolution["action"] == "map":
                    node_id = uuid.UUID(resolution["target_id"])
                    values["location_id"] = node_id
                    values["location"] = service.location_text_for(
                        db, owner_id, node_id
                    )
                elif resolution["action"] == "unset":
                    values["location"] = ""
                    values["location_id"] = None
                # "create" reaches the transform only in a dry run
                # (confirm materializes the node first and rewrites
                # the answer to a map) — the raw text stands.
        tag_resolutions = (resolutions or {}).get("tags", {})
        if tag_resolutions:
            rewritten_tags: list[str] = []
            for tag_name in tag_names:
                resolution = tag_resolutions.get(tag_name)
                if resolution is None or resolution["action"] == "create":
                    resolved_name = tag_name
                elif resolution["action"] == "map":
                    resolved_name = resolution["target_value"]
                else:  # unset: the tag is dropped from this import
                    continue
                if resolved_name not in rewritten_tags:
                    rewritten_tags.append(resolved_name)
            tag_names = rewritten_tags

        # Dealer resolution: the Resolve step's answer wins. A
        # "create" answer reaches the transform only in a dry run
        # (confirm mints the private company first and rewrites the
        # answer to a map) — no id exists yet, and the mappings
        # summary in the dry-run response says what's coming. The
        # legacy index lookup remains only as the fallback for a
        # value no resolution covers.
        dealer_name = values.pop("dealer_name", "")
        if dealer_name:
            resolution = (resolutions or {}).get("dealer_name", {}).get(
                dealer_name
            )
            if resolution is not None:
                if resolution["action"] == "map":
                    values["dealer_company_id"] = uuid.UUID(
                        resolution["target_id"]
                    )
            else:
                company_id = dealer_index.get(
                    dealer_name.strip().lower()
                ) or dealer_index.get(_normalize_header(dealer_name))
                if company_id is not None:
                    values["dealer_company_id"] = company_id
                else:
                    warnings.append(
                        f"Dealer '{dealer_name}' isn't in the directory or your "
                        "private companies — this item will import untagged."
                    )

        values["tag_names"] = tag_names

        name_value = (values.get("name") or "").strip()
        if not name_value:
            errors.append("Missing name — every item needs one.")
        for definition in required_custom:
            if str(definition.id) not in values["custom_data"]:
                errors.append(
                    f"Missing required custom field '{definition.label}'."
                )

        # Duplicates: same name + a shared serial, against the
        # existing vault or an earlier row of this same file.
        duplicate = False
        serial_values = values.get("serial_numbers") or []
        if name_value and serial_values:
            name_key = name_value.lower()
            row_serials = {s.strip().lower() for s in serial_values if s.strip()}
            for serial_set in existing_by_name.get(name_key, []):
                if row_serials & serial_set:
                    duplicate = True
                    warnings.append(
                        "Duplicate: an item with this name and serial "
                        "number is already in your inventory."
                    )
                    break
            if not duplicate:
                for serial in row_serials:
                    first_row = seen_in_file.get((name_key, serial))
                    if first_row is not None:
                        duplicate = True
                        warnings.append(
                            f"Duplicate: row {first_row} in this file has "
                            "the same name and serial number."
                        )
                        break
            for serial in row_serials:
                seen_in_file.setdefault((name_key, serial), row_number)

        # The dry run's per-row preview: the merged number lists as
        # they will land (batteries show the single kept entry), the
        # set flag and its piece serials — so the user sees exactly
        # what a multi-column merge produced before confirming.
        preview_models = list(values.get("model_numbers") or [])
        preview_serials = list(values.get("serial_numbers") or [])
        if kind == "battery":
            preview_models = preview_models[:1]
            preview_serials = preview_serials[:1]
        preview = {
            "models": preview_models,
            "serials": preview_serials,
            "is_set": bool(values.get("is_set")),
            "set_serials": list(values.get("set_serials") or []),
        }

        status = "error" if errors else "warning" if warnings else "ok"
        results.append(
            {
                "row": row_number,
                "status": status,
                "messages": errors + warnings,
                "duplicate": duplicate,
                "name": name_value,
                "values": values,
                "preview": preview,
            }
        )
    return results


# ---------------------------------------------------------------------
# Creation (confirm)
# ---------------------------------------------------------------------


def _create_from_values(
    db: Session, owner_id: uuid.UUID, kind: str, values: dict
) -> None:
    """Create one asset from transformed values through inventory's
    own create service — imported items are ordinary assets."""
    tag_ids = []
    for tag_name in values.get("tag_names") or []:
        tag = service.create_tag(db, owner_id, tag_name)
        tag_ids.append(tag.id)
    direct = (
        "name", "brand", "category", "condition", "location", "location_id",
        "notes", "quantity", "purchase_price", "msrp", "replacement_cost",
        "purchase_date", "dealer_company_id", "upc",
    )
    kwargs = {key: values[key] for key in direct if key in values}
    kwargs["tag_ids"] = tag_ids
    kwargs["custom_data"] = values.get("custom_data") or {}
    warranty_keys = (
        "warranty_months",
        "warranty_provider",
        "warranty_contact",
        "warranty_terms",
        "warranty_type",
    )
    for key in warranty_keys:
        if key in values:
            kwargs[key] = values[key]
    if kind == "tool":
        for key in (
            "size",
            "consumable",
            "rebuy_store",
            "rebuy_url",
            "rebuy_sku",
            "rebuy_notes",
            "model_numbers",
            "serial_numbers",
        ):
            if key in values:
                kwargs[key] = values[key]
        if values.get("is_set"):
            kwargs["is_set"] = True
            set_serials = values.get("set_serials") or []
            if set_serials:
                # Imported pieces are CORE pieces in file order,
                # named the way the set editor labels its rows
                # ("Piece 1", "Piece 2", …) — the file carries
                # serials, not names, and a piece requires one.
                kwargs["pieces"] = [
                    {
                        "kind": "core",
                        "name": f"Piece {position + 1}",
                        "serial_number": serial,
                        "sort_order": position,
                    }
                    for position, serial in enumerate(set_serials)
                ]
        service.create_tool(db, owner_id, schemas.ToolCreate(**kwargs))
    else:
        models_ = values.get("model_numbers") or []
        serials = values.get("serial_numbers") or []
        if models_:
            kwargs["model"] = models_[0]
        if serials:
            kwargs["serial_number"] = serials[0]
        for key in ("platform", "voltage", "capacity_ah", "chemistry"):
            if key in values:
                kwargs[key] = values[key]
        service.create_battery(db, owner_id, schemas.BatteryCreate(**kwargs))
