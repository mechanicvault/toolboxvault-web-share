"""Warranty expiry notifications — the jobs seam (sheet row,
2026-11-15).

Ryan's rule: a notification when a warranty is ending 60 / 30 /
3 days in advance, and one more stating it has expired. One
notification per (item, end date, stage); re-runs create
nothing; a moved end date earns its own warnings; lifetime and
dateless warranties never fire. Mirrors the maintenance overdue
seam's test pattern.
"""

import uuid
from datetime import date

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Test User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


import pytest


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000501", "warranty@example.com")


# Purchased 2025-01-10 with a 24-month term -> warranty ends
# 2027-01-10 (the shared computation, calendar months).
END = date(2027, 1, 10)


def _tool(db, owner, name="Torque wrench", **overrides):
    fields = {
        "purchase_date": date(2025, 1, 10),
        "warranty_months": 24,
        "warranty_type": "term",
    }
    fields.update(overrides)
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **fields)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="Jump pack", **overrides):
    fields = {
        "purchase_date": date(2025, 1, 10),
        "warranty_months": 24,
        "warranty_type": "term",
    }
    fields.update(overrides)
    battery = inventory_models.Battery(owner_id=owner.id, name=name, **fields)
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def test_stages_fire_once_each_in_order(db, owner):
    _tool(db, owner)
    run = inventory_service.run_warranty_notifications
    # 56 days out: the 60-day warning.
    assert run(db, today=date(2026, 11, 15)) == 1
    assert run(db, today=date(2026, 11, 15)) == 0
    # Still inside the 60 window a week later: nothing new.
    assert run(db, today=date(2026, 11, 22)) == 0
    # 30 days out: the 30-day warning.
    assert run(db, today=date(2026, 12, 11)) == 1
    assert run(db, today=date(2026, 12, 11)) == 0
    # 3 days out: the 3-day warning.
    assert run(db, today=date(2027, 1, 7)) == 1
    # The end date itself is the last covered day: nothing new.
    assert run(db, today=END) == 0
    # The day after: the expired note.
    assert run(db, today=date(2027, 1, 11)) == 1
    assert run(db, today=date(2027, 1, 12)) == 0


def test_notifications_land_in_the_inbox_with_stage_data(client, owner, db):
    tool = _tool(db, owner)
    inventory_service.run_warranty_notifications(db, today=date(2026, 11, 15))
    notes = client.get(
        "/api/core/notifications", headers=auth_headers(owner)
    ).json()
    hits = [n for n in notes if n["kind"] == "warranty_ending"]
    assert len(hits) == 1
    assert hits[0]["data"]["item_kind"] == "tool"
    assert hits[0]["data"]["item_id"] == str(tool.id)
    assert hits[0]["data"]["end_date"] == "2027-01-10"
    assert hits[0]["data"]["stage"] == "60"
    assert "Torque wrench" in hits[0]["body"]


def test_battery_fires_and_far_out_items_stay_quiet(db, owner):
    _battery(db, owner)
    run = inventory_service.run_warranty_notifications
    # 87 days out: outside every stage.
    assert run(db, today=date(2026, 10, 15)) == 0
    # 10 days out: the tightest applicable stage is the 30-day one.
    assert run(db, today=date(2026, 12, 31)) == 1
    assert run(db, today=date(2026, 12, 31)) == 0


def test_lifetime_and_dateless_warranties_never_fire(db, owner):
    _tool(db, owner, name="Lifetime tool", warranty_type="lifetime",
          warranty_months=None)
    _tool(db, owner, name="No dates", purchase_date=None,
          warranty_months=None, warranty_type=None)
    _tool(db, owner, name="No term", warranty_months=None,
          warranty_type=None)
    run = inventory_service.run_warranty_notifications
    assert run(db, today=date(2027, 2, 1)) == 0


def test_a_moved_end_date_earns_its_own_warnings(db, owner):
    tool = _tool(db, owner)
    run = inventory_service.run_warranty_notifications
    assert run(db, today=date(2026, 11, 15)) == 1
    # The owner extends the term: 36 months -> ends 2028-01-10.
    tool.warranty_months = 36
    db.commit()
    # The old date's stage does not re-fire against the new date;
    # the new date is far out, so nothing yet...
    assert run(db, today=date(2026, 11, 15)) == 0
    # ...until the new date enters the 60-day window.
    assert run(db, today=date(2027, 11, 20)) == 1
    assert run(db, today=date(2027, 11, 20)) == 0
