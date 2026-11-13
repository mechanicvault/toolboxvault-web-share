"""Stripe payments (billing module service, 2026-10-19).

Owner decisions (2026-10-18): Stripe for maximum payment methods
(cards, Apple/Google Pay, Cash App Pay, Link, ACH — Checkout's
dynamic payment methods surface whatever the account enables);
prices DEFERRED (the owner sets them later); periods monthly +
annual at 10x monthly; Business = base price + a tiered employee
bracket fee; failed-payment grace is 20 days after Stripe exhausts
retries, then the entitlement drops to Free.

DARK BY CONSTRUCTION: the owner's Stripe account does not exist
yet. With STRIPE_SECRET_KEY empty, `payments_configured()` is
False and every entry point refuses cleanly — checkout/portal 503
{code: payments_not_configured}, the webhook 404s without a
STRIPE_WEBHOOK_SECRET — and nothing anywhere is chargeable. The
webhook is the ONLY writer of Stripe-paid state: checkout success
pages grant nothing; subscription facts flow from verified
webhook events into the same subscription rows the entitlement
resolver already reads (entitlements.py — unchanged).

SERVICE INTERFACE (stable; bump the billing manifest version on
change):
  - payments_configured() / webhook_configured()
  - price-id settings accessors (operator config, Admin -> Settings):
    plan_price_id(db, plan_key, period), bracket_price_map(db),
    ai_credit_packs(db)
  - catalog_view(db) — what Settings -> Billing may offer, with
    price ids reduced to purchasable booleans (ids never leave
    the server).
  - get_or_create_customer(db, user_id) — lazy Stripe customer.
  - create_subscription_checkout(db, user_id, plan_key, period,
    bracket_key) -> checkout URL (raises PaymentsNotConfigured /
    PricingNotConfigured / CheckoutError with friendly copy).
  - create_credits_checkout(db, user_id, pack_id) -> URL.
  - create_portal_session(db, user_id) -> URL.
  - verify_and_process_webhook(db, payload, signature) — raises
    WebhookNotConfigured / stripe's SignatureVerificationError;
    returns {"received": True, ...}. Idempotent per event id.
"""

import uuid
from datetime import datetime, timedelta, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.billing import entitlements, models, wallet

# -- operator settings keys (system_settings; Admin -> Settings) --------

PRICE_PRO_MONTHLY_KEY = "stripe_price_pro_monthly"
PRICE_PRO_YEARLY_KEY = "stripe_price_pro_yearly"
PRICE_BUSINESS_MONTHLY_KEY = "stripe_price_business_monthly"
PRICE_BUSINESS_YEARLY_KEY = "stripe_price_business_yearly"
BRACKET_PRICE_MAP_KEY = "stripe_price_business_brackets"
AI_CREDIT_PACKS_KEY = "stripe_ai_credit_packs"

_PLAN_PRICE_KEYS = {
    ("pro", "monthly"): PRICE_PRO_MONTHLY_KEY,
    ("pro", "yearly"): PRICE_PRO_YEARLY_KEY,
    ("business", "monthly"): PRICE_BUSINESS_MONTHLY_KEY,
    ("business", "yearly"): PRICE_BUSINESS_YEARLY_KEY,
}

PERIODS = ("monthly", "yearly")
PURCHASABLE_PLANS = ("pro", "business")

# Owner decision 2026-10-18: 20 days of grace after Stripe gives
# up on a failed payment, THEN the drop to Free. The webhook arms
# the window (period end + 20 days on the subscription row); the
# resolver computes the drop — nobody is hard-dropped here.
FAILED_PAYMENT_GRACE_DAYS = 20


class PaymentsNotConfigured(Exception):
    """No STRIPE_SECRET_KEY: payments are dark (route -> 503)."""


class PricingNotConfigured(Exception):
    """A plan/pack has no Stripe price id yet (route -> 400 with
    the launch copy). Prices are the owner's call, set later."""


class CheckoutError(ValueError):
    """A friendly, user-presentable checkout refusal (route -> 400)."""


class WebhookNotConfigured(Exception):
    """No STRIPE_WEBHOOK_SECRET: the webhook route answers 404."""


# -- configuration -------------------------------------------------------


def payments_configured() -> bool:
    return bool(settings.stripe_secret_key)


def webhook_configured() -> bool:
    return bool(settings.stripe_webhook_secret)


def _require_payments() -> None:
    if not payments_configured():
        raise PaymentsNotConfigured(
            "Payments aren't switched on yet — pricing opens at launch."
        )
    stripe.api_key = settings.stripe_secret_key


def _base_url() -> str:
    return settings.app_base_url.rstrip("/")


def _success_url() -> str:
    return f"{_base_url()}/settings/billing?checkout=success"


def _cancel_url() -> str:
    return f"{_base_url()}/settings/billing?checkout=cancelled"


def _return_url() -> str:
    return f"{_base_url()}/settings/billing"


# -- price-id settings -----------------------------------------------------


def _price_setting(db: Session, key: str) -> str:
    return str(entitlements.get_setting(db, key, "") or "").strip()


def plan_price_id(db: Session, plan_key: str, period: str) -> str:
    key = _PLAN_PRICE_KEYS.get((plan_key, period))
    return _price_setting(db, key) if key else ""


def bracket_price_map(db: Session) -> dict[str, str]:
    raw = entitlements.get_setting(db, BRACKET_PRICE_MAP_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(bracket): str(price).strip()
        for bracket, price in raw.items()
        if str(price).strip()
    }


def business_brackets(db: Session) -> list[models.BusinessBracket]:
    """The Business bracket catalog rows, in display order (the
    bracket keys Business checkout validates against)."""
    return list(
        db.scalars(
            select(models.BusinessBracket)
            .where(models.BusinessBracket.plan_key == "business")
            .order_by(models.BusinessBracket.sort_order)
        ).all()
    )


def ai_credit_packs(db: Session) -> list[dict]:
    """The operator-defined credit packs, normalized. Malformed
    entries are dropped rather than trusted — this JSON is config
    a human typed into a settings form."""
    raw = entitlements.get_setting(db, AI_CREDIT_PACKS_KEY, [])
    packs: list[dict] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            pack_id = str(entry.get("id") or "").strip()
            label = str(entry.get("label") or "").strip()
            try:
                credits = int(entry.get("credits") or 0)
            except (TypeError, ValueError):
                continue
            if not pack_id or not label or credits <= 0:
                continue
            packs.append(
                {
                    "id": pack_id,
                    "label": label,
                    "credits": credits,
                    "stripe_price_id": str(
                        entry.get("stripe_price_id") or ""
                    ).strip(),
                }
            )
    return packs


def price_reverse_map(db: Session) -> dict[str, tuple[str, str | None]]:
    """price id -> (plan_key, bracket_key|None): how a subscription
    event's line items name the plan when the event carries no
    metadata (dashboard-created subscriptions, renewals)."""
    mapping: dict[str, tuple[str, str | None]] = {}
    for (plan_key, _period), key in _PLAN_PRICE_KEYS.items():
        price_id = _price_setting(db, key)
        if price_id:
            mapping[price_id] = (plan_key, None)
    for bracket_key, price_id in bracket_price_map(db).items():
        mapping[price_id] = ("business", bracket_key)
    return mapping


# -- catalog (Settings -> Billing reads this) ------------------------------


def catalog_view(db: Session) -> dict:
    configured = payments_configured()
    plans = []
    for plan in entitlements.list_plans(db):
        availability = {}
        for period in PERIODS:
            price_id = (
                plan_price_id(db, plan.plan_key, period)
                if plan.plan_key in PURCHASABLE_PLANS
                else ""
            )
            availability[period] = bool(configured and price_id)
        plans.append(
            {
                "plan_key": plan.plan_key,
                "name": plan.name,
                "item_limit": plan.item_limit,
                "is_paid": plan.is_paid,
                "checkout_available": availability,
            }
        )
    price_map = bracket_price_map(db)
    brackets = [
        {
            "bracket_key": bracket.bracket_key,
            "up_to_employees": bracket.up_to_employees,
            "price_configured": bracket.bracket_key in price_map,
        }
        for bracket in business_brackets(db)
    ]
    packs = [
        {
            "id": pack["id"],
            "label": pack["label"],
            "credits": pack["credits"],
            "purchasable": bool(configured and pack["stripe_price_id"]),
        }
        for pack in ai_credit_packs(db)
    ]
    return {
        "payments_configured": configured,
        "plans": plans,
        "brackets": brackets,
        "ai_credit_packs": packs,
    }


# -- customers ---------------------------------------------------------------


def _core_user(db: Session, user_id: uuid.UUID):
    # Lazy import: core owns user data; billing consumes it through
    # core's service interface (module law).
    from app.modules.core import service as core_service

    return core_service.get_user_by_id(db, user_id)


def get_or_create_customer(db: Session, user_id: uuid.UUID) -> str:
    """The user's Stripe customer id, created lazily at first
    checkout and stored on the user row. Repeat calls reuse the
    stored id — one customer per account, ever."""
    _require_payments()
    user = _core_user(db, user_id)
    if user is None:
        raise CheckoutError("Your account couldn't be found.")
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email,
        name=user.name or None,
        metadata={
            "user_id": str(user.id),
            "account_number": user.account_number,
        },
    )
    user.stripe_customer_id = customer.id
    db.commit()
    return customer.id


def user_by_customer_id(db: Session, customer_id: str | None):
    if not customer_id:
        return None
    from app.modules.core import models as core_models

    return db.scalars(
        select(core_models.User).where(
            core_models.User.stripe_customer_id == customer_id
        )
    ).first()


# -- checkout -------------------------------------------------------------------


def _checkout_line_items(
    db: Session, plan_key: str, period: str, bracket_key: str | None
) -> list[dict]:
    """The price ids a checkout charges, or a friendly refusal.
    Business is base + bracket fee (owner's price structure), so
    its checkout carries BOTH line items."""
    base_price = plan_price_id(db, plan_key, period)
    if not base_price:
        raise PricingNotConfigured(
            "Pricing for that plan opens at launch — it hasn't been set yet."
        )
    items = [{"price": base_price, "quantity": 1}]
    if plan_key == "business":
        bracket_price = bracket_price_map(db).get(bracket_key or "")
        if not bracket_price:
            raise PricingNotConfigured(
                "Pricing for that employee bracket opens at launch — "
                "it hasn't been set yet."
            )
        items.append({"price": bracket_price, "quantity": 1})
    return items


def create_subscription_checkout(
    db: Session,
    user_id: uuid.UUID,
    *,
    plan_key: str,
    period: str,
    bracket_key: str | None = None,
) -> str:
    """Start a subscription checkout; returns the Stripe-hosted
    URL the browser is sent to. Payment methods are Checkout's
    dynamic set — whatever the Stripe account has enabled (cards,
    wallets, Cash App Pay, Link, ACH) surfaces automatically."""
    _require_payments()
    plan = entitlements.get_plan(db, plan_key)
    if plan is None or plan_key not in PURCHASABLE_PLANS:
        raise CheckoutError("That plan can't be purchased.")
    if period not in PERIODS:
        raise CheckoutError("Pick a billing period: monthly or annual.")
    if plan_key == "business":
        known = {bracket.bracket_key for bracket in business_brackets(db)}
        if not bracket_key or bracket_key not in known:
            raise CheckoutError(
                "Pick your employee bracket for the Business plan — "
                "its price is the base price plus your bracket's fee."
            )
    line_items = _checkout_line_items(db, plan_key, period, bracket_key)
    customer_id = get_or_create_customer(db, user_id)
    metadata = {
        "user_id": str(user_id),
        "kind": "subscription",
        "plan_key": plan_key,
        "period": period,
        "bracket_key": bracket_key or "",
    }
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=line_items,
        success_url=_success_url(),
        cancel_url=_cancel_url(),
        metadata=metadata,
        subscription_data={"metadata": metadata},
    )
    return session.url


def create_credits_checkout(
    db: Session, user_id: uuid.UUID, *, pack_id: str
) -> str:
    """Start a one-time AI-credit pack purchase (mode=payment).
    The credits land via the webhook — never on the success page."""
    _require_payments()
    pack = next(
        (p for p in ai_credit_packs(db) if p["id"] == pack_id), None
    )
    if pack is None:
        raise CheckoutError("That credit pack isn't available.")
    if not pack["stripe_price_id"]:
        raise PricingNotConfigured(
            "Pricing for that credit pack opens at launch — "
            "it hasn't been set yet."
        )
    customer_id = get_or_create_customer(db, user_id)
    session = stripe.checkout.Session.create(
        mode="payment",
        customer=customer_id,
        line_items=[{"price": pack["stripe_price_id"], "quantity": 1}],
        success_url=_success_url(),
        cancel_url=_cancel_url(),
        metadata={
            "user_id": str(user_id),
            "kind": "ai_credits",
            "pack_id": pack["id"],
            "credits": str(pack["credits"]),
        },
    )
    return session.url


def create_portal_session(db: Session, user_id: uuid.UUID) -> str:
    """A Stripe Customer Portal URL (manage / cancel / update
    payment method — Stripe hosts all of it)."""
    _require_payments()
    user = _core_user(db, user_id)
    if user is None or not user.stripe_customer_id:
        raise CheckoutError(
            "There's nothing to manage yet — no Stripe subscription "
            "exists for this account."
        )
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=_return_url(),
    )
    return session.url


# -- webhook ---------------------------------------------------------------------


def verify_event(payload: bytes, signature: str | None) -> dict:
    """Verify the Stripe-Signature header and build the event —
    normalized to a PLAIN dict (the SDK's StripeObject is not a
    dict in current versions; handlers below speak dict only).
    Raises WebhookNotConfigured (route -> 404) or lets the SDK's
    SignatureVerificationError / ValueError propagate (route ->
    400). This is the ONLY door paid state enters through."""
    if not webhook_configured():
        raise WebhookNotConfigured()
    event = stripe.Webhook.construct_event(
        payload, signature or "", settings.stripe_webhook_secret
    )
    return event.to_dict()


def _epoch_dt(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _resolve_user(db: Session, metadata: dict, customer_id: str | None):
    """Who an event belongs to: explicit user metadata first
    (checkout/subscription_data stamps it), then the customer id
    join. Either path returns the core User row or None."""
    user_id = (metadata or {}).get("user_id")
    if user_id:
        try:
            user = _core_user(db, uuid.UUID(str(user_id)))
        except (ValueError, TypeError):
            user = None
        if user is not None:
            return user
    return user_by_customer_id(db, customer_id)


def _subscription_period_end(sub_obj: dict) -> datetime | None:
    """current_period_end lives on the subscription in older API
    versions and on its items in newer ones — read both."""
    end = _epoch_dt(sub_obj.get("current_period_end"))
    if end is not None:
        return end
    items = (sub_obj.get("items") or {}).get("data") or []
    if items:
        return _epoch_dt(items[0].get("current_period_end"))
    return None


# Stripe's status string -> our subscription vocabulary (the
# resolver's). Unknown/future statuses fall back to the existing
# row's status rather than inventing entitlement.
_STATUS_MAP = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "paused": "past_due",
    "canceled": "canceled",
    "incomplete": "none",
    "incomplete_expired": "ended",
}


def _plan_from_items(db: Session, sub_obj: dict, metadata: dict):
    """(plan_key, bracket_key) for a subscription event: its own
    metadata first, then the reverse price map over its items."""
    plan_key = (metadata or {}).get("plan_key") or None
    bracket_key = (metadata or {}).get("bracket_key") or None
    if plan_key:
        return plan_key, bracket_key
    reverse = price_reverse_map(db)
    for item in (sub_obj.get("items") or {}).get("data") or []:
        price = item.get("price") or {}
        found = reverse.get(price.get("id") or "")
        if found is None:
            continue
        found_plan, found_bracket = found
        if found_bracket is None:
            plan_key = plan_key or found_plan
        else:
            plan_key = found_plan
            bracket_key = bracket_key or found_bracket
    return plan_key, bracket_key


def _sync_subscription(db: Session, sub_obj: dict) -> None:
    """Fold one Stripe subscription object into our subscription
    row — the single sync path for created/updated/deleted. The
    entitlement resolver reads the row exactly as before; grace is
    armed here (period end + 20 days) when payments fail, and
    nobody is ever hard-dropped by an event."""
    metadata = sub_obj.get("metadata") or {}
    customer_id = sub_obj.get("customer")
    user = _resolve_user(db, metadata, customer_id)
    if user is None:
        return
    if customer_id and not user.stripe_customer_id:
        user.stripe_customer_id = customer_id
        db.commit()
    raw_status = str(sub_obj.get("status") or "")
    existing = entitlements.get_subscription(db, user.id)
    status = _STATUS_MAP.get(
        raw_status, existing.status if existing is not None else "none"
    )
    plan_key, bracket_key = _plan_from_items(db, sub_obj, metadata)
    if plan_key is None:
        plan_key = existing.plan_key if existing is not None else "pro"
    if bracket_key is None and existing is not None:
        bracket_key = existing.bracket_key
    period_end = _subscription_period_end(sub_obj)
    if period_end is None and existing is not None:
        period_end = existing.current_period_end
    grace_until = None
    if status == "past_due":
        if period_end is not None:
            grace_until = period_end + timedelta(
                days=FAILED_PAYMENT_GRACE_DAYS
            )
    elif status == "canceled":
        reason = (sub_obj.get("cancellation_details") or {}).get("reason")
        if reason == "payment_failed" and period_end is not None:
            # Stripe exhausted its retries and cancelled for
            # non-payment: the owner's 20-day grace runs from the
            # end of the paid period. A voluntary cancel gets NO
            # grace — the plan simply holds through the period.
            grace_until = period_end + timedelta(
                days=FAILED_PAYMENT_GRACE_DAYS
            )
    row = entitlements.upsert_subscription(
        db,
        user.id,
        plan_key=plan_key,
        status=status,
        source="stripe",
        current_period_end=period_end,
        grace_until=grace_until,
        trial_end=_epoch_dt(sub_obj.get("trial_end")),
    )
    row.stripe_subscription_id = sub_obj.get("id")
    row.stripe_status = raw_status or None
    row.bracket_key = bracket_key
    db.commit()


def _handle_checkout_completed(db: Session, session: dict) -> None:
    metadata = session.get("metadata") or {}
    customer_id = session.get("customer")
    user = _resolve_user(db, metadata, customer_id)
    if user is None:
        return
    if customer_id and not user.stripe_customer_id:
        user.stripe_customer_id = customer_id
        db.commit()
    kind = metadata.get("kind")
    mode = session.get("mode")
    if kind == "ai_credits" or mode == "payment":
        # Credit purchases land ONLY here (never on the success
        # redirect), and only once payment actually settled.
        if session.get("payment_status") != "paid":
            return
        try:
            credits = int(metadata.get("credits") or 0)
        except (TypeError, ValueError):
            credits = 0
        if credits <= 0:
            return
        # Second idempotency guard under the event ledger: the
        # ledger row's ref names this checkout session, so even a
        # DIFFERENT event about the same session can't re-credit.
        ref = f"stripe:{session.get('id')}"
        already = db.scalars(
            select(models.AiLedger).where(
                models.AiLedger.user_id == user.id,
                models.AiLedger.reason == "purchase",
                models.AiLedger.ref == ref,
            )
        ).first()
        if already is not None:
            return
        wallet.credit(
            db,
            user.id,
            amount=credits,
            bucket="banked",
            reason="purchase",
            ref=ref,
        )
        return
    # Subscription checkout: link the ids. Status/period facts
    # arrive with the subscription events — this placeholder only
    # records that a Stripe subscription now exists for the user,
    # failing safe (status "none" grants nothing) until the
    # authoritative subscription sync lands.
    subscription_id = session.get("subscription")
    if subscription_id:
        row = entitlements.get_subscription(db, user.id)
        if row is None:
            row = entitlements.upsert_subscription(
                db,
                user.id,
                plan_key=metadata.get("plan_key") or "pro",
                status="none",
                source="stripe",
            )
        row.stripe_subscription_id = subscription_id
        bracket = metadata.get("bracket_key") or None
        if bracket:
            row.bracket_key = bracket
        db.commit()


def _invoice_subscription_row(db: Session, invoice: dict):
    """(user, subscription row) for an invoice event, resolved by
    customer id; the row must be the invoice's own subscription
    when we know its id."""
    user = user_by_customer_id(db, invoice.get("customer"))
    if user is None:
        return None, None
    row = entitlements.get_subscription(db, user.id)
    invoice_sub = invoice.get("subscription")
    if row is not None and invoice_sub and row.stripe_subscription_id not in (
        None,
        invoice_sub,
    ):
        return user, None
    return user, row


def _invoice_period_end(invoice: dict) -> datetime | None:
    lines = (invoice.get("lines") or {}).get("data") or []
    for line in reversed(lines):
        end = _epoch_dt((line.get("period") or {}).get("end"))
        if end is not None:
            return end
    return None


def _handle_invoice_paid(db: Session, invoice: dict) -> None:
    """A paid invoice means the subscription is in good standing:
    mark it active and clear any armed grace window. Period facts
    follow the invoice's own period when present."""
    user, row = _invoice_subscription_row(db, invoice)
    if row is None or row.status == "ended":
        return
    entitlements.set_subscription_status(db, row, "active", source="stripe")
    row.stripe_status = "active"
    row.grace_until = None
    period_end = _invoice_period_end(invoice)
    if period_end is not None:
        row.current_period_end = period_end
    db.commit()


def _handle_invoice_payment_failed(db: Session, invoice: dict) -> None:
    """A failed invoice starts the owner's clock — status past_due
    and grace armed at period end + 20 days — but drops NOTHING:
    the entitlement holds through the paid period, then grace,
    then the resolver lands the account on Free on its own."""
    user, row = _invoice_subscription_row(db, invoice)
    if row is None or row.status == "ended":
        return
    entitlements.set_subscription_status(db, row, "past_due", source="stripe")
    row.stripe_status = "past_due"
    period_end = _invoice_period_end(invoice) or row.current_period_end
    if period_end is not None:
        row.current_period_end = period_end
        row.grace_until = period_end + timedelta(
            days=FAILED_PAYMENT_GRACE_DAYS
        )
    db.commit()


_HANDLERS = {
    "checkout.session.completed": lambda db, event: _handle_checkout_completed(
        db, event["data"]["object"]
    ),
    "checkout.session.async_payment_succeeded": (
        lambda db, event: _handle_checkout_completed(db, event["data"]["object"])
    ),
    "customer.subscription.created": lambda db, event: _sync_subscription(
        db, event["data"]["object"]
    ),
    "customer.subscription.updated": lambda db, event: _sync_subscription(
        db, event["data"]["object"]
    ),
    "customer.subscription.deleted": lambda db, event: _sync_subscription(
        db, event["data"]["object"]
    ),
    "invoice.paid": lambda db, event: _handle_invoice_paid(
        db, event["data"]["object"]
    ),
    "invoice.payment_failed": lambda db, event: _handle_invoice_payment_failed(
        db, event["data"]["object"]
    ),
}


def process_event(db: Session, event) -> dict:
    """Apply one verified event, idempotently: the event id is
    recorded BEFORE its effects; a repeat delivery is a no-op. If
    a handler fails, the record is rolled back so Stripe's retry
    of the same event can succeed later."""
    if not isinstance(event, dict):
        # A raw SDK StripeObject from a direct caller: normalize.
        event = event.to_dict()
    event_id = str(event["id"])
    event_type = str(event["type"])
    if db.get(models.StripeEvent, event_id) is not None:
        return {"received": True, "duplicate": True}
    obj = event["data"]["object"]
    db.add(
        models.StripeEvent(
            event_id=event_id,
            event_type=event_type,
            detail={"object_id": obj.get("id") if isinstance(obj, dict) else None},
        )
    )
    db.commit()
    handler = _HANDLERS.get(event_type)
    try:
        if handler is not None:
            handler(db, event)
    except Exception:
        db.rollback()
        row = db.get(models.StripeEvent, event_id)
        if row is not None:
            db.delete(row)
            db.commit()
        raise
    return {"received": True}
