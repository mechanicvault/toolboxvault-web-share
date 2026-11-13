"""Borrowing module routes. HTTP layer only — logic lives in service.py.

Every route is gated on the borrowing FEATURE module being effective
for the caller (module doctrine): global switch + dependency health
(inventory must be usable) + one of the caller's groups assigned
(seeded defaults: mechanic + shop). A module that isn't effective
answers 403 {code: module_unavailable} via require_module.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core import vcard
from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.borrowing import schemas, service
from app.modules.core import service as core_service

router = APIRouter()

_borrowing_module = require_module("borrowing")


def _account(user: CurrentUser, db: Session):
    account = core_service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


def _view(db: Session, row) -> dict:
    """A checkout view with the owner's display name resolved (the
    borrower-facing surfaces need a face for the owner)."""
    owner = core_service.get_user_by_id(db, row.owner_id)
    return service.checkout_view(row, owner_name=owner.name if owner else None)


def _as_http(exc: service.BorrowingError) -> HTTPException:
    if isinstance(exc, service.BorrowingNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "borrowing", "status": "ok"}


@router.get("/counterparties", response_model=list[schemas.PersonView])
def counterparties(
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """People I can lend to by account: my accepted peer-grant
    counterparties (either direction)."""
    return service.counterparties(db, _account(user, db))


@router.get("/overview", response_model=schemas.BorrowingOverview)
def overview(
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    return service.overview(db, _account(user, db))


@router.get("/stats", response_model=schemas.BorrowingStats)
def borrowing_stats(
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """The Checked Out home stat: my items currently out."""
    return service.stats(db, user.id)


@router.post(
    "/checkouts",
    response_model=schemas.CheckoutView,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout(
    payload: schemas.CheckoutCreate,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Lend one of my items now — to a linked person or a manual name."""
    try:
        row = service.create_checkout(
            db,
            _account(user, db),
            item_kind=payload.item_kind,
            item_id=payload.item_id,
            borrower_user_id=payload.borrower_user_id,
            borrower_name=payload.borrower_name,
            borrower_contact=payload.borrower_contact,
            borrower_contact_id=payload.borrower_contact_id,
            due_at=payload.due_at,
            notes=payload.notes,
            include_addons=payload.include_addons,
        )
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


@router.post(
    "/requests",
    response_model=schemas.CheckoutView,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: schemas.BorrowRequestCreate,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Ask an owner whose list is shared with me to borrow an item."""
    try:
        row = service.request_borrow(
            db,
            _account(user, db),
            owner_id=payload.owner_id,
            item_kind=payload.item_kind,
            item_id=payload.item_id,
            due_at=payload.due_at,
            notes=payload.notes,
        )
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


@router.get("/items/{item_kind}/{item_id}", response_model=schemas.ItemLending)
def item_lending(
    item_kind: str,
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """An item's lending standing (current lend + full history) for
    its owner's detail page."""
    if item_kind not in ("tool", "battery"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Items are tools or batteries.",
        )
    try:
        return service.item_lending(db, _account(user, db), item_kind, item_id)
    except service.BorrowingError as exc:
        raise _as_http(exc)


@router.post("/{checkout_id}/approve", response_model=schemas.CheckoutView)
def approve(
    checkout_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.decide(db, _account(user, db), checkout_id, approve=True)
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


@router.post("/{checkout_id}/decline", response_model=schemas.CheckoutView)
def decline(
    checkout_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.decide(db, _account(user, db), checkout_id, approve=False)
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


@router.post("/{checkout_id}/cancel", response_model=schemas.CheckoutView)
def cancel(
    checkout_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """The borrower withdraws their pending request."""
    try:
        row = service.cancel_request(db, _account(user, db), checkout_id)
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


@router.post("/{checkout_id}/return", response_model=schemas.CheckoutView)
def mark_returned(
    checkout_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Either party marks the item returned; the row records who."""
    try:
        row = service.mark_returned(db, _account(user, db), checkout_id)
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return _view(db, row)


# -- borrower address book (gap wave 1, 2026-10-20) -----------------------------


@router.get(
    "/borrowers", response_model=list[schemas.BorrowerContactPublic]
)
def list_borrowers(
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    owner = _account(user, db)
    return [
        service.serialize_borrower_contact(db, row)
        for row in service.list_borrower_contacts(db, owner)
    ]


@router.post(
    "/borrowers",
    response_model=schemas.BorrowerContactPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_borrower(
    payload: schemas.BorrowerContactCreate,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.create_borrower_contact(
            db, _account(user, db), payload.model_dump()
        )
    except service.BorrowingError as exc:
        raise _as_http(exc)
    return service.serialize_borrower_contact(db, row)


# -- contact cards: vCard export / import (contact cards lane, 2026-11-07) -----
#
# Registered BEFORE the /borrowers/{contact_id} routes on
# purpose: "export.vcf" must win over the {contact_id} segment.


def _vcf_response(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/borrowers/export.vcf")
def export_borrowers_vcf(
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """The whole address book as one .vcf — every contact as a
    card a phone's contacts app can open."""
    body = service.export_borrower_cards(db, _account(user, db))
    return _vcf_response(body, "toolbox-vault-borrowers.vcf")


@router.get("/borrowers/{contact_id}/export.vcf")
def export_borrower_vcf(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """One borrower's contact card."""
    owner = _account(user, db)
    row = service.get_borrower_contact(db, owner, contact_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That borrower isn't in your address book.",
        )
    return _vcf_response(
        service.borrower_contact_card(row), vcard.download_filename(row.name)
    )


@router.post("/borrowers/import/preview", response_model=schemas.ImportPreview)
async def preview_borrower_import(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Parse an uploaded .vcf and show what WOULD land: one row
    per readable card, likely duplicates flagged, unreadable
    cards as soft errors. Creates nothing."""
    data = await file.read(vcard.MAX_FILE_BYTES + 1)
    if len(data) > vcard.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file is too large for a contact import (2 MB max).",
        )
    cards, total = vcard.parse_vcf(data)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file doesn't contain any contact cards.",
        )
    preview = service.preview_borrower_import(db, _account(user, db), cards)
    preview["total_cards"] = total
    return preview


@router.post(
    "/borrowers/import",
    response_model=schemas.BorrowerImportResult,
    status_code=status.HTTP_201_CREATED,
)
def import_borrowers(
    payload: schemas.BorrowerImportRequest,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Create exactly the rows the owner confirmed in the
    preview — nothing more, nothing merged."""
    owner = _account(user, db)
    created = service.import_borrower_contacts(
        db, owner, [row.model_dump() for row in payload.contacts]
    )
    return {
        "created": [
            service.serialize_borrower_contact(db, row) for row in created
        ],
        "count": len(created),
    }


@router.get(
    "/borrowers/{contact_id}", response_model=schemas.BorrowerRollup
)
def borrower_rollup(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """The contact + their lending roll-up (current holds, full
    history) from the ledger."""
    rollup = service.borrower_rollup(db, _account(user, db), contact_id)
    if rollup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That borrower isn't in your address book.",
        )
    return rollup


@router.put(
    "/borrowers/{contact_id}", response_model=schemas.BorrowerContactPublic
)
def update_borrower(
    contact_id: uuid.UUID,
    payload: schemas.BorrowerContactUpdate,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    try:
        row = service.update_borrower_contact(
            db,
            _account(user, db),
            contact_id,
            payload.model_dump(exclude_unset=True),
        )
    except service.BorrowingError as exc:
        raise _as_http(exc)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That borrower isn't in your address book.",
        )
    return service.serialize_borrower_contact(db, row)


@router.delete("/borrowers/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_borrower(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """Remove the book entry — checkout history is NEVER touched
    (lends keep their snapshots)."""
    if not service.delete_borrower_contact(
        db, _account(user, db), contact_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That borrower isn't in your address book.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{checkout_id}/nudge", response_model=schemas.NudgeResult)
def nudge_borrower(
    checkout_id: uuid.UUID,
    user: CurrentUser = Depends(_borrowing_module),
    db: Session = Depends(get_db),
):
    """A polite pre-written reminder for a lend that's out (built
    for overdue ones). Delivered in-app when the borrower is a
    linked platform user; otherwise returned as copy-text."""
    owner = _account(user, db)
    row = db.get(service.models.Checkout, checkout_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That lend isn't available.",
        )
    try:
        return service.deliver_nudge(db, owner, row)
    except service.BorrowingError as exc:
        raise _as_http(exc)
