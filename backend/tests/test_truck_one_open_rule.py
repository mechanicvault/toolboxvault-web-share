"""Sheet row 63 (owner rule, 2026-11-17): the one-open-account
rule + the system account number.

- Every truck account is born with a system account number
  ("TV-T-000123") — unique, increasing, kept for life.
- A customer + agent pair (under a company) holds ONE live
  tab: a second open is refused, whichever door it tries —
  dealer issue, customer self-open, or invite acceptance.
- When the pair's only account is CLOSED, an open stops with
  a 409 (closed_account_exists) so the user can be asked:
  reopen the old account, or open a new one? Reopening keeps
  the same account and the same number; choosing "new" (the
  allow_new_over_closed answer) opens a fresh account with a
  fresh number while the closed one stays closed.
- Reopening notifies the other seat.
"""

from __future__ import annotations

import re
import uuid

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
    user = _make_user(
        db, "TV-D-000981", "matt3@example.com", (DEALER,), name="Matt Agent"
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
        db, "TV-M-000981", "chris3@example.com", (MECHANIC,),
        name="Chris Customer",
    )


def _connect(db, customer, company, *, agent_user_id):
    row = dealer_models.PreferredAgent(
        id=uuid.uuid4(),
        user_id=customer.id,
        company_id=company.id,
        agent_user_id=agent_user_id,
        private_agent_id=None,
        is_preferred=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _issue(client, agent, customer, **over):
    body = {
        "customer_account_number": customer.account_number,
        "customer_email": "",
        "payment_cadence": "weekly",
        "payment_amount": "50.00",
        "next_due_date": None,
    }
    body.update(over)
    return client.post(
        "/api/truck-accounts/accounts", json=body, headers=auth_headers(agent)
    )


def _open_self(client, customer, company, agent, **over):
    body = {
        "company_id": str(company.id),
        "private_agent_id": None,
        "agent_user_id": str(agent.id),
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


def _accept(client, customer, account_id):
    detail = client.get(
        f"/api/truck-accounts/accounts/{account_id}",
        headers=auth_headers(customer),
    ).json()
    version = re.search(
        r"version ([0-9A-Za-z.-]+)\)", detail["agreement_preview"]
    ).group(1)
    return client.post(
        f"/api/truck-accounts/accounts/{account_id}/accept",
        json={"agreement_version": version},
        headers=auth_headers(customer),
    )


def _close(client, user, account_id):
    return client.post(
        f"/api/truck-accounts/accounts/{account_id}/close",
        headers=auth_headers(user),
    )


# -- the system number -------------------------------------------------------


def test_accounts_are_born_with_system_numbers(client, db, agent, customer):
    first = _issue(client, agent, customer)
    assert first.status_code == 201, first.text
    assert first.json()["account_number"] == "TV-T-000001"
    _accept(client, customer, first.json()["id"])
    _close(client, customer, first.json()["id"])
    second = _issue(client, agent, customer, allow_new_over_closed=True)
    assert second.status_code == 201, second.text
    # A fresh account reports just like a new truck account —
    # new number, and the numbers never repeat.
    assert second.json()["account_number"] == "TV-T-000002"


# -- the one-open rule -------------------------------------------------------


def test_dealer_cannot_issue_a_second_live_account(
    client, db, agent, customer
):
    assert _issue(client, agent, customer).status_code == 201
    again = _issue(client, agent, customer)
    assert again.status_code == 422
    assert "already has a truck account" in again.json()["detail"]


def test_self_open_refused_while_an_issued_account_is_live(
    client, db, agent, customer, company
):
    _connect(db, customer, company, agent_user_id=agent.id)
    assert _issue(client, agent, customer).status_code == 201
    refused = _open_self(client, customer, company, agent)
    assert refused.status_code == 422
    assert "your tab with them" in refused.json()["detail"]


def test_accept_refused_when_another_live_account_serves_the_pair(
    client, db, agent, customer, company
):
    _connect(db, customer, company, agent_user_id=agent.id)
    # The invite is issued by EMAIL — no customer is resolved at
    # issue time, so no pair check can run there.
    invited = _issue(
        client, agent, customer,
        customer_account_number="", customer_email=customer.email,
    )
    assert invited.status_code == 201, invited.text
    # The customer opens his own shared tab with the agent first.
    opened = _open_self(client, customer, company, agent)
    assert opened.status_code == 201, opened.text
    # Listing attaches the pending invite to his account.
    listed = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(customer)
    )
    assert listed.status_code == 200
    refused = _accept(client, customer, invited.json()["id"])
    assert refused.status_code == 422
    assert "your tab with them" in refused.json()["detail"]


# -- closed: the reopen-or-new question --------------------------------------


def test_closed_account_stops_the_open_with_a_409(
    client, db, agent, customer
):
    issued = _issue(client, agent, customer)
    account_id = issued.json()["id"]
    _accept(client, customer, account_id)
    assert _close(client, customer, account_id).status_code == 200
    stopped = _issue(client, agent, customer)
    assert stopped.status_code == 409, stopped.text
    detail = stopped.json()["detail"]
    assert detail["code"] == "closed_account_exists"
    assert detail["account_id"] == account_id
    assert detail["account_number"] == "TV-T-000001"


def test_reopen_keeps_the_account_and_its_number(
    client, db, agent, customer
):
    issued = _issue(client, agent, customer)
    account_id = issued.json()["id"]
    _accept(client, customer, account_id)
    _close(client, customer, account_id)
    reopened = client.post(
        f"/api/truck-accounts/accounts/{account_id}/reopen",
        headers=auth_headers(agent),
    )
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body["status"] == "active"
    assert body["account_number"] == "TV-T-000001"
    # The other seat heard about it.
    notes = list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == customer.id,
                core_models.Notification.kind == "truck_account_reopened",
            )
        )
    )
    assert len(notes) == 1
    # And the pair is live again: a fresh open is refused.
    assert _issue(client, agent, customer).status_code == 422


def test_self_open_over_closed_asks_then_opens_new(
    client, db, agent, customer, company
):
    _connect(db, customer, company, agent_user_id=agent.id)
    opened = _open_self(client, customer, company, agent)
    assert opened.status_code == 201, opened.text
    account_id = opened.json()["id"]
    assert _close(client, customer, account_id).status_code == 200
    stopped = _open_self(client, customer, company, agent)
    assert stopped.status_code == 409, stopped.text
    assert stopped.json()["detail"]["account_id"] == account_id
    fresh = _open_self(
        client, customer, company, agent, allow_new_over_closed=True
    )
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["id"] != account_id
    assert fresh.json()["account_number"] == "TV-T-000002"
    # The old account stays closed, on record.
    old = db.get(truck_models.TruckAccount, uuid.UUID(account_id))
    assert old.status == "closed"


def test_reopen_refusals(client, db, agent, customer):
    issued = _issue(client, agent, customer)
    account_id = issued.json()["id"]
    # Not closed yet.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account_id}/reopen",
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    # A stranger holds no role on the account.
    stranger = _make_user(
        db, "TV-M-000982", "stranger@example.com", (MECHANIC,),
        name="Sam Stranger",
    )
    _accept(client, customer, account_id)
    _close(client, customer, account_id)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account_id}/reopen",
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404


# -- migration 0108 ------------------------------------------------------------


def test_migration_0108_backfills_numbers_oldest_first():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0108_truck_account_number.py"
    )
    spec = importlib.util.spec_from_file_location("m0108", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0107_print_file_is_public"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE truck_accounts ("
                " id VARCHAR(36) PRIMARY KEY, created_at DATETIME)"
            )
        )
        # Inserted newest-first on purpose: the backfill order
        # is (created_at, id), not insertion order.
        conn.execute(
            sa.text(
                "INSERT INTO truck_accounts (id, created_at)"
                " VALUES ('b-id', '2026-02-01 00:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO truck_accounts (id, created_at)"
                " VALUES ('a-id', '2026-01-01 00:00:00')"
            )
        )

    def run(fn):
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                fn()

    run(module.upgrade)
    inspector = sa.inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("truck_accounts")}
    assert "account_number" in columns
    assert columns["account_number"]["nullable"] is False
    indexes = {ix["name"] for ix in inspector.get_indexes("truck_accounts")}
    assert "ix_truck_accounts_account_number" in indexes
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT id, account_number FROM truck_accounts"
                " ORDER BY account_number"
            )
        ).all()
    assert rows == [("a-id", "TV-T-000001"), ("b-id", "TV-T-000002")]

    run(module.downgrade)
    inspector = sa.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("truck_accounts")}
    assert "account_number" not in columns
