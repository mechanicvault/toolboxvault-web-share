"""GET /api/inventory/stats — owner-scoped vault totals for the home
page overview row. Semantics are defined on schemas.InventoryStats:
market value sums msrp (unset contributes 0), replacement sums
replacement_cost, category_count counts distinct non-empty categories.
"""

from decimal import Decimal

import pytest

from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _mechanic_users(db, user_a, user_b):
    # Inventory routes are mechanic-gated (owner directive 2026-10-17);
    # the shared fixtures predate groups, so grant the group here.
    for user in (user_a, user_b):
        user.account_types = ["mechanic_technician"]
    db.commit()


def _create_tool(client, user, **overrides):
    payload = {"name": "Wrench"}
    payload.update(overrides)
    response = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def test_stats_requires_auth(client):
    assert client.get("/api/inventory/stats").status_code == 401


def test_stats_route_resolves_before_tool_id_wildcard(client, user_a):
    # "/stats" must not be swallowed by GET /{tool_id} (audit C2 pattern).
    response = client.get("/api/inventory/stats", headers=auth_headers(user_a))
    assert response.status_code == 200


def test_stats_empty_vault_is_zeros(client, user_a):
    response = client.get("/api/inventory/stats", headers=auth_headers(user_a))
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 0
    assert body["total_quantity"] == 0
    assert Decimal(body["total_market_value"]) == Decimal("0.00")
    assert Decimal(body["total_replacement_cost"]) == Decimal("0.00")
    assert body["category_count"] == 0


def test_stats_sums_owner_tools(client, user_a):
    _create_tool(
        client,
        user_a,
        name="Drill",
        category="Power tools",
        msrp="129.50",
        replacement_cost="149.99",
    )
    _create_tool(
        client,
        user_a,
        name="Wrench set",
        category="Hand tools",
        msrp="87.20",
        replacement_cost="102.00",
    )
    # Same category again (counted once), no msrp (contributes 0 to
    # market value), no category (not counted as a category).
    _create_tool(client, user_a, name="Hammer", category="Hand tools")
    _create_tool(client, user_a, name="Mystery tool", replacement_cost="10.00")

    body = client.get("/api/inventory/stats", headers=auth_headers(user_a)).json()
    assert body["total_items"] == 4
    assert Decimal(body["total_market_value"]) == Decimal("216.70")
    assert Decimal(body["total_replacement_cost"]) == Decimal("261.99")
    assert body["category_count"] == 2


def test_stats_exclude_other_users_tools(client, user_a, user_b):
    _create_tool(
        client,
        user_b,
        name="Not yours",
        category="Power tools",
        msrp="999.99",
        replacement_cost="999.99",
    )
    body = client.get("/api/inventory/stats", headers=auth_headers(user_a)).json()
    assert body["total_items"] == 0
    assert Decimal(body["total_market_value"]) == Decimal("0.00")
    assert Decimal(body["total_replacement_cost"]) == Decimal("0.00")
    assert body["category_count"] == 0

    # ...and B sees exactly its own tool.
    body_b = client.get("/api/inventory/stats", headers=auth_headers(user_b)).json()
    assert body_b["total_items"] == 1
    assert Decimal(body_b["total_market_value"]) == Decimal("999.99")
    assert body_b["category_count"] == 1


def test_stats_total_quantity_sums_units(client, user_a):
    # total_quantity (owner order, 2026-11-10) counts physical
    # units over the same population total_items counts records:
    # a record with quantity 3 contributes 3, across both kinds.
    _create_tool(client, user_a, name="Single wrench")
    _create_tool(client, user_a, name="Socket set", quantity=3)
    resp = client.post(
        "/api/inventory/batteries",
        json={"name": "Twin pack", "quantity": 2},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 201, resp.text

    body = client.get("/api/inventory/stats", headers=auth_headers(user_a)).json()
    assert body["total_items"] == 3
    assert body["total_quantity"] == 6


# -- warranty counters (audit A6) ----------------------------------------------


def test_stats_warranty_counters_empty_vault(client, user_a):
    body = client.get(
        "/api/inventory/stats", headers=auth_headers(user_a)
    ).json()
    assert body["warranties_expiring_soon"] == 0
    assert body["warranties_expired"] == 0


def test_stats_warranty_counters_use_the_shared_computation(client, user_a):
    from datetime import date, timedelta

    today = date.today()
    # Ends ~15 days out -> expiring soon (the 30-day window).
    _create_tool(
        client,
        user_a,
        name="Expiring drill",
        purchase_date=(today - timedelta(days=350)).isoformat(),
        warranty_months=12,
    )
    # Ended ~35 days ago -> expired.
    _create_tool(
        client,
        user_a,
        name="Dead warranty saw",
        purchase_date=(today - timedelta(days=400)).isoformat(),
        warranty_months=12,
    )
    # Comfortably covered -> neither counter.
    _create_tool(
        client,
        user_a,
        name="Covered wrench",
        purchase_date=(today - timedelta(days=10)).isoformat(),
        warranty_months=24,
    )
    # Lifetime coverage never counts, even with no dates at all.
    _create_tool(client, user_a, name="Lifetime ratchet", warranty_type="lifetime")
    # No warranty data -> unknown, never counts.
    _create_tool(client, user_a, name="Mystery tool")
    # A battery counts too (same shared computation, both kinds).
    resp = client.post(
        "/api/inventory/batteries",
        json={
            "name": "Old pack",
            "purchase_date": (today - timedelta(days=400)).isoformat(),
            "warranty_months": 12,
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 201, resp.text

    body = client.get(
        "/api/inventory/stats", headers=auth_headers(user_a)
    ).json()
    assert body["warranties_expiring_soon"] == 1
    assert body["warranties_expired"] == 2  # the saw + the battery


def test_stats_warranty_counters_are_owner_scoped(client, user_a, user_b):
    from datetime import date, timedelta

    _create_tool(
        client,
        user_b,
        name="Someone else's expired tool",
        purchase_date=(date.today() - timedelta(days=400)).isoformat(),
        warranty_months=12,
    )
    body = client.get(
        "/api/inventory/stats", headers=auth_headers(user_a)
    ).json()
    assert body["warranties_expired"] == 0
    assert body["warranties_expiring_soon"] == 0
