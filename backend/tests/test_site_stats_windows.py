"""Sheet row 49 (owner, 2026-11-15): new_paid_windows — the
New-paid header stat's carousel spans (today / Monday-start
week / month / year, each through the end of the day), counted
exactly like new_paid_on: paid-plan subscription rows with a
real status, created in the span."""
import uuid
from datetime import date, datetime, time, timedelta, timezone

from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from app.modules.core import site_stats


def _user(db, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-W-{uuid.uuid4().hex[:6]}",
        email=email,
        name="Windows User",
        password_hash="not-a-real-hash",
        account_types=[],
        tier="normal",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _sub(db, user, plan_key, status, on_day):
    stamp = datetime.combine(on_day, time(12, 0), tzinfo=timezone.utc)
    db.add(
        billing_models.Subscription(
            user_id=user.id,
            plan_key=plan_key,
            status=status,
            source="test",
            current_period_end=stamp + timedelta(days=30),
            created_at=stamp,
            updated_at=stamp,
        )
    )
    db.commit()


def test_new_paid_windows(db):
    db.add(billing_models.Plan(plan_key="free", name="Free", is_paid=False, sort_order=0))
    db.add(billing_models.Plan(plan_key="pro", name="Pro", is_paid=True, sort_order=1))
    db.commit()
    day = date(2026, 11, 10)  # a Tuesday; its week starts Mon Nov 9
    # One subscription per user (unique user_id), so each row
    # gets its own account.
    rows = [
        ("pro", "active", date(2026, 11, 10)),   # today
        ("pro", "active", date(2026, 11, 9)),    # this week
        ("pro", "active", date(2026, 11, 5)),    # this month
        ("pro", "active", date(2026, 3, 15)),    # this year
        ("pro", "none", date(2026, 11, 10)),     # placeholder: never counts
        ("free", "active", date(2026, 11, 10)),  # free plan: never counts
    ]
    for i, (plan_key, status, on_day) in enumerate(rows):
        _sub(db, _user(db, f"paid{i}@example.com"), plan_key, status, on_day)
    windows = site_stats.new_paid_windows(db, day)
    assert windows == {"today": 1, "week": 2, "month": 3, "year": 4}
    assert windows["today"] == site_stats.new_paid_on(db, day)
