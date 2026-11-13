"""Wishlist service — owner-scoped CRUD, the purchase flow, and
the Convert-to-Tool copy.

Convert mirrors the Used Parts bridge (parts/service): the copy
goes THROUGH inventory's service interface (create_tool + its
attach flow) — this module never writes a tool row itself. The
gates (inventory effective for the caller, the entitlement item
limit) live in the route, exactly as parts' convert route does.

The flow (owner spec, wave 2): an item is first MARKED PURCHASED
with the price actually paid + the date; only then may it convert
— the tool is born carrying those purchase facts, so the vault's
money history starts true.
"""

import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.modules.core import journal
from app.modules.inventory import service as inventory_service
from app.modules.wishlist import models, schemas


class WishlistError(ValueError):
    """Caller turns this into a friendly 422."""


class WishlistNotFound(WishlistError):
    """Missing OR foreign id — one answer, ids don't leak."""


def _validate_priority(priority: str) -> None:
    if priority not in models.PRIORITIES:
        raise WishlistError(
            "Priority must be one of: " + ", ".join(models.PRIORITIES) + "."
        )


def stats(db: Session, owner_id: uuid.UUID) -> dict:
    """The panel/home stat (Phase 3, 2026-10-24): how many
    things I am still hunting — items in "wanted" status.
    Purchased items stay on the page as history (stamped) but
    are not part of the live count."""
    count = db.scalar(
        select(func.count(models.WishlistItem.id)).where(
            models.WishlistItem.owner_id == owner_id,
            models.WishlistItem.status == "wanted",
        )
    )
    return {"items_count": int(count or 0)}


def get_item(
    db: Session, owner_id: uuid.UUID, item_id: uuid.UUID
) -> models.WishlistItem | None:
    item = db.get(models.WishlistItem, item_id)
    if item is None or item.owner_id != owner_id:
        return None
    return item


def list_items(
    db: Session,
    owner_id: uuid.UUID,
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[models.WishlistItem]:
    stmt = select(models.WishlistItem).where(
        models.WishlistItem.owner_id == owner_id
    )
    if status in models.STATUSES:
        stmt = stmt.where(models.WishlistItem.status == status)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.WishlistItem.title.ilike(needle),
                models.WishlistItem.notes.ilike(needle),
            )
        )
    # Wanted first by priority (high → normal → low), then newest;
    # purchased sink below the still-wanted. Priority weight is
    # computed in Python — a want-list is small by nature.
    rows = list(db.scalars(stmt))
    weight = {"high": 0, "normal": 1, "low": 2}
    rows.sort(
        key=lambda r: (
            0 if r.status == "wanted" else 1,
            weight.get(r.priority, 1),
            -r.created_at.timestamp(),
        )
    )
    return rows[:limit]


def serialize_item(item: models.WishlistItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "link_url": item.link_url,
        "target_price": item.target_price,
        "priority": item.priority,
        "dealer_company_id": item.dealer_company_id,
        # Resolved by serialize_with_db (needs a session); the
        # base shape keeps the key present with None.
        "dealer_name": None,
        "notes": item.notes,
        "attachments": _serialize_attachments(item),
        "status": item.status,
        "purchased_price": item.purchased_price,
        "purchased_on": item.purchased_on,
        "converted_tool_id": item.converted_tool_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def serialize_with_db(db: Session, item: models.WishlistItem) -> dict:
    view = serialize_item(item)
    view["dealer_name"] = inventory_service.dealer_company_name(
        db, item.dealer_company_id
    )
    return view


def _serialize_attachments(item: models.WishlistItem) -> list[dict]:
    """Stored attachments keep only keys (+ metadata); read URLs
    are minted at serialize time — the platform-wide contract."""
    view = []
    for entry in item.attachments or []:
        if not isinstance(entry, dict) or "key" not in entry:
            continue
        view.append(
            {
                "key": entry["key"],
                "filename": entry.get("filename", ""),
                "kind": entry.get("kind", ""),
                "content_type": entry.get("content_type", ""),
                "size_bytes": entry.get("size_bytes", 0),
                "uploaded_at": entry.get("uploaded_at"),
                "url": storage.presigned_get_url(entry["key"]),
            }
        )
    return view


def create_item(
    db: Session, owner_id: uuid.UUID, payload: schemas.WishlistItemCreate
) -> models.WishlistItem:
    _validate_priority(payload.priority)
    inventory_service.validate_dealer_company(db, owner_id, payload.dealer_company_id)
    item = models.WishlistItem(
        owner_id=owner_id,
        title=payload.title.strip(),
        link_url=payload.link_url.strip(),
        target_price=payload.target_price,
        priority=payload.priority,
        dealer_company_id=payload.dealer_company_id,
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: schemas.WishlistItemUpdate,
) -> models.WishlistItem | None:
    item = get_item(db, owner_id, item_id)
    if item is None:
        return None
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("priority") is not None:
        _validate_priority(changes["priority"])
    if "dealer_company_id" in changes:
        inventory_service.validate_dealer_company(
            db, owner_id, changes["dealer_company_id"]
        )
    for key, value in changes.items():
        if value is None and key not in ("target_price", "dealer_company_id"):
            continue  # None means "leave it" except the clearable fields
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, owner_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    item = get_item(db, owner_id, item_id)
    if item is None:
        return False
    # Photos tombstone with the record (audit trail): a restore
    # brings the item back with its pictures.
    journal.retire_record_files(db, owner_id, item, entity_type="wishlist_item")
    db.delete(item)
    db.commit()
    return True


def mark_purchased(
    db: Session,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: schemas.MarkPurchased,
) -> models.WishlistItem | None:
    item = get_item(db, owner_id, item_id)
    if item is None:
        return None
    if item.status == "purchased":
        raise WishlistError("This item is already marked purchased.")
    item.status = "purchased"
    item.purchased_price = payload.purchased_price
    item.purchased_on = payload.purchased_on or date.today()
    db.commit()
    db.refresh(item)
    return item


def convert_to_tool(
    db: Session, owner_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[models.WishlistItem, object] | None:
    """Copy a PURCHASED wishlist item into Asset Inventory as a
    tool, through inventory's service interface. The wishlist row
    stays — stamped with converted_tool_id. Photos are copied
    object-to-object into the tool's namespace, then attached
    through inventory's flow; a photo that fails to copy is
    skipped (its bytes still live on the wishlist item)."""
    from app.modules.inventory import attachments as inventory_attachments
    from app.modules.inventory import schemas as inventory_schemas

    item = get_item(db, owner_id, item_id)
    if item is None:
        return None
    if item.status != "purchased":
        raise WishlistError(
            "Mark the item purchased first — the tool needs the price "
            "paid and the purchase date to start its history true."
        )
    if item.converted_tool_id is not None:
        raise WishlistError("This item was already converted to a tool.")

    tool = inventory_service.create_tool(
        db,
        owner_id,
        inventory_schemas.ToolCreate(
            name=item.title,
            purchase_price=item.purchased_price,
            purchase_date=item.purchased_on,
            dealer_company_id=item.dealer_company_id,
            notes=item.notes,
        ),
    )
    for attachment in item.attachments or []:
        if not isinstance(attachment, dict) or "key" not in attachment:
            continue
        if attachment.get("kind") != "photo":
            continue
        try:
            source_key = attachment["key"]
            filename = attachment.get("filename") or storage.safe_filename(
                source_key
            )
            dest_key = storage.object_key(
                str(owner_id), str(tool.id), "photo", filename,
                collection="tools",
            )
            storage.copy(source_key, dest_key)
            inventory_attachments.attach_file(
                db,
                owner_id,
                tool.id,
                inventory_schemas.AttachRequest(
                    key=dest_key, filename=filename
                ),
            )
        except Exception:
            continue  # a failed photo copy never strands the convert
    item.converted_tool_id = tool.id
    db.commit()
    db.refresh(item)
    return item, tool


def export_rows(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """The data export's wishlist.json: every item, full facts
    (the owner's own backup carries the whole row)."""
    return [
        {
            "id": str(item.id),
            "title": item.title,
            "link_url": item.link_url,
            "target_price": (
                str(item.target_price) if item.target_price is not None else None
            ),
            "priority": item.priority,
            "dealer_company_id": (
                str(item.dealer_company_id) if item.dealer_company_id else None
            ),
            "dealer_name": inventory_service.dealer_company_name(
                db, item.dealer_company_id
            ),
            "notes": item.notes,
            "attachments": item.attachments or [],
            "status": item.status,
            "purchased_price": (
                str(item.purchased_price)
                if item.purchased_price is not None
                else None
            ),
            "purchased_on": (
                item.purchased_on.isoformat() if item.purchased_on else None
            ),
            "converted_tool_id": (
                str(item.converted_tool_id) if item.converted_tool_id else None
            ),
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in list_items(db, owner_id, limit=100000)
    ]
