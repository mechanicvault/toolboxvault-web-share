"""Redeem codes (billing module service).

Admin-issued codes a user redeems for a grant (owner doctrine:
created by the operator, live instantly; the Admin panel that
creates them is Phase A2 — the operator API lives in
admin_routes.py and this service behind it).

Kinds:
  - free_months(amount) — plan for `amount` months (stacking).
  - free_year — plan for one year (stacking).
  - lifetime — plan forever.
  - trial_months(amount) — plan for `amount` months, as a trial.
  - trial_days(amount) — LEGACY: plan for `amount` days, as a
    trial. Admin durations are months now (owner 2026-10-22);
    the kind stays redeemable for old rows but nothing creates
    it anymore.
  - ai_credits(amount) — credits into the wallet's banked bucket.

Validation is ordered so the error copy tells the user the truth:
unknown → deactivated → expired → exhausted → already-yours. The
per-user-once rule and the redemption count are enforced against
the ledger; the unique constraint is the backstop.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements, models, wallet

CODE_KINDS = (
    "free_months",
    "free_year",
    "lifetime",
    "ai_credits",
    "trial_months",
    "trial_days",
)


class RedeemError(ValueError):
    """A redemption refusal with user-facing copy (route → 400)."""


def normalize_code(code: str) -> str:
    return code.strip().upper()


def create_code(
    db: Session,
    *,
    code: str,
    kind: str,
    amount: int = 0,
    plan_key: str = "pro",
    max_redemptions: int | None = None,
    expires_at=None,
    created_by: uuid.UUID | None = None,
) -> models.RedeemCode:
    """Create a code. Raises ValueError for an unknown kind/plan or
    a code that already exists — the admin route turns those into
    422/409."""
    if kind not in CODE_KINDS:
        raise ValueError(f"Unknown code kind: {kind}")
    if entitlements.get_plan(db, plan_key) is None:
        raise ValueError(f"Unknown plan: {plan_key}")
    normalized = normalize_code(code)
    if not normalized:
        raise ValueError("Code must not be empty.")
    existing = db.scalars(
        select(models.RedeemCode).where(models.RedeemCode.code == normalized)
    ).first()
    if existing is not None:
        raise ValueError(f"A code named {normalized} already exists.")
    row = models.RedeemCode(
        code=normalized,
        kind=kind,
        amount=amount,
        plan_key=plan_key,
        max_redemptions=max_redemptions,
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_codes(db: Session) -> list[models.RedeemCode]:
    return list(
        db.scalars(
            select(models.RedeemCode).order_by(models.RedeemCode.created_at.desc())
        ).all()
    )


def redemption_count(db: Session, code_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(models.Redemption.id)).where(
                models.Redemption.code_id == code_id
            )
        )
        or 0
    )


def deactivate_code(db: Session, code_id: uuid.UUID) -> models.RedeemCode | None:
    row = db.get(models.RedeemCode, code_id)
    if row is None:
        return None
    row.active = False
    db.commit()
    db.refresh(row)
    return row


def code_view(db: Session, row: models.RedeemCode) -> dict:
    """Admin serialization: the code plus its live redemption count."""
    return {
        "id": row.id,
        "code": row.code,
        "kind": row.kind,
        "amount": row.amount,
        "plan_key": row.plan_key,
        "max_redemptions": row.max_redemptions,
        "redemptions": redemption_count(db, row.id),
        "expires_at": row.expires_at,
        "active": row.active,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def redeem(db: Session, user_id: uuid.UUID, raw_code: str) -> dict:
    """Apply a code to the caller's account. Returns a summary of
    what was granted; raises RedeemError with user-facing copy for
    every refusal. The grant/credit and its ledger row commit
    together — a code never half-applies."""
    now = entitlements._now()
    code = db.scalars(
        select(models.RedeemCode).where(
            models.RedeemCode.code == normalize_code(raw_code)
        )
    ).first()
    if code is None:
        raise RedeemError("That code doesn't look right — check it and try again.")
    if not code.active:
        raise RedeemError("That code is no longer active.")
    expires_at = entitlements._aware(code.expires_at)
    if expires_at is not None and expires_at <= now:
        raise RedeemError("That code has expired.")
    already = db.scalars(
        select(models.Redemption).where(
            models.Redemption.code_id == code.id,
            models.Redemption.user_id == user_id,
        )
    ).first()
    if already is not None:
        raise RedeemError("You've already redeemed this code.")
    if (
        code.max_redemptions is not None
        and redemption_count(db, code.id) >= code.max_redemptions
    ):
        raise RedeemError("That code has been fully redeemed.")

    grant = None
    summary: dict = {"kind": code.kind, "plan_key": code.plan_key}
    if code.kind == "ai_credits":
        wallet.credit(
            db,
            user_id,
            amount=code.amount,
            bucket="banked",
            reason="redeem",
            ref=code.code,
        )
        summary["credits"] = code.amount
    elif code.kind == "lifetime":
        grant = entitlements.create_grant(
            db,
            user_id,
            plan_key=code.plan_key,
            kind="lifetime",
            source="redeem_code",
            source_ref=code.code,
        )
    elif code.kind == "free_year":
        grant = entitlements.grant_period(
            db,
            user_id,
            plan_key=code.plan_key,
            kind="free_period",
            source="redeem_code",
            source_ref=code.code,
            months=12,
        )
    elif code.kind == "free_months":
        grant = entitlements.grant_period(
            db,
            user_id,
            plan_key=code.plan_key,
            kind="free_period",
            source="redeem_code",
            source_ref=code.code,
            months=code.amount,
        )
    elif code.kind == "trial_months":
        grant = entitlements.grant_period(
            db,
            user_id,
            plan_key=code.plan_key,
            kind="trial",
            source="redeem_code",
            source_ref=code.code,
            months=code.amount,
        )
    elif code.kind == "trial_days":
        grant = entitlements.grant_period(
            db,
            user_id,
            plan_key=code.plan_key,
            kind="trial",
            source="redeem_code",
            source_ref=code.code,
            days=code.amount,
        )
    if grant is not None:
        summary["ends_at"] = grant.ends_at

    db.add(
        models.Redemption(
            code_id=code.id,
            user_id=user_id,
            grant_id=grant.id if grant is not None else None,
        )
    )
    db.commit()
    return summary
