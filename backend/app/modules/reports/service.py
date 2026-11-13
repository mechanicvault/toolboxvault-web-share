"""Reports service: the dataset engine + saved configurations.

SERVICE INTERFACE (stable; bump manifest version on change):
  - column_catalog(db, owner_id) -> list[dict]   (base + the owner's
    custom-field columns)
  - build_report(db, owner_id, spec, dealer_visible=True) -> dict
    The full structured report: resolved columns, grouped rows with
    typed values + display strings, per-group subtotals, grand
    totals. Exports render from exactly this structure, so the CSV
    on disk and the table on screen can never disagree.
  - run_report(...) — build_report + pagination for the screen.
  - Saved configs: list_configs / get_config / create_config /
    update_config / delete_config (owner-scoped; foreign ids read
    as missing, so cross-user answers are 404s, never leaks).
  - PRESETS — the built-in configurations (code, not rows).

DATASET RULES (the module doctrine applied to reports):
  - Rows come through inventory's service interface and billing's
    SHARED active set (entitlements.active_tool_ids /
    active_battery_ids): with enforcement on, lapsed/inactive
    assets vanish from reports exactly as they vanish from stats
    and sharing — never a private query.
  - Money is PER UNIT on the records; every total multiplies by
    quantity (the app's "Price Each" rule).
  - Checked-out state reads the borrowing ledger through its
    service (borrowing may be off — the ledger is still the truth
    about what's out).

SETS (owner's rule: anything touching a set asks about addons):
the spec's sets_mode IS the answer to that question, asked in the
builder every time a report is built or run:
  - summary:   a set is ONE row, valued whole (own price + addon
               pieces + attached tools — the bundle's worth).
  - with_core: core pieces appear as rows under their set; the set
               row still carries the addons' value, since they
               aren't rows yet.
  - full:      core pieces, addon pieces AND attached tools all
               appear as rows; the set row carries only its own
               price and the members carry theirs.
Grand totals therefore agree between summary and with_core, and
full itemizes the same money across more rows.

PIECE PRICES (owner 2026-10-25): any set piece may carry its OWN
price (what that piece cost / would cost to replace). A core
piece's price shows on its piece row in the deep modes; an
unpriced core piece's price cells read "in set". A core piece
price NEVER joins any total — the set row doesn't carry it and
_subtotal skips core-piece rows — because it is the piece's own
figure, not set money (no silent rollup, in any mode).
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.modules.billing import entitlements
from app.modules.core import money as core_money
from app.modules.borrowing import service as borrowing_service
from app.modules.inventory import custom_fields
from app.modules.inventory import service as inventory_service
from app.modules.reports import columns as colmod
from app.modules.reports import models, schemas

_CENTS = Decimal("0.01")

WARRANTY_LABELS = {
    "in_warranty": "In warranty",
    "expiring_soon": "Expiring soon",
    "expired": "Expired",
    "unknown": "Unknown",
}

# Repair standing labels (maintenance module, 2026-10-19): the
# standing lives on the inventory records, so a report reads it
# straight off the row — no maintenance import needed. Pieces keep
# the repair trio; assets read their Package B `standing` (the
# `repair_status` column key now speaks standing, lost/stolen
# included — saved configs keep working untouched).
REPAIR_LABELS = {
    "in_service": "In service",
    "broken": "Broken",
    "in_repair": "In repair",
}
STANDING_LABELS = {
    **REPAIR_LABELS,
    "lost": "Lost",
    "stolen": "Stolen",
    "sold": "Sold",
    "replaced": "Replaced",
}

# Column keys retired by later packages. Saved configs that still
# name one keep running — the key is dropped, not an error.
_RETIRED_COLUMN_KEYS = {"condition"}


class ReportError(ValueError):
    """A report spec breaks a rule (unknown column, grouping, sort
    key...). Routes turn this into a 422."""


# -- catalog -------------------------------------------------------------------


def column_catalog(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Base columns + one column per custom-field definition the
    owner has (either kind — a report row shows a value only where
    the definition applies to the row's kind)."""
    catalog = [dict(c) for c in colmod.BASE_COLUMNS]
    for definition in custom_fields.list_definitions(db, owner_id, "all"):
        catalog.append(
            {
                "key": colmod.custom_key(definition.id),
                "label": definition.label,
                "type": "text",
                "custom": True,
                "item_type": definition.item_type,
            }
        )
    return catalog


def _resolve_columns(
    db: Session, owner_id: uuid.UUID, keys: list[str] | None
) -> tuple[list[dict], dict[str, dict]]:
    catalog = column_catalog(db, owner_id)
    by_key = {c["key"]: c for c in catalog}
    wanted = list(keys) if keys else list(colmod.DEFAULT_COLUMNS)
    wanted = [k for k in wanted if k not in _RETIRED_COLUMN_KEYS]
    resolved = []
    for key in wanted:
        column = by_key.get(key)
        if column is None:
            raise ReportError(f"Unknown report column: {key}")
        resolved.append(column)
    return resolved, by_key


# -- row building ---------------------------------------------------------------


def _money(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_CENTS)


def _total(per_unit, quantity: int) -> Decimal | None:
    if per_unit is None:
        return None
    return _money(Decimal(str(per_unit)) * (quantity or 1))


def _tag_names(db: Session, owner_id: uuid.UUID, kind: str, item_id) -> list[str]:
    return [
        tag.name
        for tag in inventory_service.get_item_tags(db, owner_id, kind, item_id)
    ]


def _checked_out(db: Session, kind: str, item_id) -> bool:
    return borrowing_service.active_checkout(db, kind, item_id) is not None


def _custom_values(record, kind: str, definitions: list) -> dict:
    values = {}
    data = record.custom_data or {}
    for definition in definitions:
        if definition.item_type not in (kind, "both"):
            continue
        raw = data.get(str(definition.id))
        values[colmod.custom_key(definition.id)] = _custom_display(
            definition.field_type, raw
        )
    return values


def _custom_display(field_type: str, raw) -> str | None:
    if raw is None or raw == "":
        return None
    if field_type == "boolean":
        return "Yes" if raw in (True, "true", "True", 1) else "No"
    return str(raw)


def _first_photo(record) -> dict | None:
    """The record's FIRST photo attachment (reports alignment):
    the photo column's image. Attachments are stored dicts; kind
    "photo" is images-only by the storage rules. Returns the
    storage facts the renderers need, or None — a row without a
    photo renders a clean placeholder everywhere."""
    for item in record.attachments or []:
        if isinstance(item, dict) and "key" in item and item.get("kind") == "photo":
            return {
                "key": item["key"],
                "filename": item.get("filename", ""),
                "content_type": item.get("content_type", ""),
            }
    return None


class _Row:
    """One report row with typed values for EVERY catalog column
    (display projects the selected subset)."""

    __slots__ = ("row_type", "kind", "set_name", "values", "group_tags", "in_set_price", "photo")

    def __init__(self, row_type, kind, set_name, values, group_tags, in_set_price=False, photo=None):
        self.row_type = row_type
        self.kind = kind  # "tool" | "battery"
        self.set_name = set_name
        self.values = values
        self.group_tags = group_tags  # tag names this row groups under
        self.in_set_price = in_set_price  # core piece: its price is display-only (never totaled)
        self.photo = photo  # _first_photo dict | None (sets: the set's own photo)


def _dealer_name(db, company_id, dealer_visible, cache: dict | None) -> str:
    """Dealer display name through the build's cache when one is
    provided (step-4 fix D5 — a vault reuses a handful of dealers;
    the per-row lookup cost a query each)."""
    if not dealer_visible:
        return ""
    if cache is None:
        return inventory_service.dealer_company_name(db, company_id) or ""
    if company_id not in cache:
        cache[company_id] = (
            inventory_service.dealer_company_name(db, company_id) or ""
        )
    return cache[company_id]


WARRANTY_TYPE_LABELS = {
    "term": "Term",
    "lifetime": "Lifetime",
    "limited": "Limited",
}


def _rebuy_extras(record) -> dict:
    """The audit-A7 re-buy columns for one asset row: the tool's
    own fields; anything without them (batteries, pieces) reads
    blank via the same getattr discipline as _warranty_extras."""
    return {
        "rebuy_store": getattr(record, "rebuy_store", "") or "",
        "rebuy_url": getattr(record, "rebuy_url", "") or "",
        "rebuy_sku": getattr(record, "rebuy_sku", "") or "",
        "rebuy_notes": getattr(record, "rebuy_notes", "") or "",
    }


def _warranty_extras(record, loss_report) -> dict:
    """The gap-wave-1 report columns for one asset: structured
    warranty facts + the most recent lost/stolen report's paper
    trail (the map is built once per build — _collect_rows)."""
    return {
        "warranty_provider": getattr(record, "warranty_provider", "") or "",
        "warranty_type": WARRANTY_TYPE_LABELS.get(
            getattr(record, "warranty_type", None) or "", ""
        ),
        "police_report_number": (
            loss_report.police_report_number if loss_report is not None else ""
        ),
        "loss_reported_date": (
            loss_report.reported_date if loss_report is not None else None
        ),
    }


def _sale_extras(sale) -> dict:
    """The wave-2 sold columns for one row: the item's latest
    EFFECTIVE sale from the ledger map (built once per build in
    _collect_rows, the loss-map discipline) — blank when the
    item was never sold (or its only sale was undone)."""
    if sale is None:
        return {"sale_price": None, "sold_on": None, "buyer": ""}
    return {
        "sale_price": _money(sale.sale_price),
        "sold_on": sale.sold_on,
        "buyer": sale.buyer_name or "",
    }


def _tool_values(db, owner_id, tool, definitions, dealer_visible, status: str, *, tag_names=None, dealer_cache=None, loss_report=None, sale=None) -> dict:
    models_list = list(tool.model_numbers or []) or ([tool.model] if tool.model else [])
    serials_list = list(tool.serial_numbers or []) or (
        [tool.serial_number] if tool.serial_number else []
    )
    photo = _first_photo(tool)
    values = {
        "name": tool.name,
        # The photo column's VALUE is the filename (CSV's cell);
        # image surfaces read the row's photo block instead.
        "photo": photo["filename"] if photo else None,
        "kind": "Tool",
        "brand": tool.brand or "",
        "models": ", ".join(models_list),
        "serials": ", ".join(serials_list),
        "category": tool.category or "",
        "location": tool.location or "",
        "dealer": _dealer_name(db, tool.dealer_company_id, dealer_visible, dealer_cache),
        "tags": ", ".join(
            tag_names
            if tag_names is not None
            else _tag_names(db, owner_id, "tool", tool.id)
        ),
        "quantity": tool.quantity or 1,
        "price_each": _money(tool.purchase_price),
        "price_total": _total(tool.purchase_price, tool.quantity or 1),
        "msrp": _total(tool.msrp, tool.quantity or 1),
        "replacement": _total(tool.replacement_cost, tool.quantity or 1),
        "purchase_date": tool.purchase_date,
        # Tools carry warranty terms since the maintenance build —
        # the same shared computation batteries use.
        "warranty": WARRANTY_LABELS[inventory_service.tool_warranty_status(tool)],
        "repair_status": STANDING_LABELS[getattr(tool, "standing", tool.repair_state)],
        "status": status,
        "set": "",
    }
    values.update(_warranty_extras(tool, loss_report))
    values.update(_rebuy_extras(tool))
    values.update(_sale_extras(sale))
    values.update(_custom_values(tool, "tool", definitions))
    return values


def _battery_values(db, owner_id, battery, definitions, dealer_visible, status: str, *, tag_names=None, dealer_cache=None, loss_report=None, sale=None) -> dict:
    photo = _first_photo(battery)
    values = {
        "name": battery.name,
        "photo": photo["filename"] if photo else None,
        "kind": "Battery",
        "brand": battery.brand or "",
        "models": battery.model or "",
        "serials": battery.serial_number or "",
        "category": battery.category or "",
        "location": battery.location or "",
        "dealer": _dealer_name(db, battery.dealer_company_id, dealer_visible, dealer_cache),
        "tags": ", ".join(
            tag_names
            if tag_names is not None
            else _tag_names(db, owner_id, "battery", battery.id)
        ),
        "quantity": battery.quantity or 1,
        "price_each": _money(battery.purchase_price),
        "price_total": _total(battery.purchase_price, battery.quantity or 1),
        "msrp": _total(battery.msrp, battery.quantity or 1),
        "replacement": _total(battery.replacement_cost, battery.quantity or 1),
        "purchase_date": battery.purchase_date,
        "warranty": WARRANTY_LABELS[inventory_service.warranty_status(battery)],
        "repair_status": STANDING_LABELS[getattr(battery, "standing", battery.repair_state)],
        "status": status,
        "set": "",
    }
    values.update(_warranty_extras(battery, loss_report))
    values.update(_rebuy_extras(battery))
    values.update(_sale_extras(sale))
    values.update(_custom_values(battery, "battery", definitions))
    return values


def _matches_text(values: dict, needle: str, extra: str = "") -> bool:
    haystack = " ".join(
        str(values.get(k) or "")
        for k in ("name", "brand", "models", "serials", "category", "location", "dealer", "tags")
    )
    return needle in haystack.lower() or needle in extra.lower()


def _asset_passes(
    values: dict,
    filters: schemas.ReportFilters,
    *,
    price_total: Decimal | None,
    warranty_key: str | None,
    is_set: bool,
    checked_out: bool,
    tag_names: list[str],
) -> bool:
    """Filters judge ASSETS (a set is judged whole — see the module
    docstring for the price rule). Members follow their set."""
    f = filters
    if f.kind and values["kind"].lower() != f.kind:
        return False
    if f.category and (values["category"] or "") != f.category:
        return False
    if f.location and (values["location"] or "") != f.location:
        return False
    if f.tag and f.tag not in tag_names:
        return False
    if f.warranty and warranty_key != f.warranty:
        return False
    if f.only_sets and not is_set:
        return False
    if f.only_checked_out and not checked_out:
        return False
    if f.min_price is not None and (price_total is None or price_total < f.min_price):
        return False
    if f.max_price is not None and (price_total is None or price_total > f.max_price):
        return False
    if f.date_from and (
        values["purchase_date"] is None or values["purchase_date"] < f.date_from
    ):
        return False
    if f.date_to and (
        values["purchase_date"] is None or values["purchase_date"] > f.date_to
    ):
        return False
    return True


def _collect_rows(
    db: Session,
    owner_id: uuid.UUID,
    spec: schemas.ReportSpec,
    definitions: list,
    dealer_visible: bool,
) -> list[_Row]:
    filters = spec.filters
    sets_mode = spec.sets_mode
    needle = filters.q.strip().lower()

    active_tools = entitlements.active_tool_ids(db, owner_id)
    active_batteries = entitlements.active_battery_ids(db, owner_id)

    tools = [
        t
        for t in inventory_service.list_tools(db, owner_id, include_attached=True)
        if t.attached_to_set_id is None
        and (active_tools is None or t.id in active_tools)
    ]
    batteries = [
        b
        for b in inventory_service.list_batteries(db, owner_id)
        if active_batteries is None or b.id in active_batteries
    ]

    # Batch seams (step-4 fix D5): at vault scale the per-row
    # lookups below cost a query EACH (tags, checkout state, dealer
    # name, set members) — ~4 queries × 11k rows was the 22-second
    # report run. Each is now ONE query (or one per dealer) for the
    # whole build; the row code reads the same values from maps.
    tag_map = inventory_service.item_tag_names_bulk(db, owner_id)
    checkout_keys = borrowing_service.active_checkout_keys(db, owner_id)
    dealer_cache: dict = {}
    members_by_set = inventory_service.resolve_set_members_bulk(
        db, [t for t in tools if t.is_set], include_addons=True
    )
    # Lost/stolen paper trail (gap wave 1): the latest report per
    # item, one query for the whole build (same batch discipline).
    loss_map = inventory_service.latest_loss_reports(db, owner_id)
    # Sold ledger (wave 2): the latest EFFECTIVE sale per item,
    # one query for the whole build (same batch discipline). The
    # provider lives in inventory's sales service; reports reads
    # it through the seam, never the table.
    from app.modules.inventory import sales as inventory_sales

    sales_map = inventory_sales.latest_sales_map(db, owner_id)

    rows: list[_Row] = []

    for tool in tools:
        is_set = bool(tool.is_set)
        checked = ("tool", tool.id) in checkout_keys
        status = (
            "Checked out" if checked
            else "Sold" if getattr(tool, "standing", "") == "sold"
            else "Replaced" if getattr(tool, "standing", "") == "replaced"
            else "Active"
        )
        group_tags = tag_map.get(("tool", tool.id), [])
        values = _tool_values(
            db, owner_id, tool, definitions, dealer_visible, status,
            tag_names=group_tags, dealer_cache=dealer_cache,
            loss_report=loss_map.get(("tool", tool.id)),
            sale=sales_map.get(("tool", tool.id)),
        )

        members = None
        full_price = values["price_total"]
        full_replacement = values["replacement"]
        if is_set:
            members = members_by_set[tool.id]
            full_price = members["price_total"]
            full_replacement = members["replacement_total"]
            values["set"] = f"Set: {tool.name}"

        if filters.dealer_id is not None and tool.dealer_company_id != filters.dealer_id:
            continue
        extra = ""
        if is_set and needle and members is not None:
            extra = " ".join(
                [p.name + " " + p.part_number for p in members["core_pieces"]]
                + [p.name + " " + p.part_number for p in members["addon_pieces"]]
                + [t.name for t in members["attached_tools"]]
            )
        if needle and not _matches_text(values, needle, extra):
            continue
        if not _asset_passes(
            values,
            filters,
            price_total=full_price,
            warranty_key=inventory_service.tool_warranty_status(tool),
            is_set=is_set,
            checked_out=checked,
            tag_names=group_tags,
        ):
            continue

        if is_set and members is not None:
            if sets_mode in ("summary", "with_core"):
                # The bundle's whole worth rides on the set row until
                # "full" itemizes it onto the member rows.
                values["price_total"] = members["price_total"]
                values["replacement"] = members["replacement_total"]
                attached_msrp = sum(
                    (_total(t.msrp, t.quantity or 1) or Decimal("0"))
                    for t in members["attached_tools"]
                )
                if values["msrp"] is not None or attached_msrp:
                    values["msrp"] = _money((values["msrp"] or Decimal("0")) + attached_msrp)
            rows.append(
                _Row("asset", "tool", None, values, group_tags,
                     photo=_first_photo(tool))
            )
            _append_members(
                rows, db, owner_id, tool, members, sets_mode,
                definitions, dealer_visible, group_tags, checked,
                tag_map=tag_map, checkout_keys=checkout_keys,
                dealer_cache=dealer_cache, loss_map=loss_map,
                sales_map=sales_map,
            )
        else:
            rows.append(
                _Row("asset", "tool", None, values, group_tags,
                     photo=_first_photo(tool))
            )

    for battery in batteries:
        checked = ("battery", battery.id) in checkout_keys
        status = (
            "Checked out" if checked
            else "Sold" if getattr(battery, "standing", "") == "sold"
            else "Replaced" if getattr(battery, "standing", "") == "replaced"
            else "Active"
        )
        group_tags = tag_map.get(("battery", battery.id), [])
        values = _battery_values(
            db, owner_id, battery, definitions, dealer_visible, status,
            tag_names=group_tags, dealer_cache=dealer_cache,
            loss_report=loss_map.get(("battery", battery.id)),
            sale=sales_map.get(("battery", battery.id)),
        )
        if filters.dealer_id is not None and battery.dealer_company_id != filters.dealer_id:
            continue
        if needle and not _matches_text(values, needle):
            continue
        if not _asset_passes(
            values,
            filters,
            price_total=values["price_total"],
            warranty_key=inventory_service.warranty_status(battery),
            is_set=False,
            checked_out=checked,
            tag_names=group_tags,
        ):
            continue
        rows.append(
            _Row("asset", "battery", None, values, group_tags,
                 photo=_first_photo(battery))
        )

    return rows


def _append_members(
    rows: list[_Row],
    db: Session,
    owner_id: uuid.UUID,
    set_tool,
    members: dict,
    sets_mode: str,
    definitions: list,
    dealer_visible: bool,
    set_group_tags: list[str],
    set_checked_out: bool,
    *,
    tag_map: dict | None = None,
    checkout_keys: set | None = None,
    dealer_cache: dict | None = None,
    loss_map: dict | None = None,
    sales_map: dict | None = None,
) -> None:
    """Member rows under a set, per sets_mode. with_core adds the
    core pieces; full adds core + addon pieces + attached tools."""
    if sets_mode == "summary":
        return
    set_status = "Checked out" if set_checked_out else "In set"
    for piece in members["core_pieces"]:
        values = {
            "name": piece.name,
            "photo": None,  # pieces carry no attachments of their own
            "kind": "Set piece",
            "brand": "",
            "models": piece.part_number or "",
            "serials": piece.serial_number or "",
            "category": set_tool.category or "",
            "location": set_tool.location or "",
            "dealer": "",
            "tags": ", ".join(set_group_tags),
            "quantity": 1,
            # The piece's OWN price when one is recorded (owner
            # 2026-10-25): shown on the row, never totaled — the
            # row's in_set_price flag keeps _subtotal out of it.
            "price_each": _money(piece.price),
            "price_total": _money(piece.price),
            "msrp": None,
            "replacement": None,
            "purchase_date": piece.purchase_date,
            "warranty": None,
            "warranty_provider": "",
            "warranty_type": "",
            "police_report_number": "",
            "loss_reported_date": None,
            "rebuy_store": "",
            "rebuy_url": "",
            "rebuy_sku": "",
            "rebuy_notes": "",
            "repair_status": REPAIR_LABELS[piece.repair_state],
            "status": set_status,
            "set": f"Piece of: {set_tool.name}",
        }
        values.update(_sale_extras((sales_map or {}).get(("set_piece", piece.id))))
        rows.append(
            _Row("core_piece", "tool", set_tool.name, values, set_group_tags,
                 in_set_price=True)
        )
    if sets_mode != "full":
        return
    for piece in members["addon_pieces"]:
        values = {
            "name": piece.name,
            "photo": None,  # pieces carry no attachments of their own
            "kind": "Addon piece",
            "brand": "",
            "models": piece.part_number or "",
            "serials": piece.serial_number or "",
            "category": set_tool.category or "",
            "location": set_tool.location or "",
            "dealer": "",
            "tags": ", ".join(set_group_tags),
            "quantity": 1,
            "price_each": _money(piece.price),
            "price_total": _money(piece.price),
            "msrp": None,
            "replacement": None,
            "purchase_date": piece.purchase_date,
            "warranty": None,
            "warranty_provider": "",
            "warranty_type": "",
            "police_report_number": "",
            "loss_reported_date": None,
            "rebuy_store": "",
            "rebuy_url": "",
            "rebuy_sku": "",
            "rebuy_notes": "",
            "repair_status": REPAIR_LABELS[piece.repair_state],
            "status": set_status,
            "set": f"Piece of: {set_tool.name}",
        }
        values.update(_sale_extras((sales_map or {}).get(("set_piece", piece.id))))
        rows.append(
            _Row("addon_piece", "tool", set_tool.name, values, set_group_tags)
        )
    for tool in members["attached_tools"]:
        checked = set_checked_out or (
            ("tool", tool.id) in checkout_keys
            if checkout_keys is not None
            else _checked_out(db, "tool", tool.id)
        )
        attached_tags = (
            tag_map.get(("tool", tool.id), [])
            if tag_map is not None
            else _tag_names(db, owner_id, "tool", tool.id)
        )
        values = _tool_values(
            db, owner_id, tool, definitions, dealer_visible,
            "Checked out" if checked else "In set",
            tag_names=attached_tags, dealer_cache=dealer_cache,
            loss_report=(loss_map or {}).get(("tool", tool.id)),
            sale=(sales_map or {}).get(("tool", tool.id)),
        )
        values["kind"] = "Addon tool"
        values["set"] = f"Piece of: {set_tool.name}"
        rows.append(
            _Row(
                "attached_tool", "tool", set_tool.name, values,
                attached_tags,
                photo=_first_photo(tool),
            )
        )


# -- sorting / grouping ----------------------------------------------------------


def _sort_value(row: _Row, key: str):
    value = row.values.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower()
    return value


def _sort_rows(rows: list[_Row], sort: schemas.SortSpec, by_key: dict) -> list[_Row]:
    key = sort.key
    if key not in by_key:
        raise ReportError(f"Unknown sort column: {key}")
    present = [r for r in rows if _sort_value(r, key) is not None]
    missing = [r for r in rows if _sort_value(r, key) is None]
    present.sort(key=lambda r: _sort_value(r, key), reverse=sort.direction == "desc")
    # Empties always trail, whichever direction the sort runs.
    return present + missing


def _group_label(row: _Row, grouping: str) -> str:
    values = row.values
    if grouping == "category":
        return values["category"] or "(No category)"
    if grouping == "dealer":
        return values["dealer"] or "(No dealer)"
    if grouping == "location":
        return values["location"] or "(No location)"
    if grouping == "kind":
        # Member rows group with their set's kind family.
        return "Battery" if row.kind == "battery" else "Tool"
    if grouping == "purchase_year":
        purchased = values["purchase_date"]
        return str(purchased.year) if purchased else "(No purchase date)"
    return ""


def _subtotal(rows: list[_Row]) -> dict:
    # Core-piece rows (in_set_price) are display-only: a core
    # piece's own price never joins a total (owner 2026-10-25 — no
    # rollup), in any sets mode.
    counted = [r for r in rows if not r.in_set_price]
    price = sum(
        (r.values["price_total"] for r in counted if r.values["price_total"] is not None),
        Decimal("0"),
    )
    replacement = sum(
        (r.values["replacement"] for r in counted if r.values["replacement"] is not None),
        Decimal("0"),
    )
    return {
        # Items means top-level ASSETS, in every sets mode (deep
        # audit round 2, D-01): member rows (core pieces, addon
        # pieces, folded tools) are itemization of their set, not
        # more items — the same count summary.items carries and
        # the PDF closing row already printed. Before this, the
        # closing Total row counted member rows, so one report
        # said "3 items" at the top and "7 items" at the bottom
        # in full mode. Money is untouched by the count change.
        "count": sum(1 for r in rows if r.row_type == "asset"),
        "price_total": str(_money(price)),
        "replacement": str(_money(replacement)),
    }


# -- rendering rows to API shape ---------------------------------------------------


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def format_cell(column: dict, row: _Row, currency: str = "USD") -> str:
    """The display string for one cell — the screen, the PDF and
    the exports' text all read from here. Money cells render
    through the ONE formatter (wave 3) in the OWNER's currency."""
    value = row.values.get(column["key"])
    if (
        row.in_set_price
        and column["key"] in ("price_each", "price_total")
        and value is None
    ):
        # An UNPRICED core piece: there is no number — the price
        # lives on the set. A priced one falls through and shows
        # its own figure like any other row.
        return "in set"
    if value is None or value == "":
        return "—"
    if column["type"] == "money":
        return core_money.format_money(value, currency)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _row_payload(row: _Row, columns: list[dict], currency: str = "USD") -> dict:
    photo = None
    if row.photo is not None:
        # A FRESH presigned URL for the screen (they expire and are
        # never persisted); the exports fetch bytes by key instead.
        photo = {
            "key": row.photo["key"],
            "filename": row.photo["filename"],
            "content_type": row.photo["content_type"],
            "url": storage.presigned_get_url(row.photo["key"]),
        }
    return {
        "row_type": row.row_type,
        "kind": row.kind,
        "set_name": row.set_name,
        # The "#" of the app format when row numbers are on —
        # assigned by build_report in flattened display order;
        # None when the option is off.
        "number": None,
        "photo": photo,
        "values": {
            c["key"]: _json_value(row.values.get(c["key"])) for c in columns
        },
        "display": {c["key"]: format_cell(c, row, currency) for c in columns},
    }


def prepared_for_of(user) -> dict:
    """The PREPARED FOR block's facts, from the owner's profile
    (reports alignment): name + email always; phone + postal
    address only when the owner set them — an unset field is an
    EMPTY STRING here and every renderer treats empty as ABSENT
    (no blank lines on the document)."""
    return {
        "name": user.name or "",
        "email": user.email or "",
        "phone": user.phone or "",
        "address": user.postal_address or "",
    }


# -- the report -------------------------------------------------------------------


def build_report(
    db: Session,
    owner_id: uuid.UUID,
    spec: schemas.ReportSpec,
    dealer_visible: bool = True,
    prepared_for: dict | None = None,
) -> dict:
    """The full structured report (unpaginated). Exports and email
    render from this; the run endpoint paginates it.

    `prepared_for` (service.prepared_for_of) rides along so every
    surface heads the document with the same block."""
    if spec.sort.key in _RETIRED_COLUMN_KEYS:
        # A saved config sorted by a retired column falls back to
        # the default sort instead of failing (Package B tolerance).
        spec.sort = schemas.SortSpec()
    if spec.grouping not in colmod.GROUPINGS:
        raise ReportError(f"Unknown grouping: {spec.grouping}")
    if spec.sets_mode not in colmod.SETS_MODES:
        raise ReportError(f"Unknown sets mode: {spec.sets_mode}")
    columns, by_key = _resolve_columns(db, owner_id, spec.columns)
    definitions = custom_fields.list_definitions(db, owner_id, "all")

    rows = _collect_rows(db, owner_id, spec, definitions, dealer_visible)
    rows = _sort_rows(rows, spec.sort, by_key)

    groups: dict[str, list[_Row]] = {}
    order: list[str] = []
    if spec.grouping == "tag":
        for row in rows:
            labels = row.group_tags or ["(No tag)"]
            for label in labels:
                if label not in groups:
                    groups[label] = []
                    order.append(label)
                groups[label].append(row)
    else:
        for row in rows:
            label = _group_label(row, spec.grouping)
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append(row)

    if spec.grouping == "purchase_year":
        # Years newest first; the no-date group always last.
        years = sorted(
            (label for label in order if label != "(No purchase date)"),
            reverse=True,
        )
        order = years + (["(No purchase date)"] if "(No purchase date)" in groups else [])
    elif spec.grouping != "none":
        order.sort(key=str.lower)

    from app.modules.core import service as core_service

    _owner = core_service.get_user_by_id(db, owner_id)
    _currency = core_money.normalize_currency(
        _owner.currency if _owner is not None else "USD"
    )
    group_payloads = []
    for label in order:
        group_rows = groups[label]
        group_payloads.append(
            {
                "key": label,
                "label": label,
                "subtotal": _subtotal(group_rows),
                "row_count": len(group_rows),
                "rows": [_row_payload(r, columns, _currency) for r in group_rows],
            }
        )

    totals = _subtotal(rows)

    if spec.show_row_numbers:
        # The app's "#": sequential over the flattened display
        # order (groups in order, rows in order) — computed on the
        # FULL report, so a paginated screen and the exports agree.
        number = 0
        for group in group_payloads:
            for payload in group["rows"]:
                number += 1
                payload["number"] = number

    # The top summary block (reports alignment): computed over the
    # FULL filtered result set — the unique rows, never a page.
    # Items/units count ASSETS (a set is one item; its member rows
    # are itemization, not more items — the same doctrine that
    # keeps the modes' money in agreement). Units are
    # quantity-aware: an asset with quantity 3 is 3 units. Total
    # value is the grand price total, the report's value basis.
    asset_rows = [r for r in rows if r.row_type == "asset"]
    summary = {
        "items": len(asset_rows),
        "units": sum(int(r.values.get("quantity") or 1) for r in asset_rows),
        "price_total": totals["price_total"],
        "replacement": totals["replacement"],
    }

    return {
        "columns": columns,
        "groups": group_payloads,
        # Grand totals run over the UNIQUE rows: under tag grouping
        # a row appears once per tag it carries, and summing the
        # groups would count its money once per tag too.
        "totals": totals,
        "summary": summary,
        "prepared_for": prepared_for,
        "options": {
            "show_row_numbers": spec.show_row_numbers,
            "show_summary": spec.show_summary,
            "orientation": spec.orientation,
        },
        "total_rows": len(rows),
        "grouping": spec.grouping,
        "sets_mode": spec.sets_mode,
    }


def run_report(
    db: Session,
    owner_id: uuid.UUID,
    request: schemas.RunRequest,
    dealer_visible: bool = True,
    prepared_for: dict | None = None,
) -> dict:
    """build_report + pagination over the flattened display order.
    Group subtotals in the page payload are the FULL group's — the
    page shows a slice of rows under the group's true totals."""
    report = build_report(
        db, owner_id, request, dealer_visible=dealer_visible,
        prepared_for=prepared_for,
    )
    total = report["total_rows"]
    pages = max(1, (total + request.page_size - 1) // request.page_size)
    page = min(request.page, pages)
    start = (page - 1) * request.page_size
    end = start + request.page_size

    paged_groups = []
    cursor = 0
    for group in report["groups"]:
        group_rows = group["rows"]
        slice_rows = group_rows[
            max(0, start - cursor) : max(0, end - cursor)
        ]
        cursor += len(group_rows)
        if slice_rows:
            paged_groups.append({**group, "rows": slice_rows})
    report["groups"] = paged_groups
    report["page"] = page
    report["page_size"] = request.page_size
    report["pages"] = pages
    return report


# -- saved configurations ----------------------------------------------------------


def _options_of(spec: schemas.ReportSpec) -> dict:
    """The spec's display options as stored (migration 0032's
    options bag on the config row)."""
    return {
        "show_row_numbers": spec.show_row_numbers,
        "show_summary": spec.show_summary,
        "orientation": spec.orientation,
    }


def _spec_of(config: models.ReportConfig) -> schemas.ReportSpec:
    # Options read with the LEGACY defaults: a config stored before
    # the options bag existed (or with keys missing) behaves as it
    # did — no row numbers, summary on, landscape.
    options = config.options or {}
    return schemas.ReportSpec(
        columns=list(config.columns or []) or None,
        filters=schemas.ReportFilters(**(config.filters or {})),
        grouping=config.grouping or "none",
        sets_mode=config.sets_mode or "summary",
        sort=schemas.SortSpec(**(config.sort or {"key": "name", "direction": "asc"})),
        show_row_numbers=bool(options.get("show_row_numbers", False)),
        show_summary=bool(options.get("show_summary", True)),
        orientation=options.get("orientation", "landscape"),
    )


def serialize_config(config: models.ReportConfig) -> dict:
    return {
        "id": str(config.id),
        "name": config.name,
        "spec": _spec_of(config).model_dump(mode="json"),
        "builtin": False,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def list_configs(db: Session, owner_id: uuid.UUID) -> list[models.ReportConfig]:
    return list(
        db.scalars(
            select(models.ReportConfig)
            .where(models.ReportConfig.owner_id == owner_id)
            .order_by(models.ReportConfig.name)
        )
    )


def get_config(
    db: Session, owner_id: uuid.UUID, config_id: uuid.UUID
) -> models.ReportConfig | None:
    config = db.get(models.ReportConfig, config_id)
    if config is None or config.owner_id != owner_id:
        return None
    return config


def _validate_spec(db: Session, owner_id: uuid.UUID, spec: schemas.ReportSpec) -> None:
    """Reject a spec the builder couldn't run (unknown columns /
    grouping / sort) at SAVE time, not at run time."""
    _resolve_columns(db, owner_id, spec.columns)
    if spec.grouping not in colmod.GROUPINGS:
        raise ReportError(f"Unknown grouping: {spec.grouping}")
    if spec.sets_mode not in colmod.SETS_MODES:
        raise ReportError(f"Unknown sets mode: {spec.sets_mode}")
    _, by_key = _resolve_columns(db, owner_id, None)
    if spec.sort.key not in by_key and spec.sort.key not in _RETIRED_COLUMN_KEYS:
        raise ReportError(f"Unknown sort column: {spec.sort.key}")


def create_config(
    db: Session, owner_id: uuid.UUID, payload: schemas.ConfigWrite
) -> models.ReportConfig:
    _validate_spec(db, owner_id, payload.spec)
    config = models.ReportConfig(
        owner_id=owner_id,
        name=payload.name.strip(),
        columns=list(payload.spec.columns or []),
        filters=payload.spec.filters.model_dump(mode="json"),
        grouping=payload.spec.grouping,
        sets_mode=payload.spec.sets_mode,
        sort=payload.spec.sort.model_dump(mode="json"),
        options=_options_of(payload.spec),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_config(
    db: Session,
    owner_id: uuid.UUID,
    config_id: uuid.UUID,
    payload: schemas.ConfigWrite,
) -> models.ReportConfig | None:
    config = get_config(db, owner_id, config_id)
    if config is None:
        return None
    _validate_spec(db, owner_id, payload.spec)
    config.name = payload.name.strip()
    config.columns = list(payload.spec.columns or [])
    config.filters = payload.spec.filters.model_dump(mode="json")
    config.grouping = payload.spec.grouping
    config.sets_mode = payload.spec.sets_mode
    config.sort = payload.spec.sort.model_dump(mode="json")
    config.options = _options_of(payload.spec)
    db.commit()
    db.refresh(config)
    return config


def delete_config(db: Session, owner_id: uuid.UUID, config_id: uuid.UUID) -> bool:
    config = get_config(db, owner_id, config_id)
    if config is None:
        return False
    db.delete(config)
    db.commit()
    return True


# -- built-in presets ---------------------------------------------------------------

PRESETS: list[dict] = [
    {
        "id": "preset-valuation",
        "name": "Full inventory valuation",
        "builtin": True,
        "spec": {
            "columns": [
                "name", "kind", "brand", "category", "dealer", "location",
                "quantity", "price_each", "price_total", "msrp", "replacement",
            ],
            "filters": {},
            "grouping": "category",
            # Itemized: addon pieces and attached tools carry their
            # own rows so the valuation counts every dollar once.
            "sets_mode": "full",
            "sort": {"key": "name", "direction": "asc"},
        },
    },
    {
        "id": "preset-tax",
        "name": "Tax — purchases by year",
        "builtin": True,
        "spec": {
            "columns": [
                "name", "kind", "brand", "purchase_date",
                "quantity", "price_each", "price_total",
            ],
            "filters": {},
            "grouping": "purchase_year",
            # Full: addon pieces land in the year THEY were bought,
            # with their own prices — the tax view of a set is its
            # purchase events, not one bundle row.
            "sets_mode": "full",
            "sort": {"key": "purchase_date", "direction": "asc"},
        },
    },
    {
        "id": "preset-app-style",
        "name": "Inventory Report (app style)",
        "builtin": True,
        "spec": {
            # Ryan's app format, column for column: # / Photo /
            # Name / Qty / Brand / Model # / extended COST (the
            # price TOTAL — qty × price each). Portrait, with the
            # top summary + Prepared-For header and the closing
            # totals row the app prints.
            "columns": [
                "photo", "name", "quantity", "brand", "models", "price_total",
            ],
            "filters": {},
            "grouping": "none",
            # The app renders a set as one row with its pieces
            # listed beneath: with_core is that shape (core pieces
            # ride under the set; the set row carries the value).
            "sets_mode": "with_core",
            "sort": {"key": "name", "direction": "asc"},
            "show_row_numbers": True,
            "show_summary": True,
            "orientation": "portrait",
        },
    },
]


def list_presets() -> list[dict]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "builtin": True,
            "spec": schemas.ReportSpec(**p["spec"]).model_dump(mode="json"),
            "created_at": None,
            "updated_at": None,
        }
        for p in PRESETS
    ]
