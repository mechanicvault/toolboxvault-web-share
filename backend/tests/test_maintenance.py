"""Maintenance module — schedules, warranty, standing, interplay.

Covers the rules the module was specified with:
  - warranty is ONE shared computation: battery fixtures behave
    exactly as before the generalization, and tools now read the
    same boundaries (unknown / in / expiring at exactly 30 days /
    expired);
  - schedules: next-due math, logging advances it, the home stats
    count what's due, and the jobs seam notifies once per due
    date (idempotent re-runs);
  - module gating: off -> routes 403 + the stats vanish from
    my-modules;
  - borrowing interplay: a broken item can't be lent; an item out
    on a lend CAN be marked broken (the lend stays open).

Repairs ∪ claims merge (2026-11-04): the repair RECORDS this
file used to exercise are gone — a repair IS a claim now, and
the lifecycle (break -> send -> fix with cost, history never
wiped, set pieces on their own claims) is covered in
tests/test_claims_repairs_merge.py. What remains here of the
repair world: the standing read (state + problem + schedules +
pieces, no record shapes), the out-of-service board re-derived
from standings + open claims, and piece standing writes (a
piece follows the item rule: mark broken is its own step).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from app.modules.maintenance import service as maintenance_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name="Test User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "maint@example.com", [MECHANIC], "Manny Mechanic")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000402", "maint-other@example.com", [MECHANIC], "Otto Other")


@pytest.fixture()
def operator(db):
    user = _make_user(db, "TV-M-000403", "maint-op@example.com", [MECHANIC], "Op Erator")
    user.is_operator = True
    db.commit()
    db.refresh(user)
    return user


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 5.0 pack", **overrides):
    battery = inventory_models.Battery(owner_id=owner.id, name=name, **overrides)
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _set_standing(client, user, kind, item_id, standing):
    """Mark an item broken / back in service the way the UI does
    (merge, 2026-11-04): the inventory bulk standing write — the
    Actions menu's own path."""
    response = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": kind, "id": str(item_id)}],
            "action": "set_standing",
            "params": {"standing": standing},
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _mark_broken(client, user, kind, item_id):
    return _set_standing(client, user, kind, item_id, "broken")


def _standing(client, user, kind, item_id):
    response = client.get(
        f"/api/maintenance/items/{kind}/{item_id}", headers=auth_headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- warranty: one shared computation ---------------------------------------


def test_warranty_boundaries_are_shared_by_tools_and_batteries(db, owner):
    today = date(2026, 6, 15)
    # Directly against the shared function — the boundaries both
    # kinds now read.
    assert inventory_service.warranty_status_for(None, 12, today) == "unknown"
    assert inventory_service.warranty_status_for(date(2026, 1, 1), None, today) == "unknown"
    # Ends exactly 30 days out -> expiring soon (the battery rule).
    assert (
        inventory_service.warranty_status_for(date(2025, 7, 15), 12, today)
        == "expiring_soon"
    )
    # Ends 31 days out -> in warranty.
    assert (
        inventory_service.warranty_status_for(date(2025, 7, 16), 12, today)
        == "in_warranty"
    )
    # Ended yesterday -> expired; ends today -> expiring soon.
    assert (
        inventory_service.warranty_status_for(date(2025, 6, 14), 12, today)
        == "expired"
    )
    assert (
        inventory_service.warranty_status_for(date(2025, 6, 15), 12, today)
        == "expiring_soon"
    )

    # Battery parity: the wrapper answers what it always answered.
    battery = _battery(
        db, owner, purchase_date=date(2025, 7, 15), warranty_months=12
    )
    assert inventory_service.warranty_status(battery, today) == "expiring_soon"
    assert inventory_service.warranty_end_date(battery) == date(2026, 7, 15)

    # Tools now speak the same language through their own wrapper
    # and through the public payload.
    tool = _tool(db, owner, purchase_date=date(2025, 7, 15), warranty_months=12)
    assert inventory_service.tool_warranty_status(tool, today) == "expiring_soon"
    view = inventory_service.serialize_tool(db, tool)
    assert view["warranty_months"] == 12
    assert view["warranty_end_date"] == date(2026, 7, 15)
    assert view["warranty_status"] in (
        "in_warranty",
        "expiring_soon",
        "expired",
        "unknown",
    )


def test_tool_warranty_round_trips_through_the_api(client, owner, db):
    created = client.post(
        "/api/inventory",
        json={
            "name": "Torque wrench",
            "purchase_date": "2026-01-10",
            "warranty_months": 24,
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["warranty_months"] == 24
    assert body["warranty_end_date"] == "2028-01-10"
    assert body["warranty_status"] == "in_warranty"

    updated = client.put(
        f"/api/inventory/{body['id']}",
        json={"warranty_months": 6},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["warranty_end_date"] == "2026-07-10"


# -- repair lifecycle: history is never wiped ---------------------------------


def test_standing_read_carries_no_repair_records(client, owner, db):
    # Merge (2026-11-04): the standing read is state + problem +
    # schedules + pieces — the repair history lives on the item's
    # claims, so the record shapes (open_record / history) are
    # gone from this payload for good.
    tool = _tool(db, owner)
    _mark_broken(client, owner, "tool", tool.id)
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "broken"
    assert "open_record" not in standing
    assert "history" not in standing
    assert standing["schedules"] == []

    _set_standing(client, owner, "tool", tool.id, "in_service")
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "in_service"
    assert standing["problem"] == ""


def test_battery_standing_and_cross_user_404s(client, owner, other, db):
    battery = _battery(db, owner)
    _mark_broken(client, owner, "battery", battery.id)
    assert _standing(client, owner, "battery", battery.id)["state"] == "broken"
    assert (
        client.get(
            f"/api/maintenance/items/battery/{battery.id}",
            headers=auth_headers(other),
        ).status_code
        == 404
    )
    # A foreign standing write refuses the whole batch and the
    # battery's standing is untouched.
    refused = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": "battery", "id": str(battery.id)}],
            "action": "set_standing",
            "params": {"standing": "in_service"},
        },
        headers=auth_headers(other),
    )
    assert refused.status_code == 422, refused.text
    assert _standing(client, owner, "battery", battery.id)["state"] == "broken"


# -- set pieces -------------------------------------------------------------------


def test_set_piece_standing_is_its_own(client, owner, db):
    tool = _tool(db, owner, name="Socket set 8-19mm", is_set=True)
    piece = client.post(
        f"/api/inventory/{tool.id}/pieces",
        json={"kind": "core", "name": "13mm socket", "part_number": "S1313"},
        headers=auth_headers(owner),
    )
    assert piece.status_code == 201, piece.text
    piece_id = piece.json()["id"]

    # A piece follows the item rule (merge, 2026-11-04): mark
    # broken is its own step, no claim — through the piece update.
    marked = client.put(
        f"/api/inventory/pieces/{piece_id}",
        json={"repair_state": "broken", "repair_problem": "Cracked wall"},
        headers=auth_headers(owner),
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["repair_state"] == "broken"

    standing = _standing(client, owner, "tool", tool.id)
    # The set itself never went down; the piece carries it.
    assert standing["state"] == "in_service"
    (piece_view,) = standing["pieces"]
    assert piece_view["state"] == "broken"
    assert piece_view["problem"] == "Cracked wall"
    assert "open_record" not in piece_view
    assert "history" not in piece_view

    # The set payload's piece rows carry the standing for badges.
    payload = client.get(
        f"/api/inventory/{tool.id}", headers=auth_headers(owner)
    ).json()
    (core,) = payload["set"]["core_pieces"]
    assert core["repair_state"] == "broken"
    assert core["repair_problem"] == "Cracked wall"

    # Back in service clears the problem text, like a whole item.
    back = client.put(
        f"/api/inventory/pieces/{piece_id}",
        json={"repair_state": "in_service"},
        headers=auth_headers(owner),
    )
    assert back.status_code == 200, back.text
    assert back.json()["repair_state"] == "in_service"
    assert back.json()["repair_problem"] == ""
    standing = _standing(client, owner, "tool", tool.id)
    (piece_view,) = standing["pieces"]
    assert piece_view["state"] == "in_service"

    # Into in_repair by hand is refused: a claim sends a piece out.
    refused = client.put(
        f"/api/inventory/pieces/{piece_id}",
        json={"repair_state": "in_repair"},
        headers=auth_headers(owner),
    )
    assert refused.status_code == 422, refused.text


# -- schedules --------------------------------------------------------------------


def _schedule(client, user, item_kind, item_id, **body):
    response = client.post(
        f"/api/maintenance/items/{item_kind}/{item_id}/schedules",
        json=body,
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_schedule_due_math_and_logging(client, owner, db):
    tool = _tool(db, owner, name="Torque wrench")
    today = date.today()
    schedule = _schedule(
        client,
        owner,
        "tool",
        tool.id,
        kind="calibration",
        label="Annual calibration",
        interval_days=365,
        last_done_at=(today - timedelta(days=360)).isoformat(),
    )
    assert schedule["next_due"] == (today + timedelta(days=5)).isoformat()
    assert schedule["due_status"] == "due_soon"

    # Logging the work advances last_done and recomputes next due.
    entry = client.post(
        f"/api/maintenance/schedules/{schedule['id']}/log",
        json={"cost": "45.00", "technician": "Cal Labs"},
        headers=auth_headers(owner),
    )
    assert entry.status_code == 201, entry.text
    assert entry.json()["done_date"] == today.isoformat()

    standing = _standing(client, owner, "tool", tool.id)
    (view,) = standing["schedules"]
    assert view["last_done_at"] == today.isoformat()
    assert view["next_due"] == (today + timedelta(days=365)).isoformat()
    assert view["due_status"] == "ok"
    assert len(view["log"]) == 1
    assert view["log"][0]["technician"] == "Cal Labs"

    stats = client.get("/api/maintenance/stats", headers=auth_headers(owner)).json()
    assert stats["maintenance_due_count"] == 0
    assert stats["out_of_service_count"] == 0


def test_schedule_needs_an_interval_or_a_due_date(client, owner, db):
    tool = _tool(db, owner)
    response = client.post(
        f"/api/maintenance/items/tool/{tool.id}/schedules",
        json={"kind": "service"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422


def test_overview_board_and_stats(client, owner, db):
    tool = _tool(db, owner, name="Lift")
    battery = _battery(db, owner, name="Jump pack")
    today = date.today()
    _schedule(
        client, owner, "tool", tool.id, kind="inspection",
        due_date=(today - timedelta(days=2)).isoformat(),
    )
    _schedule(
        client, owner, "battery", battery.id, kind="service",
        due_date=(today + timedelta(days=3)).isoformat(),
    )
    _mark_broken(client, owner, "battery", battery.id)

    stats = client.get("/api/maintenance/stats", headers=auth_headers(owner)).json()
    # Overdue (2 days past) + due soon (3 days out) both count.
    assert stats["maintenance_due_count"] == 2
    assert stats["out_of_service_count"] == 1

    overview = client.get(
        "/api/maintenance/overview", headers=auth_headers(owner)
    ).json()
    (entry,) = overview["out_of_service"]
    assert entry["item_name"] == "Jump pack"
    assert entry["state"] == "broken"
    assert entry["since"] is not None
    # No claim is driving this break (merge, 2026-11-04): the
    # claim link fields ride along empty.
    assert entry["claim_id"] is None
    assert entry["claim_number"] is None
    assert len(overview["schedules"]) == 2
    statuses = {s["item_name"]: s["due_status"] for s in overview["schedules"]}
    assert statuses == {"Lift": "overdue", "Jump pack": "due_soon"}


# -- jobs seam: overdue notifications, idempotent ----------------------------------


def test_overdue_notifications_are_idempotent_per_due_date(client, owner, db):
    tool = _tool(db, owner, name="Compressor")
    today = date.today()
    schedule = _schedule(
        client, owner, "tool", tool.id, kind="service", label="Oil change",
        due_date=(today - timedelta(days=1)).isoformat(),
    )
    assert maintenance_service.run_overdue_notifications(db, today=today) == 1
    # Re-runs (same due date) create nothing more.
    assert maintenance_service.run_overdue_notifications(db, today=today) == 0
    assert maintenance_service.run_overdue_notifications(db, today=today) == 0

    notes = client.get(
        "/api/core/notifications", headers=auth_headers(owner)
    ).json()
    overdue = [n for n in notes if n["kind"] == "maintenance_overdue"]
    assert len(overdue) == 1
    assert overdue[0]["data"]["schedule_id"] == schedule["id"]

    # Log it done far in the past against a short interval: a NEW
    # due date goes overdue and earns its OWN notification.
    past = today - timedelta(days=40)
    client.patch(
        f"/api/maintenance/schedules/{schedule['id']}",
        json={"interval_days": 30, "last_done_at": past.isoformat()},
        headers=auth_headers(owner),
    )
    assert maintenance_service.run_overdue_notifications(db, today=today) == 1
    assert maintenance_service.run_overdue_notifications(db, today=today) == 0


# -- module gating ------------------------------------------------------------------


def test_module_off_gates_routes_and_stats(client, owner, operator, db):
    tool = _tool(db, owner)
    assert (
        client.get("/api/maintenance/stats", headers=auth_headers(owner)).status_code
        == 200
    )
    off = client.put(
        "/api/admin/modules/maintenance/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert off.status_code == 200, off.text
    for path in ("/api/maintenance/stats", "/api/maintenance/overview"):
        response = client.get(path, headers=auth_headers(owner))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "module_unavailable"
    mine = client.get("/api/core/my-modules", headers=auth_headers(owner)).json()
    assert "maintenance" not in {m["id"] for m in mine}
    # Inventory (the dependency's other dependent surfaces) is
    # untouched by maintenance going dark.
    assert client.get("/api/inventory", headers=auth_headers(owner)).status_code == 200
    assert tool is not None


def test_dealer_group_has_no_maintenance(client, db):
    dealer = _make_user(db, "TV-D-000404", "maint-dealer@example.com", [DEALER])
    response = client.get("/api/maintenance/stats", headers=auth_headers(dealer))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"


# -- the merged page's board endpoint (Repairs & Maintenance merge, 2026-11-05) -------


def _warranty_claim(db, owner, tool, status="reported", number="CL-2026-900"):
    """A bare open warranty claim driving `tool`'s repair, built
    directly (the lifecycle that files real claims lives in the
    claims tests; the board only reads the rows)."""
    from app.modules.claims import models as claim_models

    claim = claim_models.Claim(
        owner_id=owner.id,
        kind=claim_models.KIND_WARRANTY,
        status=status,
        claim_number=number,
        claim_year=2026,
        number_seq=900,
        description="Cracked housing",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    db.add(
        claim_models.ClaimLine(
            owner_id=owner.id,
            claim_id=claim.id,
            target_kind="tool",
            target_id=tool.id,
        )
    )
    db.commit()
    return claim


def test_out_of_service_board_endpoint_claimless(client, owner, db):
    tool = _tool(db, owner, name="Board drill")
    _mark_broken(client, owner, "tool", tool.id)
    response = client.get(
        "/api/maintenance/out-of-service", headers=auth_headers(owner)
    )
    assert response.status_code == 200, response.text
    (entry,) = response.json()
    assert entry["item_name"] == "Board drill"
    assert entry["claim_id"] is None
    assert entry["claim_number"] is None
    assert entry["claim_status"] is None


def test_out_of_service_board_carries_claim_status(client, owner, db):
    tool = _tool(db, owner, name="Claimed saw")
    _mark_broken(client, owner, "tool", tool.id)
    claim = _warranty_claim(db, owner, tool, status="in_repair")
    (entry,) = client.get(
        "/api/maintenance/out-of-service", headers=auth_headers(owner)
    ).json()
    assert entry["claim_id"] == str(claim.id)
    assert entry["claim_number"] == "CL-2026-900"
    assert entry["claim_status"] == "in_repair"
    # The problem is the claim's while a claim drives the repair.
    assert entry["problem"] == "Cracked housing"


def test_out_of_service_board_survives_maintenance_off(client, owner, operator, db):
    tool = _tool(db, owner, name="Off module drill")
    _mark_broken(client, owner, "tool", tool.id)
    off = client.put(
        "/api/admin/modules/maintenance/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert off.status_code == 200, off.text
    # The maintenance module's own page read is gated off…
    assert (
        client.get(
            "/api/maintenance/overview", headers=auth_headers(owner)
        ).status_code
        == 403
    )
    # …but the board rides on inventory now and still answers.
    response = client.get(
        "/api/maintenance/out-of-service", headers=auth_headers(owner)
    )
    assert response.status_code == 200, response.text
    assert [e["item_name"] for e in response.json()] == ["Off module drill"]


def test_out_of_service_board_hides_claim_facts_when_claims_off(
    client, owner, operator, db
):
    tool = _tool(db, owner, name="Quiet claim saw")
    _mark_broken(client, owner, "tool", tool.id)
    _warranty_claim(db, owner, tool)
    off = client.put(
        "/api/admin/modules/claims/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert off.status_code == 200, off.text
    (entry,) = client.get(
        "/api/maintenance/out-of-service", headers=auth_headers(owner)
    ).json()
    # The standing still boards; the claim facts do not ride.
    assert entry["item_name"] == "Quiet claim saw"
    assert entry["claim_id"] is None
    assert entry["claim_number"] is None
    assert entry["claim_status"] is None


def test_out_of_service_board_needs_inventory(client, db):
    dealer = _make_user(db, "TV-D-000405", "board-dealer@example.com", [DEALER])
    response = client.get(
        "/api/maintenance/out-of-service", headers=auth_headers(dealer)
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"


# -- borrowing interplay -------------------------------------------------------------


def test_broken_item_cannot_be_checked_out(client, owner, db):
    tool = _tool(db, owner, name="Impact wrench")
    _mark_broken(client, owner, "tool", tool.id)
    blocked = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "borrower_name": "Nate",
        },
        headers=auth_headers(owner),
    )
    assert blocked.status_code == 422, blocked.text
    assert "broken" in blocked.json()["detail"]

    # Back in service again -> the lend goes through.
    _set_standing(client, owner, "tool", tool.id, "in_service")
    ok = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "borrower_name": "Nate",
        },
        headers=auth_headers(owner),
    )
    assert ok.status_code == 201, ok.text


def test_checked_out_item_can_be_marked_broken(client, owner, db):
    tool = _tool(db, owner, name="Shop press")
    lent = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "borrower_name": "Nate",
        },
        headers=auth_headers(owner),
    )
    assert lent.status_code == 201, lent.text

    # It breaks in the field: marking broken works and the lend
    # is NOT auto-closed.
    _mark_broken(client, owner, "tool", tool.id)
    assert _standing(client, owner, "tool", tool.id)["state"] == "broken"
    lending = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    assert lending["current"]["state"] == "checked_out"

    # And the hand-back still works while it's broken.
    back = client.post(
        f"/api/borrowing/{lent.json()['id']}/return",
        headers=auth_headers(owner),
    )
    assert back.status_code == 200, back.text


def test_peer_payload_never_carries_repair_data(client, owner, other, db):
    # The peer whitelist is FIXED (identity + photos + owner): a
    # broken tool shows a peer exactly what a healthy one does.
    tool = _tool(db, owner, name="Impact wrench")
    _mark_broken(client, owner, "tool", tool.id)
    grant = core_models.PeerShare(
        owner_id=owner.id, viewer_user_id=other.id, status="accepted"
    )
    db.add(grant)
    db.commit()

    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    )
    assert body.status_code == 200, body.text
    (item,) = body.json()["items"]
    # Exactly the pinned whitelist (tool items carry no "kind" key).
    assert set(item.keys()) == {
        "id",
        "name",
        "brand",
        "model",
        "category",
        # Package B: condition left the peer whitelist entirely.
        "photos",
        "owner",
    }
    for forbidden in ("repair_state", "repair_problem", "warranty_status", "standing"):
        assert forbidden not in item
