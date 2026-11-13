"""AI credit wallet (billing module service; spec:
files/ai-token-system.md).

Users hold abstract CREDITS, never raw model tokens — each AI
action will carry an admin-set credit price when the AI features
land, so a provider swap never revalues a balance. Two buckets:
the monthly allowance (refills to the plan amount, no rollover)
and the banked balance (purchased + granted + redeemed; persists).

SERVICE INTERFACE:
  - get_or_create_wallet(db, user_id)
  - wallet_view(db, user_id) — balances + recent ledger (Settings).
  - credit(db, user_id, amount, bucket, reason, ref)
  - spend(db, user_id, amount, reason, ref) — drains allowance
    first; raises InsufficientCredits. First caller (wave 4):
    billing.ai_service.charge_for, after a completed AI call.
  - refill_allowance(db, user_id, period=None) — idempotent monthly
    refill to the user's plan amount.
  - refill_all_allowances(db, period=None) — the monthly job seam.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements, models

BUCKETS = ("allowance", "banked")
LEDGER_LIMIT = 20


class InsufficientCredits(ValueError):
    """A spend exceeded the wallet's total balance."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _period(now: datetime | None = None) -> str:
    now = now or _now()
    return f"{now.year:04d}-{now.month:02d}"


def get_or_create_wallet(db: Session, user_id: uuid.UUID) -> models.AiWallet:
    uid = uuid.UUID(str(user_id))
    wallet_row = db.scalars(
        select(models.AiWallet).where(models.AiWallet.user_id == uid)
    ).first()
    if wallet_row is None:
        wallet_row = models.AiWallet(user_id=uid)
        db.add(wallet_row)
        db.commit()
        db.refresh(wallet_row)
    return wallet_row


def _log(
    db: Session,
    wallet_row: models.AiWallet,
    *,
    delta: int,
    bucket: str,
    reason: str,
    ref: str,
) -> None:
    balance = (
        wallet_row.allowance_balance
        if bucket == "allowance"
        else wallet_row.banked_balance
    )
    db.add(
        models.AiLedger(
            user_id=wallet_row.user_id,
            delta=delta,
            bucket=bucket,
            reason=reason,
            ref=ref,
            bucket_balance_after=balance,
        )
    )


def credit(
    db: Session,
    user_id: uuid.UUID,
    *,
    amount: int,
    bucket: str,
    reason: str,
    ref: str = "",
) -> models.AiWallet:
    """Add credits to one bucket and log the movement. Grants and
    code redemptions land in `banked` (they persist); purchases
    will too, when Stripe arrives."""
    if amount <= 0:
        raise ValueError("Credit amount must be positive.")
    if bucket not in BUCKETS:
        raise ValueError(f"Unknown wallet bucket: {bucket}")
    wallet_row = get_or_create_wallet(db, user_id)
    if bucket == "allowance":
        wallet_row.allowance_balance += amount
    else:
        wallet_row.banked_balance += amount
    _log(db, wallet_row, delta=amount, bucket=bucket, reason=reason, ref=ref)
    db.commit()
    db.refresh(wallet_row)
    return wallet_row


def spend(
    db: Session,
    user_id: uuid.UUID,
    *,
    amount: int,
    reason: str = "spend",
    ref: str = "",
) -> models.AiWallet:
    """Drain `amount` of credits, allowance first (the expiring
    bucket), then banked. One ledger row per bucket touched, so the
    history shows exactly where a spend came from."""
    if amount <= 0:
        raise ValueError("Spend amount must be positive.")
    wallet_row = get_or_create_wallet(db, user_id)
    total = wallet_row.allowance_balance + wallet_row.banked_balance
    if total < amount:
        raise InsufficientCredits(
            f"Spending {amount} credits needs a balance of {amount}; "
            f"this wallet holds {total}."
        )
    from_allowance = min(wallet_row.allowance_balance, amount)
    from_banked = amount - from_allowance
    if from_allowance:
        wallet_row.allowance_balance -= from_allowance
        _log(
            db,
            wallet_row,
            delta=-from_allowance,
            bucket="allowance",
            reason=reason,
            ref=ref,
        )
    if from_banked:
        wallet_row.banked_balance -= from_banked
        _log(
            db, wallet_row, delta=-from_banked, bucket="banked", reason=reason, ref=ref
        )
    db.commit()
    db.refresh(wallet_row)
    return wallet_row


def refill_allowance(
    db: Session, user_id: uuid.UUID, period: str | None = None
) -> models.AiWallet:
    """Set the allowance bucket to the user's plan amount for
    `period` ("YYYY-MM", default: current month). IDEMPOTENT: a
    second run in the same period changes nothing (the period
    stamp is the guard), so the monthly job can run daily and only
    the first run of a month lands. The allowance does not roll
    over — unspent credits from last month are replaced, and the
    ledger row records the true delta (which can be negative)."""
    period = period or _period()
    wallet_row = get_or_create_wallet(db, user_id)
    if wallet_row.last_refill_period == period:
        return wallet_row
    target = entitlements.resolve_entitlement(db, user_id).ai_monthly_credits
    delta = target - wallet_row.allowance_balance
    wallet_row.allowance_balance = target
    wallet_row.last_refill_period = period
    _log(
        db,
        wallet_row,
        delta=delta,
        bucket="allowance",
        reason="allowance_refill",
        ref=period,
    )
    db.commit()
    db.refresh(wallet_row)
    return wallet_row


def refill_all_allowances(db: Session, period: str | None = None) -> int:
    """The monthly job seam: refill every wallet that exists.
    (Wallets are created lazily — a user who has never touched AI
    has none, and their first wallet read can refill on the spot.)
    Returns how many wallets were refilled. SCHEDULING: no
    scheduler exists yet; a cron / management command calls this —
    see app/scripts/run_entitlement_jobs.py."""
    period = period or _period()
    user_ids = list(db.scalars(select(models.AiWallet.user_id)).all())
    refilled = 0
    for user_id in user_ids:
        row = db.scalars(
            select(models.AiWallet).where(models.AiWallet.user_id == user_id)
        ).first()
        if row is not None and row.last_refill_period == period:
            continue  # already refilled this period (idempotency)
        refill_allowance(db, user_id, period)
        refilled += 1
    return refilled


def wallet_view(db: Session, user_id: uuid.UUID) -> dict:
    """Settings payload: both balances, the total, and the recent
    ledger (newest first)."""
    wallet_row = get_or_create_wallet(db, user_id)
    ledger = list(
        db.scalars(
            select(models.AiLedger)
            .where(models.AiLedger.user_id == wallet_row.user_id)
            # Newest first; the bucket tiebreak keeps same-instant
            # movements (one spend touching both buckets shares a
            # timestamp) in a stable, sensible order: allowance
            # movements list before banked ones.
            .order_by(
                models.AiLedger.created_at.desc(),
                models.AiLedger.bucket.asc(),
                models.AiLedger.id.desc(),
            )
            .limit(LEDGER_LIMIT)
        ).all()
    )
    return {
        "allowance_balance": wallet_row.allowance_balance,
        "banked_balance": wallet_row.banked_balance,
        "total_balance": wallet_row.allowance_balance + wallet_row.banked_balance,
        "ledger": [
            {
                "id": row.id,
                "delta": row.delta,
                "bucket": row.bucket,
                "reason": row.reason,
                "ref": row.ref,
                "bucket_balance_after": row.bucket_balance_after,
                "created_at": row.created_at,
            }
            for row in ledger
        ],
    }
