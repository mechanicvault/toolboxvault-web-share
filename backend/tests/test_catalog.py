"""Wave 4 — the community product catalog.

Pins:
  - a spec value becomes a suggestion only when >= 2 DISTINCT
    contributing users' items agree on it (normalized);
  - the contributing fields are exactly category / size / msrp;
  - payloads carry NO user identity, NO serials, NO purchase
    prices — ever;
  - opting out removes a user's weight immediately (the
    aggregate reads live items; there are no stored copies);
  - Mac Tools and Matco never merge (normalization strips
    corporate filler, never a brand's stem);
  - the module doorway matches its groups (mechanic + shop).
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, types):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Catalog User",
        password_hash="not-a-real-hash",
        account_types=types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def alice(db):
    return _make_user(db, "TV-M-000401", "alice@example.com", [MECHANIC])


@pytest.fixture()
def bob(db):
    return _make_user(db, "TV-M-000402", "bob@example.com", [MECHANIC])


@pytest.fixture()
def carol(db):
    return _make_user(db, "TV-S-000403", "carol@example.com", [SHOP])


def _add_tool(client, user, **overrides):
    payload = {
        "name": "Torque wrench",
        "brand": "Snap-on",
        "model": "QD3R250",
        "category": "Torque",
        "size": "1/2 in drive",
        "msrp": "289.95",
    }
    payload.update(overrides)
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _suggestions(client, user, brand="Snap-on", model="QD3R250"):
    resp = client.get(
        "/api/catalog/suggestions",
        params={"brand": brand, "model": model},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_two_agreeing_users_make_a_suggestion(client, alice, bob):
    _add_tool(client, alice)
    _add_tool(client, bob, brand="SNAP-ON", model="qd3r250")
    out = _suggestions(client, alice)
    assert out["contributors"] == 2
    assert out["fields"]["category"] == {"value": "Torque", "supporters": 2}
    assert out["fields"]["size"]["supporters"] == 2
    assert out["fields"]["msrp"]["value"] == 289.95
    assert out["fields"]["msrp"]["supporters"] == 2


def test_single_user_never_surfaces(client, alice):
    _add_tool(client, alice)
    _add_tool(client, alice, name="Second one on my shelf")
    out = _suggestions(client, alice)
    assert out["contributors"] == 1
    assert out["fields"] == {}


def test_disagreement_keeps_the_field_silent(client, alice, bob):
    _add_tool(client, alice, category="Torque")
    _add_tool(client, bob, category="Wrenches")
    out = _suggestions(client, alice)
    assert out["contributors"] == 2
    assert "category" not in out["fields"]
    # The fields they DO agree on still speak.
    assert out["fields"]["size"]["supporters"] == 2


def test_batteries_contribute_category_and_msrp(client, alice, bob):
    for user in (alice, bob):
        resp = client.post(
            "/api/inventory/batteries",
            json={
                "name": "M18 battery",
                "brand": "Milwaukee",
                "model": "48-11-1850",
                "category": "Battery",
                "msrp": "149.00",
            },
            headers=auth_headers(user),
        )
        assert resp.status_code == 201, resp.text
    out = _suggestions(client, alice, brand="Milwaukee", model="48-11-1850")
    assert out["fields"]["category"]["supporters"] == 2
    assert out["fields"]["msrp"]["value"] == 149
    assert "size" not in out["fields"]  # batteries have no size


def test_privacy_no_identity_serials_or_paid_prices(client, alice, bob):
    _add_tool(
        client,
        alice,
        serial_number="SECRET-SERIAL-1",
        purchase_price="199.00",
        notes="private note",
    )
    _add_tool(
        client,
        bob,
        serial_number="SECRET-SERIAL-2",
        purchase_price="210.00",
    )
    out = _suggestions(client, alice)
    blob = str(out)
    assert "SECRET-SERIAL" not in blob
    assert "199" not in blob and "210" not in blob
    assert "alice" not in blob and "bob" not in blob
    assert "private note" not in blob
    assert set(out["fields"]) <= {"category", "size", "msrp"}


def test_opt_out_removes_weight_immediately(client, db, alice, bob):
    _add_tool(client, alice)
    _add_tool(client, bob)
    assert _suggestions(client, alice)["fields"] != {}
    # Bob opts out: the aggregate drops to one supporter and the
    # suggestion disappears — no stored copy anywhere to scrub.
    resp = client.patch(
        "/api/core/me",
        json={"catalog_contribute": False},
        headers=auth_headers(bob),
    )
    assert resp.status_code == 200
    assert resp.json()["catalog_contribute"] is False
    out = _suggestions(client, alice)
    assert out["contributors"] == 1
    assert out["fields"] == {}
    # And back on restores it just as immediately.
    client.patch(
        "/api/core/me",
        json={"catalog_contribute": True},
        headers=auth_headers(bob),
    )
    assert _suggestions(client, alice)["contributors"] == 2


def test_contribution_defaults_on(db, alice):
    me_row = db.get(core_models.User, alice.id)
    assert me_row.catalog_contribute is True


def test_mac_and_matco_never_merge(client, alice, bob):
    _add_tool(client, alice, brand="Mac Tools", model="MR223")
    _add_tool(client, bob, brand="Matco Tools", model="MR223")
    out = _suggestions(client, alice, brand="Mac Tools", model="MR223")
    assert out["contributors"] == 1
    assert out["fields"] == {}


def test_brand_suffix_normalization(client, alice, bob):
    _add_tool(client, alice, brand="Matco Tools")
    _add_tool(client, bob, brand="MATCO")
    out = _suggestions(client, alice, brand="Matco", model="QD3R250")
    assert out["contributors"] == 2
    assert out["fields"]["category"]["supporters"] == 2


def test_catalog_doorway_groups(client, db, alice):
    dealer = _make_user(db, "TV-D-000404", "dealer@example.com", [DEALER])
    resp = client.get(
        "/api/catalog/suggestions",
        params={"brand": "Snap-on", "model": "QD3R250"},
        headers=auth_headers(dealer),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
    # Shop holds inventory — the catalog serves it too.
    shop = _make_user(db, "TV-S-000405", "shop2@example.com", [SHOP])
    resp = client.get(
        "/api/catalog/suggestions",
        params={"brand": "Snap-on", "model": "QD3R250"},
        headers=auth_headers(shop),
    )
    assert resp.status_code == 200
