"""Batteries (owner spec 2026-10-18): first-class asset records in
Asset Inventory — own records (not children of tools), an optional
"currently in" link that lives on the battery, a COMPUTED warranty
status, full asset machinery (photos, custom fields, search), and
full citizenship in the systems tools belong to: the entitlement
item count + active set, tier sharing, peer sharing, stats, export,
and the account-deletion cascade.

These tests pin: warranty edges (exactly 30 days left = expiring
soon; missing inputs = unknown), link validation (own tools only),
tool-delete survival, owner scoping, the mixed-kind count (18 tools
+ 5 batteries breaks a 20-item cap), sharing payload kinds (battery
entries marked kind='battery'; tool entries byte-unchanged), and
peer visibility + exclusions.
"""

import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core import storage as storage_module
from app.modules.billing import entitlements, models as billing_models
from app.modules.core import export as export_module
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
NOW = datetime.now(timezone.utc)
TODAY = date.today()


def _make_user(db, account_number, email, account_types=(MECHANIC,), name="Battery User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000201", "owner@example.com", name="Olive Owner")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000202", "other@example.com", name="Oscar Other")


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


def _battery_payload(**overrides) -> dict:
    payload = {
        "name": "M18 XC5.0",
        "brand": "Milwaukee",
        "model": "48-11-1850",
        "serial_number": "B-123",
        "platform": "M18",
        "voltage": "18",
        "capacity_ah": "5.0",
        "chemistry": "Li-ion",
    }
    payload.update(overrides)
    return payload


# -- warranty computation ----------------------------------------------------


def _warranty_battery(purchase_date, warranty_months):
    return inventory_models.Battery(
        owner_id=uuid.uuid4(),
        name="B",
        purchase_date=purchase_date,
        warranty_months=warranty_months,
    )


def test_warranty_exactly_thirty_days_left_is_expiring_soon():
    # Purchased 2025-02-15 with a 12-month warranty -> ends 2026-02-15.
    battery = _warranty_battery(date(2025, 2, 15), 12)
    assert inventory_service.warranty_end_date(battery) == date(2026, 2, 15)
    assert (
        inventory_service.warranty_status(battery, today=date(2026, 1, 16))
        == "expiring_soon"
    )


def test_warranty_thirty_one_days_left_is_in_warranty():
    battery = _warranty_battery(date(2025, 2, 15), 12)
    assert (
        inventory_service.warranty_status(battery, today=date(2026, 1, 15))
        == "in_warranty"
    )


def test_warranty_last_day_and_day_after():
    battery = _warranty_battery(date(2025, 2, 15), 12)
    assert (
        inventory_service.warranty_status(battery, today=date(2026, 2, 15))
        == "expiring_soon"
    )
    assert (
        inventory_service.warranty_status(battery, today=date(2026, 2, 16))
        == "expired"
    )


def test_warranty_unknown_without_either_input():
    assert (
        inventory_service.warranty_status(
            _warranty_battery(None, 12), today=TODAY
        )
        == "unknown"
    )
    assert (
        inventory_service.warranty_status(
            _warranty_battery(date(2025, 1, 1), None), today=TODAY
        )
        == "unknown"
    )
    assert (
        inventory_service.warranty_status(_warranty_battery(None, None), today=TODAY)
        == "unknown"
    )


def test_warranty_month_addition_clamps_day():
    # Jan 31 + 1 month = Feb 28 (2025 is not a leap year).
    battery = _warranty_battery(date(2025, 1, 31), 1)
    assert inventory_service.warranty_end_date(battery) == date(2025, 2, 28)


# -- CRUD + the link ------------------------------------------------------------


def test_create_battery_defaults_and_warranty_fields(client, owner):
    purchased = TODAY - timedelta(days=350)  # 12-month warranty: ~15 days left
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(purchase_date=str(purchased), warranty_months=12),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["category"] == "Batteries"  # the default (the Batteries starter, 2026-10-25)
    assert body["platform"] == "M18"
    assert Decimal(body["voltage"]) == Decimal("18")
    assert Decimal(body["capacity_ah"]) == Decimal("5.0")
    assert body["warranty_status"] == "expiring_soon"
    assert body["warranty_end_date"] is not None
    assert body["currently_in_tool_id"] is None
    assert body["currently_in_tool_name"] is None
    assert body["active"] is True


def test_battery_link_round_trip(client, db, owner):
    tool = _make_tool(db, owner, name="Impact wrench")
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(currently_in_tool_id=str(tool.id)),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["currently_in_tool_id"] == str(tool.id)
    assert body["currently_in_tool_name"] == "Impact wrench"

    # The tool's battery list (tool detail panel source) shows it.
    listed = client.get(
        f"/api/inventory/batteries?in_tool={tool.id}", headers=auth_headers(owner)
    )
    assert [b["id"] for b in listed.json()] == [body["id"]]

    # Unlink: explicit null on update.
    unlinked = client.put(
        f"/api/inventory/batteries/{body['id']}",
        json={"currently_in_tool_id": None},
        headers=auth_headers(owner),
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["currently_in_tool_id"] is None
    assert unlinked.json()["currently_in_tool_name"] is None
    listed = client.get(
        f"/api/inventory/batteries?in_tool={tool.id}", headers=auth_headers(owner)
    )
    assert listed.json() == []


def test_battery_link_to_foreign_tool_refused(client, db, owner, other):
    foreign_tool = _make_tool(db, other)
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(currently_in_tool_id=str(foreign_tool.id)),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_battery_survives_tool_delete(client, db, owner):
    tool = _make_tool(db, owner)
    battery = _make_battery(db, owner, currently_in_tool_id=tool.id)
    deleted = client.delete(
        f"/api/inventory/{tool.id}", headers=auth_headers(owner)
    )
    assert deleted.status_code == 204, deleted.text
    resp = client.get(
        f"/api/inventory/batteries/{battery.id}", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["currently_in_tool_id"] is None
    assert resp.json()["name"] == battery.name


def test_battery_owner_scoping(client, db, owner, other):
    battery = _make_battery(db, owner)
    assert (
        client.get(
            f"/api/inventory/batteries/{battery.id}", headers=auth_headers(other)
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/inventory/batteries/{battery.id}",
            json={"name": "Hijacked"},
            headers=auth_headers(other),
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/inventory/batteries/{battery.id}", headers=auth_headers(other)
        ).status_code
        == 404
    )
    listed = client.get("/api/inventory/batteries", headers=auth_headers(other))
    assert listed.json() == []


def test_battery_endpoints_require_mechanic_module(client, db):
    dealer = _make_user(db, "TV-D-000203", "dealer@example.com", ("tool_dealer",))
    assert (
        client.get("/api/inventory/batteries", headers=auth_headers(dealer)).status_code
        == 403
    )
    assert client.get("/api/inventory/batteries").status_code == 401


# -- attachments -----------------------------------------------------------------


def test_battery_upload_flow_uses_batteries_namespace(client, db, owner, monkeypatch):
    battery = _make_battery(db, owner)
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )

    resp = client.post(
        f"/api/inventory/batteries/{battery.id}/upload-url",
        json={
            "filename": "pack.jpg",
            "content_type": "image/jpeg",
            "kind": "photo",
            "size_bytes": 1234,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    key = resp.json()["key"]
    assert f"/batteries/{battery.id}/photo/" in key

    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=1234, content_type="image/jpeg"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda k, length=512: b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    )
    attached = client.post(
        f"/api/inventory/batteries/{battery.id}/attachments",
        json={"key": key, "filename": "pack.jpg"},
        headers=auth_headers(owner),
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["kind"] == "photo"

    # A tools-namespaced key can never attach to a battery.
    bad = client.post(
        f"/api/inventory/batteries/{battery.id}/attachments",
        json={"key": f"{owner.id}/tools/{battery.id}/photo/x-pack.jpg"},
        headers=auth_headers(owner),
    )
    assert bad.status_code == 422, bad.text


# -- custom fields -----------------------------------------------------------------


def _make_definition(client, user, **overrides):
    payload = {
        "item_type": "battery",
        "name": "cycle_count",
        "label": "Cycle count",
        "field_type": "number",
        "required": False,
        "searchable": True,
        "options": [],
        "sort_order": 0,
    }
    payload.update(overrides)
    resp = client.post(
        "/api/inventory/field-definitions",
        json=payload,
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_battery_custom_fields_validate_against_battery_definitions(client, owner):
    definition = _make_definition(client, owner, required=True)
    # Missing the required battery field -> refused.
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    # With it -> created, value keyed by definition id.
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(custom_data={"cycle_count": 42}),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["custom_data"] == {definition["id"]: 42}
    # Wrong type -> refused. (A fresh serial: the identity above
    # now exists, and re-using it would trip duplicate detection
    # — wave 4 — before validation ever runs.)
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(
            serial_number="B-999", custom_data={"cycle_count": "many"}
        ),
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_tool_validation_ignores_battery_only_definitions(client, owner):
    _make_definition(client, owner, required=True)
    # A battery-only REQUIRED field must not block tool creation.
    resp = client.post(
        "/api/inventory",
        json={"name": "Wrench"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    # ...and its key is unknown to tools.
    resp = client.post(
        "/api/inventory",
        json={"name": "Wrench 2", "custom_data": {"cycle_count": 3}},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_both_definition_applies_to_tools_and_batteries(client, owner):
    definition = _make_definition(
        client,
        owner,
        item_type="both",
        name="asset_tag",
        label="Asset tag",
        field_type="text",
    )
    tool = client.post(
        "/api/inventory",
        json={"name": "Wrench", "custom_data": {"asset_tag": "A-1"}},
        headers=auth_headers(owner),
    )
    assert tool.status_code == 201, tool.text
    assert tool.json()["custom_data"] == {definition["id"]: "A-1"}
    battery = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(custom_data={"asset_tag": "A-2"}),
        headers=auth_headers(owner),
    )
    assert battery.status_code == 201, battery.text
    assert battery.json()["custom_data"] == {definition["id"]: "A-2"}
    # Both record lists see the shared definition set for their kind.
    tool_defs = client.get(
        "/api/inventory/field-definitions?item_type=tool",
        headers=auth_headers(owner),
    ).json()
    battery_defs = client.get(
        "/api/inventory/field-definitions?item_type=battery",
        headers=auth_headers(owner),
    ).json()
    assert [d["id"] for d in tool_defs] == [definition["id"]]
    assert [d["id"] for d in battery_defs] == [definition["id"]]


# -- search surfaces ---------------------------------------------------------------


def test_unified_search_marks_kinds(client, db, owner):
    _make_tool(db, owner, name="Wrench")
    _make_battery(db, owner, name="M18 pack")
    resp = client.get("/api/inventory/search/all", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    kinds = {item["name"]: item["item_kind"] for item in resp.json()}
    assert kinds == {"Wrench": "tool", "M18 pack": "battery"}


def test_battery_search_filters(client, db, owner):
    _make_battery(
        db,
        owner,
        name="Old pack",
        platform="M18",
        purchase_date=TODAY - timedelta(days=800),
        warranty_months=12,
    )
    _make_battery(
        db,
        owner,
        name="Fresh pack",
        platform="M12",
        purchase_date=TODAY - timedelta(days=10),
        warranty_months=24,
    )
    headers = auth_headers(owner)
    by_platform = client.get(
        "/api/inventory/batteries/search?platform=m18", headers=headers
    ).json()
    assert [b["name"] for b in by_platform] == ["Old pack"]
    expired = client.get(
        "/api/inventory/batteries/search?warranty=expired", headers=headers
    ).json()
    assert [b["name"] for b in expired] == ["Old pack"]
    in_warranty = client.get(
        "/api/inventory/batteries/search?warranty=in_warranty", headers=headers
    ).json()
    assert [b["name"] for b in in_warranty] == ["Fresh pack"]


# -- the count: batteries are items -------------------------------------------------


@pytest.fixture()
def _plans(db):
    db.add_all(
        [
            billing_models.Plan(
                plan_key="free", name="Free", item_limit=20,
                ai_monthly_credits=0, is_paid=False, sort_order=0,
            ),
            billing_models.Plan(
                plan_key="pro", name="Pro", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=1,
            ),
        ]
    )
    db.commit()


def _seed_mixed_vault(db, owner):
    """18 tools (older) + 5 batteries (newer) = 23 items."""
    tools = [
        _make_tool(
            db, owner, name=f"Tool {i:02d}", created_at=NOW + timedelta(minutes=i)
        )
        for i in range(18)
    ]
    batteries = [
        _make_battery(
            db,
            owner,
            name=f"Pack {i}",
            created_at=NOW + timedelta(hours=1, minutes=i),
        )
        for i in range(5)
    ]
    return tools, batteries


def test_batteries_count_toward_the_item_limit(db, owner, _plans):
    tools, batteries = _seed_mixed_vault(db, owner)
    assert entitlements.asset_count(db, owner.id) == 23
    assert entitlements.tool_count(db, owner.id) == 18

    # Enforcement OFF (the default): nothing is restricted.
    assert entitlements.active_tool_ids(db, owner.id) is None
    assert entitlements.active_battery_ids(db, owner.id) is None
    assert entitlements.can_add_tool(db, owner.id) is True

    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    # 23 items on a 20 cap: the newest 20 assets stay active — all
    # 5 batteries + the newest 15 tools; the 3 oldest tools grey out.
    active_tools = entitlements.active_tool_ids(db, owner.id)
    active_batteries = entitlements.active_battery_ids(db, owner.id)
    assert active_batteries == {b.id for b in batteries}
    assert active_tools == {t.id for t in tools[3:]}
    assert len(active_tools) + len(active_batteries) == 20
    assert entitlements.can_add_tool(db, owner.id) is False


def test_stats_and_billing_views_count_batteries(client, db, owner, _plans):
    _seed_mixed_vault(db, owner)
    headers = auth_headers(owner)
    stats = client.get("/api/inventory/stats", headers=headers).json()
    assert stats["total_items"] == 23

    mine = client.get("/api/billing/me", headers=headers).json()
    assert mine["items_total"] == 23
    assert mine["items_active"] == 23  # enforcement off

    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    stats = client.get("/api/inventory/stats", headers=headers).json()
    assert stats["total_items"] == 20  # active assets only
    mine = client.get("/api/billing/me", headers=headers).json()
    assert mine["items_total"] == 23
    assert mine["items_active"] == 20

    # The create doorway refuses BOTH kinds at the cap.
    resp = client.post(
        "/api/inventory/batteries",
        json=_battery_payload(),
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "item_limit_reached"
    resp = client.post("/api/inventory", json={"name": "One more"}, headers=headers)
    assert resp.status_code == 403, resp.text


def test_stats_money_totals_include_batteries(db, owner):
    _make_tool(db, owner, msrp=Decimal("100.00"), replacement_cost=Decimal("80.00"))
    _make_battery(
        db, owner, msrp=Decimal("50.00"), replacement_cost=Decimal("45.00")
    )
    stats = inventory_service.get_inventory_stats(db, owner.id)
    assert stats["total_items"] == 2
    assert stats["total_market_value"] == Decimal("150.00")
    assert stats["total_replacement_cost"] == Decimal("125.00")
    assert stats["category_count"] == 1  # "" (tool) is not a category; Battery is


# -- tier sharing ---------------------------------------------------------------------


def _enable_with_items(client, user, group, fields, tool_ids=(), battery_ids=()):
    config = client.put(
        f"/api/core/sharing/{group}",
        json={"enabled": True, "fields": fields},
        headers=auth_headers(user),
    )
    assert config.status_code == 200, config.text
    items = client.put(
        f"/api/core/sharing/{group}/items",
        json={
            "tool_ids": [str(t) for t in tool_ids],
            "battery_ids": [str(b) for b in battery_ids],
        },
        headers=auth_headers(user),
    )
    assert items.status_code == 200, items.text
    return items.json()


def test_tier_sharing_battery_items_and_preview_kind(client, db, owner):
    tool = _make_tool(db, owner, category="Power tools", condition="Good")
    battery = _make_battery(
        db, owner, condition="Good", purchase_price=Decimal("129.00")
    )
    state = _enable_with_items(
        client,
        owner,
        SHOP,
        # Package B (Ryan-directed): "condition" is no longer a
        # shareable field at all — it left the catalog and the
        # config literal, so it is never sent here.
        ["category", "location"],
        tool_ids=[tool.id],
        battery_ids=[battery.id],
    )
    assert state["shared_tool_ids"] == [str(tool.id)]
    assert state["shared_battery_ids"] == [str(battery.id)]
    assert {(r["kind"], r["id"]) for r in state["shared_items"]} == {
        ("tool", str(tool.id)),
        ("battery", str(battery.id)),
    }

    overview = client.get("/api/core/sharing", headers=auth_headers(owner)).json()
    by_id = {item["id"]: item for item in overview["items"]}
    assert by_id[str(battery.id)]["kind"] == "battery"
    assert by_id[str(battery.id)]["shared_with"] == [SHOP]
    assert by_id[str(tool.id)]["kind"] == "tool"

    preview = client.get(
        "/api/core/sharing/preview?group=shop_company",
        headers=auth_headers(owner),
    ).json()
    assert len(preview) == 2
    battery_entry = next(i for i in preview if i.get("kind") == "battery")
    tool_entry = next(i for i in preview if i["id"] == str(tool.id))
    # The tool payload is byte-unchanged: NO kind key on tool entries.
    assert "kind" not in tool_entry
    # The battery follows the same field rules: locked identity +
    # the chosen optionals, unchosen fields absent.
    assert set(battery_entry.keys()) == {
        "id",
        "name",
        "brand",
        "model",
        "serial_number",
        "category",
        "location",
        "kind",
    }
    # Condition never appears in a tier preview (Package B).
    assert "condition" not in battery_entry
    assert "condition" not in tool_entry
    assert battery_entry["category"] == "Batteries"
    assert "purchase_price" not in battery_entry


def test_tier_sharing_refuses_foreign_battery(client, db, owner, other):
    foreign = _make_battery(db, other)
    _enable_with_items(client, owner, SHOP, [])
    resp = client.put(
        f"/api/core/sharing/{SHOP}/items",
        json={"tool_ids": [], "battery_ids": [str(foreign.id)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


# -- peer sharing ------------------------------------------------------------------------


def _invite_and_accept(client, owner, viewer):
    invited = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": viewer.account_number},
        headers=auth_headers(owner),
    )
    assert invited.status_code in (200, 201), invited.text
    grant = invited.json()
    accepted = client.post(
        f"/api/core/sharing/peer/{grant['id']}/accept",
        headers=auth_headers(viewer),
    )
    assert accepted.status_code == 204, accepted.text
    return grant


def test_peer_list_and_search_include_batteries(client, db, owner, other):
    battery = _make_battery(
        db,
        owner,
        name="M18 XC5.0",
        attachments=[
            {
                "key": f"{owner.id}/batteries/x/photo/pack.jpg",
                "filename": "pack.jpg",
                "kind": "photo",
                "content_type": "image/jpeg",
                "size_bytes": 10,
                "uploaded_at": None,
            }
        ],
    )
    _invite_and_accept(client, owner, other)

    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    ).json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    # The peer whitelist + the battery kind mark — nothing more.
    assert set(item.keys()) == {
        "id",
        "kind",
        "name",
        "brand",
        "model",
        "category",
        # Package B (Ryan-directed): condition left the peer
        # whitelist — the exact key set is the privacy pin.
        "photos",
        "owner",
    }
    assert item["kind"] == "battery"
    assert item["category"] == "Batteries"
    assert len(item["photos"]) == 1
    assert "serial_number" not in item

    found = client.get(
        "/api/core/sharing/peer/search?q=m18", headers=auth_headers(other)
    ).json()
    assert [i["id"] for i in found] == [str(battery.id)]


def test_peer_exclusion_hides_a_battery(client, db, owner, other):
    battery = _make_battery(db, owner, name="Hidden pack")
    _make_battery(db, owner, name="Visible pack")
    _invite_and_accept(client, owner, other)

    resp = client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": [], "battery_ids": [str(battery.id)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["excluded_battery_ids"] == [str(battery.id)]

    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    ).json()
    assert [i["name"] for i in body["items"]] == ["Visible pack"]
    found = client.get(
        "/api/core/sharing/peer/search?q=pack", headers=auth_headers(other)
    ).json()
    assert [i["name"] for i in found] == ["Visible pack"]

    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(owner)
    ).json()
    assert overview["excluded_battery_ids"] == [str(battery.id)]
    assert {b["name"] for b in overview["my_batteries"]} == {
        "Hidden pack",
        "Visible pack",
    }


# -- export + account deletion ---------------------------------------------------------


def test_export_includes_batteries(db, owner):
    _make_battery(db, owner, platform="M18")
    archive = zipfile.ZipFile(io.BytesIO(export_module.build_export_zip(db, owner)))
    payload = json.loads(archive.read("batteries.json"))
    assert len(payload) == 1
    assert payload[0]["platform"] == "M18"
    assert payload[0]["warranty_status"] == "unknown"


def test_account_deletion_removes_batteries(db, owner):
    battery = _make_battery(db, owner)
    tool = _make_tool(db, owner)
    battery.currently_in_tool_id = tool.id
    db.commit()
    core_service.delete_account(db, owner)
    assert inventory_service.list_batteries(db, owner.id) == []
    assert db.get(inventory_models.Battery, battery.id) is None
