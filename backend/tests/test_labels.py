"""QR bin labels (blueprint §18): the print surface's data seam.

Pins: the selection resolver is owner-scoped (foreign, deleted and
malformed refs never resolve and are indistinguishable — they only
raise the `skipped` count), labels come back in request order with
the exact canonical QR path, a set yields ONE label for the set
record, bin-label counts follow the inventory list's own counting
(attached set addons don't count separately), the bin-label QR's
landing filter (`/inventory?location=…`) actually filters, and the
whole surface sits behind the inventory module gate like the rest
of the module.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
ORIGIN = "https://toolboxvault.com"


def _make_user(db, account_number, email, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Label User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000301", "label-owner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "label-other@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000303", "label-op@example.com", operator=True)


def _make_tool(db, owner, **overrides) -> inventory_models.Tool:
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=overrides.pop("name", "Impact wrench"),
        brand=overrides.pop("brand", "Milwaukee"),
        model=overrides.pop("model", "2853-20"),
        serial_number=overrides.pop("serial_number", "T-123"),
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _make_battery(db, owner, **overrides) -> inventory_models.Battery:
    battery = inventory_models.Battery(
        owner_id=owner.id,
        name=overrides.pop("name", "M18 XC5.0"),
        brand=overrides.pop("brand", "Milwaukee"),
        model=overrides.pop("model", "48-11-1850"),
        serial_number=overrides.pop("serial_number", "B-123"),
        **overrides,
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _labels(client, user, items):
    resp = client.get(
        "/api/inventory/labels",
        params={"items": items},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- selection resolution ------------------------------------------------------


def test_labels_resolve_owner_items_in_request_order(client, db, owner):
    tool = _make_tool(db, owner, location="Bay 1")
    battery = _make_battery(db, owner, location="Bay 1")
    tool_set = _make_tool(db, owner, name="Socket Set", is_set=True)

    body = _labels(
        client,
        owner,
        f"battery:{battery.id},tool:{tool.id},tool:{tool_set.id}",
    )
    assert body["skipped"] == 0
    assert [(row["kind"], row["name"]) for row in body["labels"]] == [
        ("battery", "M18 XC5.0"),
        ("tool", "Impact wrench"),
        ("tool", "Socket Set"),
    ]
    first = body["labels"][1]
    assert first["id"] == str(tool.id)
    assert first["brand"] == "Milwaukee"
    assert first["model"] == "2853-20"
    assert first["serial_number"] == "T-123"
    assert first["location"] == "Bay 1"
    assert first["is_set"] is False
    # The QR payload is the canonical URL — kind segment + id.
    assert first["qr_path"] == f"/inventory/tool/{tool.id}"
    assert f"{ORIGIN}{first['qr_path']}" == (
        f"https://toolboxvault.com/inventory/tool/{tool.id}"
    )
    assert body["labels"][0]["qr_path"] == f"/inventory/battery/{battery.id}"
    # A set prints ONE label — for the set record itself.
    assert body["labels"][2]["is_set"] is True
    assert body["labels"][2]["qr_path"] == f"/inventory/tool/{tool_set.id}"


def test_labels_skip_foreign_missing_and_malformed(client, db, owner, other):
    mine = _make_battery(db, owner)
    foreign = _make_tool(db, other)
    missing = uuid.uuid4()

    body = _labels(
        client,
        owner,
        ",".join(
            [
                f"battery:{mine.id}",
                f"battery:{mine.id}",  # duplicate: resolves once, not skipped
                f"tool:{foreign.id}",  # someone else's item
                f"tool:{missing}",  # doesn't exist
                "junk",  # no kind separator
                "tool:not-a-uuid",  # bad id
                f"gadget:{missing}",  # unknown kind
            ]
        ),
    )
    assert [row["id"] for row in body["labels"]] == [str(mine.id)]
    assert body["skipped"] == 5


def test_labels_empty_selection(client, owner):
    assert _labels(client, owner, "") == {"labels": [], "skipped": 0}
    resp = client.get("/api/inventory/labels", headers=auth_headers(owner))
    assert resp.status_code == 200
    assert resp.json() == {"labels": [], "skipped": 0}


def test_labels_require_auth(client):
    assert client.get("/api/inventory/labels").status_code == 401
    assert client.get("/api/inventory/labels/locations").status_code == 401


# -- bin (location) labels -----------------------------------------------------


def test_label_location_counts(client, db, owner, other):
    tool_set = _make_tool(db, owner, name="Socket Set", is_set=True, location="Bay 1")
    _make_tool(db, owner, name="Wrench", location="Bay 1")
    _make_tool(db, owner, name="Driver", location="Bay 1")
    # Attached into the set: lives inside it, never counts on its own.
    _make_tool(db, owner, name="Addon", location="Bay 1", attached_to_set_id=tool_set.id)
    _make_battery(db, owner, location="Bay 1")
    _make_battery(db, owner, name="Truck pack", location="Truck")
    _make_tool(db, owner, name="No home", location="")
    _make_tool(db, other, name="Not mine", location="Bay 1")

    resp = client.get("/api/inventory/labels/locations", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"location": "Bay 1", "count": 4},
        {"location": "Truck", "count": 1},
    ]


def test_label_location_counts_empty_vault(client, owner):
    resp = client.get("/api/inventory/labels/locations", headers=auth_headers(owner))
    assert resp.json() == []


# -- the bin-label QR landing: /inventory?location=… ----------------------------


def test_search_location_filter(client, db, owner):
    _make_tool(db, owner, name="In bay", location="Bay 1")
    _make_tool(db, owner, name="In truck", location="Truck")
    _make_battery(db, owner, name="Bay pack", location="Bay 1")

    headers = auth_headers(owner)
    tools = client.get(
        "/api/inventory/search", params={"location": "bay 1"}, headers=headers
    ).json()
    assert [t["name"] for t in tools] == ["In bay"]  # case-insensitive

    everything = client.get(
        "/api/inventory/search/all", params={"location": "Bay 1"}, headers=headers
    ).json()
    assert sorted(a["name"] for a in everything) == ["Bay pack", "In bay"]

    batteries = client.get(
        "/api/inventory/batteries/search",
        params={"location": "Bay 1"},
        headers=headers,
    ).json()
    assert [b["name"] for b in batteries] == ["Bay pack"]

    nowhere = client.get(
        "/api/inventory/search/all", params={"location": "Moon"}, headers=headers
    ).json()
    assert nowhere == []


# -- module gate ----------------------------------------------------------------


def test_labels_module_off_is_module_unavailable(client, db, owner, operator):
    headers = auth_headers(operator)
    try:
        updated = client.put(
            "/api/admin/modules/inventory/global",
            json={"enabled": False},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        for path in ("/api/inventory/labels", "/api/inventory/labels/locations"):
            resp = client.get(path, headers=auth_headers(owner))
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"]["code"] == "module_unavailable"
    finally:
        client.put(
            "/api/admin/modules/inventory/global",
            json={"enabled": True},
            headers=headers,
        )
