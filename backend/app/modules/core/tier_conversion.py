"""Tier conversion (owner order, 2026-11-10): a downloads-level
account's two doors OUT of the limited level.

Open signup (2026-11-09) made the teaser gate code decide what a
NEW account is born as — but an account born limited that later
RECEIVES the code (from its shop, its dealer, or the team) had no
door: the code was only ever asked at signup. Ryan's order closes
that gap, and adds the second door for accounts that never get a
code:

  1. THE CODE DOOR — the account enters the same gate code the
     signup doors check (core/teaser.code_matches — one
     comparison, never re-implemented). Right code: the account
     converts. The routes own the throttle (app.core.rate_limit's
     tier_conversion limiter, a failure budget per account).
  2. THE REQUEST DOOR — the account asks, ONCE, ever (the unique
     user_id on conversion_requests is the schema-level rule).
     A god-tier account approves or denies from the Admin queue.
     Approval runs the SAME conversion as the code door; denial
     is final for the request door (Ryan's anti-spam ruling)
     while the code door stays open forever.

THE CONVERSION itself is one function — convert_account — so the
two doors can never drift: the rung moves downloads → normal
(service.set_user_tier, which moves the community-role shadow
with it), the Home dashboard tip's dismissal is cleared (for this
account the full Home genuinely IS new — the tip explains the
widgets and the Add door), and an audit row lands
(user.tier_converted). One-way and permanent: nothing here or in
the grant machinery ever moves a converted account back — an
admin CAN still set the downloads rung deliberately through the
ordinary grant door (the launch tooling), but no code change,
code rotation, or request outcome demotes a converted account.

FIRST FULL ENTRY needs nothing set here: the account was born
through the one creation path, so it carries the wizard birth
marker; while it sat on the rung the group layer was waived for
it and the wizard gave it the bare-minimum pass. The moment the
rung lifts, the waiver lifts with it (tiers.group_layer_waived
reads the rung), the account still holds NO account types, and
the existing gates present exactly as they do for a code-born
account in the same state: the bare Home under the setup banner,
the wizard's account-type step required and locked first
(onboarding.set_progress refuses every later step until the pick
lands), and module reach computed off the empty group set. The
rig proves the converted seat's surfaces diff-clean against a
code-born normal account.

NOTIFICATIONS ride the inbox machinery (core/inbox.py): god
accounts hear about a new request; the requester hears the
decision. Copy is written per recipient in the recipient's own
locale (app.core.i18n.resolve_locale) — EN + ES below.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import i18n
from app.modules.core import audit, inbox, models, service, tiers

logger = logging.getLogger(__name__)

HOME_PAGE_KEY = "home"
TIP_KEY = "home_tip"

VIA_ACCESS_CODE = "access_code"
VIA_APPROVAL = "approval"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"


class AlreadyRequested(Exception):
    """The account already holds its one conversion request."""


class AlreadyDecided(Exception):
    """The request being decided is no longer pending."""


# -- notification copy (per recipient, in their locale) --------

_REQUESTED_COPY = {
    "en": (
        "Full-access request",
        "{name} ({account_number}) is on the Downloads level and "
        "has asked for full access. Open Admin → Conversion "
        "requests to approve or deny it.",
    ),
    "es": (
        "Solicitud de acceso completo",
        "{name} ({account_number}) está en el nivel de Descargas "
        "y ha pedido acceso completo. Abra Administración → "
        "Solicitudes de conversión para aprobarla o denegarla.",
    ),
}

_APPROVED_COPY = {
    "en": (
        "Welcome to the full vault",
        "Your request was approved — this account now has full "
        "access. Pick your account type to finish setting up, "
        "and make your Home your own.",
    ),
    "es": (
        "Bienvenido a la bóveda completa",
        "Su solicitud fue aprobada: esta cuenta ahora tiene "
        "acceso completo. Elija su tipo de cuenta para terminar "
        "la configuración y haga su Inicio suyo.",
    ),
}

_DENIED_COPY = {
    "en": (
        "Full-access request not approved",
        "The team didn't approve your request for full access. "
        "If you get the full-access code — from your shop, your "
        "dealer, or the team — you can still enter it on your "
        "Home page or in Settings → Profile to convert this "
        "account.",
    ),
    "es": (
        "Solicitud de acceso completo no aprobada",
        "El equipo no aprobó su solicitud de acceso completo. "
        "Si consigue el código de acceso completo — de su "
        "taller, su distribuidor o el equipo — aún puede "
        "ingresarlo en su página de Inicio o en Ajustes → "
        "Perfil para convertir esta cuenta.",
    ),
}


def _notify(db: Session, recipient: models.User, *, kind: str, copy: dict) -> None:
    title, body = copy[i18n.resolve_locale(recipient)]
    inbox.create_notification(
        db,
        recipient.id,
        kind=kind,
        title=title,
        body=body,
        data={},
        commit=False,
    )


def _god_accounts(db: Session) -> list[models.User]:
    """Every account holding the god rung — the conversion
    requests' whole audience. Resolved in Python off the tier
    ladder (tiers.resolved_tier) so the operator-flag derivation
    counts exactly as it does everywhere else."""
    candidates = list(
        db.scalars(
            select(models.User).where(
                (models.User.tier == "god") | (models.User.is_operator.is_(True)),
                models.User.is_active.is_(True),
            )
        ).all()
    )
    return [u for u in candidates if tiers.resolved_tier(u) == "god"]


# -- the conversion ---------------------------------------------

def _reset_home_tip(db: Session, user_id: uuid.UUID) -> None:
    """Clear the Home tip's dismissal from the account's stored
    home layout (HomeShell's `home_tip` pseudo-entry, visible
    False = dismissed). The entry is REMOVED, every other entry
    carried byte-for-byte — the row is edited directly, never
    round-tripped through the layout sanitizer, so panel state,
    per-stat choices and any custom boxes survive untouched. A
    layout without a tip entry is left exactly as stored."""
    row = db.scalar(
        select(models.UserPageLayout).where(
            models.UserPageLayout.user_id == user_id,
            models.UserPageLayout.page_key == HOME_PAGE_KEY,
        )
    )
    if row is None:
        return
    blocks = list(row.blocks or [])
    kept = [
        entry
        for entry in blocks
        if not (isinstance(entry, dict) and entry.get("key") == TIP_KEY)
    ]
    if len(kept) != len(blocks):
        row.blocks = kept
        db.commit()


def convert_account(db: Session, user: models.User, *, via: str, actor) -> None:
    """Move a downloads-level account to the normal rung — the
    ONE conversion both doors run. `actor` is who performed it
    (the account itself via its code; the deciding god account
    via approval) and lands on the audit row. Callers have
    already established the account sits on the downloads rung;
    the rung check repeats here so no future caller can convert
    an account that isn't limited."""
    if tiers.resolved_tier(user) != "downloads":
        raise ValueError("Only a downloads-level account can be converted.")
    service.set_user_tier(db, user, "normal")
    try:
        _reset_home_tip(db, user.id)
    except Exception:  # the tip is cosmetic; the conversion stands
        db.rollback()
        logger.exception(
            "Could not reset the Home tip for converted user %s", user.id
        )
    audit.record(
        db,
        actor,
        action="user.tier_converted",
        target=str(user.id),
        detail={
            "email": user.email,
            "previous": "downloads",
            "tier": "normal",
            "via": via,
        },
    )


# -- the request door -------------------------------------------

def get_request(
    db: Session, user_id: uuid.UUID
) -> models.ConversionRequest | None:
    """The account's one conversion request, or None."""
    return db.scalar(
        select(models.ConversionRequest).where(
            models.ConversionRequest.user_id == user_id
        )
    )


def create_request(db: Session, user: models.User) -> models.ConversionRequest:
    """File the account's one request and tell the god accounts.
    Raises AlreadyRequested when the slot is taken — pending,
    approved or denied alike (the one-ever rule)."""
    if get_request(db, user.id) is not None:
        raise AlreadyRequested
    row = models.ConversionRequest(user_id=user.id, status=STATUS_PENDING)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:  # a concurrent first request won the slot
        db.rollback()
        raise AlreadyRequested from None
    title_body = _REQUESTED_COPY
    for god in _god_accounts(db):
        title, body = title_body[i18n.resolve_locale(god)]
        inbox.create_notification(
            db,
            god.id,
            kind=inbox.KIND_CONVERSION_REQUESTED,
            title=title,
            body=body.format(name=user.name, account_number=user.account_number),
            data={"request_id": str(row.id), "user_id": str(user.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def list_requests(db: Session) -> list[models.ConversionRequest]:
    """The god queue: pending first (oldest first — first asked,
    first decided), then decided (newest decision first)."""
    rows = list(db.scalars(select(models.ConversionRequest)).all())
    pending = sorted(
        (r for r in rows if r.status == STATUS_PENDING),
        key=lambda r: r.created_at,
    )
    decided = sorted(
        (r for r in rows if r.status != STATUS_PENDING),
        key=lambda r: (r.decided_at or r.created_at),
        reverse=True,
    )
    return pending + decided


def decide_request(
    db: Session,
    actor: models.User,
    request_id: uuid.UUID,
    *,
    approve: bool,
) -> models.ConversionRequest:
    """A god account's decision. Approval runs the same
    conversion as the code door (via=approval, actor=the
    decider); denial records the decision and nothing else
    moves — the requester's rung is untouched and the code door
    stays open. Either way the requester hears the outcome."""
    row = db.get(models.ConversionRequest, request_id)
    if row is None:
        raise LookupError("Unknown conversion request.")
    if row.status != STATUS_PENDING:
        raise AlreadyDecided
    requester = service.get_user_by_id(db, row.user_id)
    if requester is None:
        raise LookupError("The requesting account no longer exists.")
    row.status = STATUS_APPROVED if approve else STATUS_DENIED
    row.decided_by_id = actor.id
    row.decided_by_email = actor.email or ""
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    if approve:
        # The requester may have converted by code while the
        # request sat pending — the approval still lands (the
        # answer was yes), and the conversion is already done;
        # only a still-limited account runs it here.
        if tiers.resolved_tier(requester) == "downloads":
            convert_account(db, requester, via=VIA_APPROVAL, actor=actor)
        _notify(
            db, requester, kind=inbox.KIND_CONVERSION_APPROVED, copy=_APPROVED_COPY
        )
    else:
        audit.record(
            db,
            actor,
            action="user.conversion_request_denied",
            target=str(requester.id),
            detail={"email": requester.email, "request_id": str(row.id)},
        )
        _notify(
            db, requester, kind=inbox.KIND_CONVERSION_DENIED, copy=_DENIED_COPY
        )
    db.commit()
    return row
