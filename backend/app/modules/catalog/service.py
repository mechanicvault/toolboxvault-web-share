"""The community product catalog (wave 4) — DERIVED, never
hand-entered, and computed from live items at read time.

For a (brand, model) key, the catalog weighs the items of every
user who contributes (users.catalog_contribute, default ON —
Settings -> Sharing carries the switch and the exact field
list). Per SPEC FIELD (category, size, msrp — the only fields
that ever contribute; serials, purchase prices, photos and
notes NEVER do), a value becomes a community suggestion when
>= MIN_SUPPORTERS DISTINCT users' items agree on it under
normalized comparison.

Because aggregation reads live rows, opting out removes a
user's weight from every aggregate immediately — there are no
contribution copies to scrub — and a deleted item stops
counting the moment it's gone.

SERVICE INTERFACE (consumed by lookup.py and the routes):
  suggestions_for(db, brand, model) -> {
      "brand": ..., "model": ..., "contributors": int,
      "fields": {field: {"value": ..., "supporters": int}},
  }
Only fields that clear the threshold appear in "fields".
"""

from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from app.modules.catalog.normalize import (
    norm_brand,
    norm_model,
    norm_money,
    norm_value,
)
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models

# A spec value needs this many DISTINCT contributing users
# behind it before the catalog will speak for it. One user's
# shelf is an opinion; two agreeing is a community fact.
MIN_SUPPORTERS = 2

# The only fields that ever contribute (owner brief, wave 4).
SPEC_FIELDS = ("category", "size", "msrp")


def suggestions_for(db: Session, brand: str, model: str) -> dict:
    """Community suggestions for one product key. Empty fields
    when nothing clears the threshold (or the key is unknown)."""
    result: dict = {
        "brand": brand or "",
        "model": model or "",
        "contributors": 0,
        "fields": {},
    }
    key_brand = norm_brand(brand)
    key_model = norm_model(model)
    if not key_brand or not key_model:
        return result

    contributor_ids = set(
        db.scalars(
            select(core_models.User.id).where(
                core_models.User.catalog_contribute.is_(True)
            )
        )
    )
    if not contributor_ids:
        return result

    # Narrow in SQL on the primary model (case-insensitive exact —
    # the discriminating half of the key), then judge brand +
    # model under full normalization in Python over the small set.
    model_fold = (model or "").strip().lower()
    rows: list[tuple] = []  # (owner_id, category, size, msrp)
    # Tools carry `size`; batteries don't have the column (their
    # spec axis is platform/voltage) — they contribute category
    # and msrp, with size always absent.
    queries = [
        select(
            inventory_models.Tool.owner_id,
            inventory_models.Tool.brand,
            inventory_models.Tool.model,
            inventory_models.Tool.category,
            inventory_models.Tool.size,
            inventory_models.Tool.msrp,
        ).where(
            inventory_models.Tool.owner_id.in_(contributor_ids),
            func.lower(inventory_models.Tool.model) == model_fold,
        ),
        select(
            inventory_models.Battery.owner_id,
            inventory_models.Battery.brand,
            inventory_models.Battery.model,
            inventory_models.Battery.category,
            literal(None),
            inventory_models.Battery.msrp,
        ).where(
            inventory_models.Battery.owner_id.in_(contributor_ids),
            func.lower(inventory_models.Battery.model) == model_fold,
        ),
    ]
    for stmt in queries:
        for owner_id, raw_brand, raw_model, category, size, msrp in db.execute(stmt):
            if norm_brand(raw_brand) != key_brand:
                continue
            if norm_model(raw_model) != key_model:
                continue
            rows.append((owner_id, category, size, msrp))

    contributors = {owner_id for owner_id, *_ in rows}
    result["contributors"] = len(contributors)
    if len(contributors) < MIN_SUPPORTERS:
        return result

    # Per field: normalized value -> {owners}, and the display
    # spelling counter (the value as its supporters actually
    # typed it — the catalog echoes the community's own casing).
    field_owners: dict[str, dict[str, set]] = {
        field: defaultdict(set) for field in SPEC_FIELDS
    }
    field_spellings: dict[str, dict[str, Counter]] = {
        field: defaultdict(Counter) for field in SPEC_FIELDS
    }
    for owner_id, category, size, msrp in rows:
        raw = {"category": category, "size": size, "msrp": msrp}
        for field in SPEC_FIELDS:
            value = raw[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if field == "msrp":
                normalized = norm_money(value)
                if normalized is None:
                    continue
                display = normalized
            else:
                normalized = norm_value(str(value))
                if not normalized:
                    continue
                display = str(value).strip()
            field_owners[field][normalized].add(owner_id)
            field_spellings[field][normalized][display] += 1

    for field in SPEC_FIELDS:
        best_key = None
        best_owners: set = set()
        for normalized, owners in field_owners[field].items():
            if len(owners) > len(best_owners):
                best_key, best_owners = normalized, owners
        if best_key is None or len(best_owners) < MIN_SUPPORTERS:
            continue
        display = field_spellings[field][best_key].most_common(1)[0][0]
        result["fields"][field] = {
            "value": display if field != "msrp" else _money_out(display),
            "supporters": len(best_owners),
        }
    return result


def _money_out(normalized: str):
    """MSRP leaves as a number when it's whole, else a float with
    cents — JSON-friendly either way, exact at 2dp."""
    amount = Decimal(normalized)
    return int(amount) if amount == amount.to_integral_value() else float(amount)
