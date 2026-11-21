"""Billing admin routes (operator-only): redeem-code management,
entitlement grants, AI credit grants.

Mounted by main.py at /api/admin alongside the module-control
admin router. The Phase A2 admin panel consumes these; the API and
its tests land now (owner doctrine: codes are created in-panel and
live instantly — this is the panel's backend). Every route is
behind require_operator, and every mutation writes an audit row
(core's audit service — the trail is one system, not per-module).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_operator
from app.modules.billing import codes, entitlements, models, schemas, wallet
from app.modules.core import audit

router = APIRouter()


@router.post("/codes", response_model=schemas.CodeView, status_code=201)
def create_code(
    payload: schemas.CodeCreate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        row = codes.create_code(
            db,
            code=payload.code,
            kind=payload.kind,
            amount=payload.amount,
            plan_key=payload.plan_key,
            max_redemptions=payload.max_redemptions,
            expires_at=payload.expires_at,
            created_by=operator.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        operator,
        action="code.create",
        target=row.code,
        detail={
            "kind": row.kind,
            "amount": row.amount,
            "plan_key": row.plan_key,
            "max_redemptions": row.max_redemptions,
        },
    )
    return codes.code_view(db, row)


@router.get("/codes", response_model=list[schemas.CodeView])
def list_codes(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [codes.code_view(db, row) for row in codes.list_codes(db)]


@router.post("/codes/{code_id}/deactivate", response_model=schemas.CodeView)
def deactivate_code(
    code_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = codes.deactivate_code(db, code_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown code."
        )
    audit.record(
        db, operator, action="code.deactivate", target=row.code, detail={}
    )
    return codes.code_view(db, row)


@router.get("/redemptions", response_model=list[schemas.RedemptionAdminView])
def list_redemptions(
    limit: int = Query(default=20, ge=1, le=100),
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Recent redemptions across all codes (the Promos section's
    activity list): which code, which account, when. User identity
    is resolved through core's service — the sanctioned path."""
    from app.modules.core import service as core_service

    rows = list(
        db.scalars(
            select(models.Redemption)
            .order_by(models.Redemption.redeemed_at.desc(), models.Redemption.id.desc())
            .limit(limit)
        ).all()
    )
    views = []
    for row in rows:
        code = db.get(models.RedeemCode, row.code_id)
        redeemer = core_service.get_user_by_id(db, row.user_id)
        views.append(
            {
                "id": row.id,
                "code": code.code if code is not None else "",
                "user_id": row.user_id,
                "user_email": redeemer.email if redeemer is not None else "",
                "user_name": redeemer.name if redeemer is not None else "",
                "redeemed_at": row.redeemed_at,
            }
        )
    return views


@router.post("/grants", status_code=201)
def create_grant(
    payload: schemas.GrantCreate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Start a free period or a trial for one user (admin doctrine:
    admins start trials and grant free access without asking
    anyone). Timed grants stack on the user's active same-plan
    grants; kind="lifetime" is the open-ended grant — the same
    shape the lifetime redeem code writes (ends_at None)."""
    if entitlements.get_plan(db, payload.plan_key) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown plan: {payload.plan_key}",
        )
    if payload.kind == "lifetime":
        grant = entitlements.create_grant(
            db,
            payload.user_id,
            plan_key=payload.plan_key,
            kind="lifetime",
            source="admin",
            source_ref=str(operator.id),
            created_by=operator.id,
        )
    else:
        if payload.months == 0 and payload.days == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A grant needs a duration (months and/or days).",
            )
        grant = entitlements.grant_period(
            db,
            payload.user_id,
            plan_key=payload.plan_key,
            kind=payload.kind,
            source="admin",
            source_ref=str(operator.id),
            months=payload.months,
            days=payload.days,
            created_by=operator.id,
        )
    audit.record(
        db,
        operator,
        action="grant.create",
        target=str(payload.user_id),
        detail={
            "kind": payload.kind,
            "plan_key": payload.plan_key,
            "months": payload.months,
            "days": payload.days,
            "ends_at": grant.ends_at.isoformat() if grant.ends_at else None,
        },
    )
    return {
        "id": grant.id,
        "user_id": grant.user_id,
        "plan_key": grant.plan_key,
        "kind": grant.kind,
        "starts_at": grant.starts_at,
        "ends_at": grant.ends_at,
    }


@router.post("/ai-grants", status_code=201)
def create_ai_grant(
    payload: schemas.AiGrantCreate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Grant AI credits to one user (banked bucket — grants
    persist). Returns the wallet's new balances."""
    wallet_row = wallet.credit(
        db,
        payload.user_id,
        amount=payload.amount,
        bucket="banked",
        reason="grant",
        ref=str(operator.id),
    )
    audit.record(
        db,
        operator,
        action="ai_grant.create",
        target=str(payload.user_id),
        detail={
            "amount": payload.amount,
            "banked_balance": wallet_row.banked_balance,
        },
    )
    return {
        "user_id": wallet_row.user_id,
        "allowance_balance": wallet_row.allowance_balance,
        "banked_balance": wallet_row.banked_balance,
    }
