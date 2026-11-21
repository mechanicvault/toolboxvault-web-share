"""Route resolution (audit C2), proven over real HTTP: literal segments
must beat /{tool_id}. If the ordering regresses, /field-definitions dies
with a 422 (UUID parse of "field-definitions") instead of returning 200.
"""

import uuid

import pytest

from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _mechanic_user(db, user_a):
    # Inventory routes are mechanic-gated (owner directive 2026-10-17);
    # the shared fixture predates groups, so grant the group here.
    user_a.account_types = ["mechanic_technician"]
    db.commit()


def test_field_definitions_route_is_not_swallowed_by_tool_id(client, user_a):
    response = client.get(
        "/api/inventory/field-definitions", headers=auth_headers(user_a)
    )
    assert response.status_code == 200
    assert response.json() == []


def test_field_definition_create_then_list_round_trip(client, user_a):
    headers = auth_headers(user_a)
    created = client.post(
        "/api/inventory/field-definitions",
        headers=headers,
        json={"name": "vin", "label": "VIN", "field_type": "text"},
    )
    assert created.status_code == 201
    listed = client.get("/api/inventory/field-definitions", headers=headers)
    assert [d["name"] for d in listed.json()] == ["vin"]


def test_search_route_is_not_swallowed_by_tool_id(client, user_a):
    response = client.get("/api/inventory/search", headers=auth_headers(user_a))
    assert response.status_code == 200
    assert response.json() == []


def test_tool_detail_route_still_matches_a_uuid(client, user_a):
    response = client.get(
        f"/api/inventory/{uuid.uuid4()}", headers=auth_headers(user_a)
    )
    assert response.status_code == 404


def test_auth_token_routes_exist(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    for expected in (
        "/api/core/signup",
        "/api/core/login",
        "/api/core/refresh",
        "/api/core/logout",
        "/api/core/verify-email",
        "/api/core/me",
    ):
        assert expected in paths
