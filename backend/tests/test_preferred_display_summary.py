"""Preferred-agent DISPLAY summary (owner ruling 2026-11-06).

Summary displays of "the viewer's preferred agent" for a
dealer (the dealer list row, the item pages' agent line, the
Warranty tab's current-agent row — all reading
GET /dealers/preferred/on-record) resolve to a SUMMARY:

  - exactly ONE preferred agent flagged → state "one", and
    the agent rides along — displays name him as before;
  - MORE THAN ONE flagged → state "many", agent None —
    displays show "Multiple Agents" and name nobody;
  - ZERO flagged → the standing pre-flag behavior: the
    earliest connection as "one", or "none" with no agent
    when the user has no connection for the company at all.

FUNCTIONAL defaults are a different read and do NOT follow
the summary: a claim's pre-picked agent (claims
.agent_on_record) still resolves the EARLIEST flagged agent
even in the "many" state — pinned here so the two reads can
never drift into each other.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.claims import service as claims_service
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Test User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-004101", "prefdisplay-owner@example.com", "Olive Owner")


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(
        name="Summary Tools",
        is_directory=True,
        phones=[{"label": "Customer Service", "number": "800-555-0100"}],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _private_agent(client, owner, company, name, phone=""):
    resp = client.post(
        "/api/dealers/agents/private",
        json={"company_id": str(company.id), "name": name, "phone": phone},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_flag(client, owner, company, private_id, is_preferred=True):
    resp = client.post(
        "/api/dealers/preferred/flag",
        json={
            "company_id": str(company.id),
            "private_agent_id": str(private_id),
            "is_preferred": is_preferred,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _separate_connections(db, owner, first_private_id, second_private_id):
    """Backdate the two CONNECTION rows so "earliest" is
    deterministic: the resolvers order by the connection's
    (created_at, id), and two rows written in the same second
    would otherwise resolve by UUID coin flip."""
    for private_id, minutes in ((first_private_id, 2), (second_private_id, 1)):
        row = db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == owner.id,
                dealer_models.PreferredAgent.private_agent_id
                == uuid.UUID(private_id),
            )
        ).one()
        row.created_at -= timedelta(minutes=minutes)
    db.commit()


def _summary(client, owner, company):
    resp = client.get(
        "/api/dealers/preferred/on-record",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_connection_is_none(client, owner, company):
    assert _summary(client, owner, company) == {"state": "none", "agent": None}


def test_one_flagged_agent_is_named(client, owner, company):
    pete = _private_agent(client, owner, company, "Private Pete", "555-0119")
    summary = _summary(client, owner, company)
    assert summary["state"] == "one"
    assert summary["agent"]["private_agent_id"] == pete["id"]
    assert summary["agent"]["name"] == "Private Pete"
    assert summary["agent"]["phone"] == "555-0119"


def test_two_flagged_agents_are_many_and_name_nobody(
    client, db, owner, company
):
    pete = _private_agent(client, owner, company, "Private Pete", "555-0119")
    sue = _private_agent(client, owner, company, "Second Sue", "555-0120")
    _separate_connections(db, owner, pete["id"], sue["id"])
    # Pete auto-flagged as the first connection; star Sue too.
    _set_flag(client, owner, company, sue["id"])

    summary = _summary(client, owner, company)
    assert summary == {"state": "many", "agent": None}

    # The FUNCTIONAL default is untouched by the display rule:
    # claims still pre-pick the EARLIEST flagged agent (Pete).
    pair = claims_service.agent_on_record(db, owner.id, company.id)
    assert pair is not None
    agent_user_id, private_agent_id = pair
    assert agent_user_id is None
    assert str(private_agent_id) == pete["id"]


def test_unstarring_back_to_one_names_the_survivor(client, owner, company):
    pete = _private_agent(client, owner, company, "Private Pete")
    sue = _private_agent(client, owner, company, "Second Sue")
    _set_flag(client, owner, company, sue["id"])
    assert _summary(client, owner, company)["state"] == "many"

    _set_flag(client, owner, company, pete["id"], is_preferred=False)
    summary = _summary(client, owner, company)
    assert summary["state"] == "one"
    assert summary["agent"]["private_agent_id"] == sue["id"]


def test_zero_flagged_falls_back_to_the_earliest_connection(
    client, db, owner, company
):
    pete = _private_agent(client, owner, company, "Private Pete")
    sue = _private_agent(client, owner, company, "Second Sue")
    _separate_connections(db, owner, pete["id"], sue["id"])
    # Unstar the only flagged row: connections remain, none
    # flagged — the pre-flag resolution (earliest row) holds.
    _set_flag(client, owner, company, pete["id"], is_preferred=False)
    summary = _summary(client, owner, company)
    assert summary["state"] == "one"
    assert summary["agent"]["private_agent_id"] == pete["id"]
