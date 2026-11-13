"""Truck Accounts (Wave 2, 2026-10-20): invite by number +
email, agreement-gated acceptance, the signed ledger with
both-party notifications, schedule + reminders, close freeze,
the DARK Connect seam, dealer dashboard numbers, deletion
tombstones, export shape."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.core import models as core_models
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
def dealer(db):
    user = _make_user(db, "TV-D-000901", "truckdealer@example.com", (DEALER,), name="Dana Dealer")
    _verify_rep(db, user)
    return user


def _verify_rep(db, user, company_name="Matco Tools"):
    """Give a dealer user a directory company + a VERIFIED
    representation for it — the 2026-10-31 issuance rule: an
    agent opens truck accounts only under a company they
    verified-represent."""
    from app.modules.dealers import models as dealer_models

    company = dealer_models.DealerCompany(
        id=uuid.uuid4(), name=company_name, is_directory=True
    )
    db.add(company)
    db.flush()
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(),
            agent_user_id=user.id,
            company_id=company.id,
            verified=True,
        )
    )
    db.commit()
    return company


@pytest.fixture()
def customer(db):
    return _make_user(db, "TV-M-000901", "truckcust@example.com", (MECHANIC,), name="Chris Customer")


def _create(client, dealer, **over):
    body = {
        "customer_account_number": "TV-M-000901",
        "customer_email": "",
        "payment_cadence": "weekly",
        "payment_amount": "10.00",
        "next_due_date": None,
    }
    body.update(over)
    resp = client.post("/api/truck-accounts/accounts", json=body, headers=auth_headers(dealer))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _notifications(db, user_id, kind=None):
    rows = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == user_id)
        .all()
    )
    if kind:
        rows = [r for r in rows if r.kind == kind]
    return rows


def _accept(client, customer, account_id):
    detail = client.get(
        f"/api/truck-accounts/accounts/{account_id}", headers=auth_headers(customer)
    ).json()
    preview = detail["agreement_preview"]
    assert preview
    import re

    version = re.search(r"version ([0-9A-Za-z.-]+)\)", preview).group(1)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account_id}/accept",
        json={"agreement_version": version},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _active_account(client, dealer, customer):
    account = _create(client, dealer)
    _accept(client, customer, account["id"])
    return account


def _entry(client, user, account_id, **over):
    body = {"kind": "payment", "amount": "10.00", "note": "", "item_link_id": None, "entry_date": None}
    body.update(over)
    return client.post(
        f"/api/truck-accounts/accounts/{account_id}/entries",
        json=body,
        headers=auth_headers(user),
    )


def test_create_by_account_number_and_invite_notification(client, db, dealer, customer):
    account = _create(client, dealer)
    assert account["status"] == "invited"
    assert account["customer_user_id"] == str(customer.id)
    assert account["my_role"] == "dealer"
    notes = _notifications(db, customer.id, "truck_invite_received")
    assert len(notes) == 1
    # Unknown numbers are refused without an oracle leak.
    resp = client.post(
        "/api/truck-accounts/accounts",
        json={"customer_account_number": "TV-M-999999", "customer_email": ""},
        headers=auth_headers(dealer),
    )
    assert resp.status_code == 422


def test_email_invite_attaches_at_read(client, db, dealer):
    account = _create(
        client, dealer, customer_account_number="", customer_email="newbie@example.com"
    )
    assert account["customer_user_id"] is None
    newbie = _make_user(db, "TV-M-000902", "newbie@example.com", (MECHANIC,), name="New Bie")
    rows = client.get("/api/truck-accounts/accounts", headers=auth_headers(newbie)).json()
    assert len(rows) == 1
    assert rows[0]["my_role"] == "customer"
    assert rows[0]["customer_user_id"] == str(newbie.id)


def test_accept_requires_current_version_and_snapshots(client, db, dealer, customer):
    account = _create(client, dealer)
    bad = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/accept",
        json={"agreement_version": "1999-01-01.0"},
        headers=auth_headers(customer),
    )
    assert bad.status_code == 422
    accepted = _accept(client, customer, account["id"])
    assert accepted["status"] == "active"
    assert accepted["agreement_version"]
    assert accepted["agreement_accepted_at"]
    from app.modules.truck_accounts import models as truck_models

    row = db.get(truck_models.TruckAccount, uuid.UUID(account["id"]))
    assert row.agreement_text_snapshot and "TRUCK ACCOUNT AGREEMENT" in row.agreement_text_snapshot
    assert len(_notifications(db, dealer.id, "truck_account_accepted")) == 1


def test_decline_closes(client, db, dealer, customer):
    account = _create(client, dealer)
    resp = client.post(
        f"/api/truck-accounts/accounts/{account['id']}/decline",
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert len(_notifications(db, dealer.id, "truck_account_declined")) == 1


def test_entries_rules_balance_and_notifications(client, db, dealer, customer):
    account = _active_account(client, dealer, customer)
    aid = account["id"]
    # Entries on an active account: dealer charges.
    charge = _entry(client, dealer, aid, kind="charge", amount="100.00", note="Impact wrench")
    assert charge.status_code == 201, charge.text
    assert charge.json()["amount"] == "100.00"
    # The customer cannot charge their own account.
    assert _entry(client, customer, aid, kind="charge", amount="5.00").status_code == 422
    # Customer records a payment; balance drops; BOTH notified.
    payment = _entry(client, customer, aid, kind="payment", amount="10.00", note="Cash")
    assert payment.status_code == 201
    assert payment.json()["amount"] == "-10.00"
    detail = client.get(f"/api/truck-accounts/accounts/{aid}", headers=auth_headers(dealer)).json()
    assert detail["account"]["balance"] == "90.00"
    assert len(_notifications(db, customer.id, "truck_charge")) >= 1
    assert len(_notifications(db, dealer.id, "truck_payment")) >= 1
    assert len(_notifications(db, customer.id, "truck_payment")) >= 1
    # Payment advances the due date by the cadence.
    assert detail["account"]["next_due_date"] is not None
    before = date.fromisoformat(detail["account"]["next_due_date"])
    _entry(client, dealer, aid, kind="payment", amount="10.00")
    after = client.get(
        f"/api/truck-accounts/accounts/{aid}", headers=auth_headers(dealer)
    ).json()["account"]["next_due_date"]
    assert date.fromisoformat(after) == before + timedelta(days=7)


def test_entries_refused_on_invited_and_closed(client, dealer, customer):
    account = _create(client, dealer)
    assert _entry(client, dealer, account["id"], kind="charge", amount="5.00").status_code == 422
    _accept(client, customer, account["id"])
    client.post(
        f"/api/truck-accounts/accounts/{account['id']}/close", headers=auth_headers(dealer)
    )
    assert _entry(client, dealer, account["id"], kind="charge", amount="5.00").status_code == 422


def test_balance_is_sum_of_ledger(client, db, dealer, customer):
    from app.modules.truck_accounts import service

    account = _active_account(client, dealer, customer)
    aid = uuid.UUID(account["id"])
    _entry(client, dealer, aid, kind="charge", amount="33.33", note="Wrench set")
    _entry(client, dealer, aid, kind="adjustment", amount="-3.33")
    _entry(client, customer, aid, kind="payment", amount="10.00")
    acct = service.get_account(db, dealer.id, aid)
    assert acct is not None
    assert str(service.balance_of(db, aid)) == "20.00"


def test_reminders_idempotent(client, db, dealer, customer):
    from app.modules.truck_accounts import service

    account = _active_account(client, dealer, customer)
    # A balance must be owed for reminders to arm.
    _entry(client, dealer, account["id"], kind="charge", amount="50.00", note="Socket set")
    # Due in 2 days → due-soon to the customer only.
    soon = date.today() + timedelta(days=2)
    client.post(
        f"/api/truck-accounts/accounts/{account['id']}/schedule",
        json={"next_due_date": soon.isoformat()},
        headers=auth_headers(dealer),
    )
    summary1 = service.run_due_reminders(db)
    assert summary1["due_soon"] == 1
    assert len(_notifications(db, customer.id, "truck_payment_due")) == 1
    summary2 = service.run_due_reminders(db)
    assert summary2["due_soon"] == 0  # idempotent within the window
    # Overdue → both sides.
    past = date.today() - timedelta(days=1)
    client.post(
        f"/api/truck-accounts/accounts/{account['id']}/schedule",
        json={"next_due_date": past.isoformat()},
        headers=auth_headers(dealer),
    )
    service.run_due_reminders(db)
    assert len(_notifications(db, customer.id, "truck_payment_overdue")) == 1
    assert len(_notifications(db, dealer.id, "truck_payment_overdue")) == 1


def test_dark_connect_endpoints_503(client, dealer, customer):
    account = _active_account(client, dealer, customer)
    for path, user in (
        ("/api/truck-accounts/connect/onboarding-link", dealer),
        ("/api/truck-accounts/connect/payouts", dealer),
        (f"/api/truck-accounts/accounts/{account['id']}/pay-online", customer),
    ):
        resp = client.post(path, headers=auth_headers(user)) if "payouts" not in path else client.get(path, headers=auth_headers(user))
        assert resp.status_code == 503, (path, resp.text)
        assert resp.json()["detail"]["code"] == "payments_not_configured"
    # And the account payload never offers Pay online in the dark.
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}", headers=auth_headers(customer)
    ).json()
    assert detail["account"]["pay_online_available"] is False


def test_dealer_dashboard_numbers(client, dealer, customer):
    _active_account(client, dealer, customer)
    account2 = _create(
        client, dealer, customer_account_number="", customer_email="second@example.com"
    )
    dash = client.get("/api/truck-accounts/dealer/dashboard", headers=auth_headers(dealer)).json()
    assert dash["open_accounts"] == 2
    assert "total_outstanding" in dash


def test_export_contains_truck_accounts(client, dealer, customer):
    import io
    import json as jsonlib
    import zipfile

    _active_account(client, dealer, customer)
    resp = client.get("/api/core/export", headers=auth_headers(customer))
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "truck_accounts.json" in archive.namelist()
    rows = jsonlib.loads(archive.read("truck_accounts.json"))
    assert rows and rows[0]["my_role"] == "customer"


def test_customer_deletion_tombstones_but_keeps_ledger(client, db, dealer, customer):
    from app.modules.core import service as core_service

    account = _active_account(client, dealer, customer)
    _entry(client, dealer, account["id"], kind="charge", amount="42.00", note="Ratchet")
    core_service.delete_account(db, customer)
    rows = client.get("/api/truck-accounts/accounts", headers=auth_headers(dealer)).json()
    assert len(rows) == 1
    assert rows[0]["status"] == "closed"
    detail = client.get(
        f"/api/truck-accounts/accounts/{account['id']}", headers=auth_headers(dealer)
    ).json()
    assert detail["account"]["balance"] == "42.00"
    assert len(detail["entries"]) == 1
