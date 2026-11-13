"""Cloud backup routes (wave 4): the Settings -> Cloud backup
surface. Mounted by core's router at /api/core/cloud-backup.

The connect flow leaves the API (browser redirect to Google)
and returns through the callback, which lands the browser back
on the settings page with a result flag in the query string.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import audit, cloud_backup, service

router = APIRouter()


class CloudBackupRunView(BaseModel):
    id: str
    trigger: str
    status: str
    file_name: str
    size_bytes: int
    error: str
    started_at: datetime
    finished_at: datetime | None
    drive_url: str | None


class CloudBackupState(BaseModel):
    connected: bool
    folder_name: str
    schedule: str
    connected_at: datetime | None
    last_backup_at: datetime | None
    history: list[CloudBackupRunView]


class ScheduleUpdate(BaseModel):
    schedule: Literal["off", "daily", "weekly", "monthly"]


def _state(db: Session, user: CurrentUser) -> dict:
    state = cloud_backup.state_for(db, user)
    state["history"] = [
        {**row, "id": str(row["id"])} for row in state["history"]
    ]
    return state


@router.get("/cloud-backup", response_model=CloudBackupState)
def cloud_backup_state(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _state(db, user)


@router.get("/cloud-backup/connect")
def cloud_backup_connect(user: CurrentUser = Depends(get_current_user)):
    """Start the connect round-trip. 503 while the site's Google
    client isn't configured (the same posture as Google sign-in)."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "oauth_not_configured",
                "message": "Google sign-in isn't configured for this site yet.",
            },
        )
    state = cloud_backup.create_connect_state(user.id)
    return {"authorize_url": cloud_backup.authorize_url(state)}


@router.get("/cloud-backup/callback")
def cloud_backup_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Google's return leg. The user rides the signed state (the
    request itself is cookieless); the browser lands back on the
    settings section either way, with the outcome in the query.

    The state's purpose dispatches: "cloud_connect" is the user
    feature (unchanged); "platform_drive_connect" is the Disaster
    Vault connection, which lands on Admin -> Settings instead
    and requires the state-bound user to be an operator."""
    parsed = cloud_backup.parse_connect_state_with_purpose(state) if state else None
    if parsed is not None and parsed[1] == cloud_backup.PLATFORM_CONNECT_PURPOSE:
        target = "/admin/settings"
        if error or not code:
            return RedirectResponse(f"{target}?drive=denied", status_code=302)
        user = service.get_user_by_id(db, parsed[0])
        if user is None or not user.is_operator:
            return RedirectResponse(f"{target}?drive=denied", status_code=302)
        try:
            connection = cloud_backup.complete_platform_connection(db, user, code)
        except cloud_backup.DriveError:
            return RedirectResponse(f"{target}?drive=failed", status_code=302)
        audit.record(
            db,
            user,
            action="backup_drive.connect",
            target=connection.drive_folder_id or "platform-drive",
            detail={"email": connection.drive_email},
        )
        return RedirectResponse(f"{target}?drive=connected", status_code=302)
    target = "/settings/cloud-backup"
    user_id = cloud_backup.parse_connect_state(state) if state else None
    if error or not code or user_id is None:
        return RedirectResponse(f"{target}?cloud=denied", status_code=302)
    user = service.get_user_by_id(db, user_id)
    if user is None:
        return RedirectResponse(f"{target}?cloud=denied", status_code=302)
    try:
        cloud_backup.complete_connection(db, user, code)
    except cloud_backup.DriveError:
        return RedirectResponse(f"{target}?cloud=failed", status_code=302)
    return RedirectResponse(f"{target}?cloud=connected", status_code=302)


@router.put("/cloud-backup/schedule", response_model=CloudBackupState)
def cloud_backup_schedule(
    payload: ScheduleUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = cloud_backup.connection_for(db, user.id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Google Drive first.",
        )
    connection.schedule = payload.schedule
    db.commit()
    return _state(db, user)


@router.post("/cloud-backup/run", response_model=CloudBackupState)
def cloud_backup_run(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Back up now. The attempt is ledgered; a failure answers
    with the state (the history row + inbox notice carry the
    error) rather than an exception — the user is looking at the
    history list either way."""
    if cloud_backup.connection_for(db, user.id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Google Drive first.",
        )
    cloud_backup.run_backup(db, user, trigger="manual")
    return _state(db, user)


@router.post("/cloud-backup/disconnect", response_model=CloudBackupState)
def cloud_backup_disconnect(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cloud_backup.disconnect(db, user)
    return _state(db, user)
