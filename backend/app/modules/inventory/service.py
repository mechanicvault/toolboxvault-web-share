"""Inventory module service: the public interface other modules use.

SERVICE INTERFACE (stable; bump manifest version on change):
  - create_tool(db, owner_id, payload) -> Tool
  - get_tool(db, owner_id, tool_id) -> Tool | None   (ownership-checked)
  - list_tools(db, owner_id) -> list[Tool]
  - update_tool(db, owner_id, tool_id, payload) -> Tool | None
  - delete_tool(db, owner_id, tool_id) -> bool
  - get_tool_summary(db, tool_id) -> dict | None   (for borrowing/claims/reports)
  - get_inventory_stats(db, owner_id) -> dict    (owner vault totals; see schemas.InventoryStats)
  - serialize_tool(tool) -> dict                  (public shape, fresh file URLs)
  - list_tool_identities(db, owner_id) -> list[dict]  (id + identity fields
    only; for pickers in other modules — core's sharing settings)
  - get_owned_tools(db, owner_id, tool_ids) -> list[Tool]  (the subset of
    tool_ids the owner actually owns; callers compare lengths to detect
    foreign ids without a second query)
  - peer_tool_view(tool) -> dict                  (the FIXED peer-sharing
    payload for one tool — identity + photo URLs only; core's peer
    sharing serializes from this and adds owner attribution, so the
    minimal shape is enforced here, at the data's owner)
  - search_peer_tools(db, owner_ids, query) -> list[Tool]  (deliberate
    cross-owner search for the peer surface: matches name/brand/model/
    category ONLY — the fields the peer payload carries — so a term
    that lives only in notes/serial/custom data can never surface a
    tool to a peer viewer)

BATTERIES (owner spec 2026-10-18): first-class asset records with
their own serials/photos/custom fields and a computed warranty
status; the optional "currently in" link to a tool lives on the
battery. The battery half of the interface mirrors the tool half:
  - create_battery / get_battery / list_batteries(db, owner_id,
    in_tool_id=None) / update_battery / delete_battery
  - serialize_battery(db, battery, active=True) -> dict (tool shape
    + battery fields + warranty_status/warranty_end_date + the
    linked tool's id AND name, resolved here)
  - warranty_status(battery, today=None) -> str  (computed, never
    stored: in_warranty | expiring_soon | expired | unknown)
  - warranty_status_for(purchase_date, warranty_months, today=None)
    + warranty_end_date_for(...) — THE shared computation both kinds
    read (maintenance build, 2026-10-19); tool_warranty_status(tool)
    is the tool-side wrapper. Battery wrappers keep battery behavior
    byte-identical.
  - get_owned_batteries(db, owner_id, battery_ids) -> list[Battery]
  - list_battery_identities / list_item_identities (tools +
    batteries, each row marked "kind") — pickers in other modules
  - peer_battery_view(battery) / search_peer_batteries(...) — the
    peer whitelist for batteries (same fields as tools, category
    reads "Battery", plus kind="battery")

Custom-field validation lives in custom_fields.py; uploads in attachments.py;
search in search.py. This module orchestrates them for tool records.

ITEM STRUCTURE PACKAGE (2026-10-18) additions:
  - Quantity (money is PER UNIT; totals multiply), size, multi-value
    model/serial lists (the single columns stay as the synced
    PRIMARY), consumable flag, tags (list_tags / create_tag /
    rename_tag / delete_tag / set_item_tags), location vocabulary
    (list_locations).
  - SETS: a set is a tool record (is_set) + set_pieces rows.
    resolve_set_members(db, set_tool, include_addons) is THE shared
    member-resolution service — tier sharing, peer sharing,
    borrowing and (later) claims all consume set structure through
    it, and user-facing set actions ask "include the addon pieces
    too?" and pass the answer in. Attach/detach of standalone tools
    as addons: attach_tool_to_set / detach_tool.
  - Dealer tags: dealer_company_id on tools and batteries (a bare
    reference into the dealers module's table, resolved lazily —
    inventory never depends on the dealers module; routes pass
    dealer_visible=False when the module is off for the user and the
    tag then hides while the stored value is preserved).
"""

import calendar
import uuid
from types import SimpleNamespace
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.core.storage import storage
from app.modules.core import journal
from app.modules.inventory import attachments, custom_fields, models, schemas, thumbs


class ToolValidationError(ValueError):
    """A tool/set/tag payload breaks a rule (bad quantity, a dealer
    tag the caller can't use, a core piece with a price, ...).
    Routes turn this into a 422."""


class ToolNotFoundError(ValueError):
    """The named tool/set does not exist OR is not the caller's —
    deliberately indistinguishable (deep audit round 2, E-02).
    Routes turn this into the house 404, the same shape every
    sibling owner-scoped read gives a foreign id, so a cross-owner
    probe learns nothing about what exists in someone else's
    vault."""


class StarLimitReached(ToolValidationError):
    """Starring one more category would break the per-owner cap
    (owner spec 2026-10-24; cap cut to 5 on 2026-10-25). Routes turn
    this into a 409 with the machine-readable code
    `star_limit_reached`; the UI answers with the limit tooltip,
    never a silent failure."""


class PreinstalledCategoryError(ToolValidationError):
    """A manager operation tried to destroy or rename a
    preinstalled starter category (owner spec 2026-10-25):
    starters can't be deleted or merged away, and Batteries
    can't be renamed. Routes turn this into a 409 with the
    machine-readable code `category_preinstalled`."""


# -- delete guards (the claims seam) -------------------------------------------
#
# A delete guard answers one question about a destructive operation:
# may this item go away right now? It returns the refusal copy (a
# friendly sentence) or None to allow. Modules that hold references
# to items register guards at import — claims (2026-10-19) is the
# first: an item on an OPEN claim can't be deleted, and a set on an
# open claim can't be taken apart (piece delete / addon detach).
#
# The registry is the whole connection: inventory never imports the
# guarding module, so removing that module removes the guard with
# it, and items without guards delete exactly as before. Guards run
# inside the service (not just the routes) so EVERY delete path is
# covered — except the account-deletion cascade, which deletes the
# guarding module's own rows first and so passes cleanly.
#
# kind vocabulary: "tool" (delete_tool — a set is a tool record),
# "battery", "piece" (delete_set_piece), "detach" (detach_tool).

DeleteGuard = Callable[[Session, uuid.UUID, str, uuid.UUID], "str | None"]

_delete_guards: list[DeleteGuard] = []


def register_delete_guard(guard: DeleteGuard) -> None:
    """Register a delete guard. Idempotent by identity."""
    if guard not in _delete_guards:
        _delete_guards.append(guard)


def _run_delete_guards(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> None:
    for guard in _delete_guards:
        message = guard(db, owner_id, kind, item_id)
        if message:
            raise ToolValidationError(message)


def _normalize_number_list(values) -> list[str]:
    """Multi-value model/serial lists: trimmed, blanks dropped,
    duplicates removed (first occurrence wins)."""
    seen: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _sync_number_fields(data: dict) -> dict:
    """Keep the primary model/serial columns in lockstep with the
    multi-value lists (create + update). When the list is supplied
    it wins and the primary becomes its first entry; when only the
    primary is supplied the list becomes [primary]. Neither supplied
    (partial update) leaves both alone."""
    for list_key, primary_key in (
        ("model_numbers", "model"),
        ("serial_numbers", "serial_number"),
    ):
        if data.get(list_key) is not None:
            values = _normalize_number_list(data[list_key])
            data[list_key] = values
            data[primary_key] = values[0] if values else ""
        elif data.get(primary_key) is not None:
            primary = str(data[primary_key]).strip()
            data[list_key] = [primary] if primary else []
    return data


def validate_dealer_company(
    db: Session, owner_id: uuid.UUID, company_id: uuid.UUID | None
) -> None:
    """A dealer tag may only name a company the caller can see: a
    directory company or their OWN private company. The dealers
    models are imported lazily — inventory must not depend on the
    dealers module (the tag is a bare reference; the module can be
    switched off without touching this validation)."""
    if company_id is None:
        return
    from app.modules.dealers import models as dealer_models

    company = db.get(dealer_models.DealerCompany, company_id)
    if company is None or not (
        company.is_directory or company.owner_id == owner_id
    ):
        raise ToolValidationError("That dealer company isn't available to you.")


def dealer_company_name(
    db: Session, company_id: uuid.UUID | None, perspective_id: uuid.UUID | None = None
) -> str | None:
    """Display name for a dealer tag, resolved lazily (see
    validate_dealer_company). None when the company is gone.

    `perspective_id` is whose eyes the name is for (personal
    dealer edits, 2026-11-05): the item serializers pass the
    item OWNER's id — an item presents its dealer the way its
    owner named it for himself — and the dealers service
    resolves his personal layer when he has one. Viewer-scoped
    dealer surfaces resolve through their own reads instead."""
    if company_id is None:
        return None
    from app.modules.dealers import models as dealer_models

    company = db.get(dealer_models.DealerCompany, company_id)
    if company is None:
        return None
    if perspective_id is not None and company.is_directory:
        from app.modules.dealers import service as dealer_service

        return dealer_service.personal_company_name(db, perspective_id, company)
    return company.name


# -- acquisition ledger (year-end fix, 2026-10-24) ------------------------
#
# The write side of models.AcquisitionRecord: what was acquired,
# recorded when it happens, so reports never have to reconstruct
# purchase history from a quantity that sales have since shrunk.
# Writers: item creation (when a purchase price is recorded) and
# quantity INCREASES via edit. Sales, reversals, decreases and
# deletion write NOTHING here — see the model's docstring.


def _record_acquisition(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    item,
    quantity: int,
) -> None:
    db.add(
        models.AcquisitionRecord(
            owner_id=owner_id,
            item_kind=kind,
            item_id=item.id,
            item_name=item.name,
            brand=item.brand or "",
            business_use=bool(item.business_use),
            acquired_on=item.purchase_date,
            quantity_acquired=quantity,
            unit_price=item.purchase_price,
        )
    )


def _item_has_acquisitions(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> bool:
    return (
        db.scalar(
            select(models.AcquisitionRecord.id)
            .where(
                models.AcquisitionRecord.owner_id == owner_id,
                models.AcquisitionRecord.item_kind == kind,
                models.AcquisitionRecord.item_id == item_id,
            )
            .limit(1)
        )
        is not None
    )


def _record_quantity_increase(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    item,
    old_quantity: int,
) -> None:
    """A quantity increase via edit is a new acquisition of the
    added units. When the item has no ledger rows yet (created
    price-less, or predating the ledger), this first row covers
    EVERYTHING on hand — history starts whole rather than with
    just the delta floating ownerless."""
    new_quantity = item.quantity or 1
    if new_quantity <= old_quantity or item.purchase_price is None:
        return
    if _item_has_acquisitions(db, owner_id, kind, item.id):
        quantity = new_quantity - old_quantity
    else:
        quantity = new_quantity
    _record_acquisition(db, owner_id, kind, item, quantity)


def list_acquisitions(
    db: Session, owner_id: uuid.UUID
) -> list[models.AcquisitionRecord]:
    """Every acquisition-ledger row the owner has — the year-end
    and tax reports' source for what was actually acquired."""
    return list(
        db.scalars(
            select(models.AcquisitionRecord)
            .where(models.AcquisitionRecord.owner_id == owner_id)
            .order_by(models.AcquisitionRecord.created_at.asc())
        )
    )


def _validate_truck_charge(
    db: Session, owner_id: uuid.UUID, data: dict, truck_charge: dict | None
) -> None:
    """The wizard's truck charge, validated UP FRONT (before the
    item exists) so a bad charge saves nothing: it needs the
    item's dealer company, a purchase price, a portion inside
    (0, price], and the truck accounts module actually usable by
    this owner. The account resolution itself (which account, or
    opening one) is the truck service's, at apply time."""
    if not truck_charge:
        return
    if not data.get("dealer_company_id"):
        raise ToolValidationError(
            "A truck account charge needs the item's dealer — "
            "pick the dealer you bought it from."
        )
    price = data.get("purchase_price")
    if price is None:
        raise ToolValidationError(
            "A truck account charge needs the purchase price first."
        )
    amount = Decimal(str(truck_charge.get("amount") or "0"))
    if amount <= 0:
        raise ToolValidationError(
            "The truck account amount must be more than zero."
        )
    if amount > Decimal(str(price)):
        raise ToolValidationError(
            "The truck account amount can't be more than the "
            "purchase price."
        )
    from app.modules.core import models as core_models
    from app.modules.core import module_control

    owner = db.get(core_models.User, owner_id)
    if owner is None or not module_control.effective_for_user(
        db,
        "truck_accounts",
        owner.account_types,
        user_id=owner.id,
        tier=owner.tier,
        beta_tester=owner.beta_tester,
    ):
        raise ToolValidationError(
            "Truck accounts aren't available on your account."
        )


def _apply_truck_charge(
    db: Session,
    owner_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    item_name: str,
    kind_label: str,
    company_id: uuid.UUID,
    truck_charge: dict,
) -> None:
    """Post the wizard's charge inside the create transaction
    (the truck service flushes; THIS create's commit lands item
    + charge together). A truck refusal rolls the whole create
    back — neither the item nor a half-opened tab survives."""
    from app.modules.core import models as core_models
    from app.modules.truck_accounts import service as truck_service

    owner = db.get(core_models.User, owner_id)
    try:
        truck_service.charge_at_item_entry(
            db,
            owner,
            company_id=company_id,
            amount=Decimal(str(truck_charge.get("amount"))),
            note=f"{kind_label} entered: {item_name}",
            item_link_id=item_id,
            account_id=truck_charge.get("account_id"),
            agent_user_id=truck_charge.get("agent_user_id"),
            private_agent_id=truck_charge.get("private_agent_id"),
        )
    except truck_service.TruckError as exc:
        db.rollback()
        raise ToolValidationError(str(exc)) from exc


def create_tool(
    db: Session, owner_id: uuid.UUID, payload: schemas.ToolCreate
) -> models.Tool:
    data = payload.model_dump()
    data["custom_data"] = custom_fields.validate_custom_data(
        db, owner_id, payload.custom_data
    )
    data["attachments"] = []  # files attach only via the upload flow
    tag_ids = data.pop("tag_ids", []) or []
    # Inline set pieces ride the create (Package B): validated up
    # front so a bad piece row saves NOTHING (one form, one save,
    # all-or-nothing). The initial maintenance schedule is the
    # routes' concern — it belongs to the maintenance module.
    pieces = data.pop("pieces", None)
    attach_tool_ids = data.pop("attach_tool_ids", None)
    data.pop("initial_schedule", None)
    # The wizard's truck charge rides the create (2026-10-31):
    # validated before anything is built, posted after the flush
    # inside this same transaction.
    truck_charge = data.pop("truck_charge", None)
    _validate_truck_charge(db, owner_id, data, truck_charge)
    if pieces:
        if not data.get("is_set"):
            raise ToolValidationError(
                "Pieces belong to a set — mark the item as a set to add pieces."
            )
        _validate_piece_rows(pieces)
    if attach_tool_ids:
        if not data.get("is_set"):
            raise ToolValidationError(
                "Tools from your inventory belong to a set — mark the "
                "item as a set to add them."
            )
        _validate_attach_ids(db, owner_id, None, attach_tool_ids)
    data = _sync_number_fields(data)
    _apply_location_write(db, owner_id, data)
    validate_dealer_company(db, owner_id, data.get("dealer_company_id"))
    tool = models.Tool(owner_id=owner_id, **data)
    db.add(tool)
    db.flush()
    if tool.purchase_price is not None:
        _record_acquisition(db, owner_id, "tool", tool, tool.quantity or 1)
    if pieces:
        _sync_set_pieces(db, owner_id, tool, pieces)
    if attach_tool_ids:
        _apply_attach_sync(db, owner_id, tool, attach_tool_ids)
    if tag_ids:
        set_item_tags(db, owner_id, "tool", tool.id, tag_ids)
    if truck_charge:
        _apply_truck_charge(
            db,
            owner_id,
            item_id=tool.id,
            item_name=tool.name,
            kind_label="Tool",
            company_id=data.get("dealer_company_id"),
            truck_charge=truck_charge,
        )
    db.commit()
    db.refresh(tool)
    return tool


def get_tool(
    db: Session, owner_id: uuid.UUID, tool_id: uuid.UUID
) -> models.Tool | None:
    tool = db.get(models.Tool, tool_id)
    if tool is None or tool.owner_id != owner_id:
        return None
    return tool


def list_tools(
    db: Session, owner_id: uuid.UUID, include_attached: bool = False
) -> list[models.Tool]:
    """The owner's tools, newest first. Attached addon tools are
    EXCLUDED by default — they live inside their set, never as
    top-level rows. Callers that need the complete record (data
    export, account deletion) pass include_attached=True."""
    stmt = (
        select(models.Tool)
        .where(models.Tool.owner_id == owner_id)
        .order_by(models.Tool.created_at.desc())
    )
    if not include_attached:
        stmt = stmt.where(models.Tool.attached_to_set_id.is_(None))
    return list(db.scalars(stmt))


def list_tool_identities(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Identity-only view of the owner's tools for cross-module pickers
    (core's sharing settings lists tools to share). Deliberately does
    NOT serialize attachments — no presigned URLs are minted for a
    list the owner just picks from. Attached addon tools are excluded
    (they live inside their set); rows carry `is_set` so pickers can
    mark sets."""
    rows = db.execute(
        select(
            models.Tool.id,
            models.Tool.name,
            models.Tool.brand,
            models.Tool.model,
            models.Tool.serial_number,
            models.Tool.is_set,
        )
        .where(
            models.Tool.owner_id == owner_id,
            models.Tool.attached_to_set_id.is_(None),
        )
        .order_by(models.Tool.created_at.desc())
    )
    return [dict(row._mapping) for row in rows]


def get_owned_tools(
    db: Session, owner_id: uuid.UUID, tool_ids: list[uuid.UUID]
) -> list[models.Tool]:
    """The subset of `tool_ids` owned by `owner_id`. Consent-sharing
    uses this to validate a whole submitted item set in one query:
    fewer rows back than ids sent means a foreign id was included."""
    if not tool_ids:
        return []
    return list(
        db.scalars(
            select(models.Tool).where(
                models.Tool.owner_id == owner_id,
                models.Tool.id.in_(tool_ids),
            )
        )
    )


def update_tool(
    db: Session,
    owner_id: uuid.UUID,
    tool_id: uuid.UUID,
    payload: schemas.ToolUpdate,
) -> models.Tool | None:
    tool = get_tool(db, owner_id, tool_id)
    if tool is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "custom_data" in data:
        data["custom_data"] = custom_fields.validate_custom_data(
            db, owner_id, data["custom_data"]
        )
    data.pop("attachments", None)  # files attach only via the upload flow
    data.pop("initial_schedule", None)  # the routes own schedules
    tag_ids = data.pop("tag_ids", None)
    pieces = data.pop("pieces", None)
    attach_tool_ids = data.pop("attach_tool_ids", None)
    data = _sync_number_fields(data)
    if "dealer_company_id" in data:
        validate_dealer_company(db, owner_id, data["dealer_company_id"])
    # The set/pieces rules judge the RESULTING record: unmarking a
    # set while pieces remain is refused (empty the pieces in the
    # same save to unmark), and pieces require the set flag.
    resulting_is_set = data.get("is_set", tool.is_set)
    if pieces is not None:
        if pieces and not resulting_is_set:
            raise ToolValidationError(
                "Pieces belong to a set — mark the item as a set to add pieces."
            )
        _validate_piece_rows(pieces)
    elif not resulting_is_set and tool.is_set:
        if _list_set_pieces(db, tool.id):
            raise ToolValidationError(
                "This set still has pieces — remove the pieces in the "
                "same save to unmark it as a set."
            )
    # Build-a-set attachments judge the RESULTING record too: a
    # non-set can't hold attached tools (submit an empty list in
    # the same save to detach them all while unmarking); ids are
    # validated before anything mutates.
    if attach_tool_ids is not None:
        if attach_tool_ids and not resulting_is_set:
            raise ToolValidationError(
                "Tools from your inventory belong to a set — keep the "
                "item marked as a set, or remove them in the same save."
            )
        _validate_attach_ids(db, owner_id, tool.id, attach_tool_ids)
    _apply_location_write(db, owner_id, data)
    old_quantity = tool.quantity or 1
    for key, value in data.items():
        setattr(tool, key, value)
    db.flush()
    _record_quantity_increase(db, owner_id, "tool", tool, old_quantity)
    if pieces is not None:
        _sync_set_pieces(db, owner_id, tool, pieces)
    if attach_tool_ids is not None:
        _apply_attach_sync(db, owner_id, tool, attach_tool_ids)
    if tag_ids is not None:
        set_item_tags(db, owner_id, "tool", tool.id, tag_ids)
    db.commit()
    db.refresh(tool)
    return tool


def delete_tool(db: Session, owner_id: uuid.UUID, tool_id: uuid.UUID) -> bool:
    tool = get_tool(db, owner_id, tool_id)
    if tool is None:
        return False
    _run_delete_guards(db, owner_id, "tool", tool_id)
    # A set's pieces die with it: their stored files first
    # (best-effort), then the rows (the FK CASCADE is the backstop).
    pieces = list(
        db.scalars(
            select(models.SetPiece).where(models.SetPiece.set_id == tool_id)
        )
    )
    for piece in pieces:
        # Audit trail (2026-10-19): a deleted piece's files are
        # TOMBSTONED, not destroyed — a restore inside the
        # retention window brings the piece back with its photos.
        # The tombstone rows ride this same transaction.
        journal.retire_record_files(
            db, owner_id, piece, entity_type="set_piece"
        )
        db.delete(piece)
    # Attached addon tools SURVIVE the set: they detach back to
    # standalone (with their own prices), exactly like a manual
    # detach. ORM writes, not a bulk UPDATE, so each detach lands
    # in the owner's change journal and a restore re-attaches.
    for addon in db.scalars(
        select(models.Tool).where(models.Tool.attached_to_set_id == tool_id)
    ):
        addon.attached_to_set_id = None
    # Tag links for this tool go too — ORM deletes, journaled like
    # every other change (the FK CASCADE remains the backstop).
    for link in db.scalars(
        select(models.ItemTag).where(models.ItemTag.tool_id == tool_id)
    ):
        db.delete(link)
    # Lost/stolen reports (gap wave 1): the paper trail dies with
    # its item — ORM deletes, journaled like the links above.
    for report in db.scalars(
        select(models.ItemLossReport).where(
            models.ItemLossReport.item_kind == "tool",
            models.ItemLossReport.item_id == tool_id,
        )
    ):
        db.delete(report)
    journal.retire_record_files(db, owner_id, tool, entity_type="tool")
    # Batteries outlive their tools: clear the "currently in" link
    # explicitly (the FK's ON DELETE SET NULL is the Postgres-side
    # backstop; doing it here keeps the behavior identical on every
    # backend and in every test). ORM writes, journaled.
    for battery in db.scalars(
        select(models.Battery).where(
            models.Battery.currently_in_tool_id == tool_id
        )
    ):
        battery.currently_in_tool_id = None
    # Tools For Sale (owner spec 2026-10-25): deleting the item
    # ENDS its active listings in this same transaction — a
    # listing must never outlive its item on the board. Lazy
    # import (marketplace's snapshot path imports this module
    # the same way). The cascade touches listings only — sale
    # records, claims and the ledger are untouched.
    from app.modules.marketplace import service as marketplace_service

    marketplace_service.end_listings_for_source(db, owner_id, "tool", tool_id)
    db.delete(tool)
    db.commit()
    return True


def _serialize_attachments(record) -> list[dict]:
    """Stored attachments keep only keys (+ metadata); read URLs are
    minted at serialize time because presigned URLs expire and must
    never be persisted. Shared by tools and batteries — the stored
    shape is identical."""
    view_attachments = []
    for item in record.attachments or []:
        if not isinstance(item, dict) or "key" not in item:
            continue
        view_attachments.append(
            {
                "key": item["key"],
                "filename": item.get("filename", ""),
                "kind": item.get("kind", ""),
                "content_type": item.get("content_type", ""),
                "size_bytes": item.get("size_bytes", 0),
                "uploaded_at": item.get("uploaded_at"),
                # Provenance (wave 4): files the system fetched
                # itself (a located user manual) carry where they
                # came from + when; user uploads leave these null.
                "origin": item.get("origin"),
                # Police-report tie (2026-10-25): the lost/stolen
                # report this file belongs to, when it was uploaded
                # as that report's document.
                "loss_report_id": item.get("loss_report_id"),
                "source_url": item.get("source_url"),
                "source_name": item.get("source_name"),
                "fetched_at": item.get("fetched_at"),
                "url": storage.presigned_get_url(item["key"]),
                # Renditions (F3-12): photos get signed thumb URLs
                # for tile (320) and list (128) slots; documents and
                # receipts keep the original URL only.
                "thumb_url": (
                    thumbs.signed_thumb_url(item["key"], 320)
                    if item.get("kind") == "photo"
                    and str(item.get("content_type", "")).startswith("image/")
                    else None
                ),
                "thumb_url_sm": (
                    thumbs.signed_thumb_url(item["key"], 128)
                    if item.get("kind") == "photo"
                    and str(item.get("content_type", "")).startswith("image/")
                    else None
                ),
            }
        )
    return view_attachments


# Public alias: the maintenance module serializes its log entries'
# documents through this same minter (Package B — certificates ride
# the item attachment machinery).
serialize_attachments = _serialize_attachments


def primary_photo_thumb(record) -> dict | None:
    """The record's primary photo as signed rendition URLs (tile
    320 / row 128, F3-12), or None when the record has no photo.
    Shared by the surfaces that show an item thumbnail without the
    full attachment list (global search's inventory group, the
    dealer page's records tab). Display data only — a None here is
    what tells the client to paint the no-photo placeholder; the
    record itself stays photo-less."""
    for att in record.attachments or []:
        if (
            isinstance(att, dict)
            and att.get("kind") == "photo"
            and str(att.get("content_type", "")).startswith("image/")
            and att.get("key")
        ):
            return {
                "thumb_url": thumbs.signed_thumb_url(att["key"], 320),
                "thumb_url_sm": thumbs.signed_thumb_url(att["key"], 128),
            }
    return None


def business_sub_limit_applies(db: Session, owner_id: uuid.UUID) -> bool:
    """A9 guidance predicate: the owner's own insurance profile
    declares a business-use sub-limit AND the policy is not a
    dedicated tool policy. Reads the owner's OWN entered data —
    guidance only, never a computation about coverage."""
    from app.modules.core import insurance as core_insurance

    profile = core_insurance.get_profile(db, owner_id)
    return bool(
        profile is not None
        and profile.business_sub_limit_cents is not None
        and profile.policy_type != "dedicated_tool"
    )


def serialize_tool(
    db: Session,
    tool: models.Tool,
    active: bool = True,
    dealer_visible: bool = True,
    ctx: dict | None = None,
) -> dict:
    """Public shape of a tool with FRESH presigned URLs for attachments.

    `active` is the caller's entitlement annotation (billing owns the
    rule; routes compute it and pass it in) — False renders the tool
    greyed in the owner's list.

    `dealer_visible` is the dealers-module switch for THIS caller:
    when the module is off/unassigned, the dealer tag hides — the
    payload carries no company id or name — while the stored value
    stays untouched in the database (module removability).

    `ctx` (scale fix, 2026-10-26) is serialize_context's batch
    prefetch for a page of rows: when given, the per-row lookups
    (tags, dealer name, set structure, parent/replacement names,
    the sub-limit flag) read its maps instead of querying per
    row. The payload is identical either way (pinned by test).

    A set's payload carries its full structure (pieces, attached
    addon tools, totals) via the `set` block plus a `set_summary`
    for list badges. Search may mark the row with matched_via /
    matched_label (set on the instance by search.py).
    """
    view_attachments = _serialize_attachments(tool)
    dealer_id = tool.dealer_company_id if dealer_visible else None
    view: dict = {
        "id": tool.id,
        "owner_id": tool.owner_id,
        "name": tool.name,
        "brand": tool.brand,
        "model": tool.model,
        "serial_number": tool.serial_number,
        "category": tool.category,
        "location": tool.location,
        "location_id": tool.location_id,
        "standing": tool.standing,
        "notes": tool.notes,
        "purchase_price": tool.purchase_price,
        "purchase_date": tool.purchase_date,
        "replacement_cost": tool.replacement_cost,
        "msrp": tool.msrp,
        # Warranty (maintenance build, 2026-10-19): the term is the
        # tool's own fact; the standing + end date are computed by
        # the shared function, mirroring the battery payload.
        # Structured details ride along (gap wave 1, 2026-10-20):
        # provider / contact / terms / type.
        "warranty_months": tool.warranty_months,
        "warranty_provider": tool.warranty_provider or "",
        "warranty_contact": tool.warranty_contact or "",
        "warranty_terms": tool.warranty_terms or "",
        "warranty_type": tool.warranty_type,
        "warranty_status": tool_warranty_status(tool),
        "warranty_end_date": warranty_end_date_of(tool),
        # Replaced marker (asset history, 2026-10-20): the date +
        # the replacement's name resolved live (the stored id is
        # a plain column and may dangle after a delete).
        "replaced_on": tool.replaced_on,
        "replaced_by_item_id": tool.replaced_by_item_id,
        "replaced_by_name": (
            ctx["replacement_names"].get(
                (tool.owner_id, tool.replaced_by_item_id)
            )
            if ctx is not None
            else replacement_name(db, tool)
        ),
        "replaced_note": tool.replaced_note or "",
        "quantity": tool.quantity or 1,
        "size": tool.size or "",
        "model_numbers": list(tool.model_numbers or [])
        or ([tool.model] if tool.model else []),
        "serial_numbers": list(tool.serial_numbers or [])
        or ([tool.serial_number] if tool.serial_number else []),
        "upc": tool.upc or "",
        "consumable": bool(tool.consumable),
        "business_use": bool(tool.business_use),
        "sub_limit_warning": bool(tool.business_use)
        and (
            ctx["sub_limit"].get(tool.owner_id, False)
            if ctx is not None
            else business_sub_limit_applies(db, tool.owner_id)
        ),
        "rebuy_store": tool.rebuy_store or "",
        "rebuy_url": tool.rebuy_url or "",
        "rebuy_sku": tool.rebuy_sku or "",
        "rebuy_notes": tool.rebuy_notes or "",
        "is_set": bool(tool.is_set),
        "attached_to_set_id": tool.attached_to_set_id,
        "attached_to_set": None,
        "dealer_company_id": dealer_id,
        "dealer_company_name": (
            (
                ctx["dealer_names"].get(tool.dealer_company_id)
                if ctx is not None
                else dealer_company_name(
                    db, tool.dealer_company_id, perspective_id=tool.owner_id
                )
            )
            if dealer_visible
            else None
        ),
        "tags": [
            serialize_tag(tag)
            for tag in (
                ctx["tags"].get(("tool", tool.id), [])
                if ctx is not None
                else get_item_tags(db, tool.owner_id, "tool", tool.id)
            )
        ],
        "set_summary": None,
        "set": None,
        "matched_via": getattr(tool, "_matched_via", None),
        "matched_label": getattr(tool, "_matched_label", None),
        "custom_data": tool.custom_data,
        "attachments": view_attachments,
        "created_at": tool.created_at,
        "updated_at": tool.updated_at,
        "active": active,
    }
    if tool.attached_to_set_id is not None:
        if ctx is not None:
            ref = ctx["tool_refs"].get(tool.attached_to_set_id)
            if ref is not None and ref[0] == tool.owner_id:
                view["attached_to_set"] = {
                    "id": tool.attached_to_set_id,
                    "name": ref[1],
                }
        else:
            parent = db.get(models.Tool, tool.attached_to_set_id)
            if parent is not None and parent.owner_id == tool.owner_id:
                view["attached_to_set"] = {"id": parent.id, "name": parent.name}
    if tool.is_set:
        if ctx is not None:
            pieces = ctx["pieces"].get(tool.id, [])
            attached = ctx["attached"].get(tool.id, [])
        else:
            pieces = _list_set_pieces(db, tool.id)
            attached = _attached_tools(db, tool)
        core = [p for p in pieces if p.kind == "core"]
        addons = [p for p in pieces if p.kind == "addon"]
        price_total, replacement_total = _set_totals(tool, pieces, attached)
        view["set_summary"] = {
            "core_count": len(core),
            "addon_count": len(addons) + len(attached),
        }
        view["set"] = {
            "core_pieces": [serialize_set_piece(p) for p in core],
            "addon_pieces": [serialize_set_piece(p) for p in addons],
            "attached_tools": [_attached_tool_ref(t) for t in attached],
            "price_total": price_total,
            "replacement_total": replacement_total,
        }
    return view


_CENTS = Decimal("0.01")


def _money_total(value) -> Decimal:
    """Coerce a SQL SUM result to a clean 2dp Decimal (0 when empty).

    Postgres SUM(Numeric) is exact; SQLite SUM can come back as a
    float with binary dust (216.70000000000002) — quantizing to cents
    makes both backends return the same value.
    """
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(_CENTS)


def get_inventory_stats(
    db: Session,
    owner_id: uuid.UUID,
    only_tool_ids: set[uuid.UUID] | None = None,
    only_battery_ids: set[uuid.UUID] | None = None,
) -> dict:
    """Vault totals for the owner's dashboard overview.

    Field semantics are defined on schemas.InventoryStats. Owner-scoped
    like every other query in this module — another user's assets never
    contribute. Batteries are assets: they count toward total_items and
    both money totals, and their categories join the distinct count.

    `only_tool_ids` / `only_battery_ids` are the entitlement active
    sets (billing computes them; routes pass them in): when given,
    inactive assets are excluded from every total — an over-limit
    vault's stats describe only what the plan actually covers.

    Item structure semantics (2026-10-18): money fields are PER UNIT,
    so both sums multiply by each record's quantity. total_items
    counts TOP-LEVEL items only (a set counts once; tools attached
    into a set and set pieces never count), but the money totals
    INCLUDE attached tools' values — the set's worth includes its
    addons. When an active set is given, attached tools ride with
    their set's activeness for the money totals.
    """
    # NOTE (wave 2): sold items follow the same stats contract as
    # every other out-of-set class (lost items included): when the
    # caller passes the entitlement active sets, sold items are
    # already absent from them (billing excludes sold outright);
    # with no active set the totals describe the whole vault.
    count_query = select(func.count(models.Tool.id)).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
    )
    money_query = select(
        func.sum(models.Tool.msrp * models.Tool.quantity),
        func.sum(models.Tool.replacement_cost * models.Tool.quantity),
        func.sum(models.Tool.purchase_price * models.Tool.quantity),
    ).where(models.Tool.owner_id == owner_id)
    battery_count_query = select(func.count(models.Battery.id)).where(
        models.Battery.owner_id == owner_id
    )
    # Total quantity (owner order, 2026-11-10: the inventory
    # header's stats): units over the SAME population
    # total_items counts — top-level tools (a set counts its
    # own quantity once; attached tools ride inside their set,
    # as they do for the count) plus every battery. The active
    # sets narrow it exactly as they narrow the count below.
    tool_qty_query = select(
        func.coalesce(func.sum(models.Tool.quantity), 0)
    ).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
    )
    battery_qty_query = select(
        func.coalesce(func.sum(models.Battery.quantity), 0)
    ).where(models.Battery.owner_id == owner_id)
    battery_money_query = select(
        func.sum(models.Battery.msrp * models.Battery.quantity),
        func.sum(models.Battery.replacement_cost * models.Battery.quantity),
        func.sum(models.Battery.purchase_price * models.Battery.quantity),
    ).where(models.Battery.owner_id == owner_id)
    # Reports-basis value (deep audit F1-03, 2026-10-23): the report
    # engine's grand "Total value" is SUM(purchase_price x quantity)
    # over assets PLUS the priced addon pieces of sets (a core
    # piece's own price is its own figure and never joins any total;
    # gone pieces contribute nothing — the _set_totals rules).
    # Home's TOTAL VALUE must be that same
    # number, so the purchase sums above and this piece sum feed a
    # separate `total_value` field; `total_market_value` keeps its
    # documented msrp semantics for its other consumers.
    piece_value_query = select(func.sum(models.SetPiece.price)).where(
        models.SetPiece.kind == "addon",
        models.SetPiece.price.is_not(None),
        models.SetPiece.status.notin_(_GONE_STATUSES),
        models.SetPiece.set_id.in_(
            select(models.Tool.id).where(
                models.Tool.owner_id == owner_id,
                models.Tool.is_set.is_(True),
            )
        ),
    )
    tool_categories = select(models.Tool.category).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
        models.Tool.category != "",
    )
    battery_categories = select(models.Battery.category).where(
        models.Battery.owner_id == owner_id,
        models.Battery.category != "",
    )
    if only_tool_ids is not None:
        count_query = count_query.where(models.Tool.id.in_(only_tool_ids))
        tool_qty_query = tool_qty_query.where(models.Tool.id.in_(only_tool_ids))
        money_query = money_query.where(
            or_(
                models.Tool.id.in_(only_tool_ids),
                models.Tool.attached_to_set_id.in_(only_tool_ids),
            )
        )
        piece_value_query = piece_value_query.where(
            models.SetPiece.set_id.in_(only_tool_ids)
        )
        tool_categories = tool_categories.where(models.Tool.id.in_(only_tool_ids))
    if only_battery_ids is not None:
        battery_count_query = battery_count_query.where(
            models.Battery.id.in_(only_battery_ids)
        )
        battery_qty_query = battery_qty_query.where(
            models.Battery.id.in_(only_battery_ids)
        )
        battery_money_query = battery_money_query.where(
            models.Battery.id.in_(only_battery_ids)
        )
        battery_categories = battery_categories.where(
            models.Battery.id.in_(only_battery_ids)
        )
    # Warranty counters (completeness audit A6, 2026-10-22): the
    # shared warranty_status_of computation over the population the
    # money totals describe — active sets applied the same way
    # (attached tools ride with their set's activeness).
    warranty_tool_query = select(
        models.Tool.purchase_date,
        models.Tool.warranty_months,
        models.Tool.warranty_type,
    ).where(models.Tool.owner_id == owner_id)
    warranty_battery_query = select(
        models.Battery.purchase_date,
        models.Battery.warranty_months,
        models.Battery.warranty_type,
    ).where(models.Battery.owner_id == owner_id)
    if only_tool_ids is not None:
        warranty_tool_query = warranty_tool_query.where(
            or_(
                models.Tool.id.in_(only_tool_ids),
                models.Tool.attached_to_set_id.in_(only_tool_ids),
            )
        )
    if only_battery_ids is not None:
        warranty_battery_query = warranty_battery_query.where(
            models.Battery.id.in_(only_battery_ids)
        )
    warranties_expiring_soon = 0
    warranties_expired = 0
    for row in db.execute(warranty_tool_query).all() + db.execute(
        warranty_battery_query
    ).all():
        record = SimpleNamespace(
            purchase_date=row[0], warranty_months=row[1], warranty_type=row[2]
        )
        status = warranty_status_of(record)
        if status == "expiring_soon":
            warranties_expiring_soon += 1
        elif status == "expired":
            warranties_expired += 1
    tool_count = db.execute(count_query).scalar_one()
    tool_money = db.execute(money_query).one()
    battery_count = db.execute(battery_count_query).scalar_one()
    battery_money = db.execute(battery_money_query).one()
    piece_value = db.execute(piece_value_query).scalar()
    total_value = (
        _money_total(tool_money[2])
        + _money_total(battery_money[2])
        + _money_total(piece_value)
    )
    categories = set(db.scalars(tool_categories)) | set(
        db.scalars(battery_categories)
    )
    total_quantity = int(db.execute(tool_qty_query).scalar_one()) + int(
        db.execute(battery_qty_query).scalar_one()
    )
    return {
        "total_items": tool_count + battery_count,
        "total_quantity": total_quantity,
        "total_market_value": _money_total(tool_money[0])
        + _money_total(battery_money[0]),
        "total_value": total_value,
        "total_replacement_cost": _money_total(tool_money[1])
        + _money_total(battery_money[1]),
        "category_count": len(categories),
        "warranties_expiring_soon": warranties_expiring_soon,
        "warranties_expired": warranties_expired,
    }


def peer_tool_view(tool: models.Tool) -> dict:
    """The fixed peer-sharing payload for one tool (owner directive
    2026-10-17): identity + photos, and NOTHING else — no pricing, no
    notes, no serial, no documents, no custom data.

    This is an explicit whitelist built key by key: the peer surface
    (core's peer_sharing) serializes from this dict and adds only
    owner attribution. Do not widen it casually — the minimal shape
    IS the feature (a browsing coworker sees what's on the shelf, not
    what it cost or what it's claimed against).
    """
    photos = [
        storage.presigned_get_url(item["key"])
        for item in tool.attachments or []
        if isinstance(item, dict) and "key" in item and item.get("kind") == "photo"
    ]
    return {
        "id": str(tool.id),
        "name": tool.name,
        "brand": tool.brand,
        "model": tool.model,
        "category": tool.category,
        "photos": photos,
    }


def _peer_like(term: str) -> str:
    """A contains-pattern for one search term, LIKE metacharacters
    in the term itself escaped so they match literally."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_peer_tools(
    db: Session, owner_ids: list[uuid.UUID], query: str
) -> list[models.Tool]:
    """Search the tools of several owners for the peer surface.

    Deliberately NOT the full-text search_vector: the vector indexes
    notes, serial numbers and custom values, and a peer viewer must
    never surface a tool through data they cannot see. Only the
    peer-payload text fields are searched — name, brand, model,
    category. Every term in the query must match (in any of the four
    fields); owners are exactly the ones passed in (core passes the
    owners with an accepted grant to the viewer).
    """
    terms = [t for t in (query or "").split() if t]
    if not owner_ids or not terms:
        return []
    fields = (models.Tool.name, models.Tool.brand, models.Tool.model, models.Tool.category)
    # Attached addon tools never appear as top-level peer items —
    # they ride inside their set's entry. A SET still matches when a
    # term hits one of its pieces' identity fields or an attached
    # tool's identity fields (same visible-fields discipline: pieces
    # show name + part number in the set entry).
    stmt = select(models.Tool).where(
        models.Tool.owner_id.in_(owner_ids),
        models.Tool.attached_to_set_id.is_(None),
        # Sold items (wave 2) never surface to peers.
        models.Tool.standing.notin_((models.STANDING_SOLD, models.STANDING_REPLACED)),
    )
    for term in terms:
        pattern = _peer_like(term)
        piece_sets = select(models.SetPiece.set_id).where(
            models.SetPiece.owner_id.in_(owner_ids),
            or_(
                models.SetPiece.part_number.ilike(pattern, escape="\\"),
                models.SetPiece.name.ilike(pattern, escape="\\"),
                models.SetPiece.serial_number.ilike(pattern, escape="\\"),
            ),
        )
        attached = aliased(models.Tool)
        attached_sets = select(attached.attached_to_set_id).where(
            attached.owner_id.in_(owner_ids),
            attached.attached_to_set_id.is_not(None),
            or_(
                attached.name.ilike(pattern, escape="\\"),
                attached.brand.ilike(pattern, escape="\\"),
                attached.model.ilike(pattern, escape="\\"),
            ),
        )
        stmt = stmt.where(
            or_(
                *(field.ilike(pattern, escape="\\") for field in fields),
                models.Tool.id.in_(piece_sets),
                models.Tool.id.in_(attached_sets),
            )
        )
    return list(
        db.scalars(stmt.order_by(models.Tool.name, models.Tool.created_at).limit(200))
    )


def get_tool_summary(db: Session, tool_id: uuid.UUID) -> dict | None:
    """Minimal cross-module view of a tool. Extend deliberately, not casually."""
    tool = db.get(models.Tool, tool_id)
    if tool is None:
        return None
    return {
        "id": str(tool.id),
        "name": tool.name,
        "brand": tool.brand,
        "model": tool.model,
        "serial_number": tool.serial_number,
        "replacement_cost": str(tool.replacement_cost)
        if tool.replacement_cost is not None
        else None,
    }


# -- batteries ---------------------------------------------------------------
#
# First-class asset records (owner spec 2026-10-18). Everything below
# mirrors the tool half above: ownership-checked reads, custom-field
# validation through the same engine (definitions applying to
# 'battery' or 'both'), attachments through the same stored-file
# services. The two battery-specific pieces are the warranty
# computation and the "currently in" link.


def _add_months_to_date(value: date, months: int) -> date:
    """Calendar month addition for dates, day clamped (Jan 31 + 1
    month = Feb 28/29) — the way warranty terms actually run."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def warranty_end_date_for(
    purchase_date: date | None, warranty_months: int | None
) -> date | None:
    """The last day of warranty coverage for ANY asset kind, or
    None when it can't be computed (no purchase date or no warranty
    term recorded). THE shared computation (maintenance build,
    2026-10-19): tools and batteries both read their standing from
    here, so the two kinds can never drift into two behaviors —
    the app had two warranty-expiry values and only one worked."""
    if purchase_date is None or warranty_months is None:
        return None
    return _add_months_to_date(purchase_date, warranty_months)


def warranty_end_date(battery: models.Battery) -> date | None:
    """The battery wrapper over warranty_end_date_for."""
    return warranty_end_date_for(battery.purchase_date, battery.warranty_months)


# An asset whose warranty ends within this window is "expiring soon".
WARRANTY_EXPIRING_DAYS = 30


def warranty_status_for(
    purchase_date: date | None,
    warranty_months: int | None,
    today: date | None = None,
) -> str:
    """COMPUTED warranty standing for any asset kind — never
    stored, so never stale.

    unknown:       purchase_date or warranty_months missing.
    expired:       the warranty end date is in the past.
    expiring_soon: the end date is today or within 30 days.
    in_warranty:   more than 30 days of coverage remain.
    """
    end = warranty_end_date_for(purchase_date, warranty_months)
    if end is None:
        return "unknown"
    today = today or date.today()
    days_left = (end - today).days
    if days_left < 0:
        return "expired"
    if days_left <= WARRANTY_EXPIRING_DAYS:
        return "expiring_soon"
    return "in_warranty"


def warranty_status_of(record, today: date | None = None) -> str:
    """The RECORD-level warranty standing (gap wave 1, 2026-10-20):
    a "lifetime" warranty_type computes as permanently in
    warranty — no purchase date or term needed, no end date.
    Every other record (type unset, "term", "limited") reads the
    shared months clock via warranty_status_for, unchanged."""
    if getattr(record, "warranty_type", None) == "lifetime":
        return "in_warranty"
    return warranty_status_for(record.purchase_date, record.warranty_months, today)


def warranty_end_date_of(record) -> date | None:
    """The record-level end date: lifetime coverage has none;
    everything else defers to the shared months computation."""
    if getattr(record, "warranty_type", None) == "lifetime":
        return None
    return warranty_end_date_for(record.purchase_date, record.warranty_months)


def warranty_status(
    battery: models.Battery, today: date | None = None
) -> str:
    """The battery wrapper over the shared computation — battery
    behavior is byte-identical to before the generalization (and
    now honors a lifetime warranty_type like tools do)."""
    return warranty_status_of(battery, today)


def tool_warranty_status(
    tool: models.Tool, today: date | None = None
) -> str:
    """A tool's computed warranty standing (tools gained
    warranty_months with the maintenance module, 2026-10-19)."""
    return warranty_status_of(tool, today)


class BatteryValidationError(ValueError):
    """A battery payload breaks a rule (e.g. a 'currently in' link to
    a tool the caller doesn't own). Routes turn this into a 422."""


def _validate_link(
    db: Session, owner_id: uuid.UUID, tool_id: uuid.UUID | None
) -> None:
    """The 'currently in' link may only name the owner's OWN tool —
    a battery can never point into someone else's vault."""
    if tool_id is None:
        return
    if get_tool(db, owner_id, tool_id) is None:
        raise BatteryValidationError(
            "The 'currently in' tool does not belong to you."
        )


def create_battery(
    db: Session, owner_id: uuid.UUID, payload: schemas.BatteryCreate
) -> models.Battery:
    data = payload.model_dump()
    data["custom_data"] = custom_fields.validate_custom_data(
        db, owner_id, payload.custom_data, item_type="battery"
    )
    data["attachments"] = []  # files attach only via the upload flow
    tag_ids = data.pop("tag_ids", []) or []
    data.pop("initial_schedule", None)  # the routes own schedules
    # The wizard's truck charge rides the create (2026-10-31) —
    # same contract as tools.
    truck_charge = data.pop("truck_charge", None)
    _validate_truck_charge(db, owner_id, data, truck_charge)
    _apply_location_write(db, owner_id, data)
    validate_dealer_company(db, owner_id, data.get("dealer_company_id"))
    _validate_link(db, owner_id, payload.currently_in_tool_id)
    battery = models.Battery(owner_id=owner_id, **data)
    db.add(battery)
    db.flush()
    if battery.purchase_price is not None:
        _record_acquisition(
            db, owner_id, "battery", battery, battery.quantity or 1
        )
    if tag_ids:
        set_item_tags(db, owner_id, "battery", battery.id, tag_ids)
    if truck_charge:
        _apply_truck_charge(
            db,
            owner_id,
            item_id=battery.id,
            item_name=battery.name,
            kind_label="Battery",
            company_id=data.get("dealer_company_id"),
            truck_charge=truck_charge,
        )
    db.commit()
    db.refresh(battery)
    return battery


def get_battery(
    db: Session, owner_id: uuid.UUID, battery_id: uuid.UUID
) -> models.Battery | None:
    battery = db.get(models.Battery, battery_id)
    if battery is None or battery.owner_id != owner_id:
        return None
    return battery


def list_batteries(
    db: Session,
    owner_id: uuid.UUID,
    in_tool_id: uuid.UUID | None = None,
) -> list[models.Battery]:
    """The owner's batteries, newest first. `in_tool_id` narrows to
    the batteries currently sitting in one tool (the tool detail
    page's battery panel)."""
    stmt = (
        select(models.Battery)
        .where(models.Battery.owner_id == owner_id)
        .order_by(models.Battery.created_at.desc())
    )
    if in_tool_id is not None:
        stmt = stmt.where(models.Battery.currently_in_tool_id == in_tool_id)
    return list(db.scalars(stmt))


def list_tools_page(
    db: Session,
    owner_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[models.Tool], int]:
    """One page of the owner's top-level tools + the whole count
    (step-4 fix D3: the plain list endpoint pages instead of
    returning the vault). Same rows and order as list_tools."""
    base = select(models.Tool).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(models.Tool.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total)


def list_batteries_page(
    db: Session,
    owner_id: uuid.UUID,
    *,
    in_tool_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[models.Battery], int]:
    """list_batteries with limit/offset + total (step-4 fix D3)."""
    base = select(models.Battery).where(models.Battery.owner_id == owner_id)
    if in_tool_id is not None:
        base = base.where(models.Battery.currently_in_tool_id == in_tool_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(models.Battery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total)


def existing_tool_ids(
    db: Session, owner_id: uuid.UUID, tool_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of `tool_ids` are the owner's tools, in ONE query —
    the bulk existence check whole-set consumers (the sharing
    preview's cheap pass, step-4 fix D4) use instead of a per-id
    get_tool loop."""
    if not tool_ids:
        return set()
    return set(
        db.scalars(
            select(models.Tool.id).where(
                models.Tool.owner_id == owner_id,
                models.Tool.id.in_(tool_ids),
            )
        )
    )


def existing_battery_ids(
    db: Session, owner_id: uuid.UUID, battery_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """The battery twin of existing_tool_ids."""
    if not battery_ids:
        return set()
    return set(
        db.scalars(
            select(models.Battery.id).where(
                models.Battery.owner_id == owner_id,
                models.Battery.id.in_(battery_ids),
            )
        )
    )


def get_owned_batteries(
    db: Session, owner_id: uuid.UUID, battery_ids: list[uuid.UUID]
) -> list[models.Battery]:
    """The subset of `battery_ids` owned by `owner_id` — the battery
    twin of get_owned_tools (sharing validates whole sets with it)."""
    if not battery_ids:
        return []
    return list(
        db.scalars(
            select(models.Battery).where(
                models.Battery.owner_id == owner_id,
                models.Battery.id.in_(battery_ids),
            )
        )
    )


def update_battery(
    db: Session,
    owner_id: uuid.UUID,
    battery_id: uuid.UUID,
    payload: schemas.BatteryUpdate,
) -> models.Battery | None:
    battery = get_battery(db, owner_id, battery_id)
    if battery is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "custom_data" in data:
        data["custom_data"] = custom_fields.validate_custom_data(
            db, owner_id, data["custom_data"], item_type="battery"
        )
    if "currently_in_tool_id" in data:
        _validate_link(db, owner_id, data["currently_in_tool_id"])
    if "dealer_company_id" in data:
        validate_dealer_company(db, owner_id, data["dealer_company_id"])
    data.pop("attachments", None)  # files attach only via the upload flow
    data.pop("initial_schedule", None)  # the routes own schedules
    _apply_location_write(db, owner_id, data)
    tag_ids = data.pop("tag_ids", None)
    old_quantity = battery.quantity or 1
    for key, value in data.items():
        setattr(battery, key, value)
    db.flush()
    _record_quantity_increase(db, owner_id, "battery", battery, old_quantity)
    if tag_ids is not None:
        set_item_tags(db, owner_id, "battery", battery.id, tag_ids)
    db.commit()
    db.refresh(battery)
    return battery


def delete_battery(db: Session, owner_id: uuid.UUID, battery_id: uuid.UUID) -> bool:
    battery = get_battery(db, owner_id, battery_id)
    if battery is None:
        return False
    _run_delete_guards(db, owner_id, "battery", battery_id)
    # Tag links: ORM deletes so they land in the change journal
    # (the FK CASCADE remains the backstop). Files: tombstoned
    # for the retention window, not destroyed (audit trail).
    for link in db.scalars(
        select(models.ItemTag).where(models.ItemTag.battery_id == battery_id)
    ):
        db.delete(link)
    # Lost/stolen reports (gap wave 1) — see delete_tool.
    for report in db.scalars(
        select(models.ItemLossReport).where(
            models.ItemLossReport.item_kind == "battery",
            models.ItemLossReport.item_id == battery_id,
        )
    ):
        db.delete(report)
    journal.retire_record_files(db, owner_id, battery, entity_type="battery")
    # Tools For Sale (owner spec 2026-10-25): deleting the item
    # ends its active listings in this same transaction — see
    # delete_tool.
    from app.modules.marketplace import service as marketplace_service

    marketplace_service.end_listings_for_source(
        db, owner_id, "battery", battery_id
    )
    db.delete(battery)
    db.commit()
    return True


def serialize_battery(
    db: Session,
    battery: models.Battery,
    active: bool = True,
    dealer_visible: bool = True,
    ctx: dict | None = None,
) -> dict:
    """Public shape of a battery: the tool shape plus the battery
    fields, the computed warranty standing, and the 'currently in'
    link resolved to BOTH the tool's id and its display name (the
    UI shows "In: <tool name>" without a second fetch).

    `ctx` is serialize_context's batch prefetch — see
    serialize_tool; the payload is identical with or without it."""
    tool_name = None
    if battery.currently_in_tool_id is not None:
        if ctx is not None:
            ref = ctx["tool_refs"].get(battery.currently_in_tool_id)
            if ref is not None and ref[0] == battery.owner_id:
                tool_name = ref[1]
        else:
            tool = db.get(models.Tool, battery.currently_in_tool_id)
            if tool is not None and tool.owner_id == battery.owner_id:
                tool_name = tool.name
    return {
        "id": battery.id,
        "owner_id": battery.owner_id,
        "name": battery.name,
        "brand": battery.brand,
        "model": battery.model,
        "serial_number": battery.serial_number,
        "upc": battery.upc or "",
        "business_use": bool(battery.business_use),
        "sub_limit_warning": bool(battery.business_use)
        and (
            ctx["sub_limit"].get(battery.owner_id, False)
            if ctx is not None
            else business_sub_limit_applies(db, battery.owner_id)
        ),
        "category": battery.category,
        "location": battery.location,
        "location_id": battery.location_id,
        "standing": battery.standing,
        "notes": battery.notes,
        "purchase_price": battery.purchase_price,
        "purchase_date": battery.purchase_date,
        "replacement_cost": battery.replacement_cost,
        "msrp": battery.msrp,
        "platform": battery.platform,
        "voltage": battery.voltage,
        "capacity_ah": battery.capacity_ah,
        "chemistry": battery.chemistry,
        "warranty_months": battery.warranty_months,
        "warranty_provider": battery.warranty_provider or "",
        "warranty_contact": battery.warranty_contact or "",
        "warranty_terms": battery.warranty_terms or "",
        "warranty_type": battery.warranty_type,
        "warranty_status": warranty_status(battery),
        "warranty_end_date": warranty_end_date_of(battery),
        # Replaced marker — mirrors Tool's exactly (see above).
        "replaced_on": battery.replaced_on,
        "replaced_by_item_id": battery.replaced_by_item_id,
        "replaced_by_name": (
            ctx["replacement_names"].get(
                (battery.owner_id, battery.replaced_by_item_id)
            )
            if ctx is not None
            else replacement_name(db, battery)
        ),
        "replaced_note": battery.replaced_note or "",
        "currently_in_tool_id": battery.currently_in_tool_id,
        "currently_in_tool_name": tool_name,
        "quantity": battery.quantity or 1,
        "dealer_company_id": (
            battery.dealer_company_id if dealer_visible else None
        ),
        "dealer_company_name": (
            (
                ctx["dealer_names"].get(battery.dealer_company_id)
                if ctx is not None
                else dealer_company_name(
                    db, battery.dealer_company_id, perspective_id=battery.owner_id
                )
            )
            if dealer_visible
            else None
        ),
        "tags": [
            serialize_tag(tag)
            for tag in (
                ctx["tags"].get(("battery", battery.id), [])
                if ctx is not None
                else get_item_tags(db, battery.owner_id, "battery", battery.id)
            )
        ],
        "custom_data": battery.custom_data,
        "attachments": _serialize_attachments(battery),
        "created_at": battery.created_at,
        "updated_at": battery.updated_at,
        "active": active,
    }


def serialize_context(
    db: Session,
    tools=(),
    batteries=(),
    dealer_visible: bool = True,
) -> dict:
    """Batch-prefetch for serialize_tool / serialize_battery over
    a PAGE of rows (scale fix, 2026-10-26; audit F-02).

    The serializers resolve six things per row — tags, the dealer
    name, a set's pieces + attached tools, the parent set's name,
    the replacement's name, the business sub-limit flag (plus a
    battery's current-tool name) — and doing that per row cost a
    list page of 200 rows 400–1,000+ queries. This builder runs
    ONE query per lookup class for the whole page, from the same
    predicates and orderings the per-row helpers use, and the
    serializers read the maps instead. Single-row callers pass no
    context and keep the per-row path — the payload is identical
    either way (pinned by test).
    """
    tools = list(tools)
    batteries = list(batteries)
    ctx: dict = {
        "tags": {},
        "dealer_names": {},
        "pieces": {},
        "attached": {},
        "tool_refs": {},
        "replacement_names": {},
        "sub_limit": {},
    }
    if not tools and not batteries:
        return ctx

    # Tags: the get_item_tags join + ordering, for every item on
    # the page in one query per kind.
    for kind, items in (("tool", tools), ("battery", batteries)):
        if not items:
            continue
        id_column = (
            models.ItemTag.tool_id
            if kind == "tool"
            else models.ItemTag.battery_id
        )
        rows = db.execute(
            select(models.Tag, id_column)
            .join(models.ItemTag, models.ItemTag.tag_id == models.Tag.id)
            .where(
                models.ItemTag.owner_id.in_({item.owner_id for item in items}),
                models.ItemTag.item_kind == kind,
                id_column.in_([item.id for item in items]),
            )
            .order_by(func.lower(models.Tag.name))
        )
        for tag, item_id in rows:
            ctx["tags"].setdefault((kind, item_id), []).append(tag)

    # Dealer display names for the page's distinct companies.
    if dealer_visible:
        company_ids = {
            item.dealer_company_id
            for item in (*tools, *batteries)
            if item.dealer_company_id is not None
        }
        if company_ids:
            from app.modules.dealers import models as dealer_models

            ctx["dealer_names"] = dict(
                db.execute(
                    select(
                        dealer_models.DealerCompany.id,
                        dealer_models.DealerCompany.name,
                    ).where(dealer_models.DealerCompany.id.in_(company_ids))
                ).all()
            )
            # Personal dealer edits (2026-11-05): each item's
            # dealer name resolves through its OWNER's personal
            # layer, matching the per-row path. The map is keyed
            # by company alone, so a mixed-owner page sharing one
            # company resolves it for the last owner in page
            # order — owner pages (the ctx callers) never mix.
            from app.modules.dealers import service as dealer_service

            owners_companies: dict[uuid.UUID, set] = {}
            for item in (*tools, *batteries):
                if item.dealer_company_id is not None:
                    owners_companies.setdefault(item.owner_id, set()).add(
                        item.dealer_company_id
                    )
            for owner_id, owned_ids in owners_companies.items():
                for cid, name in dealer_service.personal_name_map(
                    db, owner_id, owned_ids
                ).items():
                    ctx["dealer_names"][cid] = name

    # Set structure for the sets on the page: pieces and attached
    # tools, each with the single-set helpers' ordering.
    set_ids = [t.id for t in tools if t.is_set]
    if set_ids:
        for piece in db.scalars(
            select(models.SetPiece)
            .where(models.SetPiece.set_id.in_(set_ids))
            .order_by(models.SetPiece.sort_order, models.SetPiece.created_at)
        ):
            ctx["pieces"].setdefault(piece.set_id, []).append(piece)
        for attached in db.scalars(
            select(models.Tool)
            .where(models.Tool.attached_to_set_id.in_(set_ids))
            .order_by(models.Tool.created_at)
        ):
            ctx["attached"].setdefault(attached.attached_to_set_id, []).append(
                attached
            )

    # Light tool references — (owner_id, name) by tool id — for
    # the two name-only resolutions: a tool's parent set and a
    # battery's current tool.
    ref_ids = {
        t.attached_to_set_id for t in tools if t.attached_to_set_id is not None
    } | {
        b.currently_in_tool_id
        for b in batteries
        if b.currently_in_tool_id is not None
    }
    if ref_ids:
        ctx["tool_refs"] = {
            row_id: (owner_id, name)
            for row_id, owner_id, name in db.execute(
                select(models.Tool.id, models.Tool.owner_id, models.Tool.name)
                .where(models.Tool.id.in_(ref_ids))
            )
        }

    # Replacement names: replacement_name's own rule — the TOOL
    # with that id if it is the record owner's, else the BATTERY,
    # else nothing (the id may dangle).
    pairs = {
        (item.owner_id, item.replaced_by_item_id)
        for item in (*tools, *batteries)
        if item.replaced_by_item_id is not None
    }
    if pairs:
        target_ids = {target for _owner, target in pairs}
        tool_names = {
            (owner_id, row_id): name
            for row_id, owner_id, name in db.execute(
                select(models.Tool.id, models.Tool.owner_id, models.Tool.name)
                .where(models.Tool.id.in_(target_ids))
            )
        }
        battery_names = {
            (owner_id, row_id): name
            for row_id, owner_id, name in db.execute(
                select(
                    models.Battery.id, models.Battery.owner_id, models.Battery.name
                ).where(models.Battery.id.in_(target_ids))
            )
        }
        for pair in pairs:
            name = tool_names.get(pair)
            if name is None:
                name = battery_names.get(pair)
            ctx["replacement_names"][pair] = name

    # The business sub-limit flag is per OWNER — a page carries
    # one owner in practice; resolve each distinct owner once.
    for owner_id in {item.owner_id for item in (*tools, *batteries)}:
        ctx["sub_limit"][owner_id] = business_sub_limit_applies(db, owner_id)
    return ctx


def _identity_rows(model, owner_id: uuid.UUID, db: Session) -> list[dict]:
    rows = db.execute(
        select(model.id, model.name, model.brand, model.model, model.serial_number)
        .where(model.owner_id == owner_id)
        .order_by(model.created_at.desc())
    )
    return [dict(row._mapping) for row in rows]


def list_battery_identities(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Identity-only view of the owner's batteries for cross-module
    pickers — the battery twin of list_tool_identities."""
    return _identity_rows(models.Battery, owner_id, db)


def list_item_identities(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """The owner's shareable items: tools AND batteries, each row
    marked with its "kind" ('tool' | 'battery') so pickers render
    one list (core's sharing settings). Tools keep their original
    order first, then batteries — both newest-first within kind.

    Attached addon tools are NOT listed: they live inside their set
    and share (or not) with it. Tool rows carry `is_set` so pickers
    can ask the "include addon pieces?" question for sets."""
    tool_rows = list(
        db.scalars(
            select(models.Tool)
            .where(
                models.Tool.owner_id == owner_id,
                models.Tool.attached_to_set_id.is_(None),
            )
            .order_by(models.Tool.created_at.desc())
        )
    )
    items = [
        {
            "id": tool.id,
            "name": tool.name,
            "brand": tool.brand,
            "model": tool.model,
            "serial_number": tool.serial_number,
            "kind": "tool",
            "is_set": bool(tool.is_set),
        }
        for tool in tool_rows
    ]
    items += [
        {**row, "kind": "battery", "is_set": False}
        for row in _identity_rows(models.Battery, owner_id, db)
    ]
    return items


def list_item_sharing_facts(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Per-item facts core's sharing rules match on (Package C):
    every shareable item (top-level tools — attached tools ride
    inside their set — plus batteries) with the three facts a rule
    can key on: its category text, its location TREE node id, and
    its tag ids. Core resolves rules against this snapshot-shaped
    list; it never touches inventory models itself (module law).

    Tag ids come from one ItemTag sweep for the owner, grouped in
    memory — a rule resolution reads the whole vault's facts at
    once, so per-item tag queries would multiply needlessly."""
    facts: list[dict] = []
    tag_links = db.execute(
        select(
            models.ItemTag.item_kind,
            models.ItemTag.tool_id,
            models.ItemTag.battery_id,
            models.ItemTag.tag_id,
        ).where(models.ItemTag.owner_id == owner_id)
    )
    tags_by_item: dict[tuple[str, uuid.UUID], set[uuid.UUID]] = {}
    for kind, tool_id, battery_id, tag_id in tag_links:
        item_id = tool_id if kind == "tool" else battery_id
        if item_id is not None:
            tags_by_item.setdefault((kind, item_id), set()).add(tag_id)
    tool_rows = db.execute(
        select(
            models.Tool.id,
            models.Tool.category,
            models.Tool.location_id,
            models.Tool.is_set,
        ).where(
            models.Tool.owner_id == owner_id,
            models.Tool.attached_to_set_id.is_(None),
            # SOLD items (wave 2) are unshareable: they left the
            # active set. Excluding them HERE — the facts snapshot
            # both sharing systems resolve against — drops them
            # from tier picks/rules and peer views in one place.
            models.Tool.standing.notin_((models.STANDING_SOLD, models.STANDING_REPLACED)),
        )
    )
    for tool_id, category, location_id, is_set in tool_rows:
        facts.append(
            {
                "kind": "tool",
                "id": tool_id,
                "category": category or "",
                "location_id": location_id,
                "tag_ids": tags_by_item.get(("tool", tool_id), set()),
                "is_set": bool(is_set),
            }
        )
    battery_rows = db.execute(
        select(
            models.Battery.id,
            models.Battery.category,
            models.Battery.location_id,
        ).where(
            models.Battery.owner_id == owner_id,
            models.Battery.standing.notin_((models.STANDING_SOLD, models.STANDING_REPLACED)),
        )
    )
    for battery_id, category, location_id in battery_rows:
        facts.append(
            {
                "kind": "battery",
                "id": battery_id,
                "category": category or "",
                "location_id": location_id,
                "tag_ids": tags_by_item.get(("battery", battery_id), set()),
                "is_set": False,
            }
        )
    return facts


def peer_battery_view(battery: models.Battery) -> dict:
    """The fixed peer-sharing payload for one battery — the SAME
    whitelist as peer_tool_view (identity + photos, nothing else),
    with the battery's category (default 'Battery') and a
    kind='battery' mark so the peer UI can badge it. Tool items
    carry no kind key at all: their payload is pinned byte-for-byte
    by the peer tests, and absence reads as 'tool'."""
    photos = [
        storage.presigned_get_url(item["key"])
        for item in battery.attachments or []
        if isinstance(item, dict) and "key" in item and item.get("kind") == "photo"
    ]
    return {
        "id": str(battery.id),
        "kind": "battery",
        "name": battery.name,
        "brand": battery.brand,
        "model": battery.model,
        "category": battery.category,
        "photos": photos,
    }


def search_peer_batteries(
    db: Session, owner_ids: list[uuid.UUID], query: str
) -> list[models.Battery]:
    """Cross-owner battery search for the peer surface — the battery
    twin of search_peer_tools, with the same discipline: only the
    peer-payload text fields are searched (name, brand, model,
    category), never notes/serials/custom data."""
    terms = [t for t in (query or "").split() if t]
    if not owner_ids or not terms:
        return []
    fields = (
        models.Battery.name,
        models.Battery.brand,
        models.Battery.model,
        models.Battery.category,
    )
    stmt = select(models.Battery).where(
        models.Battery.owner_id.in_(owner_ids),
        # Sold items (wave 2) never surface to peers.
        models.Battery.standing.notin_((models.STANDING_SOLD, models.STANDING_REPLACED)),
    )
    for term in terms:
        pattern = _peer_like(term)
        stmt = stmt.where(
            or_(*(field.ilike(pattern, escape="\\") for field in fields))
        )
    return list(
        db.scalars(
            stmt.order_by(models.Battery.name, models.Battery.created_at).limit(200)
        )
    )



# The fixed tag palette (gap wave 1, 2026-10-20): a tag's color
# is one of these names — amber is the default, the app's color.
# The frontend renders chips from the same list. "slate" is in
# the list because the bulk-actions flow has always created tags
# with it — legacy data carries it, so the palette honors it.
TAG_COLORS = (
    "amber", "red", "orange", "yellow", "green",
    "blue", "purple", "pink", "slate", "gray",
)
DEFAULT_TAG_COLOR = "amber"

# -- tags --------------------------------------------------------------------
#
# Per-user vocabulary + item links (item structure package,
# 2026-10-18). Tags belong to one owner; links join them to tools or
# batteries. Consistent with the app's tag semantics: names must be
# unique per user (case-insensitive — creating a duplicate returns
# the existing tag), renaming a tag renames it everywhere (the name
# lives on the tag row), and deleting a tag just removes its links.


def serialize_tag(tag: models.Tag, item_count: int = 0) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "item_count": item_count,
    }


def list_tags(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """The owner's tags with live item counts, alphabetical."""
    tags = list(
        db.scalars(
            select(models.Tag)
            .where(models.Tag.owner_id == owner_id)
            .order_by(func.lower(models.Tag.name))
        )
    )
    counts = dict(
        db.execute(
            select(models.ItemTag.tag_id, func.count(models.ItemTag.id))
            .where(models.ItemTag.owner_id == owner_id)
            .group_by(models.ItemTag.tag_id)
        ).all()
    )
    return [serialize_tag(tag, counts.get(tag.id, 0)) for tag in tags]


def _find_tag_by_name(
    db: Session, owner_id: uuid.UUID, name: str
) -> models.Tag | None:
    return db.scalars(
        select(models.Tag).where(
            models.Tag.owner_id == owner_id,
            func.lower(models.Tag.name) == name.strip().lower(),
        )
    ).first()


def create_tag(
    db: Session, owner_id: uuid.UUID, name: str, color: str = "amber"
) -> models.Tag:
    """Create a tag — or return the existing one when the owner
    already has this name in any capitalization (the app's rule:
    a tag name names ONE tag per user)."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ToolValidationError("A tag needs a name.")
    if color and color not in TAG_COLORS:
        raise ToolValidationError(
            f"Unknown tag color '{color}' — pick one of: "
            + ", ".join(TAG_COLORS)
            + "."
        )
    existing = _find_tag_by_name(db, owner_id, cleaned)
    if existing is not None:
        return existing
    tag = models.Tag(owner_id=owner_id, name=cleaned, color=color or "amber")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def get_tag(db: Session, owner_id: uuid.UUID, tag_id: uuid.UUID) -> models.Tag | None:
    tag = db.get(models.Tag, tag_id)
    if tag is None or tag.owner_id != owner_id:
        return None
    return tag


def update_tag(
    db: Session,
    owner_id: uuid.UUID,
    tag_id: uuid.UUID,
    *,
    name: str | None = None,
    color: str | None = None,
) -> models.Tag | None:
    tag = get_tag(db, owner_id, tag_id)
    if tag is None:
        return None
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ToolValidationError("A tag needs a name.")
        clash = _find_tag_by_name(db, owner_id, cleaned)
        if clash is not None and clash.id != tag.id:
            raise ToolValidationError(
                f"You already have a tag called '{clash.name}'."
            )
        tag.name = cleaned
    if color is not None:
        if color not in TAG_COLORS:
            raise ToolValidationError(
                f"Unknown tag color '{color}' — pick one of: "
                + ", ".join(TAG_COLORS)
                + "."
            )
        tag.color = color
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, owner_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
    tag = get_tag(db, owner_id, tag_id)
    if tag is None:
        return False
    # ORM deletes so the link removals land in the change journal
    # and a restore of the tag brings its links back with it.
    for link in db.scalars(
        select(models.ItemTag).where(models.ItemTag.tag_id == tag_id)
    ):
        db.delete(link)
    db.delete(tag)
    db.commit()
    return True


def get_item_tags(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[models.Tag]:
    id_column = (
        models.ItemTag.tool_id if item_kind == "tool" else models.ItemTag.battery_id
    )
    return list(
        db.scalars(
            select(models.Tag)
            .join(models.ItemTag, models.ItemTag.tag_id == models.Tag.id)
            .where(
                models.ItemTag.owner_id == owner_id,
                models.ItemTag.item_kind == item_kind,
                id_column == item_id,
            )
            .order_by(func.lower(models.Tag.name))
        )
    )


def set_item_tags(
    db: Session,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    tag_ids: list[uuid.UUID],
) -> list[models.Tag]:
    """Replace an item's tag links wholesale. The item and every tag
    must be the owner's — a foreign id is a 422, never a silent skip
    (same discipline as consent sharing's item validation). Does NOT
    commit: callers fold it into their own transaction."""
    if item_kind == "tool":
        if get_tool(db, owner_id, item_id) is None:
            raise ToolValidationError("That tool does not belong to you.")
    else:
        if get_battery(db, owner_id, item_id) is None:
            raise ToolValidationError("That battery does not belong to you.")
    unique_ids = list(dict.fromkeys(tag_ids))
    tags: list[models.Tag] = []
    for tag_id in unique_ids:
        tag = get_tag(db, owner_id, tag_id)
        if tag is None:
            raise ToolValidationError("One of those tags does not belong to you.")
        tags.append(tag)
    id_column = (
        models.ItemTag.tool_id if item_kind == "tool" else models.ItemTag.battery_id
    )
    # ORM deletes, not a bulk DELETE: every removed link lands in
    # the change journal, so a restore replays the tag change
    # exactly (audit trail, 2026-10-19).
    for link in db.scalars(
        select(models.ItemTag).where(
            models.ItemTag.owner_id == owner_id,
            models.ItemTag.item_kind == item_kind,
            id_column == item_id,
        )
    ):
        db.delete(link)
    for tag in tags:
        db.add(
            models.ItemTag(
                owner_id=owner_id,
                item_kind=item_kind,
                tool_id=item_id if item_kind == "tool" else None,
                battery_id=item_id if item_kind == "battery" else None,
                tag_id=tag.id,
            )
        )
    db.flush()
    return tags


def tool_ids_with_tag(db: Session, owner_id: uuid.UUID, tag_id: uuid.UUID) -> set:
    return set(
        db.scalars(
            select(models.ItemTag.tool_id).where(
                models.ItemTag.owner_id == owner_id,
                models.ItemTag.item_kind == "tool",
                models.ItemTag.tag_id == tag_id,
                models.ItemTag.tool_id.is_not(None),
            )
        )
    )


def battery_ids_with_tag(db: Session, owner_id: uuid.UUID, tag_id: uuid.UUID) -> set:
    return set(
        db.scalars(
            select(models.ItemTag.battery_id).where(
                models.ItemTag.owner_id == owner_id,
                models.ItemTag.item_kind == "battery",
                models.ItemTag.tag_id == tag_id,
                models.ItemTag.battery_id.is_not(None),
            )
        )
    )


# -- standing (Package B) ---------------------------------------------------------


def apply_standing(record, standing: str) -> None:
    """The ONE writer of an asset's standing (tools + batteries).

    `standing` is the authority. The legacy `repair_state` column
    mirrors it for the repair trio so the maintenance history and
    its pinned readers stay true; declaring an item lost/stolen
    does NOT disturb an open repair (repair_state keeps its trio
    value), and marking it back in service completes the repair
    standing and clears the problem text — the same end state
    maintenance's "fixed" action produces.
    """
    record.standing = standing
    if standing in models.REPAIR_TRIO:
        record.repair_state = standing
    if standing == models.STANDING_IN_SERVICE:
        record.repair_problem = ""


# -- location tree (Package B) ----------------------------------------------------
#
# Ryan's organizing model: the top tier is the toolbox / place,
# drawers nest under it, and filtering by a place shows EVERYTHING
# beneath it. An item's `location` text is the node's PATH string,
# denormalized and kept in sync here; `location_id` is the
# structure. The Used Parts tree (parts module) is a SEPARATE tree
# by design — never merged with this one.


def owned_locations(db: Session, owner_id: uuid.UUID) -> list[models.InventoryLocation]:
    """The owner's whole tree, roots first, name-ordered within a
    level (a stable, friendly reading order)."""
    nodes = list(
        db.scalars(
            select(models.InventoryLocation)
            .where(models.InventoryLocation.owner_id == owner_id)
            .order_by(
                models.InventoryLocation.sort_order,
                models.InventoryLocation.name,
            )
        )
    )
    nodes.sort(key=lambda n: (0 if n.parent_id is None else 1, n.sort_order, n.name.lower()))
    return nodes


def get_location_node(
    db: Session, owner_id: uuid.UUID, location_id: uuid.UUID
) -> models.InventoryLocation | None:
    node = db.get(models.InventoryLocation, location_id)
    if node is None or node.owner_id != owner_id:
        return None
    return node


def location_path(nodes: list[models.InventoryLocation], node: models.InventoryLocation) -> str:
    """'Shop Toolbox / Left Drawer 2' — root first, ' / '-joined."""
    by_id = {n.id: n for n in nodes}
    parts: list[str] = []
    current: models.InventoryLocation | None = node
    while current is not None:
        parts.append(current.name)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return " / ".join(reversed(parts))


def location_subtree_ids(nodes: list[models.InventoryLocation], root_id: uuid.UUID) -> set[uuid.UUID]:
    """The node plus every descendant — the subtree filter set."""
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node.id)
    found: set[uuid.UUID] = set()
    stack = [root_id]
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(children.get(current, []))
    return found


def _location_item_counts(db: Session, owner_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Direct item counts per node (tools + batteries)."""
    counts: dict[uuid.UUID, int] = {}
    for model in (models.Tool, models.Battery):
        rows = db.execute(
            select(model.location_id, func.count())
            .where(model.owner_id == owner_id, model.location_id.is_not(None))
            .group_by(model.location_id)
        )
        for location_id, count in rows:
            counts[location_id] = counts.get(location_id, 0) + count
    return counts


def serialize_location_node(
    db: Session,
    owner_id: uuid.UUID,
    node: models.InventoryLocation,
    *,
    nodes: list[models.InventoryLocation] | None = None,
    counts: dict[uuid.UUID, int] | None = None,
) -> dict:
    nodes = nodes if nodes is not None else owned_locations(db, owner_id)
    counts = counts if counts is not None else _location_item_counts(db, owner_id)
    subtree = location_subtree_ids(nodes, node.id)
    return {
        "id": node.id,
        "owner_id": node.owner_id,
        "name": node.name,
        "parent_id": node.parent_id,
        "parent_layout_id": node.parent_layout_id,
        "drawer_index": node.drawer_index,
        "path": location_path(nodes, node),
        "sort_order": node.sort_order,
        "item_count": counts.get(node.id, 0),
        "subtree_item_count": sum(counts.get(nid, 0) for nid in subtree),
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


def list_location_tree(db: Session, owner_id: uuid.UUID) -> list[dict]:
    nodes = owned_locations(db, owner_id)
    counts = _location_item_counts(db, owner_id)
    return [
        serialize_location_node(db, owner_id, n, nodes=nodes, counts=counts)
        for n in nodes
    ]


def create_location_node(
    db: Session,
    owner_id: uuid.UUID,
    *,
    name: str,
    parent_id: uuid.UUID | None = None,
    sort_order: int = 0,
    parent_layout_id: uuid.UUID | None = None,
    drawer_index: int | None = None,
) -> models.InventoryLocation:
    if parent_id is not None and get_location_node(db, owner_id, parent_id) is None:
        raise ToolValidationError("That parent location isn't yours.")
    if (
        parent_layout_id is not None
        and get_location_node(db, owner_id, parent_layout_id) is None
    ):
        raise ToolValidationError("That layout location isn't yours.")
    node = models.InventoryLocation(
        owner_id=owner_id,
        name=name,
        parent_id=parent_id,
        sort_order=sort_order,
        parent_layout_id=parent_layout_id,
        drawer_index=drawer_index,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def update_location_node(
    db: Session,
    owner_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    name: str | None = None,
    parent_id: uuid.UUID | None = ...,
    sort_order: int | None = None,
    parent_layout_id: uuid.UUID | None = ...,
    drawer_index: int | None = ...,
) -> models.InventoryLocation | None:
    """Rename / reparent / reorder a node. A rename or move changes
    the PATH of everything under it — filed items' location text is
    resynced before returning."""
    node = get_location_node(db, owner_id, location_id)
    if node is None:
        return None
    nodes = owned_locations(db, owner_id)
    if name is not None:
        node.name = name
    if parent_id is not ...:
        if parent_id is not None:
            if get_location_node(db, owner_id, parent_id) is None:
                raise ToolValidationError("That parent location isn't yours.")
            if parent_id in location_subtree_ids(nodes, location_id):
                raise ToolValidationError(
                    "A location can't be moved inside itself."
                )
        node.parent_id = parent_id
    if sort_order is not None:
        node.sort_order = sort_order
    if parent_layout_id is not ...:
        if parent_layout_id is not None:
            if get_location_node(db, owner_id, parent_layout_id) is None:
                raise ToolValidationError("That layout location isn't yours.")
            if parent_layout_id == location_id:
                raise ToolValidationError(
                    "A drawer can't be its own layout."
                )
        node.parent_layout_id = parent_layout_id
    if drawer_index is not ...:
        node.drawer_index = drawer_index
    db.flush()
    _resync_location_texts(db, owner_id)
    db.commit()
    db.refresh(node)
    return node


def delete_location_node(
    db: Session,
    owner_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    reassign_to_id: uuid.UUID | None = None,
    detach: bool = False,
) -> bool:
    """Delete a node that holds children or items — never a silent
    orphan. Reassignment moves children AND items to the target;
    detach lifts children to this node's parent and unfiles the
    items (location text cleared — the place is gone)."""
    node = get_location_node(db, owner_id, location_id)
    if node is None:
        return False
    nodes = owned_locations(db, owner_id)
    children = [n for n in nodes if n.parent_id == location_id]
    items = [
        item
        for model in (models.Tool, models.Battery)
        for item in db.scalars(
            select(model).where(
                model.owner_id == owner_id, model.location_id == location_id
            )
        )
    ]
    if (children or items) and reassign_to_id is None and not detach:
        raise ToolValidationError(
            "That location still holds places or items — choose where "
            "they go, or detach them, before deleting it."
        )
    if reassign_to_id is not None:
        target = get_location_node(db, owner_id, reassign_to_id)
        if target is None or reassign_to_id == location_id:
            raise ToolValidationError(
                "Choose one of your other locations to move things to."
            )
        if reassign_to_id in location_subtree_ids(nodes, location_id):
            raise ToolValidationError(
                "Things can't move into a place that's being deleted."
            )
    new_parent = reassign_to_id if reassign_to_id is not None else node.parent_id
    for child in children:
        child.parent_id = new_parent
    # Drawer links (audit A3): a node that named this place as its
    # layout is a drawer of a place that no longer exists — clear
    # the link (the drawer position itself is kept; it describes
    # the node's place in whatever layout holds it next).
    for other in nodes:
        if other.parent_layout_id == location_id:
            other.parent_layout_id = None
    for item in items:
        item.location_id = reassign_to_id  # None when detaching
    db.flush()
    db.delete(node)
    db.flush()
    _resync_location_texts(db, owner_id)
    # Detached items have no node left to derive a path from.
    for item in items:
        if item.location_id is None:
            item.location = ""
    db.commit()
    return True


def _resync_location_texts(db: Session, owner_id: uuid.UUID) -> None:
    """Rewrite every filed item's location text from its node's
    current path (rename / move / delete side)."""
    nodes = owned_locations(db, owner_id)
    paths = {n.id: location_path(nodes, n) for n in nodes}
    for model in (models.Tool, models.Battery):
        for item in db.scalars(
            select(model).where(
                model.owner_id == owner_id, model.location_id.is_not(None)
            )
        ):
            if item.location_id in paths:
                item.location = paths[item.location_id]


def _node_by_path(
    nodes: list[models.InventoryLocation], text: str
) -> models.InventoryLocation | None:
    """Resolve a 'A / B / C' path string to its node, if it is one."""
    parts = [p.strip() for p in text.split(" / ")]
    parent_id: uuid.UUID | None = None
    found: models.InventoryLocation | None = None
    for part in parts:
        found = next(
            (n for n in nodes if n.parent_id == parent_id and n.name == part),
            None,
        )
        if found is None:
            return None
        parent_id = found.id
    return found


def _apply_location_write(db: Session, owner_id: uuid.UUID, data: dict) -> None:
    """Resolve a create/update payload's location fields against
    the tree, in place. The tree picker sends location_id (the text
    is derived); legacy text writes (importer, API) find-or-create a
    top-level node by name — a text that IS an existing node's path
    resolves to that node rather than minting a strangely named
    root. An explicit location_id of None with no text unfiles."""
    has_id = "location_id" in data
    has_text = "location" in data
    if not has_id and not has_text:
        return
    if has_id and data["location_id"] is not None:
        node = get_location_node(db, owner_id, data["location_id"])
        if node is None:
            raise ToolValidationError("That location isn't yours.")
        data["location"] = location_path(owned_locations(db, owner_id), node)
        return
    if has_id and not has_text:
        data["location_id"] = None
        data["location"] = ""
        return
    text = (data.get("location") or "").strip()
    if not text:
        data["location_id"] = None
        data["location"] = ""
        return
    nodes = owned_locations(db, owner_id)
    node = _node_by_path(nodes, text) or next(
        (n for n in nodes if n.parent_id is None and n.name == text), None
    )
    if node is None:
        node = models.InventoryLocation(
            owner_id=owner_id, name=text, parent_id=None, sort_order=0
        )
        db.add(node)
        db.flush()
    data["location_id"] = node.id
    data["location"] = location_path(owned_locations(db, owner_id), node)


def location_text_for(db: Session, owner_id: uuid.UUID, location_id: uuid.UUID | None) -> str:
    if location_id is None:
        return ""
    node = get_location_node(db, owner_id, location_id)
    if node is None:
        return ""
    return location_path(owned_locations(db, owner_id), node)


# -- inline set pieces (Package B) --------------------------------------------------


def _validate_piece_rows(rows: list[dict]) -> None:
    """The set rules over a submitted piece list (the resulting
    state). Since 2026-10-25 every piece, core included, may carry
    its own price, so there is no price rule left to enforce here —
    the hook stays for the callers' shape (validate the whole list
    before anything saves)."""
    return None


def _sync_set_pieces(
    db: Session, owner_id: uuid.UUID, tool: models.Tool, rows: list[dict]
) -> None:
    """Make the set's pieces EXACTLY the submitted rows — the
    inline editor's one save. Rows with an id update that piece
    (files and history survive); rows without create; pieces absent
    from the list are deleted through the same guards + file
    retirement as a standalone piece delete. The caller validates
    first, so a rejected save changes nothing."""
    existing = {p.id: p for p in _list_set_pieces(db, tool.id)}
    keep: set[uuid.UUID] = set()
    for row in rows:
        row = dict(row)
        piece_id = row.pop("id", None)
        if piece_id is not None:
            piece = existing.get(piece_id)
            if piece is None:
                raise ToolValidationError(
                    "One of those pieces belongs to a different set."
                )
            for key, value in row.items():
                setattr(piece, key, value)
            keep.add(piece_id)
        else:
            piece = models.SetPiece(owner_id=owner_id, set_id=tool.id, **row)
            db.add(piece)
            db.flush()
            keep.add(piece.id)
    for piece_id, piece in existing.items():
        if piece_id not in keep:
            _run_delete_guards(db, owner_id, "piece", piece_id)
            journal.retire_record_files(
                db, owner_id, piece, entity_type="set_piece"
            )
            db.delete(piece)
    db.flush()


# -- field suggestions (Package B) --------------------------------------------------

_SUGGESTION_LIMIT = 200


def field_suggestions(db: Session, owner_id: uuid.UUID, field: str) -> list[str]:
    """The caller's OWN distinct values for a self-learning field —
    the type-ahead vocabulary. Strictly owner-scoped: another
    user's values never appear."""
    values: set[str] = set()
    if field in ("brand", "category"):
        column = {"brand": models.Tool.brand, "category": models.Tool.category}[field]
        bcolumn = {"brand": models.Battery.brand, "category": models.Battery.category}[field]
        values |= {
            v for (v,) in db.execute(
                select(column).where(models.Tool.owner_id == owner_id).distinct()
            ) if v
        }
        values |= {
            v for (v,) in db.execute(
                select(bcolumn).where(models.Battery.owner_id == owner_id).distinct()
            ) if v
        }
    elif field == "size":
        values |= {
            v for (v,) in db.execute(
                select(models.Tool.size).where(models.Tool.owner_id == owner_id).distinct()
            ) if v
        }
    elif field == "tag":
        values |= {
            v for (v,) in db.execute(
                select(models.Tag.name).where(models.Tag.owner_id == owner_id).distinct()
            ) if v
        }
    else:
        raise ToolValidationError(f"No suggestions for field: {field}")
    return sorted(values, key=str.lower)[:_SUGGESTION_LIMIT]


# -- bulk edit (Package B) ----------------------------------------------------------

BULK_ACTIONS = (
    "move_location",
    "set_dealer",
    "set_brand",
    "set_category",
    "add_tag",
    "set_standing",
    "delete",
)


def bulk_apply(
    db: Session,
    owner_id: uuid.UUID,
    *,
    items: list[tuple[str, uuid.UUID]],
    action: str,
    params: dict,
) -> dict:
    """One bulk operation over an explicit item selection. Every
    item is resolved and ownership-checked FIRST — a single
    foreign or missing id refuses the WHOLE operation, never a
    partial apply. Each item then mutates through the ORM, so the
    audit journal records one entry per item."""
    if action not in BULK_ACTIONS:
        raise ToolValidationError(f"Unknown bulk action: {action}")
    resolved: list[tuple[str, object]] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for kind, item_id in items:
        if (kind, item_id) in seen:
            continue
        seen.add((kind, item_id))
        record = (
            get_tool(db, owner_id, item_id)
            if kind == "tool"
            else get_battery(db, owner_id, item_id) if kind == "battery" else None
        )
        if record is None:
            raise ToolValidationError(
                "That selection includes an item that isn't yours — "
                "nothing was changed."
            )
        resolved.append((kind, record))
    if not resolved:
        raise ToolValidationError("Select at least one item.")

    if action == "move_location":
        location_id = params.get("location_id")
        if location_id is not None:
            location_id = uuid.UUID(str(location_id))
            if get_location_node(db, owner_id, location_id) is None:
                raise ToolValidationError("That location isn't yours.")
        text = location_text_for(db, owner_id, location_id)
        for _kind, record in resolved:
            record.location_id = location_id
            record.location = text
    elif action == "set_dealer":
        dealer_id = params.get("dealer_company_id")
        if dealer_id is not None:
            dealer_id = uuid.UUID(str(dealer_id))
        validate_dealer_company(db, owner_id, dealer_id)
        for _kind, record in resolved:
            record.dealer_company_id = dealer_id
    elif action == "set_brand":
        brand = str(params.get("brand") or "").strip()
        for _kind, record in resolved:
            record.brand = brand
    elif action == "set_category":
        category = str(params.get("category") or "").strip()
        for _kind, record in resolved:
            record.category = category
    elif action == "add_tag":
        tag_name = str(params.get("tag_name") or "").strip()
        if not tag_name:
            raise ToolValidationError("Name the tag to add.")
        tag = create_tag(db, owner_id, tag_name, "slate")
        for kind, record in resolved:
            id_column = (
                models.ItemTag.tool_id if kind == "tool" else models.ItemTag.battery_id
            )
            exists = db.scalar(
                select(models.ItemTag).where(
                    models.ItemTag.owner_id == owner_id,
                    models.ItemTag.item_kind == kind,
                    id_column == record.id,
                    models.ItemTag.tag_id == tag.id,
                )
            )
            if exists is None:
                link = models.ItemTag(
                    owner_id=owner_id, item_kind=kind, tag_id=tag.id
                )
                if kind == "tool":
                    link.tool_id = record.id
                else:
                    link.battery_id = record.id
                db.add(link)
    elif action == "set_standing":
        standing = str(params.get("standing") or "")
        if standing not in models.STANDINGS:
            raise ToolValidationError(f"Unknown standing: {standing}")
        if standing == models.STANDING_SOLD:
            # A sale is a LEDGER event (buyer, price, date), not a
            # bare standing flip — the Mark sold flow writes both.
            raise ToolValidationError(
                "Use Mark sold on the item itself — a sale records the "
                "buyer and price, not just the standing."
            )
        for _kind, record in resolved:
            apply_standing(record, standing)
    elif action == "delete":
        # Guards for the whole selection run BEFORE anything is
        # deleted, so a guarded item refuses the batch untouched.
        for kind, record in resolved:
            _run_delete_guards(db, owner_id, kind, record.id)
        for kind, record in resolved:
            if kind == "tool":
                delete_tool(db, owner_id, record.id)
            else:
                delete_battery(db, owner_id, record.id)
        return {
            "action": action,
            "affected": len(resolved),
            "items": [
                {"kind": kind, "id": str(record.id)} for kind, record in resolved
            ],
        }
    db.commit()
    return {
        "action": action,
        "affected": len(resolved),
        "items": [
            {"kind": kind, "id": str(record.id)} for kind, record in resolved
        ],
    }


def list_locations(db: Session, owner_id: uuid.UUID) -> list[str]:
    """The owner's location vocabulary for form autocomplete: every
    distinct non-empty location they've used on tools or batteries.
    Location itself stays free text — this only suggests."""
    tool_locations = db.scalars(
        select(models.Tool.location).where(
            models.Tool.owner_id == owner_id, models.Tool.location != ""
        )
    )
    battery_locations = db.scalars(
        select(models.Battery.location).where(
            models.Battery.owner_id == owner_id, models.Battery.location != ""
        )
    )
    return sorted(set(tool_locations) | set(battery_locations))


# -- QR bin labels (blueprint §18) -------------------------------------------
#
# The print surface's data seam: resolve a requested selection of
# item refs into label rows, and count items per location for bin
# labels. Owner-scoped end to end — a ref that isn't the caller's
# (foreign, deleted, malformed) never resolves and is only COUNTED,
# so the existence of other people's items can't leak through it.


def parse_label_refs(raw: str) -> tuple[list[tuple[str, uuid.UUID]], int]:
    """Parse the /labels `items` parameter: comma-separated
    ``tool:<uuid>`` / ``battery:<uuid>`` refs. Returns the valid
    refs (deduplicated, request order) and the malformed count."""
    refs: list[tuple[str, uuid.UUID]] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    malformed = 0
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        kind, sep, raw_id = entry.partition(":")
        parsed: uuid.UUID | None = None
        if sep and kind in ("tool", "battery"):
            try:
                parsed = uuid.UUID(raw_id.strip())
            except ValueError:
                parsed = None
        if parsed is None:
            malformed += 1
            continue
        ref = (kind, parsed)
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs, malformed


def resolve_label_items(
    db: Session, owner_id: uuid.UUID, raw_items: str
) -> tuple[list[dict], int]:
    """Resolve a label selection to label rows + a skipped count.

    A row carries exactly what a label face prints (name, brand,
    model, serial, location) plus the canonical ``qr_path`` the QR
    encodes. Sets are tools: one label for the set record itself.
    Skipped = malformed refs + refs that aren't this owner's items,
    deliberately indistinguishable."""
    refs, skipped = parse_label_refs(raw_items)
    tool_ids = [item_id for kind, item_id in refs if kind == "tool"]
    battery_ids = [item_id for kind, item_id in refs if kind == "battery"]
    tools = {
        tool.id: tool
        for tool in db.scalars(
            select(models.Tool).where(
                models.Tool.owner_id == owner_id,
                models.Tool.id.in_(tool_ids),
            )
        )
    } if tool_ids else {}
    batteries = {
        battery.id: battery
        for battery in db.scalars(
            select(models.Battery).where(
                models.Battery.owner_id == owner_id,
                models.Battery.id.in_(battery_ids),
            )
        )
    } if battery_ids else {}
    labels: list[dict] = []
    for kind, item_id in refs:
        record = (tools if kind == "tool" else batteries).get(item_id)
        if record is None:
            skipped += 1
            continue
        labels.append(
            {
                "kind": kind,
                "id": record.id,
                "name": record.name,
                "brand": record.brand,
                "model": record.model,
                "serial_number": record.serial_number,
                "location": record.location,
                "is_set": bool(getattr(record, "is_set", False)),
                "qr_path": f"/inventory/{kind}/{record.id}",
            }
        )
    return labels, skipped


def location_label_counts(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """Items per distinct location, for bin labels: top-level tools
    (attached set addons live inside their set and don't count
    separately — the same rule the inventory list shows) plus all
    batteries. Empty locations are not bins and drop out."""
    counts: dict[str, int] = {}
    for location, n in db.execute(
        select(models.Tool.location, func.count())
        .where(
            models.Tool.owner_id == owner_id,
            models.Tool.location != "",
            models.Tool.attached_to_set_id.is_(None),
        )
        .group_by(models.Tool.location)
    ):
        counts[location] = counts.get(location, 0) + n
    for location, n in db.execute(
        select(models.Battery.location, func.count())
        .where(
            models.Battery.owner_id == owner_id,
            models.Battery.location != "",
        )
        .group_by(models.Battery.location)
    ):
        counts[location] = counts.get(location, 0) + n
    return [
        {"location": location, "count": counts[location]}
        for location in sorted(counts)
    ]


# -- sets ----------------------------------------------------------------------
#
# Owner's model (2026-10-18): a set IS a tool record (own name, own
# set part number via its model field, own price) whose CORE pieces
# each carry their own part number, and whose ADDON pieces (bought
# later) keep their own part numbers AND prices. Since 2026-10-25 a
# CORE piece may carry its own price too — the piece's own figure,
# never part of the set's totals (only addon prices join those).
# Addons may also be whole standalone tools attached into the set.
# The inventory list shows the SET as one row; pieces and attached
# tools never appear top-level.
#
# resolve_set_members is the ONE member-resolution service: tier
# sharing, peer sharing, borrowing and (later) claims all consume a
# set's structure through it, passing the user's stored/asked answer
# to "include the addon pieces too?".

# Piece statuses that remove a piece from totals and member lists
# (it stays in history — the row is never deleted by a status).
_GONE_STATUSES = ("sold", "removed")


def _list_set_pieces(db: Session, set_id: uuid.UUID) -> list[models.SetPiece]:
    return list(
        db.scalars(
            select(models.SetPiece)
            .where(models.SetPiece.set_id == set_id)
            .order_by(models.SetPiece.sort_order, models.SetPiece.created_at)
        )
    )


def _attached_tools(db: Session, set_tool: models.Tool) -> list[models.Tool]:
    return list(
        db.scalars(
            select(models.Tool)
            .where(models.Tool.attached_to_set_id == set_tool.id)
            .order_by(models.Tool.created_at)
        )
    )


def _set_totals(
    set_tool: models.Tool,
    included_pieces: list[models.SetPiece],
    included_attached: list[models.Tool],
) -> tuple[Decimal, Decimal]:
    """(price_total, replacement_total) for a set over its INCLUDED
    members: the set's own per-unit price x its quantity, plus addon
    pieces' prices, plus attached tools' totals (their price x
    their quantity). Gone pieces (sold/removed) never contribute —
    callers pass the filtered lists. A core piece's own price (when
    recorded) never contributes either — it is the piece's own
    cost/replacement figure, not set money."""
    price = (set_tool.purchase_price or Decimal("0")) * (set_tool.quantity or 1)
    replacement = (set_tool.replacement_cost or Decimal("0")) * (
        set_tool.quantity or 1
    )
    for piece in included_pieces:
        # Gone pieces (sold/removed) never contribute money, even
        # when a caller passes the full structure for display.
        if (
            piece.kind == "addon"
            and piece.price is not None
            and piece.status not in _GONE_STATUSES
        ):
            price += piece.price
    for tool in included_attached:
        price += (tool.purchase_price or Decimal("0")) * (tool.quantity or 1)
        replacement += (tool.replacement_cost or Decimal("0")) * (
            tool.quantity or 1
        )
    return _money_total(price), _money_total(replacement)


def resolve_set_members(
    db: Session,
    set_tool: models.Tool,
    include_addons: bool,
    include_gone: bool = False,
) -> dict:
    """THE shared set-membership service. Core pieces are ALWAYS in;
    addon pieces and attached tools ride only when include_addons.
    Gone pieces (sold/removed) are excluded unless include_gone
    (data export passes True — a backup carries the full structure;
    claims will read stored choices through here too).

    Returns ORM rows plus money totals computed over exactly the
    included members, so every consumer prices a set the same way.
    """
    pieces = _list_set_pieces(db, set_tool.id)
    if not include_gone:
        pieces = [p for p in pieces if p.status not in _GONE_STATUSES]
    core = [p for p in pieces if p.kind == "core"]
    addons = [p for p in pieces if p.kind == "addon"] if include_addons else []
    attached = _attached_tools(db, set_tool) if include_addons else []
    price_total, replacement_total = _set_totals(
        set_tool, core + addons, attached
    )
    return {
        "set": set_tool,
        "include_addons": include_addons,
        "core_pieces": core,
        "addon_pieces": addons,
        "attached_tools": attached,
        "price_total": price_total,
        "replacement_total": replacement_total,
    }


def item_tag_names_bulk(
    db: Session, owner_id: uuid.UUID
) -> dict[tuple[str, uuid.UUID], list[str]]:
    """Every tag name of every item the owner has, in ONE query —
    {(kind, item_id): [names]}. The batch twin of get_item_tags
    for whole-vault consumers (reports at scale, step-4 fix D5):
    the per-item version costs a query per row."""
    rows = db.execute(
        select(
            models.ItemTag.item_kind,
            models.ItemTag.tool_id,
            models.ItemTag.battery_id,
            models.Tag.name,
        )
        .join(models.Tag, models.Tag.id == models.ItemTag.tag_id)
        .where(models.ItemTag.owner_id == owner_id)
        .order_by(models.Tag.name)
    )
    out: dict[tuple[str, uuid.UUID], list[str]] = {}
    for kind, tool_id, battery_id, name in rows:
        item_id = tool_id if kind == "tool" else battery_id
        if item_id is not None:
            out.setdefault((kind, item_id), []).append(name)
    return out


def resolve_set_members_bulk(
    db: Session,
    set_tools: list[models.Tool],
    include_addons: bool = True,
) -> dict[uuid.UUID, dict]:
    """resolve_set_members for MANY sets in two queries total
    (pieces + attached tools), grouped in Python — the reports
    path at vault scale (step-4 fix D5). Same composition rules
    (gone pieces out, addons/attached ride include_addons) and the
    same _set_totals math as the single-set version."""
    out: dict[uuid.UUID, dict] = {}
    if not set_tools:
        return out
    set_ids = [t.id for t in set_tools]
    pieces_by_set: dict[uuid.UUID, list[models.SetPiece]] = {}
    for piece in db.scalars(
        select(models.SetPiece)
        .where(models.SetPiece.set_id.in_(set_ids))
        .order_by(models.SetPiece.sort_order, models.SetPiece.created_at)
    ):
        pieces_by_set.setdefault(piece.set_id, []).append(piece)
    attached_by_set: dict[uuid.UUID, list[models.Tool]] = {}
    for attached in db.scalars(
        select(models.Tool)
        .where(models.Tool.attached_to_set_id.in_(set_ids))
        .order_by(models.Tool.created_at)
    ):
        attached_by_set.setdefault(attached.attached_to_set_id, []).append(attached)
    for tool in set_tools:
        pieces = [
            p
            for p in pieces_by_set.get(tool.id, [])
            if p.status not in _GONE_STATUSES
        ]
        core = [p for p in pieces if p.kind == "core"]
        addons = [p for p in pieces if p.kind == "addon"] if include_addons else []
        attached = attached_by_set.get(tool.id, []) if include_addons else []
        price_total, replacement_total = _set_totals(tool, core + addons, attached)
        out[tool.id] = {
            "set": tool,
            "include_addons": include_addons,
            "core_pieces": core,
            "addon_pieces": addons,
            "attached_tools": attached,
            "price_total": price_total,
            "replacement_total": replacement_total,
        }
    return out


def serialize_set_piece(piece: models.SetPiece) -> dict:
    return {
        "id": piece.id,
        "set_id": piece.set_id,
        "kind": piece.kind,
        "name": piece.name,
        "part_number": piece.part_number,
        "serial_number": piece.serial_number,
        "status": piece.status,
        # Repair standing (maintenance build): read by the set
        # panel's piece badges; the actions live in the maintenance
        # module's own endpoints.
        "repair_state": piece.repair_state,
        "repair_problem": piece.repair_problem,
        "price": piece.price,
        "purchase_date": piece.purchase_date,
        "sort_order": piece.sort_order,
        "attachments": _serialize_attachments(piece),
        "created_at": piece.created_at,
        "updated_at": piece.updated_at,
    }


def _attached_tool_ref(tool: models.Tool) -> dict:
    return {
        "id": tool.id,
        "name": tool.name,
        "brand": tool.brand,
        "model": tool.model,
        "serial_number": tool.serial_number,
        "quantity": tool.quantity or 1,
        "purchase_price": tool.purchase_price,
        "purchase_total": (
            _money_total(tool.purchase_price * (tool.quantity or 1))
            if tool.purchase_price is not None
            else None
        ),
        "replacement_cost": tool.replacement_cost,
    }


def _require_set(
    db: Session, owner_id: uuid.UUID, set_id: uuid.UUID
) -> models.Tool:
    tool = get_tool(db, owner_id, set_id)
    if tool is None:
        raise ToolValidationError("That set does not belong to you.")
    if not tool.is_set:
        raise ToolValidationError(
            "That item isn't a set — mark it as a set before adding pieces."
        )
    return tool


def add_set_piece(
    db: Session, owner_id: uuid.UUID, set_id: uuid.UUID, payload: schemas.SetPieceCreate
) -> models.SetPiece:
    set_tool = _require_set(db, owner_id, set_id)
    data = payload.model_dump()
    piece = models.SetPiece(owner_id=owner_id, set_id=set_tool.id, **data)
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece


def get_set_piece(
    db: Session, owner_id: uuid.UUID, piece_id: uuid.UUID
) -> models.SetPiece | None:
    piece = db.get(models.SetPiece, piece_id)
    if piece is None or piece.owner_id != owner_id:
        return None
    return piece


def update_set_piece(
    db: Session,
    owner_id: uuid.UUID,
    piece_id: uuid.UUID,
    payload: schemas.SetPieceUpdate,
) -> models.SetPiece | None:
    piece = get_set_piece(db, owner_id, piece_id)
    if piece is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "repair_state" in data:
        # A piece follows the item rule (merge, 2026-11-04): mark
        # broken / back in service are the owner's own steps; the
        # move INTO in_repair belongs to the claim lifecycle alone
        # (a claim sends the piece out), never to a bare edit.
        target = data["repair_state"]
        if target == models.STANDING_IN_REPAIR and piece.repair_state != target:
            raise ToolValidationError(
                "A piece goes out for repair through its claim — "
                "start the claim and send it from there."
            )
        if target == models.STANDING_IN_SERVICE:
            # Back in service clears the problem text, exactly as
            # apply_standing does for whole items.
            data["repair_problem"] = ""
    for key, value in data.items():
        setattr(piece, key, value)
    db.commit()
    db.refresh(piece)
    return piece


def delete_set_piece(db: Session, owner_id: uuid.UUID, piece_id: uuid.UUID) -> bool:
    piece = get_set_piece(db, owner_id, piece_id)
    if piece is None:
        return False
    _run_delete_guards(db, owner_id, "piece", piece_id)
    # Files tombstoned for the retention window (audit trail).
    journal.retire_record_files(db, owner_id, piece, entity_type="set_piece")
    db.delete(piece)
    db.commit()
    return True


def attach_tool_to_set(
    db: Session, owner_id: uuid.UUID, set_id: uuid.UUID, tool_id: uuid.UUID
) -> models.Tool:
    """Attach one of the owner's standalone tools INTO a set as an
    addon. The tool keeps its own prices (they join the set's
    totals), vanishes from the top-level list and the billing count,
    and detaches back to standalone cleanly. No nesting: a set can't
    be attached into a set, and an attached tool can't re-attach."""
    if get_tool(db, owner_id, set_id) is None:
        # A foreign (or missing) set: the non-leaking 404, exactly
        # as a foreign tool below (E-02) — never a 422 that
        # confirms the set exists in someone else's vault.
        raise ToolNotFoundError("Tool not found")
    set_tool = _require_set(db, owner_id, set_id)
    tool = get_tool(db, owner_id, tool_id)
    if tool is None:
        raise ToolNotFoundError("Tool not found")
    if tool.id == set_tool.id:
        raise ToolValidationError("A set can't be attached to itself.")
    if tool.is_set:
        raise ToolValidationError(
            "A set can't be attached into another set — detach its pieces first."
        )
    if tool.attached_to_set_id is not None:
        raise ToolValidationError(
            "That tool is already attached to a set — detach it first."
        )
    tool.attached_to_set_id = set_tool.id
    db.commit()
    db.refresh(tool)
    return tool


def _validate_attach_ids(
    db: Session,
    owner_id: uuid.UUID,
    set_id: uuid.UUID | None,
    tool_ids: list[uuid.UUID],
) -> None:
    """The build-a-set rules over a submitted attached-tools list,
    judged BEFORE anything mutates (one form, one save): every id
    must be one of the owner's tools, not a set, not the set itself,
    and either standalone or already attached to THIS set. The same
    rules attach_tool_to_set enforces one tool at a time."""
    for tool_id in dict.fromkeys(tool_ids):
        tool = get_tool(db, owner_id, tool_id)
        if tool is None:
            raise ToolValidationError(
                "One of those tools does not belong to you."
            )
        if set_id is not None and tool.id == set_id:
            raise ToolValidationError("A set can't be attached to itself.")
        if tool.is_set:
            raise ToolValidationError(
                "A set can't be attached into another set — detach its pieces first."
            )
        if (
            tool.attached_to_set_id is not None
            and tool.attached_to_set_id != set_id
        ):
            raise ToolValidationError(
                "One of those tools is already attached to a different "
                "set — detach it first."
            )


def _apply_attach_sync(
    db: Session,
    owner_id: uuid.UUID,
    set_tool: models.Tool,
    tool_ids: list[uuid.UUID],
) -> None:
    """Make the set's attached tools EXACTLY the submitted list
    (build-a-set from inventory, owner 2026-10-25): newly listed
    tools fold in with all their data intact — one inventory line
    for the set, the folded tools stop listing/counting standalone —
    and tools no longer listed detach back to standalone through
    the same guards as a manual detach."""
    desired = set(tool_ids)
    current = _attached_tools(db, set_tool)
    current_ids = {t.id for t in current}
    for tool in current:
        if tool.id not in desired:
            _run_delete_guards(db, owner_id, "detach", tool.id)
            tool.attached_to_set_id = None
    for tool_id in desired - current_ids:
        tool = get_tool(db, owner_id, tool_id)
        if tool is not None:
            tool.attached_to_set_id = set_tool.id
    db.flush()


def detach_tool(
    db: Session, owner_id: uuid.UUID, tool_id: uuid.UUID
) -> models.Tool | None:
    """Detach an addon tool back to standalone (its prices intact)."""
    tool = get_tool(db, owner_id, tool_id)
    if tool is None:
        return None
    _run_delete_guards(db, owner_id, "detach", tool_id)
    tool.attached_to_set_id = None
    db.commit()
    db.refresh(tool)
    return tool


# -- lost/stolen report records (gap wave 1, 2026-10-20) -------------------------
#
# The standing (lost/stolen on the item) says WHAT state an item
# is in; an ItemLossReport carries the paper trail — police
# report number/department, insurer + claim number on file, the
# date reported, notes. One ACTIVE report per item; recovering
# closes it (recovered_date) and keeps it as history. Claims keep
# their own police block — this record is the ITEM's, and the two
# never write each other.


def replacement_name(db: Session, record) -> str | None:
    """The display name of the item this record was replaced by.
    The stored id is a PLAIN column (no FK): it may name a tool
    or a battery, and it may dangle — the replacement can be
    deleted later, in which case the marker keeps its date and
    simply loses the name/link."""
    target_id = record.replaced_by_item_id
    if target_id is None:
        return None
    for model in (models.Tool, models.Battery):
        target = db.get(model, target_id)
        if target is not None and target.owner_id == record.owner_id:
            return target.name
    return None


def _replaced_record(db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID):
    if item_kind == "tool":
        return get_tool(db, owner_id, item_id)
    if item_kind == "battery":
        return get_battery(db, owner_id, item_id)
    return None


def mark_replaced(
    db: Session,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    *,
    on_date: date | None = None,
    replaced_by_item_id: uuid.UUID | None = None,
    note: str = "",
):
    """Mark an item replaced (asset history, 2026-10-20): stamp
    the date (today when the owner doesn't pick one), the
    optional replacement item, and an optional note. The item
    is NOT retired by this — it stays in the active set exactly
    as before (the owner may still need it for a claim); the
    marker is history, not a state change. Returns the record,
    or None when the item isn't the owner's. The write rides
    the change journal like every other item edit."""
    record = _replaced_record(db, owner_id, item_kind, item_id)
    if record is None:
        return None
    if replaced_by_item_id is not None:
        if replaced_by_item_id == item_id:
            raise ToolValidationError("An item can't replace itself.")
        target = get_tool(db, owner_id, replaced_by_item_id) or get_battery(
            db, owner_id, replaced_by_item_id
        )
        if target is None:
            raise ToolValidationError(
                "That replacement item isn't in your vault."
            )
    record.replaced_on = on_date or date.today()
    record.replaced_by_item_id = replaced_by_item_id
    record.replaced_note = (note or "").strip()
    db.commit()
    db.refresh(record)
    return record


def clear_replaced(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
):
    """Un-replace: clear the marker (the journal keeps the
    milestone; the timeline's replaced event goes with the
    fields, since the feed reads the record, not the journal,
    for this event)."""
    record = _replaced_record(db, owner_id, item_kind, item_id)
    if record is None:
        return None
    record.replaced_on = None
    record.replaced_by_item_id = None
    record.replaced_note = ""
    db.commit()
    db.refresh(record)
    return record


def serialize_loss_report(
    row: models.ItemLossReport, documents: list[dict] | None = None
) -> dict:
    return {
        "id": row.id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "status": row.status,
        "standing": row.standing,
        "reported_date": row.reported_date,
        "police_report_number": row.police_report_number,
        "police_department": row.police_department,
        "insurer_name": row.insurer_name,
        "claim_number": row.claim_number,
        "notes": row.notes,
        "recovered_date": row.recovered_date,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        # The report's own documents (already-serialized item
        # attachments carrying this report's marker); callers that
        # don't resolve them (writes, the data export) get [].
        "documents": documents if documents is not None else [],
    }


def _loss_item(db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID):
    """The owned item a report hangs off (None = not found / not
    yours — routes answer 404, never an existence leak)."""
    if item_kind == "tool":
        return get_tool(db, owner_id, item_id)
    if item_kind == "battery":
        return get_battery(db, owner_id, item_id)
    return None


def list_loss_reports(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[models.ItemLossReport]:
    return list(
        db.scalars(
            select(models.ItemLossReport)
            .where(
                models.ItemLossReport.owner_id == owner_id,
                models.ItemLossReport.item_kind == item_kind,
                models.ItemLossReport.item_id == item_id,
            )
            .order_by(
                models.ItemLossReport.created_at.desc(),
                models.ItemLossReport.id.desc(),
            )
        )
    )


def active_loss_report(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> models.ItemLossReport | None:
    return db.scalars(
        select(models.ItemLossReport).where(
            models.ItemLossReport.owner_id == owner_id,
            models.ItemLossReport.item_kind == item_kind,
            models.ItemLossReport.item_id == item_id,
            models.ItemLossReport.status == "active",
        )
    ).first()


def list_all_loss_reports(
    db: Session, owner_id: uuid.UUID
) -> list[models.ItemLossReport]:
    """Every report the owner has ever filed (active + history) —
    the data export's read."""
    return list(
        db.scalars(
            select(models.ItemLossReport)
            .where(models.ItemLossReport.owner_id == owner_id)
            .order_by(models.ItemLossReport.created_at.desc())
        )
    )


def latest_loss_reports(
    db: Session, owner_id: uuid.UUID
) -> dict[tuple[str, uuid.UUID], models.ItemLossReport]:
    """{(kind, item_id): the item's MOST RECENT report} — the
    reports module's bulk read (one query per build, the D5 batch
    pattern): a report column shows the latest paper trail,
    active or recovered."""
    rows = db.scalars(
        select(models.ItemLossReport)
        .where(models.ItemLossReport.owner_id == owner_id)
        .order_by(models.ItemLossReport.created_at.desc())
    )
    latest: dict[tuple[str, uuid.UUID], models.ItemLossReport] = {}
    for row in rows:
        latest.setdefault((row.item_kind, row.item_id), row)
    return latest


_LOSS_DETAIL_FIELDS = (
    "reported_date",
    "police_report_number",
    "police_department",
    "insurer_name",
    "claim_number",
    "notes",
)


def create_loss_report(
    db: Session,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    data: dict,
) -> models.ItemLossReport:
    """Open a report on an item: applies the lost/stolen standing
    (the ONE writer, apply_standing) and records the paper trail
    in the same commit. Refuses when an active report already
    exists — edit that one, or recover first. Commits."""
    item = _loss_item(db, owner_id, item_kind, item_id)
    if item is None:
        raise ToolValidationError("That item isn't available.")
    standing = data.get("standing") or "lost"
    if standing not in (models.STANDING_LOST, models.STANDING_STOLEN):
        raise ToolValidationError("A report is for a lost or stolen item.")
    if active_loss_report(db, owner_id, item_kind, item_id) is not None:
        raise ToolValidationError(
            "This item already has an open lost/stolen report — "
            "edit it, or mark the item recovered first."
        )
    apply_standing(item, standing)
    row = models.ItemLossReport(
        owner_id=owner_id,
        item_kind=item_kind,
        item_id=item_id,
        status="active",
        standing=standing,
        reported_date=data.get("reported_date") or date.today(),
        police_report_number=(data.get("police_report_number") or "")[:100],
        police_department=(data.get("police_department") or "")[:200],
        insurer_name=(data.get("insurer_name") or "")[:200],
        claim_number=(data.get("claim_number") or "")[:100],
        notes=data.get("notes") or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_loss_report(
    db: Session, owner_id: uuid.UUID, report_id: uuid.UUID
) -> models.ItemLossReport | None:
    row = db.get(models.ItemLossReport, report_id)
    if row is None or row.owner_id != owner_id:
        return None
    return row


def update_loss_report(
    db: Session, owner_id: uuid.UUID, report_id: uuid.UUID, data: dict
) -> models.ItemLossReport | None:
    """Edit the paper-trail fields (active or historical — a
    correction to a closed report is still the owner's record to
    fix). Status and dates of recovery move only through
    recover_loss_report. Commits."""
    row = get_loss_report(db, owner_id, report_id)
    if row is None:
        return None
    for field in _LOSS_DETAIL_FIELDS:
        if field in data and data[field] is not None:
            setattr(row, field, data[field])
    db.commit()
    db.refresh(row)
    return row


def recover_loss_report(
    db: Session,
    owner_id: uuid.UUID,
    report_id: uuid.UUID,
    recovered_date: date | None = None,
) -> models.ItemLossReport | None:
    """Mark recovered: the report closes WITH its history intact
    (recovered_date stamped, row kept), and the item's standing
    flips back to in_service through apply_standing — but only
    when the item is still standing lost/stolen (a standing the
    owner changed by another path is theirs to keep). Commits."""
    row = get_loss_report(db, owner_id, report_id)
    if row is None:
        return None
    if row.status != "active":
        raise ToolValidationError("That report is already closed.")
    row.status = "recovered"
    row.recovered_date = recovered_date or date.today()
    item = _loss_item(db, owner_id, row.item_kind, row.item_id)
    if item is not None and item.standing in (
        models.STANDING_LOST,
        models.STANDING_STOLEN,
    ):
        apply_standing(item, models.STANDING_IN_SERVICE)
    db.commit()
    db.refresh(row)
    return row


# -- category manager (gap wave 1, 2026-10-20) -----------------------------------
#
# Categories live as free text on items; the manager gives that
# vocabulary a control surface (the taxonomy manager the app had):
# list with counts, create (registry row, so a category can exist
# empty), rename (cascades onto every item of BOTH kinds), merge
# (items move, the source disappears), delete (items detach to
# uncategorized — items are NEVER deleted). Identity is the
# importer's normalized key: "Power Tools" and "power tools" are
# ONE category, and the manager groups legacy spelling variants
# under it instead of pretending they're different categories.

def _category_key(name: str) -> str:
    from app.modules.inventory.matching import normalize_match_value

    return normalize_match_value(name or "")


def _category_universe(
    db: Session, owner_id: uuid.UUID
) -> dict[str, dict]:
    """{normalized_key: {name, item_count, registered}} across the
    registry + every spelling variant actually carried by items.
    The display name prefers the registry spelling, else the
    most-carried item spelling."""
    universe: dict[str, dict] = {}
    for row in db.scalars(
        select(models.InventoryCategory).where(
            models.InventoryCategory.owner_id == owner_id
        )
    ):
        universe[row.normalized] = {
            "name": row.name,
            "item_count": 0,
            "registered": True,
            "starred": row.starred,
            "system_key": row.system_key,
            "spellings": {},
        }
    for model in (models.Tool, models.Battery):
        for (value,) in db.execute(
            select(model.category).where(
                model.owner_id == owner_id, model.category != ""
            )
        ).all():
            key = _category_key(value)
            if not key:
                continue
            entry = universe.setdefault(
                key,
                {"name": value, "item_count": 0, "registered": False,
                 "starred": False, "system_key": None, "spellings": {}},
            )
            entry["item_count"] += 1
            entry["spellings"][value] = entry["spellings"].get(value, 0) + 1
    for entry in universe.values():
        if not entry["registered"] and entry["spellings"]:
            entry["name"] = max(
                entry["spellings"].items(), key=lambda kv: kv[1]
            )[0]
        entry.pop("spellings", None)
    return universe


def list_categories(db: Session, owner_id: uuid.UUID) -> list[dict]:
    universe = _category_universe(db, owner_id)
    # Order (owner spec 2026-10-25): the preinstalled starters
    # first, in seed order — the Inventory view row reads this
    # list top to bottom, so a fresh row is All · Batteries ·
    # Hand Tools · Power Tools · Pneumatic Tools — then the
    # owner's own categories alphabetically, as before.
    return sorted(
        (
            {
                "name": entry["name"],
                "item_count": entry["item_count"],
                "registered": entry["registered"],
                "starred": entry["starred"],
                "preinstalled": entry["system_key"] is not None,
                "system_key": entry["system_key"],
            }
            for entry in universe.values()
        ),
        key=lambda row: (
            STARTER_ORDER.get(row["system_key"], len(STARTER_ORDER)),
            row["name"].lower(),
        ),
    )


def _category_row(
    db: Session, owner_id: uuid.UUID, key: str
) -> models.InventoryCategory | None:
    return db.scalars(
        select(models.InventoryCategory).where(
            models.InventoryCategory.owner_id == owner_id,
            models.InventoryCategory.normalized == key,
        )
    ).first()


# -- preinstalled starter categories (owner spec 2026-10-25) ------------------
#
# Every account carries four starter categories — Batteries,
# Hand Tools, Power Tools, Pneumatic Tools — permanent and
# starred by default, so the Inventory view row (All + starred
# categories + Sold) starts populated. The seed is idempotent
# and ADOPTIVE: a category the owner already has under a
# starter's name (either shipped locale's spelling, in any
# case/punctuation folding) is marked as that starter instead
# of duplicated. Seed stars are system-granted: they set the
# flag directly, never through the capped star path — but they
# count toward the owner's 5 like any other star afterwards.

# (system_key, {locale: display name}) in seed/row order.
STARTER_CATEGORIES: tuple[tuple[str, dict[str, str]], ...] = (
    ("batteries", {"en": "Batteries", "es": "Baterías"}),
    ("hand_tools", {"en": "Hand Tools", "es": "Herramientas manuales"}),
    ("power_tools", {"en": "Power Tools", "es": "Herramientas eléctricas"}),
    ("pneumatic_tools", {"en": "Pneumatic Tools", "es": "Herramientas neumáticas"}),
)

STARTER_ORDER: dict[str, int] = {
    key: rank for rank, (key, _names) in enumerate(STARTER_CATEGORIES)
}

# Legacy spellings a starter may be adopted from, beyond its two
# shipped names. Battery records defaulted to the category text
# "Battery" (singular) for years — those items belong to the
# Batteries starter, and the adoption REWRITES them onto the
# canonical name (the battery reconciliation).
_STARTER_LEGACY_KEYS: dict[str, tuple[str, ...]] = {
    "batteries": ("battery",),
}


def _starter_names(system_key: str) -> dict[str, str]:
    for key, names in STARTER_CATEGORIES:
        if key == system_key:
            return names
    raise KeyError(system_key)


def _starter_display_name(system_key: str, locale: str | None) -> str:
    names = _starter_names(system_key)
    return names.get(locale or "", names["en"])


def _starter_adoption_keys(system_key: str) -> list[str]:
    """Every normalized key that already MEANS this starter:
    both shipped spellings plus the legacy ones."""
    keys = [
        _category_key(name)
        for name in _starter_names(system_key).values()
    ]
    keys.extend(_STARTER_LEGACY_KEYS.get(system_key, ()))
    return keys


def ensure_starter_categories(
    db: Session, owner_id: uuid.UUID, locale: str | None = None
) -> bool:
    """Seed the four starter categories for one owner (starred,
    preinstalled). Idempotent: a starter whose row already
    carries its system_key is left exactly as the owner has it —
    in particular an unstarred starter STAYS unstarred (the seed
    fills gaps, it never overrides the owner). Returns True when
    anything changed. Commits on change.

    Runs at account creation (core's one creation path, so
    password and social signups alike) and was run once for the
    accounts that predate it. It is deliberately NOT run on
    category-list reads: no read in this codebase performs lazy
    writes, and the manager's contract is that the list shows
    exactly what the owner's operations made it."""
    if locale is None:
        from app.modules.core import models as core_models

        user = db.get(core_models.User, owner_id)
        locale = user.locale if user is not None else ""
    rows = db.scalars(
        select(models.InventoryCategory).where(
            models.InventoryCategory.owner_id == owner_id
        )
    ).all()
    by_system = {row.system_key: row for row in rows if row.system_key}
    by_key = {row.normalized: row for row in rows}
    # The universe (registry + item-carried names) is computed
    # once, up front: adoption has to see categories that live
    # only on items, in either shipped spelling.
    universe = _category_universe(db, owner_id)
    changed = False
    # The battery reconciliation runs FIRST, on its own: items
    # filed under the legacy singular "Battery" belong to the
    # Batteries starter whatever else the account holds, so they
    # are rewritten onto the name that starter will carry (an
    # existing starter-name row's own spelling wins; otherwise
    # the canonical seeded name), and a leftover registry row
    # under the legacy spelling is folded away — its items are
    # already moved, and the starter itself carries the star.
    legacy_key = _STARTER_LEGACY_KEYS["batteries"][0]
    if legacy_key in universe:
        target_name = _starter_display_name("batteries", locale)
        for key in _starter_adoption_keys("batteries"):
            existing = by_key.get(key)
            if existing is not None and key != legacy_key:
                target_name = existing.name
                break
        moved = _rewrite_category(db, owner_id, legacy_key, target_name)
        legacy_row = by_key.pop(legacy_key, None)
        if legacy_row is not None:
            db.delete(legacy_row)
            db.flush()
        changed = changed or moved > 0 or legacy_row is not None
    for system_key, _names in STARTER_CATEGORIES:
        if system_key in by_system:
            continue
        canonical = _starter_display_name(system_key, locale)
        canonical_key = _category_key(canonical)
        adopted_key = next(
            (
                key
                for key in _starter_adoption_keys(system_key)
                if key in by_key or (universe and key in universe)
            ),
            None,
        )
        if adopted_key is None:
            row = models.InventoryCategory(
                owner_id=owner_id,
                name=canonical,
                normalized=canonical_key,
                starred=True,
                system_key=system_key,
            )
            db.add(row)
            db.flush()
            by_key[canonical_key] = row
            changed = True
            continue
        # Adopt what the owner already has under this starter's
        # name — never a duplicate.
        row = by_key.get(adopted_key)
        if row is None:
            # The category lives only on items: register it under
            # the canonical spelling (or the spelling the items
            # carry, for the shipped names) so the flags have a
            # row to live on.
            display = (
                canonical
                if adopted_key in _STARTER_LEGACY_KEYS.get(system_key, ())
                else universe[adopted_key]["name"]
            )
            row = models.InventoryCategory(
                owner_id=owner_id,
                name=display,
                normalized=_category_key(display),
                starred=True,
                system_key=system_key,
            )
            db.add(row)
            db.flush()
            by_key[row.normalized] = row
        else:
            row.system_key = system_key
            row.starred = True
        changed = True
    if changed:
        db.commit()
    return changed


# -- starred categories (owner spec 2026-10-24) ------------------------------
#
# The owner's shortcut set: starred categories surface as links
# in the Inventory view row. The cap is 5 per owner (owner spec
# 2026-10-25, cut from 10 so the row fits on one line),
# enforced HERE, on the server — the UI's counter and tooltip
# are courtesies on top of this rule, never the rule itself.

STAR_LIMIT = 5


def _starred_count(db: Session, owner_id: uuid.UUID) -> int:
    return len(
        db.scalars(
            select(models.InventoryCategory).where(
                models.InventoryCategory.owner_id == owner_id,
                models.InventoryCategory.starred.is_(True),
            )
        ).all()
    )


def _try_star(
    db: Session, owner_id: uuid.UUID, row: models.InventoryCategory
) -> bool:
    """Star a registry row when the cap allows. Returns False
    when the cap is already full (the row stays unstarred).
    Does NOT commit — the caller's operation does."""
    if row.starred:
        return True
    if _starred_count(db, owner_id) >= STAR_LIMIT:
        return False
    row.starred = True
    return True


def set_category_star(
    db: Session, owner_id: uuid.UUID, name: str, starred: bool
) -> dict:
    """Star or unstar a category (the Categories & tags page's
    star toggle). Starring registers a name that lives only on
    items, so the flag has a row to live on. Starring past the
    cap raises StarLimitReached; un-starring always succeeds,
    including for a name with no registry row (already unstarred:
    a no-op). Commits."""
    key = _category_key(name or "")
    universe = _category_universe(db, owner_id)
    if key not in universe:
        raise ToolValidationError("That category isn't available.")
    entry = universe[key]
    row = _category_row(db, owner_id, key)
    if starred:
        if row is None:
            row = models.InventoryCategory(
                owner_id=owner_id, name=entry["name"], normalized=key
            )
            db.add(row)
            db.flush()
        if not _try_star(db, owner_id, row):
            # A refused star leaves no trace — not even the
            # registry row created above just to hold it.
            db.rollback()
            raise StarLimitReached(
                f"You can star up to {STAR_LIMIT} categories."
            )
    elif row is not None:
        row.starred = False
    db.commit()
    return {
        "name": entry["name"],
        "item_count": entry["item_count"],
        "registered": row is not None or entry["registered"],
        "starred": bool(row.starred) if row is not None else False,
        "preinstalled": entry["system_key"] is not None,
        "system_key": entry["system_key"],
    }


def create_category(
    db: Session, owner_id: uuid.UUID, name: str, starred: bool = False
) -> dict:
    """Register a category — or return the existing one when the
    name (in any spelling) already names a category, on the
    registry or on items (the duplicate-folding rule). With
    starred=True the category is born starred when the cap
    allows; a full cap creates it UNSTARRED with star_capped
    set — the limit blocks the star, never the category.
    Commits."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ToolValidationError("A category needs a name.")
    key = _category_key(cleaned)
    if not key:
        raise ToolValidationError("A category needs a name.")
    universe = _category_universe(db, owner_id)
    if key in universe:
        entry = universe[key]
        if not starred:
            return {
                "name": entry["name"],
                "item_count": entry["item_count"],
                "registered": entry["registered"],
                "starred": entry["starred"],
                "star_capped": False,
                "preinstalled": entry["system_key"] is not None,
                "system_key": entry["system_key"],
            }
        row = _category_row(db, owner_id, key)
        if row is None:
            # Lives only on items: register it so the star has
            # a row to live on (display spelling is the
            # universe's preferred one).
            row = models.InventoryCategory(
                owner_id=owner_id, name=entry["name"], normalized=key
            )
            db.add(row)
            db.flush()
        applied = _try_star(db, owner_id, row)
        db.commit()
        return {
            "name": entry["name"],
            "item_count": entry["item_count"],
            "registered": True,
            "starred": row.starred,
            "star_capped": not applied,
            "preinstalled": entry["system_key"] is not None,
            "system_key": entry["system_key"],
        }
    row = models.InventoryCategory(
        owner_id=owner_id, name=cleaned, normalized=key
    )
    db.add(row)
    db.flush()
    capped = False
    if starred:
        capped = not _try_star(db, owner_id, row)
    db.commit()
    return {
        "name": cleaned,
        "item_count": 0,
        "registered": True,
        "starred": row.starred,
        "star_capped": capped,
        "preinstalled": False,
        "system_key": None,
    }


def _rewrite_category(
    db: Session, owner_id: uuid.UUID, source_key: str, new_value: str
) -> int:
    """Point every item filed under the source category (any
    spelling variant) at new_value. ORM writes — each item's
    change lands in the owner's journal. Returns the move count.
    Does NOT commit (the caller's operation does)."""
    moved = 0
    for model in (models.Tool, models.Battery):
        for item in db.scalars(
            select(model).where(
                model.owner_id == owner_id, model.category != ""
            )
        ):
            if _category_key(item.category) == source_key:
                item.category = new_value
                moved += 1
    return moved


def rename_category(
    db: Session, owner_id: uuid.UUID, old_name: str, new_name: str
) -> dict:
    """Rename a category everywhere it appears (tools +
    batteries, all spelling variants). Refuses when the new name
    already names a DIFFERENT category — that's a merge, and the
    manager makes the user say so. Commits."""
    cleaned = (new_name or "").strip()
    if not cleaned:
        raise ToolValidationError("A category needs a name.")
    old_key = _category_key(old_name or "")
    new_key = _category_key(cleaned)
    universe = _category_universe(db, owner_id)
    if old_key not in universe:
        raise ToolValidationError("That category isn't available.")
    if new_key != old_key and new_key in universe:
        raise ToolValidationError(
            f"'{universe[new_key]['name']}' already exists — merge "
            "the categories instead of renaming onto it."
        )
    source_row = _category_row(db, owner_id, old_key)
    if source_row is not None and source_row.system_key == "batteries":
        # Batteries is the one fixed-name starter (owner spec
        # 2026-10-25): battery records are wired to it, so the
        # name is not the owner's to change. The tool starters
        # rename freely — the system_key rides the row.
        raise PreinstalledCategoryError(
            "Batteries is a built-in category and can't be renamed."
        )
    moved = _rewrite_category(db, owner_id, old_key, cleaned)
    row = _category_row(db, owner_id, old_key)
    if row is not None:
        row.name = cleaned
        row.normalized = new_key
    elif new_key != old_key:
        db.add(
            models.InventoryCategory(
                owner_id=owner_id, name=cleaned, normalized=new_key
            )
        )
    # The star rides the registry row, so a rename of a starred
    # category carries it to the new name untouched.
    starred = bool(row.starred) if row is not None else False
    system_key = row.system_key if row is not None else None
    db.commit()
    return {
        "name": cleaned,
        "item_count": moved,
        "registered": True,
        "starred": starred,
        "preinstalled": system_key is not None,
        "system_key": system_key,
    }


def merge_categories(
    db: Session, owner_id: uuid.UUID, source_name: str, target_name: str
) -> dict:
    """Fold the source category into the target: every source
    item moves to the target's display spelling and the source
    disappears (registry row included). Commits."""
    source_key = _category_key(source_name or "")
    target_key = _category_key(target_name or "")
    universe = _category_universe(db, owner_id)
    if source_key not in universe:
        raise ToolValidationError("That category isn't available.")
    if target_key not in universe:
        raise ToolValidationError("That target category isn't available.")
    if source_key == target_key:
        raise ToolValidationError("A category can't merge into itself.")
    source_row = _category_row(db, owner_id, source_key)
    if source_row is not None and source_row.system_key is not None:
        # Merging a starter away would delete it (owner spec
        # 2026-10-25: starters are permanent). Merging INTO a
        # starter stays allowed — the target survives and gains.
        raise PreinstalledCategoryError(
            f"'{universe[source_key]['name']}' is a built-in category "
            "and can't be merged away."
        )
    target_display = universe[target_key]["name"]
    moved = _rewrite_category(db, owner_id, source_key, target_display)
    row = _category_row(db, owner_id, source_key)
    if row is not None:
        db.delete(row)
    db.commit()
    return {
        "name": target_display,
        "item_count": universe[target_key]["item_count"] + moved,
        "registered": universe[target_key]["registered"],
        # The target keeps its OWN star; the source's star dies
        # with the source row above (the source category is gone).
        "starred": universe[target_key]["starred"],
        "preinstalled": universe[target_key]["system_key"] is not None,
        "system_key": universe[target_key]["system_key"],
        "moved": moved,
    }


def delete_category(db: Session, owner_id: uuid.UUID, name: str) -> dict:
    """Detach a category: every item under it becomes
    uncategorized and the registry row goes. Items are NEVER
    deleted by the manager. Commits; returns the detach count."""
    key = _category_key(name or "")
    universe = _category_universe(db, owner_id)
    if key not in universe:
        raise ToolValidationError("That category isn't available.")
    row = _category_row(db, owner_id, key)
    if row is not None and row.system_key is not None:
        # Preinstalled starters are permanent (owner spec
        # 2026-10-25): they can be unstarred, never deleted.
        raise PreinstalledCategoryError(
            f"'{universe[key]['name']}' is a built-in category "
            "and can't be deleted."
        )
    detached = _rewrite_category(db, owner_id, key, "")
    if row is not None:
        db.delete(row)
    db.commit()
    return {"detached": detached}


# -- health check (gap wave 1, 2026-10-20) ---------------------------------------
#
# The claim-readiness scan (the app's Health Check): which ACTIVE
# items are missing the data a claim/report actually needs — a
# model number, a serial number, a photo, a purchase date.
# DECISION (documented per the build brief): set PIECES are
# checked by their own serial rule — a set whose piece is missing
# a serial surfaces UNDER THE SET with the piece named; pieces
# have no model/photo/date of their own to miss (their part
# number rides the set's model check at set level).


def _has_photo(record) -> bool:
    return any(
        (a or {}).get("kind") == "photo" for a in (record.attachments or [])
    )


def health_check(db: Session, owner_id: uuid.UUID) -> dict:
    """{total, counts: {identifier, photo, purchase_date,
    piece_serial}, items: [{kind, id, name, missing, pieces}]} —
    ACTIVE items only (the entitlement active set, the reports
    rule: an inactive item is excluded, not flagged), attached
    addon tools excluded (they live inside their set). The
    identifier gap fires only when an item has NEITHER a model
    number NOR a serial number — either one satisfies the
    identifier a claim needs (owner ruling 2026-11-03)."""
    from app.modules.billing import entitlements

    active_tools = entitlements.active_tool_ids(db, owner_id)
    active_batteries = entitlements.active_battery_ids(db, owner_id)
    items: list[dict] = []
    counts = {"identifier": 0, "photo": 0, "purchase_date": 0,
              "piece_serial": 0}
    # Sweep E3: active items whose missing photo is currently
    # ignored (the flag is set and there is still no photo). An
    # item whose ONLY gap was the photo drops off `items` above —
    # this list is where the page offers Un-ignore, so the ignore
    # is reversible from the same place it was set. Display /
    # reversal data only: these items never enter total/counts.
    photo_ignored_items: list[dict] = []

    def flag(kind, record, missing, pieces_missing):
        pieces_missing_serial = [p["name"] for p in pieces_missing]
        if not missing and not pieces_missing_serial:
            # A9: a business-use item under a declared sub-limit
            # surfaces in the Health Check even when its records
            # are complete — the warning is the point.
            if not (getattr(record, "business_use", False) and sub_limit_applies):
                return
        for key in missing:
            counts[key] += 1
        if pieces_missing_serial:
            counts["piece_serial"] += 1
        items.append(
            {
                "kind": kind,
                "id": record.id,
                "name": record.name,
                "missing": missing,
                "pieces_missing_serial": pieces_missing_serial,
                "pieces_missing": pieces_missing,
                "sub_limit_warning": bool(
                    getattr(record, "business_use", False) and sub_limit_applies
                ),
                # Sweep E3 (busy-work #5): the photo ignore state
                # rides the row so the page can offer Un-ignore on
                # an item whose photo gap is currently silenced
                # (its other gaps keep it on the list), plus the
                # identifying data the fix-all wizard shows so the
                # user knows which item a step is about.
                "photo_ignored": bool(
                    getattr(record, "health_photo_ignored", False)
                ),
                "brand": getattr(record, "brand", "") or "",
                "model": getattr(record, "model", "") or "",
                "serial_number": getattr(record, "serial_number", "") or "",
            }
        )

    sub_limit_applies = business_sub_limit_applies(db, owner_id)

    tools = [
        t
        for t in list_tools(db, owner_id)
        if active_tools is None or t.id in active_tools
    ]
    for tool in tools:
        missing = []
        if not (tool.model_numbers or []) and not (tool.model or "") and not (
            tool.serial_numbers or []
        ) and not (tool.serial_number or ""):
            missing.append("identifier")
        # Photo ignore (sweep E3): an ignored missing photo does
        # not flag — the item's other gaps still do, untouched.
        if not _has_photo(tool) and not tool.health_photo_ignored:
            missing.append("photo")
        if tool.health_photo_ignored and not _has_photo(tool):
            photo_ignored_items.append(
                {"kind": "tool", "id": tool.id, "name": tool.name}
            )
        if tool.purchase_date is None:
            missing.append("purchase_date")
        pieces_missing: list[dict] = []
        if tool.is_set:
            pieces_missing = [
                {"id": piece.id, "name": piece.name}
                for piece in _list_set_pieces(db, tool.id)
                if piece.status == "present"
                and not (piece.serial_number or "")
            ]
        flag("tool", tool, missing, pieces_missing)

    batteries = [
        b
        for b in list_batteries(db, owner_id)
        if active_batteries is None or b.id in active_batteries
    ]
    for battery in batteries:
        missing = []
        if not (battery.model or "") and not (battery.serial_number or ""):
            missing.append("identifier")
        if not _has_photo(battery) and not battery.health_photo_ignored:
            missing.append("photo")
        if battery.health_photo_ignored and not _has_photo(battery):
            photo_ignored_items.append(
                {"kind": "battery", "id": battery.id, "name": battery.name}
            )
        if battery.purchase_date is None:
            missing.append("purchase_date")
        flag("battery", battery, missing, [])

    items.sort(key=lambda row: row["name"].lower())
    # total_items (sweep B2-F16): the ACTIVE vault size behind the
    # scan, so the page can tell an empty vault ("No items yet")
    # apart from a populated one that is fully claim-ready — with
    # only `total` (items needing attention) the two read the same.
    photo_ignored_items.sort(key=lambda row: row["name"].lower())
    return {
        "total": len(items),
        "counts": counts,
        "items": items,
        "total_items": len(tools) + len(batteries),
        "photo_ignored_items": photo_ignored_items,
    }


def set_health_photo_ignore(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    ignored: bool,
) -> dict | None:
    """Set or clear ONE item's health-check photo ignore (sweep
    E3, busy-work #5). Owner-scoped; photo only — there is no
    other field this can touch, by construction. Returns the
    item's {kind, id, name, photo_ignored} or None when the item
    is not the owner's (the route answers 404)."""
    if kind == "tool":
        record = get_tool(db, owner_id, item_id)
    elif kind == "battery":
        record = get_battery(db, owner_id, item_id)
    else:
        return None
    if record is None:
        return None
    record.health_photo_ignored = bool(ignored)
    db.commit()
    db.refresh(record)
    return {
        "kind": kind,
        "id": record.id,
        "name": record.name,
        "photo_ignored": bool(record.health_photo_ignored),
    }


def ignore_all_missing_photos(db: Session, owner_id: uuid.UUID) -> dict:
    """Ignore EVERY currently-flagged missing photo for this
    owner in one action (owner order, 2026-11-12 — the Health
    Check page's "Ignore all missing photos" button). Semantically
    identical to pressing the per-item Ignore button on each
    affected item one by one: the target set is read FROM THE
    SCAN ITSELF — every item whose `missing` list carries
    "photo" (which by the scan's construction means: active,
    no photo attachment, not already ignored) — and the same
    per-item flag is set on each, in ONE commit. Items already
    ignored are never in that set, so they are untouched; items
    with a photo never are either. Other owners' items cannot
    appear: the scan is owner-scoped. Returns how many items
    were newly ignored."""
    scan = health_check(db, owner_id)
    targets = [
        (row["kind"], row["id"])
        for row in scan["items"]
        if "photo" in row["missing"]
    ]
    ignored_count = 0
    for kind, item_id in targets:
        record = (
            get_tool(db, owner_id, item_id)
            if kind == "tool"
            else get_battery(db, owner_id, item_id)
        )
        if record is None or record.health_photo_ignored:
            continue
        record.health_photo_ignored = True
        ignored_count += 1
    if ignored_count:
        db.commit()
    return {"ignored_count": ignored_count}


def health_check_due(db: Session, owner_id: uuid.UUID) -> dict:
    """The Health checks due widget's read (widget wave 2,
    2026-11-10): the health_check scan above, VERBATIM — the
    same total, the same counts, the same items in the same
    order, computed by the scan itself so the widget can never
    disagree with the Health Check page about what needs
    attention. The only addition is display data: each flagged
    item's primary-photo thumbnail (primary_photo_thumb — the
    shared minter the search and dealer surfaces use), so a
    widget row can show the item's photo where it has one.
    Items the scan flags for a missing photo carry nulls, which
    is the client's cue for its no-photo treatment. The due
    definition is NOT restated here — there is exactly one."""
    result = health_check(db, owner_id)
    if not result["items"]:
        return result
    records: dict[tuple[str, uuid.UUID], object] = {}
    for tool in list_tools(db, owner_id):
        records[("tool", tool.id)] = tool
    for battery in list_batteries(db, owner_id):
        records[("battery", battery.id)] = battery
    for item in result["items"]:
        record = records.get((item["kind"], item["id"]))
        thumb = primary_photo_thumb(record) if record is not None else None
        item["thumb_url"] = thumb["thumb_url"] if thumb else None
        item["thumb_url_sm"] = thumb["thumb_url_sm"] if thumb else None
    return result
