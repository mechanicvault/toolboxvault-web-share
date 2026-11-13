"""Truck Accounts — the AGENT revision (owner, 2026-10-31).

The issuer is a specific dealer agent acting under a dealer
company they verified-represent; the account nests under that
company (the serializer carries company + agent + credit line);
route changes NEVER move an account — only the customer
transfers it, to another agent of the same dealer, with the
move written to the transfer history and both platform holders
notified; a transfer to the customer's private agent record
leaves the customer maintaining the tab himself.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.truck_accounts import models as truck_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name="Truck User"):
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


def _company(db, name="Matco Tools"):
    company = dealer_models.DealerCompany(
        id=uuid.uuid4(), name=name, is_directory=True
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _rep(db, user, company, *, verified=True, display_name=""):
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(),
            agent_user_id=user.id,
            company_id=company.id,
            verified=verified,
        )
    )
    if display_name:
        db.add(
            dealer_models.AgentProfile(
                id=uuid.uuid4(), user_id=user.id, display_name=display_name
            )
        )
    db.commit()


@pytest.fixture()
def company(db):
    return _company(db)


@pytest.fixture()
def agent(db, company):
    user = _make_user(
        db, "TV-D-000951", "matt@example.com", (DEALER,), name="Matt Agent"
    )
    _rep(db, user, company, display_name="Matt")
    return user


@pytest.fixture()
def agent2(db, company):
    user = _make_user(
        db, "TV-D-000952", "rachel@example.com", (DEALER,), name="Rachel Agent"
    )
    _rep(db, user, company, display_name="Rachel")
    return user


@pytest.fixture()
def customer(db):
    return _make_user(
        db, "TV-M-000951", "chris@example.com", (MECHANIC,), name="Chris Customer"
    )


def _create(client, agent, customer, **over):
    body = {
        "customer_account_number": customer.account_number,
        "customer_email": "",
        "payment_cadence": "weekly",
        "payment_amount": "50.00",
        "next_due_date": None,
    }
    body.update(over)
    resp = client.post(
        "/api/truck-accounts/accounts", json=body, headers=auth_headers(agent)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _accept(client, customer, account_id):
    detail = client.get(
        f"/api/truck-accounts/accounts/{account_id}",
        headers=auth_headers(customer),
    ).json()
    version = re.search(
        r"version ([0-9A-Za-z.-]+)\)", detail["agreement_preview"]
    ).group(1)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account_id}/accept",
        json={"agreement_version": version},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(client, user, account_id, **over):
    body = {
        "kind": "payment",
        "amount": "10.00",
        "note": "",
        "item_link_id": None,
        "entry_date": None,
    }
    body.update(over)
    return client.post(
        f"/api/truck-accounts/accounts/{account_id}/entries",
        json=body,
        headers=auth_headers(user),
    )


def _active(client, agent, customer, **over):
    account = _create(client, agent, customer, **over)
    _accept(client, customer, account["id"])
    return account


def _notifications(db, user_id, kind=None):
    rows = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == user_id)
        .all()
    )
    if kind:
        rows = [r for r in rows if r.kind == kind]
    return rows


# -- issuance -------------------------------------------------------------------


def test_issue_under_company_with_credit_line(client, db, agent, customer, company):
    account = _create(client, agent, customer, credit_limit="1500.00")
    assert account["dealer_company_id"] == str(company.id)
    assert account["dealer_company_name"] == "Matco Tools"
    # The agent's PROFILE display name is the name the customer reads.
    assert account["agent_name"] == "Matt"
    assert account["agent_kind"] == "platform"
    assert account["credit_limit"] == "1500.00"
    # Nothing charged yet: the whole line is available.
    assert account["credit_available"] == "1500.00"
    # The customer's own list carries the nesting facts.
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(customer)
    ).json()
    assert rows[0]["dealer_company_name"] == "Matco Tools"
    assert rows[0]["agent_name"] == "Matt"


def test_issue_refused_without_verified_rep(client, db, customer, company):
    hopeful = _make_user(
        db, "TV-D-000953", "hopeful@example.com", (DEALER,), name="Hope Ful"
    )
    body = {
        "customer_account_number": customer.account_number,
        "customer_email": "",
        "payment_cadence": "weekly",
        "payment_amount": "50.00",
        "next_due_date": None,
    }
    resp = client.post(
        "/api/truck-accounts/accounts", json=body, headers=auth_headers(hopeful)
    )
    assert resp.status_code == 422
    # An UNVERIFIED representation doesn't open the door either.
    _rep(db, hopeful, company, verified=False)
    resp = client.post(
        "/api/truck-accounts/accounts", json=body, headers=auth_headers(hopeful)
    )
    assert resp.status_code == 422


def test_issue_under_wrong_company_refused(client, db, agent, customer):
    other = _company(db, "Snap-on")
    body = {
        "customer_account_number": customer.account_number,
        "customer_email": "",
        "payment_cadence": "weekly",
        "payment_amount": "50.00",
        "next_due_date": None,
        "dealer_company_id": str(other.id),
    }
    resp = client.post(
        "/api/truck-accounts/accounts", json=body, headers=auth_headers(agent)
    )
    assert resp.status_code == 422


def test_second_agent_of_same_company_cannot_see(
    client, db, agent, agent2, customer
):
    account = _active(client, agent, customer)
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(agent2)
    ).json()
    assert rows == []
    resp = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(agent2),
    )
    assert resp.status_code == 404


# -- route changes do NOT move accounts ------------------------------------------


def test_agent_change_on_record_leaves_account_put(
    client, db, agent, agent2, customer, company
):
    account = _active(client, agent, customer)
    # The customer's agent ON RECORD changes (a new preferred
    # agent for the company — the claims world would follow;
    # truck accounts deliberately do NOT).
    db.add(
        dealer_models.PreferredAgent(
            id=uuid.uuid4(),
            user_id=customer.id,
            company_id=company.id,
            agent_user_id=agent2.id,
        )
    )
    db.commit()
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(customer)
    ).json()
    assert rows[0]["agent_name"] == "Matt"
    assert rows[0]["dealer_user_id"] == str(agent.id)
    # And the new agent on record still can't see it.
    assert (
        client.get(
            "/api/truck-accounts/accounts", headers=auth_headers(agent2)
        ).json()
        == []
    )


# -- transfers --------------------------------------------------------------------


def test_transfer_to_platform_agent(client, db, agent, agent2, customer):
    account = _active(client, agent, customer)
    _entry(client, agent, account["id"], kind="charge", amount="1000.00", note="Toolbox")
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    options = {o["name"]: o for o in detail["transfer_options"]}
    assert "Rachel" in options

    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/transfer",
        json={"to_agent_user_id": options["Rachel"]["agent_user_id"]},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert moved["dealer_user_id"] == str(agent2.id)
    assert moved["agent_name"] == "Rachel"
    # Balance and schedule carried over untouched.
    assert moved["balance"] == "1000.00"
    assert moved["payment_amount"] == "50.00"

    # The old agent loses it; the new agent holds it.
    assert (
        client.get(
            f"/api/truck-accounts/accounts/{account['id']}",
            headers=auth_headers(agent),
        ).status_code
        == 404
    )
    got = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(agent2),
    )
    assert got.status_code == 200
    assert got.json()["account"]["my_role"] == "dealer"

    # History + notifications.
    transfers = got.json()["transfers"]
    assert len(transfers) == 1
    assert transfers[0]["from_agent_name"] == "Matt"
    assert transfers[0]["to_agent_name"] == "Rachel"
    assert len(_notifications(db, agent.id, "truck_account_transferred")) == 1
    assert len(_notifications(db, agent2.id, "truck_account_transferred")) == 1


def test_transfer_to_private_agent_customer_maintains(
    client, db, agent, customer, company
):
    account = _active(client, agent, customer)
    record = dealer_models.PrivateAgent(
        id=uuid.uuid4(),
        owner_id=customer.id,
        company_id=company.id,
        name="Off Platform Otto",
    )
    db.add(record)
    db.commit()

    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/transfer",
        json={"to_private_agent_id": str(record.id)},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert moved["dealer_user_id"] is None
    assert moved["agent_kind"] == "private"
    assert moved["agent_name"] == "Off Platform Otto"
    assert moved["customer_maintained"] is True

    # The old platform agent is out.
    assert (
        client.get(
            f"/api/truck-accounts/accounts/{account['id']}",
            headers=auth_headers(agent),
        ).status_code
        == 404
    )
    # The customer maintains the tab: he records a CHARGE (the
    # off-platform agent's pen, in the customer's own record)
    # and sets the schedule.
    resp = _entry(
        client, customer, account["id"], kind="charge", amount="25.00",
        note="Off-truck purchase",
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/schedule",
        json={"payment_amount": "75.00"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_amount"] == "75.00"


def test_transfer_refusals(client, db, agent, agent2, customer):
    account = _active(client, agent, customer)
    # The dealer can't transfer (it's the customer's move).
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/transfer",
        json={"to_agent_user_id": str(agent2.id)},
        headers=auth_headers(agent),
    )
    assert resp.status_code in (404, 422)
    # An agent of a DIFFERENT company isn't a valid target.
    outsider = _make_user(
        db, "TV-D-000954", "outsider@example.com", (DEALER,), name="Out Sider"
    )
    other = _company(db, "Cornwell Tools")
    _rep(db, outsider, other)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/transfer",
        json={"to_agent_user_id": str(outsider.id)},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 422
    # Both targets at once is refused too.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/transfer",
        json={
            "to_agent_user_id": str(agent2.id),
            "to_private_agent_id": str(uuid.uuid4()),
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 422


# -- status summary (the dealers page strip) --------------------------------------


def test_status_summary_counts_and_route_visits(
    client, db, agent, agent2, customer, company
):
    account = _active(client, agent, customer)
    _entry(client, agent, account["id"], kind="charge", amount="1000.00", note="Toolbox")
    # The customer prefers agent2, whose route runs TODAY.
    today = date.today()
    profile = db.scalar(
        select(dealer_models.AgentProfile).where(
            dealer_models.AgentProfile.user_id == agent2.id
        )
    )
    profile.route_frequency = "weekly"
    profile.route_day_of_week = today.weekday()
    profile.route_anchor_date = today
    db.add(
        dealer_models.PreferredAgent(
            id=uuid.uuid4(),
            user_id=customer.id,
            company_id=company.id,
            agent_user_id=agent2.id,
        )
    )
    db.commit()

    summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(customer)
    ).json()
    assert summary["customer_open_accounts"] == 1
    assert summary["customer_total_balance"] == "1000.00"
    assert summary["dealer_open_accounts"] == 0
    visits = summary["route_visits"]
    assert len(visits) == 1
    assert visits[0]["agent_name"] == "Rachel"
    assert visits[0]["company_name"] == "Matco Tools"
    assert visits[0]["next_visit"] == today.isoformat()

    dealer_summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(agent)
    ).json()
    assert dealer_summary["dealer_open_accounts"] == 1
    assert dealer_summary["dealer_total_outstanding"] == "1000.00"
    assert dealer_summary["customer_open_accounts"] == 0


def test_status_summary_payments_this_week_boundaries(
    client, db, agent, customer
):
    """This week's payments (2026-11-10): payment entries dated
    in the current MONDAY-START calendar week count, on either
    side of the counter; last week's payments, this week's
    charges and this week's adjustments never do."""
    account = _active(client, agent, customer)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_sunday = monday - timedelta(days=1)
    _entry(
        client, agent, account["id"],
        kind="charge", amount="1000.00", note="Toolbox",
        entry_date=today.isoformat(),
    )
    # In the week: Monday itself, and today.
    _entry(
        client, agent, account["id"],
        kind="payment", amount="50.00",
        entry_date=monday.isoformat(),
    )
    _entry(
        client, agent, account["id"],
        kind="payment", amount="25.00",
        entry_date=today.isoformat(),
    )
    # Out of the week: last Sunday's payment must NOT count.
    _entry(
        client, agent, account["id"],
        kind="payment", amount="40.00",
        entry_date=last_sunday.isoformat(),
    )
    # An adjustment this week is not a payment.
    _entry(
        client, agent, account["id"],
        kind="adjustment", amount="-10.00", note="Goodwill",
        entry_date=today.isoformat(),
    )

    from decimal import Decimal

    summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(customer)
    ).json()
    assert Decimal(summary["payments_this_week"]) == Decimal("75.00")
    # The dealer sees the same money — payments he received.
    dealer_summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(agent)
    ).json()
    assert Decimal(dealer_summary["payments_this_week"]) == Decimal("75.00")


def test_status_summary_payments_this_week_empty_is_zero(
    client, db, agent, customer
):
    """An empty week reads an honest 0 — including a week whose
    only payment landed LAST week."""
    from decimal import Decimal

    account = _active(client, agent, customer)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    _entry(
        client, agent, account["id"],
        kind="payment", amount="60.00",
        entry_date=(monday - timedelta(days=2)).isoformat(),
    )
    summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(customer)
    ).json()
    assert Decimal(summary["payments_this_week"]) == Decimal("0")


def test_status_summary_payments_this_week_skips_closed_accounts(
    client, db, agent, customer
):
    """Closed accounts are frozen history: a payment recorded
    this week stops counting once the account is closed."""
    from decimal import Decimal

    account = _active(client, agent, customer)
    _entry(
        client, agent, account["id"],
        kind="charge", amount="300.00", note="Toolbox",
    )
    _entry(
        client, agent, account["id"],
        kind="payment", amount="300.00",
        entry_date=date.today().isoformat(),
    )
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/close",
        headers=auth_headers(agent),
    )
    assert resp.status_code == 200, resp.text
    summary = client.get(
        "/api/truck-accounts/status-summary", headers=auth_headers(customer)
    ).json()
    assert Decimal(summary["payments_this_week"]) == Decimal("0")


def test_issuable_companies_endpoint(client, db, agent, company):
    rows = client.get(
        "/api/truck-accounts/issuable-companies", headers=auth_headers(agent)
    ).json()
    assert rows == [
        {"company_id": str(company.id), "company_name": "Matco Tools"}
    ]
