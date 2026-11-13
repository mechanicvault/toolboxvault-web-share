"""The Disaster Vault jobs: nightly bundle + weekly digest.

One bundle = EVERYTHING needed to rebuild the site from zero
(owner spec 2026-10-18): the full database, every stored object,
the deployed source tree WITH its .env (all secrets — they only
ever exist inside the encrypted archive), a manifest with counts
and SHA-256 hashes, and the RESTORE.md runbook. Packed as ONE
tar.zst archive (anti-bloat law: never thousands of loose files;
regenerable bulk — node_modules, .venv, dist, .git — is excluded
and rebuilt from lockfiles at restore time).

Fail-safe posture, by design:
  - No BACKUP_AGE_PUBLIC_KEY  -> the bundle is built but left
    UNENCRYPTED and LOCAL-ONLY, the run is marked
    "encryption_not_configured", and it is NEVER uploaded. An
    unencrypted copy of every secret must not leave the server.
  - No Drive connection (the operator hasn't clicked "Connect
    backup Drive" in Admin -> Settings, or disconnected it)
    -> the run is "local_only": a complete bundle on the server,
    honestly labeled, not a failure, and NO alert email — the
    known not-connected state is not a failure. A connection
    that exists but fails (revoked/expired) IS a failure and
    alerts like any other.
  - Any stage raising -> the run is "failed", detail records the
    stage + error, and the failure alerts under the shared
    policy (app/core/backup_alerts.py): the streak's first
    failure immediately, a continuing streak at most once a
    day, and one recovery notice when a run completes again
    after an alerted streak.

Every run writes its backup_runs row BEFORE doing work and
completes it at the end: a job that dies mid-run leaves a visible
"running" row in Admin -> Settings instead of a silent gap.

Run by hand:
    python -m app.backup.job            # one bundle, now
    python -m app.backup.job --digest   # the weekly digest, now
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.backup import reports
from app.core import backup_alerts, notifications
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.core import cloud_backup, cloud_crypto, models

logger = logging.getLogger("app.backup")

BUNDLE_NAME_RE = re.compile(r"^toolboxvault-(\d{8})\.tar\.zst(?:\.age)?$")

# Regenerable bulk — rebuilt from lockfiles at restore time, never
# backed up (the Emergent scar: a 1.1 GB backup of mostly
# node_modules that could no longer be uploaded at all).
EXCLUDED_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "dist", "dist-ssr",
    "__pycache__", ".pytest_cache", "pgdata", "minio-data",
    ".idea", ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

DRIVE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024


class StageError(RuntimeError):
    """A failure at a named stage — the stage name keys the
    owner-facing guidance in reports.STAGE_GUIDANCE."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()  # Drive's md5Checksum is an integrity check, not a security control.
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -- run ledger ---------------------------------------------------------------


def _start_run(bundle_name: str) -> models.BackupRun:
    with SessionLocal() as db:
        run = models.BackupRun(status="running", bundle_name=bundle_name, detail={})
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


def _finish_run(run_id, **fields) -> None:
    with SessionLocal() as db:
        run = db.get(models.BackupRun, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        run.finished_at = _now()
        db.commit()


def _send_report(kind: str, to: str, subject: str, body: str) -> bool:
    """Send one report email through the app's provider seam (the
    outbox records it like every other email) and report whether
    the seam accepted it. Never raises — a mail problem must not
    mask the backup outcome it was reporting."""
    try:
        with SessionLocal() as db:
            return notifications.send_email(db, to, subject, body, kind=kind)
    except Exception:
        logger.exception("backup report email failed to send (kind=%s)", kind)
        return False


# -- failure-streak bookkeeping (the shared alert policy) ----------------------


def _finished_outcomes(
    exclude_id=None,
) -> list[tuple[datetime, bool, list[datetime]]]:
    """Finished runs, newest first, as (started_at, is_failure,
    alert_times): the Disaster Vault side of the streak math in
    app.core.backup_alerts. A run's alert times come from its
    own detail record of the report emails it sent (kind
    backup_alert; the entry's "at" when present — entries
    written before 2026-10-30 carry no timestamp, so those
    fall back to the run's own start)."""
    with SessionLocal() as db:
        query = (
            db.query(models.BackupRun)
            .filter(models.BackupRun.finished_at.isnot(None))
            .order_by(models.BackupRun.started_at.desc())
        )
        if exclude_id is not None:
            query = query.filter(models.BackupRun.id != exclude_id)
        query = query.limit(500)
        out: list[tuple[datetime, bool, list[datetime]]] = []
        for row in query.all():
            started = backup_alerts.as_utc(row.started_at)
            times: list[datetime] = []
            for entry in (row.detail or {}).get("emails") or []:
                if entry.get("kind") != notifications.KIND_BACKUP_ALERT:
                    continue
                parsed = None
                if entry.get("at"):
                    try:
                        parsed = datetime.fromisoformat(str(entry["at"]))
                    except ValueError:
                        parsed = None
                times.append(
                    backup_alerts.as_utc(parsed) if parsed else started
                )
            out.append((started, row.status == "failed", times))
        return out


def _streak_and_alerts(
    outcomes: list[tuple[datetime, bool, list[datetime]]],
) -> tuple[backup_alerts.Streak, list[datetime]]:
    """The leading failure streak in `outcomes` + every alert
    time recorded on the runs that make it up."""
    streak = backup_alerts.leading_streak([(s, f) for s, f, _ in outcomes])
    if streak.started_at is None:
        return streak, []
    times: list[datetime] = []
    for _started, _failed, entry_times in outcomes[: streak.count]:
        times.extend(entry_times)
    return streak, times


def _send_recovery_if_streak_closed(run_id, view: reports.RunView, detail: dict) -> None:
    """The policy's third rule, Disaster Vault side: a completed
    run that ends an ALERTED failure streak sends ONE recovery
    notice to the operator (recorded on the run's detail like
    every report email). Quiet otherwise — a healthy run needs
    no mail, and a streak nobody was alerted about needs no
    all-clear. Failure-isolated: a bookkeeping hiccup here must
    never reach back and mark a completed backup failed."""
    try:
        _recovery_if_streak_closed(run_id, view, detail)
    except Exception:
        logger.exception("backup recovery-notice bookkeeping failed")


def _recovery_if_streak_closed(run_id, view: reports.RunView, detail: dict) -> None:
    streak, alert_times = _streak_and_alerts(_finished_outcomes(exclude_id=run_id))
    if streak.started_at is None:
        return
    if not backup_alerts.recovery_notice_due(streak, len(alert_times)):
        return
    subject, body = reports.build_recovery_alert(
        view,
        streak_started_at=streak.started_at,
        failure_count=streak.count,
    )
    sent = _send_report(
        notifications.KIND_BACKUP_RECOVERY,
        settings.backup_report_email,
        subject,
        body,
    )
    detail.setdefault("emails", []).append(
        {
            "kind": "backup_recovery",
            "to": settings.backup_report_email,
            "sent": sent,
            "at": _now().isoformat(),
        }
    )
    _finish_run(run_id, detail=detail)


# -- bundle stages ------------------------------------------------------------


def stage_database_dump(staging: Path) -> dict:
    """pg_dump the production database (custom format) into the
    staging bundle. Returns the manifest's db_dump entry."""
    url = make_url(settings.database_url)
    if not url.drivername.startswith("postgresql"):
        raise StageError(
            "database_dump",
            f"DATABASE_URL is not a PostgreSQL URL (driver: {url.drivername})",
        )
    dump_path = staging / "database.dump"
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PGPASSWORD": url.password or "",
    }
    cmd = [
        "pg_dump",
        "-h", url.host or "postgres",
        "-p", str(url.port or 5432),
        "-U", url.username or "",
        "-d", url.database or "",
        "-Fc", "--no-owner", "--no-privileges",
        "-f", str(dump_path),
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise StageError(
            "database_dump",
            f"pg_dump exited {result.returncode}: {result.stderr.strip()[:500]}",
        )
    return {
        "file": "database.dump",
        "size_bytes": dump_path.stat().st_size,
        "sha256": sha256_file(dump_path),
    }


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_app_user,
        aws_secret_access_key=settings.minio_app_password,
    )


def stage_storage_export(staging: Path) -> list[dict]:
    """Copy EVERY object in the app bucket into staging/objects/,
    preserving keys, hashing as we go. Returns manifest entries."""
    objects_dir = staging / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    client = _s3_client()
    entries: list[dict] = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.minio_bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.startswith("/") or ".." in Path(key).parts:
                    raise StageError(
                        "storage_export", f"unsafe object key refused: {key!r}"
                    )
                target = objects_dir / key
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                response = client.get_object(Bucket=settings.minio_bucket, Key=key)
                with target.open("wb") as handle:
                    for chunk in response["Body"].iter_chunks(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        handle.write(chunk)
                entries.append(
                    {
                        "key": key,
                        "size_bytes": size,
                        "sha256": digest.hexdigest(),
                        # Carried so a restore re-uploads the file
                        # with the type browsers were served before.
                        "content_type": response.get("ContentType")
                        or "application/octet-stream",
                    }
                )
    except StageError:
        raise
    except Exception as exc:
        raise StageError("storage_export", f"{type(exc).__name__}: {exc}") from exc
    return entries


def _copy_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in EXCLUDED_DIR_NAMES or Path(name).suffix in EXCLUDED_SUFFIXES:
            ignored.add(name)
    return ignored


def stage_source_copy(staging: Path) -> dict:
    """Copy the deployed source tree (INCLUDING .env — the secrets
    live only inside the encrypted archive) minus regenerable bulk."""
    source = Path(settings.backup_source_dir)
    if not source.is_dir():
        raise StageError("source_copy", f"source tree not found at {source}")
    target = staging / "source"
    try:
        shutil.copytree(source, target, ignore=_copy_ignore)
    except Exception as exc:
        raise StageError("source_copy", f"{type(exc).__name__}: {exc}") from exc
    file_count = sum(1 for p in target.rglob("*") if p.is_file())
    # The runbook rides at the bundle root where a restorer looks
    # first; the canonical copy lives in the repo (docs/RESTORE.md)
    # and reaches here as part of the source copy.
    runbook = target / "docs" / "RESTORE.md"
    if runbook.is_file():
        shutil.copy2(runbook, staging / "RESTORE.md")
    else:
        (staging / "RESTORE.md").write_text(
            "RESTORE.md was missing from the deployed tree at backup "
            "time. The canonical runbook lives in the repository at "
            "docs/RESTORE.md (also inside source/docs/ when present).\n"
        )
    return {"files": file_count}


def stage_counts() -> dict:
    """Headline row counts for the manifest (users/tools are the
    numbers the restore drill compares against)."""
    counts: dict[str, int] = {}
    with SessionLocal() as db:
        for table in ("users", "tools"):
            counts[table] = int(
                db.scalar(text(f"SELECT count(*) FROM {table}")) or 0
            )
    return counts


def stage_archive(staging: Path, bundle_id: str, out_path: Path) -> None:
    """Pack the staging bundle dir into ONE tar.zst archive."""
    tar = subprocess.Popen(
        ["tar", "-cf", "-", "-C", str(staging.parent), staging.name],
        stdout=subprocess.PIPE,
    )
    zstd = subprocess.Popen(
        ["zstd", "-q", "-f", "-o", str(out_path) + ".tmp"],
        stdin=tar.stdout,
    )
    assert tar.stdout is not None
    tar.stdout.close()
    zstd_rc = zstd.wait()
    tar_rc = tar.wait()
    if tar_rc != 0 or zstd_rc != 0:
        raise StageError(
            "archive", f"tar exited {tar_rc}, zstd exited {zstd_rc}"
        )
    Path(str(out_path) + ".tmp").replace(out_path)
    # Integrity: the archive must decompress cleanly end to end.
    check = subprocess.run(
        ["zstd", "-t", str(out_path)], capture_output=True, text=True, timeout=3600
    )
    if check.returncode != 0:
        raise StageError("archive", f"archive failed zstd -t: {check.stderr[:300]}")


def stage_encrypt(archive_path: Path, recipient: str) -> Path:
    if not recipient.startswith("age1"):
        raise StageError(
            "encrypt",
            "BACKUP_AGE_PUBLIC_KEY does not look like an age recipient "
            f"key (got {recipient[:12]!r}…)",
        )
    out_path = archive_path.with_suffix(archive_path.suffix + ".age")
    result = subprocess.run(
        ["age", "-r", recipient, "-o", str(out_path), str(archive_path)],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0:
        out_path.unlink(missing_ok=True)  # never leave a partial .age behind
        raise StageError(
            "encrypt", f"age exited {result.returncode}: {result.stderr.strip()[:300]}"
        )
    archive_path.unlink()
    return out_path


# -- Drive leg ------------------------------------------------------------------


def platform_drive_configured() -> bool:
    """The Drive leg is configured when a platform connection row
    exists AND the vault folder id is set. (The old service-account
    leg is gone entirely: a service account has no storage quota,
    so it could never own an uploaded file.)"""
    if not settings.backup_drive_folder_id.strip():
        return False
    with SessionLocal() as db:
        return cloud_backup.platform_connection(db) is not None


def platform_drive_token() -> str:
    """Trade the stored platform refresh token for an access
    token. THE token seam for the Drive leg (tests substitute
    this). Any failure raises StageError("upload", ...) so a real
    failure (revoked/expired connection) still lands the run as
    failed + sends the failure alert email."""
    with SessionLocal() as db:
        connection = cloud_backup.platform_connection(db)
        if connection is None:
            raise StageError(
                "upload", "No backup Drive connection is stored."
            )
        try:
            refresh_token = cloud_crypto.decrypt_secret(
                connection.refresh_token_encrypted
            )
        except ValueError as exc:
            raise StageError(
                "upload",
                "The stored backup Drive connection couldn't be opened "
                "— reconnect in Admin -> Settings.",
            ) from exc
        response = httpx.post(
            DRIVE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise StageError(
                "upload",
                f"Drive token refresh failed: HTTP {response.status_code}: "
                f"{response.text[:300]}",
            )
        body = response.json()
        access_token = body.get("access_token")
        if not access_token:
            raise StageError(
                "upload", "Google didn't return an access token."
            )
        rotated = body.get("refresh_token")
        if rotated and rotated != refresh_token:
            connection.refresh_token_encrypted = cloud_crypto.encrypt_secret(
                str(rotated)
            )
            db.commit()
        return str(access_token)


def _drive_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def drive_upload(token: str, folder_id: str, file_path: Path) -> dict:
    """Resumable chunked upload of ONE file into the vault folder.
    Returns the Drive file resource (id, size, md5Checksum)."""
    size = file_path.stat().st_size
    metadata = {"name": file_path.name, "parents": [folder_id]}
    init = httpx.post(
        DRIVE_UPLOAD_URL,
        params={"uploadType": "resumable"},
        headers={
            **_drive_headers(token),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
        },
        json=metadata,
        timeout=60,
    )
    if init.status_code not in (200, 201):
        raise StageError(
            "upload",
            f"Drive upload init failed: HTTP {init.status_code}: {init.text[:300]}",
        )
    session_uri = init.headers["Location"]
    offset = 0
    final: httpx.Response | None = None
    with file_path.open("rb") as handle:
        while offset < size:
            chunk = handle.read(UPLOAD_CHUNK_BYTES)
            end = offset + len(chunk) - 1
            response = httpx.put(
                session_uri,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                },
                content=chunk,
                timeout=600,
            )
            if response.status_code in (200, 201):
                final = response
                offset = size
            elif response.status_code == 308:
                offset = end + 1
            else:
                raise StageError(
                    "upload",
                    f"Drive upload chunk at {offset} failed: HTTP "
                    f"{response.status_code}: {response.text[:300]}",
                )
    if size == 0:
        final = httpx.put(
            session_uri, headers={"Content-Length": "0"}, content=b"", timeout=60
        )
        if final.status_code not in (200, 201):
            raise StageError("upload", "Drive upload of empty file failed")
    assert final is not None
    file_id = final.json()["id"]
    got = httpx.get(
        f"{DRIVE_FILES_URL}/{file_id}",
        params={"fields": "id,name,size,md5Checksum"},
        headers=_drive_headers(token),
        timeout=60,
    )
    if got.status_code != 200:
        raise StageError("verify", f"Drive file readback failed: HTTP {got.status_code}")
    return got.json()


def drive_list_bundles(token: str, folder_id: str) -> list[dict]:
    """Bundle files currently in the vault folder, newest first."""
    query = (
        f"'{folder_id}' in parents and trashed = false "
        "and name contains 'toolboxvault-'"
    )
    response = httpx.get(
        DRIVE_FILES_URL,
        params={
            "q": query,
            "fields": "files(id,name,size,createdTime)",
            "orderBy": "name desc",
            "pageSize": "100",
        },
        headers=_drive_headers(token),
        timeout=60,
    )
    if response.status_code != 200:
        raise StageError(
            "upload", f"Drive listing failed: HTTP {response.status_code}"
        )
    bundles = [f for f in response.json().get("files", []) if BUNDLE_NAME_RE.match(f["name"])]
    return sorted(bundles, key=lambda f: f["name"], reverse=True)


def drive_delete(token: str, file_id: str) -> None:
    httpx.delete(
        f"{DRIVE_FILES_URL}/{file_id}", headers=_drive_headers(token), timeout=60
    )


# -- rotation -------------------------------------------------------------------


def bundle_date(name: str) -> str:
    match = BUNDLE_NAME_RE.match(name)
    return match.group(1) if match else ""


def local_bundles(backup_dir: Path) -> list[Path]:
    """Retained local bundle files, newest first."""
    files = [
        p
        for p in backup_dir.glob("toolboxvault-*.tar.zst*")
        if p.is_file() and BUNDLE_NAME_RE.match(p.name)
    ]
    return sorted(files, key=lambda p: p.name, reverse=True)


def prune_local(backup_dir: Path, keep: int) -> list[str]:
    """Delete local bundles beyond the newest `keep`; returns the
    names removed."""
    removed = []
    for path in local_bundles(backup_dir)[keep:]:
        path.unlink()
        removed.append(path.name)
    return removed


def prune_drive(token: str, folder_id: str, keep: int) -> list[str]:
    removed = []
    for entry in drive_list_bundles(token, folder_id)[keep:]:
        drive_delete(token, entry["id"])
        removed.append(entry["name"])
    return removed


# -- the jobs -------------------------------------------------------------------


def run_bundle(label: str | None = None) -> models.BackupRun:
    """Build one nightly bundle end to end. Returns the completed
    run row; failures are recorded on the row (and alerted), not
    raised — the scheduler must survive a bad night."""
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = f"toolboxvault-{_now().strftime('%Y%m%d')}"
    detail: dict = {"label": label} if label else {}
    run = _start_run(f"{bundle_id}.tar.zst")
    encrypted = False
    uploaded = False
    verified = False
    final_path: Path | None = None
    try:
        staging_root = backup_dir / ".staging"
        if staging_root.exists():
            shutil.rmtree(staging_root)
        staging = staging_root / bundle_id
        staging.mkdir(parents=True)

        db_entry = stage_database_dump(staging)
        objects = stage_storage_export(staging)
        source_info = stage_source_copy(staging)
        counts = stage_counts()
        counts["objects"] = len(objects)
        manifest = {
            "bundle_id": bundle_id,
            "created_at": _now().isoformat(),
            "git_commit": settings.app_git_commit or "unknown",
            "counts": counts,
            "db_dump": db_entry,
            "objects": objects,
            "source_files": source_info["files"],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))
        detail["manifest"] = {
            "counts": counts,
            "db_dump_sha256": db_entry["sha256"],
            "source_files": source_info["files"],
        }

        archive_path = backup_dir / f"{bundle_id}.tar.zst"
        stage_archive(staging, bundle_id, archive_path)
        shutil.rmtree(staging_root, ignore_errors=True)
        detail["archive_sha256"] = sha256_file(archive_path)
        final_path = archive_path

        recipient = (settings.backup_age_public_key or "").strip()
        if recipient:
            final_path = stage_encrypt(archive_path, recipient)
            encrypted = True
        detail["bundle_file"] = {
            "name": final_path.name,
            "size_bytes": final_path.stat().st_size,
            "sha256": sha256_file(final_path),
            "md5": md5_file(final_path),
        }
        # Local verification: every staged hash was computed from
        # the bytes themselves and the archive passed zstd -t; the
        # hashes in the manifest are the drill's comparison set.
        verified = True
        detail["verification"] = "local_hashes+zstd_test"

        drive_configured = platform_drive_configured()
        if not recipient:
            status = "encryption_not_configured"
        elif not drive_configured:
            # Known not-connected state: local-only is honest
            # labeling, NOT a failure — no exception, no alert.
            status = "local_only"
            detail["drive"] = "not_connected"
        else:
            status = "ok"
            token = platform_drive_token()
            remote = drive_upload(
                token, settings.backup_drive_folder_id.strip(), final_path
            )
            uploaded = True
            if int(remote.get("size", -1)) != detail["bundle_file"]["size_bytes"] or (
                remote.get("md5Checksum") or ""
            ).lower() != detail["bundle_file"]["md5"]:
                raise StageError(
                    "verify",
                    "Drive readback mismatch: remote size/md5 "
                    f"({remote.get('size')}, {remote.get('md5Checksum')}) != local "
                    f"({detail['bundle_file']['size_bytes']}, "
                    f"{detail['bundle_file']['md5']})",
                )
            detail["verification"] = "drive_size+md5"
            detail["drive_file_id"] = remote["id"]
            removed_remote = prune_drive(
                token, settings.backup_drive_folder_id.strip(), settings.backup_keep
            )
            if removed_remote:
                detail["drive_pruned"] = removed_remote

        removed_local = prune_local(backup_dir, settings.backup_keep)
        if removed_local:
            detail["local_pruned"] = removed_local

        _finish_run(
            run.id,
            bundle_name=final_path.name,
            size_bytes=detail["bundle_file"]["size_bytes"],
            encrypted=encrypted,
            uploaded=uploaded,
            verified=verified,
            status=status,
            detail=detail,
        )
        logger.info("backup run %s: %s (%s)", run.id, status, final_path.name)
        _send_recovery_if_streak_closed(
            run.id,
            reports.RunView(
                started_at=run.started_at or _now(),
                bundle_name=final_path.name,
                size_bytes=detail["bundle_file"]["size_bytes"],
                status=status,
                detail=detail,
            ),
            detail,
        )
    except StageError as exc:
        detail["stage"] = exc.stage
        detail["error"] = str(exc)
        _finish_run(
            run.id,
            bundle_name=final_path.name if final_path else None,
            size_bytes=(
                final_path.stat().st_size if final_path and final_path.exists() else None
            ),
            encrypted=encrypted,
            uploaded=uploaded,
            verified=False,
            status="failed",
            detail=detail,
        )
        logger.error("backup run failed at stage %s: %s", exc.stage, exc)
        failed_view = reports.RunView(
            started_at=run.started_at or _now(),
            bundle_name=final_path.name if final_path else None,
            size_bytes=(
                final_path.stat().st_size
                if final_path and final_path.exists()
                else None
            ),
            status="failed",
            detail=detail,
        )
        streak, alert_times = _streak_and_alerts(_finished_outcomes())
        subject, body = reports.build_failure_alert(
            failed_view,
            streak_started_at=streak.started_at,
            failure_count=max(streak.count, 1),
        )
        if backup_alerts.failure_alert_due(_now(), alert_times):
            sent = _send_report(
                notifications.KIND_BACKUP_ALERT,
                settings.backup_report_email,
                subject,
                body,
            )
            detail["emails"] = [
                {
                    "kind": "backup_alert",
                    "to": settings.backup_report_email,
                    "sent": sent,
                    "at": _now().isoformat(),
                }
            ]
        else:
            # The policy's suppression window: this streak was
            # alerted less than 24h ago. The failure itself is
            # fully recorded above (and the weekly digest lines
            # it up regardless); it just doesn't ring again yet.
            detail["alert_suppressed"] = (
                "continuing failure streak — last alert under 24h ago"
            )
        _finish_run(run.id, detail=detail)
    except Exception as exc:  # last-resort guard: never die silently
        detail["stage"] = "record"
        detail["error"] = f"{type(exc).__name__}: {exc}"
        try:
            _finish_run(run.id, status="failed", detail=detail)
        except Exception:
            logger.exception("could not even record the failed backup run")
    with SessionLocal() as db:
        return db.get(models.BackupRun, run.id)


def _run_view(run: models.BackupRun) -> reports.RunView:
    return reports.RunView(
        started_at=run.started_at,
        bundle_name=run.bundle_name,
        size_bytes=run.size_bytes,
        status=run.status,
        detail=run.detail or {},
    )


def _drill_status(backup_dir: Path) -> str:
    """The digest's drill line: written to drill-status.json in the
    backup dir by whoever ran the last restore drill (the build
    drill did; future drills should refresh it)."""
    marker = backup_dir / "drill-status.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text())
            return str(data.get("summary") or "drill recorded (no summary)")
        except Exception:
            return "drill status file unreadable"
    return (
        "no restore drill recorded yet — until one is, these "
        "backups are unproven"
    )


def run_digest() -> bool:
    """Build + send the weekly digest. Returns whether the seam
    accepted it; records the send on the newest run's detail."""
    backup_dir = Path(settings.backup_dir)
    since = _now() - timedelta(days=7)
    with SessionLocal() as db:
        rows = (
            db.query(models.BackupRun)
            .filter(models.BackupRun.started_at >= since)
            .order_by(models.BackupRun.started_at.asc())
            .all()
        )
        views = [_run_view(r) for r in rows]
        newest_id = rows[-1].id if rows else None
    total_local = sum(p.stat().st_size for p in local_bundles(backup_dir))
    total_vault = total_local
    if platform_drive_configured():
        try:
            token = platform_drive_token()
            entries = drive_list_bundles(
                token, settings.backup_drive_folder_id.strip()
            )
            total_vault = sum(int(e.get("size", 0)) for e in entries)
        except Exception:
            logger.exception("digest: Drive total unavailable; using local total")
    subject, body = reports.build_digest(
        views,
        total_vault_bytes=total_vault,
        drill_status=_drill_status(backup_dir),
        any_failed=any(v.status == "failed" for v in views),
    )
    sent = _send_report(
        notifications.KIND_BACKUP_DIGEST,
        settings.backup_report_email,
        subject,
        body,
    )
    if newest_id is not None:
        with SessionLocal() as db:
            run = db.get(models.BackupRun, newest_id)
            if run is not None:
                detail = dict(run.detail or {})
                detail.setdefault("emails", []).append(
                    {
                        "kind": "backup_digest",
                        "to": settings.backup_report_email,
                        "sent": sent,
                        "at": _now().isoformat(),
                    }
                )
                run.detail = detail
                db.commit()
    logger.info("weekly digest sent=%s to %s", sent, settings.backup_report_email)
    return sent


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Disaster Vault jobs")
    parser.add_argument("--digest", action="store_true", help="send the weekly digest")
    parser.add_argument("--label", default=None, help="label recorded on the run")
    args = parser.parse_args(argv)
    if args.digest:
        run_digest()
    else:
        run_bundle(label=args.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
