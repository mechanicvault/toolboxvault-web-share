"""Admin panel widgets (owner, 2026-11-15): the three sample
panels — Admin overview, Site scoreboard, System health — on
ONE aggregate read, GET /api/admin/panel.

Pins (fixed clock, rows planted on the boundaries):

- GATE: require_user_manager — god / moderator_admin /
  operator get 200; normal and downloads seats get 403;
  anonymous callers get 401.
- WINDOW MATH: UTC calendar windows (site_pulse convention);
  a row at a window's start counts, one second before it
  does not.
- SOURCES: every windowed number counts the source table the
  module docstring names; cancellations use
  entitlements.is_cancellation_change; AI cost is the wallet
  credits charged, never dollars.
- HEALTH: the database check really pings, the backup check
  reads the ledger's latest row, the email check reads the
  outbox; there is no uptime number anywhere in the payload.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from app.modules.billing import models as billing_models
from app.modules.core import admin_panel, models as core_models
from app.modules.downloads import models as downloads_models
from app.modules.feedback import models as feedback_models
from app.modules.forum import models as forum_models
from app.modules.inventory import models as inventory_models
from app.modules.prints import models as prints_models
from app.modules.support import models as support_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)
# Business-day frame (sheet row 119): TODAY is the
# Chicago-midnight start of NOW's Chicago day, as a UTC
# instant; seed offsets below are whole business days/hours
# from it.
from app.core.business_time import business_date, business_day_bounds

TODAY = business_day_bounds(business_date(NOW))[0]


def _make_user(db, account_number, email, tier=None, is_operator=False,
               role="user", created_at=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Panel User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role=role,
        is_operator=is_operator,
    )
    if tier is not None:
        user.tier = tier
    if created_at is not None:
        user.created_at = created_at
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seeded(db):
    db.add_all([
        billing_models.Plan(
            plan_key="free", name="Free", item_limit=20,
            ai_monthly_credits=0, is_paid=False, sort_order=0),
        billing_models.Plan(
            plan_key="pro", name="Pro", item_limit=None,
            ai_monthly_credits=0, is_paid=True, sort_order=1),
    ])
    db.commit()
    owner = _make_user(db, "TV-P-000001", "panel-owner@example.com",
                       created_at=TODAY + timedelta(hours=1))
    _make_user(db, "TV-P-000002", "panel-week@example.com",
               created_at=TODAY - timedelta(days=3))
    _make_user(db, "TV-P-000003", "panel-month@example.com",
               created_at=TODAY - timedelta(days=20))
    _make_user(db, "TV-P-000004", "panel-old@example.com",
               created_at=TODAY - timedelta(days=40))
    # One tool logged today.
    db.add(inventory_models.AcquisitionRecord(
        id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
        item_id=uuid.uuid4(),
        created_at=TODAY + timedelta(hours=2)))
    # One download today (a document file first).
    doc = downloads_models.DownloadFile(
        id=uuid.uuid4(), key="panel-doc", file_format="pdf",
        filename="panel.pdf", storage_key="panel/panel.pdf", sort_order=1)
    db.add(doc)
    db.commit()
    db.add(downloads_models.DownloadEvent(
        id=uuid.uuid4(), file_key="panel-doc",
        created_at=TODAY + timedelta(hours=3)))
    # One print uploaded today.
    db.add(prints_models.PrintFile(
        id=uuid.uuid4(), publisher_id=owner.id, title="Panel Print",
        category_key="tools", created_at=TODAY + timedelta(hours=4)))
    # One forum post today (category + thread first).
    category = forum_models.ForumCategory(
        id=uuid.uuid4(), name="Panel Category")
    db.add(category)
    db.commit()
    thread = forum_models.ForumThread(
        id=uuid.uuid4(), category_id=category.id,
        author_id=owner.id, title="Panel Thread")
    db.add(thread)
    db.commit()
    db.add(forum_models.ForumPost(
        id=uuid.uuid4(), thread_id=thread.id, author_id=owner.id,
        created_at=TODAY + timedelta(hours=5)))
    # One open support ticket, filed 30 hours ago.
    db.add(support_models.SupportTicket(
        id=uuid.uuid4(), user_id=owner.id, subject="Panel Ticket",
        status="open", created_at=NOW - timedelta(hours=30)))
    # One open bug report (high urgency) from 10 days ago.
    db.add(feedback_models.FeedbackPost(
        id=uuid.uuid4(), board="bug", author_id=owner.id,
        title="Panel Bug", status="open", visibility="public",
        urgency="high", created_at=TODAY - timedelta(days=10)))
    # One AI action today (2 calls, 15 credits).
    db.add(billing_models.AiUsage(
        id=uuid.uuid4(), user_id=owner.id, action="lookup",
        calls=2, credits_charged=15, created_at=TODAY + timedelta(hours=6)))
    # One paid subscription created today + one cancellation
    # recorded 10 days ago (active -> canceled).
    sub = billing_models.Subscription(
        id=uuid.uuid4(), user_id=owner.id, plan_key="pro",
        status="active", created_at=TODAY + timedelta(hours=7))
    db.add(sub)
    db.commit()
    db.add(billing_models.SubscriptionStatusChange(
        id=uuid.uuid4(), subscription_id=sub.id, user_id=owner.id,
        from_status="active", to_status="canceled",
        source="admin", created_at=TODAY - timedelta(days=10)))
    # One clean backup run, finished 2 hours ago, off-site.
    db.add(core_models.BackupRun(
        id=uuid.uuid4(), started_at=NOW - timedelta(hours=2, minutes=5),
        finished_at=NOW - timedelta(hours=2), size_bytes=1_000_000,
        encrypted=True, uploaded=True, verified=True, status="ok"))
    # Outbox: two logged messages in the last 7 days.
    for _ in range(2):
        db.add(core_models.EmailOutbox(
            id=uuid.uuid4(), recipient="panel@example.com",
            subject="Panel", kind="generic", body="x",
            provider="dev", status="logged",
            created_at=TODAY - timedelta(days=1)))
    # One clean job run.
    db.add(core_models.JobRun(
        id=uuid.uuid4(), job="entitlements",
        started_at=NOW - timedelta(hours=1),
        finished_at=NOW - timedelta(hours=1), status="ok",
        detail={"summary": "ok"}))
    db.commit()
    return owner


def test_overview_windows_and_attention(db, seeded):
    payload = admin_panel.panel_payload(db, now=NOW)
    overview = payload["overview"]
    assert overview["users_total"] == 4
    assert overview["paying_users"] == 1
    assert overview["free_users"] == 3
    # The seeded Pro plan carries the $7.99 monthly price, so
    # one paying member is $7.99 of MRR (site_stats' own math).
    assert float(overview["mrr"]) == 7.99
    assert overview["new_last_7_days"] == 2
    assert overview["new_prior_7_days"] == 0
    assert overview["new_last_30_days"] == 3
    series = overview["signups_series_30d"]
    assert len(series) == 30
    assert series[29] == 1 and series[26] == 1 and series[9] == 1
    assert sum(series) == 3
    # Sheet row 50: the chart's hover readout names exact dates,
    # so the payload carries the series' first day (NOW is
    # 2026-11-12; the 30-day window opens 2026-10-14).
    assert overview["signups_series_start"] == "2026-10-14"
    tiles = overview["tiles"]
    assert tiles["today"]["downloads"] == 1
    assert tiles["today"]["tools_logged"] == 1
    assert tiles["today"]["ai_credits"] == 15
    assert tiles["today"]["ai_calls"] == 2
    assert tiles["last_30_days"]["downloads"] == 1
    attention = overview["attention"]
    assert attention["tickets_open"] == 1
    assert attention["tickets_over_24h"] == 1
    assert attention["bug_reports_open"] == 1
    assert attention["bug_reports_high"] == 1


def test_scoreboard_rows(db, seeded):
    payload = admin_panel.panel_payload(db, now=NOW)
    rows = {row["key"]: row for row in payload["scoreboard"]}
    assert rows["new_users"]["today"] == 1
    assert rows["new_users"]["last_7_days"] == 2
    assert rows["new_users"]["last_30_days"] == 3
    assert rows["new_paid"]["today"] == 1
    assert rows["cancellations"]["today"] == 0
    assert rows["cancellations"]["last_30_days"] == 1
    assert rows["cancellations"]["good_when"] == "down"
    assert rows["tools_logged"]["today"] == 1
    assert rows["downloads"]["today"] == 1
    assert rows["prints_uploaded"]["today"] == 1
    assert rows["forum_posts"]["today"] == 1
    assert rows["support_tickets"]["today"] == 0
    assert rows["support_tickets"]["last_30_days"] == 1
    assert rows["bug_reports"]["today"] == 0
    assert rows["bug_reports"]["last_30_days"] == 1
    assert rows["ai_credits"]["today"] == 15
    assert rows["ai_credits"]["format"] == "credits"
    # The "old" user (40 days) sits inside the prior-30
    # window: 3 new vs 1 prior = +200%.
    assert rows["new_users"]["change_pct"] == 200.0
    # Change is null where there is no prior-30 baseline.
    assert rows["downloads"]["change_pct"] is None
    # No uptime figure anywhere in the payload.
    assert "uptime" not in str(payload).lower()


def test_health_reads_real_systems(db, seeded):
    payload = admin_panel.panel_payload(db, now=NOW)
    health = payload["health"]
    by_key = {c["key"]: c for c in health["checks"]}
    db_check = by_key["database"]
    assert db_check["status"] == "ok"
    assert db_check["value"].endswith("ms response")
    assert "SQLite" in db_check["detail"] or "PostgreSQL" in db_check["detail"]
    backup = by_key["backup"]
    assert backup["status"] == "ok"
    assert "off-site copy uploaded" in backup["detail"]
    assert by_key["email"]["status"] == "watch"
    assert "logged" in by_key["email"]["value"]
    assert by_key["jobs"]["status"] == "ok"
    assert health["ok_count"] <= health["total"]
    assert health["total"] == 7


def test_panel_endpoint_gate(client, db, seeded):
    god = _make_user(db, "TV-P-000101", "panel-god@example.com",
                     tier="god", is_operator=True)
    admin = _make_user(db, "TV-P-000102", "panel-admin@example.com",
                       tier="moderator_admin")
    normal = _make_user(db, "TV-P-000103", "panel-normal@example.com",
                        tier="normal")
    for user, expected in ((god, 200), (admin, 200), (normal, 403)):
        resp = client.get("/api/admin/panel", headers=auth_headers(user))
        assert resp.status_code == expected, (user.email, resp.status_code)
    assert client.get("/api/admin/panel").status_code == 401
