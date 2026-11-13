"""Home header-stats catalog (Lane 3, owner design 2026-11-10):
the stats moved from the retired stats widget into the Home
header, and the catalog is enumerated SERVER-side from the
caller's effective reach — the picker never lists a stat outside
the caller's reach.

Pins:
- a mechanic's catalog carries his modules' stats and NO staff
  stats (they do not exist as far as his picker is concerned);
- god and moderator_admin seats DO carry the staff stats, and the
  payload's server-computed values are correct;
- "New members today" counts the America/Chicago calendar day,
  not the UTC day (a signup late in the Chicago evening is
  already tomorrow in UTC and still counts);
- the downloads rung's catalog is exactly its reach: prints,
  downloads, support, feedback, account — no group-gated stats,
  no staff stats;
- a dealer seat gets the dealer stats and no inventory stats;
- signed-out callers get 401.
"""

import uuid
from datetime import datetime, timezone

from app.modules.billing import models as billing_models
from app.modules.core import header_stats
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, email, *, types=(), tier="normal", created_at=None, **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-H-{uuid.uuid4().hex[:6]}",
        email=email,
        name="Header Stats User",
        password_hash="not-a-real-hash",
        account_types=list(types),
        tier=tier,
        **kw,
    )
    if created_at is not None:
        user.created_at = created_at
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get(client, user):
    response = client.get("/api/core/header-stats", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def test_mechanic_catalog_has_his_stats_and_no_staff_stats(client, db):
    user = _make_user(db, "mech@example.com", types=[MECHANIC])
    payload = _get(client, user)
    available = payload["available"]
    for key in (
        "inventory.total_items",
        "inventory.total_market_value",
        "borrowing.checked_out",
        "claims.open_claims",
        "maintenance.maintenance_due",
        "truck_accounts.total_owed",
        "support.open_tickets",
        "downloads.documents",
        "prints.listings",
        "account.plan_items",
    ):
        assert key in available, key
    # Staff stats do not exist for a mechanic's picker.
    assert not any(key.startswith("admin.") for key in available)
    assert "values" not in payload
    # Dealer-group stats are not his either.
    assert "dealers.preferred_by" not in available


def test_catalog_follows_the_users_own_module_switches(client, db):
    # The per-user layer of the one gate: a module the user has
    # switched off for themselves loses its stats too.
    user = _make_user(db, "off@example.com", types=[MECHANIC])
    db.add(
        core_models.UserModulePref(
            id=uuid.uuid4(), user_id=user.id, module_id="claims",
            enabled=False,
        )
    )
    db.commit()
    available = _get(client, user)["available"]
    assert "claims.open_claims" not in available
    assert "inventory.total_items" in available


def test_god_catalog_is_the_whole_catalog_with_values(client, db):
    god = _make_user(db, "god@example.com", types=[MECHANIC], tier="god")
    payload = _get(client, god)
    assert payload["available"] == list(header_stats.CATALOG_KEYS)
    assert payload["values"]["admin.new_members_today"] >= 1
    assert payload["values"]["admin.ai_actions_today"] == 0


def test_moderator_admin_gets_staff_stats_plain_moderator_does_not(client, db):
    admin = _make_user(
        db, "modadmin@example.com", types=[MECHANIC], tier="moderator_admin"
    )
    payload = _get(client, admin)
    assert "admin.new_members_today" in payload["available"]
    assert "values" in payload

    moderator = _make_user(
        db, "mod@example.com", types=[MECHANIC], tier="moderator"
    )
    payload = _get(client, moderator)
    assert not any(k.startswith("admin.") for k in payload["available"])
    assert "values" not in payload


def test_downloads_rung_catalog_is_exactly_its_reach(client, db):
    # Mirror production's tier cells (migration 0096's seed, plus
    # feedback lit for the rung since): the downloads key is
    # opt-in only, so the cells must exist to read at all. Full
    # cell sets per module, as the migration materializes them.
    for module_id in ("prints", "support", "feedback"):
        for tier_key in ("normal", "moderator", "moderator_admin",
                         "beta", "downloads"):
            db.add(
                core_models.ModuleTierAccess(
                    id=uuid.uuid4(), module_id=module_id,
                    tier=tier_key, enabled=True,
                )
            )
    db.commit()
    rung = _make_user(db, "rung@example.com", types=[], tier="downloads")
    payload = _get(client, rung)
    assert payload["available"] == [
        "support.open_tickets",
        "feedback.my_posts",
        "downloads.documents",
        "downloads.wallpapers",
        "downloads.total_downloads",
        "prints.listings",
        "prints.downloads",
        "prints.my_uploads",
        "prints.my_downloads",
        "account.plan_items",
    ]
    assert "values" not in payload


def test_dealer_catalog(client, db):
    dealer = _make_user(db, "dealer@example.com", types=[DEALER])
    available = _get(client, dealer)["available"]
    for key in (
        "dealers.preferred_by",
        "dealers.companies_represented",
        "dealers.my_agents",
        "truck_accounts.total_owed",
    ):
        assert key in available, key
    assert "inventory.total_items" not in available
    assert "claims.open_claims" not in available


# "Now" for the day-count tests: 2026-11-10 23:45 in Chicago
# (CST, UTC-6) = 2026-11-11 05:45 UTC. The Chicago day Nov 10
# spans [Nov 10 06:00 UTC, Nov 11 06:00 UTC); the UTC day at the
# same moment is Nov 11 — the two calendars disagree, which is
# what makes the rows below discriminating.
NOW_CT = datetime(2026, 11, 11, 5, 45, tzinfo=timezone.utc)
IN_CHICAGO_DAY = (
    datetime(2026, 11, 10, 6, 30, tzinfo=timezone.utc),   # Nov 10 00:30 CT
    datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc),  # Nov 10 17:30 CT
    datetime(2026, 11, 11, 5, 30, tzinfo=timezone.utc),   # Nov 10 23:30 CT
)
OUT_CHICAGO_DAY = (
    datetime(2026, 11, 10, 5, 30, tzinfo=timezone.utc),   # Nov 9 23:30 CT
    datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc),   # Nov 11 17:00 CT
)


def test_new_members_today_counts_the_chicago_day(db):
    for i, stamp in enumerate(IN_CHICAGO_DAY + OUT_CHICAGO_DAY):
        _make_user(db, f"day{i}@example.com", created_at=stamp)
    # A UTC-day count at the same moment would find only 2 of
    # these (the Nov 10 23:30 CT row and the Nov 11 17:00 CT row).
    assert header_stats.new_members_today(db, now=NOW_CT) == 3


def test_ai_actions_today_counts_the_chicago_day(db):
    user = _make_user(db, "ai@example.com")
    for stamp in IN_CHICAGO_DAY + OUT_CHICAGO_DAY:
        db.add(
            billing_models.AiUsage(
                id=uuid.uuid4(),
                user_id=user.id,
                action="lookup",
                created_at=stamp,
            )
        )
    db.commit()
    assert header_stats.ai_actions_today(db, now=NOW_CT) == 3


def test_header_stats_requires_sign_in(client):
    response = client.get("/api/core/header-stats")
    assert response.status_code == 401
