"""Admin panel routes (Phase A2, operator-only): Users, Bans,
Settings, Audit.

Mounted by main.py at /api/admin alongside the module-control and
billing admin routers. Owner doctrine: the admin has God
privileges and never needs this chat — every action here is
immediate, and every mutating action writes an audit row
(core/audit.py) after it lands.

Self-guards: an operator cannot revoke their own operator flag,
deactivate their own account, or ban their own email from this
surface — the three ways to lock yourself out of God mode by
misclick. (Another operator can still do all three to them.)

God-account protection (owner design, 2026-10-31): the god
account (core/tiers.py — the account carrying the god rung) can
be edited ONLY by itself. Every admin path that would change the
god account — profile/role/tier/beta edits, benefit grants,
deactivation, restore-on-behalf, an email ban — refuses when the
actor is anyone else (_guard_god_target). The grant endpoints
(/tier, /beta) additionally enforce the rung rules: moderator
admin is god's alone to grant or revoke; moderator and beta are
god's or a moderator admin's; nobody grants themselves anything.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.db import Base, get_db
from app.core.deps import CurrentUser, require_operator, require_user_manager
from app.core.storage import StorageError, storage
from app.modules.billing import ai_service, entitlements, stripe_payments, wallet
from app.modules.catalog import lookup_config
from app.modules.core import admin_schemas as schemas
from app.modules.core import audit, cloud_backup, history_routes, journal, landing, models, nav_badges, service, teaser, tier_conversion, tiers
from app.modules.claims import readiness
from app.modules.forum import service as forum_service
from app.modules.marketplace import service as marketplace_service
from app.modules.messaging import spam
from app.modules.parts import pool as parts_pool
from app.modules.truck_accounts import agreement as truck_agreement
from app.modules.truck_accounts import truck_payments

router = APIRouter()

# The AI seam's setting keys live with the seam (billing.ai_service);
# re-exported under the historical names this module's handlers use.
AI_PROVIDER_KEY = ai_service.PROVIDER_KEY
AI_MODEL_KEY = ai_service.MODEL_KEY
AI_API_KEY_REF_KEY = ai_service.API_KEY_REF_KEY


def _user_or_404(db: Session, user_id: uuid.UUID) -> models.User:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown user."
        )
    return user


def _summary(db: Session, user: models.User) -> dict:
    entitlement = entitlements.resolve_entitlement(db, user.id)
    return {
        "id": user.id,
        "account_number": user.account_number,
        "name": user.name,
        "email": user.email,
        "account_types": list(user.account_types or []),
        "plan_key": entitlement.plan_key,
        "plan_name": entitlement.plan_name,
        "is_operator": bool(user.is_operator),
        "role": user.role,
        "tier": tiers.resolved_tier(user),
        "beta_tester": bool(getattr(user, "beta_tester", False)),
        "is_active": bool(user.is_active),
        "created_at": user.created_at,
    }


def _guard_god_target(actor: CurrentUser, target: models.User) -> None:
    """The god account is edited by itself alone (owner design,
    2026-10-31): any admin path about to change the god account
    refuses when the actor is a different account. The test is
    the god IDENTITY (tiers.is_god_account — the stored god
    rung), not god-rung access: an operator grant gives another
    account god's access, and that account stays revocable and
    editable by god exactly as before — the crown doesn't move
    with the flag. Reads (the directory, the detail view) are
    NOT guarded — seeing is not editing."""
    if tiers.is_god_account(target) and actor.id != target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The God account can only be edited by the God account itself.",
        )


def _detail(db: Session, user: models.User) -> dict:
    entitlement = entitlements.resolve_entitlement(db, user.id)
    sub = entitlement.subscription
    wallet_row = wallet.get_or_create_wallet(db, user.id)
    detail = _summary(db, user)
    detail.update(
        {
            "email_verified": bool(user.email_verified),
            "referred_by_id": user.referred_by_id,
            "entitlement": {
                "plan_key": entitlement.plan_key,
                "plan_name": entitlement.plan_name,
                "source": entitlement.source,
                "is_paid": entitlement.is_paid,
                "status": sub.status if sub is not None else None,
                "current_period_end": (
                    sub.current_period_end if sub is not None else None
                ),
                "trial_end": sub.trial_end if sub is not None else None,
                "grace_until": sub.grace_until if sub is not None else None,
            },
            "wallet": {
                "allowance_balance": wallet_row.allowance_balance,
                "banked_balance": wallet_row.banked_balance,
            },
            "session_count": len(service.list_sessions(db, user, None)),
            "referral_count": service.referral_count(db, user.id),
        }
    )
    return detail


# -- conversion requests (tier conversion, 2026-11-10) ----------
#
# The god queue for the request door out of the downloads level.
# GOD ONLY, both reads and decisions — and the permission model
# carries it cleanly, twice over: require_operator refuses
# everyone without the operator flag (a moderator admin holds
# the rung WITHOUT the flag — core/tiers.derive_tier makes the
# flag itself derive god), and the actor's RESOLVED tier must
# then be god, the same tier test the /tier grant endpoint uses
# for moderator-admin grants. Nothing is widened to fit.


def _require_god(actor: CurrentUser) -> None:
    if actor.tier != "god":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversion requests are decided by the god account only.",
        )


def _conversion_request_view(
    db: Session, row: models.ConversionRequest
) -> dict:
    requester = service.get_user_by_id(db, row.user_id)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "account_number": requester.account_number if requester else "",
        "name": requester.name if requester else "",
        "email": requester.email if requester else "",
        "status": row.status,
        "created_at": row.created_at,
        "decided_by_email": row.decided_by_email,
        "decided_at": row.decided_at,
    }


@router.get(
    "/conversion-requests",
    response_model=list[schemas.AdminConversionRequestView],
)
def list_conversion_requests(
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Pending first (oldest first), then the decided history."""
    _require_god(actor)
    return [
        _conversion_request_view(db, row)
        for row in tier_conversion.list_requests(db)
    ]


@router.post(
    "/conversion-requests/{request_id}/approve",
    response_model=schemas.AdminConversionRequestView,
)
def approve_conversion_request(
    request_id: uuid.UUID,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Approval runs the SAME conversion as the code door."""
    _require_god(actor)
    decider = service.get_user_by_id(db, actor.id)
    try:
        row = tier_conversion.decide_request(
            db, decider, request_id, approve=True
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown conversion request.",
        ) from None
    except tier_conversion.AlreadyDecided:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That request has already been decided.",
        ) from None
    return _conversion_request_view(db, row)


@router.post(
    "/conversion-requests/{request_id}/deny",
    response_model=schemas.AdminConversionRequestView,
)
def deny_conversion_request(
    request_id: uuid.UUID,
    actor: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Denial is final for the request door (the owner's
    anti-spam ruling); the code door stays open to the account."""
    _require_god(actor)
    decider = service.get_user_by_id(db, actor.id)
    try:
        row = tier_conversion.decide_request(
            db, decider, request_id, approve=False
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown conversion request.",
        ) from None
    except tier_conversion.AlreadyDecided:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That request has already been decided.",
        ) from None
    return _conversion_request_view(db, row)


# -- users ---------------------------------------------------------------------


@router.get("/users", response_model=schemas.AdminUserPage)
def list_users(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _operator: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """The directory: search name/email/account number, paginated.
    Readable by user managers (god + moderator admins) — the grant
    endpoints below need the directory to find their targets; the
    mutations beyond tier/beta stay operator-only."""
    rows, total = service.search_users(db, q, limit=limit, offset=offset)
    return {
        "items": [_summary(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/users/{user_id}", response_model=schemas.AdminUserDetail)
def get_user(
    user_id: uuid.UUID,
    _operator: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    return _detail(db, _user_or_404(db, user_id))


@router.post("/users/{user_id}/operator", response_model=schemas.AdminUserDetail)
def set_operator(
    user_id: uuid.UUID,
    payload: schemas.OperatorRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Grant or revoke God access for one account."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    if user.id == operator.id and not payload.is_operator:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't revoke your own operator access.",
        )
    service.set_user_operator(db, user, payload.is_operator)
    audit.record(
        db,
        operator,
        action="user.operator_grant" if payload.is_operator else "user.operator_revoke",
        target=str(user.id),
        detail={"email": user.email},
    )
    return _detail(db, user)


@router.post("/users/{user_id}/role", response_model=schemas.AdminUserDetail)
def set_role(
    user_id: uuid.UUID,
    payload: schemas.RoleRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Set the community role (user | moderator | community_admin).
    The tier fold-in applies (service.set_user_role moves the rung
    to match), and the god account's role is its own to edit."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    previous = user.role
    service.set_user_role(db, user, payload.role)
    audit.record(
        db,
        operator,
        action="user.role_set",
        target=str(user.id),
        detail={"email": user.email, "role": payload.role, "previous": previous},
    )
    return _detail(db, user)


@router.post("/users/{user_id}/tier", response_model=schemas.AdminUserDetail)
def set_tier(
    user_id: uuid.UUID,
    payload: schemas.TierRequest,
    actor: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """Set the account's rung (normal | moderator | moderator_admin).

    The grant rules (owner design, 2026-10-31 — core/tiers.py):
    - moderator admin is granted AND revoked by god alone — any
      move into or out of that rung by anyone else refuses;
    - moderator moves are god's or a moderator admin's (this
      endpoint's gate already ensures the actor is one of those);
    - nobody changes their own rung;
    - the god rung is never a payload value (the schema's Literal
      excludes it) and the god account's rung cannot be changed
      by anyone — the target guard refuses first.
    """
    user = _user_or_404(db, user_id)
    _guard_god_target(actor, user)
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't change your own account tier.",
        )
    previous = tiers.resolved_tier(user)
    touches_mod_admin = (
        payload.tier == "moderator_admin" or previous == "moderator_admin"
    )
    if touches_mod_admin and actor.tier != "god":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the God account can grant or revoke Moderator Admin.",
        )
    service.set_user_tier(db, user, payload.tier)
    audit.record(
        db,
        actor,
        action="user.tier_set",
        target=str(user.id),
        detail={"email": user.email, "tier": payload.tier, "previous": previous},
    )
    return _detail(db, user)


@router.post("/users/{user_id}/beta", response_model=schemas.AdminUserDetail)
def set_beta(
    user_id: uuid.UUID,
    payload: schemas.BetaRequest,
    actor: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """Grant or revoke the Beta Tester upgrade flag. God or a
    moderator admin (the gate); never for oneself; the god
    account's flag is the god account's own business (the target
    guard refuses anyone else)."""
    user = _user_or_404(db, user_id)
    _guard_god_target(actor, user)
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't change your own beta tester status.",
        )
    previous = bool(getattr(user, "beta_tester", False))
    service.set_user_beta(db, user, payload.beta_tester)
    audit.record(
        db,
        actor,
        action="user.beta_set",
        target=str(user.id),
        detail={
            "email": user.email,
            "beta_tester": payload.beta_tester,
            "previous": previous,
        },
    )
    return _detail(db, user)


@router.post("/users/{user_id}/trial", response_model=schemas.AdminUserDetail)
def start_trial(
    user_id: uuid.UUID,
    payload: schemas.TrialRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Start a trial: the plan for N months (admin durations run
    off months — owner 2026-10-22; a legacy days body still
    works), stacking on any active same-plan grant (the grant
    machinery's rule)."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    grant = entitlements.grant_period(
        db,
        user.id,
        plan_key=payload.plan_key,
        kind="trial",
        source="admin",
        source_ref=str(operator.id),
        months=payload.months or 0,
        days=payload.days or 0,
        created_by=operator.id,
    )
    audit.record(
        db,
        operator,
        action="user.trial_start",
        target=str(user.id),
        detail={
            "email": user.email,
            "plan_key": payload.plan_key,
            "months": payload.months,
            "days": payload.days,
            "ends_at": grant.ends_at.isoformat() if grant.ends_at else None,
        },
    )
    return _detail(db, user)


@router.post("/users/{user_id}/free-period", response_model=schemas.AdminUserDetail)
def grant_free_period(
    user_id: uuid.UUID,
    payload: schemas.FreePeriodRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Give an account free access: the plan for N months, no
    charge — or, with lifetime: true, the open-ended grant (the
    same shape the lifetime redeem code writes). A legacy days
    body still works."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    if payload.lifetime:
        grant = entitlements.create_grant(
            db,
            user.id,
            plan_key=payload.plan_key,
            kind="lifetime",
            source="admin",
            source_ref=str(operator.id),
            created_by=operator.id,
        )
    else:
        grant = entitlements.grant_period(
            db,
            user.id,
            plan_key=payload.plan_key,
            kind="free_period",
            source="admin",
            source_ref=str(operator.id),
            months=payload.months or 0,
            days=payload.days or 0,
            created_by=operator.id,
        )
    audit.record(
        db,
        operator,
        action="user.free_period",
        target=str(user.id),
        detail={
            "email": user.email,
            "plan_key": payload.plan_key,
            "months": payload.months,
            "days": payload.days,
            "lifetime": payload.lifetime,
            "ends_at": grant.ends_at.isoformat() if grant.ends_at else None,
        },
    )
    return _detail(db, user)


@router.post("/users/{user_id}/ai-credits", response_model=schemas.AdminUserDetail)
def grant_ai_credits(
    user_id: uuid.UUID,
    payload: schemas.AiCreditsRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Grant AI credits into the banked bucket (grants persist)."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    wallet_row = wallet.credit(
        db,
        user.id,
        amount=payload.amount,
        bucket="banked",
        reason="grant",
        ref=str(operator.id),
    )
    audit.record(
        db,
        operator,
        action="user.ai_credits",
        target=str(user.id),
        detail={
            "email": user.email,
            "amount": payload.amount,
            "banked_balance": wallet_row.banked_balance,
        },
    )
    return _detail(db, user)


@router.post("/users/{user_id}/deactivate", response_model=schemas.AdminUserDetail)
def deactivate_user(
    user_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Soft deactivation: sign-in blocked, sessions revoked, data
    kept, reversible with /reactivate."""
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    if user.id == operator.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't deactivate your own account.",
        )
    service.set_user_active(db, user, False)
    audit.record(
        db,
        operator,
        action="user.deactivate",
        target=str(user.id),
        detail={"email": user.email},
    )
    return _detail(db, user)


@router.post("/users/{user_id}/reactivate", response_model=schemas.AdminUserDetail)
def reactivate_user(
    user_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    service.set_user_active(db, user, True)
    audit.record(
        db,
        operator,
        action="user.reactivate",
        target=str(user.id),
        detail={"email": user.email},
    )
    return _detail(db, user)


# -- user history & restore (audit trail, 2026-10-19) ---------------------------
#
# The operator's on-behalf surface over a user's change journal:
# view their restore points + timeline, create a marker for them,
# and restore their account to a marker. A restore here writes
# BOTH trails — the user's journal (the engine's restore event,
# actor = the operator) and this panel's audit log (user.restore).


def _target_marker_or_404(db: Session, user_id: uuid.UUID, marker_id: uuid.UUID):
    marker = journal.get_marker(db, user_id, marker_id)
    if marker is None:
        raise HTTPException(status_code=404, detail="Restore point not found.")
    return marker


@router.get(
    "/users/{user_id}/history", response_model=schemas.AdminUserHistory
)
def get_user_history(
    user_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    rows, total = journal.list_entries(db, user.id, limit=limit, offset=offset)
    return {
        "markers": [
            history_routes.marker_view(m)
            for m in journal.list_markers(db, user.id)
        ],
        "entries": [
            history_routes.entry_view(r, owner_id=user.id, self_word="owner")
            for r in rows
        ],
        "entries_total": total,
    }


@router.post(
    "/users/{user_id}/history/markers",
    response_model=schemas.RestoreMarkerView,
    status_code=status.HTTP_201_CREATED,
)
def create_user_marker(
    user_id: uuid.UUID,
    payload: schemas.MarkerCreate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    marker = journal.create_marker(
        db, user.id, kind="manual", label=payload.label
    )
    audit.record(
        db,
        operator,
        action="user.marker.create",
        target=str(user.id),
        detail={"email": user.email, "marker_id": str(marker.id)},
    )
    return history_routes.marker_view(marker)


@router.post(
    "/users/{user_id}/history/restore",
    response_model=schemas.RestoreResultView,
)
def restore_user(
    user_id: uuid.UUID,
    payload: schemas.RestoreRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, user_id)
    _guard_god_target(operator, user)
    marker = _target_marker_or_404(db, user.id, payload.marker_id)
    try:
        result = journal.restore_to_marker(
            db, user.id, marker, actor_id=operator.id
        )
    except journal.RestoreConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "restore_conflict", "message": str(exc)},
        )
    audit.record(
        db,
        operator,
        action="user.restore",
        target=str(user.id),
        detail={
            "email": user.email,
            "marker_id": str(marker.id),
            "marker_label": marker.label,
            "restored": result["restored"],
            "not_changed": result["not_changed"],
        },
    )
    return result


# -- bans ------------------------------------------------------------------------


def _ban_view(db: Session, row: models.BannedEmail) -> dict:
    banner = (
        service.get_user_by_id(db, row.banned_by) if row.banned_by else None
    )
    return {
        "id": row.id,
        "email": row.email,
        "reason": row.reason,
        "banned_by": row.banned_by,
        "banned_by_email": banner.email if banner is not None else None,
        "created_at": row.created_at,
    }


@router.get("/bans", response_model=list[schemas.BanView])
def list_bans(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return [_ban_view(db, row) for row in service.list_bans(db)]


@router.post("/bans", response_model=schemas.BanView, status_code=201)
def create_ban(
    payload: schemas.BanCreate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Ban an email address: signup, password sign-in, and social
    sign-in all refuse it from the next request, and any account
    holding it loses its live sessions immediately."""
    if payload.email.strip().lower() == operator.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't ban your own email address.",
        )
    # God-account protection: banning the god account's email is
    # an edit of the god account (it ends its sign-in), so it is
    # the god account's own act or nobody's.
    holder = service.get_user_by_email(db, payload.email.strip().lower())
    if holder is not None:
        _guard_god_target(operator, holder)
    try:
        row = service.ban_email(
            db, payload.email, reason=payload.reason, banned_by=operator.id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    audit.record(
        db,
        operator,
        action="ban.create",
        target=row.email,
        detail={"reason": row.reason},
    )
    return _ban_view(db, row)


@router.delete("/bans/{ban_id}", status_code=204)
def remove_ban(
    ban_id: uuid.UUID,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = db.get(models.BannedEmail, ban_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown ban."
        )
    email = row.email
    service.unban_email(db, email)
    audit.record(db, operator, action="ban.remove", target=email, detail={})


# -- settings ---------------------------------------------------------------------


def _system_stats(db: Session) -> dict:
    """Cheap aggregates for the Settings section: headline counts
    plus a per-table row-count summary over every table the app
    owns. Counts are plain SELECT COUNT(*) — fine at this scale,
    and the section is operator-only and rarely loaded."""
    from sqlalchemy import inspect as sa_inspect

    from app.modules.registry import FEATURE_MODULES

    existing = set(sa_inspect(db.get_bind()).get_table_names())
    tables: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        tables[table.name] = (
            db.scalar(select(func.count()).select_from(table)) or 0
        )
    return {
        "users": tables.get("users", 0),
        "tools": tables.get("tools", 0),
        "feature_modules": len(FEATURE_MODULES),
        "tables": tables,
    }


def _recent_backup_runs(db: Session) -> list[dict]:
    """The Disaster Vault's newest runs for the Settings block.
    Guarded like _system_stats: a database that predates migration
    0013 simply shows no runs instead of failing the whole page."""
    from sqlalchemy import inspect as sa_inspect

    if "backup_runs" not in set(sa_inspect(db.get_bind()).get_table_names()):
        return []
    rows = db.scalars(
        select(models.BackupRun)
        .order_by(models.BackupRun.started_at.desc())
        .limit(7)
    ).all()
    return [
        {
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "bundle_name": row.bundle_name,
            "size_bytes": row.size_bytes,
            "encrypted": row.encrypted,
            "uploaded": row.uploaded,
            "verified": row.verified,
            "status": row.status,
        }
        for row in rows
    ]


def _job_statuses(db: Session) -> list[dict]:
    """The scheduler registry with each job's newest ledger row
    (step-4 fix round). Guarded like _recent_backup_runs: a
    database that predates migration 0035 shows the registry with
    no runs instead of failing the whole page."""
    from sqlalchemy import inspect as sa_inspect

    from app.scripts.scheduler import JOBS

    latest: dict[str, models.JobRun] = {}
    if "job_runs" in set(sa_inspect(db.get_bind()).get_table_names()):
        for row in db.scalars(
            select(models.JobRun).order_by(models.JobRun.started_at.desc())
        ):
            latest.setdefault(row.job, row)
    out = []
    for spec in JOBS:
        row = latest.get(spec.name)
        detail = (row.detail or {}) if row is not None else {}
        out.append(
            {
                "job": spec.name,
                "interval_minutes": spec.interval_minutes,
                "last_status": row.status if row is not None else None,
                "last_started_at": row.started_at if row is not None else None,
                "last_finished_at": row.finished_at if row is not None else None,
                "summary": detail.get("summary"),
                "error": detail.get("error"),
            }
        )
    return out


def _backup_drive_view(db: Session) -> dict:
    """The Disaster Vault Drive connection posture for Settings.
    Guarded like _recent_backup_runs: a database that predates
    migration 0051 shows "not connected" instead of failing the
    whole page."""
    from sqlalchemy import inspect as sa_inspect

    view = {
        "connected": False,
        "email": "",
        "folder_id": app_settings.backup_drive_folder_id or "",
        "connected_at": None,
        "oauth_configured": bool(
            app_settings.google_client_id and app_settings.google_client_secret
        ),
    }
    if "platform_drive_connection" not in set(
        sa_inspect(db.get_bind()).get_table_names()
    ):
        return view
    connection = cloud_backup.platform_connection(db)
    if connection is not None:
        view.update(
            {
                "connected": True,
                "email": connection.drive_email or "",
                "folder_id": connection.drive_folder_id
                or view["folder_id"],
                "connected_at": connection.connected_at,
            }
        )
    return view


def _settings_view(db: Session) -> dict:
    return {
        "enforcement_enabled": entitlements.enforcement_enabled(db),
        "require_email_verification": entitlements.email_verification_required(db),
        # Teaser mode (2026-10-26): the switch + whether a custom
        # gate code is stored. The code itself is NEVER part of
        # this view — it is write-only (core/teaser.py).
        "teaser": {
            "enabled": teaser.teaser_enabled(db),
            "gate_code_custom": teaser.gate_code_is_custom(db),
            "video_set": teaser.video_state(db)["set"],
            "video_name": teaser.video_state(db)["name"],
        },
        "audit_retention_days": journal.retention_days(db),
        "ai": {
            "provider": entitlements.get_setting(db, AI_PROVIDER_KEY, "") or "",
            "model": entitlements.get_setting(db, AI_MODEL_KEY, "") or "",
            "api_key_ref": entitlements.get_setting(db, AI_API_KEY_REF_KEY, "") or "",
            # Per-action credit prices (wave 4; 0 = free).
            "prices": {
                action: ai_service.price_for(db, action)
                for action in ai_service.PRICE_KEYS
            },
            # Per-action model overrides (2026-10-25): the raw
            # operator value; blank = rides the site model.
            "action_models": {
                action: entitlements.get_setting(db, key, "") or ""
                for action, key in ai_service.MODEL_KEYS.items()
            },
        },
        # Product lookup layers (wave 4): provider + key REFERENCE
        # names, the same pattern as the AI config. Empty = the
        # layer is dark and the chain skips it silently.
        "lookup": {
            "upc_provider": entitlements.get_setting(
                db, lookup_config.UPC_PROVIDER_KEY, ""
            )
            or "",
            "upc_api_key_ref": entitlements.get_setting(
                db, lookup_config.UPC_API_KEY_REF_KEY, ""
            )
            or "",
        },
        "stripe": {
            "configured": stripe_payments.payments_configured(),
            "price_pro_monthly": stripe_payments.plan_price_id(
                db, "pro", "monthly"
            ),
            "price_pro_yearly": stripe_payments.plan_price_id(db, "pro", "yearly"),
            "price_business_monthly": stripe_payments.plan_price_id(
                db, "business", "monthly"
            ),
            "price_business_yearly": stripe_payments.plan_price_id(
                db, "business", "yearly"
            ),
            "price_business_brackets": stripe_payments.bracket_price_map(db),
            "brackets": [
                {
                    "bracket_key": bracket.bracket_key,
                    "up_to_employees": bracket.up_to_employees,
                }
                for bracket in stripe_payments.business_brackets(db)
            ],
            "ai_credit_packs": stripe_payments.ai_credit_packs(db),
        },
        # Public landing page (landing build, 2026-10-20): the
        # operator-edited display config — effective values with
        # the seeded defaults folded in (core/landing.py).
        "landing": landing.landing_config(db),
        # Community (2026-10-19): the firewall's effective config
        # (messaging owns the merge) + the pool switch's RAW stored
        # value (pool.pool_enabled ALSO consults the parts global
        # switch — the panel edits this one key, so it shows it).
        "spam": spam.get_config(db),
        "parts_pool_enabled": bool(
            entitlements.get_setting(db, parts_pool.POOL_ENABLED_KEY, True)
        ),
        # Tools For Sale kill switch (2026-10-19): the RAW stored
        # value, same posture as the pool's (marketplace_enabled
        # also consults the module's global switch — the panel
        # edits this one key, so it shows it).
        "marketplace_enabled": bool(
            entitlements.get_setting(
                db, marketplace_service.MARKETPLACE_ENABLED_KEY, True
            )
        ),
        # Community Forum kill switch (2026-10-20): the RAW stored
        # value, same posture (forum_enabled also consults the
        # module's global switch).
        "forum_enabled": bool(
            entitlements.get_setting(db, forum_service.FORUM_ENABLED_KEY, True)
        ),
        # Claim-readiness nudges (audit A8): kill switch +
        # interval, raw stored values like the switches above.
        "claim_readiness_nudges_enabled": bool(
            entitlements.get_setting(db, readiness.READINESS_ENABLED_KEY, True)
        ),
        "claim_readiness_interval_days": readiness.nudge_interval_days(db),
        # Truck payments (wave 2): the Connect seam's switch + fee,
        # with `configured` reporting the EFFECTIVE dark/live
        # state (keys AND switch) so the panel never overpromises.
        "truck_payments": {
            "connect_enabled": truck_payments.connect_enabled(db),
            "configured": truck_payments.payments_configured(db),
            "truck_fee_percent": float(
                entitlements.get_setting(
                    db, truck_agreement.TRUCK_FEE_PERCENT_KEY, 0
                )
                or 0
            ),
        },
        "stats": _system_stats(db),
        "backups": _recent_backup_runs(db),
        "backup_drive": _backup_drive_view(db),
        "jobs": _job_statuses(db),
        # NEW-badge registry (release machinery, 2026-11-08):
        # nav item key -> release date, edited as one map.
        "nav_new_badges": nav_badges.get_nav_badges(db),
    }


@router.get("/settings", response_model=schemas.SettingsView)
def get_settings(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return _settings_view(db)


@router.post("/settings/backup-drive/connect")
def connect_backup_drive(
    operator: CurrentUser = Depends(require_operator),
):
    """Start the Disaster Vault Drive connect round-trip: the
    operator consents AS the backup account (MechanicVault) and
    Google returns through the shared cloud-backup callback,
    which dispatches on the state's platform purpose. 503 while
    the site's Google client isn't configured (the same posture
    as Google sign-in)."""
    if not app_settings.google_client_id or not app_settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "oauth_not_configured",
                "message": "Google sign-in isn't configured for this site yet.",
            },
        )
    state = cloud_backup.create_connect_state(
        operator.id, purpose=cloud_backup.PLATFORM_CONNECT_PURPOSE
    )
    return {"authorize_url": cloud_backup.platform_authorize_url(state)}


@router.post("/settings/backup-drive/disconnect", response_model=schemas.SettingsView)
def disconnect_backup_drive(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Disconnect the platform Drive leg: best-effort revoke at
    Google, delete the stored connection, audit the act. Nightly
    bundles stay local-only (and un-alerted) until a reconnect."""
    existed = cloud_backup.disconnect_platform(db)
    if existed:
        audit.record(
            db,
            operator,
            action="backup_drive.disconnect",
            target="platform-drive",
            detail={},
        )
    return _settings_view(db)


@router.put("/settings", response_model=schemas.SettingsView)
def update_settings(
    payload: schemas.SettingsUpdate,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Partial update of the system settings. The AI fields are
    CONFIG ONLY today (provider/model/key-reference names per the
    AI token spec) — nothing calls a provider with them yet; the
    AI service reads them when it lands, so a provider swap is
    this form, not a deploy."""
    changes: list[tuple[str, object]] = []
    if payload.enforcement_enabled is not None:
        entitlements.set_setting(
            db, entitlements.ENFORCEMENT_KEY, payload.enforcement_enabled
        )
        changes.append((entitlements.ENFORCEMENT_KEY, payload.enforcement_enabled))
    # Teaser mode (2026-10-26): the switch, and the gate code —
    # write-only: the audit trail records THAT it changed, never
    # the code itself. An empty string clears the stored code
    # back to the owner's default (core/teaser.py).
    if payload.teaser_enabled is not None:
        entitlements.set_setting(db, teaser.ENABLED_KEY, payload.teaser_enabled)
        changes.append((teaser.ENABLED_KEY, payload.teaser_enabled))
    if payload.teaser_gate_code is not None:
        new_code = payload.teaser_gate_code.strip()
        if new_code and len(new_code) < 4:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The gate code needs at least 4 characters.",
            )
        entitlements.set_setting(db, teaser.GATE_CODE_KEY, new_code)
        changes.append((teaser.GATE_CODE_KEY, "***"))
    if payload.require_email_verification is not None:
        entitlements.set_setting(
            db,
            entitlements.REQUIRE_EMAIL_VERIFICATION_KEY,
            payload.require_email_verification,
        )
        changes.append(
            (
                entitlements.REQUIRE_EMAIL_VERIFICATION_KEY,
                payload.require_email_verification,
            )
        )
    if payload.audit_retention_days is not None:
        entitlements.set_setting(
            db, journal.RETENTION_KEY, payload.audit_retention_days
        )
        changes.append((journal.RETENTION_KEY, payload.audit_retention_days))
    for key, value in (
        (AI_PROVIDER_KEY, payload.ai_provider),
        (AI_MODEL_KEY, payload.ai_model),
        (AI_API_KEY_REF_KEY, payload.ai_api_key_ref),
    ):
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    # AI per-action credit prices (wave 4): one setting per action,
    # stored only when the panel sends it.
    for action, key in ai_service.PRICE_KEYS.items():
        value = getattr(payload, f"ai_price_{action}", None)
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    # AI per-action model overrides (2026-10-25): same shape —
    # one setting per action, stored only when sent.
    for action, key in ai_service.MODEL_KEYS.items():
        value = getattr(payload, f"ai_model_{action}", None)
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    # Product lookup layers (wave 4): provider name + key ref
    # for the UPC database. (Web search has no settings here —
    # it rides the AI seam.)
    for key, value in (
        (lookup_config.UPC_PROVIDER_KEY, payload.lookup_upc_provider),
        (lookup_config.UPC_API_KEY_REF_KEY, payload.lookup_upc_api_key_ref),
    ):
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    # Stripe price ids (billing's keys, the same store): setting
    # them is what makes plans/packs purchasable once the server
    # keys exist — prices go live from this panel, never a deploy.
    for key, value in (
        (stripe_payments.PRICE_PRO_MONTHLY_KEY, payload.stripe_price_pro_monthly),
        (stripe_payments.PRICE_PRO_YEARLY_KEY, payload.stripe_price_pro_yearly),
        (
            stripe_payments.PRICE_BUSINESS_MONTHLY_KEY,
            payload.stripe_price_business_monthly,
        ),
        (
            stripe_payments.PRICE_BUSINESS_YEARLY_KEY,
            payload.stripe_price_business_yearly,
        ),
        (
            stripe_payments.BRACKET_PRICE_MAP_KEY,
            payload.stripe_price_business_brackets,
        ),
    ):
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    if payload.stripe_ai_credit_packs is not None:
        packs = [pack.model_dump() for pack in payload.stripe_ai_credit_packs]
        entitlements.set_setting(db, stripe_payments.AI_CREDIT_PACKS_KEY, packs)
        changes.append((stripe_payments.AI_CREDIT_PACKS_KEY, packs))
    # Public landing page (2026-10-20): display prices, the
    # self-serve trial switch + copy, and the app-store URLs —
    # core owns the keys; edits are live on the anonymous page
    # the moment they save, one audit row per key like the rest.
    for key, value in (
        (landing.PRO_MONTHLY_PRICE_KEY, payload.landing_pro_monthly_price),
        (landing.PRO_YEARLY_PRICE_KEY, payload.landing_pro_yearly_price),
        (
            landing.BUSINESS_MONTHLY_PRICE_KEY,
            payload.landing_business_monthly_price,
        ),
        (
            landing.BUSINESS_YEARLY_PRICE_KEY,
            payload.landing_business_yearly_price,
        ),
        (
            landing.SELF_SERVE_TRIAL_ENABLED_KEY,
            payload.landing_self_serve_trial_enabled,
        ),
        (landing.TRIAL_COPY_KEY, payload.landing_trial_copy),
        (landing.APP_STORE_URL_KEY, payload.landing_app_store_url),
        (landing.PLAY_STORE_URL_KEY, payload.landing_play_store_url),
    ):
        if value is not None:
            entitlements.set_setting(db, key, value)
            changes.append((key, value))
    # Community (2026-10-19): the spam firewall config (stored as
    # one JSON dict; the update merges field-by-field over what
    # is stored, and spam.get_config merges THAT over the seeded
    # defaults — an operator edit can never zero the rest), and
    # the Community Parts pool switch.
    if payload.spam is not None:
        stored = entitlements.get_setting(db, spam.CONFIG_KEY, None)
        merged = dict(stored) if isinstance(stored, dict) else {}
        spam_changes = payload.spam.model_dump(exclude_unset=True)
        for key, value in spam_changes.items():
            if key == "tiers" and isinstance(value, dict):
                tiers = dict(merged.get("tiers") or {})
                for tier, caps in value.items():
                    if isinstance(caps, dict):
                        tier_caps = dict(tiers.get(tier) or {})
                        tier_caps.update(
                            {k: v for k, v in caps.items() if v is not None}
                        )
                        tiers[tier] = tier_caps
                merged["tiers"] = tiers
            elif value is not None:
                merged[key] = value
        entitlements.set_setting(db, spam.CONFIG_KEY, merged)
        changes.append((spam.CONFIG_KEY, {"fields": sorted(spam_changes)}))
    if payload.community_parts_pool_enabled is not None:
        entitlements.set_setting(
            db, parts_pool.POOL_ENABLED_KEY, payload.community_parts_pool_enabled
        )
        changes.append(
            (parts_pool.POOL_ENABLED_KEY, payload.community_parts_pool_enabled)
        )
    if payload.community_marketplace_enabled is not None:
        entitlements.set_setting(
            db,
            marketplace_service.MARKETPLACE_ENABLED_KEY,
            payload.community_marketplace_enabled,
        )
        changes.append(
            (
                marketplace_service.MARKETPLACE_ENABLED_KEY,
                payload.community_marketplace_enabled,
            )
        )
    if payload.community_forum_enabled is not None:
        entitlements.set_setting(
            db,
            forum_service.FORUM_ENABLED_KEY,
            payload.community_forum_enabled,
        )
        changes.append(
            (
                forum_service.FORUM_ENABLED_KEY,
                payload.community_forum_enabled,
            )
        )
    if payload.claim_readiness_nudges_enabled is not None:
        entitlements.set_setting(
            db,
            readiness.READINESS_ENABLED_KEY,
            payload.claim_readiness_nudges_enabled,
        )
        changes.append(
            (
                readiness.READINESS_ENABLED_KEY,
                payload.claim_readiness_nudges_enabled,
            )
        )
    if payload.claim_readiness_interval_days is not None:
        entitlements.set_setting(
            db,
            readiness.READINESS_INTERVAL_KEY,
            payload.claim_readiness_interval_days,
        )
        changes.append(
            (
                readiness.READINESS_INTERVAL_KEY,
                payload.claim_readiness_interval_days,
            )
        )
    # Truck payments (wave 2): the Connect switch + platform fee.
    if payload.payments_connect_enabled is not None:
        entitlements.set_setting(
            db,
            truck_agreement.CONNECT_ENABLED_KEY,
            payload.payments_connect_enabled,
        )
        changes.append(
            (
                truck_agreement.CONNECT_ENABLED_KEY,
                payload.payments_connect_enabled,
            )
        )
    if payload.payments_truck_fee_percent is not None:
        entitlements.set_setting(
            db,
            truck_agreement.TRUCK_FEE_PERCENT_KEY,
            payload.payments_truck_fee_percent,
        )
        changes.append(
            (
                truck_agreement.TRUCK_FEE_PERCENT_KEY,
                payload.payments_truck_fee_percent,
            )
        )
    if payload.nav_new_badges is not None:
        # The NEW-badge registry (release machinery, 2026-11-08):
        # the whole map is replaced by what the operator sends;
        # a malformed map is refused whole, never half-stored.
        if not nav_badges.valid_badge_map(payload.nav_new_badges):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "nav_new_badges must map nav item keys to "
                    "release dates (YYYY-MM-DD)."
                ),
            )
        nav_badges.set_nav_badges(db, payload.nav_new_badges)
        changes.append((nav_badges.NAV_BADGES_KEY, payload.nav_new_badges))
    for key, value in changes:
        audit.record(
            db,
            operator,
            action="setting.update",
            target=key,
            detail={"value": value},
        )
    return _settings_view(db)


# -- the teaser video (owner refinement, 2026-10-26) -----------------
#
# The current Facebook-teaser trailer also plays on the teaser
# page. Set/replace runs the site's standard upload shape —
# presigned PUT straight to object storage, then a complete call
# that verifies the stored object before the settings point at
# it — and clear empties the slot (the page then renders with no
# video element at all). core/teaser.py owns the keys + caps.


def _delete_teaser_objects(keys: tuple[str, str]) -> None:
    """Best-effort storage cleanup for replaced/cleared assets:
    a failed delete must never fail the settings change itself."""
    for key in keys:
        if key:
            try:
                storage.delete(key)
            except StorageError:
                pass


@router.post(
    "/settings/teaser-video/upload-url",
    response_model=schemas.TeaserVideoUploadUrlView,
)
def teaser_video_upload_url(
    payload: schemas.TeaserVideoUploadUrlRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Mint a presigned PUT for one teaser asset. The MP4 is
    capped at the series' own 10 MiB; the poster frame at 2 MiB.
    Only the exact content types the page can play/show pass."""
    content_type = payload.content_type.lower().strip()
    if payload.kind == "video":
        if content_type != teaser.VIDEO_CONTENT_TYPE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The teaser video must be an MP4 file.",
            )
        if payload.size_bytes > teaser.VIDEO_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The teaser video is over the 10 MB series limit.",
            )
    else:
        if content_type not in teaser.POSTER_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The poster frame must be a WebP, JPEG, or PNG image.",
            )
        if payload.size_bytes > teaser.POSTER_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The poster frame is over the 2 MB limit.",
            )
    key = storage.object_key(
        "site", "teaser", payload.kind, payload.filename, collection="assets"
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return {"upload_url": url, "key": key, "expires_in": 900}


@router.post("/settings/teaser-video/complete", response_model=schemas.SettingsView)
def teaser_video_complete(
    payload: schemas.TeaserVideoCompleteRequest,
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Register the uploaded objects as the current teaser video.

    Both objects are verified against storage before anything
    moves: the key must be one this flow minted (prefix), the
    object must exist, its real content type and size must fit,
    and the video's bytes must carry the MP4 `ftyp` box — a
    renamed file never reaches the public page. The replaced
    objects are deleted after the settings move."""
    if not payload.key.startswith(teaser.VIDEO_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That video key wasn't issued for the teaser slot.",
        )
    try:
        stored = storage.head(payload.key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded video wasn't found in storage.",
        ) from exc
    if stored.content_type != teaser.VIDEO_CONTENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The stored file isn't an MP4 video.",
        )
    if stored.size_bytes > teaser.VIDEO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The teaser video is over the 10 MB series limit.",
        )
    prefix = storage.fetch_prefix(payload.key, 16)
    if len(prefix) < 8 or prefix[4:8] != b"ftyp":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The stored file doesn't look like an MP4 video.",
        )
    if payload.poster_key:
        if not payload.poster_key.startswith(teaser.POSTER_KEY_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That poster key wasn't issued for the teaser slot.",
            )
        try:
            poster = storage.head(payload.poster_key)
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The uploaded poster wasn't found in storage.",
            ) from exc
        if poster.content_type not in teaser.POSTER_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The stored poster isn't a WebP, JPEG, or PNG image.",
            )
        if poster.size_bytes > teaser.POSTER_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The poster frame is over the 2 MB limit.",
            )
    old_keys = teaser.set_current_video(
        db,
        video_key=payload.key,
        poster_key=payload.poster_key,
        name=payload.name.strip(),
    )
    _delete_teaser_objects(old_keys)
    audit.record(
        db,
        operator,
        action="settings.teaser_video_set",
        target="teaser",
        detail={"name": payload.name.strip()},
    )
    return _settings_view(db)


@router.delete("/settings/teaser-video", response_model=schemas.SettingsView)
def teaser_video_clear(
    operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Empty the slot: the settings forget the keys and the
    stored objects are deleted. The teaser page renders complete
    without any video element."""
    old_keys = teaser.clear_current_video(db)
    _delete_teaser_objects(old_keys)
    audit.record(
        db,
        operator,
        action="settings.teaser_video_clear",
        target="teaser",
        detail={},
    )
    return _settings_view(db)


# -- audit -------------------------------------------------------------------------


@router.get("/audit", response_model=schemas.AuditPage)
def list_audit(
    actor: str | None = Query(default=None, max_length=320),
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """The audit trail, read-only: newest first, filterable by
    actor (email or id), action, and date window."""
    rows, total = audit.list_entries(
        db,
        actor=actor,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "actor_email": row.actor_email,
                "action": row.action,
                "target": row.target,
                "detail": row.detail or {},
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# -- admin Home widgets (admin lane, owner 2026-11-06) -----------------
# ONE bag for the five god + moderator_admin Home widgets
# (support tickets, bug reports, feature requests, forum
# moderator, site stats). The gate is the panel's own
# require_user_manager (operator OR moderator-admin tier), so
# the full bag travels only to admin seats — the widgets
# themselves never render for anyone else (their definitions
# are tier-gated on the client), and this endpoint refuses
# lower tiers outright. Per-stat toggles are client layout
# settings; the numbers all come from core/site_stats, whose
# docstring states which figures derive from timestamps and
# which ride the daily snapshot.


@router.get("/home-widgets")
def admin_home_widgets(
    _manager: CurrentUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    from app.modules.core import site_stats

    return site_stats.home_widgets_payload(db)


# -- site pulse (sweep lane D4, owner idea 5) --------------------------
# ONE aggregate read for the Admin → Site pulse page: signups,
# downloads activity, new print listings, AI calls + cost, and
# the attention strip — every number from data the system
# already keeps (core/site_pulse names the source per number).
# The gate is the admin surface's own require_operator, exactly
# like its sibling sections: the numbers never travel to a
# non-operator seat, moderator admins included.


@router.get("/site-pulse")
def admin_site_pulse(
    _operator: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    from app.modules.core import site_pulse

    return site_pulse.pulse_payload(db)
