"""Health check price gap (owner order, 2026-11-12).

Price is a REQUIRED health-check field — the owner named it in
his own column spec for the Health Check list ("column 1 the
name, column 2 the photo, column 3 the price, and so on — every
piece of information required for the health check to pass"),
after two earlier builds shipped the list without it by reading
the columns off what the scan happened to check. The scan now
flags it end to end, and these tests pin the rule:

  * THE RULE — an ACTIVE tool or battery with no purchase price
    recorded flags "price". "No price recorded" is
    ``purchase_price is None`` — the same reading the Inventory
    list's PRICE column and the purchase-cost valuations use. A
    stored 0.00 is a recorded price (a free item) and does NOT
    flag: zero is distinguishable from unset because the column
    is nullable and unset stays NULL.
  * THE SHAPE — the gap rides the same `missing` list (seated
    between photo and purchase_date, the list's column order)
    and the same `counts` dict under "price".
  * EVERY CONSUMER AGREES — the Home due read carries the price
    gap verbatim, and the claim-readiness counts read their
    value gap off the scan's price count (one definition).
  * THE FIX SAVES — the fix-all wizard's price step rides the
    item's own PUT with {purchase_price}; after it, the rescan
    clears the gap (and only the gap).
"""

import itertools
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.claims import readiness
from app.modules.core import models as core_models
from app.modules.core import tiers
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(9100)


def _make_user(db, account_types=(MECHANIC,), *, tier="normal", name="Price Owner"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"price-{n}@example.com",
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        role=tiers.role_for_tier(tier),
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db)


def _tool(client, user, **payload):
    payload.setdefault("name", "Price wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Price pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _give_photo(db, kind, item_id, key):
    model = inventory_models.Tool if kind == "tool" else inventory_models.Battery
    row = db.get(model, uuid.UUID(item_id))
    row.attachments = [
        {
            "kind": "photo",
            "key": key,
            "filename": "p.jpg",
            "content_type": "image/jpeg",
        }
    ]
    db.commit()


def _scan(client, user):
    resp = client.get("/api/inventory/health-check", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _due(client, user):
    resp = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _complete_tool(client, user, db, name, **over):
    """A tool with every checked field — except, by default, a
    price: each test decides the price state explicitly."""
    payload = {
        "name": name,
        "model": "M1",
        "serial_number": "S1",
        "purchase_date": "2026-01-15",
    }
    payload.update(over)
    tool = _tool(client, user, **payload)
    _give_photo(db, "tool", tool["id"], f"price-k-{tool['id']}")
    return tool


def test_scan_flags_priceless_tool_and_battery(client, owner, db):
    _complete_tool(client, owner, db, "No price tool")
    pack = _battery(
        client, owner, name="No price pack", model="M18",
        serial_number="B1", purchase_date="2026-02-01",
    )
    _give_photo(db, "battery", pack["id"], "price-k-pack")

    scan = _scan(client, owner)
    by_name = {row["name"]: row for row in scan["items"]}
    assert by_name["No price tool"]["missing"] == ["price"]
    assert by_name["No price pack"]["missing"] == ["price"]
    assert scan["counts"]["price"] == 2
    assert scan["total"] == 2


def test_scan_does_not_flag_priced_items(client, owner, db):
    _complete_tool(client, owner, db, "Priced tool", purchase_price="129.99")
    pack = _battery(
        client, owner, name="Priced pack", model="M18",
        serial_number="B1", purchase_date="2026-02-01",
        purchase_price="89.50",
    )
    _give_photo(db, "battery", pack["id"], "price-k-priced-pack")

    scan = _scan(client, owner)
    assert scan["items"] == [] and scan["total"] == 0
    assert scan["counts"]["price"] == 0


def test_zero_price_is_a_recorded_price(client, owner, db):
    # The rule, pinned: the column is nullable, so a stored
    # 0.00 (a free / gifted item) is distinguishable from unset
    # and counts as HAVING a price — the Inventory list reads
    # it the same way.
    _complete_tool(client, owner, db, "Free tool", purchase_price="0")
    row = db.scalars(
        select(inventory_models.Tool).where(
            inventory_models.Tool.name == "Free tool"
        )
    ).one()
    assert row.purchase_price == Decimal("0")

    scan = _scan(client, owner)
    assert scan["items"] == [] and scan["counts"]["price"] == 0


def test_price_gap_seats_between_photo_and_purchase_date(client, owner):
    _tool(client, owner, name="Bare")  # every gap
    scan = _scan(client, owner)
    [row] = scan["items"]
    assert row["missing"] == [
        "identifier", "photo", "price", "purchase_date",
    ]


def test_set_with_piece_and_price_gaps_surfaces_both(client, owner, db):
    toolset = _tool(
        client, owner, name="Priceless set", model="SET1",
        serial_number="SETSN", purchase_date="2026-02-01", is_set=True,
        pieces=[
            {"kind": "core", "name": "10mm socket", "part_number": "P10"},
        ],
    )
    _give_photo(db, "tool", toolset["id"], "price-k-set")
    scan = _scan(client, owner)
    [row] = scan["items"]
    assert row["missing"] == ["price"]
    assert row["pieces_missing_serial"] == ["10mm socket"]
    assert scan["counts"]["price"] == 1
    assert scan["counts"]["piece_serial"] == 1


def test_due_read_carries_the_price_gap_verbatim(client, owner, db):
    _complete_tool(client, owner, db, "No price tool")
    due = _due(client, owner)
    scan = _scan(client, owner)
    assert due["counts"] == scan["counts"]
    assert due["counts"]["price"] == 1
    [row] = due["items"]
    assert row["missing"] == ["price"]


def test_readiness_value_gap_is_the_scans_price_count(client, owner, db):
    _complete_tool(client, owner, db, "No price tool")
    _tool(client, owner, name="Bare")  # price + every other gap
    gaps = readiness.readiness_gap_counts(db, owner.id)
    assert gaps["value"] == 2
    assert gaps["value"] == _scan(client, owner)["counts"]["price"]


def test_wizard_price_save_clears_the_gap(client, owner, db):
    # The fix-all wizard's price step saves through the item's
    # own PUT with {purchase_price} — the exact call the wizard
    # makes — for a tool and a battery alike.
    tool = _complete_tool(client, owner, db, "No price tool")
    pack = _battery(
        client, owner, name="No price pack", model="M18",
        serial_number="B1", purchase_date="2026-02-01",
    )
    _give_photo(db, "battery", pack["id"], "price-k-wiz-pack")
    assert _scan(client, owner)["counts"]["price"] == 2

    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={"purchase_price": "129.99"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/api/inventory/batteries/{pack['id']}",
        json={"purchase_price": "89.50"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text

    scan = _scan(client, owner)
    assert scan["items"] == [] and scan["counts"]["price"] == 0
    row = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    assert row.purchase_price == Decimal("129.99")
