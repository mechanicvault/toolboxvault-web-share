"""Core module routes: health, signup, login, refresh, logout, verify,
me, change-password, account-type, layouts, sessions, export,
redeem, account deletion.

Social login (Google/Facebook) lives in oauth_routes.py, mounted below
at /auth. HTTP layer only — business logic lives in service.py.
"""

import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.rate_limit import (
    login_rate_limiter,
    password_reset_rate_limiter,
    signup_unlock_rate_limiter,
    tier_conversion_rate_limiter,
)
from app.core.security import (
    create_access_token,
    create_signup_unlock_token,
    create_visitor_token,
)
from app.modules.billing import codes as billing_codes
from app.modules.billing import entitlements as billing_entitlements
from app.modules.billing import schemas as billing_schemas
from app.modules.core import export as export_service
from app.modules.core import global_search, inbox_routes, landing, models, oauth_routes, schemas, service, teaser, tier_conversion
from app.modules.core.account_types import resolve_self_serve_set
from app.modules.core import history_routes
from app.modules.core import insurance_routes
from app.modules.core import cloud_routes
from app.modules.core import crew_routes
from app.modules.core import insurer_routes
from app.modules.core import money_routes
from app.modules.core import module_control
from app.modules.core import module_routes, peer_sharing_routes, sharing_routes
from app.modules.core import onboarding_routes
from app.modules.core import tiers as tiers_mod

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(oauth_routes.router, prefix="/auth")
router.include_router(inbox_routes.router)
router.include_router(module_routes.router)
router.include_router(onboarding_routes.router)
# Peer routes register BEFORE the tier-sharing group routes: their
# literal "/sharing/peer/..." paths must win over parameterized ones.
router.include_router(peer_sharing_routes.router)
router.include_router(sharing_routes.router)
router.include_router(history_routes.router)
router.include_router(insurance_routes.router)
router.include_router(money_routes.router)
router.include_router(crew_routes.router)
router.include_router(insurer_routes.router)
router.include_router(cloud_routes.router)
router.include_router(global_search.router)


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "core", "status": "ok"}


@router.get("/landing", response_model=schemas.LandingPublicView)
def landing_public(db: Session = Depends(get_db)):
    """The anonymous landing page's config — NO auth, by design:
    the response model is the whole disclosure (display prices,
    the trial switch + copy, store URLs, the catalog's free item
    limit; see core/landing.py for the honesty rules). Like the
    OAuth-providers probe, this is how the signed-out frontend
    learns what it may show."""
    return landing.public_landing(db)


@router.get("/signup-gate", response_model=schemas.SignupGateView)
def signup_gate(request: Request, db: Session = Depends(get_db)):
    """The signup door's public posture (teaser build, 2026-10-26):
    is teaser mode on, and does THIS browser already hold a valid
    unlock? Two booleans — the page renders its locked or open
    state from this and nothing more is disclosed."""
    return {
        "teaser_mode": teaser.teaser_enabled(db),
        "unlocked": teaser.has_valid_unlock(request),
    }


@router.post("/visit", response_model=schemas.VisitCountView)
def record_visit(request: Request, response: Response, db: Session = Depends(get_db)):
    """The teaser page's unique-visitor counter (owner order,
    2026-10-26): the page calls this once on load and renders the
    returned count as bare digits. The counting rules — counted
    cookie, automation and operator-IP exclusions, teaser-on
    only — live in core/teaser.py; here we only mint the counted
    cookie when the service says this browser was just counted.
    No auth: the count is public by design, and the response
    carries nothing but the number."""
    count, counted = teaser.record_visit(db, request)
    if counted:
        response.set_cookie(
            teaser.COUNT_COOKIE,
            create_visitor_token(),
            max_age=teaser.COUNT_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.app_base_url.startswith("https://"),
            path="/",
        )
    return {"count": count}


@router.post("/signup-unlock", response_model=schemas.SignupGateView)
def signup_unlock(
    payload: schemas.SignupUnlockRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Trade the gate code for a short-lived unlock cookie.

    The code is compared on the server (core/teaser.py) and never
    echoed; a right answer sets an httpOnly cookie carrying a
    signed 30-minute token (app.core.security) that BOTH signup
    doors check. Wrong answers are rate-limited per client IP on
    the login limiter's shape, so the short code can't be ground
    through. With teaser mode off the door is simply open — the
    endpoint answers unlocked and sets nothing."""
    if not teaser.teaser_enabled(db):
        return {"teaser_mode": False, "unlocked": True}
    client_ip = request.client.host if request.client else "unknown"
    limit_key = f"unlock:{client_ip}"
    retry_after = signup_unlock_rate_limiter.retry_after(limit_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many code attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    if not teaser.code_matches(db, payload.code):
        signup_unlock_rate_limiter.record_failure(limit_key)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_gate_code",
                "message": "That code isn't right. Check it and try again.",
            },
        )
    signup_unlock_rate_limiter.record_success(limit_key)
    response.set_cookie(
        teaser.UNLOCK_COOKIE,
        create_signup_unlock_token(),
        max_age=teaser.UNLOCK_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.app_base_url.startswith("https://"),
        path="/",
    )
    return {"teaser_mode": True, "unlocked": True}


# -- tier conversion (downloads level → normal, 2026-11-10) -----
#
# The doors OUT of the limited level for an account that was born
# into it (core/tier_conversion.py owns the model). The signup
# gate only ever decided what a NEW account is; these endpoints
# serve the EXISTING limited account that later receives the code
# — or, lacking one, files its one request for a god account's
# decision (the admin queue lives in admin_routes.py).


def _conversion_account(db: Session, user: CurrentUser) -> models.User:
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


def _require_downloads_rung(account: models.User) -> None:
    """Both conversion doors exist for the limited level alone.
    Any other rung already holds what a conversion would grant,
    so the answer is a clean refusal — no state change, and the
    throttle/code machinery is never even reached."""
    if tiers_mod.resolved_tier(account) != "downloads":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_full_access",
                "message": "This account already has full access.",
            },
        )


@router.post("/convert-with-code", response_model=schemas.TierConversionView)
def convert_with_code(
    payload: schemas.AccessCodeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trade the gate code for the normal rung. The comparison is
    the signup gate's own (teaser.code_matches — one comparison
    for the whole site, the code never echoed). Wrong answers
    are rate-limited per ACCOUNT (tier_conversion_rate_limiter),
    so the short code can't be ground through; the refusal names
    nothing but the miss."""
    account = _conversion_account(db, user)
    _require_downloads_rung(account)
    limit_key = f"convert:{account.id}"
    retry_after = tier_conversion_rate_limiter.retry_after(limit_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many code attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    if not teaser.code_matches(db, payload.code):
        tier_conversion_rate_limiter.record_failure(limit_key)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_gate_code",
                "message": "That code isn't right. Check it and try again.",
            },
        )
    tier_conversion_rate_limiter.record_success(limit_key)
    tier_conversion.convert_account(
        db, account, via=tier_conversion.VIA_ACCESS_CODE, actor=user
    )
    return {"tier": tiers_mod.resolved_tier(account)}


@router.get(
    "/conversion-request", response_model=schemas.ConversionRequestStateView
)
def conversion_request_state(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's one-request state (status None = never
    asked). Any rung may read it — the flow surface renders the
    account's standing from this one shape."""
    row = tier_conversion.get_request(db, user.id)
    if row is None:
        return {"status": None, "requested_at": None, "decided_at": None}
    return {
        "status": row.status,
        "requested_at": row.created_at,
        "decided_at": row.decided_at,
    }


@router.post(
    "/conversion-request",
    response_model=schemas.ConversionRequestStateView,
    status_code=201,
)
def create_conversion_request(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File the account's ONE request for full access (owner's
    anti-spam rule: one per account, ever — a denial does not
    free the slot). God accounts are notified through the inbox;
    the decision comes back the same way."""
    account = _conversion_account(db, user)
    _require_downloads_rung(account)
    try:
        row = tier_conversion.create_request(db, account)
    except tier_conversion.AlreadyRequested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_requested",
                "message": "You've already sent your request.",
            },
        ) from None
    return {
        "status": row.status,
        "requested_at": row.created_at,
        "decided_at": row.decided_at,
    }


def _token_response(
    user: models.User, db: Session, user_agent: str | None = None
) -> schemas.TokenResponse:
    """Access token + a fresh refresh token for a just-authenticated user."""
    access_token, refresh_token = service.issue_session(
        db, user, user_agent=user_agent
    )
    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/signup", response_model=schemas.UserPublic, status_code=201)
def signup(
    payload: schemas.SignupRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # The teaser gate's question (2026-10-26; OPEN SIGNUP
    # 2026-11-09): the gate no longer refuses a no-code signup —
    # it decides the new account's RUNG. A browser holding the
    # signup unlock (the operator code) creates a normal account,
    # the full site as always; without one, the account is born
    # on the downloads level (core/tiers.py). Resolved here, at
    # the door itself, before every other check, so the rung can
    # never depend on anything the caller sent.
    birth_tier = teaser.signup_tier(db, request)
    # Ban check first (admin panel): a banned address gets the same
    # refusal whatever else is true of it — no existence oracle.
    if service.is_email_banned(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This email address can't be used to create an account.",
        )
    if service.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )
    # Referral capture: resolve the code (a referrer's account
    # number) if one was supplied. Unknown codes are ignored —
    # signup must never fail over a referral.
    referred_by_id = None
    if payload.referral_code and payload.referral_code.strip():
        referrer = service.get_user_by_account_number(db, payload.referral_code)
        if referrer is not None:
            referred_by_id = referrer.id
    user = service.create_user(
        db,
        payload.email,
        payload.name,
        payload.password,
        list(payload.account_types),
        referred_by_id=referred_by_id,
        country=payload.country,
        currency=payload.currency,
        locale=payload.locale,
        tier=birth_tier,
    )
    # Signup module choices (2026-10-24): the modules the new user
    # unchecked land off from the first sign-in. The helper never
    # raises and ignores unknown/always-on/unentitled ids — a
    # module choice can never fail a signup.
    module_control.apply_signup_module_choices(
        db, user, list(payload.disabled_modules or [])
    )
    try:
        service.start_email_verification(db, user)
    except Exception:  # a mail hiccup must never fail a signup
        logger.exception("Could not start email verification for user %s", user.id)
    return user


@router.post("/login", response_model=schemas.TokenResponse)
def login(
    payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    limit_key = f"{client_ip}:{payload.email.lower()}"
    retry_after = login_rate_limiter.retry_after(limit_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    # Ban check before the password check (admin panel): the owner
    # wants a banned address told plainly that it's blocked — and a
    # ban is an operator's deliberate act, not a secret to protect.
    if service.is_email_banned(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This email address has been blocked from Toolbox Vault. "
                "If you think this is a mistake, contact support."
            ),
        )
    user = service.authenticate(db, payload.email, payload.password)
    if user is None:
        login_rate_limiter.record_failure(limit_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    # Deactivation is checked only AFTER the password verifies, so
    # the refusal never confirms an account exists to a stranger.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account has been deactivated. "
                "If you think this is a mistake, contact support."
            ),
        )
    # Verification launch switch (auth.require_email_verification,
    # Admin → Settings; default OFF — flip at launch): unverified
    # password-signup accounts can't sign in until the address is
    # confirmed. OAuth accounts are exempt by construction (their
    # provider verified the address, so email_verified is already
    # True). The structured detail carries a code so the login
    # page offers the resend action instead of a dead end.
    if billing_entitlements.email_verification_required(db) and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_unverified",
                "message": (
                    "Your email address isn't verified yet. Open the "
                    "verification link we sent when you signed up — "
                    "or resend it below."
                ),
            },
        )
    login_rate_limiter.record_success(limit_key)
    return _token_response(user, db, user_agent=request.headers.get("user-agent"))


@router.post("/refresh", response_model=schemas.TokenResponse)
def refresh(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new token pair. The presented token
    is revoked in the exchange (rotation) — it can never be used twice."""
    rotated = service.rotate_refresh_token(db, payload.refresh_token)
    if rotated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user, new_plain = rotated
    return schemas.TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=new_plain,
    )


@router.post("/logout", status_code=204)
def logout(payload: schemas.LogoutRequest, db: Session = Depends(get_db)):
    """Revoke the presented refresh token. Always 204 — no oracle."""
    service.revoke_refresh_token(db, payload.refresh_token)


@router.get("/verify-email", response_model=dict[str, str])
def verify_email(
    token: str = Query(min_length=1), db: Session = Depends(get_db)
):
    if not service.verify_email(db, token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That verification link is invalid or has expired",
        )
    return {"detail": "Email verified"}


# -- password reset + email change + verification resend ----------------------
#
# The email flows (email phase, 2026-10-18). The two public doors
# that SEND email share one request budget (per IP+email and per
# email) — sending mail on an attacker's say-so is the abuse these
# endpoints would otherwise invite.


def _email_send_rate_check(request: Request, email: str) -> None:
    """Count one request against the email-send budget; raise 429
    when either key (this IP + this address, or this address from
    anywhere) is spent. Every request counts — allowed or not,
    account or not — so the budget itself can't be probed for
    account existence."""
    client_ip = request.client.host if request.client else "unknown"
    keys = [f"{client_ip}:{email.lower()}", f"email:{email.lower()}"]
    for key in keys:
        retry_after = password_reset_rate_limiter.retry_after(key)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many email requests. Wait a while and try again.",
                headers={"Retry-After": str(retry_after)},
            )
    for key in keys:
        password_reset_rate_limiter.record_hit(key)


@router.post("/password-reset/request", response_model=dict[str, str])
def request_password_reset(
    payload: schemas.PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Ask for a reset link. ALWAYS the same answer, account or
    not — the endpoint must never confirm an address is
    registered. The service sends only for a live, unbanned
    account; every other case is silence that looks identical."""
    _email_send_rate_check(request, payload.email)
    service.request_password_reset(db, payload.email)
    return {
        "detail": (
            "If an account exists for that email, we've sent a link "
            "to reset its password."
        )
    }


@router.post("/password-reset/confirm", response_model=dict[str, str])
def confirm_password_reset(
    payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)
):
    """Consume a reset link and set the new password. The holder
    of the link proved inbox control, so failures say exactly
    what happened (invalid / used / expired / blocked)."""
    result = service.reset_password(db, payload.token, payload.new_password)
    if result == "ok":
        return {
            "detail": "Your password has been reset. Sign in with your new password."
        }
    errors = {
        "invalid": (
            status.HTTP_400_BAD_REQUEST,
            "That reset link is invalid. Request a new one and try again.",
        ),
        "used": (
            status.HTTP_400_BAD_REQUEST,
            "That reset link was already used. Request a new one if you "
            "still need to reset your password.",
        ),
        "expired": (
            status.HTTP_400_BAD_REQUEST,
            "That reset link has expired. Request a new one and try again.",
        ),
        "blocked": (
            status.HTTP_403_FORBIDDEN,
            "This account can't reset its password. If you think this "
            "is a mistake, contact support.",
        ),
    }
    code, detail = errors[result]
    raise HTTPException(status_code=code, detail=detail)


@router.post("/resend-verification", response_model=dict[str, str])
def resend_verification(
    payload: schemas.ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Resend the signup verification link (the login page's
    answer to the verification gate). Same generic-answer rule
    as the reset request: the email goes out only when the
    account exists and still needs verifying."""
    _email_send_rate_check(request, payload.email)
    user = service.get_user_by_email(db, payload.email)
    if (
        user is not None
        and user.is_active
        and not user.email_verified
        and not service.is_email_banned(db, user.email)
    ):
        try:
            service.start_email_verification(db, user)
        except Exception:  # a mail hiccup must not leak or fail the door
            logger.exception("Could not resend verification for user %s", user.id)
    return {
        "detail": (
            "If that account still needs verifying, we've sent a "
            "fresh verification link."
        )
    }


@router.post("/me/resend-verification", status_code=204)
def resend_my_verification(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Settings → Profile's resend: the signed-in unverified
    account asks for a fresh link for ITSELF. A verified account
    is a no-op (204 either way — the UI state already agrees)."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    if not account.email_verified:
        service.start_email_verification(db, account)


@router.get("/email-change", response_model=schemas.EmailChangeState)
def get_email_change(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's pending email change (Settings → Profile)."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    pending = service.pending_email_change(db, account)
    if pending is None:
        return {"pending_email": None, "expires_at": None}
    return {"pending_email": pending.new_email, "expires_at": pending.expires_at}


@router.post("/email-change/request", response_model=schemas.EmailChangeState)
def request_email_change(
    payload: schemas.EmailChangeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an email change: verify the current password (when
    the account has one), then send the confirmation link to the
    NEW address. The address itself moves only at confirm."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    result = service.request_email_change(
        db, account, payload.new_email, payload.current_password
    )
    if result == "ok":
        pending = service.pending_email_change(db, account)
        return {
            "pending_email": pending.new_email if pending else None,
            "expires_at": pending.expires_at if pending else None,
        }
    errors = {
        "wrong_password": (
            status.HTTP_400_BAD_REQUEST,
            "Current password is incorrect.",
        ),
        "same": (
            status.HTTP_400_BAD_REQUEST,
            "That's already your email address.",
        ),
        "taken": (
            status.HTTP_409_CONFLICT,
            "An account with that email already exists.",
        ),
        "banned": (
            status.HTTP_403_FORBIDDEN,
            "This email address can't be used.",
        ),
    }
    code, detail = errors[result]
    raise HTTPException(status_code=code, detail=detail)


@router.delete("/email-change", status_code=204)
def cancel_email_change(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel the pending change (the sent link dies with it).
    204 whether or not one was pending — cancel is idempotent."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    service.cancel_email_change(db, account)


@router.post(
    "/email-change/confirm", response_model=schemas.EmailChangeConfirmResponse
)
def confirm_email_change(
    payload: schemas.EmailChangeConfirm, db: Session = Depends(get_db)
):
    """Consume the confirmation link and move the address. No
    session is required — the emailed token IS the credential
    (it was sent to the new inbox); when the confirming browser
    is signed in it passes its refresh token so its own session
    survives the change."""
    result, account = service.confirm_email_change(
        db, payload.token, payload.refresh_token
    )
    if result == "ok" and account is not None:
        return {
            "detail": "Your email address has been changed.",
            "email": account.email,
        }
    errors = {
        "invalid": (
            status.HTTP_400_BAD_REQUEST,
            "That confirmation link is invalid. Start the change again "
            "from Settings.",
        ),
        "used": (
            status.HTTP_400_BAD_REQUEST,
            "That confirmation link was already used. If the change "
            "didn't happen, start it again from Settings.",
        ),
        "expired": (
            status.HTTP_400_BAD_REQUEST,
            "That confirmation link has expired. Start the change "
            "again from Settings.",
        ),
        "taken": (
            status.HTTP_409_CONFLICT,
            "That email address was claimed by another account before "
            "this change was confirmed. Start again with a different "
            "address.",
        ),
        "blocked": (
            status.HTTP_403_FORBIDDEN,
            "This account can't change its email address. If you think "
            "this is a mistake, contact support.",
        ),
    }
    code, detail = errors[result]
    raise HTTPException(status_code=code, detail=detail)


@router.post("/change-password", status_code=204)
def change_password(
    payload: schemas.ChangePasswordRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set or change the caller's password (Settings → Account & security).

    Brute-force surface = the current-password check, so it shares the
    login rate limiter (keyed IP + account email). A wrong current
    password is a plain 400 — the caller is already authenticated; this
    is not a credential oracle for anyone else.
    """
    client_ip = request.client.host if request.client else "unknown"
    limit_key = f"{client_ip}:{user.email.lower()}"
    retry_after = login_rate_limiter.retry_after(limit_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    changed = service.change_password(
        db,
        account,
        payload.current_password,
        payload.new_password,
        payload.refresh_token,
    )
    if not changed:
        login_rate_limiter.record_failure(limit_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    login_rate_limiter.record_success(limit_key)


@router.post("/account-type", response_model=schemas.UserPublic)
def set_account_type(
    payload: schemas.AccountTypeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set (first pick) or replace the caller's group set.

    Self-serve: the one-time "choose your groups" prompt and the
    Settings editor both post here. The account number is NOT
    touched — it is final at creation and never changes (sweep
    fix 10-F12). An empty set never gets here — the schema
    refuses it with a 422.
    """
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    # A group-waived rung (tiers.py — the downloads level) holds
    # no account groups BY DESIGN: the pick is not a step it has,
    # so the self-serve door refuses it outright rather than
    # writing a set the rung's entitlement never reads. An admin
    # moving the account off the rung (the ordinary tier grant)
    # restores this door with the rung.
    if tiers_mod.group_layer_waived(tiers_mod.resolved_tier(account)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This account level doesn't use account groups",
        )
    # Self-serve picks control only the self-serve groups (owner
    # directive 2026-10-31: insurance is not pickable, and a group an
    # operator assigned outside the self-serve list is preserved —
    # it can neither be added nor removed from here).
    merged = resolve_self_serve_set(
        list(payload.account_types), list(account.account_types or ())
    )
    if not merged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pick at least one account group",
        )
    return service.set_account_types(db, account, merged)


@router.get("/me", response_model=schemas.UserPublic)
def me(user: CurrentUser = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=schemas.UserPublic)
def update_me(
    payload: schemas.ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit the caller's profile: the display name and the
    community contact preferences (Settings → Public profile &
    contact). Only the fields sent are applied. Email is
    display-only here: changing it safely requires confirming the
    NEW address by email (the email-change flow)."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    fields = payload.model_dump(exclude_unset=True)
    # Settings follow reach (owner ruling, 2026-11-09): two of
    # this endpoint's fields are MODULE settings wearing profile
    # clothes — the Add-wizard defaults belong to Inventory, and
    # the community-catalog contribution switch belongs to the
    # Catalog module. An account that cannot reach the module
    # cannot change its settings (the typeless-account settings
    # invariant, generalized: the check is the same
    # effective_for_user gate every module route uses, with the
    # caller's own rung/groups — god's bypass included). The
    # refusal is the module gate's own shape, so the client
    # reads it exactly like a refused module door.
    for field, module_id in (
        ("wizard_defaults", "inventory"),
        ("catalog_contribute", "catalog"),
    ):
        if field in fields and fields[field] is not None:
            if not module_control.effective_for_user(
                db,
                module_id,
                user.account_types,
                user_id=user.id,
                tier=user.tier,
                beta_tester=user.beta_tester,
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "module_unavailable",
                        "module": module_id,
                        "message": "This module isn't enabled for your account.",
                    },
                )
    if "name" in fields and fields["name"] is not None and not fields["name"].strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name must not be empty.",
        )
    updated = service.update_profile(db, account, fields)
    # The response serializes the CurrentUser principal; rebuild it
    # from the updated row so the community fields answer fresh.
    return CurrentUser(
        id=updated.id,
        account_number=updated.account_number,
        email=updated.email,
        name=updated.name,
        email_verified=updated.email_verified,
        created_at=updated.created_at,
        password_login_enabled=updated.password_login_enabled,
        account_types=tuple(updated.account_types or ()),
        is_operator=bool(updated.is_operator),
        role=tiers_mod.role_for_tier(tiers_mod.resolved_tier(updated)),
        tier=tiers_mod.resolved_tier(updated),
        beta_tester=bool(updated.beta_tester),
        public_area_label=updated.public_area_label or "",
        contact_phone=updated.contact_phone or "",
        show_phone=bool(updated.show_phone),
        silence_claim_readiness_nudges=bool(
            updated.silence_claim_readiness_nudges
        ),
        phone=updated.phone or "",
        postal_address=updated.postal_address or "",
        country=updated.country or "",
        currency=updated.currency or "USD",
        locale=updated.locale or "",
        catalog_contribute=bool(updated.catalog_contribute),
        appearance_mode=updated.appearance_mode,
        appearance_accent=updated.appearance_accent,
        appearance_accent_light=updated.appearance_accent_light,
        appearance_theme=updated.appearance_theme,
        wizard_defaults=updated.wizard_defaults,
        rail_pinned=updated.rail_pinned,
    )


@router.delete("/me", status_code=204)
def delete_me(
    payload: schemas.DeleteAccountRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete the caller's account and everything it
    owns. Type-to-confirm: the body must carry the exact word
    DELETE — anything else is a refusal, so a stray request can
    never vaporize an account."""
    if payload.confirmation != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type DELETE to confirm permanent account deletion.",
        )
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    service.delete_account(db, account)


# -- sessions (Settings → Account & security) -------------------------------


@router.get("/sessions", response_model=list[schemas.SessionPublic])
def list_sessions(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_current_session: str | None = Header(default=None),
):
    """The caller's live sessions/devices. The client sends its own
    refresh token in X-Current-Session so the list can mark which
    session is this one (same trust as a refresh call)."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return service.list_sessions(db, account, x_current_session)


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sign out one session (its refresh chain head is revoked; its
    access tokens live out their short remainder, as everywhere)."""
    account = service.get_user_by_id(db, user.id)
    if account is None or not service.revoke_session(db, account, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found."
        )


@router.post("/sessions/revoke-others", response_model=dict[str, int])
def revoke_other_sessions(
    payload: schemas.RevokeOthersRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sign out everywhere else: every session but the caller's."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    ended = service.revoke_other_sessions(db, account, payload.refresh_token)
    return {"ended": ended}


# -- data export (user backup v1) --------------------------------------------


@router.get("/export")
def export_my_data(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download my data: one ZIP with the account's profile, tools,
    field definitions, sharing setup, and attachment files (or a
    manifest of links for any file storage couldn't hand over)."""
    account = service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    archive = export_service.build_export_zip(db, account)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="toolbox-vault-export.zip"'
        },
    )


# -- redeem codes (billing service; the path is core's by spec) --------------


@router.get(
    "/data-removal", response_model=list[schemas.DataRemovalCategoryView]
)
def data_removal_categories(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Audit A11: the removable categories with live counts and
    any guard refusal already visible."""
    from app.modules.core import data_removal

    account = service.get_user_by_id(db, user.id)
    return data_removal.summaries(db, account)


@router.post("/data-removal", response_model=schemas.DataRemovalResult)
def remove_data_category(
    payload: schemas.DataRemovalRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Audit A11: remove ONE category (typed confirmation = the
    category key). Guards refuse with 409 + the reason; the
    account and every other category stay intact."""
    from app.modules.core import data_removal

    account = service.get_user_by_id(db, user.id)
    try:
        return data_removal.remove_category(
            db, account, payload.category, payload.confirmation
        )
    except data_removal.RemovalRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))



@router.post("/redeem", response_model=billing_schemas.RedeemResponse)
def redeem_code(
    payload: billing_schemas.RedeemRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Redeem a code (free time, lifetime, trial, AI credits). The
    validation copy comes from the billing service — every refusal
    says the true reason."""
    try:
        summary = billing_codes.redeem(db, user.id, payload.code)
    except billing_codes.RedeemError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    messages = {
        "free_months": "Code applied — free time was added to your plan.",
        "free_year": "Code applied — a free year was added to your plan.",
        "lifetime": "Code applied — you have lifetime access. Welcome aboard.",
        "trial_months": "Code applied — your trial has started.",
        "trial_days": "Code applied — your trial has started.",
        "ai_credits": "Code applied — AI credits were added to your wallet.",
    }
    return {**summary, "message": messages.get(summary["kind"], "Code applied.")}


# Page keys name frontend pages ("home", later "inventory", …): lower
# snake/kebab, bounded length. Anything else is a client bug → 422.
PageKey = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


@router.get(
    "/layouts/{page_key}",
    response_model=schemas.PageLayoutResponse,
    response_model_exclude_none=True,
)
def get_layout(
    page_key: PageKey,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's stored layout for a page. `blocks` is empty when
    they have never customized it — the client renders the page's
    registered defaults. Owner-scoped: layouts are only ever read and
    written through the caller's own id."""
    blocks = service.get_page_layout(db, user.id, page_key)
    return {"page_key": page_key, "blocks": blocks or []}


@router.put(
    "/layouts/{page_key}",
    response_model=schemas.PageLayoutResponse,
    response_model_exclude_none=True,
)
def put_layout(
    page_key: PageKey,
    payload: schemas.PageLayoutSave,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save the caller's layout for a page (wholesale replace). Block
    keys are opaque to the server; the service dedupes by key and caps
    the stored list."""
    blocks = service.save_page_layout(
        db, user.id, page_key, [b.model_dump() for b in payload.blocks]
    )
    return {"page_key": page_key, "blocks": blocks}


@router.get("/header-stats", response_model=dict)
def get_header_stats(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The Home header-stats catalog as THIS caller may see it
    (Lane 3, 2026-11-10): the reachable stat keys, enumerated
    server-side from the caller's effective reach, plus the
    server-computed values for the staff stats that have no
    module endpoint of their own. See header_stats.py."""
    from app.modules.core import header_stats

    return header_stats.header_stats_payload(db, user)
