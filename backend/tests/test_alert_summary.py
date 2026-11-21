"""Alert summary (sheet row 62, owner 2026-11-17): the unread
counts behind the left menu's red count badges and the Home
widgets' urgency flags — GET /api/core/notifications/summary.

Pins: counts are the caller's UNREAD notifications inside the
inbox's own 30-day window, grouped by badge surface (a kind's
home is where its click-through lands, so the claims family
splits — deadline to Disaster Claims, warranty/backorder to
Repairs & Maintenance, readiness to Inventory); kinds with no
module home never count; a module the user has switched off
hides its counts exactly as it hides the inbox rows; marking a
notification read clears its badge (nothing is stored); and an
overdue borrow counts LIVE in both seats even though no
notification kind carries it — the owner's headline case.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.borrowing import models as borrowing_models
from app.modules.core import inbox, models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _alert_tables(db):
    bind = db.get_bind()
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)
    core_models.UserModulePref.__table__.create(bind=bind, checkfirst=True)
    borrowing_models.Checkout.__table__.create(bind=bind, checkfirst=True)


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
def user(db):
    return _make_user(db, "TV-M-000301", "sam@example.com", "Sam Summary")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "ora@example.com", "Ora Other")


def _note(db, user, kind, *, read=False, age_days=0):
    row = core_models.Notification(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=kind,
        title="t",
        body="b",
        data={},
        created_at=NOW - timedelta(days=age_days),
        read_at=NOW if read else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _summary(client, user) -> dict:
    resp = client.get(
        "/api/core/notifications/summary", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_summary_requires_signin(client):
    assert client.get("/api/core/notifications/summary").status_code == 401


def test_unread_grouped_by_surface(client, db, user):
    _note(db, user, inbox.KIND_FEEDBACK_STATUS)
    _note(db, user, inbox.KIND_FEEDBACK_COMMENT)
    _note(db, user, inbox.KIND_CLAIM_DEADLINE)
    _note(db, user, inbox.KIND_WARRANTY_CLAIM_UPDATE)
    _note(db, user, inbox.KIND_TRUCK_CHARGE)
    _note(db, user, inbox.KIND_PEER_INVITE_RECEIVED)
    # An account/system note with no module home: bell-only.
    _note(db, user, inbox.KIND_FEATURE_ANNOUNCEMENT)
    assert _summary(client, user) == {
        "counts": {
            "feedback": 2,
            "disaster_claims": 1,
            "maintenance": 1,
            "truck_accounts": 1,
            "shared_tools": 1,
        },
        "total": 6,
    }


def test_claims_family_splits_by_destination(client, db, user):
    _note(db, user, inbox.KIND_CLAIM_DEADLINE)
    _note(db, user, inbox.KIND_CLAIM_READINESS)
    _note(db, user, inbox.KIND_WARRANTY_ENDING)
    _note(db, user, inbox.KIND_CLAIM_BACKORDER)
    _note(db, user, inbox.KIND_MANUAL_SAVED)
    assert _summary(client, user)["counts"] == {
        "disaster_claims": 1,
        "inventory": 3,
        "maintenance": 1,
    }


def test_read_and_out_of_window_rows_do_not_count(client, db, user):
    _note(db, user, inbox.KIND_FEEDBACK_STATUS, read=True)
    _note(db, user, inbox.KIND_FEEDBACK_STATUS, age_days=40)
    assert _summary(client, user) == {"counts": {}, "total": 0}


def test_marking_read_clears_the_badge(client, db, user):
    row = _note(db, user, inbox.KIND_BORROW_REQUESTED)
    assert _summary(client, user)["counts"] == {"borrowing": 1}
    resp = client.post(
        f"/api/core/notifications/{row.id}/read", headers=auth_headers(user)
    )
    assert resp.status_code == 204
    assert _summary(client, user) == {"counts": {}, "total": 0}


def test_module_off_hides_its_counts(client, db, user):
    _note(db, user, inbox.KIND_FEEDBACK_STATUS)
    _note(db, user, inbox.KIND_DEALER_ROUTE_DAY)
    db.add(
        core_models.UserModulePref(
            user_id=user.id, module_id="feedback", enabled=False
        )
    )
    db.commit()
    assert _summary(client, user)["counts"] == {"dealers": 1}


def test_other_users_rows_never_count(client, db, user, other):
    _note(db, other, inbox.KIND_FEEDBACK_STATUS)
    _note(db, other, inbox.KIND_TRUCK_CHARGE)
    assert _summary(client, user) == {"counts": {}, "total": 0}


def _checkout(db, *, owner_id, borrower_user_id=None, state="checked_out",
              due_at=None):
    row = borrowing_models.Checkout(
        id=uuid.uuid4(),
        owner_id=owner_id,
        item_kind="tool",
        item_id=uuid.uuid4(),
        item_name="Impact wrench",
        borrower_name="Borrower",
        borrower_user_id=borrower_user_id,
        state=state,
        due_at=due_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_borrowing_overdue_counts_live_in_both_seats(client, db, user, other):
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    # Lent out by the user, overdue: counts.
    _checkout(db, owner_id=user.id, due_at=yesterday)
    # Borrowed by the user, overdue: counts.
    _checkout(db, owner_id=other.id, borrower_user_id=user.id,
              due_at=yesterday)
    # Out but not yet due: no count.
    _checkout(db, owner_id=user.id, due_at=tomorrow)
    # Overdue once, but returned: no count.
    _checkout(db, owner_id=user.id, state="returned", due_at=yesterday)
    # Somebody else's overdue lend between strangers: no count.
    _checkout(db, owner_id=other.id, due_at=yesterday)
    assert _summary(client, user)["counts"] == {"borrowing": 2}
