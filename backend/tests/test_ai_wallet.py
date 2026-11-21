"""AI credit wallet (billing, Phase A1; spec ai-token-system.md):
two buckets (monthly allowance, no rollover; banked, persists),
spend drains allowance first, every movement lands in the ledger,
and the monthly refill is idempotent. The wallet works regardless
of the AI module's assignment — credits can bank ahead of launch.
"""

import uuid

import pytest

from app.modules.billing import models as billing_models
from app.modules.billing import wallet
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _seed_plans(db):
    db.add_all(
        [
            billing_models.Plan(
                plan_key="free", name="Free", item_limit=20,
                ai_monthly_credits=0, is_paid=False, sort_order=0,
            ),
            billing_models.Plan(
                plan_key="pro", name="Pro", item_limit=None,
                ai_monthly_credits=100, is_paid=True, sort_order=1,
            ),
        ]
    )
    db.commit()


def _make_user(db, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-M-{uuid.uuid4().hex[:6]}",
        email=email,
        name="Wallet User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user(db):
    return _make_user(db, "wallet@example.com")


def test_wallet_starts_empty_and_view_shape(db, user, client):
    view = wallet.wallet_view(db, user.id)
    assert view["allowance_balance"] == 0
    assert view["banked_balance"] == 0
    assert view["total_balance"] == 0
    assert view["ledger"] == []
    resp = client.get("/api/billing/ai-wallet", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["total_balance"] == 0


def test_credit_buckets_and_ledger(db, user):
    wallet.credit(db, user.id, amount=10, bucket="banked", reason="grant", ref="op-1")
    wallet.credit(db, user.id, amount=5, bucket="allowance", reason="admin_adjust")
    view = wallet.wallet_view(db, user.id)
    assert view["banked_balance"] == 10
    assert view["allowance_balance"] == 5
    assert [row["reason"] for row in view["ledger"]] == ["admin_adjust", "grant"]
    assert view["ledger"][0]["bucket_balance_after"] == 5


def test_spend_drains_allowance_first(db, user):
    wallet.credit(db, user.id, amount=10, bucket="banked", reason="grant")
    wallet.credit(db, user.id, amount=10, bucket="allowance", reason="admin_adjust")
    wallet.spend(db, user.id, amount=14, ref="identify_item")
    view = wallet.wallet_view(db, user.id)
    assert view["allowance_balance"] == 0
    assert view["banked_balance"] == 6
    spends = [r for r in view["ledger"] if r["reason"] == "spend"]
    # Same-instant movements order allowance-before-banked (the
    # wallet_view tiebreak), matching the drain order.
    assert [(r["bucket"], r["delta"]) for r in spends] == [
        ("allowance", -10),
        ("banked", -4),
    ]


def test_spend_beyond_balance_refused(db, user):
    wallet.credit(db, user.id, amount=3, bucket="banked", reason="grant")
    with pytest.raises(wallet.InsufficientCredits):
        wallet.spend(db, user.id, amount=4)
    # The refusal leaves the wallet untouched.
    assert wallet.wallet_view(db, user.id)["banked_balance"] == 3


def test_refill_sets_plan_allowance_without_rollover(db, user):
    from app.modules.billing import entitlements

    entitlements.create_grant(db, user.id, plan_key="pro", kind="lifetime")
    wallet.credit(db, user.id, amount=40, bucket="allowance", reason="admin_adjust")
    refilled = wallet.refill_allowance(db, user.id, period="2026-10")
    assert refilled.allowance_balance == 100  # plan amount, not 140
    assert refilled.last_refill_period == "2026-10"

    # Idempotent: a second run in the same period changes nothing,
    # ledger included.
    ledger_before = len(wallet.wallet_view(db, user.id)["ledger"])
    wallet.spend(db, user.id, amount=30)
    again = wallet.refill_allowance(db, user.id, period="2026-10")
    assert again.allowance_balance == 70
    refills = [
        r
        for r in wallet.wallet_view(db, user.id)["ledger"]
        if r["reason"] == "allowance_refill"
    ]
    assert len(refills) == 1
    assert len(wallet.wallet_view(db, user.id)["ledger"]) == ledger_before + 1

    # Next month refills again (spent allowance is replaced, and the
    # refill row records the true delta: 100 - 70 = +30).
    nxt = wallet.refill_allowance(db, user.id, period="2026-11")
    assert nxt.allowance_balance == 100


def test_free_plan_refills_to_zero(db, user):
    wallet.credit(db, user.id, amount=9, bucket="allowance", reason="admin_adjust")
    refilled = wallet.refill_allowance(db, user.id, period="2026-10")
    assert refilled.allowance_balance == 0  # free plan: 0 monthly credits


def test_refill_all_is_idempotent(db, user):
    other = _make_user(db, "other@example.com")
    wallet.get_or_create_wallet(db, user.id)
    wallet.get_or_create_wallet(db, other.id)
    assert wallet.refill_all_allowances(db, period="2026-10") == 2
    assert wallet.refill_all_allowances(db, period="2026-10") == 0
