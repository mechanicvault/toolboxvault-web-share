"""Billing module routes. HTTP layer only — logic lives in
entitlements.py / codes.py / wallet.py / stripe_payments.py.

Mounted at /api/billing. The redeem endpoint itself lives on the
core router (POST /api/core/redeem — the path the account design
specced) and delegates to codes.py from there.
"""

import stripe as stripe_sdk
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.billing import entitlements, schemas, stripe_payments, wallet

router = APIRouter()


def _payments_error(exc: Exception) -> HTTPException:
    """Translate the payment service's refusals into the API's
    structured error shape ({code, message} — the frontend's
    ApiError reads both)."""
    if isinstance(exc, stripe_payments.PaymentsNotConfigured):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "payments_not_configured",
                "message": str(exc),
            },
        )
    if isinstance(exc, stripe_payments.PricingNotConfigured):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "pricing_not_configured", "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "checkout_unavailable", "message": str(exc)},
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "billing", "status": "ok"}


@router.get("/me", response_model=schemas.EntitlementView)
def my_entitlement(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's effective plan + item standing + referral
    credit. Items are ASSETS (tools + batteries — the count the
    limit judges). `items_active` respects the enforcement switch:
    with enforcement off, every item counts as active."""
    entitlement = entitlements.resolve_entitlement(db, user.id)
    total = entitlements.asset_count(db, user.id)
    active_tools = entitlements.active_tool_ids(db, user.id)
    active_batteries = entitlements.active_battery_ids(db, user.id)
    items_active = (
        total
        if active_tools is None
        else len(active_tools) + len(active_batteries or ())
    )
    sub = entitlement.subscription
    # The Stripe-customer fact lives on core's user row; read it
    # through core's service (module law), never a cross-import of
    # core's models from a route.
    from app.modules.core import service as core_service

    core_user = core_service.get_user_by_id(db, user.id)
    return {
        "plan_key": entitlement.plan_key,
        "plan_name": entitlement.plan_name,
        "source": entitlement.source,
        "is_paid": entitlement.is_paid,
        "item_limit": entitlement.item_limit,
        "items_total": total,
        "items_active": items_active,
        "enforcement_enabled": entitlements.enforcement_enabled(db),
        "has_stripe_customer": bool(
            core_user is not None and core_user.stripe_customer_id
        ),
        "subscription": (
            {
                "status": sub.status,
                "plan_key": sub.plan_key,
                "source": sub.source,
                "current_period_end": sub.current_period_end,
                "grace_until": sub.grace_until,
                "trial_end": sub.trial_end,
            }
            if sub is not None
            else None
        ),
        "referral_paying_count": entitlement.referral_paying_count,
        "referral_free_months": entitlement.referral_free_months,
    }


@router.get("/ai-wallet", response_model=schemas.AiWalletView)
def my_ai_wallet(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's AI credit balances + recent ledger (Settings →
    AI credits). The wallet works regardless of the AI module's
    assignment: grants and codes can bank credits ahead of launch."""
    return wallet.wallet_view(db, user.id)


@router.get("/catalog", response_model=schemas.BillingCatalogView)
def billing_catalog(
    _user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Plans, brackets, and credit packs as the browser may offer
    them (Settings -> Billing / AI credits). While payments are
    dark this reports payments_configured=False and nothing
    purchasable — the honest state, not an error."""
    return stripe_payments.catalog_view(db)


@router.post("/checkout", response_model=schemas.CheckoutSessionView)
def create_checkout(
    payload: schemas.CheckoutRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a Stripe subscription checkout; the browser follows
    the returned URL to Stripe's hosted page. Paid state arrives
    ONLY via the webhook — this endpoint grants nothing."""
    try:
        url = stripe_payments.create_subscription_checkout(
            db,
            user.id,
            plan_key=payload.plan_key,
            period=payload.period,
            bracket_key=payload.bracket,
        )
    except (
        stripe_payments.PaymentsNotConfigured,
        stripe_payments.PricingNotConfigured,
        stripe_payments.CheckoutError,
    ) as exc:
        raise _payments_error(exc)
    return {"url": url}


@router.post("/checkout-credits", response_model=schemas.CheckoutSessionView)
def create_credits_checkout(
    payload: schemas.CreditsCheckoutRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a one-time AI-credit pack checkout (mode=payment).
    The credits are banked by the webhook when payment settles."""
    try:
        url = stripe_payments.create_credits_checkout(
            db, user.id, pack_id=payload.pack_id
        )
    except (
        stripe_payments.PaymentsNotConfigured,
        stripe_payments.PricingNotConfigured,
        stripe_payments.CheckoutError,
    ) as exc:
        raise _payments_error(exc)
    return {"url": url}


@router.post("/portal", response_model=schemas.CheckoutSessionView)
def create_portal(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A Stripe Customer Portal session URL — manage, cancel, or
    update the payment method on Stripe's hosted pages."""
    try:
        url = stripe_payments.create_portal_session(db, user.id)
    except (
        stripe_payments.PaymentsNotConfigured,
        stripe_payments.PricingNotConfigured,
        stripe_payments.CheckoutError,
    ) as exc:
        raise _payments_error(exc)
    return {"url": url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe's event door — no user auth; the SIGNATURE is the
    credential. Unconfigured secret -> 404 (the route pretends not
    to exist, the same posture as unconfigured OAuth providers).
    Bad signature -> 400. Handler failure -> 500 so Stripe retries
    (the event ledger rolls the id back, making the retry safe)."""
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature")
    try:
        event = stripe_payments.verify_event(payload, signature)
    except stripe_payments.WebhookNotConfigured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except (stripe_sdk.SignatureVerificationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature.",
        )
    try:
        return stripe_payments.process_event(db, event)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed; Stripe will retry.",
        )
