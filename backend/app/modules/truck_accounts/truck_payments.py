"""Stripe Connect for truck accounts — the DARK SEAM
(wave 2, 2026-10-20).

The route (owner decision, 2026-10-20): dealers are paid
DIRECTLY into their own bank accounts via Stripe Connect
(Express) — a customer's payment flows customer → Stripe →
dealer, and the platform never holds money (no money-
transmission exposure; the dealer is the creditor of record).

This module is the whole integration surface, and every method
is INERT until BOTH activation conditions hold:

  (a) the platform Stripe keys exist (billing's stripe seam —
      STRIPE_SECRET_KEY in the server env, dark until Ryan
      creates the account), AND
  (b) the operator switch `payments.connect_enabled` is on
      (Admin → Settings).

Until then every method raises PaymentsNotConfigured, every API
endpoint answers 503 {code: "payments_not_configured"}, and the
user-side "Pay online" button never renders (the account
payload's pay_online_available stays False). Activation is
configuration, not a code change — the same dark pattern the
billing Stripe wiring shipped under.

NO live Connect calls happen in this build: the methods below
are guarded stubs that raise before touching the SDK. The
AgentProfile columns they will read/write (stripe_connect_
account_id, connect_charges_enabled, connect_payouts_enabled,
connect_onboarding_state) exist from migration 0040 so
activation needs no schema change.
"""

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.truck_accounts.agreement import CONNECT_ENABLED_KEY


class PaymentsNotConfigured(Exception):
    """The dark state's one answer. Routes render it as
    503 {code: payments_not_configured}."""

    code = "payments_not_configured"


def connect_enabled(db: Session) -> bool:
    return bool(entitlements.get_setting(db, CONNECT_ENABLED_KEY, False))


def payments_configured(db: Session) -> bool:
    """Both activation conditions: platform keys present AND the
    operator switch on."""
    from app.modules.billing import stripe_payments

    return bool(stripe_payments.payments_configured()) and connect_enabled(db)


def dealer_connect_ready(db: Session, dealer_user_id: uuid.UUID) -> bool:
    """Per-dealer readiness: the platform is configured AND this
    dealer finished Connect onboarding with charges + payouts
    enabled. Drives pay_online_available on account payloads."""
    if not payments_configured(db):
        return False
    from sqlalchemy import select

    from app.modules.dealers import models as dealer_models

    profile = db.scalars(
        select(dealer_models.AgentProfile).where(
            dealer_models.AgentProfile.user_id == dealer_user_id
        )
    ).first()
    return bool(
        profile is not None
        and profile.stripe_connect_account_id
        and profile.connect_charges_enabled
        and profile.connect_payouts_enabled
    )


def _require_configured(db: Session) -> None:
    if not payments_configured(db):
        raise PaymentsNotConfigured(
            "Online truck payments aren't enabled yet."
        )


def create_onboarding_link(db: Session, dealer_user_id: uuid.UUID) -> str:
    """A Stripe-hosted Express onboarding URL for the dealer.
    Dark: raises PaymentsNotConfigured."""
    _require_configured(db)
    raise PaymentsNotConfigured(
        "Online truck payments aren't enabled yet."
    )


def create_payment(
    db: Session,
    *,
    account_id: uuid.UUID,
    payer_user_id: uuid.UUID,
    amount: Decimal,
) -> dict:
    """Charge the customer's saved method for one scheduled
    payment, routed to the dealer's connected account (minus the
    admin-set platform fee). Dark: raises PaymentsNotConfigured."""
    _require_configured(db)
    raise PaymentsNotConfigured(
        "Online truck payments aren't enabled yet."
    )


def payout_configuration(db: Session, dealer_user_id: uuid.UUID) -> dict:
    """The dealer's payout schedule/status as Stripe reports it.
    Dark: raises PaymentsNotConfigured."""
    _require_configured(db)
    raise PaymentsNotConfigured(
        "Online truck payments aren't enabled yet."
    )
