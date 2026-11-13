"""Truck Accounts — the HIGHEST CREDIT LIMIT (owner's label +
rule, 2026-11-05; build, 2026-11-06, migration 0080).

The highest balance an account has ever stood at: stored,
system-maintained, NEVER decreases, nobody edits it, both
seats see it. The owner's worked example is the arc test:
open at $100 → highest $100; the balance hits $3,100 →
highest $3,100; pay it down → highest STAYS $3,100. Because
the value is stored (never recomputed from the ledger), a
later backdated correction cannot rewrite it either — the
backdated-adjustment test pins exactly that.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest

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
        db, "TV-D-000977", "matt7@example.com", (DEALER,), name="Matt Agent"
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
        db, "TV-M-000977", "chris7@example.com", (MECHANIC,),
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


def _detail(client, user, account_id):
    resp = client.get(
        f"/api/truck-accounts/accounts/{account_id}",
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["account"]


def _money(value) -> Decimal:
    return Decimal(str(value))


# -- the owner's worked example, through the real API -----------------------------


def test_self_kept_arc_highest_credit_limit(client, db, customer, company):
    record = _private_record(db, customer, company)
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="100.00",
    )
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["id"]

    # Open at $100 → the highest credit limit is $100.
    view = _detail(client, customer, account_id)
    assert _money(view["balance"]) == Decimal("100.00")
    assert _money(view["highest_balance"]) == Decimal("100.00")

    # The balance hits $3,100 → the highest follows it up.
    resp = _entry(
        client, customer, account_id,
        kind="charge", amount="3000.00", note="Tool chest",
    )
    assert resp.status_code == 201, resp.text
    view = _detail(client, customer, account_id)
    assert _money(view["balance"]) == Decimal("3100.00")
    assert _money(view["highest_balance"]) == Decimal("3100.00")

    # Pay it down → the highest STAYS $3,100.
    resp = _entry(client, customer, account_id, kind="payment", amount="2000.00")
    assert resp.status_code == 201, resp.text
    view = _detail(client, customer, account_id)
    assert _money(view["balance"]) == Decimal("1100.00")
    assert _money(view["highest_balance"]) == Decimal("3100.00")

    # And the stored column itself agrees (not a read-time trick).
    stored = db.get(truck_models.TruckAccount, uuid.UUID(account_id))
    assert stored.highest_balance == Decimal("3100.00")


def test_peak_never_decreases_on_backdated_correction(
    client, db, customer, company
):
    """A backdated negative adjustment rewrites the ledger's
    own running history (in canonical order it lands FIRST) —
    a computed peak would drop; the stored peak must not."""
    from datetime import date, timedelta

    record = _private_record(db, customer, company)
    resp = _open_self(
        client, customer,
        company_id=str(company.id),
        private_agent_id=str(record.id),
        opening_balance="100.00",
    )
    account_id = resp.json()["id"]
    _entry(client, customer, account_id,
           kind="charge", amount="3000.00", note="Tool chest")
    assert _money(_detail(client, customer, account_id)["highest_balance"]) \
        == Decimal("3100.00")

    backdated = (date.today() - timedelta(days=30)).isoformat()
    resp = _entry(
        client, customer, account_id,
        kind="adjustment", amount="-2900.00",
        note="Correction booked back", entry_date=backdated,
    )
    assert resp.status_code == 201, resp.text
    view = _detail(client, customer, account_id)
    assert _money(view["balance"]) == Decimal("200.00")
    assert _money(view["highest_balance"]) == Decimal("3100.00")


# -- the agent-issued seat: both parties read the same peak ------------------------


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


def test_agent_issued_peak_both_seats(client, db, agent, customer):
    resp = client.post(
        "/api/truck-accounts/accounts",
        json={
            "customer_account_number": "TV-M-000977",
            "customer_email": "",
            "payment_cadence": "weekly",
            "payment_amount": "50.00",
            "next_due_date": None,
        },
        headers=auth_headers(agent),
    )
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["id"]

    # A fresh invite stands at zero — and so does its highest.
    view = _detail(client, agent, account_id)
    assert _money(view["highest_balance"]) == Decimal("0")

    _accept(client, customer, account_id)
    resp = _entry(client, agent, account_id,
                  kind="charge", amount="500.00", note="Impact wrench")
    assert resp.status_code == 201, resp.text

    for seat in (agent, customer):
        view = _detail(client, seat, account_id)
        assert _money(view["balance"]) == Decimal("500.00")
        assert _money(view["highest_balance"]) == Decimal("500.00")

    # Paid off in full: balance zero, the highest stays — from
    # BOTH seats.
    resp = _entry(client, customer, account_id,
                  kind="payment", amount="500.00")
    assert resp.status_code == 201, resp.text
    for seat in (agent, customer):
        view = _detail(client, seat, account_id)
        assert _money(view["balance"]) == Decimal("0")
        assert _money(view["highest_balance"]) == Decimal("500.00")


# -- every write path maintains it ---------------------------------------------------


def test_wizard_charge_raises_peak(db, customer, company):
    record = _private_record(db, customer, company)
    db.add(
        dealer_models.PreferredAgent(
            id=uuid.uuid4(),
            user_id=customer.id,
            company_id=company.id,
            agent_user_id=None,
            private_agent_id=record.id,
            is_preferred=True,
        )
    )
    db.commit()
    entry = service.charge_at_item_entry(
        db, customer,
        company_id=company.id,
        amount=Decimal("250.00"),
        note="DeWalt impact",
        item_link_id=uuid.uuid4(),
    )
    db.commit()
    account = db.get(truck_models.TruckAccount, entry.account_id)
    assert service.balance_of(db, account.id) == Decimal("250.00")
    assert account.highest_balance == Decimal("250.00")


def test_peak_is_not_a_form_field(client, db, agent, customer):
    """No create surface accepts the figure: a body carrying
    one is ignored — the account still starts at zero."""
    resp = client.post(
        "/api/truck-accounts/accounts",
        json={
            "customer_account_number": "TV-M-000977",
            "customer_email": "",
            "payment_cadence": "weekly",
            "payment_amount": "50.00",
            "next_due_date": None,
            "highest_balance": "9999.00",
        },
        headers=auth_headers(agent),
    )
    assert resp.status_code == 201, resp.text
    view = _detail(client, agent, resp.json()["id"])
    assert _money(view["highest_balance"]) == Decimal("0")


# -- Order A's backend fact: who can issue at all -------------------------------------


def test_issuable_companies_empty_for_plain_mechanic(client, customer):
    resp = client.get(
        "/api/truck-accounts/issuable-companies",
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
