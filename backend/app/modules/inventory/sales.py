"""Sold tracking (wave 2, 2026-10-20): the sale ledger and the
Mark sold / Undo sale actions.

Doctrine:
- The ledger (models.SaleRecord) is APPEND-ONLY through every
  surface: no edit, no delete. A mistake is corrected by Undo,
  which writes a compensating reversal row and restores the
  item — both events stay in the item's history.
- A FULL sale flips the item's standing to `sold` (the one
  writer: service.apply_standing). Sold items LEAVE the
  entitlement active set (billing excludes them — they are no
  longer the owner's assets, unlike lost/stolen items which the
  owner still holds title to). A PARTIAL sale (quantity > 1,
  sell N of M) writes ONE record for the portion and reduces the
  record's quantity by N — the app's partial-sale TWIN-RECORD
  problem solved as record + reduction: no twin items, ever.
- Guards mirror the deletion guards' spirit: an item out on
  loan can't be sold until it comes back, and an item on an
  OPEN claim can't be sold out from under the claim. Both probes
  are read-only lazy imports (the history.py precedent) — the
  borrowing/claims modules own their tables; this module only
  reads the two facts it needs, so removing either module
  removes its guard with it.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import history as inv_history
from app.modules.inventory import models
from app.modules.inventory import service


class SaleError(service.ToolValidationError):
    """A refused sale/undo — routes render it as a friendly 422."""


# -- read-only cross-module probes (lazy, history.py precedent) -----------------


def _active_checkout_item_ids(
    db: Session, owner_id: uuid.UUID
) -> set[tuple[str, uuid.UUID]]:
    """(kind, item_id) pairs with a live lend (requested or
    checked out) — borrowed items can't be sold mid-lend."""
    try:
        from app.modules.borrowing import models as borrowing_models
    except ImportError:
        return set()
    rows = db.execute(
        select(
            borrowing_models.Checkout.item_kind,
            borrowing_models.Checkout.item_id,
        ).where(
            borrowing_models.Checkout.owner_id == owner_id,
            borrowing_models.Checkout.state.in_(("requested", "checked_out")),
        )
    ).all()
    return {(kind, item_id) for kind, item_id in rows}


def _open_claim_number(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    set_id: uuid.UUID | None = None,
) -> str | None:
    """The claim number of an OPEN claim touching this item, or
    None. Mirrors the claims delete guard's reach: a direct line
    on the item; for a set, a line on any of its pieces; for a
    piece, a line on the piece or on its whole set."""
    try:
        from app.modules.claims import models as claim_models
    except ImportError:
        return None
    base = (
        select(claim_models.Claim.claim_number)
        .join(
            claim_models.ClaimLine,
            claim_models.ClaimLine.claim_id == claim_models.Claim.id,
        )
        .where(
            claim_models.Claim.owner_id == owner_id,
            claim_models.Claim.status.in_(claim_models.OPEN_STATUSES),
        )
    )
    if kind == "battery":
        stmt = base.where(
            claim_models.ClaimLine.target_kind == "battery",
            claim_models.ClaimLine.target_id == item_id,
        )
    elif kind == "piece":
        stmt = base.where(
            (
                (claim_models.ClaimLine.target_kind == "piece")
                & (claim_models.ClaimLine.target_id == item_id)
            )
            | (
                (claim_models.ClaimLine.target_kind == "set")
                & (claim_models.ClaimLine.target_id == set_id)
            )
        )
    else:  # tool (a set is a tool record)
        stmt = base.where(
            (
                claim_models.ClaimLine.target_kind.in_(("tool", "set"))
                & (claim_models.ClaimLine.target_id == item_id)
            )
            | (
                (claim_models.ClaimLine.target_kind == "piece")
                & (claim_models.ClaimLine.set_id == item_id)
            )
        )
    row = db.execute(stmt).first()
    return row[0] if row else None


def _guards(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    set_id: uuid.UUID | None = None,
) -> None:
    checkout_key = (kind, item_id) if kind != "piece" else ("tool", set_id)
    if checkout_key in _active_checkout_item_ids(db, owner_id):
        raise SaleError(
            "This item is checked out right now — mark it returned "
            "before selling it."
        )
    claim_number = _open_claim_number(db, owner_id, kind, item_id, set_id)
    if claim_number:
        raise SaleError(
            f"This item is on open claim {claim_number} — close the "
            "claim before selling it."
        )


# -- serialization ---------------------------------------------------------------


def serialize_sale_record(row: models.SaleRecord) -> dict:
    return {
        "id": row.id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "set_id": row.set_id,
        "item_name": row.item_name,
        "quantity_sold": row.quantity_sold,
        "buyer_name": row.buyer_name,
        "buyer_contact": row.buyer_contact,
        "sale_price": row.sale_price,
        "sold_on": row.sold_on,
        "note": row.note,
        "source": row.source,
        "kind": row.kind,
        "reverses_id": row.reverses_id,
        "created_at": row.created_at,
    }


def _reversed_ids(db: Session, owner_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(models.SaleRecord.reverses_id).where(
                models.SaleRecord.owner_id == owner_id,
                models.SaleRecord.kind == "reversal",
                models.SaleRecord.reverses_id.is_not(None),
            )
        )
    )


def sale_view(db: Session, owner_id: uuid.UUID, row: models.SaleRecord) -> dict:
    """Wire shape + the derived `reversed` flag (a sale with a
    compensating row is history, not a live sale)."""
    view = serialize_sale_record(row)
    view["reversed"] = row.id in _reversed_ids(db, owner_id)
    return view


# -- the actions -------------------------------------------------------------------


def mark_sold(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    *,
    quantity_sold: int | None = None,
    buyer_name: str = "",
    buyer_contact: str = "",
    sale_price: Decimal,
    sold_on: date | None = None,
    note: str = "",
) -> models.SaleRecord:
    """Record a sale of a tool, battery, or set piece.

    kind "tool" | "battery": quantity_sold defaults to the whole
    quantity (a FULL sale → standing sold). Less than the whole
    is a PARTIAL: the record's quantity drops by the amount sold
    and the item stays in service. kind "set_piece": the piece
    (addressed by its own id) flips to its sold presence status.
    A set is sold through its tool record (kind "tool").
    """
    sold_on = sold_on or date.today()
    if sale_price is None or sale_price < 0:
        raise SaleError("Sale price can't be negative.")

    if kind == "piece":
        piece = service.get_set_piece(db, owner_id, item_id)
        if piece is None:
            raise SaleError("That piece doesn't exist.")
        if piece.status == "sold":
            raise SaleError("That piece is already marked sold.")
        _guards(db, owner_id, "piece", piece.id, set_id=piece.set_id)
        record = models.SaleRecord(
            owner_id=owner_id,
            item_kind="set_piece",
            item_id=piece.id,
            set_id=piece.set_id,
            item_name=piece.name,
            quantity_sold=1,
            buyer_name=buyer_name.strip(),
            buyer_contact=buyer_contact.strip(),
            sale_price=sale_price,
            sold_on=sold_on,
            note=note,
            source="manual",
            kind="sale",
        )
        piece.status = "sold"
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    if kind not in ("tool", "battery"):
        raise SaleError(f"Unknown item kind: {kind}")
    item = (
        service.get_tool(db, owner_id, item_id)
        if kind == "tool"
        else service.get_battery(db, owner_id, item_id)
    )
    if item is None:
        raise SaleError("That item doesn't exist.")
    if kind == "tool" and item.attached_to_set_id is not None:
        raise SaleError(
            "This tool is an addon inside a set — detach it first, "
            "or sell the set it belongs to."
        )
    if item.standing == models.STANDING_SOLD:
        raise SaleError("This item is already marked sold.")
    _guards(db, owner_id, kind, item.id)

    available = item.quantity or 1
    qty = available if quantity_sold is None else quantity_sold
    if qty < 1 or qty > available:
        raise SaleError(
            f"You can sell between 1 and {available} of this item."
        )
    record = models.SaleRecord(
        owner_id=owner_id,
        item_kind=kind,
        item_id=item.id,
        set_id=None,
        item_name=item.name,
        quantity_sold=qty,
        buyer_name=buyer_name.strip(),
        buyer_contact=buyer_contact.strip(),
        sale_price=sale_price,
        sold_on=sold_on,
        note=note,
        source="manual",
        kind="sale",
    )
    db.add(record)
    if qty == available:
        # FULL sale: the item leaves the vault.
        service.apply_standing(item, models.STANDING_SOLD)
    else:
        # PARTIAL: record + reduction, no twin item.
        item.quantity = available - qty
    db.commit()
    db.refresh(record)
    return record


def undo_sale(
    db: Session, owner_id: uuid.UUID, record_id: uuid.UUID
) -> models.SaleRecord:
    """Reverse a sale: write the compensating reversal row and
    restore the item (full → standing back in service; partial →
    quantity restored; piece → present again). The reversal is
    the correction mechanism — sales are never edited silently.
    The pre-sale standing is not recoverable from the ledger, so
    a full undo lands on in_service (documented in the module
    docstring of models.SaleRecord's feature)."""
    original = db.get(models.SaleRecord, record_id)
    if original is None or original.owner_id != owner_id:
        raise SaleError("That sale record doesn't exist.")
    if original.kind != "sale":
        raise SaleError("A reversal can't be undone — record a new sale instead.")
    if original.id in _reversed_ids(db, owner_id):
        raise SaleError("This sale was already undone.")
    # LIFO discipline: a newer live sale on the same item must be
    # undone first. That ordering is what makes the restore below
    # unambiguous — under it, "the item stands sold" can only mean
    # THIS sale was the full one, and "in service with a short
    # quantity" can only mean this sale was partial.
    reversed_ids = _reversed_ids(db, owner_id)
    for other in db.scalars(
        select(models.SaleRecord).where(
            models.SaleRecord.owner_id == owner_id,
            models.SaleRecord.item_id == original.item_id,
            models.SaleRecord.kind == "sale",
            models.SaleRecord.id != original.id,
        )
    ):
        if other.id in reversed_ids:
            continue
        if (other.seq or 0) > (original.seq or 0):
            raise SaleError(
                "Undo the newer sale on this item first — sales "
                "unwind in reverse order."
            )

    reversal = models.SaleRecord(
        owner_id=owner_id,
        item_kind=original.item_kind,
        item_id=original.item_id,
        set_id=original.set_id,
        item_name=original.item_name,
        quantity_sold=original.quantity_sold,
        buyer_name=original.buyer_name,
        buyer_contact=original.buyer_contact,
        sale_price=original.sale_price,
        sold_on=date.today(),
        note=f"Undo of the sale recorded {original.sold_on.isoformat()}.",
        source="manual",
        kind="reversal",
        reverses_id=original.id,
    )
    db.add(reversal)

    if original.item_kind == "set_piece":
        piece = service.get_set_piece(db, owner_id, original.item_id)
        if piece is not None and piece.status == "sold":
            piece.status = "present"
    else:
        item = (
            service.get_tool(db, owner_id, original.item_id)
            if original.item_kind == "tool"
            else service.get_battery(db, owner_id, original.item_id)
        )
        if item is not None:
            if item.standing == models.STANDING_SOLD:
                service.apply_standing(item, models.STANDING_IN_SERVICE)
            else:
                # A partial sale: give the units back.
                item.quantity = (item.quantity or 1) + original.quantity_sold
    db.commit()
    db.refresh(reversal)
    return reversal


# -- reads -------------------------------------------------------------------------


def list_sales(
    db: Session,
    owner_id: uuid.UUID,
    *,
    item_id: uuid.UUID | None = None,
    limit: int = 500,
) -> list[models.SaleRecord]:
    stmt = select(models.SaleRecord).where(
        models.SaleRecord.owner_id == owner_id
    )
    if item_id is not None:
        stmt = stmt.where(
            (models.SaleRecord.item_id == item_id)
            | (models.SaleRecord.set_id == item_id)
        )
    rows = list(db.scalars(stmt))
    rows.sort(key=lambda r: (r.sold_on, r.seq or 0, str(r.id)), reverse=True)
    return rows[:limit]


def sales_totals(db: Session, owner_id: uuid.UUID) -> dict:
    """The Sold view's headline numbers: net sold value (sales
    minus reversals), live sale count, units moved."""
    rows = list(
        db.scalars(
            select(models.SaleRecord).where(
                models.SaleRecord.owner_id == owner_id
            )
        )
    )
    reversed_ids = {
        r.reverses_id for r in rows if r.kind == "reversal" and r.reverses_id
    }
    total = Decimal("0")
    live_sales = 0
    units = 0
    for row in rows:
        if row.kind == "sale" and row.id not in reversed_ids:
            total += row.sale_price
            live_sales += 1
            units += row.quantity_sold
    return {
        "total_sold_value": total,
        "sale_count": live_sales,
        "units_sold": units,
        "record_count": len(rows),
    }


def latest_sales_map(
    db: Session, owner_id: uuid.UUID
) -> dict[tuple[str, uuid.UUID], models.SaleRecord]:
    """{(kind, item_id): latest EFFECTIVE sale} — reversed sales
    don't count. The reports seam: one query per report build
    (the loss-report batch discipline). Piece sales key on the
    piece id under item_kind "set_piece"."""
    rows = list_sales(db, owner_id, limit=100000)
    reversed_ids = {
        r.reverses_id for r in rows if r.kind == "reversal" and r.reverses_id
    }
    latest: dict[tuple[str, uuid.UUID], models.SaleRecord] = {}
    for row in rows:  # newest first — first writer wins
        if row.kind != "sale" or row.id in reversed_ids:
            continue
        latest.setdefault((row.item_kind, row.item_id), row)
    return latest


def export_rows(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """The data export's sales.json: the whole ledger, reversals
    included — the owner's backup carries the honest history."""
    out = []
    for row in list_sales(db, owner_id, limit=100000):
        view = serialize_sale_record(row)
        view["id"] = str(view["id"])
        view["item_id"] = str(view["item_id"])
        view["set_id"] = str(view["set_id"]) if view["set_id"] else None
        view["reverses_id"] = (
            str(view["reverses_id"]) if view["reverses_id"] else None
        )
        view["sale_price"] = str(view["sale_price"])
        view["sold_on"] = view["sold_on"].isoformat()
        view["created_at"] = (
            view["created_at"].isoformat() if view["created_at"] else None
        )
        out.append(view)
    return out


# -- asset history provider ---------------------------------------------------------


def sales_history_events(db, owner_id, item_kind, item_id):
    """History provider (registered below): this item's sales as
    life events. For a SET (a tool), its pieces' sales ride
    along — the piece's story is told on the set's page, the only
    page pieces have."""
    if item_kind not in ("tool", "battery"):
        return []
    rows = list(
        db.scalars(
            select(models.SaleRecord).where(
                models.SaleRecord.owner_id == owner_id,
                (models.SaleRecord.item_id == item_id)
                | (
                    (models.SaleRecord.item_kind == "set_piece")
                    & (models.SaleRecord.set_id == item_id)
                ),
            )
        )
    )
    reversed_ids = {
        r.reverses_id for r in rows if r.kind == "reversal" and r.reverses_id
    }
    events = []
    for row in rows:
        if row.kind == "reversal":
            events.append(
                inv_history.HistoryEvent(
                    ts=inv_history.day_start(row.sold_on),
                    kind="sold",
                    title=f"Sale of {row.item_name} undone",
                    detail="The sale was reversed; the item is back.",
                )
            )
            continue
        buyer = f" to {row.buyer_name}" if row.buyer_name else ""
        price = inv_history.money(row.sale_price, inv_history.owner_currency(db, owner_id))
        price_part = f" — {price}" if price else ""
        if row.item_kind == "set_piece":
            title = f"Sold piece {row.item_name}{buyer}{price_part}"
        elif row.id in reversed_ids:
            title = f"Sold{buyer}{price_part} (later undone)"
        else:
            title = f"Sold{buyer}{price_part}"
        detail_parts = []
        if row.quantity_sold and row.quantity_sold > 1:
            detail_parts.append(f"{row.quantity_sold} units")
        events.append(
            inv_history.HistoryEvent(
                ts=inv_history.day_start(row.sold_on),
                kind="sold",
                title=title,
                detail=" · ".join(detail_parts),
            )
        )
    return events


inv_history.register_history_provider("sales", sales_history_events)
