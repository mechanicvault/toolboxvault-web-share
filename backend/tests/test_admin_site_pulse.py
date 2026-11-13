"""Site pulse (sweep lane D4, owner idea 5): the Admin → Site
pulse page's one aggregate endpoint.

Pins:

- GATE: GET /api/admin/site-pulse answers operator seats only
  (200). Moderator admin, moderator, normal and downloads seats
  are refused outright (403) and anonymous callers get 401 —
  the numbers never travel to a non-operator seat.
- WINDOW MATH (fixed clock, rows planted on the boundaries):
  today = since 00:00 UTC; last 7 days = today + the six days
  before; last 30 days likewise. A row at exactly a window's
  start counts; a row one second before it does not.
- SOURCES: signups count users.created_at; downloads count
  download_events rows; print windows count LIVE listings only
  and the total is live-only; AI sums the ai_usage calls /
  credits columns (cost = wallet credits charged) with the
  per-action split over the last 30 days; the tier split is
  the active-accounts-by-resolved-rung state fact.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from app.modules.billing import models as billing_models
from app.modules.core import models as core_models, site_pulse
from app.modules.downloads import models as downloads_models
from app.modules.prints import models as prints_models
from app.modules.support import models as support_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)
TODAY = datetime.combine(NOW.date(), time.min, tzinfo=timezone.utc)


def _make_user(db, account_number, email, tier=None, is_operator=False,
               role="user", created_at=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Pulse User",
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
def god(db):
    return _make_user(
        db, "TV-M-002001", "pulse-god@example.com",
        role="community_admin", tier="god", is_operator=True,
    )


@pytest.fixture()
def mod_admin(db):
    return _make_user(
        db, "TV-M-002002", "pulse-modadmin@example.com",
        role="community_admin", tier="moderator_admin",
    )


@pytest.fixture()
def member(db):
    return _make_user(db, "TV-M-002003", "pulse-member@example.com")


@pytest.fixture()
def rung(db):
    return _make_user(
        db, "TV-M-002004", "pulse-rung@example.com", tier="downloads"
    )


# -- the gate ----------------------------------------------------------


def test_site_pulse_gate(client, god, mod_admin, member, rung):
    response = client.get("/api/admin/site-pulse", headers=auth_headers(god))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "generated_at", "signups", "downloads", "prints", "ai", "attention",
    }
    for seat in (mod_admin, member, rung):
        response = client.get(
            "/api/admin/site-pulse", headers=auth_headers(seat)
        )
        assert response.status_code == 403, response.text
    response = client.get("/api/admin/site-pulse")
    assert response.status_code == 401, response.text


# -- window math ---------------------------------------------------------


def _seed_windows(db, god):
    """Rows planted on the window boundaries relative to NOW."""
    # Signups: 1 today, 1 six days ago (inside 7d), 1 seven days
    # ago (outside 7d, inside nothing else we window signups by).
    _make_user(db, "TV-M-002011", "pulse-s1@example.com", created_at=NOW)
    _make_user(
        db, "TV-M-002012", "pulse-s2@example.com",
        created_at=TODAY - timedelta(days=6),
    )
    _make_user(
        db, "TV-M-002013", "pulse-s3@example.com",
        created_at=TODAY - timedelta(days=7),
    )
    # Downloads: a file row the events can point at, then events
    # today / 3 days ago / 40 days ago.
    db.add(
        downloads_models.DownloadFile(
            key="pulse-doc", file_format="pdf", filename="pulse.pdf",
            storage_key="pulse/pulse.pdf",
        )
    )
    for when in (NOW, TODAY - timedelta(days=3), TODAY - timedelta(days=40)):
        db.add(downloads_models.DownloadEvent(file_key="pulse-doc",
                                               created_at=when))
    # Prints: live today, live 2 days ago, live 20 days ago, and
    # a REMOVED one today (never counted).
    for i, (status, when) in enumerate([
        ("live", NOW),
        ("live", TODAY - timedelta(days=2)),
        ("live", TODAY - timedelta(days=20)),
        ("removed", NOW),
    ]):
        db.add(
            prints_models.PrintFile(
                publisher_id=god.id, title=f"Pulse print {i}",
                category_key="toolbox", status=status, created_at=when,
            )
        )
    # AI: today (2 actions), 10 days ago (inside 30d only),
    # 30 days ago at the boundary start (inside), 31 days ago
    # (outside).
    def usage(action, calls, credits, when):
        db.add(
            billing_models.AiUsage(
                user_id=god.id, action=action, subject="x",
                provider="openai", model="test", calls=calls,
                tokens_in=10, tokens_out=5, credits_charged=credits,
                created_at=when,
            )
        )

    usage("lookup", 2, 3, NOW)
    usage("identify", 1, 4, NOW)
    usage("lookup", 5, 6, TODAY - timedelta(days=10))
    usage("manual_lookup", 7, 8, TODAY - timedelta(days=29))
    usage("lookup", 11, 12, TODAY - timedelta(days=30))
    # Support: one open + one under_review waiting, one closed.
    for status in ("open", "under_review", "closed"):
        db.add(
            support_models.SupportTicket(
                user_id=god.id, subject=f"ticket {status}", status=status,
            )
        )
    db.commit()


def test_site_pulse_window_math(db, god):
    _seed_windows(db, god)
    payload = site_pulse.pulse_payload(db, now=NOW)

    signups = payload["signups"]
    # god (created by the fixture at the real clock, which is
    # also 2026-11-12) + the 3 planted signups.
    assert signups["today"] == 2
    assert signups["last_7_days"] == 3
    assert signups["total"] == 4
    assert signups["by_tier_now"]["god"] == 1
    assert signups["by_tier_now"]["normal"] == 3

    downloads = payload["downloads"]
    assert downloads == {"today": 1, "last_7_days": 2, "total": 3}

    prints = payload["prints"]
    assert prints == {"today": 1, "last_7_days": 2, "total_live": 3}

    ai = payload["ai"]
    assert ai["today"] == {
        "actions": 2, "calls": 3, "credits_charged": 7,
        "tokens_in": 20, "tokens_out": 10,
    }
    assert ai["last_7_days"] == ai["today"]
    assert ai["last_30_days"]["actions"] == 4
    assert ai["last_30_days"]["calls"] == 2 + 1 + 5 + 7
    assert ai["last_30_days"]["credits_charged"] == 3 + 4 + 6 + 8
    by_action = {row["action"]: row for row in ai["by_action_last_30_days"]}
    assert by_action["lookup"]["actions"] == 2
    assert by_action["lookup"]["credits_charged"] == 3 + 6
    assert by_action["identify"]["calls"] == 1
    assert by_action["manual_lookup"]["calls"] == 7

    assert payload["attention"]["support_tickets_waiting"] == 2
    assert payload["attention"]["announcements_sent_total"] == 0
