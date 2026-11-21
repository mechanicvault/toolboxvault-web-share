"""Wave 4 — duplicate detection + smart search (both
DETERMINISTIC, no AI anywhere in either path).

Duplicate pins:
  - same normalized brand+model AND same serial -> 409
    {code: possible_duplicate, existing: [...]};
  - same brand+model AND same UPC -> 409;
  - same brand+model ALONE never blocks (two identical ratchets
    are legitimate);
  - different serial + different UPC -> created;
  - ?force=true creates anyway;
  - another owner's identical item never blocks;
  - the check is at the create doorway for BOTH kinds.

Smart-search pins:
  - the parser reads the owner's own vocabulary: brand/category
    chips, "in <location>", standing words, "under $N" prices,
    "tagged <name>";
  - unparseable text falls back to plain text search;
  - the chips ride the X-Search-Chips header;
  - a parsed standing actually filters.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import smart_search
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Dup User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000421", "dup@example.com")


@pytest.fixture()
def stranger(db):
    return _make_user(db, "TV-M-000422", "stranger@example.com")


def _tool_payload(**overrides):
    payload = {
        "name": "Ratchet",
        "brand": "Snap-on",
        "model": "FHR80",
        "serial_number": "SN-001",
        "category": "Ratchets",
    }
    payload.update(overrides)
    return payload


def _create_tool(client, user, **overrides):
    return client.post(
        "/api/inventory",
        json=_tool_payload(**overrides),
        headers=auth_headers(user),
    )


# -- duplicates ---------------------------------------------------------------


def test_same_serial_blocks_with_409(client, owner):
    assert _create_tool(client, owner).status_code == 201
    resp = _create_tool(client, owner, name="Ratchet again")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "possible_duplicate"
    assert len(detail["existing"]) == 1
    assert detail["existing"][0]["matched_on"] == "serial"
    assert detail["existing"][0]["name"] == "Ratchet"


def test_same_upc_blocks(client, owner):
    assert (
        _create_tool(client, owner, serial_number="", upc="012345678905").status_code
        == 201
    )
    resp = _create_tool(client, owner, serial_number="OTHER-9", upc="0123 4567 8905")
    assert resp.status_code == 409
    assert resp.json()["detail"]["existing"][0]["matched_on"] == "upc"


def test_brand_model_alone_never_blocks(client, owner):
    assert _create_tool(client, owner).status_code == 201
    # Identical brand+model, no shared serial or UPC: legitimate.
    resp = _create_tool(client, owner, serial_number="SN-002")
    assert resp.status_code == 201


def test_force_creates_anyway(client, owner):
    assert _create_tool(client, owner).status_code == 201
    resp = client.post(
        "/api/inventory?force=true",
        json=_tool_payload(name="Forced twin"),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201


def test_other_owners_items_never_block(client, owner, stranger):
    assert _create_tool(client, owner).status_code == 201
    assert _create_tool(client, stranger).status_code == 201


def test_battery_duplicate_blocks(client, owner):
    payload = {
        "name": "M18 battery",
        "brand": "Milwaukee",
        "model": "48-11-1850",
        "serial_number": "B-1",
    }
    first = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(owner)
    )
    assert first.status_code == 201
    second = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(owner)
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "possible_duplicate"


def test_normalized_brand_model_matching(client, owner):
    assert _create_tool(client, owner, brand="Snap-On Tools").status_code == 201
    resp = _create_tool(client, owner, brand="snap-on", model="fhr80")
    assert resp.status_code == 409


# -- smart search -------------------------------------------------------------


def _seed_vault(client, db, owner):
    _create_tool(client, owner)  # Snap-on FHR80, Ratchets, SN-001
    resp = _create_tool(
        client,
        owner,
        name="Broken ratchet",
        serial_number="SN-002",
        location="Shop toolbox",
    )
    assert resp.status_code == 201
    broken_id = resp.json()["id"]
    # Standing is written in production by the maintenance funnel
    # (repairs); the search filter reads the column, so the seed
    # sets the column directly.
    import uuid as _uuid

    from app.modules.inventory import models as inventory_models

    row = db.get(inventory_models.Tool, _uuid.UUID(broken_id))
    row.standing = "broken"
    db.commit()
    return broken_id


def test_parser_reads_the_vocabulary(db, client, owner):
    _seed_vault(client, db, owner)
    parsed = smart_search.parse_smart_query(db, owner.id, "snap-on broken under $200")
    assert parsed["filters"]["standing"] == "broken"
    assert parsed["filters"]["max_price"] == "200"
    labels = [chip["label"] for chip in parsed["chips"]]
    assert "Brand: Snap-on" in labels
    assert "Broken" in labels
    assert "Under $200" in labels


def test_parser_location_and_fallback(db, client, owner):
    _seed_vault(client, db, owner)
    parsed = smart_search.parse_smart_query(db, owner.id, "in shop toolbox")
    assert parsed["filters"]["location"] == "Shop toolbox"
    assert parsed["text"] == ""
    nonsense = smart_search.parse_smart_query(db, owner.id, "purple monkey")
    assert nonsense["filters"]["standing"] is None
    assert nonsense["text"] == "purple monkey"


def test_smart_search_endpoint_filters_and_chips(client, db, owner):
    broken_id = _seed_vault(client, db, owner)
    resp = client.get(
        "/api/inventory/search",
        params={"q": "broken", "smart": "true"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [broken_id]
    assert "Broken" in resp.headers.get("X-Search-Chips", "")


def test_plain_search_without_smart_unchanged(client, db, owner):
    _seed_vault(client, db, owner)
    resp = client.get(
        "/api/inventory/search",
        params={"q": "ratchet"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert "X-Search-Chips" not in resp.headers
