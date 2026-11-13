"""Admin lane (owner program 2026-11-06 23:14 + 23:26): the
five admin Home widgets' data door, the daily Site Stats
snapshot, Admin Reports, and the platform-fee setting.

Pins:

- WIDGET DOOR: GET /api/admin/home-widgets answers god +
  moderator_admin seats (200, the five blocks) and refuses
  moderator + normal seats outright (403) — the full bag never
  travels to a lower tier.
- SNAPSHOT HONESTY: with no earlier snapshot the site block's
  deltas are null (no baseline, never fabricated); after a
  snapshot exists for an earlier day, deltas read
  now-minus-that-day. The daily job refreshes today's row
  instead of duplicating it.
- ADMIN REPORTS: the catalog carries admin_types ONLY for
  admin seats (a member's response has no such field, and no
  admin key ever appears in the user types list); generating,
  describing or templating an admin type refuses non-admins
  (403); admin templates are forced into the "admin" area;
  the datasets render in all three formats through the shared
  library door.
- PLATFORM FEE: the truck agreement's fee line reads the
  payments.truck_fee_percent setting — unset and 0 both read
  "no platform fee"; a set percent is disclosed; the admin
  settings write path validates 0–100.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
from app.modules.core import models as core_models, site_stats
from app.modules.reports import library
from app.modules.truck_accounts import agreement
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(
    db,
    account_number,
    email,
    name="Admin Lane User",
    role="user",
    tier=None,
    is_operator=False,
):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role=role,
        is_operator=is_operator,
    )
    if tier is not None:
        user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def god(db):
    return _make_user(
        db, "TV-M-000901", "al-god@example.com", "Gail God",
        role="community_admin", tier="god", is_operator=True,
    )


@pytest.fixture()
def mod_admin(db):
    return _make_user(
        db, "TV-M-000902", "al-modadmin@example.com", "Adam Admin",
        role="community_admin", tier="moderator_admin",
    )


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000903", "al-mod@example.com", "Maude Mod",
        role="moderator", tier="moderator",
    )


@pytest.fixture()
def member(db):
    return _make_user(
        db, "TV-M-000904", "al-member@example.com", "Ned Normal"
    )


# -- the widget door ---------------------------------------------------


def test_home_widgets_door(client, god, mod_admin, moderator, member):
    for seat in (god, mod_admin):
        response = client.get(
            "/api/admin/home-widgets", headers=auth_headers(seat)
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert set(payload) == {
            "tickets",
            "bug_reports",
            "feature_requests",
            "forum_moderator",
            "site",
        }
    for seat in (moderator, member):
        response = client.get(
            "/api/admin/home-widgets", headers=auth_headers(seat)
        )
        assert response.status_code == 403, response.text


def test_home_widgets_site_block_counts(client, db, god, member):
    response = client.get(
        "/api/admin/home-widgets", headers=auth_headers(god)
    )
    site = response.json()["site"]
    # god + member exist, both normal-or-higher seats counted.
    assert site["users_total"] == 2
    assert site["users_by_tier"]["god"] == 1
    assert site["users_by_tier"]["normal"] == 1
    assert site["paying_users"] == 0
    assert site["free_users"] == 2
    assert site["mrr"] == "0.00"
    assert site["new_users"] == 2


def test_snapshot_deltas_honest_without_baseline(db, god, member):
    payload = site_stats.home_widgets_payload(db)
    assert payload["site"]["baseline_day"] is None
    assert payload["site"]["tier_deltas"] is None
    assert payload["site"]["paying_delta"] is None


def test_snapshot_job_and_deltas(db, god, member):
    yesterday = date.today() - timedelta(days=1)
    row = site_stats.snapshot_day(db, yesterday)
    assert row.day == yesterday
    assert row.payload["users_total"] == 2
    # A second member arrives today; deltas read now-minus-yesterday.
    _make_user(db, "TV-M-000905", "al-late@example.com", "Late Arrival")
    payload = site_stats.home_widgets_payload(db)
    assert payload["site"]["baseline_day"] == yesterday.isoformat()
    assert payload["site"]["tier_deltas"]["normal"] == 1
    assert payload["site"]["tier_deltas"]["god"] == 0
    # The daily job refreshes today's row — running it twice
    # still leaves exactly one row for today.
    site_stats.run_daily_snapshot(db)
    site_stats.run_daily_snapshot(db)
    rows = list(
        db.scalars(
            select(core_models.SiteStatsSnapshot).where(
                core_models.SiteStatsSnapshot.day == date.today()
            )
        )
    )
    assert len(rows) == 1
    assert rows[0].payload["users_total"] == 3


# -- admin reports -------------------------------------------------------


def test_catalog_admin_types_admin_seats_only(client, god, member):
    member_payload = client.get(
        "/api/reports/catalog", headers=auth_headers(member)
    ).json()
    assert "admin_types" not in member_payload
    assert not any(
        t["key"].startswith("admin_") for t in member_payload["types"]
    )
    god_payload = client.get(
        "/api/reports/catalog", headers=auth_headers(god)
    ).json()
    assert {t["key"] for t in god_payload["admin_types"]} == {
        "admin_site_stats",
        "admin_users",
        "admin_inventory",
        "admin_payments",
        "admin_revenue_year",
        "admin_revenue_quarter",
        # Admin polish lane (2026-11-07): the Accounting and
        # AI Usage reports joined the admin catalog.
        "admin_accounting",
        "admin_ai_usage",
    }
    assert not any(
        t["key"].startswith("admin_") for t in god_payload["types"]
    )


def test_admin_generate_refused_for_member(client, member):
    response = client.post(
        "/api/reports/generate",
        json={"report_type": "admin_users", "settings": {}, "format": "csv"},
        headers=auth_headers(member),
    )
    assert response.status_code == 403, response.text
    described = client.post(
        "/api/reports/describe",
        json={"report_type": "admin_users", "settings": {}},
        headers=auth_headers(member),
    )
    assert described.status_code == 403, described.text
    templated = client.post(
        "/api/reports/templates",
        json={"report_type": "admin_users", "settings": {}},
        headers=auth_headers(member),
    )
    assert templated.status_code == 403, templated.text


def test_admin_template_area_forced_and_generation(
    client, db, god, member
):
    created = client.post(
        "/api/reports/templates",
        json={
            "report_type": "admin_users",
            "name": "Directory snapshot",
            "area": "quick",
            "settings": {"format": "csv"},
        },
        headers=auth_headers(god),
    )
    assert created.status_code == 201, created.text
    assert created.json()["area"] == "admin"

    content = library.generate_bytes(
        db, god, "admin_users", {}, "csv"
    )
    text = content.decode("utf-8-sig")
    assert "User directory" in text
    assert "al-god@example.com" in text
    assert "al-member@example.com" in text
    pdf = library.generate_bytes(db, god, "admin_site_stats", {}, "pdf")
    assert pdf.startswith(b"%PDF")
    xlsx = library.generate_bytes(
        db, god, "admin_revenue_year", {"year": 2026}, "xlsx"
    )
    assert xlsx.startswith(b"PK")


def test_admin_datasets_reflect_reality(db, god, member):
    doc_csv = library.generate_bytes(
        db, god, "admin_revenue_year", {"year": 2026}, "csv"
    ).decode("utf-8-sig")
    assert "Revenue by month" in doc_csv
    assert "January" in doc_csv and "December" in doc_csv
    payments = library.generate_bytes(
        db, god, "admin_payments", {}, "csv"
    ).decode("utf-8-sig")
    assert "Payment accounts" in payments
    assert "Free" in payments


# -- the platform fee -----------------------------------------------------


def test_platform_fee_setting_reads_through(db):
    # Unset reads as the decided posture: no platform fee.
    assert "no platform fee" in agreement.fee_disclosure_line(db)
    entitlements.set_setting(db, agreement.TRUCK_FEE_PERCENT_KEY, 0)
    assert "no platform fee" in agreement.fee_disclosure_line(db)
    entitlements.set_setting(db, agreement.TRUCK_FEE_PERCENT_KEY, 2.5)
    line = agreement.fee_disclosure_line(db)
    assert "2.5%" in line
    entitlements.set_setting(db, agreement.TRUCK_FEE_PERCENT_KEY, 0)
    assert "no platform fee" in agreement.fee_disclosure_line(db)


def test_platform_fee_admin_write_validates(client, god):
    ok = client.put(
        "/api/admin/settings",
        json={"payments_truck_fee_percent": 0},
        headers=auth_headers(god),
    )
    assert ok.status_code == 200, ok.text
    bad = client.put(
        "/api/admin/settings",
        json={"payments_truck_fee_percent": 140},
        headers=auth_headers(god),
    )
    assert bad.status_code == 422, bad.text
