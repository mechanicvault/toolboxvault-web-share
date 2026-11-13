"""Maintenance module tables.

Owned exclusively by the maintenance module: SCHEDULES and their
service logs. Repairs used to live here too (repair_records, one
row per break->fix cycle) until the repairs ∪ claims merge
(2026-11-04, migration 0074): Ryan's ruling folded the repair
into the warranty claim — the claim carries the working end now
(sent-to, repair cost, completion) and the old records were
converted into claims. An item's CURRENT repair standing —
repair_state / repair_problem — still lives on the inventory
records themselves, like the dealer tag, because borrowing must
refuse a broken item without depending on this module; the
claims module's lifecycle is what writes it now.

- maintenance_schedules: per-item recurring care (calibration /
  service / inspection / other) with an interval and/or a fixed
  due date; next due is COMPUTED, never stored.
- maintenance_log_entries: each schedule's service history
  (date, cost, technician — the app's embedded event shape, as
  rows). Logging an entry advances the schedule's last_done_at.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Item kinds maintenance data can hang on. Pieces are set pieces —
# one socket of a set can break while the set itself works.
ITEM_KINDS = ("tool", "battery", "piece")

# Schedule kinds (the app's vocabulary: Calibration / Service /
# Inspection / custom).
SCHEDULE_KINDS = ("calibration", "service", "inspection", "other")

# Repair standing (stored on the inventory records; written by
# the claims lifecycle since the 2026-11-04 merge).
STATE_IN_SERVICE = "in_service"
STATE_BROKEN = "broken"
STATE_IN_REPAIR = "in_repair"
REPAIR_STATES = (STATE_IN_SERVICE, STATE_BROKEN, STATE_IN_REPAIR)

class MaintenanceSchedule(Base):
    """One recurring-care schedule on one item (tool or battery —
    pieces are not assets and carry no schedules).

    next_due is COMPUTED (service.next_due): last_done_at +
    interval_days when both exist, else the fixed due_date seed,
    else unknown. due_date is the one-off/first due date: once
    entries are logged against an interval schedule, the interval
    rules from the last logged date.
    """

    __tablename__ = "maintenance_schedules"

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

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="service")
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    interval_days: Mapped[int | None] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date)
    last_done_at: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaintenanceLogEntry(Base):
    """One performed service event against a schedule (the app's
    per-schedule history: date, cost, technician, notes)."""

    __tablename__ = "maintenance_log_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("maintenance_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    done_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    technician: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Documents for THIS service event (Package B, 2026-10-19) —
    # calibration certificates and the like: storage keys + metadata,
    # the same stored shape as item attachments (inventory's
    # attachments service owns the flow, collection "log_entries").
    attachments: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
