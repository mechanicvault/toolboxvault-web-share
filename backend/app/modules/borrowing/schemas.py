"""Borrowing module request/response shapes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CheckoutCreate(BaseModel):
    """Owner-initiated checkout: lend one of my items right now.

    The borrower is EITHER a linked counterparty
    (borrower_user_id) OR a manual name (+ optional contact) —
    never both; the service resolves and validates the choice."""

    item_kind: str = Field(pattern="^(tool|battery)$")
    item_id: uuid.UUID
    borrower_user_id: uuid.UUID | None = None
    borrower_name: str | None = Field(default=None, max_length=300)
    borrower_contact: str = Field(default="", max_length=300)
    # Address book (gap wave 1): pick a saved borrower — the
    # service prefills the manual name/contact from the book and
    # stamps the link on the ledger row.
    borrower_contact_id: uuid.UUID | None = None
    due_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)
    # SETS: the checkout modal's answer to "include the addon
    # pieces too?" — sibling rows cover the attached addon tools.
    include_addons: bool = False


class BorrowRequestCreate(BaseModel):
    """A peer request: I ask an owner (whose list is shared with me
    under an accepted grant) to borrow one item on their list."""

    owner_id: uuid.UUID
    item_kind: str = Field(pattern="^(tool|battery)$")
    item_id: uuid.UUID
    due_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)


class PersonView(BaseModel):
    id: str
    name: str
    account_number: str


class CheckoutView(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    owner_name: str | None = None
    item_kind: str
    item_id: uuid.UUID
    item_name: str
    # Set lends: sibling rows share a group id (null otherwise).
    group_id: uuid.UUID | None = None
    borrower_user_id: uuid.UUID | None
    borrower_name: str
    borrower_contact: str
    borrower_contact_id: uuid.UUID | None = None
    state: str
    requested_at: datetime
    decided_at: datetime | None
    checked_out_at: datetime | None
    due_at: datetime | None
    returned_at: datetime | None
    returned_by: str | None
    notes: str
    overdue: bool
    created_at: datetime
    updated_at: datetime


class BorrowingCounts(BaseModel):
    pending_requests: int
    checked_out: int
    borrowed: int
    overdue: int


class BorrowingOverview(BaseModel):
    requests_for_me: list[CheckoutView]
    my_requests: list[CheckoutView]
    lent_out: list[CheckoutView]
    borrowed_by_me: list[CheckoutView]
    history: list[CheckoutView]
    counts: BorrowingCounts


class BorrowingStats(BaseModel):
    checked_out_count: int
    borrowed_by_me_count: int


class ItemLending(BaseModel):
    item_kind: str
    item_id: uuid.UUID
    current: CheckoutView | None
    history: list[CheckoutView]


# -- borrower address book (gap wave 1) -------------------------------------------


class BorrowerContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    contact: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5000)
    # Optional link to the borrower's own Toolbox Vault account —
    # powers in-app nudge delivery.
    linked_user_id: uuid.UUID | None = None


class BorrowerContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    contact: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=5000)
    linked_user_id: uuid.UUID | None = None


class BorrowerContactPublic(BaseModel):
    id: uuid.UUID
    name: str
    contact: str
    notes: str
    linked_user_id: uuid.UUID | None = None
    current_holds: int = 0
    total_lends: int = 0
    created_at: datetime
    updated_at: datetime


class BorrowerRollup(BaseModel):
    contact: BorrowerContactPublic
    # Lends out with this borrower right now.
    current: list[CheckoutView] = []
    # The full ledger history linked to the contact, newest first.
    history: list[CheckoutView] = []


# -- contact cards: vCard import (contact cards lane, 2026-11-07) ---------------


class ImportPreviewRow(BaseModel):
    index: int
    name: str
    contact: str
    notes: str
    # Likely duplicate of a book entry (same name + a shared
    # phone or email). Flagged only — the owner decides per row.
    duplicate: bool = False
    duplicate_of: str | None = None


class ImportPreviewError(BaseModel):
    index: int
    message: str


class ImportPreview(BaseModel):
    rows: list[ImportPreviewRow] = []
    errors: list[ImportPreviewError] = []
    total_cards: int = 0


class BorrowerImportRow(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    contact: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5000)


class BorrowerImportRequest(BaseModel):
    # The rows the owner confirmed in the preview — created
    # verbatim through the ordinary create path.
    contacts: list[BorrowerImportRow] = Field(max_length=500)


class BorrowerImportResult(BaseModel):
    created: list[BorrowerContactPublic] = []
    count: int = 0


class NudgeResult(BaseModel):
    # The pre-written reminder text (always returned — the owner
    # can copy it even when it was also delivered in-app).
    message: str
    # "message" = delivered through the messaging module;
    # "copy" = hand it over yourself (tel/sms/mailto in the UI).
    delivered_via: str
    thread_id: uuid.UUID | None = None
