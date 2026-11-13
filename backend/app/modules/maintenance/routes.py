"""Maintenance module routes. HTTP layer only — logic lives in service.py.

Every route is gated on the maintenance FEATURE module being
effective for the caller (module doctrine): global switch +
dependency health (inventory must be usable) + one of the caller's
groups assigned (seeded defaults: mechanic + shop). A module that
isn't effective answers 403 {code: module_unavailable} via
require_module.

ONE exception (Repairs & Maintenance merge, 2026-11-05):
GET /out-of-service is gated on the inventory module instead —
on the merged page the board is the landing tab and rides on
inventory, so it outlives the maintenance module being off.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.core import service as core_service
from app.modules.inventory import schemas as inventory_schemas
from app.modules.maintenance import schemas, service

router = APIRouter()

_maintenance_module = require_module("maintenance")

# The out-of-service board's own gate (Repairs & Maintenance
# merge, 2026-11-05): on the merged page the board is the
# landing tab and rides on the INVENTORY module — it must stay
# reachable for a user whose maintenance module is off, so this
# one route answers to inventory, not to maintenance.
_inventory_module = require_module("inventory")

_ITEM_KINDS = ("tool", "battery", "piece")


def _account(user: CurrentUser, db: Session):
    account = core_service.get_user_by_id(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


def _as_http(exc: service.MaintenanceError) -> HTTPException:
    if isinstance(exc, service.MaintenanceNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _check_kind(item_kind: str) -> None:
    if item_kind not in _ITEM_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Items are tools, batteries, or set pieces.",
        )


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "maintenance", "status": "ok"}


@router.get("/overview", response_model=schemas.MaintenanceOverview)
def overview(
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    """The module page: out-of-service board + all schedules."""
    return service.overview(db, _account(user, db))


@router.get(
    "/out-of-service", response_model=list[schemas.OutOfServiceEntry]
)
def out_of_service(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The out-of-service board alone, for the merged Repairs &
    Maintenance page's landing tab. Gated on inventory (the
    board is inventory standings); claim facts ride only while
    the claims module is effective for the caller — the service
    resolves that per user."""
    return service.out_of_service_board(db, _account(user, db))


@router.get("/stats", response_model=schemas.MaintenanceStats)
def maintenance_stats(
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    """The Maintenance Due + Out of Service home stats."""
    return service.stats(db, user.id)


# -- item standing -------------------------------------------------------------


@router.get(
    "/items/{item_kind}/{item_id}", response_model=schemas.ItemStanding
)
def item_standing(
    item_kind: str,
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    _check_kind(item_kind)
    try:
        return service.item_standing(db, _account(user, db), item_kind, item_id)
    except service.MaintenanceError as exc:
        raise _as_http(exc)


# -- schedules -------------------------------------------------------------------


@router.post(
    "/items/{item_kind}/{item_id}/schedules",
    response_model=schemas.ScheduleView,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    item_kind: str,
    item_id: uuid.UUID,
    payload: schemas.ScheduleCreate,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    if item_kind not in ("tool", "battery"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Schedules belong to tools or batteries.",
        )
    account = _account(user, db)
    try:
        row = service.create_schedule(
            db,
            account,
            item_kind=item_kind,
            item_id=item_id,
            kind=payload.kind,
            label=payload.label,
            interval_days=payload.interval_days,
            due_date=payload.due_date,
            last_done_at=payload.last_done_at,
        )
    except service.MaintenanceError as exc:
        raise _as_http(exc)
    return service.schedule_view(db, row)


@router.patch(
    "/schedules/{schedule_id}", response_model=schemas.ScheduleView
)
def update_schedule(
    schedule_id: uuid.UUID,
    payload: schemas.ScheduleUpdate,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    account = _account(user, db)
    try:
        row = service.update_schedule(
            db, account, schedule_id, **payload.model_dump(exclude_unset=True)
        )
    except service.MaintenanceError as exc:
        raise _as_http(exc)
    return service.schedule_view(db, row)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: uuid.UUID,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    if not service.delete_schedule(db, _account(user, db), schedule_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That schedule doesn't exist.",
        )


@router.post(
    "/schedules/{schedule_id}/log",
    response_model=schemas.LogEntryView,
    status_code=status.HTTP_201_CREATED,
)
def log_done(
    schedule_id: uuid.UUID,
    payload: schemas.LogCreate,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    """Log performed work — advances the schedule's next due."""
    try:
        entry = service.log_done(
            db,
            _account(user, db),
            schedule_id,
            done_date=payload.done_date,
            cost=payload.cost,
            technician=payload.technician,
            notes=payload.notes,
        )
    except service.MaintenanceError as exc:
        raise _as_http(exc)
    return service.log_view(entry)


# -- log entry documents (Package B: calibration certificates) ---------
# A log entry's documents ride the INVENTORY attachment machinery
# (presigned upload → attach), collection "log_entries" — the entry
# is the record, the item's detail page lists them under the
# schedule's log, and the item's documents section links them.


@router.post(
    "/log-entries/{entry_id}/upload-url",
    response_model=inventory_schemas.UploadUrlResponse,
)
def get_log_entry_upload_url(
    entry_id: uuid.UUID,
    payload: inventory_schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    from app.modules.inventory import attachments

    try:
        return attachments.issue_upload_url(
            db, user.id, entry_id, payload, collection="log_entries"
        )
    except attachments.RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except attachments.UploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )


@router.post("/log-entries/{entry_id}/attachments", response_model=dict)
def attach_log_entry_file(
    entry_id: uuid.UUID,
    payload: inventory_schemas.AttachRequest,
    user: CurrentUser = Depends(_maintenance_module),
    db: Session = Depends(get_db),
):
    from app.modules.inventory import attachments

    try:
        return attachments.attach_file(
            db, user.id, entry_id, payload, collection="log_entries"
        )
    except attachments.RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except attachments.UploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

