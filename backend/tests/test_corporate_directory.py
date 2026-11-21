"""Corporate directory data (owner 2026-10-19): the warranty
fields on dealer companies — operator Admin CRUD round-trips them,
the user-facing serialization carries the warranty block, invalid
scope/kind values are refused, and private companies default to
no warranty data at all.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, is_operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Corporate User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=is_operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user(db):
    return _make_user(db, "TV-M-000501", "user@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000500", "operator@example.com", is_operator=True)


def _payload(**overrides):
    payload = {
        "name": "Acme Tools",
        "email": "",
        "website": "https://example.com",
        "address": "",
        "phones": [{"label": "Customer Service", "number": "800-555-0100"}],
        "notes": "",
    }
    payload.update(overrides)
    return payload


def _admin_create(client, operator, **overrides):
    resp = client.post(
        "/api/admin/dealer-companies",
        json=_payload(**overrides),
        headers=auth_headers(operator),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_admin_crud_round_trips_corporate_fields(client, operator, user):
    created = _admin_create(
        client,
        operator,
        kind="retailer",
        warranty_url="https://example.com/warranty",
        warranty_phone="888-555-0199",
        ship_to_name="Acme Warranty Returns",
        ship_to_address="1 Industrial Way\nSpringfield, IL 62701",
        ship_to_scope="scoped",
        ship_to_scope_note="Torque products only.",
        warranty_process={"gate": None, "notes": ["Keep the receipt."]},
        logo_key="platform/logos/acme.png",
        logo_tile="dark",
    )
    assert created["kind"] == "retailer"
    assert created["warranty_url"] == "https://example.com/warranty"
    assert created["warranty_phone"] == "888-555-0199"
    assert created["ship_to_name"] == "Acme Warranty Returns"
    assert created["ship_to_address"] == "1 Industrial Way\nSpringfield, IL 62701"
    assert created["ship_to_scope"] == "scoped"
    assert created["ship_to_scope_note"] == "Torque products only."
    assert created["warranty_process"] == {"gate": None, "notes": ["Keep the receipt."]}
    assert created["logo_key"] == "platform/logos/acme.png"
    assert created["logo_tile"] == "dark"
    assert created["customer_service_phone"] == "800-555-0100"

    # The user-facing detail serialization carries the same block.
    detail = client.get(
        f"/api/dealers/companies/{created['id']}", headers=auth_headers(user)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["ship_to_scope"] == "scoped"
    assert body["ship_to_scope_note"] == "Torque products only."
    assert body["warranty_process"]["notes"] == ["Keep the receipt."]

    # Update clears the ship-to (brand stops publishing a mail-in):
    # nulls come back as nulls, never stale values.
    resp = client.put(
        f"/api/admin/dealer-companies/{created['id']}",
        json=_payload(
            kind="retailer",
            ship_to_name=None,
            ship_to_address=None,
            ship_to_scope=None,
            ship_to_scope_note=None,
            warranty_process={"gate": "Call first.", "notes": []},
        ),
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["ship_to_address"] is None
    assert updated["ship_to_scope"] is None
    assert updated["warranty_process"] == {"gate": "Call first.", "notes": []}


def test_invalid_scope_kind_and_tile_are_refused(client, operator):
    for overrides in (
        {"ship_to_scope": "everywhere"},
        {"kind": "conglomerate"},
        {"logo_tile": "plaid"},
    ):
        resp = client.post(
            "/api/admin/dealer-companies",
            json=_payload(**overrides),
            headers=auth_headers(operator),
        )
        assert resp.status_code == 422, (overrides, resp.text)


def test_private_company_defaults_carry_no_warranty_data(client, user):
    resp = client.post(
        "/api/dealers/companies",
        json=_payload(name="My Local Co"),
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "manufacturer"
    assert body["warranty_url"] == ""
    assert body["warranty_phone"] is None
    assert body["ship_to_address"] is None
    assert body["ship_to_scope"] is None
    assert body["warranty_process"] is None
    assert body["logo_key"] is None
    assert body["logo_url"] is None
    assert body["logo_tile"] is None


def test_customer_service_phone_inference(client, operator):
    # The entry labeled "Customer Service" wins over order.
    created = _admin_create(
        client,
        operator,
        name="Labeled Co",
        phones=[
            {"label": "Billing", "number": "800-555-0111"},
            {"label": "Customer Service", "number": "800-555-0122"},
        ],
    )
    assert created["customer_service_phone"] == "800-555-0122"

    # No label -> the first listed number.
    created = _admin_create(
        client,
        operator,
        name="Unlabeled Co",
        phones=[{"label": "Corporate Office", "number": "800-555-0133"}],
    )
    assert created["customer_service_phone"] == "800-555-0133"

    # No phones at all -> null, never an invented number.
    created = _admin_create(client, operator, name="Phoneless Co", phones=[])
    assert created["customer_service_phone"] is None


def test_empty_warranty_process_normalizes_to_none(client, operator):
    created = _admin_create(
        client, operator, warranty_process={"gate": "  ", "notes": ["", "  "]}
    )
    assert created["warranty_process"] is None
    created = _admin_create(
        client, operator, name="Gate Only Co", warranty_process={"gate": "Form first."}
    )
    assert created["warranty_process"] == {"gate": "Form first.", "notes": []}
