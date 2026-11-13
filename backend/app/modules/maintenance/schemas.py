"""Maintenance module schemas (schedules + standings since the
repairs ∪ claims merge retired the repair-record shapes)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# -- item standing --------------------------------------------------------


class PieceStanding(BaseModel):
    """One set piece's repair standing, for the set's detail page."""

    piece_id: uuid.UUID
    name: str
    kind: str  # core | addon
    state: str  # in_service | broken | in_repair
    problem: str


class ItemStanding(BaseModel):
    """One item's care picture for its detail page: current
    standing (the claims lifecycle writes it since the merge),
    its schedules, and — for sets — each piece's standing. The
    repair history itself lives on the item's claims now."""

    item_kind: str
    item_id: uuid.UUID
    item_name: str
    state: str  # in_service | broken | in_repair
    problem: str
    schedules: list["ScheduleView"]
    pieces: list[PieceStanding]


# -- schedules ------------------------------------------------------------


class LogAttachmentView(BaseModel):
    """One document on a log entry (Package B — calibration
    certificates): the shared item-attachment shape, read URL minted
    fresh at serialize time."""

    key: str
    filename: str
    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: str | None = None
    url: str


class LogEntryView(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    done_date: date
    cost: Decimal | None
    technician: str
    notes: str
    attachments: list[LogAttachmentView] = []
    created_at: datetime


class ScheduleView(BaseModel):
    id: uuid.UUID
    item_kind: str  # tool | battery
    item_id: uuid.UUID
    item_name: str
    kind: str  # calibration | service | inspection | other
    label: str
    interval_days: int | None
    due_date: date | None
    last_done_at: date | None
    # Computed at read time — never stored, so never stale.
    next_due: date | None
    due_status: str  # overdue | due_soon | ok | unknown
    log: list[LogEntryView]
    created_at: datetime
    updated_at: datetime


class ScheduleCreate(BaseModel):
    kind: str = Field(default="service", pattern="^(calibration|service|inspection|other)$")
    label: str = Field(default="", max_length=300)
    interval_days: int | None = Field(default=None, ge=1, le=36500)
    due_date: date | None = None
    last_done_at: date | None = None


class ScheduleUpdate(BaseModel):
    kind: str | None = Field(
        default=None, pattern="^(calibration|service|inspection|other)$"
    )
    label: str | None = Field(default=None, max_length=300)
    interval_days: int | None = Field(default=None, ge=1, le=36500)
    due_date: date | None = None
    last_done_at: date | None = None


class LogCreate(BaseModel):
    done_date: date | None = None  # defaults to today
    cost: Decimal | None = Field(default=None, ge=0)
    technician: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5000)


# -- module page + stats ----------------------------------------------------


class OutOfServiceEntry(BaseModel):
    item_kind: str  # tool | battery | piece
    item_id: uuid.UUID
    item_name: str
    set_id: uuid.UUID | None = None
    set_name: str = ""
    state: str  # broken | in_repair
    problem: str
    since: datetime | None  # when the open claim was started
    # The open warranty claim driving the repair, when there is
    # one (repairs ∪ claims merge, 2026-11-04) — the board links
    # straight at it.
    claim_id: uuid.UUID | None = None
    claim_number: str | None = None
    # The driving claim's own status (Repairs & Maintenance
    # merge, 2026-11-05): the board's row shows where the claim
    # stands next to the link. Rides with the other claim facts —
    # present only when the claims module is effective for the
    # reader (see service.out_of_service_board).
    claim_status: str | None = None


class MaintenanceOverview(BaseModel):
    out_of_service: list[OutOfServiceEntry]
    schedules: list[ScheduleView]


class MaintenanceStats(BaseModel):
    """The home stats: schedules due within 7 days (overdue counts
    too) and items currently out of service."""

    maintenance_due_count: int
    out_of_service_count: int


ItemStanding.model_rebuild()
