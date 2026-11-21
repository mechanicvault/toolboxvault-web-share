"""Audit A13 + A14 (2026-10-22): the dedicated reports round.

Sales, dealer accounts (truck ledger), checked-out, lost/
stolen, warranty claims as first-class activity kinds (screen
+ CSV + PDF + the shared activity email), and the Tax /
Section 179 worksheet — purchases by placed-in-service year
split on the business-use flag, disposals, and the standing
"not tax advice" label.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.modules.borrowing import models as borrowing_models
from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from app.modules.reports import activity
from app.modules.truck_accounts import models as truck_models

from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, number, email, types=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=number,
        email=email,
        name="Kind Reporter",
        password_hash="x",
        account_types=types or [MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000701", "a13-owner@example.com")


def _tool(db, owner, **kw):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=kw.pop("name", "Wrench"),
        model="",
        serial_number="",
        **kw,
    )
    db.add(tool)
    db.flush()
    return tool


def test_sales_report_nets_reversals(db, owner):
    wrench = _tool(db, owner)
    db.add_all(
        [
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                item_name="Wrench", quantity_sold=1,
                sale_price=Decimal("300"), sold_on=date(2026, 4, 2),
                kind="sale", source="manual",
            ),
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                item_name="Wrench", quantity_sold=1,
                sale_price=Decimal("300"), sold_on=date(2026, 4, 3),
                kind="reversal", source="manual",
            ),
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                item_name="Wrench", quantity_sold=2, buyer_name="Pat",
                sale_price=Decimal("150"), sold_on=date(2025, 1, 1),
                kind="sale", source="manual",
            ),
        ]
    )
    db.commit()
    report = activity.build_sales(db, owner)
    assert report["kind"] == "sales"
    assert report["totals"][0]["amount"] == "150.00"  # 300 - 300 + 150
    period = activity.build_sales(db, owner, start=date(2026, 1, 1))
    assert period["totals"][0]["amount"] == "0.00"


def test_lost_stolen_splits_recovered(db, owner):
    # Amounts are PURCHASE cost (owner ruling 2026-11-06): the
    # replacement costs on these records (300 / 120) never price
    # a lost/stolen figure.
    wrench = _tool(
        db, owner, purchase_price=Decimal("200"), replacement_cost=Decimal("300")
    )
    saw = _tool(
        db, owner, name="Saw",
        purchase_price=Decimal("90"), replacement_cost=Decimal("120"),
    )
    db.add_all(
        [
            inventory_models.ItemLossReport(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                standing="stolen", reported_date=date(2026, 2, 1),
                police_report_number="PR-9",
            ),
            inventory_models.ItemLossReport(
                owner_id=owner.id, item_kind="tool", item_id=saw.id,
                standing="lost", reported_date=date(2026, 3, 1),
                recovered_date=date(2026, 3, 20),
            ),
        ]
    )
    db.commit()
    report = activity.build_lost_stolen(db, owner)
    sections = {s["key"]: s for s in report["sections"]}
    assert sections["still_out"]["count"] == 1
    assert sections["recovered"]["count"] == 1
    assert report["totals"][0]["amount"] == "200.00"  # still out only, purchase cost
    assert report["totals"][0]["label"] == "Purchase cost still out"
    assert "PR-9" in sections["still_out"]["rows"][0]["detail"]


def test_warranty_claims_links_repair_cost(db, owner):
    wrench = _tool(db, owner)
    # Merge (2026-11-04): the cost lives ON the warranty claim;
    # the request links by claim_id.
    repair = claims_models.Claim(
        owner_id=owner.id, claim_number="CL-2026-001",
        claim_year=2026, number_seq=1, kind="warranty_repair",
        description="Cracked", repair_cost=Decimal("80"),
        reported_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        repair_completed_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        status="completed",
    )
    db.add(repair)
    db.flush()
    db.add(
        claims_models.ClaimLine(
            owner_id=owner.id, claim_id=repair.id,
            target_kind="tool", target_id=wrench.id,
            target_name="Wrench", value_basis="entered",
        )
    )
    db.flush()
    company = dealer_models.DealerCompany(name="Snap-on Incorporated")
    db.add(company)
    db.flush()
    db.add(
        dealer_models.WarrantyServiceRequest(
            requester_id=owner.id, company_id=company.id,
            company_name="Snap-on Incorporated",
            item_kind="tool", item_id=wrench.id, item_name="Wrench",
            claim_id=repair.id, status="sent",
        )
    )
    db.commit()
    report = activity.build_warranty_claims(db, owner)
    assert report["sections"][0]["count"] == 1
    assert report["totals"][0]["amount"] == "80.00"


def test_dealer_accounts_uses_signed_ledger(db, owner):
    dealer = _make_user(db, "TV-D-000701", "a13-dealer@example.com", ["tool_dealer"])
    account = truck_models.TruckAccount(
        dealer_user_id=dealer.id,
        customer_user_id=owner.id,
        customer_name="Kind Reporter",
        customer_email=owner.email,
        status="open",
        invite_token="a13-token",
    )
    db.add(account)
    db.flush()
    db.add_all(
        [
            truck_models.TruckEntry(
                account_id=account.id, dealer_user_id=dealer.id,
                kind="charge", amount=Decimal("200"), note="Sockets",
                entry_date=date(2026, 1, 5), source="manual",
                recorded_by=dealer.id,
            ),
            truck_models.TruckEntry(
                account_id=account.id, dealer_user_id=dealer.id,
                kind="payment", amount=Decimal("-75"), note="Cash",
                entry_date=date(2026, 1, 20), source="manual",
                recorded_by=owner.id,
            ),
        ]
    )
    db.commit()
    report = activity.build_dealer_accounts(db, owner)
    assert report["sections"][0]["total"] == "125.00"
    assert report["totals"][0]["amount"] == "125.00"  # balance agrees


def test_checked_out_report(db, owner):
    wrench = _tool(db, owner, replacement_cost=Decimal("450"))
    db.add(
        borrowing_models.Checkout(
            owner_id=owner.id,
            borrower_name="Neighbor Ned",
            item_kind="tool",
            item_id=wrench.id,
            item_name="Wrench",
            state="checked_out",
            checked_out_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            due_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        )
    )
    db.commit()
    report = activity.build_checked_out(db, owner)
    sections = {s["key"]: s for s in report["sections"]}
    assert sections["lent_out"]["count"] == 1
    assert sections["lent_out"]["rows"][0]["amount"] == "450.00"
    assert "Neighbor Ned" in sections["lent_out"]["rows"][0]["detail"]


def test_tax_year_splits_business_use(db, owner):
    _tool(
        db, owner, name="Shop press", business_use=True,
        purchase_price=Decimal("1200"), purchase_date=date(2026, 2, 1),
        quantity=1,
    )
    _tool(
        db, owner, name="Home drill", business_use=False,
        purchase_price=Decimal("150"), purchase_date=date(2026, 3, 1),
        quantity=1,
    )
    _tool(
        db, owner, name="Last year press", business_use=True,
        purchase_price=Decimal("999"), purchase_date=date(2025, 3, 1),
        quantity=1,
    )
    db.commit()
    report = activity.build_tax_year(db, owner, 2026)
    sections = {s["key"]: s for s in report["sections"]}
    assert sections["business_purchases"]["total"] == "1200.00"
    assert sections["other_purchases"]["total"] == "150.00"
    assert "NOT tax advice" in report["subtitle"]
    assert "placed in service" in sections["business_purchases"]["rows"][0]["detail"]


def test_activity_kinds_serve_and_email(client, db, owner, monkeypatch):
    _tool(db, owner, name="Taxed", business_use=True,
          purchase_price=Decimal("10"), purchase_date=date(2026, 1, 1))
    db.commit()
    headers = auth_headers(owner)
    for path in (
        "/api/reports/sales",
        "/api/reports/dealer-accounts",
        "/api/reports/checked-out",
        "/api/reports/lost-stolen",
        "/api/reports/warranty-claims",
        "/api/reports/tax-year?year=2026",
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.text)
    export = client.get("/api/reports/tax-year/export?year=2026&fmt=csv", headers=headers)
    assert export.status_code == 200
    assert b"Section 179" in export.content

    from app.core import notifications

    sent = {}

    def fake_send(db_, to, subject, body, *, kind="generic", attachment=None):
        sent.update(to=to, subject=subject, attachment=attachment)
        return True

    monkeypatch.setattr(notifications, "send_email", fake_send)
    resp = client.post(
        "/api/reports/activity/email",
        json={"kind": "tax_year", "year": 2026, "format": "pdf"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert sent["attachment"][0] == "tax_year.pdf"
    assert len(sent["attachment"][1]) > 100
