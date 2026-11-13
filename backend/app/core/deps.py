"""Shared FastAPI dependencies.

Universal request-level concerns (e.g. "who is the current user?") live here
so every module resolves them the same way.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.modules.core.account_types import ACCOUNT_TYPES
from app.modules.core.service import get_user_by_id, is_email_banned

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Lightweight principal: the ONLY user shape cross-module code sees.

    get_current_user returns this DTO instead of core's ORM User model, so
    a core table refactor cannot ripple into other modules (blueprint §4,
    Laws 4–5). Modules that need more than this go through core's service
    interface explicitly.
    """

    id: uuid.UUID
    account_number: str
    email: str
    name: str
    email_verified: bool
    created_at: datetime
    # Defaulted so existing constructions stay valid; get_current_user
    # always populates it from the account row.
    password_login_enabled: bool = True
    # The account's group set (core account_types vocabulary). Empty
    # tuple = not chosen yet. Group-gated routes check membership —
    # see require_account_type.
    account_types: tuple[str, ...] = ()
    # Operator flag (module doctrine, owner 2026-10-18): gates the
    # /api/admin/* surface. Defaulted False so existing constructions
    # stay valid; get_current_user always populates it.
    is_operator: bool = False
    # Community role (role ladder): user | moderator |
    # community_admin. Gates the messaging moderation queue.
    # Since the tier fold-in (2026-10-31) this is DERIVED from the
    # account's rung in get_current_user (core/tiers.role_for_tier),
    # so the moderation gates always read the tier's shadow.
    role: str = "user"
    # Account tier (owner design, 2026-10-31 — core/tiers.py): the
    # account's primary rung: normal | moderator | moderator_admin |
    # god. Drives the module switchboard's per-tier layer and the
    # admin grant rules. beta_tester is the stackable Beta Tester
    # upgrade flag (early access to beta-lit modules).
    tier: str = "normal"
    beta_tester: bool = False
    # Community contact preferences (2026-10-19): the coarse area
    # label, the publishable phone, and the show-phone opt-in —
    # carried here because /me serializes this DTO and the public
    # profile reads the same facts.
    public_area_label: str = ""
    contact_phone: str = ""
    show_phone: bool = False
    silence_claim_readiness_nudges: bool = False
    # Interface language (audit A17): "" = unset (fall back to
    # the country default, then English).
    locale: str = ""
    # Report contact details (reports alignment, 2026-10-19): the
    # owner's private phone + postal address for generated
    # paperwork; /me serializes this DTO, so Settings reads them
    # from here.
    phone: str = ""
    postal_address: str = ""
    # Country + currency (wave 3): the account's ISO country (""
    # = unset) and its currency — /me serializes this DTO, and
    # cross-user money surfaces read the viewer's currency here
    # for the approximate-hint math.
    country: str = ""
    currency: str = "USD"
    # Community catalog contribution (wave 4): the owner's opt-in
    # for the derived product catalog (default ON). /me serializes
    # this DTO, so Settings -> Sharing reads the switch here.
    catalog_contribute: bool = True
    # Appearance (owner ruling, 2026-10-25): the account-held
    # look — mode (dark|light), accent (hex), theme. All None
    # until the account first saves an appearance; /me
    # serializes this DTO, so the client hydrates its theme
    # state from here at sign-in and the account wins over any
    # browser-local value.
    appearance_mode: str | None = None
    appearance_accent: str | None = None
    # Per-mode accent (owner order, 2026-11-08): the LIGHT-mode
    # pick; None until the account picks a color in light mode.
    appearance_accent_light: str | None = None
    appearance_theme: str | None = None
    # Wizard defaults (Wizard Phase 1, 2026-10-25): the account's
    # saved Add-wizard setup (one JSON document) or None when
    # never saved; /me serializes this DTO so the wizard and
    # Settings -> Add-tool wizard defaults read it at sign-in.
    wizard_defaults: dict | None = None
    # Rail pin (widget options Wave 1, 2026-11-02): the account's
    # menu-pin choice — None until the account first sets it
    # (None reads as unpinned); /me serializes this DTO, so the
    # shell applies the choice at sign-in on every device.
    rail_pinned: bool | None = None


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Extract the user id from the Authorization: Bearer <token> header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return user_id


def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Resolve the bearer token to the caller's principal.

    NOTE: this imports the core module's *service* function — the sanctioned
    cross-module path — and converts the result to the CurrentUser DTO, so
    core's ORM model never crosses the module boundary.
    """
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    # Admin panel enforcement (Phase A2): deactivation and email
    # bans land on the very next request, not at the next sign-in —
    # an account an operator just switched off must not keep using
    # an already-issued access token. Both checks read the row this
    # function already loaded (the ban is one indexed lookup).
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )
    if is_email_banned(db, user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This email address has been blocked.",
        )
    # Audit trail attribution (2026-10-19): the change journal
    # stamps this user as the actor of everything the request
    # mutates, so entries can tell "you changed it" from "a peer /
    # the system changed it" — the restore engine only ever
    # rewinds the owner's own changes. The stamp rides the
    # SESSION (not a contextvar): FastAPI runs this dependency and
    # the endpoint in different context copies, and the journal
    # listener reads the session it flushes.
    db.info["journal_actor"] = user.id
    # The tier fold-in (2026-10-31): the rung resolves from the
    # stored tier (or the legacy derivation mid-deploy), the beta
    # flag rides along, and the community role is the rung's
    # shadow — never the raw column — so a tier change moves the
    # moderation gates in the same request.
    from app.modules.core import tiers as _tiers

    rung = _tiers.resolved_tier(user)
    return CurrentUser(
        id=user.id,
        account_number=user.account_number,
        email=user.email,
        name=user.name,
        email_verified=user.email_verified,
        created_at=user.created_at,
        password_login_enabled=user.password_login_enabled,
        account_types=tuple(user.account_types or ()),
        is_operator=bool(user.is_operator),
        role=_tiers.role_for_tier(rung),
        tier=rung,
        beta_tester=bool(getattr(user, "beta_tester", False)),
        public_area_label=user.public_area_label or "",
        contact_phone=user.contact_phone or "",
        show_phone=bool(user.show_phone),
        silence_claim_readiness_nudges=bool(
            user.silence_claim_readiness_nudges
        ),
        phone=user.phone or "",
        postal_address=user.postal_address or "",
        country=user.country or "",
        currency=user.currency or "USD",
        locale=user.locale or "",
        catalog_contribute=bool(user.catalog_contribute),
        appearance_mode=user.appearance_mode,
        appearance_accent=user.appearance_accent,
        appearance_accent_light=user.appearance_accent_light,
        appearance_theme=user.appearance_theme,
        wizard_defaults=user.wizard_defaults,
        rail_pinned=getattr(user, "rail_pinned", None),
    )


def require_account_type(*types: str):
    """Dependency factory: gate a route on the caller's group set.

    FOUNDATION SEAM (2026-10-17): modules declare the groups they
    serve by depending on this —

        @router.get("/dealer/accounts")
        def accounts(user=Depends(require_account_type("tool_dealer"))):
            ...

    Access is a UNION: the caller passes when ANY of the named groups
    is in their set (a mechanic who also deals passes a dealer gate).
    A caller with an empty set (group not chosen yet) or no matching
    group gets a 403. No route is gated yet — the mechanism ships
    ahead of the modules that will use it.
    """
    unknown = [t for t in types if t not in ACCOUNT_TYPES]
    if unknown:
        raise ValueError(f"Unknown account type(s): {', '.join(unknown)}")
    allowed = frozenset(types)

    def _require(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not allowed.intersection(user.account_types):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account group does not include access to this.",
            )
        return user

    return _require


def require_module(module_id: str):
    """Dependency factory: gate a route tree on a FEATURE module
    being effective for the caller (module doctrine, owner
    2026-10-18 — see app/modules/core/module_control.py for the
    rules: healthy graph + global switch + dependencies usable +
    one of the caller's groups assigned by the operator).

    A module that isn't effective answers 403 with
    detail.code == "module_unavailable" — machine-readable, so the
    client can tell "this module is off for you" apart from an
    ordinary permission refusal. Where require_account_type was a
    hard-coded group list, this is the operator-controlled version;
    module route trees use this instead.
    """
    # Imported here, not at module top: module_control resolves the
    # feature registry lazily for the same cycle reason documented
    # there; keeping this import local makes the seam obvious.
    from app.modules.core import module_control

    def _require(
        user: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
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
        return user

    return _require


def require_operator(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Gate for the /api/admin/* surface: operators only. Everyone
    else — including signed-in non-operators — gets a 403. The flag
    lives on the account row (users.is_operator); it is not a group
    and can never be self-assigned through the API."""
    if not user.is_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access only.",
        )
    return user


def require_user_manager(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Gate for the admin USER-MANAGEMENT surface (the directory
    read + the tier/beta grant endpoints): god, and moderator
    admins — the two rungs the grant rules empower (owner design,
    2026-10-31). God arrives via the operator flag or the god
    rung; a moderator admin via the rung. Everyone else gets a
    403. This gate never widens the rest of /api/admin/* — module
    switches, settings, bans, and benefit grants stay
    operator-only behind require_operator."""
    if user.is_operator or user.tier in ("god", "moderator_admin"):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User management is restricted to the God account and moderator admins.",
    )
