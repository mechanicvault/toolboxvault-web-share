"""Dealer directory LIST row — the one-phone contact seam
(owner, 2026-11-04 22:40).

The directory list row shows exactly ONE contact number: the
preferred agent's number when he has one on record, else the
dealer's own. Both halves of that rule ride the preferred read
(the batched list the /dealers page already loads, resolved by
the same flagged-row seam as the on-record endpoint):

  - a PRIVATE preferred agent's number is his record's phone
    (already serialized — pinned here because the row depends
    on it);
  - a PLATFORM preferred agent's number is his agent PROFILE's
    phone — serialize_preferred used to leave it blank, so the
    directory row would have fallen back to the dealer's number
    even when the agent had one on record;
  - a platform agent with no profile phone still serializes
    blank, so the fallback to the dealer's number (the company
    read's customer_service_phone) stays honest.

The row rebuild (owner, 2026-11-06) widened the same seam:
the row now stands the ONE shown agent's phone, EMAIL and
next route day in the dealer's place, so the preferred read
also carries his email and his next_visit — computed from
his route schedule exactly as the roster computes it
(route_days.next_route_visit), for private records and
platform profiles alike. With no complete schedule the read
carries next_visit None and the row's route cell is empty.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.dealers import portal
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
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
    return _make_user(
        db, "TV-M-003201", "dirlist-owner@example.com", [MECHANIC], "Olive Owner"
    )


@pytest.fixture()
def agent_user(db):
    return _make_user(
        db, "TV-D-003202", "dirlist-agent@example.com", [DEALER], "Adam Agent"
    )


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(
        name="List Row Tools",
        is_directory=True,
        phones=[
            {"label": "Customer Service", "number": "800-555-0100"},
            {"label": "General", "number": "800-555-0101"},
        ],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _preferred_rows(client, owner, company):
    resp = client.get(
        "/api/dealers/preferred",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _connect_platform(client, owner, company, agent_user):
    resp = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": str(company.id),
            "agent_account_number": agent_user.account_number,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_private_preferred_phone_rides_the_preferred_read(
    client, db, owner, company
):
    resp = client.post(
        "/api/dealers/agents/private",
        json={
            "company_id": str(company.id),
            "name": "Private Pete",
            "phone": "555-0119",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    rows = _preferred_rows(client, owner, company)
    flagged = [r for r in rows if r["is_preferred"]]
    assert len(flagged) == 1
    assert flagged[0]["kind"] == "private"
    assert flagged[0]["phone"] == "555-0119"


def test_platform_preferred_phone_comes_from_his_profile(
    client, db, owner, company, agent_user
):
    portal.update_profile(db, agent_user, {"phone": "555-0140"})
    connected = _connect_platform(client, owner, company, agent_user)
    assert connected["is_preferred"] is True
    assert connected["phone"] == "555-0140"

    rows = _preferred_rows(client, owner, company)
    flagged = [r for r in rows if r["is_preferred"]]
    assert len(flagged) == 1
    assert flagged[0]["kind"] == "platform"
    assert flagged[0]["phone"] == "555-0140"

    # The on-record summary resolves the same row — same phone.
    on_record = client.get(
        "/api/dealers/preferred/on-record",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    )
    assert on_record.status_code == 200, on_record.text
    assert on_record.json()["state"] == "one"
    assert on_record.json()["agent"]["phone"] == "555-0140"


def test_platform_preferred_without_a_profile_phone_stays_blank(
    client, db, owner, company, agent_user
):
    # No profile at all: nothing on record, so the row's number
    # must come from the dealer — whose own customer-service
    # pick is untouched by this lane.
    connected = _connect_platform(client, owner, company, agent_user)
    assert connected["phone"] == ""

    view = client.get(
        f"/api/dealers/companies/{company.id}", headers=auth_headers(owner)
    )
    assert view.status_code == 200, view.text
    assert view.json()["customer_service_phone"] == "800-555-0100"
    assert view.json()["phones"][0]["number"] == "800-555-0100"


def _route_triple(days_ahead=3):
    """A weekly route whose next visit is exactly `days_ahead`
    days from today (today's weekday + days_ahead)."""
    from datetime import date, timedelta

    target = date.today() + timedelta(days=days_ahead)
    return target, {
        "route_frequency": "weekly",
        "route_day_of_week": target.weekday(),
        "route_anchor_date": date.today().isoformat(),
    }


def test_private_preferred_email_and_next_visit_ride_the_read(
    client, db, owner, company
):
    target, route = _route_triple()
    resp = client.post(
        "/api/dealers/agents/private",
        json={
            "company_id": str(company.id),
            "name": "Routed Ruth",
            "phone": "555-0130",
            "email": "ruth@example.com",
            **route,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text

    rows = _preferred_rows(client, owner, company)
    flagged = [r for r in rows if r["is_preferred"]]
    assert len(flagged) == 1
    assert flagged[0]["email"] == "ruth@example.com"
    assert flagged[0]["next_visit"] == target.isoformat()

    # The on-record summary carries the same facts.
    on_record = client.get(
        "/api/dealers/preferred/on-record",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    )
    assert on_record.status_code == 200, on_record.text
    assert on_record.json()["agent"]["next_visit"] == target.isoformat()


def test_private_preferred_without_a_route_has_no_next_visit(
    client, db, owner, company
):
    resp = client.post(
        "/api/dealers/agents/private",
        json={
            "company_id": str(company.id),
            "name": "Routeless Ron",
            "phone": "555-0131",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    rows = _preferred_rows(client, owner, company)
    flagged = [r for r in rows if r["is_preferred"]]
    assert len(flagged) == 1
    assert flagged[0]["next_visit"] is None


def test_platform_preferred_email_and_next_visit_come_from_his_profile(
    client, db, owner, company, agent_user
):
    target, route = _route_triple()
    # Direct service call (no HTTP layer): the anchor rides as
    # a date object, the shape the profile write stores.
    from datetime import date

    route = {**route, "route_anchor_date": date.fromisoformat(route["route_anchor_date"])}
    portal.update_profile(
        db,
        agent_user,
        {
            "phone": "555-0140",
            "contact_email": "adam@example.com",
            **route,
        },
    )
    connected = _connect_platform(client, owner, company, agent_user)
    assert connected["is_preferred"] is True
    assert connected["email"] == "adam@example.com"
    assert connected["next_visit"] == target.isoformat()

    rows = _preferred_rows(client, owner, company)
    flagged = [r for r in rows if r["is_preferred"]]
    assert len(flagged) == 1
    assert flagged[0]["kind"] == "platform"
    assert flagged[0]["email"] == "adam@example.com"
    assert flagged[0]["next_visit"] == target.isoformat()
