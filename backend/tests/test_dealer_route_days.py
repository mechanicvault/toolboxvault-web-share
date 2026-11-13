"""Dealer route-day schedules (completeness audit A2).

Pins: the next-visit computation for all three frequencies
(including anchor edge cases), the profile write/read round-trip
with the computed next visit, refusal of bad shapes, and the
scheduler reminder's idempotency (once per route day, only on
the route day).
"""

import uuid
from datetime import date, timedelta

import pytest

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.dealers import route_days
from tests.conftest import auth_headers

DEALER = "tool_dealer"


def _make_user(db, account_number, email, name="Route Agent"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[DEALER],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def agent(db):
    return _make_user(db, "TV-D-000601", "route-agent@example.com")


# -- the computation -----------------------------------------------------------


def test_next_visit_weekly():
    thursday = date(2026, 10, 22)
    assert thursday.weekday() == 3
    # Tuesday routes: next is Oct 27; on the day itself it is today.
    assert route_days.next_route_visit("weekly", 1, date(2026, 10, 20), thursday) == date(2026, 10, 27)
    assert route_days.next_route_visit("weekly", 3, date(2026, 10, 15), thursday) == thursday


def test_next_visit_biweekly_counts_from_the_anchor():
    anchor = date(2026, 10, 8)  # a Thursday route day
    assert route_days.next_route_visit("biweekly", 3, anchor, date(2026, 10, 22)) == date(2026, 10, 22)
    assert route_days.next_route_visit("biweekly", 3, anchor, date(2026, 10, 23)) == date(2026, 11, 5)
    # Before the anchor, the anchor itself is next.
    assert route_days.next_route_visit("biweekly", 3, anchor, date(2026, 10, 1)) == anchor


def test_next_visit_monthly_same_weekday_same_week():
    anchor = date(2026, 9, 8)  # the 2nd Tuesday of September
    assert anchor.weekday() == 1
    # October's 2nd Tuesday (Oct 13) has passed by Oct 22, so the
    # next visit is November's 2nd Tuesday.
    assert route_days.next_route_visit("monthly", 1, anchor, date(2026, 10, 22)) == date(2026, 11, 10)
    # Asked before October's visit, October answers.
    assert route_days.next_route_visit("monthly", 1, anchor, date(2026, 10, 1)) == date(2026, 10, 13)


def test_next_visit_incomplete_schedule_is_none():
    today = date(2026, 10, 22)
    assert route_days.next_route_visit(None, 1, today, today) is None
    assert route_days.next_route_visit("weekly", None, today, today) is None
    assert route_days.next_route_visit("weekly", 1, None, today) is None
    assert route_days.next_route_visit("daily", 1, today, today) is None


# -- profile round-trip ----------------------------------------------------------


def _set_route(client, user, **overrides):
    payload = {
        "route_frequency": "weekly",
        "route_day_of_week": 1,
        "route_anchor_date": "2026-10-20",
    }
    payload.update(overrides)
    return client.put(
        "/api/dealers/profile/me", json=payload, headers=auth_headers(user)
    )


def test_profile_route_round_trip_and_next_visit(client, agent):
    resp = _set_route(client, agent)
    assert resp.status_code == 200, resp.text
    view = client.get(
        "/api/dealers/profile/me", headers=auth_headers(agent)
    ).json()
    assert view["route_frequency"] == "weekly"
    assert view["route_day_of_week"] == 1
    assert view["route_anchor_date"] == "2026-10-20"
    expected = route_days.next_route_visit("weekly", 1, date(2026, 10, 20))
    assert view["route_next_visit"] == expected.isoformat()
    # Clearing with explicit nulls empties the schedule.
    resp = _set_route(
        client, agent, route_frequency=None, route_day_of_week=None,
        route_anchor_date=None,
    )
    assert resp.status_code == 200, resp.text
    view = client.get(
        "/api/dealers/profile/me", headers=auth_headers(agent)
    ).json()
    assert view["route_frequency"] is None
    assert view["route_next_visit"] is None


def test_profile_route_bad_shapes_refused(client, agent):
    assert _set_route(client, agent, route_frequency="daily").status_code == 422
    assert _set_route(client, agent, route_day_of_week=7).status_code == 422


# -- the reminder job ------------------------------------------------------------


def test_route_day_reminder_fires_once_on_the_route_day(client, db, agent):
    resp = _set_route(client, agent)
    assert resp.status_code == 200, resp.text
    today = date.today()
    # The fixture route is weekly Tuesdays; ask the job to run on
    # the coming Tuesday (a real route day) and again the same day.
    route_day = route_days.next_route_visit("weekly", 1, date(2026, 10, 20), today)
    assert route_days.run_route_day_reminders(db, today=route_day) == 1
    assert route_days.run_route_day_reminders(db, today=route_day) == 0
    notes = [
        n for n in inbox.list_for_user(db, agent.id)
        if n["kind"] == inbox.KIND_DEALER_ROUTE_DAY
    ]
    assert len(notes) == 1
    assert "Route day" in notes[0]["title"]
    # A non-route day sends nothing.
    assert route_days.run_route_day_reminders(db, today=route_day + timedelta(days=1)) == 0
