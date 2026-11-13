"""The Add wizard's truck-account charge (owner, 2026-10-31).

Entering a tool (or battery), the buyer may put any portion of
the purchase price on his truck account with that dealer: an
ACTIVE account with the dealer company takes the charge in the
SAME transaction as the item save; with none, the wizard opens
a self-tab on the spot — NO agreement step (the owner's ruling)
— under the customer's agent on record (platform agent, private
record, or no agent at all: a company-linked, customer-
maintained tab). The question is create-only: edits never ask.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.core import inbox as inbox_mod
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inv_models
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


def _rep(db, user, company, *, display_name=""):
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(),
            agent_user_id=user.id,
            company_id=company.id,
            verified=True,
        )
    )
    if display_name:
        db.add(
            dealer_models.AgentProfile(
                id=uuid.uuid4(), user_id=user.id, display_name=display_name
            )
        )
    db.commit()


def _prefer_platform(db, customer, company, agent_user):
    db.add(
        dealer_models.PreferredAgent(
            id=uuid.uuid4(),
            user_id=customer.id,
            company_id=company.id,
            agent_user_id=agent_user.id,
        )
    )
    db.commit()


def _private_record(db, customer, company, name="Matt (paper card)"):
    record = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=customer.id, company_id=company.id, name=name
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _prefer_private(db, customer, company, record):
    db.add(
        dealer_models.PreferredAgent(
            id=uuid.uuid4(),
            user_id=customer.id,
            company_id=company.id,
            private_agent_id=record.id,
        )
    )
    db.commit()


@pytest.fixture()
def company(db):
    return _company(db)


@pytest.fixture()
def agent(db, company):
    user = _make_user(
        db, "TV-D-000961", "matt@example.com", (DEALER,), name="Matt Agent"
    )
    _rep(db, user, company, display_name="Matt")
    return user


@pytest.fixture()
def agent2(db, company):
    user = _make_user(
        db, "TV-D-000962", "rachel@example.com", (DEALER,), name="Rachel Agent"
    )
    _rep(db, user, company, display_name="Rachel")
    return user


@pytest.fixture()
def customer(db):
    return _make_user(
        db, "TV-M-000961", "chris@example.com", (MECHANIC,), name="Chris Customer"
    )


def _dealer_create(client, agent, customer, **over):
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


def _active_account(client, agent, customer, **over):
    account = _dealer_create(client, agent, customer, **over)
    _accept(client, customer, account["id"])
    return account


def _post_tool(client, customer, **over):
    body = {
        "name": "Torque Wrench 2000",
        "purchase_price": "250.00",
        "quantity": 1,
    }
    body.update(over)
    return client.post("/api/inventory", json=body, headers=auth_headers(customer))


def _accounts(db, customer):
    return list(
        db.scalars(
            select(truck_models.TruckAccount).where(
                truck_models.TruckAccount.customer_user_id == customer.id
            )
        )
    )


def _entries(db, account_id):
    return list(
        db.scalars(
            select(truck_models.TruckEntry).where(
                truck_models.TruckEntry.account_id == account_id
            )
        )
    )


def _balance(db, account_id):
    detail_entries = _entries(db, account_id)
    return sum((e.amount for e in detail_entries), Decimal("0"))


def _tools(db, owner_id):
    return list(
        db.scalars(
            select(inv_models.Tool).where(inv_models.Tool.owner_id == owner_id)
        )
    )


# -- the charge onto an existing active account ---------------------------------


def test_charge_lands_on_existing_active_account(
    client, db, agent, customer, company
):
    account = _active_account(client, agent, customer)
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "100.00"},
    )
    assert resp.status_code == 201, resp.text
    tool = resp.json()
    entries = _entries(db, uuid.UUID(account["id"]))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.kind == "charge"
    assert entry.amount == Decimal("100.00")
    assert entry.item_link_id == uuid.UUID(tool["id"])
    assert "Torque Wrench 2000" in entry.note
    assert entry.recorded_by == customer.id
    assert _balance(db, uuid.UUID(account["id"])) == Decimal("100.00")
    # The platform-agent holder gets the standard entry notice.
    notes = (
        db.query(core_models.Notification)
        .filter(
            core_models.Notification.user_id == agent.id,
            core_models.Notification.kind == inbox_mod.KIND_TRUCK_CHARGE,
        )
        .all()
    )
    assert len(notes) == 1


def test_charge_records_past_a_credit_line(client, db, agent, customer, company):
    account = _active_account(client, agent, customer, credit_limit="40.00")
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "100.00"},
    )
    assert resp.status_code == 201, resp.text
    assert _balance(db, uuid.UUID(account["id"])) == Decimal("100.00")


# -- self-opened tabs -------------------------------------------------------------


def test_self_open_under_platform_agent_on_record(
    client, db, agent, customer, company
):
    _prefer_platform(db, customer, company, agent)
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "250.00"},
    )
    assert resp.status_code == 201, resp.text
    accounts = _accounts(db, customer)
    assert len(accounts) == 1
    account = accounts[0]
    # Active immediately — no agreement step, nothing accepted.
    assert account.status == "active"
    assert account.agreement_accepted_at is None
    assert account.dealer_user_id == agent.id
    assert account.private_agent_id is None
    assert account.dealer_company_id == company.id
    assert account.credit_limit is None
    entries = _entries(db, account.id)
    assert len(entries) == 1
    assert entries[0].kind == "charge"
    assert entries[0].amount == Decimal("250.00")
    assert entries[0].item_link_id == uuid.UUID(resp.json()["id"])


def test_self_open_under_private_record_customer_maintains(
    client, db, customer, company
):
    record = _private_record(db, customer, company)
    _prefer_private(db, customer, company, record)
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "75.00"},
    )
    assert resp.status_code == 201, resp.text
    accounts = _accounts(db, customer)
    assert len(accounts) == 1
    account = accounts[0]
    assert account.status == "active"
    assert account.dealer_user_id is None
    assert account.private_agent_id == record.id
    assert _balance(db, account.id) == Decimal("75.00")
    # The customer maintains this tab: he can record a charge
    # himself through the ordinary entries endpoint.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account.id}/entries",
        json={
            "kind": "charge",
            "amount": "25.00",
            "note": "Socket off the truck",
            "item_link_id": None,
            "entry_date": None,
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    assert _balance(db, account.id) == Decimal("100.00")


def test_self_open_with_no_agent_at_all(client, db, customer, company):
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "60.00"},
    )
    assert resp.status_code == 201, resp.text
    accounts = _accounts(db, customer)
    assert len(accounts) == 1
    account = accounts[0]
    # The no-agent fit: company-linked, NO holder on either side
    # of the exactly-one pair — the customer is the only seat.
    assert account.status == "active"
    assert account.dealer_company_id == company.id
    assert account.dealer_user_id is None
    assert account.private_agent_id is None
    assert _balance(db, account.id) == Decimal("60.00")
    # And the tab stays maintainable by its owner (a payment and
    # a further charge both record). Stage 2: the further charge
    # carries a note — an unexplained increase is refused now
    # (every increase on the tab is explained).
    for kind, amount, note in (
        ("payment", "20.00", ""),
        ("charge", "5.00", "More gear off the truck"),
    ):
        resp = client.post(
            f"/api/truck-accounts/accounts/{account.id}/entries",
            json={
                "kind": kind,
                "amount": amount,
                "note": note,
                "item_link_id": None,
                "entry_date": None,
            },
            headers=auth_headers(customer),
        )
        assert resp.status_code == 201, resp.text
    assert _balance(db, account.id) == Decimal("45.00")


# -- validation + atomicity --------------------------------------------------------


def test_amount_over_price_refused_and_saves_nothing(
    client, db, customer, company
):
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "250.01"},
    )
    assert resp.status_code == 422, resp.text
    assert _tools(db, customer.id) == []
    assert _accounts(db, customer) == []


def test_charge_without_dealer_refused(client, db, customer):
    resp = _post_tool(client, customer, truck_charge={"amount": "10.00"})
    assert resp.status_code == 422, resp.text
    assert _tools(db, customer.id) == []
    assert _accounts(db, customer) == []


def test_bad_account_choice_rolls_back_the_tool(
    client, db, agent, agent2, customer, company
):
    # An active account that belongs to ANOTHER customer: naming
    # it must fail the whole save — no tool, no entry anywhere.
    other = _make_user(
        db, "TV-M-000962", "sam@example.com", (MECHANIC,), name="Sam Other"
    )
    foreign = _active_account(client, agent, other)
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "10.00", "account_id": foreign["id"]},
    )
    assert resp.status_code == 422, resp.text
    assert _tools(db, customer.id) == []
    assert _accounts(db, customer) == []
    assert _entries(db, uuid.UUID(foreign["id"])) == []


# -- several active accounts: the chooser ------------------------------------------


def test_multiple_active_accounts_need_a_choice(
    client, db, agent, agent2, customer, company
):
    first = _active_account(client, agent, customer)
    second = _active_account(client, agent2, customer)
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "30.00"},
    )
    assert resp.status_code == 422, resp.text
    assert _tools(db, customer.id) == []
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "30.00", "account_id": second["id"]},
    )
    assert resp.status_code == 201, resp.text
    assert _balance(db, uuid.UUID(first["id"])) == Decimal("0")
    assert _balance(db, uuid.UUID(second["id"])) == Decimal("30.00")


# -- the invited-account interaction -------------------------------------------------


def test_invited_account_is_not_current_and_does_not_block(
    client, db, agent, customer, company
):
    invited = _dealer_create(client, agent, customer)
    ctx = client.get(
        "/api/truck-accounts/wizard-context",
        params={"company_id": str(company.id)},
        headers=auth_headers(customer),
    )
    assert ctx.status_code == 200, ctx.text
    ctx = ctx.json()
    assert ctx["active_accounts"] == []
    assert ctx["invited_exists"] is True
    resp = _post_tool(
        client,
        customer,
        dealer_company_id=str(company.id),
        truck_charge={"amount": "45.00"},
    )
    assert resp.status_code == 201, resp.text
    accounts = _accounts(db, customer)
    assert len(accounts) == 2
    by_id = {a.id: a for a in accounts}
    # The invite stands untouched — still awaiting acceptance,
    # still empty; the charge opened its own self-tab.
    assert by_id[uuid.UUID(invited["id"])].status == "invited"
    assert _balance(db, uuid.UUID(invited["id"])) == Decimal("0")
    opened = [a for a in accounts if a.id != uuid.UUID(invited["id"])]
    assert len(opened) == 1
    assert opened[0].status == "active"
    assert _balance(db, opened[0].id) == Decimal("45.00")


# -- the wizard context + the battery branch + edits ---------------------------------


def test_wizard_context_lists_active_accounts(client, db, agent, customer, company):
    account = _active_account(client, agent, customer)
    ctx = client.get(
        "/api/truck-accounts/wizard-context",
        params={"company_id": str(company.id)},
        headers=auth_headers(customer),
    )
    assert ctx.status_code == 200, ctx.text
    ctx = ctx.json()
    assert ctx["company_name"] == company.name
    assert ctx["invited_exists"] is False
    assert len(ctx["active_accounts"]) == 1
    row = ctx["active_accounts"][0]
    assert row["id"] == account["id"]
    assert row["agent_name"] == "Matt"
    assert Decimal(row["balance"]) == Decimal("0")


def test_battery_branch_charge(client, db, customer, company):
    resp = client.post(
        "/api/inventory/batteries",
        json={
            "name": "M18 5.0 Pack",
            "purchase_price": "120.00",
            "quantity": 1,
            "dealer_company_id": str(company.id),
            "truck_charge": {"amount": "120.00"},
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    accounts = _accounts(db, customer)
    assert len(accounts) == 1
    entries = _entries(db, accounts[0].id)
    assert len(entries) == 1
    assert entries[0].item_link_id == uuid.UUID(resp.json()["id"])
    assert "M18 5.0 Pack" in entries[0].note
    assert _balance(db, accounts[0].id) == Decimal("120.00")


def test_editing_never_charges(client, db, agent, customer, company):
    account = _active_account(client, agent, customer)
    created = _post_tool(client, customer, dealer_company_id=str(company.id))
    assert created.status_code == 201, created.text
    tool_id = created.json()["id"]
    resp = client.put(
        f"/api/inventory/{tool_id}",
        json={
            "purchase_price": "300.00",
            "truck_charge": {"amount": "300.00"},
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    assert _entries(db, uuid.UUID(account["id"])) == []
