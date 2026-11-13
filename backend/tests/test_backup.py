"""Disaster Vault (owner spec 2026-10-18): unit coverage for the
backup job's pure pieces —

- manifest assembly (counts, dump hash, object entries with
  SHA-256 + content type) and the bundle stages that can run
  without Docker services (source copy exclusions, tar.zst pack),
- the source-copy anti-bloat law (node_modules/.venv/dist/.git
  never enter a bundle; .env and lockfiles always do),
- rotation: newest 7 kept, by bundle-date in the name,
- status posture: no age key -> encryption_not_configured,
  key but no Drive -> local_only (via job.run_bundle with the
  service stages stubbed),
- report content: the digest lists every run with sizes and
  calls out failures; the failure alert names the stage, the
  likely cause, and the fix,
- the scheduler's firing rules,
- Admin -> Settings carries the last backup runs.
"""

import hashlib
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.backup import job, reports, scheduler
from app.modules.core import models

requires_age = pytest.mark.skipif(
    subprocess.run(["which", "age"], capture_output=True).returncode != 0,
    reason="age binary not installed (it ships in the backup image)",
)
requires_zstd = pytest.mark.skipif(
    subprocess.run(["which", "zstd"], capture_output=True).returncode != 0,
    reason="zstd binary not installed (it ships in the backup image)",
)


def _dt(day: int, hour: int = 3, minute: int = 30) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


# -- source copy: the anti-bloat law -------------------------------------------


def _plant_source(root: Path) -> None:
    (root / "frontend" / "node_modules" / "leftpad").mkdir(parents=True)
    (root / "frontend" / "node_modules" / "leftpad" / "index.js").write_text("junk")
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "frontend" / "dist" / "app.js").write_text("built")
    (root / "frontend" / "package-lock.json").write_text("{}")
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "junk.py").write_text("junk")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "main.py").write_text("# app")
    (root / "backend" / "__pycache__").mkdir(parents=True)
    (root / "backend" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (root / "docs").mkdir()
    (root / "docs" / "RESTORE.md").write_text("# runbook")
    (root / "docker-compose.yml").write_text("services: {}")
    (root / ".env").write_text("JWT_SECRET=test-only\n")


def test_source_copy_excludes_bulk_keeps_secrets_and_lockfiles(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _plant_source(source)
    staging = tmp_path / "bundle"
    staging.mkdir()
    monkeypatch.setattr(job.settings, "backup_source_dir", str(source))

    info = job.stage_source_copy(staging)

    copied = staging / "source"
    assert (copied / ".env").is_file()  # secrets ride inside the encrypted bundle
    assert (copied / "docker-compose.yml").is_file()
    assert (copied / "frontend" / "package-lock.json").is_file()
    assert (copied / "backend" / "app" / "main.py").is_file()
    assert not (copied / "frontend" / "node_modules").exists()
    assert not (copied / "frontend" / "dist").exists()
    assert not (copied / ".venv").exists()
    assert not (copied / ".git").exists()
    assert not list(copied.rglob("*.pyc"))
    # The runbook is promoted to the bundle root.
    assert (staging / "RESTORE.md").read_text() == "# runbook"
    assert info["files"] >= 5


@requires_zstd
def test_archive_is_one_tar_zst_with_manifest(tmp_path):
    staging_root = tmp_path / "staging"
    bundle = staging_root / "toolboxvault-20261019"
    (bundle / "objects" / "u1" / "tools").mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"dump-bytes")
    (bundle / "objects" / "u1" / "tools" / "photo.jpg").write_bytes(b"\xff\xd8photo")
    (bundle / "manifest.json").write_text("{}")
    out = tmp_path / "toolboxvault-20261019.tar.zst"

    job.stage_archive(bundle, bundle.name, out)

    assert out.is_file()
    import subprocess

    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(out)], capture_output=True, text=True
    )
    assert listing.returncode == 0
    names = listing.stdout
    assert "toolboxvault-20261019/manifest.json" in names
    assert "toolboxvault-20261019/database.dump" in names
    assert "toolboxvault-20261019/objects/u1/tools/photo.jpg" in names


def test_sha256_and_md5_helpers(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"toolbox vault")
    assert job.sha256_file(blob) == hashlib.sha256(b"toolbox vault").hexdigest()
    assert job.md5_file(blob) == hashlib.md5(b"toolbox vault").hexdigest()


# -- rotation --------------------------------------------------------------------


def _touch_bundle(directory: Path, day: int, *, encrypted: bool = False) -> Path:
    name = f"toolboxvault-202610{day:02d}.tar.zst" + (".age" if encrypted else "")
    path = directory / name
    path.write_bytes(b"x")
    return path


def test_prune_local_keeps_newest_seven(tmp_path):
    for day in range(10, 20):  # 10 bundles, Oct 10..19
        _touch_bundle(tmp_path, day, encrypted=day % 2 == 0)
    (tmp_path / "notes.txt").write_text("not a bundle")

    removed = job.prune_local(tmp_path, keep=7)

    remaining = sorted(p.name for p in tmp_path.glob("toolboxvault-*"))
    assert len(remaining) == 7
    assert remaining[0].startswith("toolboxvault-20261013")
    assert remaining[-1].startswith("toolboxvault-20261019")
    assert len(removed) == 3
    assert (tmp_path / "notes.txt").is_file()  # unrelated files untouched


def test_local_bundles_newest_first(tmp_path):
    _touch_bundle(tmp_path, 11)
    _touch_bundle(tmp_path, 19)
    _touch_bundle(tmp_path, 15)
    names = [p.name for p in job.local_bundles(tmp_path)]
    assert names[0].startswith("toolboxvault-20261019")
    assert names[-1].startswith("toolboxvault-20261011")


# -- status posture (job.run_bundle with service stages stubbed) -----------------


@pytest.fixture()
def bundle_env(db, tmp_path, monkeypatch):
    """Point the job at a tmp vault and stub the stages that need
    live services (DB dump, storage, counts) with file fixtures.
    The job's ledger session is rebound to the test database."""
    monkeypatch.setattr(
        job,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), class_=Session, expire_on_commit=False),
    )
    source = tmp_path / "source"
    source.mkdir()
    _plant_source(source)
    vault = tmp_path / "vault"
    vault.mkdir()

    def fake_dump(staging: Path) -> dict:
        dump = staging / "database.dump"
        dump.write_bytes(b"fake-dump")
        return {
            "file": "database.dump",
            "size_bytes": dump.stat().st_size,
            "sha256": hashlib.sha256(b"fake-dump").hexdigest(),
        }

    def fake_export(staging: Path) -> list[dict]:
        objects = staging / "objects" / "u1"
        objects.mkdir(parents=True, exist_ok=True)
        (objects / "a.jpg").write_bytes(b"jpg")
        return [
            {
                "key": "u1/a.jpg",
                "size_bytes": 3,
                "sha256": hashlib.sha256(b"jpg").hexdigest(),
                "content_type": "image/jpeg",
            }
        ]

    monkeypatch.setattr(job, "stage_database_dump", fake_dump)
    monkeypatch.setattr(job, "stage_storage_export", fake_export)
    monkeypatch.setattr(job, "stage_counts", lambda: {"users": 3, "tools": 9})
    monkeypatch.setattr(job.settings, "backup_source_dir", str(source))
    monkeypatch.setattr(job.settings, "backup_dir", str(vault))
    monkeypatch.setattr(job.settings, "app_git_commit", "abc123")
    return vault


@requires_zstd
def test_run_without_age_key_is_unencrypted_local_and_never_uploaded(
    db, bundle_env, monkeypatch
):
    monkeypatch.setattr(job.settings, "backup_age_public_key", "")
    # Even WITH a platform Drive connection present, no key = no
    # upload, ever.
    monkeypatch.setattr(job.settings, "backup_drive_folder_id", "folder123")
    db.add(
        models.PlatformDriveConnection(
            refresh_token_encrypted="stored-encrypted-token",
            drive_email="backup@example.com",
            drive_folder_id="folder123",
        )
    )
    db.commit()
    uploads = []
    monkeypatch.setattr(job, "drive_upload", lambda *a, **k: uploads.append(a))
    tokens = []
    monkeypatch.setattr(job, "platform_drive_token", lambda: tokens.append(1))

    run = job.run_bundle(label="test")

    assert run.status == "encryption_not_configured"
    assert run.encrypted is False
    assert run.uploaded is False
    assert uploads == []
    assert tokens == []
    assert run.bundle_name.endswith(".tar.zst")
    assert not run.bundle_name.endswith(".age")
    bundle_file = bundle_env / run.bundle_name
    assert bundle_file.is_file()
    # The manifest inside the archive carries counts + hashes.
    import subprocess

    names = subprocess.run(
        ["tar", "--zstd", "-tf", str(bundle_file)], capture_output=True, text=True
    ).stdout
    assert "manifest.json" in names
    assert run.detail["manifest"]["counts"] == {"users": 3, "tools": 9, "objects": 1}
    assert run.detail["label"] == "test"


@requires_age
@requires_zstd
def test_run_with_key_but_no_drive_is_local_only(db, bundle_env, monkeypatch, tmp_path):
    keypair = tmp_path / "key.txt"
    import subprocess

    subprocess.run(["age-keygen", "-o", str(keypair)], check=True, capture_output=True)
    public = [
        line.split("public key: ")[1].strip()
        for line in keypair.read_text().splitlines()
        if "public key:" in line
    ][0]
    monkeypatch.setattr(job.settings, "backup_age_public_key", public)
    # No platform Drive connection row = not connected.
    monkeypatch.setattr(job.settings, "backup_drive_folder_id", "folder123")
    sent = []
    monkeypatch.setattr(
        job, "_send_report", lambda kind, to, subject, body: sent.append(kind) or True
    )

    run = job.run_bundle()

    assert run.status == "local_only"
    assert run.detail["drive"] == "not_connected"
    assert sent == []  # the known not-connected state never alerts
    assert run.encrypted is True
    assert run.uploaded is False
    assert run.bundle_name.endswith(".tar.zst.age")
    assert (bundle_env / run.bundle_name).is_file()
    # The plaintext archive must not linger beside the encrypted one.
    assert not list(bundle_env.glob("*.tar.zst")) or all(
        p.name.endswith(".age") for p in bundle_env.glob("*.tar.zst*")
    )


@requires_zstd
def test_failed_stage_records_stage_and_alerts(db, bundle_env, monkeypatch):
    def boom(staging: Path) -> dict:
        raise job.StageError("database_dump", "pg_dump exited 1: connection refused")

    monkeypatch.setattr(job, "stage_database_dump", boom)
    sent = []
    monkeypatch.setattr(
        job, "_send_report", lambda kind, to, subject, body: sent.append((kind, subject, body)) or True
    )

    run = job.run_bundle()

    assert run.status == "failed"
    assert run.detail["stage"] == "database_dump"
    assert "connection refused" in run.detail["error"]
    assert sent and sent[0][0] == "backup_alert"
    assert "FAILED" in sent[0][1]
    assert "How to fix it" in sent[0][2]
    assert run.detail["emails"][0]["kind"] == "backup_alert"


@requires_zstd
def test_failure_streak_alerts_daily_and_recovers(db, bundle_env, monkeypatch):
    """The alert policy, Disaster Vault side: the streak's
    first failure alerts; a second failure inside 24h is fully
    recorded but does NOT re-alert; a failure after the window
    re-alerts in "still failing" wording; and the first
    completed run afterwards sends exactly one recovery
    notice, never two."""
    sent = []
    monkeypatch.setattr(
        job, "_send_report", lambda kind, to, subject, body: sent.append((kind, subject, body)) or True
    )

    def boom(staging: Path) -> dict:
        raise job.StageError("database_dump", "pg_dump exited 1: connection refused")

    monkeypatch.setattr(job, "stage_database_dump", boom)

    run1 = job.run_bundle()
    assert run1.status == "failed"
    assert [k for k, _, _ in sent] == ["backup_alert"]
    assert run1.detail["emails"][0]["kind"] == "backup_alert"
    assert "at" in run1.detail["emails"][0]

    run2 = job.run_bundle()
    assert run2.status == "failed"
    assert len(sent) == 1  # suppressed: same streak, alert <24h old
    assert run2.detail["alert_suppressed"]

    # Age the streak's only alert past the 24h window.
    row = db.get(models.BackupRun, run1.id)
    aged = dict(row.detail)
    aged_emails = [dict(e) for e in aged["emails"]]
    aged_emails[0]["at"] = (
        datetime.now(timezone.utc) - timedelta(hours=25)
    ).isoformat()
    aged["emails"] = aged_emails
    row.detail = aged
    db.commit()

    run3 = job.run_bundle()
    assert run3.status == "failed"
    assert [k for k, _, _ in sent] == ["backup_alert", "backup_alert"]
    assert "STILL FAILING" in sent[1][1]
    assert "#3 in a row" in sent[1][2]

    # The stage heals; the next completed run closes the loop once.
    def fake_dump(staging: Path) -> dict:
        dump = staging / "database.dump"
        dump.write_bytes(b"fake-dump")
        return {
            "file": "database.dump",
            "size_bytes": dump.stat().st_size,
            "sha256": hashlib.sha256(b"fake-dump").hexdigest(),
        }

    monkeypatch.setattr(job, "stage_database_dump", fake_dump)
    run4 = job.run_bundle()
    assert run4.status != "failed"
    assert sent[-1][0] == "backup_recovery"
    assert "recovered" in sent[-1][1]
    assert run4.detail["emails"][-1]["kind"] == "backup_recovery"

    run5 = job.run_bundle()
    assert run5.status != "failed"
    assert len(sent) == 3  # no second all-clear


# -- reports ---------------------------------------------------------------------


def _view(day: int, status: str, size: int = 2_400_000, stage: str | None = None):
    detail = {"stage": stage, "error": "boom"} if stage else {}
    return reports.RunView(
        started_at=_dt(day),
        bundle_name=f"toolboxvault-202610{day:02d}.tar.zst.age",
        size_bytes=size,
        status=status,
        detail=detail,
    )


def test_digest_lists_runs_sizes_and_all_clear():
    runs = [_view(13, "ok"), _view(14, "ok"), _view(15, "local_only")]
    subject, body = reports.build_digest(
        runs,
        total_vault_bytes=16_800_000,
        drill_status="passed 2026-10-19",
        any_failed=False,
    )
    assert "all completed" in subject
    assert body.count("toolboxvault-202610") == 3
    assert "2.4 MB" in body
    assert "16.8 MB" in body  # total vault size is reported (growth visibility)
    assert "passed 2026-10-19" in body
    assert "off-site upload not set up yet" in body  # local_only said out loud


def test_digest_flags_failures():
    runs = [_view(13, "ok"), _view(14, "failed", stage="upload")]
    subject, body = reports.build_digest(
        runs, total_vault_bytes=5_000_000, drill_status="n/a", any_failed=True
    )
    assert "ATTENTION NEEDED" in subject
    assert "FAILED" in body


def test_failure_alert_names_stage_cause_and_fix():
    run = _view(14, "failed", stage="upload")
    subject, body = reports.build_failure_alert(run)
    assert "FAILED" in subject
    assert "Google Drive" in body
    assert "Likely cause:" in body
    assert "How to fix it:" in body
    assert "boom" in body  # the technical detail rides along


def test_failure_alert_unknown_stage_still_complete():
    run = reports.RunView(
        started_at=_dt(14),
        bundle_name=None,
        size_bytes=None,
        status="failed",
        detail={"stage": "mystery", "error": "??"},
    )
    _subject, body = reports.build_failure_alert(run)
    assert "How to fix it:" in body


def test_failure_alert_reminder_names_the_streak():
    run = _view(14, "failed", stage="upload")
    subject, body = reports.build_failure_alert(
        run, streak_started_at=_dt(12), failure_count=3
    )
    assert "STILL FAILING" in subject
    assert "#3 in a row" in body
    assert "October 12" in body  # the streak's start, spelled out


def test_recovery_alert_closes_the_loop():
    run = _view(15, "ok")
    subject, body = reports.build_recovery_alert(
        run, streak_started_at=_dt(12), failure_count=3
    )
    assert "recovered" in subject
    assert "3 failed run(s)" in body
    assert "October 12" in body
    assert "encrypted, uploaded to Drive, and verified" in body  # status said plainly


# -- scheduler firing rules --------------------------------------------------------


def test_scheduler_bundle_due_once_per_day(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "backup_time_utc", "03:30")
    before = datetime(2026, 10, 19, 3, 29, tzinfo=timezone.utc)
    after = datetime(2026, 10, 19, 3, 31, tzinfo=timezone.utc)
    assert scheduler.due(before, {})[0] is False
    assert scheduler.due(after, {})[0] is True
    assert scheduler.due(after, {"last_bundle_date": "2026-10-19"})[0] is False


def test_scheduler_digest_due_on_configured_weekday(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "backup_digest_weekday", 0)  # Monday
    monkeypatch.setattr(scheduler.settings, "backup_digest_time_utc", "14:00")
    # 2026-10-19 is a Monday.
    monday = datetime(2026, 10, 19, 14, 5, tzinfo=timezone.utc)
    tuesday = datetime(2026, 10, 20, 14, 5, tzinfo=timezone.utc)
    assert scheduler.due(monday, {})[1] is True
    assert scheduler.due(tuesday, {})[1] is False


# -- admin settings shows the runs -------------------------------------------------


def test_admin_settings_includes_recent_backup_runs(db, client):
    from tests.conftest import auth_headers

    operator = models.User(
        id=uuid.uuid4(),
        account_number="TV-M-OP0001",
        email="op@example.com",
        name="Operator",
        password_hash="not-a-real-hash",
        is_operator=True,
    )
    db.add(operator)
    for i, status in enumerate(["ok", "local_only", "failed"]):
        db.add(
            models.BackupRun(
                started_at=_dt(17) + timedelta(days=i),
                finished_at=_dt(17) + timedelta(days=i, minutes=2),
                bundle_name=f"toolboxvault-202610{17 + i}.tar.zst.age",
                size_bytes=1_000_000 * (i + 1),
                encrypted=True,
                uploaded=status == "ok",
                verified=status == "ok",
                status=status,
                detail={},
            )
        )
    db.commit()

    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()

    assert [r["status"] for r in view["backups"]] == ["failed", "local_only", "ok"]
    newest = view["backups"][0]
    assert newest["bundle_name"] == "toolboxvault-20261019.tar.zst.age"
    assert newest["size_bytes"] == 3_000_000


def test_admin_settings_backups_empty_until_first_run(db, client):
    from tests.conftest import auth_headers

    operator = models.User(
        id=uuid.uuid4(),
        account_number="TV-M-OP0002",
        email="op2@example.com",
        name="Operator Two",
        password_hash="not-a-real-hash",
        is_operator=True,
    )
    db.add(operator)
    db.commit()
    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()
    assert view["backups"] == []

