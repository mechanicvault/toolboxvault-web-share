"""Truck Accounts schemas — the wire shapes.

Money on the wire: charges/payments are entered as POSITIVE
amounts with the KIND carrying the direction (the service signs
them into the ledger) — nobody types a negative payment.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateAccountRequest(BaseModel):
    # Exactly one of the two addressing modes: an existing
    # customer by their exact account number, or an email invite
    # (works pre-signup — the account attaches at signup).
    customer_account_number: str = Field(default="", max_length=40)
    customer_email: str = Field(default="", max_length=320)
    payment_cadence: str = "weekly"
    payment_amount: Decimal | None = Field(default=None, gt=0)
    next_due_date: date | None = None
    # The company the issuing agent opens the account under
    # (2026-10-31): must be one they verified-represent. Omitted
    # + exactly one verified company defaults to it.
    dealer_company_id: uuid.UUID | None = None
    # The credit line the agent extends (optional).
    credit_limit: Decimal | None = Field(default=None, ge=0)


class TruckAccountPublic(BaseModel):
    id: uuid.UUID
    # NULL while a private (off-platform) agent holds the
    # account — the customer maintains that tab himself.
    dealer_user_id: uuid.UUID | None
    dealer_name: str | None
    dealer_account_number: str | None
    # The agent + company face (2026-10-31).
    dealer_company_id: uuid.UUID | None = None
    dealer_company_name: str | None = None
    agent_name: str = ""
    # "platform" | "private" | None
    agent_kind: str | None = None
    credit_limit: Decimal | None = None
    credit_available: Decimal | None = None
    customer_maintained: bool = False
    # Stage 2 (2026-11-05): the holding private record (the
    # customer's link back to the agent record), who keeps the
    # ledger, the stored pay-through-the-site choice, and the
    # computed missed-payment state.
    private_agent_id: uuid.UUID | None = None
    ledger_keeper: str = "agent"
    payment_mode: str = "manual"
    missed_payments: int = 0
    amount_past_due: Decimal = Decimal("0")
    customer_user_id: uuid.UUID | None
    customer_name: str
    customer_account_number: str | None
    customer_email: str
    status: str
    payment_cadence: str
    payment_amount: Decimal | None
    next_due_date: date | None
    balance: Decimal
    # Dealer page pass (2026-11-06): the balance the ledger's
    # first entry took the account to (see serialize_account).
    starting_balance: Decimal = Decimal("0")
    # Truck page fixes (2026-11-06): the highest credit limit —
    # the stored peak balance the account has ever stood at
    # (migration 0080; never decreases, nobody edits it).
    highest_balance: Decimal = Decimal("0")
    agreement_version: str | None
    agreement_accepted_at: datetime | None
    # "dealer" | "customer" | None — the caller's seat on it.
    my_role: str | None
    # The dark Connect seam's per-account answer: True only when
    # online payment is actually configured for this dealer.
    pay_online_available: bool = False
    created_at: datetime
    updated_at: datetime


class TruckEntryPublic(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    kind: str
    # SIGNED, as stored: charges positive, payments negative.
    amount: Decimal
    note: str
    item_link_id: uuid.UUID | None
    # Stage 2: the linked item resolved (name + kind) so the
    # ledger links through to the tool the charge was for.
    item_name: str | None = None
    item_kind: str | None = None
    entry_date: date
    source: str
    recorded_by: uuid.UUID | None
    recorded_by_name: str | None
    created_at: datetime


class PaymentRequestPublic(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    requested_by: uuid.UUID | None
    requested_by_name: str | None = None
    amount: Decimal
    note: str = ""
    # pending | approved | declined
    status: str
    entry_id: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    created_at: datetime


class ScheduleStatusPublic(BaseModel):
    # The computed schedule state (service.schedule_status):
    # missed payments counted + listed by date, never skipped.
    has_schedule: bool = False
    overdue: bool = False
    missed_payments: int = 0
    missed_due_dates: list[date] = []
    amount_past_due: Decimal = Decimal("0")
    days_until_due: int | None = None


class TruckTransferPublic(BaseModel):
    id: uuid.UUID
    from_agent_name: str
    to_agent_name: str
    from_agent_kind: str | None = None
    to_agent_kind: str | None = None
    created_at: datetime


class TransferOptionPublic(BaseModel):
    # "platform" (a verified agent user of the company) or
    # "private" (one of the customer's own agent records).
    kind: str
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    name: str


class AccountDetailPublic(BaseModel):
    account: TruckAccountPublic
    entries: list[TruckEntryPublic]
    # Present only for an INVITED customer looking at their own
    # invite (or a dealer previewing what the customer will see):
    # the agreement text acceptance will snapshot.
    agreement_preview: str | None = None
    # The account's transfer history (both parties' record) and,
    # for the customer, the agents it could move to.
    transfers: list[TruckTransferPublic] = []
    transfer_options: list[TransferOptionPublic] = []
    # Stage 2: the computed schedule state + the payment-request
    # conversation (agent asks, customer answers).
    schedule: ScheduleStatusPublic = ScheduleStatusPublic()
    payment_requests: list[PaymentRequestPublic] = []


# -- stage 2: the customer's seat -------------------------------------------------


class SelfOpenRequest(BaseModel):
    # The customer opens a self-kept account against ONE roster
    # agent: his own record (private_agent_id) or a connected
    # registered agent (agent_user_id) — exactly one.
    company_id: uuid.UUID
    private_agent_id: uuid.UUID | None = None
    agent_user_id: uuid.UUID | None = None
    # The opening balance he enters (0 = start empty); when > 0
    # it becomes the first ledger entry with opening_note (or
    # the standing "Opening balance" explanation).
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    opening_note: str = Field(default="", max_length=1000)
    payment_cadence: str = "weekly"
    payment_amount: Decimal | None = Field(default=None, gt=0)
    next_due_date: date | None = None
    payment_mode: str = "manual"


class SelfTargetPublic(BaseModel):
    # One roster agent the customer could open a self-kept
    # account with (or already has one with).
    kind: str  # "platform" | "private"
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    name: str
    is_preferred: bool = False
    has_open_account: bool = False


class PaymentModeRequest(BaseModel):
    payment_mode: str  # "automatic" | "manual"


class PaymentRequestCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    note: str = Field(default="", max_length=1000)


class PaymentRequestDecision(BaseModel):
    note: str = Field(default="", max_length=1000)


class TransferRequest(BaseModel):
    # Exactly one target: a platform agent of the same company,
    # or one of the customer's private agent records for it.
    to_agent_user_id: uuid.UUID | None = None
    to_private_agent_id: uuid.UUID | None = None


class IssuableCompanyPublic(BaseModel):
    company_id: uuid.UUID
    company_name: str


class RouteVisitPublic(BaseModel):
    agent_name: str
    company_name: str
    next_visit: date
    frequency: str | None = None


class StatusSummaryPublic(BaseModel):
    customer_open_accounts: int
    customer_total_balance: Decimal
    dealer_open_accounts: int
    dealer_total_outstanding: Decimal
    # Payments recorded in the current Monday-start calendar
    # week across the viewer's open accounts, both sides,
    # stated positive (the ledger stores payments negative).
    payments_this_week: Decimal
    route_visits: list[RouteVisitPublic] = []


class WizardAccountPublic(BaseModel):
    id: uuid.UUID
    agent_name: str
    balance: Decimal


class WizardAgentPublic(BaseModel):
    # One agent on the customer's roster for the company
    # (multi-preferred, 2026-11-05): his own active accounts, so
    # the wizard can offer a per-agent charge target.
    agent_user_id: uuid.UUID | None = None
    private_agent_id: uuid.UUID | None = None
    name: str = ""
    is_preferred: bool = False
    is_default: bool = False
    active_accounts: list[WizardAccountPublic] = []


class WizardContextPublic(BaseModel):
    # The Add wizard's truck question for one dealer company
    # (2026-10-31): the customer's active accounts under it,
    # whether an unaccepted invite is also waiting, and the
    # agent a self-opened tab would land under (None = the
    # customer's own records, no agent).
    company_id: uuid.UUID
    company_name: str
    active_accounts: list[WizardAccountPublic] = []
    invited_exists: bool = False
    new_account_agent_name: str | None = None
    # Every roster agent for the company (roster order); the
    # top-level account fields above are the display default's.
    agents: list[WizardAgentPublic] = []


class AcceptRequest(BaseModel):
    # The customer must affirmatively accept the CURRENT
    # agreement — the version they send must match what the
    # server renders, so a stale screen can't accept stale terms.
    agreement_version: str = Field(min_length=1, max_length=20)


class EntryCreate(BaseModel):
    kind: str  # charge | payment | adjustment
    # Positive for charge/payment; adjustments carry their own
    # sign (a negative adjustment lowers the balance).
    amount: Decimal
    note: str = Field(default="", max_length=1000)
    item_link_id: uuid.UUID | None = None
    entry_date: date | None = None  # defaults to today


class UpdateScheduleRequest(BaseModel):
    payment_cadence: str | None = None
    payment_amount: Decimal | None = Field(default=None, gt=0)
    next_due_date: date | None = None


class DashboardSummary(BaseModel):
    open_accounts: int
    total_outstanding: Decimal
    due_this_week: list[dict]
    overdue: list[dict]
