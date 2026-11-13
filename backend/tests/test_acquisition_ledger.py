"""Acquisition ledger (year-end fix, 2026-10-24).

Pins the staged proof that motivated the fix, plus the writer
and reader rules around it:

- create 3 × $149, sell 1 → the year-end Acquired section still
  says 3 / $447.00 (it used to say 2 / $298, because it read the
  item's CURRENT quantity, which the sale had shrunk), and the
  Sold section shows the sale;
- a quantity INCREASE via edit is a new acquisition of the added
  units; a decrease changes nothing;
- batteries ride the same ledger;
- deleting the item keeps its acquisition history (snapshot);
- a sale reversal restores quantity but never double-counts;
- the tax worksheet's purchase sections read the same ledger,
  split by the business-use flag at acquisition time;
- an item created price-less falls back to its own record until
  its first recorded acquisition, which then covers everything
  on hand.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import sales as sales_service
from app.modules.inventory import schemas as inventory_schemas
from app.modules.inventory import service as inventory_service
from app.modules.reports import activity

MECHANIC = "mechanic_technician"


@pytest.fixture()
def owner(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000777",
        email="ledger@example.com",
        name="Ledger Owner",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _section(report, key):
    return {s["key"]: s for s in report["sections"]}[key]


def _make_tool(db, owner, **overrides):
    payload = {
        "name": "Impact wrench",
        "brand": "Milwaukee",
        "quantity": 3,
        "purchase_price": Decimal("149"),
        "purchase_date": date(2026, 2, 1),
    }
    payload.update(overrides)
    return inventory_service.create_tool(
        db, owner.id, inventory_schemas.ToolCreate(**payload)
    )


def test_partial_sale_never_rewrites_acquisition_history(db, owner):
    tool = _make_tool(db, owner)
    sales_service.mark_sold(
        db,
        owner.id,
        "tool",
        tool.id,
        quantity_sold=1,
        sale_price=Decimal("200"),
        sold_on=date(2026, 3, 1),
    )
    db.refresh(tool)
    assert tool.quantity == 2  # the sale really did shrink the record

    report = activity.build_year_end(db, owner, 2026)
    acquired = _section(report, "acquired")
    assert acquired["total"] == "447.00"
    assert acquired["count"] == 1
    assert acquired["rows"][0]["amount"] == "447.00"
    assert acquired["rows"][0]["item"] == "Impact wrench"
    sold = _section(report, "sold")
    assert sold["total"] == "200.00"
    assert sold["count"] == 1
    totals = {t["label"]: t["amount"] for t in report["totals"]}
    assert totals["Total acquired value"] == "447.00"
    assert totals["Total sales"] == "200.00"


def test_quantity_increase_is_a_new_acquisition(db, owner):
    tool = _make_tool(
        db, owner, quantity=2, purchase_price=Decimal("100"),
        purchase_date=date(2026, 1, 10),
    )
    inventory_service.update_tool(
        db, owner.id, tool.id,
        inventory_schemas.ToolUpdate(quantity=5),
    )
    report = activity.build_year_end(db, owner, 2026)
    acquired = _section(report, "acquired")
    # 2 × $100 at creation + 3 × $100 added later.
    assert acquired["total"] == "500.00"
    assert acquired["count"] == 2

    # A decrease is NOT an acquisition event and un-acquires nothing.
    inventory_service.update_tool(
        db, owner.id, tool.id,
        inventory_schemas.ToolUpdate(quantity=4),
    )
    report = activity.build_year_end(db, owner, 2026)
    assert _section(report, "acquired")["total"] == "500.00"


def test_battery_partial_sale_keeps_acquired_total(db, owner):
    battery = inventory_service.create_battery(
        db,
        owner.id,
        inventory_schemas.BatteryCreate(
            name="M18 pack",
            brand="Milwaukee",
            quantity=4,
            purchase_price=Decimal("50"),
            purchase_date=date(2026, 5, 5),
        ),
    )
    sales_service.mark_sold(
        db,
        owner.id,
        "battery",
        battery.id,
        quantity_sold=1,
        sale_price=Decimal("60"),
        sold_on=date(2026, 6, 1),
    )
    report = activity.build_year_end(db, owner, 2026)
    assert _section(report, "acquired")["total"] == "200.00"
    assert _section(report, "sold")["total"] == "60.00"


def test_deleted_item_keeps_its_acquisition_history(db, owner):
    tool = _make_tool(
        db, owner, quantity=1, purchase_price=Decimal("75"),
        purchase_date=date(2026, 2, 2),
    )
    assert inventory_service.delete_tool(db, owner.id, tool.id)
    report = activity.build_year_end(db, owner, 2026)
    acquired = _section(report, "acquired")
    assert acquired["total"] == "75.00"
    assert acquired["rows"][0]["item"] == "Impact wrench"


def test_sale_reversal_does_not_double_count(db, owner):
    tool = _make_tool(db, owner)
    record = sales_service.mark_sold(
        db,
        owner.id,
        "tool",
        tool.id,
        quantity_sold=1,
        sale_price=Decimal("200"),
        sold_on=date(2026, 3, 1),
    )
    sales_service.undo_sale(db, owner.id, record.id)
    db.refresh(tool)
    assert tool.quantity == 3
    report = activity.build_year_end(db, owner, 2026)
    assert _section(report, "acquired")["total"] == "447.00"
    # Sale + reversal net to zero in the Sold section.
    assert _section(report, "sold")["total"] == "0.00"


def test_tax_worksheet_reads_the_same_ledger(db, owner):
    tool = _make_tool(db, owner, business_use=True)
    sales_service.mark_sold(
        db,
        owner.id,
        "tool",
        tool.id,
        quantity_sold=1,
        sale_price=Decimal("200"),
        sold_on=date(2026, 3, 1),
    )
    report = activity.build_tax_year(db, owner, 2026)
    sections = {s["key"]: s for s in report["sections"]}
    assert sections["business_purchases"]["total"] == "447.00"
    assert sections["other_purchases"]["total"] == "0.00"
    assert sections["disposals"]["count"] == 1
    totals = {t["label"]: t["amount"] for t in report["totals"]}
    assert totals["Business purchases"] == "447.00"


def test_priceless_item_falls_back_until_first_recorded_acquisition(db, owner):
    tool = inventory_service.create_tool(
        db,
        owner.id,
        inventory_schemas.ToolCreate(
            name="Untagged socket set",
            quantity=2,
            purchase_date=date(2026, 4, 1),
        ),
    )
    # No price recorded anywhere → nothing acquired, money-wise.
    report = activity.build_year_end(db, owner, 2026)
    assert _section(report, "acquired")["total"] == "0.00"

    # A price typed in later (no quantity change) reads off the
    # item's own record — the pre-ledger behavior for row-less items.
    inventory_service.update_tool(
        db, owner.id, tool.id,
        inventory_schemas.ToolUpdate(purchase_price=Decimal("80")),
    )
    report = activity.build_year_end(db, owner, 2026)
    assert _section(report, "acquired")["total"] == "160.00"

    # The first quantity increase now records the WHOLE holding,
    # so history starts complete rather than delta-only.
    inventory_service.update_tool(
        db, owner.id, tool.id,
        inventory_schemas.ToolUpdate(quantity=3),
    )
    report = activity.build_year_end(db, owner, 2026)
    acquired = _section(report, "acquired")
    assert acquired["total"] == "240.00"
    assert acquired["count"] == 1


def test_other_years_stay_empty(db, owner):
    _make_tool(db, owner)
    report = activity.build_year_end(db, owner, 2025)
    assert _section(report, "acquired")["count"] == 0
    assert _section(report, "acquired")["total"] == "0.00"
