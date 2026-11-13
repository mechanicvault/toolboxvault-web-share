"""Social-login routes: provider discovery, start, and callback.

Mounted inside the core router at /auth, so full paths are
/api/core/auth/... HTTP layer only — provider verification lives in
oauth.py, account/session logic in service.py.

Flow: start 302s to the provider with a signed state token; the
provider returns the user to the callback, which verifies state +
identity, resolves the local account, and 302s to the SPA's
/auth/callback with the token pair in the URL fragment (fragments are
never sent to servers, so tokens stay out of access logs and Referer
headers). Every failure takes the same generic exit —
/login?error=oauth — with no provider details leaked.
"""

import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    create_oauth_state_token,
    read_oauth_state_next,
    verify_oauth_state_token,
)
from app.modules.core import models, oauth, schemas, service, teaser

logger = logging.getLogger(__name__)

router = APIRouter()


def _failure_redirect() -> RedirectResponse:
    return RedirectResponse(
        url=f"{settings.app_base_url}/login?error=oauth",
        status_code=status.HTTP_302_FOUND,
    )


def _success_redirect(
    db: Session,
    user: models.User,
    user_agent: str | None = None,
    next_path: str | None = None,
) -> RedirectResponse:
    access_token, refresh_token = service.issue_session(
        db, user, user_agent=user_agent
    )
    fragment = f"access_token={access_token}&refresh_token={refresh_token}"
    # Sweep C2 completion: the kept destination rides the fragment
    # beside the tokens (fragments never reach a server or a log);
    # OAuthCallbackPage validates it again before honouring it.
    if next_path:
        fragment += f"&next={urllib.parse.quote(next_path, safe='')}"
    return RedirectResponse(
        url=f"{settings.app_base_url}/auth/callback#{fragment}",
        status_code=status.HTTP_302_FOUND,
    )


def _finish(
    db: Session,
    identity: dict[str, str],
    user_agent: str | None = None,
    request: Request | None = None,
    next_path: str | None = None,
) -> RedirectResponse:
    # Teaser gate (2026-10-26; OPEN SIGNUP 2026-11-09): social
    # find-or-create is an account-creation door like any other,
    # and it asks the gate the same question the email door asks —
    # not WHETHER this browser may create an account, but at what
    # RUNG: the unlock cookie (riding the provider round trip like
    # any same-site cookie) earns a normal account; without it a
    # NEW account is born on the downloads level. An EXISTING
    # account is a sign-in, not a creation — its rung never moves
    # here (resolve_oauth_user applies `tier` only on creation).
    birth_tier = (
        teaser.signup_tier(db, request) if request is not None else "normal"
    )
    # Ban/deactivation enforcement lives in resolve_oauth_user (it
    # refuses before find-or-create); here the refusals become the
    # login page's specific notices instead of the generic failure.
    try:
        user = service.resolve_oauth_user(
            db, identity["email"], identity["name"], tier=birth_tier
        )
    except service.EmailBannedError:
        return RedirectResponse(
            url=f"{settings.app_base_url}/login?error=banned",
            status_code=status.HTTP_302_FOUND,
        )
    except service.AccountDeactivatedError:
        return RedirectResponse(
            url=f"{settings.app_base_url}/login?error=deactivated",
            status_code=status.HTTP_302_FOUND,
        )
    return _success_redirect(db, user, user_agent=user_agent, next_path=next_path)


@router.get("/providers", response_model=schemas.OAuthProviders)
def providers() -> dict[str, bool]:
    """Which social providers are configured (the UI shows buttons
    only for these)."""
    return oauth.configured_providers()


# -- Google --------------------------------------------------------------------
@router.get("/google/start")
def google_start(
    next: str | None = Query(default=None),
) -> RedirectResponse:
    if not oauth.google_configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google sign-in is not configured",
        )
    # The optional kept destination is validated inside
    # create_oauth_state_token — an unsafe value mints a plain
    # state token, never an off-site ride.
    state = create_oauth_state_token("google", next)
    return RedirectResponse(
        url=oauth.google_authorization_url(state),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if (
        not oauth.google_configured()
        or error
        or not code
        or not state
        or not verify_oauth_state_token(state, "google")
    ):
        return _failure_redirect()
    try:
        identity = oauth.authenticate_google(code)
    except oauth.OAuthError:
        logger.warning("Google OAuth sign-in failed", exc_info=True)
        return _failure_redirect()
    return _finish(
        db,
        identity,
        user_agent=request.headers.get("user-agent"),
        request=request,
        next_path=read_oauth_state_next(state, "google"),
    )


# -- Facebook ------------------------------------------------------------------
@router.get("/facebook/start")
def facebook_start(
    next: str | None = Query(default=None),
) -> RedirectResponse:
    if not oauth.facebook_configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook sign-in is not configured",
        )
    state = create_oauth_state_token("facebook", next)
    return RedirectResponse(
        url=oauth.facebook_authorization_url(state),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/facebook/callback")
def facebook_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if (
        not oauth.facebook_configured()
        or error
        or not code
        or not state
        or not verify_oauth_state_token(state, "facebook")
    ):
        return _failure_redirect()
    try:
        identity = oauth.authenticate_facebook(code)
    except oauth.OAuthError:
        logger.warning("Facebook OAuth sign-in failed", exc_info=True)
        return _failure_redirect()
    return _finish(
        db,
        identity,
        user_agent=request.headers.get("user-agent"),
        request=request,
        next_path=read_oauth_state_next(state, "facebook"),
    )
