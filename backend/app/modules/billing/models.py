"""Billing module tables.

Owned exclusively by the billing module. Other modules read
entitlement answers via entitlements.py functions, never by importing
these models.

The module deliberately contains NO money: plans are configuration
(names + limits), subscriptions are facts fed by Stripe webhooks /
redeem codes / admin grants (Phase C wires Stripe), and the one
resolver in entitlements.py turns every source into a single answer.
All money values — when they arrive — live in Stripe and in
admin-editable config, never as hardcoded truths in code.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Plan(Base):
    """One row of the plan catalog (config, not code).

    `item_limit` NULL = unlimited items. `ai_monthly_credits` is the
    AI wallet's monthly allowance on this plan (0 until the owner
    prices the AI module). Prices are NOT here on purpose: the money
    mapping lives in Stripe (Phase C); this catalog only names plans
    and what they allow.
    """

    __tablename__ = "plans"

    plan_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_limit: Mapped[int | None] = mapped_column(Integer)
    ai_monthly_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BusinessBracket(Base):
    """One employee bracket of the Business plan's price structure
    (owner decision 2026-10-18: shop price = base + bracket fee for
    up-to-N employees; NOT flat band, NOT per-seat).

    The fee itself is money, so it lives in Stripe later; this table
    models only the STRUCTURE the entitlement engine needs: which
    bracket a shop's employee count falls into. `up_to_employees`
    NULL is the open-ended top bracket. Employee counting itself
    lands with the business module; the catalog models it now.
    """

    __tablename__ = "business_brackets"
    __table_args__ = (
        UniqueConstraint("bracket_key", name="uq_business_bracket_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.plan_key"), nullable=False, default="business"
    )
    up_to_employees: Mapped[int | None] = mapped_column(Integer)
    bracket_key: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Subscription(Base):
    """A user's subscription facts, mirrored from the payment
    provider (Phase C) or set by codes/admin/tests until Stripe
    lands. One row per user, created lazily — no row = free.

    Status vocabulary: none | active | trialing | past_due |
    canceled | ended. The resolver (entitlements.py) computes
    entitlement from status + current_period_end + grace_until:
    after cancellation the plan holds through the paid period, then
    through `grace_until` (owner decision 2026-10-18: 20 days after
    Stripe exhausts retries), then drops to Free.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_user"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    # Where the facts came from: stripe | redeem_code | admin | …
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # Stripe mirror facts (2026-10-19): the provider's own ids and
    # status string, kept verbatim next to our normalized `status`
    # so an operator can reconcile our row against the Stripe
    # dashboard without a translation table. `stripe_status` is the
    # raw value (active | trialing | past_due | canceled | unpaid |
    # incomplete | …); `status` above stays OUR vocabulary.
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64))
    stripe_status: Mapped[str | None] = mapped_column(String(32))
    # The Business bracket the subscriber declared at checkout
    # (business_brackets.bracket_key). Self-declared until the
    # employee system exists to count heads; the bracket price id
    # charged came from this key.
    bracket_key: Mapped[str | None] = mapped_column(String(32))
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SubscriptionStatusChange(Base):
    """One RECORDED subscription status transition (cancellation
    counts lane, owner 2026-11-07): the subscription, the status
    it left, the status it entered, when, and the source of the
    change ("stripe" for webhook-driven facts, "lapse_job" for
    the daily lapse flip, or whatever source an upsert caller
    declared — admin, tests, …).

    Why this table exists: the Subscription row stores only its
    CURRENT status, so before this lane nothing could say WHEN a
    subscription was canceled — the admin Accounting report
    printed that gap honestly instead of counting. Every write
    path that moves a subscription's status now appends one row
    here, transitions only: a write that re-saves the same
    status records nothing, and a replayed webhook event that
    changes nothing records nothing. `from_status` NULL means
    the row's first recorded state (the subscription row was
    created directly in `to_status`).

    A CANCELLATION (the Accounting report's printed definition)
    is a transition from a live state (active | trialing |
    past_due) into a terminal state (canceled | ended), counted
    once, at the moment the subscription first goes terminal —
    a later canceled -> ended lapse flip is not a second
    cancellation. entitlements.is_cancellation_change is the
    one definition both the writers and the report read.

    History starts with the migration that created this table
    (0088) — no earlier change was ever recorded, and no row
    pretends otherwise.
    """

    __tablename__ = "subscription_status_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Where the change came from: stripe | lapse_job | admin | …
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class StripeEvent(Base):
    """Webhook idempotency ledger: one row per Stripe event id
    ever accepted. Stripe retries deliveries and can send the same
    event more than once; the handler inserts the id BEFORE
    applying effects and treats a repeat as a no-op, so a retried
    invoice.paid or credit purchase can never land twice. (The
    wallet ledger's ref is the second guard for credit purchases.)
    """

    __tablename__ = "stripe_events"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EntitlementGrant(Base):
    """One time-boxed (or permanent) plan grant from a non-Stripe
    source: a redeem code, an admin free period, a trial. The
    resolver folds every active grant into the effective plan, so
    sources never fight — the most generous valid one wins.

    `kind`: free_period | trial | lifetime. `source`: redeem_code |
    admin. `source_ref`: the code string or the operator's id.
    `ends_at` NULL = permanent (lifetime).
    """

    __tablename__ = "entitlement_grants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False, default="pro")
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SystemSetting(Base):
    """Operator-tunable key/value config (JSON values).

    Today it carries exactly one key the engine reads:
    `entitlements.enforcement_enabled` (bool, default False — owner
    decision 2026-10-18: build the limits now, enforce from launch).
    The Admin settings surface (Phase A2) edits these; the service
    layer here is its API-ready backend.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RedeemCode(Base):
    """An admin-issued code (owner doctrine: codes are created in
    the admin panel and are live instantly — Phase A2 builds that
    panel; the API lands here).

    `kind`: free_months | free_year | lifetime | ai_credits |
    trial_months | trial_days (legacy). `amount` is
    kind-dependent: months count for free_months / trial_months,
    credits for ai_credits, days for trial_days (unused for
    free_year/lifetime). `plan_key` is the plan a time grant
    confers (default pro). Per-user once is enforced by the
    redemptions ledger's unique constraint.
    """

    __tablename__ = "redeem_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_redeem_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stored normalized: uppercased, trimmed. Codes are
    # case-insensitive for the person typing them.
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_key: Mapped[str] = mapped_column(String(32), nullable=False, default="pro")
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Redemption(Base):
    """The redemption ledger: who redeemed which code, when, and
    what it produced (a grant row and/or a wallet credit). The
    unique (code_id, user_id) constraint IS the per-user-once rule,
    enforced by the database, not by hope."""

    __tablename__ = "redemptions"
    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_redemption_code_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("redeem_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entitlement_grants.id")
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiWallet(Base):
    """A user's AI credit wallet (ai-token-system.md): two buckets.

    - allowance_balance: the plan's monthly allowance. Refills to
      the plan amount each cycle and does NOT roll over — the refill
      replaces it.
    - banked_balance: purchased + granted + redeemed credits. These
      persist (no expiry in v1).

    Spending drains the allowance first (it's the use-it-or-lose-it
    bucket), then the banked balance.
    """

    __tablename__ = "ai_wallets"
    __table_args__ = (UniqueConstraint("user_id", name="uq_ai_wallet_user"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    allowance_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    banked_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # "YYYY-MM" of the last monthly refill (idempotency stamp).
    last_refill_period: Mapped[str | None] = mapped_column(String(7))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiLedger(Base):
    """One wallet movement (ai-token-system.md: the full usage
    ledger). `reason`: allowance_refill | purchase | grant | redeem
    | spend | admin_adjust. `ref` names the source (code string,
    operator id, AI action). `bucket_balance_after` snapshots the
    bucket so a user's history view never has to replay the ledger.
    """

    __tablename__ = "ai_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    ref: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bucket_balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiUsage(Base):
    """One METERED AI action (admin polish lane, owner
    2026-11-07): when it ran, which action consumed it, what it
    was for, how many provider calls / tokens it took, and what
    the wallet was charged.

    Why this table exists next to AiLedger: the ledger records
    WALLET movements only, so at the default price of 0 credits
    an AI call left no trace anywhere — and the providers' token
    counts were discarded by the transports. This is the usage
    record the admin AI Usage report reads. `ai_service` writes
    one row per charged action, free ones included, draining the
    per-flow capture the transports feed. History starts with
    the migration that created this table (0087) — nothing
    before it was ever recorded, and no row pretends otherwise.

    `subject` is the call's context as the consumer names it
    (the brand + model looked up, the item a manual was hunted
    for, the text identified) — free text, trimmed to 300 chars
    at write time. `calls` counts provider round-trips the
    action took; a row can carry calls = 0 when a priced action
    resolved without a provider call (a deterministic manual
    pattern hit), in which case tokens are honestly 0 too.
    """

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The metered action (ai_service.PRICE_KEYS vocabulary).
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default=""
    )
    model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=""
    )
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credits_charged: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
