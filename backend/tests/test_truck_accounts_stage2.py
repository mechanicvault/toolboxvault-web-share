"""Truck Accounts — STAGE 2 (owner model, 2026-11-04; build,
2026-11-05): the mechanic's seat.

The customer opens a SELF-KEPT account against any agent on
his roster (his own record or a connected registered agent)
with an opening balance and keeps the ledger himself; every
increase is explained (a note, or the tool a charge links to);
missed payments are computed and shown as missed; a linked
agent sees the same tab and can REQUEST a payment, which the
customer approves (the payment entry lands, marked
agent_request) or declines; the wizard charge targets the
PREFERRED agent's tab; statements render.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.truck_accounts import models as truck_models
from app.modules.truck_accounts import service
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


@pytest.fixture()
def company(db):
    company = dealer_models.DealerCompany(
        id=uuid.uuid4(), name="Matco Tools", is_directory=True
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@pytest.fixture()
def agent(db, company):
    """A registered agent who verified-represents the company."""
    user = _make_user(
        db, "TV-D-000971", "matt2@example.com", (DEALER,), name="Matt Agent"
    )
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(),
            agent_user_id=user.id,
            company_id=company.id,
            verified=True,
        )
    )
    db.add(
        dealer_models.AgentProfile(
            id=uuid.uuid4(), user_id=user.id, display_name="Matt"
        )
    )
    db.commit()
    return user


@pytest.fixture()
def customer(db):
    return _make_user(
        db, "TV-M-000971", "chris2@example.com", (MECHANIC,),
        name="Chris Customer",
    )


def _private_record(db, customer, company, name="Austin"):
    record = dealer_models.PrivateAgent(
        id=uuid.uuid4(),
        owner_id=customer.id,
        company_id=company.id,
        name=name,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _connect(db, customer, company, *, agent_user_id=None,
             private_agent_id=None, preferred=False):
    row = dealer_models.PreferredAgent(
        id=uuid.uuid4(),
        user_id=customer.id,
        company_id=company.id,
        agent_user_id=agent_user_id,
        private_agent_id=private_agent_id,
        is_preferred=preferred,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _open_self(client, customer, **over):
    body = {
        "company_id": over.pop("company_id"),
        "private_agent_id": over.pop("private_agent_id", None),
        "agent_user_id": over.pop("agent_user_id", None),
        "opening_balance": "0",
        "opening_note": "",
        "payment_cadence": "weekly",
        "payment_amount": None,
        "next_due_date": None,
        "payment_mode": "manual",
    }
    body.update(over)
    return client.post(
        "/api/truck-accounts/accounts/self",
        json=body,
        headers=auth_headers(customer),
    )


def _entry(client, user, account_id, **body):
    payload = {
        "kind": "payment",
        "amount": "10.00",
        "note": "",
        "item_link_id": None,
        "entry_date": None,
    }
    payload.update(body)
    return client.post(
        f"/api/truck-accounts/accounts/{account_id}/entries",
        json=payload,
        headers=auth_headers(user),
    )


def _notifications(db, user_id, kind=None):
    rows = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == user_id)
        .all()
    )
    if kind:
        rows = [r for r in rows if r.kind == kind]
    return rows


# -- opening a self-kept account ---------------------------------------------------


def test_open_self_on_private_record_with_opening_balance(
    client, db, customer, company
):
    record = _private_record(db, customer, company)
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="250.00",
        payment_amount="50.00",
    )
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["status"] == "active"
    assert account["ledger_keeper"] == "customer"
    assert account["customer_maintained"] is True
    assert account["agent_kind"] == "private"
    assert account["agent_name"] == "Austin"
    assert account["agreement_version"] is None
    assert Decimal(account["balance"]) == Decimal("250.00")
    # The opening balance is the first entry, explained by the
    # standing note when the customer wrote none of his own.
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    assert len(detail["entries"]) == 1
    entry = detail["entries"][0]
    assert entry["kind"] == "charge"
    assert entry["note"] == "Opening balance"
    assert entry["amount"] == "250.00"


def test_starting_balance_is_the_first_entrys_balance(
    client, db, customer, company
):
    # Dealer page pass (2026-11-06): the account read carries
    # where the account STARTED — the balance its first ledger
    # entry took it to — and later entries never move it.
    record = _private_record(db, customer, company)
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="250.00",
    )
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert Decimal(account["starting_balance"]) == Decimal("250.00")
    # Ledger order is (entry_date, created_at, id) and the
    # stamps carry second precision — date the later entries
    # after the opening entry's day so the order is the true
    # posting order, never a same-second coin flip.
    from datetime import date as _date, timedelta as _td

    assert _entry(
        client, customer, account["id"],
        kind="payment", amount="50.00",
        entry_date=(_date.today() + _td(days=7)).isoformat(),
    ).status_code == 201
    assert _entry(
        client, customer, account["id"],
        kind="charge", amount="100.00", note="Wrench set",
        entry_date=(_date.today() + _td(days=8)).isoformat(),
    ).status_code == 201
    after = client.get(
        "/api/truck-accounts/accounts",
        headers=auth_headers(customer),
    ).json()
    row = next(r for r in after if r["id"] == account["id"])
    assert Decimal(row["balance"]) == Decimal("300.00")
    assert Decimal(row["starting_balance"]) == Decimal("250.00")

    # An account opened empty starts at its first entry, and
    # one with no entries at all starts (and stands) at zero.
    record2 = _private_record(db, customer, company, name="Second")
    resp2 = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record2.id),
        opening_balance="0",
    )
    assert resp2.status_code == 201, resp2.text
    account2 = resp2.json()
    assert Decimal(account2["starting_balance"]) == Decimal("0")
    assert _entry(
        client, customer, account2["id"],
        kind="charge", amount="80.00", note="First tool",
    ).status_code == 201
    after2 = client.get(
        "/api/truck-accounts/accounts",
        headers=auth_headers(customer),
    ).json()
    row2 = next(r for r in after2 if r["id"] == account2["id"])
    assert Decimal(row2["starting_balance"]) == Decimal("80.00")


def test_open_self_on_connected_platform_agent_is_shared(
    client, db, customer, company, agent
):
    _connect(db, customer, company, agent_user_id=agent.id, preferred=True)
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        agent_user_id=str(agent.id),
        opening_balance="80.00",
        opening_note="What I owed Matt before the site",
    )
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["ledger_keeper"] == "customer"
    assert account["agent_kind"] == "platform"
    # The agent's seat sees the same tab (the two-seat view).
    agent_rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(agent)
    ).json()
    assert [r["id"] for r in agent_rows] == [account["id"]]
    assert agent_rows[0]["my_role"] == "dealer"
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(agent),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["entries"][0]["note"] == (
        "What I owed Matt before the site"
    )


def test_open_self_refusals(client, db, customer, company, agent):
    record = _private_record(db, customer, company)
    # An unconnected platform agent is not on the roster.
    resp = _open_self(
        client, customer,
        company_id=str(company.id), agent_user_id=str(agent.id),
    )
    assert resp.status_code == 422
    # Neither target / both targets.
    resp = _open_self(client, customer, company_id=str(company.id))
    assert resp.status_code == 422
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        agent_user_id=str(agent.id),
    )
    assert resp.status_code == 422
    # A record belonging to somebody else.
    other = _make_user(
        db, "TV-M-000972", "other@example.com", (MECHANIC,), name="Other"
    )
    foreign = _private_record(db, other, company, name="Not Yours")
    resp = _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(foreign.id),
    )
    assert resp.status_code == 422
    # Duplicate: one live tab per agent.
    resp = _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(record.id),
    )
    assert resp.status_code == 201, resp.text
    resp = _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(record.id),
    )
    assert resp.status_code == 422


def test_self_targets_and_companies(client, db, customer, company, agent):
    record = _private_record(db, customer, company)
    _connect(db, customer, company, agent_user_id=agent.id, preferred=True)
    companies = client.get(
        "/api/truck-accounts/accounts/self/companies",
        headers=auth_headers(customer),
    ).json()
    assert [c["company_id"] for c in companies] == [str(company.id)]
    targets = client.get(
        "/api/truck-accounts/accounts/self/targets",
        params={"company_id": str(company.id)},
        headers=auth_headers(customer),
    ).json()
    by_kind = {t["kind"]: t for t in targets}
    assert by_kind["platform"]["name"] == "Matt"
    assert by_kind["platform"]["is_preferred"] is True
    assert by_kind["private"]["name"] == "Austin"
    assert by_kind["private"]["has_open_account"] is False
    _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(record.id),
    )
    targets = client.get(
        "/api/truck-accounts/accounts/self/targets",
        params={"company_id": str(company.id)},
        headers=auth_headers(customer),
    ).json()
    by_kind = {t["kind"]: t for t in targets}
    assert by_kind["private"]["has_open_account"] is True


# -- every increase is explained ----------------------------------------------------


def test_manual_charge_needs_a_note(client, db, customer, company):
    record = _private_record(db, customer, company)
    account = _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(record.id),
    ).json()
    resp = _entry(
        client, customer, account["id"], kind="charge", amount="25.00", note=""
    )
    assert resp.status_code == 422, resp.text
    assert "explained" in resp.json()["detail"]
    resp = _entry(
        client, customer, account["id"],
        kind="charge", amount="25.00", note="Ratchet off the truck",
    )
    assert resp.status_code == 201, resp.text
    # A positive adjustment is an increase too.
    resp = _entry(
        client, customer, account["id"],
        kind="adjustment", amount="5.00", note="",
    )
    assert resp.status_code == 422
    # A payment needs no note; a negative adjustment neither.
    resp = _entry(
        client, customer, account["id"], kind="payment", amount="10.00", note=""
    )
    assert resp.status_code == 201
    resp = _entry(
        client, customer, account["id"],
        kind="adjustment", amount="-5.00", note="",
    )
    assert resp.status_code == 201


def test_tool_linked_charge_is_explained_by_the_tool(
    client, db, customer, company
):
    from app.modules.inventory import models as inv_models

    record = _private_record(db, customer, company)
    account = _open_self(
        client, customer,
        company_id=str(company.id), private_agent_id=str(record.id),
    ).json()
    tool = inv_models.Tool(
        id=uuid.uuid4(), owner_id=customer.id, name="Impact wrench"
    )
    db.add(tool)
    db.commit()
    resp = _entry(
        client, customer, account["id"],
        kind="charge", amount="199.00", note="",
        item_link_id=str(tool.id),
    )
    assert resp.status_code == 201, resp.text
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    entry = detail["entries"][0]
    assert entry["item_name"] == "Impact wrench"
    assert entry["item_kind"] == "tool"


# -- missed payments ------------------------------------------------------------------


def test_missed_payments_are_computed_and_shown(client, db, customer, company):
    record = _private_record(db, customer, company)
    due = date.today() - timedelta(days=15)
    account = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="300.00",
        payment_amount="50.00",
        next_due_date=due.isoformat(),
    ).json()
    # Weekly cadence, due 15 days ago: the due date itself plus
    # the cycles at -8 and -1 days are missed — 3 payments.
    assert account["missed_payments"] == 3
    assert Decimal(account["amount_past_due"]) == Decimal("150.00")
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    schedule = detail["schedule"]
    assert schedule["overdue"] is True
    assert schedule["missed_due_dates"] == [
        due.isoformat(),
        (due + timedelta(days=7)).isoformat(),
        (due + timedelta(days=14)).isoformat(),
    ]
    # A payment settles exactly one missed cycle (the due date
    # advances one cadence step from the standing due date —
    # settle-oldest, see _advance_due_after_payment).
    resp = _entry(
        client, customer, account["id"],
        kind="payment", amount="50.00", note="Cash at the truck",
    )
    assert resp.status_code == 201, resp.text
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    assert detail["schedule"]["missed_payments"] == 2


def test_missed_amount_caps_at_balance(client, db, customer, company):
    record = _private_record(db, customer, company)
    account = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="40.00",
        payment_amount="50.00",
        next_due_date=(date.today() - timedelta(days=30)).isoformat(),
    ).json()
    # 5 cycles missed × $50 would be $250 — the tab only owes $40.
    assert Decimal(account["amount_past_due"]) == Decimal("40.00")


# -- payment requests -------------------------------------------------------------------


def _shared_account(client, db, customer, company, agent, **over):
    _connect(db, customer, company, agent_user_id=agent.id, preferred=True)
    body = {
        "company_id": str(company.id),
        "agent_user_id": str(agent.id),
        "opening_balance": "200.00",
    }
    body.update(over)
    resp = _open_self(client, customer, **body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_payment_request_approve_records_the_payment(
    client, db, customer, company, agent
):
    account = _shared_account(client, db, customer, company, agent)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests",
        json={"amount": "50.00", "note": "Weekly payment"},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 201, resp.text
    request = resp.json()
    assert request["status"] == "pending"
    # The customer was told (inbox kind registered).
    assert _notifications(db, customer.id, "truck_payment_requested")
    # A second open request is refused.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests",
        json={"amount": "10.00"},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    # Approval posts the payment, marked as agent-requested.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests/"
        f"{request['id']}/approve",
        json={"note": ""},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    decided = resp.json()
    assert decided["status"] == "approved"
    assert decided["entry_id"]
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    payments = [e for e in detail["entries"] if e["kind"] == "payment"]
    assert len(payments) == 1
    assert payments[0]["source"] == "agent_request"
    assert payments[0]["amount"] == "-50.00"
    assert Decimal(detail["account"]["balance"]) == Decimal("150.00")
    assert _notifications(db, agent.id, "truck_payment_request_approved")


def test_payment_request_decline_writes_no_entry(
    client, db, customer, company, agent
):
    account = _shared_account(client, db, customer, company, agent)
    request = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests",
        json={"amount": "50.00"},
        headers=auth_headers(agent),
    ).json()
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests/"
        f"{request['id']}/decline",
        json={"note": "Paid cash already"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "declined"
    assert resp.json()["decision_note"] == "Paid cash already"
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    assert [e for e in detail["entries"] if e["kind"] == "payment"] == []
    assert Decimal(detail["account"]["balance"]) == Decimal("200.00")
    assert _notifications(db, agent.id, "truck_payment_request_declined")


def test_payment_request_refusals(client, db, customer, company, agent):
    account = _shared_account(client, db, customer, company, agent)
    # The customer can't request a payment from himself.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-requests",
        json={"amount": "10.00"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 404
    # On an AGENT-KEPT account there are no requests — the agent
    # holds the pen there. Build one through issuance.
    from tests.test_truck_account_agents import _accept, _create

    issued = _create(client, agent, customer)
    _accept(client, customer, issued["id"])
    resp = client.post(
        f"/api/truck-accounts/accounts/{issued['id']}/payment-requests",
        json={"amount": "10.00"},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422


def test_agent_records_payment_but_not_charge_on_customer_kept(
    client, db, customer, company, agent
):
    account = _shared_account(client, db, customer, company, agent)
    # Money the agent received: either party records a payment.
    resp = _entry(
        client, agent, account["id"],
        kind="payment", amount="25.00", note="Cash at the truck",
    )
    assert resp.status_code == 201, resp.text
    # Charges stay the keeper's pen on a customer-kept tab.
    resp = _entry(
        client, agent, account["id"],
        kind="charge", amount="25.00", note="Sneaky",
    )
    assert resp.status_code == 422


# -- payment mode ---------------------------------------------------------------------


def test_payment_mode_is_the_customers_stored_choice(
    client, db, customer, company, agent
):
    account = _shared_account(client, db, customer, company, agent)
    assert account["payment_mode"] == "manual"
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-mode",
        json={"payment_mode": "automatic"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_mode"] == "automatic"
    # The agent doesn't choose how the customer pays.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-mode",
        json={"payment_mode": "manual"},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 404
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/payment-mode",
        json={"payment_mode": "whenever"},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 422


# -- the wizard charge re-aim ------------------------------------------------------------


def test_wizard_charge_prefers_the_preferred_agents_tab(
    client, db, customer, company, agent
):
    """Two agents, two tabs: the wizard charge lands on the
    PREFERRED agent's tab — and when he has none, a fresh tab
    opens under him instead of charging the other agent's."""

    other = _make_user(
        db, "TV-D-000973", "rachel2@example.com", (DEALER,),
        name="Rachel Agent",
    )
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(), agent_user_id=other.id,
            company_id=company.id, verified=True,
        )
    )
    db.commit()
    _connect(db, customer, company, agent_user_id=other.id)
    _connect(db, customer, company, agent_user_id=agent.id, preferred=True)
    # Only the OTHER agent has a tab.
    other_tab = _open_self(
        client, customer,
        company_id=str(company.id), agent_user_id=str(other.id),
        opening_balance="10.00",
    ).json()

    ctx = service.wizard_context(db, customer, company.id)
    assert ctx["active_accounts"] == []
    assert ctx["new_account_agent_name"] == "Matt"

    resp = client.post(
        "/api/inventory",
        json={
            "name": "Wizard ratchet",
            "purchase_price": "90.00",
            "quantity": 1,
            "dealer_company_id": str(company.id),
            "truck_charge": {"amount": "90.00"},
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    tool_id = uuid.UUID(resp.json()["id"])
    accounts = service.accounts_for_user(db, customer.id)
    by_holder = {
        (a.dealer_user_id, a.private_agent_id): a for a in accounts
    }
    preferred_tab = by_holder[(agent.id, None)]
    assert service.balance_of(db, preferred_tab.id) == Decimal("90.00")
    entries = service.list_entries(db, preferred_tab)
    assert entries[0].item_link_id == tool_id
    # The other agent's tab is untouched.
    assert service.balance_of(db, uuid.UUID(other_tab["id"])) == Decimal("10.00")
    assert preferred_tab.ledger_keeper == "customer"


def test_wizard_charge_can_pick_the_other_preferred_agent(
    client, db, customer, company, agent
):
    """Multi-preferred (2026-11-05): TWO agents flagged for one
    dealer. The wizard context lists both (the earliest flagged
    is the default); a charge naming the OTHER agent auto-opens
    a tab under HIM and charges it, never the default's; a
    charge naming an agent who isn't on the roster is refused."""
    other = _make_user(
        db, "TV-D-000974", "rachel3@example.com", (DEALER,),
        name="Rachel Agent",
    )
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(), agent_user_id=other.id,
            company_id=company.id, verified=True,
        )
    )
    db.commit()
    first = _connect(db, customer, company, agent_user_id=agent.id, preferred=True)
    second = _connect(db, customer, company, agent_user_id=other.id, preferred=True)
    # Separate the stamps: earliest flagged = the default.
    from datetime import timedelta

    first.created_at -= timedelta(minutes=2)
    second.created_at -= timedelta(minutes=1)
    db.commit()

    ctx = service.wizard_context(db, customer, company.id)
    by_name = {a["name"]: a for a in ctx["agents"]}
    assert set(by_name) == {"Matt", "Rachel Agent"}
    assert by_name["Matt"]["is_default"] is True
    assert by_name["Matt"]["is_preferred"] is True
    assert by_name["Rachel Agent"]["is_preferred"] is True
    assert by_name["Rachel Agent"]["is_default"] is False
    assert by_name["Rachel Agent"]["active_accounts"] == []

    resp = client.post(
        "/api/inventory",
        json={
            "name": "Picked ratchet",
            "purchase_price": "45.00",
            "quantity": 1,
            "dealer_company_id": str(company.id),
            "truck_charge": {
                "amount": "45.00",
                "agent_user_id": str(other.id),
            },
        },
        headers=auth_headers(customer),
    )
    assert resp.status_code == 201, resp.text
    accounts = service.accounts_for_user(db, customer.id)
    by_holder = {(a.dealer_user_id, a.private_agent_id): a for a in accounts}
    assert (agent.id, None) not in by_holder  # the default got NO tab
    rachel_tab = by_holder[(other.id, None)]
    assert service.balance_of(db, rachel_tab.id) == Decimal("45.00")
    assert rachel_tab.ledger_keeper == "customer"

    refused = client.post(
        "/api/inventory",
        json={
            "name": "Stranger ratchet",
            "purchase_price": "10.00",
            "quantity": 1,
            "dealer_company_id": str(company.id),
            "truck_charge": {
                "amount": "10.00",
                "agent_user_id": str(uuid.uuid4()),
            },
        },
        headers=auth_headers(customer),
    )
    assert refused.status_code == 422, refused.text


# -- statements ---------------------------------------------------------------------------


def test_statement_renders_pdf_and_csv(client, db, customer, company):
    record = _private_record(db, customer, company)
    account = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="120.00",
    ).json()
    _entry(
        client, customer, account["id"],
        kind="payment", amount="20.00", note="Cash",
    )
    pdf = client.get(
        f"/api/truck-accounts/accounts/{account['id']}/statement?fmt=pdf",
        headers=auth_headers(customer),
    )
    assert pdf.status_code == 200, pdf.text[:200]
    assert pdf.content[:4] == b"%PDF"
    csv_resp = client.get(
        f"/api/truck-accounts/accounts/{account['id']}/statement?fmt=csv",
        headers=auth_headers(customer),
    )
    assert csv_resp.status_code == 200
    assert "Opening balance" in csv_resp.text
    assert "Balance owed" in csv_resp.text


def test_statement_markup_shape(client, db, customer, company):
    """Owner markup (2026-11-06): the statement's title lost
    its dealer suffix, the account summary line is gone, the
    header carries labeled DEALER / AGENT party blocks with
    real contact facts, the totals band is the navy
    presentation (balance parked right, bold white — the
    report standard that replaced the red accent), and the
    ledger renders as the wrapping DATE/TYPE/NAME/AMOUNT
    table."""
    from app.modules.reports.activity import render_activity_pdf

    customer.phone = "612-555-0100"
    customer.postal_address = "1 Main St\nLittle Falls, MN 56345"
    company.phones = [
        {"label": "Customer Service", "number": "(855) 555-0147"},
        {"label": "Sales", "number": "(855) 555-0199"},
    ]
    db.add(company)
    record = _private_record(db, customer, company)
    record.phone = "320-555-0119"
    record.email = "austin@matco.example"
    db.add(record)
    db.commit()

    account_json = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="120.00",
    ).json()
    _entry(
        client, customer, account_json["id"],
        kind="charge", amount="100.00",
        note="Fluke 87V multimeter with a very long descriptive "
        "name that must wrap in the ledger, never truncate",
    )
    account = service.accounts_for_user(db, customer.id)[0]
    report = service.statement_report(db, account, customer)

    assert report["title"] == "Truck account statement"
    assert report["subtitle"] == ""
    assert report["prepared_for"]["phone"] == "612-555-0100"
    assert report["prepared_for"]["email"] == "chris2@example.com"
    assert report["parties"]["dealer"] == {
        "name": "Matco Tools",
        "phone": "(855) 555-0147",
    }
    assert report["parties"]["agent"] == {
        "name": "Austin",
        "phone": "320-555-0119",
        "email": "austin@matco.example",
    }
    assert report["totals_band"] == "navy"
    assert report["ledger_table"] is True
    assert report["section_band"] is False
    balance = [t for t in report["totals"] if t["label"] == "Balance owed"]
    assert balance[0]["park"] == "right"
    # No total anywhere carries the retired red accent —
    # red on the band was rejected as unreadable (2026-11-06;
    # the band was teal then, navy since Ryan's call that
    # evening).
    assert all("accent" not in t for t in report["totals"])
    # The ledger row's NAME keeps the whole detail — wrapping
    # is the renderer's job, the dataset never truncates.
    details = [row["detail"] for row in report["sections"][0]["rows"]]
    assert any("never truncate" in d for d in details)

    pdf = render_activity_pdf(report, "en")
    assert pdf[:4] == b"%PDF"
    # The sibling dealer-accounts document shares the ledger
    # presentation but keeps its per-account section bands.
    from app.modules.reports.activity import build_dealer_accounts

    sibling = build_dealer_accounts(db, customer)
    assert sibling["ledger_table"] is True
    assert sibling["totals_band"] == "navy"
    assert sibling["totals"][0]["park"] == "right"
    assert all("accent" not in t for t in sibling["totals"])
    assert sibling.get("section_band") is not False
    assert render_activity_pdf(sibling, "en")[:4] == b"%PDF"


def test_statement_name_rule_and_balance_column(client, db, customer, company):
    """The name rule + the BALANCE column (Ryan, 2026-11-06
    22:25/22:34): a report row's NAME is the clean name only —
    a wizard charge's "Tool entered: …" note never echoes next
    to its item's name, and no "balance $X" annotation rides
    the name; the running balance is each row's own "balance"
    field and the last row's ties to the banner's BALANCE OWED.
    The Dealer accounts sibling keeps the same names and reads
    its balances in LEDGER order (a same-date payment posted
    before a charge keeps its place — an alphabetical re-sort
    would step the balances differently)."""
    from app.modules.inventory import models as inv_models
    from app.modules.reports.activity import build_dealer_accounts

    record = _private_record(db, customer, company)
    account_json = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="0",
    ).json()
    tool = inv_models.Tool(
        id=uuid.uuid4(), owner_id=customer.id, name="Hex Bit Ratchet"
    )
    db.add(tool)
    db.commit()
    account = service.accounts_for_user(db, customer.id)[0]
    # Ledger rows written directly, all on ONE date with
    # explicit recorded stamps: list_entries orders by (date,
    # recorded, id), and the API's second-precision stamps
    # would leave same-second rows to the id tiebreak — the
    # recorded order below is the ledger order under test.
    day = date.today()
    base = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    specs = [
        ("charge", "100.00", "Opening balance", None, 0),
        ("payment", "-40.00", "Cash", None, 1),
        ("charge", "75.00", "Tool entered: Hex Bit Ratchet", tool.id, 2),
        ("charge", "25.00", "Shop supplies", None, 3),
    ]
    for kind, amount, note, link, minutes in specs:
        db.add(
            truck_models.TruckEntry(
                id=uuid.uuid4(),
                account_id=account.id,
                kind=kind,
                amount=Decimal(amount),
                note=note,
                item_link_id=link,
                entry_date=day,
                source="manual",
                recorded_by=customer.id,
                created_at=base + timedelta(minutes=minutes),
            )
        )
    db.commit()
    report = service.statement_report(db, account, customer)
    rows = report["sections"][0]["rows"]
    # Names: opening note, the payment's own note, the ITEM's
    # name alone for the wizard charge, the keeper's note.
    assert [r["detail"] for r in rows] == [
        "Opening balance",
        "Cash",
        "Hex Bit Ratchet",
        "Shop supplies",
    ]
    assert all("entered:" not in r["detail"] for r in rows)
    # Balances step down the ledger in recorded order, and the
    # last one IS the balance owed the banner parks.
    assert [r["balance"] for r in rows] == [
        "100.00", "60.00", "135.00", "160.00",
    ]
    owed = [t for t in report["totals"] if t["label"] == "Balance owed"]
    assert owed[0]["amount"] == rows[-1]["balance"] == "160.00"

    sibling = build_dealer_accounts(db, customer)
    srows = sibling["sections"][0]["rows"]
    assert [r["detail"] for r in srows] == [r["detail"] for r in rows]
    assert [r["balance"] for r in srows] == [r["balance"] for r in rows]
    assert sibling["sections"][0]["total"] == "160.00"


def test_roster_slot_carries_schedule_facts(client, db, customer, company):
    """The agent record's truck slot (dealers module) reads the
    same missed state — the response schema must carry the
    fields, not strip them."""
    record = _private_record(db, customer, company)
    due = date.today() - timedelta(days=8)
    _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="100.00",
        payment_amount="50.00",
        next_due_date=due.isoformat(),
    )
    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster/agent",
        params={"kind": "private", "ref_id": str(record.id)},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    slot = resp.json()["truck_accounts"]
    assert len(slot) == 1
    assert slot[0]["next_due_date"] == due.isoformat()
    assert slot[0]["missed_payments"] == 2
    assert slot[0]["amount_past_due"] == "100.00"


# -- unlink keeps the customer's tab -------------------------------------------------------


def test_takeover_link_then_unlink_keeps_account_with_customer(
    client, db, customer, company, agent
):
    """Stage 1 semantics under stage 2: the record is claimed
    (the account gains the agent's seat), then the link is
    severed — the self-kept account stays the customer's, data
    untouched."""
    record = _private_record(db, customer, company)
    account = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="60.00",
    ).json()
    # Claim the record the way the takeover seam leaves it.
    record.linked_user_id = agent.id
    record.link_source = "takeover"
    db.commit()
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(agent),
    )
    assert detail.status_code == 200
    assert detail.json()["account"]["my_role"] == "dealer"
    # Sever the link: the agent's seat is gone, the customer's
    # tab stands exactly as it was.
    record.linked_user_id = None
    record.link_source = None
    db.commit()
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(agent),
    )
    assert detail.status_code == 404
    mine = client.get(
        f"/api/truck-accounts/accounts/{account['id']}",
        headers=auth_headers(customer),
    ).json()
    assert Decimal(mine["account"]["balance"]) == Decimal("60.00")

