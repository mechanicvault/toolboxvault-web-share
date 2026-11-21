"""Tab notification bubbles (sheet row 190, owner 2026-11-19).

Pins: GET /api/core/notifications/tab-badges counts the caller's
UNREAD notifications per tab — the warranty-claim family on the
Claims tab, maintenance overdue on the Maintenance tab, claim
deadlines on the Disaster tab, the borrow family on the Borrowing
tab — kept separate even where two tabs share one row-62 badge
surface. Borrowing also returns the LIVE overdue checkout ids
(both seats). Health is the live health-check scan total: it is
not an unread count and nothing in this surface clears it.

POST /api/core/notifications/read-tab marks exactly that tab's
kinds read for the caller (clicking the tab clears its bubble),
answers how many changed, touches no other tab's rows and no
other user's rows, and 422s an unknown tab.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.borrowing import models as borrow_models
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _tables(db):
    bind = db.get_bind()
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)
    borrow_models.Checkout.__table__.create(bind=bind, checkfirst=True)


def _make_user(db, account_number: str, email: str, name: str):
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
    return _make_user(db, "TV-M-000301", "tab-owner@example.com", "Tab Owner")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "tab-other@example.com", "Tab Other")


def _note(db, user, kind, *, read=False, days_ago=0):
    row = core_models.Notification(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=kind,
        title="t",
        body="b",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        read_at=datetime.now(timezone.utc) if read else None,
    )
    db.add(row)
    db.commit()
    return row


def _badges(client, user):
    resp = client.get(
        "/api/core/notifications/tab-badges", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_tab_badges_split_the_shared_surface(db, client, owner):
    _note(db, owner, "warranty_claim_new")
    _note(db, owner, "warranty_claim_update")
    _note(db, owner, "claim_backorder_reminder")
    _note(db, owner, "maintenance_overdue")
    _note(db, owner, "maintenance_overdue")
    _note(db, owner, "claim_deadline")
    _note(db, owner, "borrow_requested")
    # Read rows and other families never count.
    _note(db, owner, "warranty_claim_new", read=True)
    _note(db, owner, "message_received")
    _note(db, owner, "support_reply")
    badges = _badges(client, owner)
    assert badges["claims"] == 3
    assert badges["maintenance"] == 2
    assert badges["disaster"] == 1
    assert badges["borrowing"] == 1
    assert badges["borrowing_overdue_ids"] == []
    assert badges["health"] == 0


def test_tab_badges_are_caller_scoped(db, client, owner, other):
    _note(db, other, "maintenance_overdue")
    _note(db, other, "claim_deadline")
    badges = _badges(client, owner)
    assert badges["maintenance"] == 0
    assert badges["disaster"] == 0


def test_tab_badges_window_matches_the_inbox(db, client, owner):
    _note(db, owner, "maintenance_overdue", days_ago=31)
    _note(db, owner, "maintenance_overdue", days_ago=29)
    assert _badges(client, owner)["maintenance"] == 1


def test_tab_badges_live_overdue_ids_both_seats(db, client, owner, other):
    now = datetime.now(timezone.utc)
    lent = borrow_models.Checkout(
        id=uuid.uuid4(),
        owner_id=owner.id,
        item_kind="tool",
        item_id=uuid.uuid4(),
        item_name="Lent wrench",
        borrower_name="Manual Borrower",
        state=borrow_models.STATE_CHECKED_OUT,
        due_at=now - timedelta(days=2),
    )
    held = borrow_models.Checkout(
        id=uuid.uuid4(),
        owner_id=other.id,
        borrower_user_id=owner.id,
        item_kind="tool",
        item_id=uuid.uuid4(),
        item_name="Held wrench",
        borrower_name="Tab Owner",
        state=borrow_models.STATE_CHECKED_OUT,
        due_at=now - timedelta(hours=3),
    )
    not_due = borrow_models.Checkout(
        id=uuid.uuid4(),
        owner_id=owner.id,
        item_kind="tool",
        item_id=uuid.uuid4(),
        item_name="Fine wrench",
        borrower_name="Manual Borrower",
        state=borrow_models.STATE_CHECKED_OUT,
        due_at=now + timedelta(days=2),
    )
    db.add_all([lent, held, not_due])
    db.commit()
    badges = _badges(client, owner)
    assert sorted(badges["borrowing_overdue_ids"]) == sorted(
        [str(lent.id), str(held.id)]
    )


def test_health_count_is_the_live_scan(client, owner):
    resp = client.post(
        "/api/inventory",
        json={"name": "Bare wrench"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    badges = _badges(client, owner)
    assert badges["health"] == 1


def test_read_tab_marks_only_that_tab(db, client, owner):
    _note(db, owner, "warranty_claim_new")
    _note(db, owner, "warranty_claim_update")
    _note(db, owner, "maintenance_overdue")
    resp = client.post(
        "/api/core/notifications/read-tab",
        json={"tab": "claims"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2
    badges = _badges(client, owner)
    assert badges["claims"] == 0
    assert badges["maintenance"] == 1


def test_read_tab_is_caller_scoped(db, client, owner, other):
    _note(db, other, "claim_deadline")
    resp = client.post(
        "/api/core/notifications/read-tab",
        json={"tab": "disaster"},
        headers=auth_headers(owner),
    )
    assert resp.json()["updated"] == 0
    assert _badges(client, other)["disaster"] == 1


def test_read_tab_unknown_tab_422s(client, owner):
    resp = client.post(
        "/api/core/notifications/read-tab",
        json={"tab": "health"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
