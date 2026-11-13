"""Billing module schemas: entitlement view, wallet view, redeem
and admin payloads."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CodeKind = Literal[
    "free_months",
    "free_year",
    "lifetime",
    "ai_credits",
    "trial_months",
    # Legacy: days-based trials (2026-10-22 — admin durations are
    # months now; trial_days stays ACCEPTED so old rows still
    # redeem, but nothing creates it anymore).
    "trial_days",
]


class SubscriptionView(BaseModel):
    status: str
    plan_key: str
    source: str
    current_period_end: datetime | None = None
    grace_until: datetime | None = None
    trial_end: datetime | None = None


class EntitlementView(BaseModel):
    """GET /api/billing/me: the caller's effective plan, what
    produced it, how their items stand against it, and their
    referral credit — everything Settings → Subscription & billing
    renders."""

    plan_key: str
    plan_name: str
    source: str
    is_paid: bool
    item_limit: int | None = None  # None = unlimited
    items_total: int
    items_active: int
    enforcement_enabled: bool
    # True once a Stripe customer exists for the account (first
    # checkout) — Settings shows "Manage subscription" only then.
    has_stripe_customer: bool = False
    subscription: SubscriptionView | None = None
    referral_paying_count: int
    referral_free_months: int


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class RedeemResponse(BaseModel):
    kind: str
    plan_key: str
    credits: int | None = None
    ends_at: datetime | None = None
    message: str


class LedgerEntry(BaseModel):
    id: uuid.UUID
    delta: int
    bucket: str
    reason: str
    ref: str
    bucket_balance_after: int
    created_at: datetime


class AiWalletView(BaseModel):
    allowance_balance: int
    banked_balance: int
    total_balance: int
    ledger: list[LedgerEntry]


# -- Stripe payments (2026-10-19; dark until keys + prices exist) -------


class CheckoutRequest(BaseModel):
    """Start a subscription checkout. `bracket` is the Business
    employee bracket (business_brackets.bracket_key) — required
    for the Business plan, ignored otherwise."""

    plan_key: Literal["pro", "business"]
    period: Literal["monthly", "yearly"]
    bracket: str | None = Field(default=None, max_length=32)


class CreditsCheckoutRequest(BaseModel):
    pack_id: str = Field(min_length=1, max_length=64)


class CheckoutSessionView(BaseModel):
    url: str


class CatalogPlanView(BaseModel):
    plan_key: str
    name: str
    item_limit: int | None = None
    is_paid: bool
    # Per-period "can the browser offer checkout" booleans — price
    # ids themselves never leave the server.
    checkout_available: dict[str, bool]


class CatalogBracketView(BaseModel):
    bracket_key: str
    up_to_employees: int | None = None
    price_configured: bool


class CatalogPackView(BaseModel):
    id: str
    label: str
    credits: int
    purchasable: bool


class BillingCatalogView(BaseModel):
    """GET /api/billing/catalog: everything Settings -> Billing
    needs to render plan cards and credit packs honestly — with
    payments dark, `payments_configured` is False and every
    purchasable flag is False, so the UI shows launch copy
    instead of dead buttons."""

    payments_configured: bool
    plans: list[CatalogPlanView]
    brackets: list[CatalogBracketView]
    ai_credit_packs: list[CatalogPackView]


# -- admin (operator-only; the Phase A2 panel consumes these) ----------


class CodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    kind: CodeKind
    amount: int = Field(default=0, ge=0)
    plan_key: str = "pro"
    max_redemptions: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


class CodeView(BaseModel):
    id: uuid.UUID
    code: str
    kind: str
    amount: int
    plan_key: str
    max_redemptions: int | None = None
    redemptions: int
    expires_at: datetime | None = None
    active: bool
    created_by: uuid.UUID | None = None
    created_at: datetime


class GrantCreate(BaseModel):
    """An admin free-period or trial grant for one user.

    Durations are MONTHS (owner directive 2026-10-22: admin time
    runs off months, never a typed day count). `days` stays
    accepted for API backward compatibility. kind="lifetime" is
    the open-ended grant — months/days are ignored."""

    user_id: uuid.UUID
    plan_key: str = "pro"
    kind: Literal["free_period", "trial", "lifetime"] = "free_period"
    months: int = Field(default=0, ge=0)
    days: int = Field(default=0, ge=0)


class AiGrantCreate(BaseModel):
    """An admin AI-credit grant: banked bucket (grants persist)."""

    user_id: uuid.UUID
    amount: int = Field(ge=1)


class RedemptionAdminView(BaseModel):
    """One recent redemption for the Promos section's activity
    list: the code, the account that redeemed it, and when."""

    id: uuid.UUID
    code: str
    user_id: uuid.UUID
    user_email: str
    user_name: str
    redeemed_at: datetime
