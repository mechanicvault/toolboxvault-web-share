"""Duplicate detection on item create (wave 4) — DETERMINISTIC,
no AI: an owner probably doesn't mean to catalogue the same
physical item twice, but the system must never guess.

The rule (pinned by tests): a create is a POSSIBLE duplicate
only when an existing item of the owner's has BOTH
  - the same normalized brand + model, AND
  - the same serial number (any of the item's serials), OR the
    same UPC.
Brand + model alone NEVER blocks — a mechanic legitimately owns
two identical ratchets; identity needs a serial or a barcode.
The create routes answer 409 {code: possible_duplicate,
existing: [...]} unless the caller passes force=true (the UI's
"Add anyway"). The check lives in the routes, not the service,
so bulk paths (the importer) are never blocked by it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.normalize import norm_brand, norm_model, norm_text, norm_upc
from app.modules.inventory import models


def _serial_set(record) -> set[str]:
    # Tools carry a serial_numbers list; batteries don't have the
    # attribute at all — getattr keeps one code path for both.
    listed = getattr(record, "serial_numbers", None) or []
    serials = {norm_text(s) for s in listed if norm_text(s)}
    if norm_text(record.serial_number):
        serials.add(norm_text(record.serial_number))
    return serials


def find_duplicates(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    *,
    brand: str,
    model: str,
    serials: list[str],
    upc: str,
) -> list[dict]:
    """The owner's existing items this create probably repeats
    (wire shape for the 409's `existing` list)."""
    key_brand = norm_brand(brand)
    key_model = norm_model(model)
    new_serials = {norm_text(s) for s in serials if norm_text(s)}
    new_upc = norm_upc(upc)
    if not key_brand or not key_model or (not new_serials and not new_upc):
        return []
    record_model = models.Tool if kind == "tool" else models.Battery
    rows = db.scalars(
        select(record_model).where(record_model.owner_id == owner_id)
    )
    out: list[dict] = []
    for record in rows:
        if norm_brand(record.brand) != key_brand:
            continue
        if norm_model(record.model) != key_model:
            continue
        serial_hit = bool(new_serials & _serial_set(record))
        upc_hit = bool(new_upc) and norm_upc(record.upc) == new_upc
        if not (serial_hit or upc_hit):
            continue
        out.append(
            {
                "id": str(record.id),
                "item_kind": kind,
                "name": record.name,
                "brand": record.brand,
                "model": record.model,
                "serial_number": record.serial_number,
                "upc": record.upc or "",
                "matched_on": "serial" if serial_hit else "upc",
            }
        )
    return out
