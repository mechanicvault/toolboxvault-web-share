"""Wave 3 — reports extras (year-end + repair costs) and claim
extras (package PDF, duplicate, archive, per-line toggles).

Pins:
- the year-end ledger gathers from each owning module's book:
  purchases (price × qty, tools + batteries), the sold ledger
  (reversals net against sales), lost/stolen reports (at
  purchase cost where resolvable), repairs with costs, and
  warranty service requests — each section totalled, with the
  three headline totals (acquired / sales / repair spend) and
  the honest "for your records / give to your tax preparer"
  label (never tax advice);
- CSV + PDF render off the SAME builder, so the download can
  never disagree with the screen;
- repair costs: only records with a recorded cost, period
  filtered, totalled;
- claims: archive hides a claim from the default list + the
  home stat but keeps it readable + filterable, unarchive
  restores; duplicate copies incident fields + lines into a new
  DRAFT with a FRESH number and NO evidence / comms / deadlines;
  the package PDF respects the per-line include toggle.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from app.modules.claims import models as claims_models
from app.modules.reports import activity
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Reporter"):
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
    return _make_user(db, "TV-M-000601", "w3-reports@example.com")


def _seed_year(db, owner):
    """A 2026 with one of everything + a 2025 purchase that must
    NOT leak into the 2026 ledger."""
    wrench = inventory_models.Tool(
        owner_id=owner.id, name="Torque wrench", brand="Snap-on",
        model="", serial_number="", quantity=2,
        purchase_price=Decimal("250"), purchase_date=date(2026, 3, 4),
        replacement_cost=Decimal("300"),
    )
    old = inventory_models.Tool(
        owner_id=owner.id, name="Old ratchet", brand="", model="",
        serial_number="", purchase_price=Decimal("80"),
        purchase_date=date(2025, 5, 1),
    )
    battery = inventory_models.Battery(
        owner_id=owner.id, name="M18 pack", brand="Milwaukee",
        model="", serial_number="", quantity=1,
        purchase_price=Decimal("99"), purchase_date=date(2026, 1, 15),
    )
    db.add_all([wrench, old, battery])
    db.flush()
    # Sold ledger: +300 sale, its reversal, +150 sale → net 150.
    db.add_all(
        [
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                item_name="Torque wrench", quantity_sold=1,
                sale_price=Decimal("300"), sold_on=date(2026, 4, 2),
                kind="sale", source="manual",
            ),
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=wrench.id,
                item_name="Torque wrench", quantity_sold=1,
                sale_price=Decimal("300"), sold_on=date(2026, 4, 3),
                kind="reversal", source="manual",
            ),
            inventory_models.SaleRecord(
                owner_id=owner.id, item_kind="tool", item_id=old.id,
                item_name="Old ratchet", quantity_sold=1,
                sale_price=Decimal("150"), sold_on=date(2026, 5, 6),
                kind="sale", source="manual",
            ),
        ]
    )
    # Lost report on the wrench (purchase 250 x qty 2; its
    # replacement cost of 300 is not the report's basis).
    db.add(
        inventory_models.ItemLossReport(
            owner_id=owner.id, item_kind="tool", item_id=wrench.id,
            standing="lost", reported_date=date(2026, 7, 7),
        )
    )
    # Repairs (merge, 2026-11-04): the repair IS a warranty claim
    # now — one costed + completed, one costless (excluded from
    # the cost reports by its missing cost).
    repair = claims_models.Claim(
        owner_id=owner.id, claim_number="CL-2026-001",
        claim_year=2026, number_seq=1, kind="warranty_repair",
        status="completed", description="Cracked handle",
        repair_cost=Decimal("175.50"), repair_sent_to="Snap-on",
        reported_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        repair_completed_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db.add(repair)
    db.add(
        claims_models.Claim(
            owner_id=owner.id, claim_number="CL-2026-002",
            claim_year=2026, number_seq=2, kind="warranty_repair",
            status="reported", description="Inspection only",
            reported_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
    )
    db.flush()
    db.add(
        claims_models.ClaimLine(
            owner_id=owner.id, claim_id=repair.id,
            target_kind="tool", target_id=wrench.id,
            target_name="Torque wrench", value_basis="entered",
        )
    )
    db.flush()
    # A warranty service request in the year, linked to the claim.
    company = dealer_models.DealerCompany(name="Snap-on Incorporated")
    db.add(company)
    db.flush()
    db.add(
        dealer_models.WarrantyServiceRequest(
            requester_id=owner.id, company_id=company.id,
            item_kind="tool", item_id=wrench.id,
            item_name="Torque wrench", claim_id=repair.id,
            status="sent",
        )
    )
    db.commit()
    return {"wrench": wrench, "battery": battery, "claim": repair}


# -- year-end ---------------------------------------------------------------------


def test_year_end_ledger_totals(db, owner):
    _seed_year(db, owner)
    report = activity.build_year_end(db, owner, 2026)
    assert report["kind"] == "year_end"
    # The honest label, verbatim — records for a tax preparer,
    # never presented as tax advice.
    assert report["subtitle"] == activity.YEAR_END_LABEL
    assert "tax preparer" in report["subtitle"]
    sections = {s["key"]: s for s in report["sections"]}
    # Acquired: 250×2 tools + 99 battery; the 2025 ratchet excluded.
    assert sections["acquired"]["total"] == "599.00"
    assert sections["acquired"]["count"] == 2
    # Sold: 300 − 300 (reversal) + 150.
    assert sections["sold"]["total"] == "150.00"
    assert sections["sold"]["count"] == 3
    # Lost: valued at PURCHASE cost (owner ruling 2026-11-06 —
    # report money is what the owner paid): 250 x qty 2 = 500.
    # The wrench's 300 replacement cost plays no part.
    assert sections["lost_stolen"]["rows"][0]["amount"] == "500.00"
    # Repairs: only the costed record.
    assert sections["repairs"]["total"] == "175.50"
    assert sections["repairs"]["count"] == 1
    # Warranty: the request, carrying the linked repair's cost.
    assert sections["warranty_repairs"]["count"] == 1
    assert sections["warranty_repairs"]["rows"][0]["amount"] == "175.50"
    totals = {t["label"]: t["amount"] for t in report["totals"]}
    assert totals == {
        "Total acquired value": "599.00",
        "Total sales": "150.00",
        "Total repair spend": "175.50",
    }
    # Other years are honestly empty.
    empty = activity.build_year_end(db, owner, 2024)
    assert all(s["count"] == 0 for s in empty["sections"])


def test_year_end_endpoints_and_downloads(client, db, owner):
    _seed_year(db, owner)
    headers = auth_headers(owner)
    body = client.get("/api/reports/year-end", params={"year": 2026}, headers=headers)
    assert body.status_code == 200, body.text
    assert body.json()["totals"][0]["amount"] == "599.00"

    csv_body = client.get(
        "/api/reports/year-end/export",
        params={"year": 2026, "fmt": "csv"},
        headers=headers,
    )
    assert csv_body.status_code == 200
    text = csv_body.content.decode("utf-8")
    assert "Total acquired value: 599.00 USD" in text
    assert "Torque wrench" in text

    pdf_body = client.get(
        "/api/reports/year-end/export",
        params={"year": 2026, "fmt": "pdf"},
        headers=headers,
    )
    assert pdf_body.status_code == 200
    assert pdf_body.content.startswith(b"%PDF")
    assert "attachment" in pdf_body.headers["content-disposition"]


# -- repair costs ---------------------------------------------------------------------


def test_repair_costs_report(db, client, owner):
    _seed_year(db, owner)
    report = activity.build_repair_costs(db, owner)
    section = report["sections"][0]
    assert section["count"] == 1
    assert section["rows"][0]["item"] == "Torque wrench"
    assert report["totals"] == [
        {"label": "Total repair spend", "amount": "175.50"}
    ]
    # Period filter excludes the June repair.
    january = activity.build_repair_costs(
        db, owner, start=date(2026, 1, 1), end=date(2026, 1, 31)
    )
    assert january["sections"][0]["count"] == 0

    headers = auth_headers(owner)
    body = client.get("/api/reports/repair-costs", headers=headers)
    assert body.status_code == 200
    assert body.json()["totals"][0]["amount"] == "175.50"
    pdf_body = client.get(
        "/api/reports/repair-costs/export", params={"fmt": "pdf"}, headers=headers
    )
    assert pdf_body.content.startswith(b"%PDF")


# -- claim extras ------------------------------------------------------------------------


def _claim_with_line(client, db, owner):
    tool = inventory_models.Tool(
        owner_id=owner.id, name="Claimed saw", brand="Makita",
        model="", serial_number="", purchase_price=Decimal("400"),
        replacement_cost=Decimal("450"),
    )
    db.add(tool)
    db.commit()
    claim = client.post(
        "/api/disaster-claims",
        json={
            "insurer_name": "Acme Mutual",
            "policy_number": "POL-9",
            "incident_type": "theft",
            "incident_date": "2026-09-01",
            "description": "Garage break-in",
            "police_report_number": "26-1042",
            "police_department": "Morrison County Sheriff",
        },
        headers=auth_headers(owner),
    )
    assert claim.status_code == 201, claim.text
    claim = claim.json()
    line = client.post(
        f"/api/disaster-claims/{claim['id']}/lines",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            # Claim money is purchase cost (ruling 2026-11-06):
            # the line prices from the 400 paid, not the 450
            # replacement decoy on the same record.
            "value_basis": "purchase",
        },
        headers=auth_headers(owner),
    )
    assert line.status_code == 201, line.text
    return claim, line.json(), tool


def test_claim_archive_hides_and_restores(client, db, owner):
    claim, _line, _tool = _claim_with_line(client, db, owner)
    headers = auth_headers(owner)
    listed = client.get("/api/disaster-claims", headers=headers).json()
    assert [c["id"] for c in listed] == [claim["id"]]
    # The home stat counts insurer-held claims — file it first.
    filed = client.post(
        f"/api/disaster-claims/{claim['id']}/transition",
        json={"to_status": "filed"},
        headers=headers,
    )
    assert filed.status_code == 200, filed.text
    stats = client.get("/api/disaster-claims/stats", headers=headers).json()
    assert stats["open_claims_count"] == 1

    archived = client.post(
        f"/api/disaster-claims/{claim['id']}/archive",
        json={"archived": True},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived"] is True
    assert archived.json()["archived_at"] is not None
    # Gone from the default list + the stat…
    assert client.get("/api/disaster-claims", headers=headers).json() == []
    assert client.get("/api/disaster-claims/stats", headers=headers).json()["open_claims_count"] == 0
    # …but viewable through the filter and directly.
    filtered = client.get(
        "/api/disaster-claims", params={"include_archived": True}, headers=headers
    ).json()
    assert [c["id"] for c in filtered] == [claim["id"]]
    assert client.get(f"/api/disaster-claims/{claim['id']}", headers=headers).status_code == 200
    # Journaled as an edit.
    from app.modules.core import models as core_models

    kinds = {
        (row.entity_type, row.action)
        for row in db.query(core_models.ChangeJournal).all()
    }
    assert ("claim", "update") in kinds

    restored = client.post(
        f"/api/disaster-claims/{claim['id']}/archive",
        json={"archived": False},
        headers=headers,
    )
    assert restored.json()["archived"] is False
    assert [c["id"] for c in client.get("/api/disaster-claims", headers=headers).json()] == [
        claim["id"]
    ]


def test_claim_duplicate_copies_incident_and_lines_only(client, db, owner):
    claim, line, _tool = _claim_with_line(client, db, owner)
    headers = auth_headers(owner)
    # Give the source a comms entry — duplicates must NOT carry it.
    comm = client.post(
        f"/api/disaster-claims/{claim['id']}/communications",
        json={
            "channel": "phone",
            "contact": "Adjuster Amy",
            "summary": "Called about the saw",
            "occurred_at": "2026-09-02T10:00:00Z",
        },
        headers=headers,
    )
    assert comm.status_code == 201, comm.text

    copy = client.post(f"/api/disaster-claims/{claim['id']}/duplicate", headers=headers)
    assert copy.status_code == 201, copy.text
    body = copy.json()
    assert body["id"] != claim["id"]
    assert body["claim_number"] != claim["claim_number"]
    assert body["status"] == "draft"
    assert body["insurer_name"] == "Acme Mutual"
    assert body["police_report_number"] == "26-1042"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["target_name"] == "Claimed saw"
    assert body["lines"][0]["amount"] == "400.00" or body["lines"][0]["amount"] == "400"
    assert body["communications"] == []
    assert body["evidence"] == []
    # Deadlines do NOT carry (they belong to the original filing).
    assert body["proof_of_loss_due"] is None


def test_claim_package_respects_line_toggles(client, db, owner):
    claim, line, _tool = _claim_with_line(client, db, owner)
    headers = auth_headers(owner)
    full = client.get(f"/api/disaster-claims/{claim['id']}/package", headers=headers)
    assert full.status_code == 200
    assert full.content.startswith(b"%PDF")
    assert "claim-package-" in full.headers["content-disposition"]

    toggled = client.patch(
        f"/api/disaster-claims/{claim['id']}/lines/{line['id']}/package",
        json={"include_in_package": False},
        headers=headers,
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["include_in_package"] is False
    # The toggled package still builds (its summary total drops
    # the excluded line: the PDF bytes differ from the full one).
    trimmed = client.get(f"/api/disaster-claims/{claim['id']}/package", headers=headers)
    assert trimmed.status_code == 200
    assert trimmed.content.startswith(b"%PDF")
    assert trimmed.content != full.content
