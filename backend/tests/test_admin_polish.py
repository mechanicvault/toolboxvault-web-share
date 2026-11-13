"""Admin polish lane (owner corrections 2026-11-07): the Site
Stats fact extensions behind the widget + Site Overview
(member types, paying by plan, honest snapshot deltas), the
two new admin reports (Accounting, AI Usage), and the AI
usage recording the AI Usage report reads.

Pins:

- MEMBER TYPES: an account counts in EVERY type it holds
  (mechanic / shop / insurance from its account groups);
  "agent" counts REGISTERED agents only (owner correction
  2026-11-07): an account with its own agent profile or a
  claimed company representation. Dealer-group membership
  alone is not an agent, and private user-made agent records
  — linked or not — never count.
- PAYING BY PLAN: paying subscriptions (paid plan + active)
  split monthly vs annual per paid plan, catalog order.
- SNAPSHOT HONESTY, EXTENDED: snapshots written by the new
  code carry the new dimensions; a baseline written BEFORE
  them yields null type/plan deltas (never a backfill), while
  the tier deltas keep working off the same baseline.
- AI RECORDING: charge_for — the one door every metered
  action walks through — writes one AiUsage row per consumed
  action, free ones included, draining the transports'
  captured provider calls + token counts; a refused charge
  (insufficient credits) records nothing; a free action that
  consumed nothing records nothing.
- ACCOUNTING: figures reconcile (the Not paying column sums
  to the free count); period-end MRR comes from the daily
  snapshot when the period ends in the past, and reads "Not
  recorded" when no snapshot reaches that far.
- AI USAGE REPORT: totals and per-account sections are built
  from the metering table only; an empty period reads as an
  empty period.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.billing import ai_service, entitlements, wallet
from app.modules.billing import models as billing_models
from app.modules.core import models as core_models, site_stats
from app.modules.dealers import models as dealer_models
from app.modules.reports import admin_reports, catalog, library
from app.modules.reports.service import ReportError

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"


def _make_user(db, account_number, email, types=(MECHANIC,), tier=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=f"User {account_number}",
        password_hash="not-a-real-hash",
        account_types=list(types),
        role="user",
        is_operator=False,
    )
    if tier is not None:
        user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def god(db):
    return _make_user(db, "TV-M-000951", "ap-god@example.com", tier="god")


@pytest.fixture()
def plans(db):
    rows = {}
    for key, name, is_paid, sort_order in (
        ("free", "Free", False, 0),
        ("pro", "Pro", True, 1),
        ("business", "Business", True, 2),
    ):
        plan = billing_models.Plan(
            plan_key=key, name=name, is_paid=is_paid, sort_order=sort_order
        )
        db.add(plan)
        rows[key] = plan
    db.commit()
    entitlements.set_setting(db, "landing.pro_monthly_price", "7.99")
    entitlements.set_setting(db, "landing.pro_yearly_price", "79.99")
    entitlements.set_setting(db, "landing.business_monthly_price", "29.99")
    entitlements.set_setting(db, "landing.business_yearly_price", "299.99")
    return rows


def _sub(db, user, plan_key, status, created_days_ago, period_days=30):
    created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    sub = billing_models.Subscription(
        user_id=user.id,
        plan_key=plan_key,
        status=status,
        source="admin",
        current_period_end=created + timedelta(days=period_days),
        created_at=created,
        updated_at=created,
    )
    db.add(sub)
    db.commit()
    return sub


# -- member types + paying by plan -------------------------------------


def test_member_type_counts(db):
    _make_user(db, "TV-M-000961", "ap-m1@example.com", (MECHANIC,))
    _make_user(db, "TV-M-000962", "ap-s1@example.com", (SHOP,))
    _make_user(
        db, "TV-M-000963", "ap-multi@example.com", (MECHANIC, SHOP, DEALER)
    )
    _make_user(db, "TV-M-000964", "ap-ins@example.com", (INSURANCE,))
    _make_user(db, "TV-M-000965", "ap-d1@example.com", (DEALER,))
    profiled = _make_user(db, "TV-M-000966", "ap-a1@example.com", (MECHANIC,))
    db.add(dealer_models.AgentProfile(user_id=profiled.id, display_name="A"))
    owner = _make_user(db, "TV-M-000967", "ap-o1@example.com", (MECHANIC,))
    linked = _make_user(db, "TV-M-000968", "ap-a2@example.com", (MECHANIC,))
    company = dealer_models.DealerCompany(name="Rig Tools Co")
    db.add(company)
    db.flush()
    # User-made agent records — one plain, one LINKED to a real
    # account. Neither may move the agent count (owner ruling
    # 2026-11-07: registered agents only, not user-made agents).
    db.add(
        dealer_models.PrivateAgent(
            owner_id=owner.id, company_id=company.id, name="Typed In"
        )
    )
    db.add(
        dealer_models.PrivateAgent(
            owner_id=owner.id,
            company_id=company.id,
            name="Linked Agent",
            linked_user_id=linked.id,
        )
    )
    # A registered agent by claimed representation alone.
    claimed = _make_user(db, "TV-M-000969", "ap-a3@example.com", (DEALER,))
    db.add(
        dealer_models.CompanyRepresentation(
            agent_user_id=claimed.id, company_id=company.id
        )
    )
    # Profile AND representation on one account: still ONE agent.
    both = _make_user(db, "TV-M-000970", "ap-a4@example.com", (MECHANIC,))
    db.add(dealer_models.AgentProfile(user_id=both.id, display_name="B"))
    db.add(
        dealer_models.CompanyRepresentation(
            agent_user_id=both.id, company_id=company.id
        )
    )
    db.commit()
    counts = site_stats.users_by_member_type(db)
    # mechanic: m1, multi, profiled, owner, linked, both = 6
    # shop: s1, multi = 2 · insurance: 1
    # agent: profiled (profile), claimed (representation),
    # both (both identities, counted once) = 3.
    # NOT agent: multi + d1 (dealer group alone), owner (record
    # owner), linked (target of a user-made record).
    assert counts == {"mechanic": 6, "shop": 2, "insurance": 1, "agent": 3}
    assert claimed is not None and both is not None


def test_paying_by_plan_split(db, plans):
    monthly = _make_user(db, "TV-M-000971", "ap-pm@example.com")
    annual = _make_user(db, "TV-M-000972", "ap-pa@example.com")
    biz = _make_user(db, "TV-M-000973", "ap-bm@example.com")
    past_due = _make_user(db, "TV-M-000974", "ap-pd@example.com")
    _sub(db, monthly, "pro", "active", 40, 30)
    _sub(db, annual, "pro", "active", 300, 365)
    _sub(db, biz, "business", "active", 20, 30)
    _sub(db, past_due, "pro", "past_due", 10, 30)
    rows = site_stats.paying_by_plan(db)
    assert rows == [
        {"plan_key": "pro", "name": "Pro", "monthly": 1, "annual": 1, "total": 2},
        {
            "plan_key": "business",
            "name": "Business",
            "monthly": 1,
            "annual": 0,
            "total": 1,
        },
    ]


# -- snapshot deltas -----------------------------------------------------


def _snapshot(db, day, payload):
    row = core_models.SiteStatsSnapshot(day=day, payload=payload)
    db.add(row)
    db.commit()
    return row


def test_snapshot_deltas_honest_for_old_and_new_baselines(db, plans):
    _make_user(db, "TV-M-000981", "ap-snap@example.com", (SHOP,))
    yesterday = date.today() - timedelta(days=1)
    old_payload = {
        "day": yesterday.isoformat(),
        "users_total": 0,
        "users_by_tier": {
            "god": 0, "moderator_admin": 0, "moderator": 0, "normal": 0,
        },
        "free_users": 0,
        "paying_users": 0,
        "mrr": "0.00",
        "tools_total": 0,
        "new_users": 0,
        "new_paid": 0,
        "tools_logged": 0,
    }
    _snapshot(db, yesterday, old_payload)
    block = site_stats._site_block(db)
    assert block["tier_deltas"] is not None
    assert block["type_deltas"] is None
    assert block["plan_deltas"] is None

    new_payload = dict(old_payload)
    new_payload["users_by_type"] = {
        "mechanic": 0, "shop": 0, "insurance": 0, "agent": 0,
    }
    new_payload["paying_by_plan"] = [
        {"plan_key": "pro", "name": "Pro", "monthly": 0, "annual": 0, "total": 0}
    ]
    row = db.scalars(select(core_models.SiteStatsSnapshot)).first()
    row.payload = new_payload
    db.commit()
    block = site_stats._site_block(db)
    assert block["type_deltas"]["shop"] == 1
    assert block["type_deltas"]["mechanic"] == 0
    assert block["plan_deltas"]["pro"] == {
        "monthly": 0, "annual": 0, "total": 0,
    }


def test_snapshot_writes_new_dimensions(db, plans):
    _make_user(db, "TV-M-000982", "ap-snap2@example.com", (INSURANCE,))
    row = site_stats.snapshot_day(db)
    assert row.payload["users_by_type"]["insurance"] == 1
    assert "paying_by_plan" in row.payload


def test_widget_payload_carries_new_dimensions(client, db, god):
    from tests.conftest import auth_headers

    resp = client.get("/api/admin/home-widgets", headers=auth_headers(god))
    assert resp.status_code == 200
    site = resp.json()["site"]
    assert set(site["users_by_type"]) == {
        "mechanic", "shop", "insurance", "agent",
    }
    assert isinstance(site["paying_by_plan"], list)
    assert "type_deltas" in site and "plan_deltas" in site


# -- AI usage recording ---------------------------------------------------


def _configure_ai(db, monkeypatch, provider="openai"):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, provider)
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "POLISH_TEST_KEY")
    monkeypatch.setenv("POLISH_TEST_KEY", "key-not-real")
    db.commit()


def _usage_rows(db):
    return list(db.scalars(select(billing_models.AiUsage)).all())


def test_recording_free_action_with_tokens(db, monkeypatch):
    user = _make_user(db, "TV-M-000991", "ap-ai1@example.com")
    _configure_ai(db, monkeypatch)
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    ai_service.begin_usage_capture()
    ai_service.complete_json(db, "prompt")
    charged = ai_service.charge_for(
        db, user.id, "identify", subject="a red wrench"
    )
    assert charged == 0
    rows = _usage_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "identify"
    assert row.subject == "a red wrench"
    assert row.provider == "openai"
    assert row.model == "test-model"
    assert row.calls == 1
    assert row.tokens_in == 10
    assert row.tokens_out == 4
    assert row.credits_charged == 0


def test_recording_priced_action_and_search_tokens(db, monkeypatch):
    user = _make_user(db, "TV-M-000992", "ap-ai2@example.com")
    _configure_ai(db, monkeypatch)
    entitlements.set_setting(db, "ai.lookup_price", 3)
    wallet.credit(
        db, user.id, amount=10, bucket="banked", reason="grant", ref="test"
    )
    body = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "x",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/m.pdf",
                                "title": "M",
                            }
                        ],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 5, "output_tokens": 1},
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    ai_service.begin_usage_capture()
    ai_service.web_search(db, "StubBrand SW-1")
    charged = ai_service.charge_for(db, user.id, "lookup", subject="SW-1")
    assert charged == 3
    rows = _usage_rows(db)
    assert len(rows) == 1
    assert rows[0].tokens_in == 5
    assert rows[0].tokens_out == 1
    assert rows[0].credits_charged == 3


def test_recording_anthropic_usage_shape(db, monkeypatch):
    user = _make_user(db, "TV-M-000993", "ap-ai3@example.com")
    _configure_ai(db, monkeypatch, provider="anthropic")
    body = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 7, "output_tokens": 2},
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    ai_service.begin_usage_capture()
    ai_service.complete(db, "prompt")
    ai_service.charge_for(db, user.id, "report_summary", subject="Inventory")
    rows = _usage_rows(db)
    assert len(rows) == 1
    assert rows[0].provider == "anthropic"
    assert rows[0].tokens_in == 7
    assert rows[0].tokens_out == 2


def test_recording_refusals_and_noops_write_nothing(db, monkeypatch):
    user = _make_user(db, "TV-M-000994", "ap-ai4@example.com")
    _configure_ai(db, monkeypatch)
    # A free action that consumed nothing records nothing.
    assert ai_service.charge_for(db, user.id, "identify") == 0
    assert _usage_rows(db) == []
    # A charge the wallet refuses records nothing either.
    entitlements.set_setting(db, "ai.identify_price", 50)
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    ai_service.begin_usage_capture()
    ai_service.complete_json(db, "prompt")
    with pytest.raises(wallet.InsufficientCredits):
        ai_service.charge_for(db, user.id, "identify", subject="x")
    assert _usage_rows(db) == []


# -- the Accounting report --------------------------------------------------


def test_accounting_report_figures(db, god, plans):
    payer_m = _make_user(db, "TV-M-001001", "ap-am@example.com")
    payer_a = _make_user(db, "TV-M-001002", "ap-aa@example.com")
    past_due = _make_user(db, "TV-M-001003", "ap-apd@example.com")
    canceled = _make_user(db, "TV-M-001004", "ap-ac@example.com")
    _make_user(db, "TV-M-001005", "ap-af@example.com")  # free, no row
    _sub(db, payer_m, "pro", "active", 10, 30)
    _sub(db, payer_a, "pro", "active", 300, 365)
    _sub(db, past_due, "pro", "past_due", 5, 30)
    _sub(db, canceled, "pro", "canceled", 5, 30)
    start = (date.today() - timedelta(days=400)).isoformat()
    doc = admin_reports.build_accounting(
        db, god, {"start": start, "end": date.today().isoformat()}
    )
    sections = {s["label"]: s for s in doc["sections"]}
    plan_rows = {
        row[0]: row for row in sections["Accounts by plan (today)"]["rows"]
    }
    # Pro: 2 paying (monthly 7.99 + annual 79.99/12=6.67 = 14.66),
    # 2 not paying (past due + canceled).
    assert plan_rows["Pro"][1:] == ["2", "2", "$14.66"]
    # Free: accounts with no paid-plan row = god + the free user.
    assert plan_rows["Free"][1] == "0"
    assert plan_rows["Free"][2] == "2"
    states = {
        row[0]: row[1]
        for row in sections["Subscription states (today)"]["rows"]
    }
    assert states["Active"] == "2"
    assert states["Past due"] == "1"
    assert states["Canceled (current state)"] == "1"
    assert states["No subscription (free)"] == "2"
    period_rows = {row[0]: row for row in doc["sections"][2]["rows"]}
    assert period_rows["New paying accounts"][1] == "4"
    assert period_rows["New paying — Pro"][1] == "4"


def test_accounting_period_end_mrr_snapshot_and_gap(db, god, plans):
    snapshot_day_ = date.today() - timedelta(days=3)
    _snapshot(
        db,
        snapshot_day_,
        {"day": snapshot_day_.isoformat(), "mrr": "10.00"},
    )
    doc = admin_reports.build_accounting(
        db,
        god,
        {
            "start": (snapshot_day_ - timedelta(days=30)).isoformat(),
            "end": snapshot_day_.isoformat(),
        },
    )
    mrr_rows = {
        row[0]: row[1] for row in doc["sections"][3]["rows"]
    }
    end_label = f"MRR at period end ({snapshot_day_.strftime('%b %d, %Y')})"
    assert mrr_rows[end_label].startswith("$10.00 (daily snapshot,")
    gap_day = snapshot_day_ - timedelta(days=1)
    doc = admin_reports.build_accounting(
        db,
        god,
        {
            "start": (gap_day - timedelta(days=30)).isoformat(),
            "end": gap_day.isoformat(),
        },
    )
    mrr_rows = {row[0]: row[1] for row in doc["sections"][3]["rows"]}
    gap_label = f"MRR at period end ({gap_day.strftime('%b %d, %Y')})"
    assert mrr_rows[gap_label] == "Not recorded"


# -- the AI Usage report -----------------------------------------------------


def test_ai_usage_report_from_ledger(db, god):
    user_a = _make_user(db, "TV-M-001011", "ap-ua@example.com")
    user_b = _make_user(db, "TV-M-001012", "ap-ub@example.com")
    now = datetime.now(timezone.utc)

    def usage(user, action, subject, tin, tout, credits, when):
        db.add(
            billing_models.AiUsage(
                user_id=user.id,
                action=action,
                subject=subject,
                provider="openai",
                model="test-model",
                calls=1,
                tokens_in=tin,
                tokens_out=tout,
                credits_charged=credits,
                created_at=when,
            )
        )

    usage(user_a, "identify", "a wrench", 100, 20, 5, now)
    usage(user_a, "manual_lookup", "Milwaukee 2853-20", 50, 10, 0, now)
    usage(user_b, "identify", "Photo: X", 200, 40, 5, now)
    usage(user_b, "identify", "old", 999, 999, 9, now - timedelta(days=90))
    db.commit()
    doc = admin_reports.build_ai_usage(
        db,
        god,
        {
            "start": (date.today() - timedelta(days=7)).isoformat(),
            "end": date.today().isoformat(),
        },
    )
    totals = {row[0]: row[1] for row in doc["sections"][0]["rows"]}
    assert totals["AI actions recorded"] == "3"
    assert totals["Tokens in"] == "350"
    assert totals["Tokens out"] == "70"
    assert totals["Wallet credits charged"] == "10"
    assert totals["Accounts that used AI"] == "2"
    labels = [s["label"] for s in doc["sections"]]
    assert any(label.startswith("User TV-M-001011") for label in labels)
    assert any(label.startswith("User TV-M-001012") for label in labels)
    assert "recording began" in doc["subtitle"]

    empty = admin_reports.build_ai_usage(
        db, god, {"start": "2020-01-01", "end": "2020-01-31"}
    )
    assert empty["sections"][1]["rows"][0][0] == (
        "No AI usage was recorded in this period."
    )


def test_site_overview_new_sections(db, god, plans):
    payer = _make_user(db, "TV-M-001021", "ap-so@example.com", (SHOP,))
    _sub(db, payer, "pro", "active", 300, 365)
    doc = admin_reports.build_site_stats(db, god, {})
    labels = [s["label"] for s in doc["sections"]]
    assert "Members by type" in labels
    types = {
        row[0]: row[1]
        for row in doc["sections"][labels.index("Members by type")]["rows"]
    }
    assert types["Shop"] == "1"
    assert types["Mechanic"] == "1"  # the god owner fixture
    plan_rows = [row[0] for row in doc["sections"][labels.index("Plans")]["rows"]]
    assert "Pro — monthly" in plan_rows
    assert "Pro — annual" in plan_rows
    assert "in every type it holds" in doc["subtitle"]


def test_new_admin_types_catalog_shape():
    assert "admin_accounting" not in catalog.TYPES
    assert "admin_ai_usage" not in catalog.TYPES
    assert catalog.ADMIN_TYPES["admin_accounting"]["settings"] == "period"
    assert catalog.ADMIN_TYPES["admin_ai_usage"]["settings"] == "period"
    cleaned = library.validate_settings(
        "admin_accounting", {"start": "2026-01-01", "end": "2026-01-31"}
    )
    assert cleaned == {"start": "2026-01-01", "end": "2026-01-31"}
    with pytest.raises(ReportError):
        library.validate_settings(
            "admin_ai_usage", {"start": "2026-02-01", "end": "2026-01-31"}
        )
