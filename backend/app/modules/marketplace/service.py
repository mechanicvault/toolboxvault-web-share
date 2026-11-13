"""Tools For Sale service: listings, the publish gate, the
board, mark-sold, and the export rows.

SERVICE INTERFACE (stable; bump the marketplace manifest version
on change):
  - marketplace_enabled(db) — the operator kill switch
    (`community.marketplace_enabled`, default ON) AND the
    module's global switch. Board reads + anchor resolution 404
    while off; owners keep managing their own listings.
  - can_publish(db, user_id) — the community suite's paid-
    contribution gate, the pool's exact shape: bites only while
    the entitlements enforcement switch is ON; a paying resolver
    source counts, a TRIAL never does.
  - create_listing / update_listing / delete_listing /
    mark_sold / remove_listing / reactivate_listing — the owner
    lifecycle. An ACTIVE listing IS a publication, so the gate
    checks at create, at any edit of an active listing, and at
    reactivation — and again per seller at board READ time, so a
    lapsed plan stops listing while enforcement is on.
  - serialize_public(listing, seller) — THE board payload (exact
    keys, see LISTING_KEYS): only what the seller put on the
    listing. NO email, ever; phone only on opt-in (listing
    override > profile toggle > hidden — the pool's chain); a
    from-inventory listing shows the SNAPSHOT it carries, never
    the live inventory record (no serials, no notes, no purchase
    data — the inventory whitelist question never even arises).
  - search_listings(db, ...) / get_public_listing(db, id) — the
    board + the messaging anchor resolver.
  - end_listings_for_source(db, owner_id, kind, item_id) — the
    delete cascade inventory calls in its own transaction
    (owner spec 2026-10-25): an item's ACTIVE listings end when
    the item is deleted. Read surfaces additionally exclude
    ORPHAN listings (source item gone) so one can never display,
    however it was orphaned; displayable() is the /mine filter
    (sold orphans stay visible — completed-deal history).
  - snapshot_from_inventory(db, owner, kind, item_id) — the
    one-tap create: copies the item's display facts and COPIES
    its photo objects into the marketplace namespace (mirrors
    parts' convert-to-tool copy) so the listing stands alone.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.modules.core import money as core_money
from app.modules.core import service as core_service
from app.modules.marketplace import models, reputation

MARKETPLACE_ENABLED_KEY = "community.marketplace_enabled"

# The exact board payload contract (see serialize_public).
LISTING_KEYS = (
    "id",
    "title",
    "description",
    "listing_type",
    "price",
    "condition",
    "brand",
    "model",
    "delivery_local_pickup",
    "delivery_ships",
    "area_label",
    "photos",
    "seller_id",
    "seller_name",
    "seller_member_since",
    "seller_reputation",
    # Wave 3 currency: the listing's price is in the SELLER's
    # currency (amounts live in their owner's currency — v1
    # semantics); viewers label it with this code and may see an
    # approximate converted hint beside it.
    "seller_currency",
    "phone",
    "created_at",
    "updated_at",
)

_CANDIDATE_CAP = 5000
_LISTING_CAP = 200

_SORTS = ("newest", "price_asc", "price_desc", "rating")


class MarketplaceError(ValueError):
    """Friendly refusal. Routes -> 422."""


class MarketplaceNotFound(MarketplaceError):
    """Missing OR not yours — ids never leak existence. -> 404."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- switches + the publish gate -------------------------------------------------


def marketplace_enabled(db: Session) -> bool:
    """The board's master switch: the operator's community
    setting AND the module's global switch (either off hides the
    board entirely, the pool's exact posture)."""
    from app.modules.billing import entitlements
    from app.modules.core import module_control

    if not module_control.globally_enabled(db, "marketplace"):
        return False
    return bool(entitlements.get_setting(db, MARKETPLACE_ENABLED_KEY, True))


def can_publish(db: Session, user_id: uuid.UUID) -> bool:
    """May this account have active listings RIGHT NOW? The
    pool's rule verbatim: enforcement OFF (pre-launch) → everyone
    may; enforcement ON → a paid plan from a paying source, a
    trial never counts."""
    from app.modules.billing import entitlements

    if not entitlements.enforcement_enabled(db):
        return True
    entitlement = entitlements.resolve_entitlement(db, user_id)
    return bool(entitlement.is_paid) and entitlement.source != "trial"


# -- ownership ---------------------------------------------------------------------


def get_listing(db: Session, listing_id: uuid.UUID) -> models.SaleListing | None:
    return db.get(models.SaleListing, listing_id)


def owned_listing(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID
) -> models.SaleListing:
    listing = get_listing(db, listing_id)
    if listing is None or listing.owner_id != owner_id:
        raise MarketplaceNotFound("That listing isn't available.")
    return listing


def list_mine(db: Session, owner_id: uuid.UUID) -> list[models.SaleListing]:
    return list(
        db.scalars(
            select(models.SaleListing)
            .where(models.SaleListing.owner_id == owner_id)
            .order_by(models.SaleListing.updated_at.desc())
        ).all()
    )


# -- the orphan rule (owner spec 2026-10-25) -------------------------------------
#
# A listing is a SNAPSHOT: its data never depends on the source
# item, and deleting an item never rewrites a listing's fields.
# But a listing whose source item is GONE must stop DISPLAYING —
# Ryan deleted a listed test tool and its listing stayed on the
# board. Two layers enforce it: inventory's delete path ends the
# item's active listings (end_listings_for_source, below), and
# every read surface excludes orphans, so a listing orphaned by
# any other path (a raw row delete, an older build) still never
# shows. A SOLD listing is exempt in the owner's own view: it is
# a completed deal's record, and its history must stay visible.


def _existing_source_ids(
    db: Session, listings: list[models.SaleListing]
) -> set[tuple[str, uuid.UUID]]:
    """{(kind, id)} of the source records the given listings
    point at that still exist. Existence only — a listing's own
    fields are never read from the item (the snapshot rule)."""
    from app.modules.inventory import models as inventory_models

    wanted: dict[str, set[uuid.UUID]] = {}
    for listing in listings:
        if listing.source_id is not None and listing.source_kind:
            wanted.setdefault(listing.source_kind, set()).add(listing.source_id)
    existing: set[tuple[str, uuid.UUID]] = set()
    for kind, model in (
        ("tool", inventory_models.Tool),
        ("battery", inventory_models.Battery),
    ):
        ids = wanted.get(kind)
        if not ids:
            continue
        found = db.scalars(select(model.id).where(model.id.in_(ids))).all()
        existing.update((kind, found_id) for found_id in found)
    return existing


def _is_orphan(
    listing: models.SaleListing, existing: set[tuple[str, uuid.UUID]]
) -> bool:
    if listing.source_id is None or not listing.source_kind:
        return False
    return (listing.source_kind, listing.source_id) not in existing


def displayable(
    db: Session, listings: list[models.SaleListing]
) -> list[models.SaleListing]:
    """The owner's display set for My Listings: everything except
    orphans that never completed a sale. Sold orphans stay — the
    deal happened; the record is history, not clutter."""
    existing = _existing_source_ids(db, listings)
    return [
        listing
        for listing in listings
        if listing.status == "sold" or not _is_orphan(listing, existing)
    ]


def end_listings_for_source(
    db: Session, owner_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> int:
    """End every ACTIVE listing created from an inventory record
    (owner spec 2026-10-25): called by inventory's delete path in
    the SAME transaction (the caller commits). "Ends" = the
    removed state — the listing leaves the board and the counts;
    its row and snapshot fields are never rewritten. Sold
    listings are untouched: a completed deal's record, anchored
    by its interaction and ratings."""
    rows = list(
        db.scalars(
            select(models.SaleListing).where(
                models.SaleListing.owner_id == owner_id,
                models.SaleListing.source_kind == kind,
                models.SaleListing.source_id == item_id,
                models.SaleListing.status == "active",
            )
        ).all()
    )
    for row in rows:
        row.status = "removed"
        row.updated_at = _now()
    return len(rows)


def stats(db: Session, owner_id: uuid.UUID) -> dict:
    """The panel/home stat (Phase 3, 2026-10-24): my listings
    currently live on the board — status "active" only; sold
    and removed listings are history, not a count of what I
    have for sale. Orphan actives (source item gone) don't
    count either — they aren't on the board (2026-10-25)."""
    rows = list(
        db.scalars(
            select(models.SaleListing).where(
                models.SaleListing.owner_id == owner_id,
                models.SaleListing.status == "active",
            )
        ).all()
    )
    existing = _existing_source_ids(db, rows)
    count = sum(1 for row in rows if not _is_orphan(row, existing))
    return {"active_listings_count": int(count)}


# -- the inventory snapshot ---------------------------------------------------------


def snapshot_from_inventory(
    db: Session, owner, kind: str, item_id: uuid.UUID, listing_id: uuid.UUID
) -> dict:
    """Display facts + COPIED photos from one of the owner's
    inventory records. Raises MarketplaceError for anything that
    isn't the owner's tool/battery. Only name/brand/model and
    photo-kind attachments cross — the listing never sees (so can
    never leak) serials, notes, prices, or documents."""
    from app.modules.inventory import service as inventory_service

    if kind == "tool":
        record = inventory_service.get_tool(db, owner.id, item_id)
    elif kind == "battery":
        record = inventory_service.get_battery(db, owner.id, item_id)
    else:
        raise MarketplaceError("Listings can start from a tool or a battery.")
    if record is None:
        raise MarketplaceError(
            "That item isn't in your inventory — it may have been removed."
        )
    facts = {
        "title": (record.name or "")[:300],
        "brand": record.brand or "",
        "model": record.model or "",
        "attachments": [],
    }
    for item in record.attachments or []:
        if not isinstance(item, dict) or "key" not in item:
            continue
        if item.get("kind") not in ("photo", "", None):
            continue
        filename = item.get("filename") or storage.safe_filename(item["key"])
        dest_key = storage.object_key(
            str(owner.id), str(listing_id), "photo", filename,
            collection="marketplace",
        )
        try:
            storage.copy(item["key"], dest_key)
            facts["attachments"].append(
                {
                    "key": dest_key,
                    "filename": filename,
                    "kind": "photo",
                    "content_type": item.get("content_type", ""),
                    "size_bytes": item.get("size_bytes", 0),
                    "uploaded_at": _now().isoformat(),
                }
            )
        except Exception:
            # A photo that won't copy doesn't sink the listing:
            # the seller can upload fresh photos to the listing.
            continue
    return facts


# -- lifecycle -------------------------------------------------------------------


_EDITABLE = (
    "title",
    "description",
    "listing_type",
    "price",
    "condition",
    "brand",
    "model",
    "delivery_local_pickup",
    "delivery_ships",
    "public_area_label",
    "show_phone_override",
)


def _clean(fields: dict) -> dict:
    cleaned = {}
    for key in _EDITABLE:
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, str):
            value = value.strip()
        cleaned[key] = value
    return cleaned


def create_listing(db: Session, owner, fields: dict) -> models.SaleListing:
    """Create an ACTIVE listing (born published — the caller has
    already applied the publish gate). A source item pre-fills
    the snapshot facts; explicit fields in the same payload win
    (the seller may retitle before posting). Commits."""
    cleaned = _clean(fields)
    # The id is minted up front: the photo-copy namespace is
    # keyed by it, before the row exists.
    listing = models.SaleListing(id=uuid.uuid4(), owner_id=owner.id)
    source_kind = (fields.get("source_kind") or "").strip()
    source_id = fields.get("source_id")
    if source_kind and source_id is not None:
        facts = snapshot_from_inventory(
            db, owner, source_kind, source_id, listing.id
        )
        listing.title = facts["title"]
        listing.brand = facts["brand"]
        listing.model = facts["model"]
        listing.attachments = facts["attachments"]
        listing.source_kind = source_kind
        listing.source_id = source_id
    for key, value in cleaned.items():
        setattr(listing, key, value)
    if not (listing.title or "").strip():
        raise MarketplaceError("Give the listing a title.")
    # Fields the seller didn't send arrive as None pre-flush (the
    # column defaults land at INSERT); normalize the one the
    # validation below reads.
    if not listing.listing_type:
        listing.listing_type = "for_sale"
    if listing.listing_type not in models.LISTING_TYPES:
        raise MarketplaceError("Listing type must be “for sale” or “wanted”.")
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def update_listing(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID, fields: dict
) -> models.SaleListing:
    listing = owned_listing(db, owner_id, listing_id)
    cleaned = _clean(fields)
    if "listing_type" in cleaned and cleaned["listing_type"] not in models.LISTING_TYPES:
        raise MarketplaceError("Listing type must be “for sale” or “wanted”.")
    for key, value in cleaned.items():
        setattr(listing, key, value)
    if not (listing.title or "").strip():
        raise MarketplaceError("Give the listing a title.")
    listing.updated_at = _now()
    db.commit()
    db.refresh(listing)
    return listing


def delete_listing(db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID) -> bool:
    """Hard delete (the owner's eraser — history/restore rides
    the journal). Photos are retired through the journal's
    tombstone path exactly like parts (a restore brings the
    listing back with its pictures; under account deletion's
    permanent mode the objects are destroyed instead)."""
    from app.modules.core import journal

    listing = get_listing(db, listing_id)
    if listing is None or listing.owner_id != owner_id:
        return False
    journal.retire_record_files(db, owner_id, listing, entity_type="sale_listing")
    db.delete(listing)
    db.commit()
    return True


def remove_listing(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID
) -> models.SaleListing:
    listing = owned_listing(db, owner_id, listing_id)
    if listing.status == "active":
        listing.status = "removed"
        listing.updated_at = _now()
        db.commit()
        db.refresh(listing)
    return listing


def reactivate_listing(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID
) -> models.SaleListing:
    listing = owned_listing(db, owner_id, listing_id)
    if listing.status == "sold":
        raise MarketplaceError(
            "A sold listing stays sold — list the item again as a new listing."
        )
    listing.status = "active"
    listing.updated_at = _now()
    db.commit()
    db.refresh(listing)
    return listing


def mark_sold(
    db: Session,
    seller,
    listing_id: uuid.UUID,
    *,
    buyer_user_id: uuid.UUID | None = None,
    buyer_account_number: str | None = None,
) -> tuple[models.SaleListing, models.DealInteraction | None]:
    """Mark sold. The buyer is identified by picked user id
    (from the listing's thread participants) or by EXACT account
    number (the platform's no-enumeration pattern). With a buyer,
    the deal becomes a rateable interaction; without one, the
    listing still closes honestly — it just can't be rated.
    Commits."""
    listing = owned_listing(db, seller.id, listing_id)
    if listing.status == "sold":
        raise MarketplaceError("That listing is already marked sold.")
    buyer = None
    if buyer_user_id is not None:
        buyer = core_service.get_user_by_id(db, buyer_user_id)
        if buyer is None or not buyer.is_active:
            raise MarketplaceError("That buyer isn't available.")
    elif buyer_account_number:
        buyer = core_service.get_user_by_account_number(
            db, buyer_account_number.strip()
        )
        if buyer is None or not buyer.is_active:
            raise MarketplaceError(
                "No account with that number — check the number and try again."
            )
    if buyer is not None and buyer.id == seller.id:
        raise MarketplaceError("You can't sell to yourself.")
    listing.status = "sold"
    listing.buyer_id = buyer.id if buyer is not None else None
    listing.sold_at = _now()
    listing.updated_at = _now()
    db.commit()
    db.refresh(listing)
    interaction = None
    if buyer is not None:
        interaction, _created = reputation.create_interaction(
            db,
            user_a=seller,
            user_b=buyer,
            source="listing",
            dedupe_key=f"listing:{listing.id}",
            listing_id=listing.id,
            context_title=listing.title,
        )
    return listing, interaction


def buyer_candidates(
    db: Session, owner_id: uuid.UUID, listing_id: uuid.UUID
) -> list[dict]:
    """The people the seller could pick as the buyer: the OTHER
    participants of threads anchored to this listing (they're
    the ones who actually inquired)."""
    from app.modules.messaging import models as messaging_models

    listing = owned_listing(db, owner_id, listing_id)
    threads = list(
        db.scalars(
            select(messaging_models.MessageThread).where(
                messaging_models.MessageThread.anchor_type == "listing",
                messaging_models.MessageThread.anchor_id == listing.id,
            )
        ).all()
    )
    seen: dict[uuid.UUID, dict] = {}
    for thread in threads:
        for participant in (thread.participant_low_id, thread.participant_high_id):
            if participant == owner_id or participant in seen:
                continue
            user = core_service.get_user_by_id(db, participant)
            if user is not None:
                seen[participant] = {"user_id": user.id, "name": user.name}
    return sorted(seen.values(), key=lambda row: row["name"].lower())


# -- serialization -----------------------------------------------------------------


def _photos(listing: models.SaleListing) -> list[dict]:
    photos = []
    for item in listing.attachments or []:
        if not isinstance(item, dict) or "key" not in item:
            continue
        if item.get("kind") not in ("photo", "", None):
            continue
        photos.append(
            {
                "filename": item.get("filename", ""),
                "url": storage.presigned_get_url(item["key"]),
            }
        )
    return photos


def resolve_phone(listing: models.SaleListing, seller) -> str | None:
    """The pool's chain: listing override > profile toggle >
    hidden — and only a number the seller actually recorded."""
    show = listing.show_phone_override
    if show is None:
        show = bool(seller.show_phone)
    if show and (seller.contact_phone or "").strip():
        return seller.contact_phone
    return None


def resolve_area(listing: models.SaleListing, seller) -> str | None:
    area = (listing.public_area_label or "").strip() or (
        seller.public_area_label or ""
    ).strip()
    return area or None


def serialize_public(db: Session, listing: models.SaleListing, seller) -> dict:
    """THE board payload — exact keys (LISTING_KEYS). Only what
    the seller put on the listing: snapshot facts, their price,
    their words, their opt-in phone, and their reputation
    summary (the ONE aggregate function — reputation.py)."""
    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "listing_type": listing.listing_type,
        "price": listing.price,
        "condition": listing.condition,
        "brand": listing.brand,
        "model": listing.model,
        "delivery_local_pickup": listing.delivery_local_pickup,
        "delivery_ships": listing.delivery_ships,
        "area_label": resolve_area(listing, seller),
        "photos": _photos(listing),
        "seller_id": seller.id,
        "seller_name": seller.name,
        "seller_member_since": seller.created_at,
        "seller_reputation": reputation.summary_for(db, seller.id),
        "seller_currency": core_money.normalize_currency(
            getattr(seller, "currency", "USD")
        ),
        "phone": resolve_phone(listing, seller),
        "created_at": listing.created_at,
        "updated_at": listing.updated_at,
    }


def serialize_owner(db: Session, listing: models.SaleListing, seller) -> dict:
    """The owner's view: the public shape plus the lifecycle and
    the raw overrides (so the edit form can show what it set)."""
    view = serialize_public(db, listing, seller)
    buyer_name = None
    if listing.buyer_id is not None:
        buyer = core_service.get_user_by_id(db, listing.buyer_id)
        buyer_name = buyer.name if buyer is not None else None
    view.update(
        {
            "status": listing.status,
            "source_kind": listing.source_kind,
            "source_id": listing.source_id,
            "buyer_id": listing.buyer_id,
            "buyer_name": buyer_name,
            "sold_at": listing.sold_at,
            "area_override": listing.public_area_label,
            "show_phone_override": listing.show_phone_override,
        }
    )
    return view


# -- the board ---------------------------------------------------------------------


def _matches(listing: models.SaleListing, area: str | None, filters: dict) -> bool:
    if filters.get("listing_type") and listing.listing_type != filters["listing_type"]:
        return False
    price = listing.price
    if filters.get("price_min") is not None:
        if price is None or price < Decimal(str(filters["price_min"])):
            return False
    if filters.get("price_max") is not None:
        if price is None or price > Decimal(str(filters["price_max"])):
            return False
    if area is not None:
        needle = (filters.get("area") or "").strip().lower()
        if needle and needle not in area.lower():
            return False
    q = (filters.get("q") or "").strip().lower()
    if q:
        terms = q.split()
        haystacks = [
            listing.title.lower(),
            (listing.description or "").lower(),
            (listing.brand or "").lower(),
            (listing.model or "").lower(),
            (listing.condition or "").lower(),
        ]
        if not all(any(term in field for field in haystacks) for term in terms):
            return False
    return True


def search_listings(
    db: Session,
    *,
    q: str | None = None,
    listing_type: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    area: str | None = None,
    seller_id: uuid.UUID | None = None,
    sort: str = "newest",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Every active listing, newest first (or by price / seller
    rating). The publish gate is re-checked per seller at read
    time (a lapsed plan stops listing while enforcement is on);
    sellers resolve once per request. Rating sort never HIDES a
    seller — unrated sellers sort last among equals, the numbers
    speak (community suite rule)."""
    if sort not in _SORTS:
        sort = "newest"
    filters = {
        "q": q,
        "listing_type": listing_type,
        "price_min": price_min,
        "price_max": price_max,
        "area": area,
    }
    stmt = (
        select(models.SaleListing)
        .where(models.SaleListing.status == "active")
        .order_by(models.SaleListing.updated_at.desc())
    )
    if seller_id is not None:
        stmt = stmt.where(models.SaleListing.owner_id == seller_id)
    candidates = list(db.scalars(stmt.limit(_CANDIDATE_CAP)).all())

    sellers: dict[uuid.UUID, object] = {}
    publishable: dict[uuid.UUID, bool] = {}

    def seller_of(owner_id: uuid.UUID):
        if owner_id not in sellers:
            sellers[owner_id] = core_service.get_user_by_id(db, owner_id)
        return sellers[owner_id]

    # Orphans never reach the board (owner spec 2026-10-25): a
    # listing whose source item is gone stops displaying even
    # if its row was never ended by the delete cascade.
    existing_sources = _existing_source_ids(db, candidates)

    rows: list[tuple[models.SaleListing, object]] = []
    for listing in candidates:
        if _is_orphan(listing, existing_sources):
            continue
        seller = seller_of(listing.owner_id)
        if seller is None or not seller.is_active:
            continue
        if listing.owner_id not in publishable:
            publishable[listing.owner_id] = can_publish(db, listing.owner_id)
        if not publishable[listing.owner_id]:
            continue
        if not _matches(listing, resolve_area(listing, seller), filters):
            continue
        rows.append((listing, seller))

    if sort == "price_asc":
        rows.sort(
            key=lambda pair: (
                pair[0].price is None,
                pair[0].price if pair[0].price is not None else Decimal(0),
            )
        )
    elif sort == "price_desc":
        rows.sort(
            key=lambda pair: (
                pair[0].price is None,
                -(pair[0].price) if pair[0].price is not None else Decimal(0),
            )
        )
    elif sort == "rating":
        summaries = {
            seller.id: reputation.summary_for(db, seller.id)
            for _listing, seller in rows
        }
        rows.sort(
            key=lambda pair: (
                summaries[pair[1].id]["average"] is None,
                -(summaries[pair[1].id]["average"] or 0),
                -summaries[pair[1].id]["completed_deals"],
            )
        )
    listings = [serialize_public(db, listing, seller) for listing, seller in rows]
    cap = max(1, min(limit, _LISTING_CAP))
    return listings[offset : offset + cap]


def get_public_listing(
    db: Session, listing_id: uuid.UUID | None
) -> models.SaleListing | None:
    """The listing when it is a LIVE board listing (active, its
    seller still publishable, the board switched on), else None
    — the anchor resolver messaging uses, mirroring the pool's."""
    if listing_id is None or not marketplace_enabled(db):
        return None
    listing = get_listing(db, listing_id)
    if listing is None or listing.status != "active":
        return None
    if _is_orphan(listing, _existing_source_ids(db, [listing])):
        return None
    if not can_publish(db, listing.owner_id):
        return None
    return listing


# -- export ------------------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The data export's marketplace.json: my listings (with the
    stored attachment metadata — core's export fetches the photo
    files itself), the interactions I took part in, and every
    rating I gave or received (published or not — it's MY data;
    the blind rule governs what OTHER people see, not my own
    backup)."""
    listings = list_mine(db, owner_id)
    interactions = reputation.interactions_for(db, owner_id)
    given = list(
        db.scalars(
            select(models.Rating)
            .where(models.Rating.rater_id == owner_id)
            .order_by(models.Rating.created_at)
        ).all()
    )
    received = list(
        db.scalars(
            select(models.Rating)
            .where(models.Rating.ratee_id == owner_id)
            .order_by(models.Rating.created_at)
        ).all()
    )

    def rating_view(row: models.Rating) -> dict:
        return {
            "id": str(row.id),
            "interaction_id": str(row.interaction_id),
            "rater_id": str(row.rater_id),
            "ratee_id": str(row.ratee_id),
            "stars": row.stars,
            "text": row.text,
            "published_at": row.published_at,
            "created_at": row.created_at,
        }

    return {
        "listings": [
            {
                "id": str(listing.id),
                "listing_type": listing.listing_type,
                "title": listing.title,
                "description": listing.description,
                "price": listing.price,
                "condition": listing.condition,
                "brand": listing.brand,
                "model": listing.model,
                "delivery_local_pickup": listing.delivery_local_pickup,
                "delivery_ships": listing.delivery_ships,
                "public_area_label": listing.public_area_label,
                "show_phone_override": listing.show_phone_override,
                "source_kind": listing.source_kind,
                "source_id": str(listing.source_id) if listing.source_id else None,
                "status": listing.status,
                "buyer_id": str(listing.buyer_id) if listing.buyer_id else None,
                "sold_at": listing.sold_at,
                "attachments": list(listing.attachments or []),
                "created_at": listing.created_at,
                "updated_at": listing.updated_at,
            }
            for listing in listings
        ],
        "interactions": [
            {
                "id": str(row.id),
                "source": row.source,
                "context_title": row.context_title,
                "other_user_id": str(
                    row.party_high_id if row.party_low_id == owner_id
                    else row.party_low_id
                ),
                "other_name": (
                    row.party_high_name if row.party_low_id == owner_id
                    else row.party_low_name
                ),
                "completed_at": row.completed_at,
            }
            for row in interactions
        ],
        "ratings_given": [rating_view(row) for row in given],
        "ratings_received": [rating_view(row) for row in received],
    }
