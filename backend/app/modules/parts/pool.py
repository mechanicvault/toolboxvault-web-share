"""Community Parts pool (owner, 2026-10-19): the public face of
the Used Parts shelf.

Owners opt parts IN — by a per-part override, per category, or
for the whole shelf ("choose all") — and the pool is the
community's searchable index of what's available, by year / make
/ model / engine. The private shelf is untouched by all of this:
a part's storage location, its custom fields, and anything the
owner didn't publish never leave the owner's own surfaces.

THE PRIVACY CONTRACT (test-pinned, exact keys):
  A pool listing carries ONLY: id, title, quantity, condition,
  category, year, make, model, engine, asking_price, area_label,
  photos (filename + fresh read URL), seller_id, seller_name,
  seller_member_since, phone, created_at, updated_at.
  - The storage location tree NEVER appears (not the node, not
    the path): where a part sits is the owner's business.
  - The owner's notes are SEARCHED but never SHOWN — a note is
    where people write "bought from Dave, owes me a favor".
  - The seller's phone appears ONLY while they opted in (their
    profile toggle, or the part's override).
  - Email never appears anywhere.

THE PUBLISH GATE: publishing is a PAID contribution (community
suite rule). The gate mirrors the entitlement item-cap pattern
exactly: the check runs through billing's resolver and bites
only while the entitlements enforcement switch is ON — pre-launch
testing stays open. "Paid" means the resolver's winning source
is a paying one; a TRIAL never counts (stripe subscription,
lifetime, admin grant, redeem grant, earned referral months all
do). The gate is checked wherever a change would PUBLISH: pool
settings writes, part create/update — and again at READ time, so
a seller whose plan lapses while enforcement is on stops listing
until they're paid again (the same live-resolution rule the
item cap lives by).

THE POOL SWITCH: `community.parts_pool_enabled` (system setting,
default True) hides the pool entirely — both read routes 404 and
the owner's own parts report no public state beyond the raw
settings. The parts module's global switch hides it too.

Search is dialect-free Python over a bounded candidate set — the
parts list's own rule, for the same reason: identical behavior on
Postgres and SQLite beats a second search implementation.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.modules.core import money as core_money
from app.modules.core import service as core_service
from app.modules.parts import models

POOL_ENABLED_KEY = "community.parts_pool_enabled"
VISIBILITIES = ("public", "private")

# The exact listing payload contract (see module docstring).
LISTING_KEYS = (
    "id",
    "title",
    "quantity",
    "condition",
    "category",
    "year",
    "make",
    "model",
    "engine",
    "asking_price",
    "area_label",
    "photos",
    "seller_id",
    "seller_name",
    "seller_member_since",
    "phone",
    "created_at",
    "updated_at",
)

_CANDIDATE_CAP = 5000
_LISTING_CAP = 200


# -- settings + resolution ---------------------------------------------------------


def pool_enabled(db: Session) -> bool:
    """The operator's pool switch (+ the parts module's global
    switch): either off hides the pool entirely."""
    from app.modules.billing import entitlements
    from app.modules.core import module_control

    if not module_control.globally_enabled(db, "parts"):
        return False
    return bool(entitlements.get_setting(db, POOL_ENABLED_KEY, True))


def settings_for(
    db: Session, owner_id: uuid.UUID
) -> models.PartPoolSettings | None:
    """The owner's pool settings row, or None when they have
    never touched the pool (which resolves exactly like the
    defaults: private)."""
    return db.scalars(
        select(models.PartPoolSettings).where(
            models.PartPoolSettings.owner_id == owner_id
        )
    ).first()


def get_settings(db: Session, owner_id: uuid.UUID) -> models.PartPoolSettings:
    """The owner's pool settings, created lazily (defaults:
    everything private)."""
    row = settings_for(db, owner_id)
    if row is None:
        row = models.PartPoolSettings(owner_id=owner_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def settings_view(row: models.PartPoolSettings) -> dict:
    return {
        "default_visibility": row.default_visibility,
        "category_visibility": dict(row.category_visibility or {}),
    }


def resolve_visibility(
    part: models.Part, settings: models.PartPoolSettings | None
) -> str:
    """entry override > category setting > owner default."""
    if part.visibility in VISIBILITIES:
        return part.visibility
    if settings is not None and part.category:
        category_value = (settings.category_visibility or {}).get(part.category)
        if category_value in VISIBILITIES:
            return category_value
    if settings is not None and settings.default_visibility in VISIBILITIES:
        return settings.default_visibility
    return "private"


def is_public(
    db: Session, part: models.Part, settings: models.PartPoolSettings | None = None
) -> bool:
    if settings is None:
        settings = settings_for(db, part.owner_id)
    return resolve_visibility(part, settings) == "public"


# -- the publish gate ---------------------------------------------------------------


def can_publish(db: Session, user_id: uuid.UUID) -> bool:
    """May this account have publicly listed parts RIGHT NOW?
    Enforcement OFF (pre-launch) → everyone may (the item-cap
    pattern). Enforcement ON → a paid plan from a paying source;
    a trial never counts."""
    from app.modules.billing import entitlements

    if not entitlements.enforcement_enabled(db):
        return True
    entitlement = entitlements.resolve_entitlement(db, user_id)
    return bool(entitlement.is_paid) and entitlement.source != "trial"


def would_publish_count(
    db: Session,
    owner_id: uuid.UUID,
    settings: models.PartPoolSettings,
    *,
    extra_part: models.Part | None = None,
) -> int:
    """How many of the owner's parts resolve public under the
    GIVEN (possibly unsaved) settings — the gate's question for a
    settings write. `extra_part` substitutes one part's pending
    state (used by part create/update through the same math)."""
    parts = list(
        db.scalars(
            select(models.Part).where(models.Part.owner_id == owner_id)
        ).all()
    )
    count = 0
    for part in parts:
        if extra_part is not None and part.id == extra_part.id:
            part = extra_part
        if resolve_visibility(part, settings) == "public":
            count += 1
    if extra_part is not None and all(p.id != extra_part.id for p in parts):
        if resolve_visibility(extra_part, settings) == "public":
            count += 1
    return count


# -- listings -------------------------------------------------------------------------


def serialize_listing(
    part: models.Part, seller, settings: models.PartPoolSettings | None
) -> dict:
    """THE listing payload — exact keys, privacy contract in the
    module docstring. `seller` is the owner's core User row."""
    show_phone = part.show_phone_override
    if show_phone is None:
        show_phone = bool(seller.show_phone)
    phone = (
        seller.contact_phone
        if (show_phone and (seller.contact_phone or "").strip())
        else None
    )
    area = (part.public_area_label or "").strip() or (
        seller.public_area_label or ""
    ).strip()
    photos = []
    for item in part.attachments or []:
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
    return {
        "id": part.id,
        "title": part.title,
        "quantity": part.quantity,
        "condition": part.condition,
        "category": part.category,
        "year": part.year,
        "make": part.make,
        "model": part.model,
        "engine": part.engine,
        "asking_price": part.asking_price,
        "area_label": area or None,
        "photos": photos,
        "seller_id": seller.id,
        "seller_name": seller.name,
        "seller_member_since": seller.created_at,
        # Wave 3 currency: the asking price is in the SELLER's
        # currency (v1 semantics — amounts live in their owner's
        # currency); viewers label + hint from this code.
        "seller_currency": core_money.normalize_currency(
            getattr(seller, "currency", "USD")
        ),
        "phone": phone,
        "created_at": part.created_at,
        "updated_at": part.updated_at,
    }


def _matches(part: models.Part, filters: dict) -> bool:
    if filters.get("year") is not None and part.year != filters["year"]:
        return False
    for key in ("make", "model", "engine"):
        needle = (filters.get(key) or "").strip().lower()
        if needle and needle not in (getattr(part, key) or "").lower():
            return False
    category = (filters.get("category") or "").strip().lower()
    if category and (part.category or "").strip().lower() != category:
        return False
    q = (filters.get("q") or "").strip().lower()
    if q:
        terms = q.split()
        haystacks = [
            part.title.lower(),
            (part.notes or "").lower(),
            (part.make or "").lower(),
            (part.model or "").lower(),
            (part.engine or "").lower(),
            (part.category or "").lower(),
            (part.condition or "").lower(),
        ]
        if not all(any(term in field for field in haystacks) for term in terms):
            return False
    return True


def search_listings(
    db: Session,
    *,
    q: str | None = None,
    year: int | None = None,
    make: str | None = None,
    model: str | None = None,
    engine: str | None = None,
    category: str | None = None,
    seller_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Every user's publicly listed parts, newest first. The
    publish gate is re-checked per seller at read time (a lapsed
    plan stops listing while enforcement is on — see the module
    docstring); sellers are resolved once per request."""
    filters = {
        "q": q,
        "year": year,
        "make": make,
        "model": model,
        "engine": engine,
        "category": category,
    }
    stmt = select(models.Part).order_by(models.Part.updated_at.desc())
    if seller_id is not None:
        stmt = stmt.where(models.Part.owner_id == seller_id)
    candidates = list(db.scalars(stmt.limit(_CANDIDATE_CAP)).all())

    sellers: dict[uuid.UUID, object] = {}
    settings_by_owner: dict[uuid.UUID, models.PartPoolSettings | None] = {}
    publishable: dict[uuid.UUID, bool] = {}
    if candidates:
        owner_ids = {part.owner_id for part in candidates}
        for row in db.scalars(
            select(models.PartPoolSettings).where(
                models.PartPoolSettings.owner_id.in_(owner_ids)
            )
        ).all():
            settings_by_owner[row.owner_id] = row

    def seller_of(owner_id: uuid.UUID):
        if owner_id not in sellers:
            sellers[owner_id] = core_service.get_user_by_id(db, owner_id)
        return sellers[owner_id]

    listings: list[dict] = []
    for part in candidates:
        settings = settings_by_owner.get(part.owner_id)
        if resolve_visibility(part, settings) != "public":
            continue
        seller = seller_of(part.owner_id)
        if seller is None or not seller.is_active:
            continue
        if part.owner_id not in publishable:
            publishable[part.owner_id] = can_publish(db, part.owner_id)
        if not publishable[part.owner_id]:
            continue
        if not _matches(part, filters):
            continue
        listings.append(serialize_listing(part, seller, settings))
    cap = max(1, min(limit, _LISTING_CAP))
    return listings[offset : offset + cap]


def get_public_listing_part(
    db: Session, part_id: uuid.UUID | None
) -> tuple[models.Part, models.PartPoolSettings | None] | None:
    """(part, its owner's pool settings) when the part is a live
    public listing, else None — the anchor resolver messaging
    uses, so a thread can only anchor to a listing that really
    is public (and its seller still publishable) right now."""
    if part_id is None or not pool_enabled(db):
        return None
    part = db.get(models.Part, part_id)
    if part is None:
        return None
    settings = settings_for(db, part.owner_id)
    if resolve_visibility(part, settings) != "public":
        return None
    if not can_publish(db, part.owner_id):
        return None
    return part, settings
