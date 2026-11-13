"""Deep audit F1-03 regression (2026-10-23): Home's numbers must
derive from the same truth as Reports.

The defect: Home's TOTAL VALUE read the inventory stats field
`total_market_value` — a SUM of `msrp`, a field owners rarely set —
while the Reports page's grand "Total value" is the report engine's
SUM of `purchase_price` (plus priced set addon pieces). A real
vault of purchase-priced tools therefore showed $0 at home and
$15,352.81 in Reports. The stats payload now carries `total_value`
on the reports basis, the Home stat reads it, and this test pins
stats == report on one fixture so the two can never drift again.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inv_models
from app.modules.inventory import service as inventory_service
from app.modules.reports import schemas as report_schemas
from app.modules.reports import service as report_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Stats User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000901", "stats-owner@example.com")


def _tool(db, owner, name, **kw):
    tool = inv_models.Tool(id=uuid.uuid4(), owner_id=owner.id, name=name, **kw)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name, **kw):
    battery = inv_models.Battery(
        id=uuid.uuid4(), owner_id=owner.id, name=name, **kw
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _rich_vault(db, owner):
    """The F1-03 shape: purchase prices everywhere, msrp nowhere —
    plus a set whose priced addon pieces and attached tool the
    report engine folds into the set row's totals."""
    _tool(
        db, owner, "Drill",
        purchase_price=Decimal("100.00"), quantity=2,
        replacement_cost=Decimal("120.00"),
    )
    _tool(
        db, owner, "Wrench",
        purchase_price=Decimal("25.50"), quantity=1,
        replacement_cost=Decimal("30.00"),
    )
    kit = _tool(
        db, owner, "Socket Kit", is_set=True,
        purchase_price=Decimal("50.00"), quantity=1,
        replacement_cost=Decimal("80.00"),
    )
    _tool(
        db, owner, "Ratchet (attached)", attached_to_set_id=kit.id,
        purchase_price=Decimal("10.00"), quantity=3,
        replacement_cost=Decimal("12.00"),
    )
    db.add(
        inv_models.SetPiece(
            id=uuid.uuid4(), set_id=kit.id, owner_id=owner.id,
            kind="addon", name="Deep sockets", price=Decimal("25.00"),
            status="present",
        )
    )
    db.add(
        inv_models.SetPiece(
            id=uuid.uuid4(), set_id=kit.id, owner_id=owner.id,
            kind="addon", name="Sold extension", price=Decimal("999.00"),
            status="sold",
        )
    )
    db.add(
        inv_models.SetPiece(
            id=uuid.uuid4(), set_id=kit.id, owner_id=owner.id,
            kind="core", name="Core socket", price=None, status="present",
        )
    )
    _battery(
        db, owner, "M18 pack",
        purchase_price=Decimal("50.00"), quantity=2,
        replacement_cost=Decimal("60.00"),
    )
    db.commit()


def test_home_stats_match_report_totals(db, owner):
    _rich_vault(db, owner)

    stats = inventory_service.get_inventory_stats(db, owner.id)
    report = report_service.build_report(db, owner.id, report_schemas.ReportSpec())

    # 200 + 25.50 + (50 set + 25 addon + 30 attached) + 100 battery.
    assert stats["total_value"] == Decimal("430.50")
    assert Decimal(report["summary"]["price_total"]) == Decimal("430.50")
    assert stats["total_value"] == Decimal(report["summary"]["price_total"])
    # Replacement already agreed before the fix; pin that too.
    # 240 + 30 + (80 set + 36 attached) + 120 battery.
    assert stats["total_replacement_cost"] == Decimal("506.00")
    assert stats["total_replacement_cost"] == Decimal(
        report["summary"]["replacement"]
    )
    # The msrp field keeps its own semantics — and on this
    # purchase-priced vault it is exactly the $0 that misled Home.
    assert stats["total_market_value"] == Decimal("0.00")


def test_stats_endpoint_carries_reports_basis_value(client, db, user_a):
    user_a.account_types = [MECHANIC]
    db.commit()
    created = client.post(
        "/api/inventory",
        json={
            "name": "Torque wrench",
            "purchase_price": "189.99",
            "replacement_cost": "219.99",
        },
        headers=auth_headers(user_a),
    )
    assert created.status_code == 201, created.text
    body = client.get(
        "/api/inventory/stats", headers=auth_headers(user_a)
    ).json()
    assert Decimal(body["total_value"]) == Decimal("189.99")
    assert Decimal(body["total_market_value"]) == Decimal("0.00")
    assert Decimal(body["total_replacement_cost"]) == Decimal("219.99")
