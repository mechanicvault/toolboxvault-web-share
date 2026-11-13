"""Cloud (Google Drive) user auto-backups (wave 4).

Settings -> Cloud backup: a user connects THEIR OWN Google
Drive (OAuth, the single scope drive.file — the app can only
ever touch files it created), and the platform sends them the
same export ZIP the manual Export produces, on their schedule
(off | daily | weekly | monthly), keeping the newest 7.

Pieces:
  - Tokens: the refresh token is stored ENCRYPTED at rest
    (core/cloud_crypto.py — the app's first field-encryption
    helper; see its module docstring for the key story).
  - The Drive client is a narrow class; `drive_client_for` is
    the single construction seam, so tests substitute a fake
    end-to-end with NO real Google calls.
  - Every attempt lands a cloud_backup_runs ledger row
    (started/finished/status/size/error). Failures alert their
    owner under the shared alert policy (app/core/
    backup_alerts.py): the streak's first failure notifies,
    a continuing streak re-notifies at most once a day, and
    the first success after an alerted streak sends one
    recovery notice. Other successes stay quiet.
  - Restore: a history row links out to the file in Drive; the
    file is the standard export ZIP, and restoring INTO the
    account stays the existing Import machinery (the UI says
    exactly that).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import backup_alerts
from app.core.config import settings
from app.modules.core import cloud_crypto, export, inbox, models

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
# The PLATFORM backup connection's scope (Disaster Vault, 2026-10-24):
# FULL drive access, because the nightly job must write into the
# pre-existing "Toolbox Vault Backups" folder — drive.file can only
# touch files the app itself created, so it can never see that folder.
PLATFORM_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
PLATFORM_CONNECT_PURPOSE = "platform_drive_connect"
FOLDER_NAME = "Toolbox Vault Backups"
KEEP_BACKUPS = 7
BACKUP_NAME_PREFIX = "ToolboxVault-Backup-"
# The callback URI mirrors core/oauth.py's _callback_url posture:
# built from the configured app base URL, and it must be
# registered on the Google client beside the sign-in one.


def cloud_redirect_uri() -> str:
    return f"{settings.app_base_url}/api/core/cloud-backup/callback"
_STATE_TTL_MINUTES = 10
_HTTP_TIMEOUT_SECONDS = 60.0


class DriveError(RuntimeError):
    """A Drive/token operation failed; str() is user-safe copy."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- connect state -------------------------------------------------------------


def create_connect_state(user_id: uuid.UUID, purpose: str = "cloud_connect") -> str:
    """Short-lived signed state for the connect round-trip: it
    binds the eventual callback to the user who clicked Connect
    (the callback itself arrives cookieless from Google).
    `purpose` defaults to the user feature's "cloud_connect"; the
    platform backup leg passes PLATFORM_CONNECT_PURPOSE so the one
    shared callback can dispatch on it."""
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "nonce": uuid.uuid4().hex,
        "exp": _now() + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def parse_connect_state_with_purpose(token: str) -> tuple[uuid.UUID, str] | None:
    """Decode a connect state into (user_id, purpose). None when
    the token is invalid/expired or carries no usable subject."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        return None
    return user_id, str(payload.get("purpose") or "")


def parse_connect_state(token: str) -> uuid.UUID | None:
    parsed = parse_connect_state_with_purpose(token)
    if parsed is None:
        return None
    user_id, purpose = parsed
    if purpose != "cloud_connect":
        return None
    return user_id


def authorize_url(state: str) -> str:
    """The Google consent URL: the sign-in client, the ONE
    additional scope (drive.file), offline access + a forced
    consent so a refresh token is always issued."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": cloud_redirect_uri(),
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "false",
    }
    from urllib.parse import urlencode

    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def platform_authorize_url(state: str) -> str:
    """The consent URL for the PLATFORM backup connection: same
    client and SAME registered redirect URI as the user feature,
    but the FULL drive scope (see PLATFORM_DRIVE_SCOPE) and a
    forced consent so a refresh token is always issued."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": cloud_redirect_uri(),
        "response_type": "code",
        "scope": PLATFORM_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "false",
    }
    from urllib.parse import urlencode

    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


# -- the Drive client ------------------------------------------------------------


class DriveClient:
    """The narrow Google surface the feature uses. Constructed
    with a working access token; token refresh lives in
    drive_client_for."""

    def __init__(self, access_token: str):
        self._token = access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = httpx.request(
                method, url, headers=self._headers(), timeout=_HTTP_TIMEOUT_SECONDS, **kwargs
            )
        except httpx.HTTPError as exc:
            raise DriveError(f"Couldn't reach Google Drive: {exc}") from exc
        if response.status_code == 204:
            return {}
        if response.status_code >= 400:
            raise DriveError(
                f"Google Drive answered HTTP {response.status_code}."
            )
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def ensure_folder(self, name: str) -> dict:
        from urllib.parse import urlencode

        query = (
            "mimeType='application/vnd.google-apps.folder' "
            f"and name='{name}' and trashed=false"
        )
        body = self._request(
            "GET",
            "https://www.googleapis.com/drive/v3/files?"
            + urlencode({"q": query, "fields": "files(id,name)"}),
        )
        files = body.get("files") or []
        if files:
            return files[0]
        return self._request(
            "POST",
            "https://www.googleapis.com/drive/v3/files?fields=id,name",
            json={"name": name, "mimeType": "application/vnd.google-apps.folder"},
        )

    def upload(
        self, name: str, folder_id: str, data: bytes, *, mime_type: str = "application/zip"
    ) -> dict:
        metadata = {"name": name, "parents": [folder_id]}
        try:
            response = httpx.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                headers=self._headers(),
                params={"uploadType": "multipart", "fields": "id,name,size,webViewLink"},
                files={
                    "metadata": (None, json.dumps(metadata), "application/json"),
                    "media": (name, data, mime_type),
                },
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise DriveError(f"Couldn't reach Google Drive: {exc}") from exc
        if response.status_code >= 400:
            raise DriveError(
                f"Google Drive answered HTTP {response.status_code}."
            )
        body = response.json()
        return body if isinstance(body, dict) else {}

    def list_backups(self, folder_id: str) -> list[dict]:
        from urllib.parse import urlencode

        query = (
            f"'{folder_id}' in parents and name contains "
            f"'{BACKUP_NAME_PREFIX}' and trashed=false"
        )
        body = self._request(
            "GET",
            "https://www.googleapis.com/drive/v3/files?"
            + urlencode(
                {
                    "q": query,
                    "orderBy": "createdTime desc",
                    "fields": "files(id,name,createdTime,size,webViewLink)",
                }
            ),
        )
        return list(body.get("files") or [])

    def delete(self, file_id: str) -> None:
        self._request(
            "DELETE", f"https://www.googleapis.com/drive/v3/files/{file_id}"
        )


def _token_request(data: dict) -> dict:
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data=data,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise DriveError(f"Couldn't reach Google: {exc}") from exc
    if response.status_code != 200:
        raise DriveError(f"Google's token endpoint answered HTTP {response.status_code}.")
    body = response.json()
    return body if isinstance(body, dict) else {}


def exchange_code(code: str) -> dict:
    """Authorization code -> tokens (the connect callback)."""
    return _token_request(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": cloud_redirect_uri(),
            "grant_type": "authorization_code",
        }
    )


def refresh_access_token(refresh_token: str) -> tuple[str, str | None]:
    body = _token_request(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    access = body.get("access_token")
    if not access:
        raise DriveError("Google didn't return an access token.")
    return str(access), (str(body["refresh_token"]) if body.get("refresh_token") else None)


def revoke_token(token: str) -> None:
    """Best-effort revoke at Google (disconnect)."""
    try:
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        pass


def drive_client_for(db: Session, connection: models.CloudDriveConnection) -> DriveClient:
    """THE construction seam (tests substitute this): decrypt the
    stored refresh token, trade it for an access token, persist a
    rotated refresh token when Google hands one back."""
    try:
        refresh_token = cloud_crypto.decrypt_secret(connection.refresh_token_encrypted)
    except ValueError as exc:
        raise DriveError(
            "The stored Drive connection couldn't be opened — reconnect in Settings."
        ) from exc
    access_token, rotated = refresh_access_token(refresh_token)
    if rotated and rotated != refresh_token:
        connection.refresh_token_encrypted = cloud_crypto.encrypt_secret(rotated)
        db.commit()
    return DriveClient(access_token)


# -- service ---------------------------------------------------------------------


def connection_for(db: Session, user_id: uuid.UUID) -> models.CloudDriveConnection | None:
    return db.scalar(
        select(models.CloudDriveConnection).where(
            models.CloudDriveConnection.user_id == user_id
        )
    )


def complete_connection(db: Session, user: models.User, code: str) -> models.CloudDriveConnection:
    """The callback's work: exchange the code, store the refresh
    token encrypted, create/find the backups folder."""
    tokens = exchange_code(code)
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token or not access_token:
        raise DriveError(
            "Google didn't grant offline access — try connecting again."
        )
    client = DriveClient(str(access_token))
    folder = client.ensure_folder(FOLDER_NAME)
    connection = connection_for(db, user.id)
    if connection is None:
        connection = models.CloudDriveConnection(user_id=user.id)
        db.add(connection)
    connection.refresh_token_encrypted = cloud_crypto.encrypt_secret(str(refresh_token))
    connection.drive_folder_id = str(folder.get("id") or "")
    connection.drive_folder_name = str(folder.get("name") or FOLDER_NAME)
    if connection.schedule not in ("off", "daily", "weekly", "monthly"):
        connection.schedule = "weekly"
    connection.connected_at = _now()
    db.commit()
    db.refresh(connection)
    return connection


def run_backup(
    db: Session,
    user: models.User,
    trigger: str,
    client: DriveClient | None = None,
) -> models.CloudBackupRun:
    """One backup attempt, ledgered either way. The ZIP is the
    standard export — the same bytes the manual Export gives —
    so a Drive file restores through the ordinary Import."""
    connection = connection_for(db, user.id)
    run = models.CloudBackupRun(
        user_id=user.id, trigger=trigger, status="running", started_at=_now()
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    if connection is None:
        run.status = "failed"
        run.error = "No Drive connection."
        run.finished_at = _now()
        db.commit()
        return run
    try:
        if client is None:
            client = drive_client_for(db, connection)
        if not connection.drive_folder_id:
            folder = client.ensure_folder(FOLDER_NAME)
            connection.drive_folder_id = str(folder.get("id") or "")
            db.commit()
        payload = export.build_export_zip(db, user)
        stamp = _now().strftime("%Y%m%d-%H%M")
        name = f"{BACKUP_NAME_PREFIX}{stamp}.zip"
        stored = client.upload(name, connection.drive_folder_id, payload)
        run.file_id = str(stored.get("id") or "")
        run.file_name = name
        run.size_bytes = int(stored.get("size") or len(payload))
        # Rotation: keep the newest KEEP_BACKUPS app-created
        # backups; delete the rest (they're ours — drive.file
        # scope can't touch anything else anyway).
        backups = client.list_backups(connection.drive_folder_id)
        for stale in backups[KEEP_BACKUPS:]:
            try:
                client.delete(str(stale.get("id")))
            except DriveError:
                pass  # rotation is best-effort; the backup itself landed
        run.status = "ok"
        run.error = ""
        connection.last_backup_at = _now()
    except DriveError as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
    except Exception as exc:  # the ledger must still land
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:500]
    run.finished_at = _now()
    db.commit()
    db.refresh(run)
    try:
        _notify_backup_outcome(db, user, run)
    except Exception:  # alerting must never mask the backup's own outcome
        import logging

        logging.getLogger(__name__).exception(
            "cloud backup outcome notification failed (run=%s)", run.id
        )
        db.rollback()
    return run


# -- failure alerting (the shared policy, app/core/backup_alerts.py) -----------


def _recent_outcomes(
    db: Session, user_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, datetime, bool]]:
    """Newest-first (run id, started_at, is_failure) triples
    from this user's run ledger — the streak math's raw
    material. The ledger is complete (every attempt lands a
    row), so streaks derived from it are exact."""
    stmt = (
        select(
            models.CloudBackupRun.id,
            models.CloudBackupRun.started_at,
            models.CloudBackupRun.status,
        )
        .where(models.CloudBackupRun.user_id == user_id)
        .order_by(models.CloudBackupRun.started_at.desc())
        .limit(500)
    )
    if exclude_id is not None:
        stmt = stmt.where(models.CloudBackupRun.id != exclude_id)
    return [
        (run_id, backup_alerts.as_utc(started), status == "failed")
        for run_id, started, status in db.execute(stmt)
    ]


def _streak_alert_times(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    streak_run_ids: list[uuid.UUID],
) -> list[datetime]:
    """When the alerts for THIS streak went out. A streak's
    alerts are exactly the notifications whose data.run_id
    names one of the streak's runs — matched by id, never by
    clock, so a previous streak's alerts can't leak into this
    one's math and clock granularity can't either. (The
    notification IS the alert: its email twin follows the
    owner's channel preferences at creation time, like every
    notification's.)"""
    wanted = {str(r) for r in streak_run_ids}
    if not wanted:
        return []
    rows = db.execute(
        select(models.Notification.created_at, models.Notification.data)
        .where(
            models.Notification.user_id == user_id,
            models.Notification.kind == kind,
        )
        .order_by(models.Notification.created_at.desc())
        .limit(500)
    )
    return [
        backup_alerts.as_utc(created)
        for created, data in rows
        if str((data or {}).get("run_id") or "") in wanted
    ]


def _fmt_when(moment: datetime) -> str:
    """'Oct 30, 2026 at 05:58 UTC' — owner-facing streak times."""
    return backup_alerts.as_utc(moment).strftime("%b %d, %Y at %H:%M UTC")


def _notify_backup_outcome(
    db: Session, user: models.User, run: models.CloudBackupRun
) -> None:
    """Apply the alert policy to one finished run.

    Failure: notify on the streak's first failure; while the
    streak continues, re-notify at most once per 24 hours (the
    "still failing" wording carries the streak's start, the
    attempt count, and the latest error). Suppressed failures
    still ledger — Settings -> Cloud backup history shows
    every attempt — they just don't ring the bell again yet.

    Success: when the run closes a streak that was alerted,
    send the ONE recovery notice. Any other success is quiet.
    """
    if run.status == "failed":
        outcomes = _recent_outcomes(db, user.id)
        streak = backup_alerts.leading_streak(
            [(started, failed) for _id, started, failed in outcomes]
        )
        if streak.started_at is None:
            return  # defensive: a failed run always heads a streak
        alerts = _streak_alert_times(
            db,
            user.id,
            inbox.KIND_CLOUD_BACKUP_FAILED,
            [run_id for run_id, _s, _f in outcomes[: streak.count]],
        )
        if not backup_alerts.failure_alert_due(_now(), alerts):
            return
        if alerts:
            title = "Cloud backup still failing"
            body = (
                "Your scheduled Toolbox Vault backups to Google Drive "
                f"are still failing — the trouble started "
                f"{_fmt_when(streak.started_at)} and {streak.count} "
                f"attempt(s) have failed so far. Latest error: {run.error} "
                "The system keeps retrying on schedule. You'll get at "
                "most one of these updates a day while it keeps "
                "failing, and a notice when a backup goes through again."
            )
        else:
            title = "Cloud backup failed"
            body = (
                "Your scheduled Toolbox Vault backup to Google Drive "
                f"didn't complete: {run.error} The system keeps "
                "retrying on schedule — if it keeps failing you'll "
                "get at most one update a day, and a notice when a "
                "backup goes through again."
            )
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_CLOUD_BACKUP_FAILED,
            title=title,
            body=body,
            data={"run_id": str(run.id)},
        )
        return
    if run.status == "ok":
        outcomes = _recent_outcomes(db, user.id, exclude_id=run.id)
        streak = backup_alerts.leading_streak(
            [(started, failed) for _id, started, failed in outcomes]
        )
        if streak.started_at is None:
            return
        alerts = _streak_alert_times(
            db,
            user.id,
            inbox.KIND_CLOUD_BACKUP_FAILED,
            [run_id for run_id, _s, _f in outcomes[: streak.count]],
        )
        if not backup_alerts.recovery_notice_due(streak, len(alerts)):
            return
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_CLOUD_BACKUP_RECOVERED,
            title="Cloud backup working again",
            body=(
                "Your Toolbox Vault backup to Google Drive completed "
                f"again. It had been failing since "
                f"{_fmt_when(streak.started_at)} ({streak.count} failed "
                "attempt(s)). The newest backup is now in your Drive."
            ),
            data={"run_id": str(run.id)},
        )


def disconnect(db: Session, user: models.User) -> None:
    """Revoke at Google (best effort), wipe the stored token,
    drop the connection + its schedule. History rows stay — they
    point at files that are still in the user's Drive."""
    connection = connection_for(db, user.id)
    if connection is None:
        return
    try:
        token = cloud_crypto.decrypt_secret(connection.refresh_token_encrypted)
        revoke_token(token)
    except ValueError:
        pass
    db.delete(connection)
    db.commit()


# -- platform (Disaster Vault) connection ---------------------------------------
#
# The platform's own Drive connection: ONE row, connected by an
# operator AS the MechanicVault account, used only by the nightly
# backup job (app/backup/job.py) to upload encrypted bundles into
# the pre-existing vault folder. Storage choice (2026-10-24):
# server-side DB row, refresh token Fernet-encrypted at rest via
# cloud_crypto — the same machinery as the user connections above.


def platform_connection(db: Session) -> models.PlatformDriveConnection | None:
    """The single platform connection row, if one exists."""
    return db.scalar(select(models.PlatformDriveConnection))


def drive_account_email(access_token: str) -> str:
    """The connected account's email (Drive about endpoint).
    Best-effort: any failure answers "" — the email is a display
    label for the admin panel, never load-bearing."""
    try:
        response = httpx.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return ""
        user = response.json().get("user") or {}
        return str(user.get("emailAddress") or "")
    except Exception:
        return ""


def complete_platform_connection(
    db: Session, user: models.User, code: str
) -> models.PlatformDriveConnection:
    """The callback's platform leg: exchange the code, REQUIRE a
    refresh token (offline access is the whole point), and
    store/replace the single connection row. The folder is the
    configured vault folder — the platform connection never
    creates or renames folders."""
    tokens = exchange_code(code)
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token or not access_token:
        raise DriveError(
            "Google didn't grant offline access — try connecting again."
        )
    email = drive_account_email(str(access_token))
    connection = platform_connection(db)
    if connection is None:
        connection = models.PlatformDriveConnection()
        db.add(connection)
    connection.refresh_token_encrypted = cloud_crypto.encrypt_secret(
        str(refresh_token)
    )
    connection.drive_email = email
    connection.drive_folder_id = settings.backup_drive_folder_id
    connection.connected_by_id = user.id
    connection.connected_at = _now()
    db.commit()
    db.refresh(connection)
    return connection


def disconnect_platform(db: Session) -> bool:
    """Revoke at Google (best effort) and delete the connection
    row. Returns whether a row existed."""
    connection = platform_connection(db)
    if connection is None:
        return False
    try:
        token = cloud_crypto.decrypt_secret(connection.refresh_token_encrypted)
        revoke_token(token)
    except ValueError:
        pass
    db.delete(connection)
    db.commit()
    return True


def due_connections(db: Session, now: datetime | None = None) -> list[models.CloudDriveConnection]:
    """Connections whose schedule is due at `now` (daily = last
    successful backup >= 24h ago or never; weekly = >= 7 days;
    monthly = >= 30 days — owner 2026-10-22: daily, weekly or
    monthly are the user's choices)."""
    moment = now or _now()
    windows = {
        "daily": timedelta(hours=24),
        "weekly": timedelta(days=7),
        "monthly": timedelta(days=30),
    }
    out = []
    for connection in db.scalars(select(models.CloudDriveConnection)):
        window = windows.get(connection.schedule)
        if window is None:
            continue
        last = connection.last_backup_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)  # SQLite reads back naive
        if last is None or (moment - last) >= window:
            out.append(connection)
    return out


def state_for(db: Session, user: models.User) -> dict:
    """The Settings surface's read model: connection posture +
    schedule + the newest history rows (each with a Drive link)."""
    connection = connection_for(db, user.id)
    runs = db.scalars(
        select(models.CloudBackupRun)
        .where(models.CloudBackupRun.user_id == user.id)
        .order_by(models.CloudBackupRun.started_at.desc())
        .limit(20)
    )
    return {
        "connected": connection is not None,
        "folder_name": connection.drive_folder_name if connection else "",
        "schedule": connection.schedule if connection else "off",
        "connected_at": connection.connected_at if connection else None,
        "last_backup_at": connection.last_backup_at if connection else None,
        "history": [
            {
                "id": run.id,
                "trigger": run.trigger,
                "status": run.status,
                "file_name": run.file_name,
                "size_bytes": run.size_bytes,
                "error": run.error,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "drive_url": (
                    f"https://drive.google.com/file/d/{run.file_id}/view"
                    if run.file_id
                    else None
                ),
            }
            for run in runs
        ],
    }
