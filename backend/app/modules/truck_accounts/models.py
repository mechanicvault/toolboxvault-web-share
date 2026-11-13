"""Truck Accounts tables (wave 2, 2026-10-20).

A truck account is a two-party running tab between a DEALER
(the tool-truck agent) and a CUSTOMER (a mechanic on the truck's
route): the dealer charges tools against it, the customer pays
it down on a weekly / bi-weekly cadence.

Two deliberate schema choices:

- dealer_user_id / customer_user_id / recorded_by are PLAIN
  columns, NOT foreign keys — the 0038 warranty lesson: a
  two-party table whose user columns are FKs BLOCKS account
  deletion on Postgres. Core's deletion cascade tombstones these
  rows instead (sets the *_deleted flags, closes the account,
  keeps the ledger with the customer_name snapshot). Entries are
  children of their account (real FK, CASCADE) and never outlive
  it; the account row itself dies only when BOTH parties are
  gone (the cascade removes it then, entries with it).

- The balance is NEVER stored: it is SUM(truck_entries.amount)
  computed at read time, with entry amounts SIGNED by kind —
  charges positive (money owed grows), payments negative,
  adjustments as entered. A test pins computed == ledger sum so
  the two can never drift apart silently.

Agreement: acceptance stores the version + the FULL TEXT the
customer saw (agreement_text_snapshot) + the timestamp — the
record of consent the payment authorization stands on.

Agent revision (2026-10-31, migration 0068): the issuer is a
specific dealer AGENT acting under a dealer COMPANY. The
account carries the company link (dealer_company_id + name
snapshot) so it nests under that company's dealer page, a
credit_limit (the line the agent extended), and an agent holder
in the claims exactly-one shape: dealer_user_id (a platform
agent user) OR private_agent_id (one of the CUSTOMER's private
agent records — while it is set, dealer_user_id is NULL and the
customer maintains the tab himself). Route changes never move
an account; only the customer transfers it (TruckAccountTransfer
rows are that history). dealer_user_id is therefore NULLABLE
from 0068 on — NULL exactly while a private agent holds the
account (or the holding agent's account is gone).

Stage 2 (2026-11-05, migration 0077): the MECHANIC's seat. An
account now also carries WHO KEEPS THE LEDGER —
ledger_keeper "agent" (the classic tab: the agent's pen writes
charges; the shape every pre-stage-2 account already had) or
"customer" (a SELF-KEPT account the customer opened against
any agent on his roster, with his own opening balance, no
agreement gate, no verified-representation requirement; he
records every entry kind himself). A customer-kept account
held by a platform agent (directly, or via a takeover-claimed
record) is SHARED: the agent sees the tab, can record payments
he received, and can REQUEST a payment — the customer's
approval of a request is what writes the payment entry
(TruckPaymentRequest). payment_mode is the customer's stored
pay-through-the-site choice ("manual" | "automatic"): state
only — it takes effect when payment processing connects; no
money moves on it today.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUSES = ("invited", "active", "closed")
CADENCES = ("weekly", "biweekly")
ENTRY_KINDS = ("charge", "payment", "adjustment")
# Stage 2 (2026-11-05): who keeps the ledger (see the module
# docstring) and the customer's pay-through-the-site choice.
LEDGER_KEEPERS = ("agent", "customer")
PAYMENT_MODES = ("manual", "automatic")
REQUEST_STATUSES = ("pending", "approved", "declined")


class TruckAccount(Base):
    __tablename__ = "truck_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # PLAIN columns (see module docstring) — no FKs on purpose.
    # NULLABLE since 0068: NULL exactly while a private agent
    # record holds the account (private_agent_id set) — and the
    # pair (dealer_user_id, private_agent_id) is the claims
    # exactly-one agent shape, kept by the service.
    dealer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # The dealer COMPANY this account is under (0068): a real FK
    # (SET NULL — the company is factual context; a deleted
    # company leaves the tab standing on its name snapshot).
    dealer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )
    dealer_company_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # The customer's OWN private agent record, when the account's
    # agent is not on the platform (0068). SET NULL: if the
    # customer deletes the record, the account reads agent-less
    # rather than dangling — the name snapshot keeps who it was.
    private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="SET NULL"),
        index=True,
    )
    # Who the agent was, as the customer saw the name at issue /
    # last transfer — the surviving label if the agent's account
    # or record later goes away.
    agent_name_snapshot: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # The credit line the issuing agent extended (0068). NULL =
    # no line recorded. The BALANCE is still never stored — it
    # is SUM(truck_entries.amount) at read time, as always.
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # The HIGHEST CREDIT LIMIT (owner's label + rule,
    # 2026-11-05; migration 0080): the highest balance this
    # account has ever stood at — the peak of what was owed.
    # Unlike the balance this one IS stored, precisely so it
    # can NEVER decrease: every entry write raises it to the
    # balance when the balance tops it, and nothing ever lowers
    # it — not a payment, not a downward adjustment, not a
    # later ledger correction. System-maintained; no form
    # anywhere writes it. Backfilled at 0080 from each
    # account's ledger history (max running balance).
    highest_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"),
        server_default="0",
    )
    customer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # The invite address + the display-name snapshot. The snapshot
    # is what the surviving party's ledger shows after the other
    # side deletes their account.
    customer_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    customer_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # invited | active | closed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="invited"
    )
    # The pre-signup attach token: the signup that claims the
    # invited email presents it (peer-invite pattern).
    invite_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    agreement_version: Mapped[str | None] = mapped_column(String(20))
    agreement_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    agreement_text_snapshot: Mapped[str | None] = mapped_column(Text)

    # weekly | biweekly
    payment_cadence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="weekly"
    )
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    next_due_date: Mapped[date | None] = mapped_column(Date)

    # Stage 2 (0077): who keeps the ledger — "agent" (the
    # classic agent-issued tab) or "customer" (a self-kept
    # account the customer opened from his own seat). NOT NULL
    # with the "agent" default so every pre-stage-2 row keeps
    # exactly the behavior it already had.
    ledger_keeper: Mapped[str] = mapped_column(
        String(12), nullable=False, default="agent", server_default="agent"
    )
    # Stage 2 (0077): the customer's pay-through-the-site
    # choice — "manual" (he approves/records each payment) or
    # "automatic" (scheduled payments run themselves once
    # payment processing is connected). Stored state only:
    # Stripe Connect stays dark, nothing charges on this.
    payment_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="manual", server_default="manual"
    )

    # Deletion tombstones (core cascade writes these).
    customer_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    dealer_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TruckEntry(Base):
    __tablename__ = "truck_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("truck_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized from the account: the change journal attributes
    # an entry to its dealer without a join (the journal owner's
    # rule reads this column). NULLABLE since 0068: an entry
    # recorded while a private agent holds the account attributes
    # to no platform dealer — the column reads as-is.
    dealer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # charge | payment | adjustment
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # SIGNED: charges positive, payments negative, adjustments as
    # entered (a positive adjustment raises the balance).
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Optional link to the inventory item a charge was for (plain
    # id, stored only — no cross-module join on the read path).
    item_link_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # manual | online | migrated (the app converter maps
    # dealer_payment_accounts here with source=migrated later).
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual"
    )
    # PLAIN column (who recorded it; survives their deletion).
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TruckAccountTransfer(Base):
    """One customer-initiated transfer of a truck account from
    one agent to another (2026-10-31). Route changes NEVER move
    an account on their own — this row is the only way the agent
    holder changes after issue, and it is the account's history
    of those moves: from/to pointers (platform user OR private
    record, the exactly-one shape) PLUS name snapshots, all
    PLAIN columns so the history survives either side deleting
    their account (the snapshots carry who was who). Entries are
    children of their account (real FK, CASCADE)."""

    __tablename__ = "truck_account_transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("truck_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_agent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    from_private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    from_agent_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    to_agent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    to_private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    to_agent_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # PLAIN column: the customer who made the transfer.
    transferred_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TruckPaymentRequest(Base):
    """One AGENT's ask for a payment on a customer-kept shared
    account (stage 2, 2026-11-05, migration 0077). The agent
    requests; the CUSTOMER approves or declines. Approval is
    what writes the payment entry — entry_id points at it (a
    PLAIN column: the entry is a child of the same account and
    dies with it) — and the entry carries source
    "agent_request" so the ledger itself shows the payment was
    requested-by-agent and customer-confirmed. Declining closes
    the request with an optional note. User columns are PLAIN
    (the truck tables' posture): a deleted party leaves the
    request standing on the account with the decision intact.
    Requests exist only where a platform agent seat faces a
    customer-kept ledger — on agent-kept accounts the agent
    holds the pen already and asks nobody."""

    __tablename__ = "truck_payment_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("truck_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # PLAIN columns (see the class docstring).
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # pending | approved | declined
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # The ledger entry approval wrote (plain id; see docstring).
    entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    decision_note: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
