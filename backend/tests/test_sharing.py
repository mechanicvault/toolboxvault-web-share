"""Consent sharing (owner directive 2026-10-17): a mechanic shares
their tool list with the shop group and/or the insurance group —
fields per group (locked identity fields always go, optional fields
are the owner's toggles), items per group (all / none / per item).

These tests pin: owner scoping (another user can neither see nor
touch your config, and naming their tool id in your item set refuses
the whole write), set-replace item semantics, preview field
filtering (unchosen fields ABSENT, not nulled), and the mechanic
gate on the inventory module (shop-only/dealer-only 403; mechanic
and mechanic+shop 200).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"

# Package B: condition left the sharing catalog — the seeded
# defaults no longer include it.
DEFAULT_FIELDS = ["category", "photos", "replacement_cost"]


@pytest.fixture(autouse=True)
def _sharing_tables(db):
    # The shared conftest creates only the long-standing tables; the
    # sharing tables are created here so the fixture list stays put
    # (same pattern as test_page_layouts.py).
    bind = db.get_bind()
    core_models.ShareConfig.__table__.create(bind=bind, checkfirst=True)
    core_models.SharedItem.__table__.create(bind=bind, checkfirst=True)


def _make_user(db, account_number: str, email: str, account_types: list[str]):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Sharing User",
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_a(db):
    # This file's owners carry the mechanic type they would
    # hold in production: sharing writes follow reach
    # (2026-11-09) — an account that cannot reach the
    # inventory module is refused at the sharing writes, and
    # the shared conftest pair is typeless by design.
    return _make_user(db, "TV-000001", "a@example.com", ["mechanic_technician"])


@pytest.fixture()
def user_b(db):
    return _make_user(db, "TV-000002", "b@example.com", ["mechanic_technician"])


def _make_tool(db, owner, **overrides) -> inventory_models.Tool:
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=overrides.pop("name", "Impact wrench"),
        brand=overrides.pop("brand", "Snap-on"),
        model=overrides.pop("model", "CT9075"),
        serial_number=overrides.pop("serial_number", "SN-123"),
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _full_tool(db, owner) -> inventory_models.Tool:
    """A tool with every shareable field populated + one attachment
    of each kind, so preview tests can prove what is filtered out."""
    tool = _make_tool(
        db,
        owner,
        category="Power tools",
        condition="Good",
        location="Drawer 3",
        notes="Calibrated in March",
        purchase_price=Decimal("400.00"),
        purchase_date=date(2024, 3, 1),
        msrp=Decimal("549.99"),
        replacement_cost=Decimal("519.00"),
        custom_data={"vin": "1FTFW1ET5DFC10312"},
    )
    tool.attachments = [
        {
            "key": f"{owner.id}/tools/{tool.id}/photo/front.jpg",
            "filename": "front.jpg",
            "kind": "photo",
            "content_type": "image/jpeg",
            "size_bytes": 100,
            "uploaded_at": None,
        },
        {
            "key": f"{owner.id}/tools/{tool.id}/document/manual.pdf",
            "filename": "manual.pdf",
            "kind": "document",
            "content_type": "application/pdf",
            "size_bytes": 200,
            "uploaded_at": None,
        },
        {
            "key": f"{owner.id}/tools/{tool.id}/receipt/store.pdf",
            "filename": "store.pdf",
            "kind": "receipt",
            "content_type": "application/pdf",
            "size_bytes": 150,
            "uploaded_at": None,
        },
    ]
    db.commit()
    db.refresh(tool)
    return tool


def _enable(client, user, group: str, fields: list[str], tool_ids=()):
    config = client.put(
        f"/api/core/sharing/{group}",
        json={"enabled": True, "fields": fields},
        headers=auth_headers(user),
    )
    assert config.status_code == 200, config.text
    items = client.put(
        f"/api/core/sharing/{group}/items",
        json={"tool_ids": [str(t) for t in tool_ids]},
        headers=auth_headers(user),
    )
    assert items.status_code == 200, items.text


# -- auth + defaults -----------------------------------------------------------


def test_sharing_endpoints_require_auth(client):
    assert client.get("/api/core/sharing").status_code == 401
    assert client.get("/api/core/sharing/preview?group=insurance").status_code == 401
    assert (
        client.put(
            "/api/core/sharing/insurance", json={"enabled": True, "fields": []}
        ).status_code
        == 401
    )
    assert (
        client.put(
            "/api/core/sharing/insurance/items", json={"tool_ids": []}
        ).status_code
        == 401
    )


def test_overview_defaults_before_any_configuration(client, user_a):
    body = client.get("/api/core/sharing", headers=auth_headers(user_a)).json()
    assert [g["recipient_group"] for g in body["groups"]] == [SHOP, INSURANCE]
    for group in body["groups"]:
        assert group["enabled"] is False
        assert group["fields"] == DEFAULT_FIELDS
        assert group["shared_tool_ids"] == []
    assert body["items"] == []


def test_unknown_group_and_fields_are_422(client, user_a):
    headers = auth_headers(user_a)
    assert (
        client.put(
            "/api/core/sharing/tool_dealer",
            json={"enabled": True, "fields": []},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/core/sharing/preview?group=tool_dealer", headers=headers
        ).status_code
        == 422
    )
    # A locked identity field is not a valid config field (it always goes).
    assert (
        client.put(
            "/api/core/sharing/insurance",
            json={"enabled": True, "fields": ["serial_number"]},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/core/sharing/insurance",
            json={"enabled": True, "fields": ["bogus"]},
            headers=headers,
        ).status_code
        == 422
    )


# -- config CRUD, owner-scoped ---------------------------------------------------


def test_config_update_roundtrip_and_canonical_order(client, user_a):
    headers = auth_headers(user_a)
    response = client.put(
        "/api/core/sharing/insurance",
        json={"enabled": True, "fields": ["notes", "category", "notes"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["fields"] == ["category", "notes"]  # catalog order, deduped

    overview = client.get("/api/core/sharing", headers=headers).json()
    insurance = next(
        g for g in overview["groups"] if g["recipient_group"] == INSURANCE
    )
    assert insurance["enabled"] is True
    assert insurance["fields"] == ["category", "notes"]
    shop = next(g for g in overview["groups"] if g["recipient_group"] == SHOP)
    assert shop["enabled"] is False  # the other group is untouched


def test_config_is_invisible_and_untouchable_across_owners(client, db, user_a, user_b):
    tool = _full_tool(db, user_a)
    _enable(client, user_a, INSURANCE, ["notes"], [tool.id])

    # B's overview shows none of A's setup; B's preview is empty.
    overview_b = client.get("/api/core/sharing", headers=auth_headers(user_b)).json()
    assert overview_b["items"] == []
    assert all(g["enabled"] is False for g in overview_b["groups"])
    assert (
        client.get(
            "/api/core/sharing/preview?group=insurance",
            headers=auth_headers(user_b),
        ).json()
        == []
    )
    # A's preview is unaffected by anything B does with B's own config.
    client.put(
        "/api/core/sharing/insurance",
        json={"enabled": False, "fields": []},
        headers=auth_headers(user_b),
    )
    preview_a = client.get(
        "/api/core/sharing/preview?group=insurance", headers=auth_headers(user_a)
    ).json()
    assert len(preview_a) == 1


def test_overview_items_carry_per_group_shared_flags(client, db, user_a, user_b):
    mine = _make_tool(db, user_a, name="Mine")
    _make_tool(db, user_b, name="Not mine")
    _enable(client, user_a, SHOP, [], [mine.id])

    body = client.get("/api/core/sharing", headers=auth_headers(user_a)).json()
    assert [item["name"] for item in body["items"]] == ["Mine"]
    assert body["items"][0]["shared_with"] == [SHOP]


# -- item set semantics ------------------------------------------------------------


def test_items_replace_wholesale(client, db, user_a):
    headers = auth_headers(user_a)
    t1 = _make_tool(db, user_a, name="One")
    t2 = _make_tool(db, user_a, name="Two")

    def put_items(ids):
        return client.put(
            "/api/core/sharing/shop_company/items",
            json={"tool_ids": [str(i) for i in ids]},
            headers=headers,
        )

    assert set(put_items([t1.id, t2.id]).json()["shared_tool_ids"]) == {
        str(t1.id),
        str(t2.id),
    }
    assert put_items([t2.id]).json()["shared_tool_ids"] == [str(t2.id)]
    assert put_items([]).json()["shared_tool_ids"] == []


def test_items_refuse_foreign_tool_ids(client, db, user_a, user_b):
    mine = _make_tool(db, user_a, name="Mine")
    foreign = _make_tool(db, user_b, name="Foreign")
    _enable(client, user_a, INSURANCE, [], [mine.id])

    response = client.put(
        "/api/core/sharing/insurance/items",
        json={"tool_ids": [str(mine.id), str(foreign.id)]},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 422
    # Nothing partial was applied: the previous set stands.
    overview = client.get("/api/core/sharing", headers=auth_headers(user_a)).json()
    insurance = next(
        g for g in overview["groups"] if g["recipient_group"] == INSURANCE
    )
    assert insurance["shared_tool_ids"] == [str(mine.id)]


# -- preview: the recipient payload --------------------------------------------


def test_preview_contains_only_the_shared_fields(client, db, user_a):
    tool = _full_tool(db, user_a)
    _enable(client, user_a, SHOP, ["category", "photos"], [tool.id])

    preview = client.get(
        "/api/core/sharing/preview?group=shop_company",
        headers=auth_headers(user_a),
    ).json()
    assert len(preview) == 1
    item = preview[0]
    assert set(item.keys()) == {
        "id",
        "name",
        "brand",
        "model",
        "serial_number",
        "category",
        "photos",
    }
    # Unchosen fields are ABSENT — not null, not empty.
    for absent in (
        "condition",
        "location",
        "purchase_price",
        "purchase_date",
        "msrp",
        "replacement_cost",
        "notes",
        "documents",
        "custom_fields",
        "custom_data",
        "attachments",
        "owner_id",
    ):
        assert absent not in item
    assert item["category"] == "Power tools"
    assert item["photos"]["count"] == 1
    assert len(item["photos"]["urls"]) == 1


def test_preview_locked_fields_present_with_no_optional_fields(client, db, user_a):
    tool = _full_tool(db, user_a)
    _enable(client, user_a, INSURANCE, [], [tool.id])
    preview = client.get(
        "/api/core/sharing/preview?group=insurance", headers=auth_headers(user_a)
    ).json()
    assert len(preview) == 1
    assert set(preview[0].keys()) == {
        "id",
        "name",
        "brand",
        "model",
        "serial_number",
    }
    assert preview[0]["serial_number"] == "SN-123"


def test_preview_documents_custom_fields_and_money(client, db, user_a):
    tool = _full_tool(db, user_a)
    _enable(
        client,
        user_a,
        INSURANCE,
        ["documents", "custom_fields", "purchase_price", "purchase_date", "notes"],
        [tool.id],
    )
    preview = client.get(
        "/api/core/sharing/preview?group=insurance", headers=auth_headers(user_a)
    ).json()
    item = preview[0]
    # document + receipt kinds ride the documents toggle.
    assert item["documents"]["count"] == 2
    assert len(item["documents"]["urls"]) == 2
    assert "photos" not in item
    assert item["custom_fields"] == {"vin": "1FTFW1ET5DFC10312"}
    assert item["purchase_price"] == "400.00"  # decimal string, API-style
    assert item["purchase_date"] == "2024-03-01"
    assert item["notes"] == "Calibrated in March"


def test_preview_is_empty_when_sharing_is_off(client, db, user_a):
    tool = _make_tool(db, user_a)
    headers = auth_headers(user_a)
    # Never configured at all.
    assert (
        client.get(
            "/api/core/sharing/preview?group=insurance", headers=headers
        ).json()
        == []
    )
    # Configured with items, then switched off: recipients get nothing.
    _enable(client, user_a, INSURANCE, ["notes"], [tool.id])
    assert (
        len(
            client.get(
                "/api/core/sharing/preview?group=insurance", headers=headers
            ).json()
        )
        == 1
    )
    client.put(
        "/api/core/sharing/insurance",
        json={"enabled": False, "fields": ["notes"]},
        headers=headers,
    )
    assert (
        client.get(
            "/api/core/sharing/preview?group=insurance", headers=headers
        ).json()
        == []
    )


def test_preview_includes_only_shared_items(client, db, user_a):
    shared = _make_tool(db, user_a, name="Shared")
    _make_tool(db, user_a, name="Private")
    _enable(client, user_a, SHOP, [], [shared.id])
    preview = client.get(
        "/api/core/sharing/preview?group=shop_company",
        headers=auth_headers(user_a),
    ).json()
    assert [item["name"] for item in preview] == ["Shared"]


# -- inventory belongs to mechanics ---------------------------------------------


@pytest.mark.parametrize(
    ("account_types", "expected"),
    [
        ([SHOP], 403),
        ([DEALER], 403),
        ([INSURANCE], 403),
        ([], 403),
        ([MECHANIC], 200),
        ([MECHANIC, SHOP], 200),
        ([MECHANIC, DEALER, INSURANCE], 200),
    ],
)
def test_inventory_routes_are_mechanic_gated(client, db, account_types, expected):
    stamp = abs(hash(tuple(account_types))) % 10**10
    user = _make_user(
        db,
        f"TV-G{stamp:010d}"[:16],
        f"gate-{stamp}@example.com",
        account_types,
    )
    headers = auth_headers(user)
    assert client.get("/api/inventory", headers=headers).status_code == expected
    assert client.get("/api/inventory/stats", headers=headers).status_code == expected
    created = client.post(
        "/api/inventory", json={"name": "Gate wrench"}, headers=headers
    )
    assert created.status_code == (201 if expected == 200 else 403)
