"""Borrowing module tables.

Owned exclusively by the borrowing module. Other modules read lending
data through service.py, never by importing these models.

The app this replaces kept lending EMBEDDED in tool records
(`current_checkout` + `checkout_history` inside every tool document;
its standalone `checkouts` collection was empty). The website builds
it properly: one ledger table, one row per lend, rows NEVER deleted —
the table IS the history. State transitions only.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# The lifecycle. Terminal states: returned / declined / cancelled.
STATE_REQUESTED = "requested"
STATE_CHECKED_OUT = "checked_out"
STATE_RETURNED = "returned"
STATE_DECLINED = "declined"
STATE_CANCELLED = "cancelled"

STATES = (
    STATE_REQUESTED,
    STATE_CHECKED_OUT,
    STATE_RETURNED,
    STATE_DECLINED,
    STATE_CANCELLED,
)

# States in which the item is spoken for: at most ONE such row may
# exist per item at a time (the partial unique index below).
ACTIVE_STATES = (STATE_REQUESTED, STATE_CHECKED_OUT)

ITEM_KINDS = ("tool", "battery")


class Checkout(Base):
    """One lend of one item (tool or battery) to one borrower.

    The borrower is either a LINKED user (borrower_user_id — a peer
    counterparty with an account; they can see the lend, act on it,
    and get inbox notifications) or a MANUAL name/contact pair for
    people without an account (the app's borrowers-list pattern).
    borrower_name is a snapshot in both cases: a linked user's name
    at lend time, so the ledger stays readable if they later rename.

    item_name is likewise a snapshot: history must survive the item
    being renamed or deleted, so the row never depends on a join to
    render. item_id is deliberately NOT a foreign key — the ledger
    outlives the item.
    """

    __tablename__ = "checkouts"
    # SET LENDS (item structure package, 2026-10-18): lending a set
    # with its addons creates one row per covered tool (the set row
    # plus one per attached addon tool), all sharing one `group_id`.
    # Returning any row of the group returns them all. NULL = an
    # ordinary single-item lend (every pre-sets row).
    __table_args__ = (
        # One active lend per item, enforced by the database itself
        # (the service pre-checks for a friendly error; this index is
        # the race-proof backstop, Postgres partial index + its
        # SQLite twin for the test suite).
        Index(
            "uq_checkouts_one_active_per_item",
            "item_kind",
            "item_id",
            unique=True,
            postgresql_where=text("state IN ('requested', 'checked_out')"),
            sqlite_where=text("state IN ('requested', 'checked_out')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    item_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    borrower_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    # Borrower address book (gap wave 1, 2026-10-20): when the lend
    # was made by picking one of the owner's saved contacts, the
    # contact's id rides along as the roll-up link. A PLAIN column
    # (no FK): the ledger is history — deleting the contact later
    # must never touch it; the name/contact snapshots above keep
    # the row readable on their own.
    borrower_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )
    borrower_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    borrower_contact: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )

    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATE_REQUESTED, index=True
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 'owner' | 'borrower' — who marked the return (either party may;
    # the row records who, see service.mark_returned).
    returned_by: Mapped[str | None] = mapped_column(String(20))

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Monotonic insertion order (hardening 2026-10-19). created_at
    # alone cannot order the history: SQLite's now() has SECOND
    # resolution, so two lends created in the same tick tie, and the
    # old random-UUID tiebreaker ordered tied rows arbitrarily (the
    # flaky history test). seq is assigned by the before_insert hook
    # below in true insertion order and is the ordering tiebreaker
    # after created_at (service._history_order). No default here:
    # the hook is the single assignment path, so every writer —
    # service code today, anything else tomorrow — gets a value.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)


@event.listens_for(Checkout, "before_insert")
def _assign_checkout_seq(mapper, connection, target):  # noqa: ANN001, ANN202
    """Give every new checkout the next sequence value.

    Postgres draws from the real `checkouts_seq` sequence (created
    by migration 0023; atomic across concurrent writers). SQLite
    has no sequences SQLAlchemy will fire, so it takes max+1 inside
    the insert transaction — its writers serialize, so the value is
    still strictly increasing in insertion order. Behavior (a
    per-row, ever-increasing integer) is identical on both.
    """
    if target.seq is not None:
        return
    if connection.dialect.name == "postgresql":
        target.seq = connection.scalar(text("SELECT nextval('checkouts_seq')"))
    else:
        target.seq = connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM checkouts")
        )


class BorrowerContact(Base):
    """One reusable borrower in the owner's address book (gap
    wave 1, 2026-10-20) — the app's borrowers list, done as its
    own records: name + free-text contact info + notes, so the
    check-out flow can pick a person instead of re-typing them.

    Records are the owner's private data: CRUD is owner-scoped,
    deleting one NEVER touches the checkout ledger (lends keep
    their name/contact snapshots; the borrower_contact_id link on
    a checkout is a plain column that simply stops resolving).
    """

    __tablename__ = "borrower_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Free text: a phone, an email, "the guy at the marina" —
    # whatever the owner uses to reach them. The nudge surface
    # picks tel:/sms:/mailto: candidates out of it best-effort.
    contact: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # When the borrower is ALSO a Toolbox Vault user, the owner's
    # optional link to their account (set in the UI when known) —
    # it powers the Nudge's in-app delivery. The link is a
    # convenience pointer only: history never depends on it (the
    # checkouts carry their own borrower_contact_id + snapshots).
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
