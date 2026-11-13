"""Truck Accounts routes. HTTP layer only — logic lives in
service.py; the payments seam answers for itself (dark).
Gated on the truck_accounts FEATURE module (seeded defaults:
mechanic + shop + dealer).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.core import models as core_models
from app.modules.truck_accounts import schemas, service, truck_payments

router = APIRouter()

_truck_module = require_module("truck_accounts")


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.TruckNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _account_or_404(db: Session, user_id, account_id) -> object:
    account = service.get_account(db, user_id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Truck account not found")
    return account


def _payments_503() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": truck_payments.PaymentsNotConfigured.code,
            "message": "Online truck payments aren't enabled yet.",
        },
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "truck_accounts", "status": "ok"}


@router.get("/accounts", response_model=list[schemas.TruckAccountPublic])
def list_accounts(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    me = db.get(core_models.User, user.id)
    if me is not None:
        # Pre-signup email invites attach on first sight (the
        # peer-invite pattern) — then the list reads whole.
        service.attach_pending_invites(db, me)
    return [
        service.serialize_account(db, account, user.id)
        for account in service.accounts_for_user(db, user.id)
    ]


@router.post(
    "/accounts",
    response_model=schemas.TruckAccountPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    payload: schemas.CreateAccountRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    dealer = db.get(core_models.User, user.id)
    try:
        account = service.create_account(
            db,
            dealer,
            customer_account_number=payload.customer_account_number,
            customer_email=payload.customer_email,
            payment_cadence=payload.payment_cadence,
            payment_amount=payload.payment_amount,
            next_due_date=payload.next_due_date,
            dealer_company_id=payload.dealer_company_id,
            credit_limit=payload.credit_limit,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.get(
    "/issuable-companies", response_model=list[schemas.IssuableCompanyPublic]
)
def issuable_companies(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The companies the caller can open truck accounts under:
    the ones they are a VERIFIED agent for."""
    dealer = db.get(core_models.User, user.id)
    return service.issuable_companies(db, dealer)


# -- stage 2: the customer's seat (self-kept accounts) -------------------------------
#
# The mechanic opens and keeps his own tabs: against any agent
# on his roster, with his opening balance, no agreement gate.
# These routes are the customer's doors; the agent-issuance
# doors above are untouched.


@router.get(
    "/accounts/self/companies",
    response_model=list[schemas.IssuableCompanyPublic],
)
def self_open_companies(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The companies where the caller HAS a roster agent — the
    self-kept account's company picker."""
    customer = db.get(core_models.User, user.id)
    return service.self_open_companies(db, customer)


@router.get(
    "/accounts/self/targets", response_model=list[schemas.SelfTargetPublic]
)
def self_open_targets(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The caller's roster agents for one company — who a
    self-kept account can be opened with there."""
    customer = db.get(core_models.User, user.id)
    try:
        return service.self_open_targets(db, customer, company_id)
    except service.TruckError as exc:
        raise _as_http(exc)


@router.post(
    "/accounts/self",
    response_model=schemas.TruckAccountPublic,
    status_code=status.HTTP_201_CREATED,
)
def open_self_account(
    payload: schemas.SelfOpenRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    customer = db.get(core_models.User, user.id)
    try:
        account = service.open_customer_account(
            db,
            customer,
            company_id=payload.company_id,
            private_agent_id=payload.private_agent_id,
            agent_user_id=payload.agent_user_id,
            opening_balance=payload.opening_balance,
            opening_note=payload.opening_note,
            payment_cadence=payload.payment_cadence,
            payment_amount=payload.payment_amount,
            next_due_date=payload.next_due_date,
            payment_mode=payload.payment_mode,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/payment-mode",
    response_model=schemas.TruckAccountPublic,
)
def set_payment_mode(
    account_id: uuid.UUID,
    payload: schemas.PaymentModeRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        account = service.set_payment_mode(
            db, customer, account, payment_mode=payload.payment_mode
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/payment-requests",
    response_model=schemas.PaymentRequestPublic,
    status_code=status.HTTP_201_CREATED,
)
def request_payment(
    account_id: uuid.UUID,
    payload: schemas.PaymentRequestCreate,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    agent = db.get(core_models.User, user.id)
    try:
        row = service.request_payment(
            db, agent, account, amount=payload.amount, note=payload.note
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_payment_request(db, row)


@router.post(
    "/accounts/{account_id}/payment-requests/{request_id}/approve",
    response_model=schemas.PaymentRequestPublic,
)
def approve_payment_request(
    account_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: schemas.PaymentRequestDecision,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        row = service.decide_payment_request(
            db, customer, account, request_id,
            approve=True, note=payload.note,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_payment_request(db, row)


@router.post(
    "/accounts/{account_id}/payment-requests/{request_id}/decline",
    response_model=schemas.PaymentRequestPublic,
)
def decline_payment_request(
    account_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: schemas.PaymentRequestDecision,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        row = service.decide_payment_request(
            db, customer, account, request_id,
            approve=False, note=payload.note,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_payment_request(db, row)


@router.get("/accounts/{account_id}/statement")
def account_statement(
    account_id: uuid.UUID,
    fmt: str = "pdf",
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The account's printable statement (PDF) or CSV export,
    rendered by the Reports module's activity machinery from
    the truck module's own statement dataset — the site's one
    document style, fed by the ledger itself."""
    from fastapi import Response

    from app.modules.reports import activity as reports_activity
    from app.modules.reports import exports as reports_exports

    if fmt not in ("pdf", "csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be pdf or csv.",
        )
    account = _account_or_404(db, user.id, account_id)
    viewer = db.get(core_models.User, user.id)
    report = service.statement_report(db, account, viewer)
    content = reports_activity.render_activity(report, fmt, viewer)
    return Response(
        content=content,
        media_type=reports_exports.MIME_TYPES[fmt],
        headers={
            "Content-Disposition": (
                f'attachment; filename="truck-statement-'
                f'{account.id}.{reports_exports.EXTENSIONS[fmt]}"'
            )
        },
    )


@router.get("/wizard-context", response_model=schemas.WizardContextPublic)
def wizard_context(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The Add wizard's truck question for one dealer company:
    the caller's active accounts under it, any waiting invite,
    and the agent a self-opened tab would land under."""
    customer = db.get(core_models.User, user.id)
    try:
        return service.wizard_context(db, customer, company_id)
    except service.TruckError as exc:
        raise _as_http(exc)


@router.get("/status-summary", response_model=schemas.StatusSummaryPublic)
def status_summary(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    """The dealers page's status strip: the caller's open truck
    accounts + balances on both sides, and the next route visits
    of their agents."""
    return service.status_summary(db, user.id)


@router.get(
    "/accounts/{account_id}", response_model=schemas.AccountDetailPublic
)
def get_account(
    account_id: uuid.UUID,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    me = db.get(core_models.User, user.id)
    if me is not None:
        service.attach_pending_invites(db, me)
    account = _account_or_404(db, user.id, account_id)
    return service.account_detail(db, account, user.id)


@router.post(
    "/accounts/{account_id}/accept",
    response_model=schemas.TruckAccountPublic,
)
def accept_account(
    account_id: uuid.UUID,
    payload: schemas.AcceptRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        account = service.accept_account(
            db, customer, account,
            agreement_version=payload.agreement_version,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/decline",
    response_model=schemas.TruckAccountPublic,
)
def decline_account(
    account_id: uuid.UUID,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        account = service.decline_account(db, customer, account)
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/transfer",
    response_model=schemas.TruckAccountPublic,
)
def transfer_account(
    account_id: uuid.UUID,
    payload: schemas.TransferRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    customer = db.get(core_models.User, user.id)
    try:
        account = service.transfer_account(
            db, customer, account,
            to_agent_user_id=payload.to_agent_user_id,
            to_private_agent_id=payload.to_private_agent_id,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/close",
    response_model=schemas.TruckAccountPublic,
)
def close_account(
    account_id: uuid.UUID,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    me = db.get(core_models.User, user.id)
    try:
        account = service.close_account(db, me, account)
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/schedule",
    response_model=schemas.TruckAccountPublic,
)
def update_schedule(
    account_id: uuid.UUID,
    payload: schemas.UpdateScheduleRequest,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    me = db.get(core_models.User, user.id)
    try:
        account = service.update_schedule(
            db, me, account,
            payment_cadence=payload.payment_cadence,
            payment_amount=payload.payment_amount,
            next_due_date=payload.next_due_date,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_account(db, account, user.id)


@router.post(
    "/accounts/{account_id}/entries",
    response_model=schemas.TruckEntryPublic,
    status_code=status.HTTP_201_CREATED,
)
def add_entry(
    account_id: uuid.UUID,
    payload: schemas.EntryCreate,
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    me = db.get(core_models.User, user.id)
    try:
        entry = service.add_entry(
            db, me, account,
            kind=payload.kind,
            amount=payload.amount,
            note=payload.note,
            item_link_id=payload.item_link_id,
            entry_date=payload.entry_date,
        )
    except service.TruckError as exc:
        raise _as_http(exc)
    return service.serialize_entry(db, entry)


@router.get(
    "/dealer/dashboard", response_model=schemas.DashboardSummary
)
def dealer_dashboard(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    return service.dealer_dashboard(db, user.id)


# -- the dark Connect seam ------------------------------------------------------------
#
# These endpoints EXIST so activation is configuration, not a
# deploy: every one answers the dark state's 503 until platform
# keys exist AND payments.connect_enabled is on. (The dealer
# dashboard sections read the same summary service-side.)


@router.post("/connect/onboarding-link")
def connect_onboarding_link(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    try:
        url = truck_payments.create_onboarding_link(db, user.id)
    except truck_payments.PaymentsNotConfigured:
        raise _payments_503()
    return {"url": url}


@router.get("/connect/payouts")
def connect_payouts(
    user: CurrentUser = Depends(_truck_module),
    db: Session = Depends(get_db),
):
    try:
        return truck_payments.payout_configuration(db, user.id)
    except truck_payments.PaymentsNotConfigured:
        raise _payments_503()


@router.post("/accounts/{account_id}/pay-online")
def pay_online(
    account_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account_or_404(db, user.id, account_id)
    try:
        return truck_payments.create_payment(
            db,
            account_id=account.id,
            payer_user_id=user.id,
            amount=account.payment_amount or 0,
        )
    except truck_payments.PaymentsNotConfigured:
        raise _payments_503()
