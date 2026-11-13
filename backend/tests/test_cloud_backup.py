"""Wave 4 — Cloud (Google Drive) user auto-backups.

Everything Google is MOCKED: a FakeDriveClient stands at the
drive_client_for / DriveClient seams and the token exchange is
stubbed. NO real Google call happens in this file — a real
connect needs the account owner's own Google consent and is
deliberately NOT exercised here or in the live smoke.

Pins:
  - tokens are stored ENCRYPTED at rest (the raw column never
    holds the token; the crypto round-trips, and a wrong key
    can't open it);
  - connect is state/nonce-protected and 503s while the site's
    Google client is unconfigured;
  - the backup is the standard export ZIP under the
    ToolboxVault-Backup-<stamp>.zip name, in the
    "Toolbox Vault Backups" folder;
  - rotation keeps the newest 7;
  - failures land a history row AND an inbox notification;
  - the schedule/due logic: off never, daily >= 24h, weekly
    >= 7d, monthly >= 30d, never-backed-up is due;
  - disconnect revokes (best effort), wipes the stored token,
    and leaves history + the Drive files alone;
  - account deletion cascades the cloud rows away.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.modules.core import cloud_backup, cloud_crypto, models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


class FakeDriveClient:
    """In-memory Drive: folders + files, newest-first listing."""

    instances: list["FakeDriveClient"] = []

    def __init__(self, access_token: str = ""):
        self.access_token = access_token
        self.files: list[dict] = []
        self.deleted: list[str] = []
        self.counter = 0
        FakeDriveClient.instances.append(self)

    def ensure_folder(self, name):
        return {"id": "folder-1", "name": name}

    def upload(self, name, folder_id, data):
        self.counter += 1
        entry = {"id": f"file-{self.counter}", "name": name, "size": str(len(data))}
        self.files.append(entry)
        return entry

    def list_backups(self, folder_id):
        return list(reversed(self.files))

    def delete(self, file_id):
        self.deleted.append(file_id)
        self.files = [f for f in self.files if f["id"] != file_id]


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeDriveClient.instances = []
    yield


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Cloud User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000441", "cloud@example.com")


@pytest.fixture()
def google_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id-test")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret-test")


def _connect(db, owner, monkeypatch):
    """Drive the connect machine to completion with stubs."""
    monkeypatch.setattr(
        cloud_backup,
        "exchange_code",
        lambda code: {
            "refresh_token": "refresh-token-plaintext",
            "access_token": "access-token-1",
        },
    )
    fake = FakeDriveClient()
    monkeypatch.setattr(cloud_backup, "DriveClient", lambda token: fake)
    connection = cloud_backup.complete_connection(db, owner, "the-code")
    return connection, fake


# -- crypto ---------------------------------------------------------------------


def test_token_crypto_roundtrip_and_wrong_key():
    token = cloud_crypto.encrypt_secret("refresh-token-plaintext")
    assert "refresh-token-plaintext" not in token
    assert cloud_crypto.decrypt_secret(token) == "refresh-token-plaintext"
    import base64 as _b64

    from cryptography.fernet import Fernet

    other = Fernet(_b64.urlsafe_b64encode(b"0" * 32))
    with pytest.raises(Exception):
        other.decrypt(token.encode())


# -- connect ---------------------------------------------------------------------


def test_connect_is_503_without_google_client(client, owner):
    resp = client.get("/api/core/cloud-backup/connect", headers=auth_headers(owner))
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "oauth_not_configured"


def test_connect_authorize_url_carries_state_and_scope(
    client, owner, google_configured
):
    resp = client.get("/api/core/cloud-backup/connect", headers=auth_headers(owner))
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "accounts.google.com" in url
    assert "drive.file" in url
    assert "state=" in url
    assert "openid" not in url and "email" not in url  # ONLY drive.file


def test_callback_completes_and_stores_token_encrypted(
    client, db, owner, google_configured, monkeypatch
):
    state = cloud_backup.create_connect_state(owner.id)
    connection, _fake = _connect(db, owner, monkeypatch)
    assert connection.drive_folder_id == "folder-1"
    assert connection.schedule == "weekly"  # sensible default
    assert connection.refresh_token_encrypted != "refresh-token-plaintext"
    assert (
        cloud_crypto.decrypt_secret(connection.refresh_token_encrypted)
        == "refresh-token-plaintext"
    )
    # Through the HTTP callback leg as well:
    resp = client.get(
        "/api/core/cloud-backup/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "cloud=connected" in resp.headers["location"]


def test_callback_rejects_forged_state(client, google_configured):
    resp = client.get(
        "/api/core/cloud-backup/callback",
        params={"code": "abc", "state": "forged"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "cloud=denied" in resp.headers["location"]


# -- backups ---------------------------------------------------------------------


def _connected_owner(db, owner, monkeypatch):
    connection, fake = _connect(db, owner, monkeypatch)
    monkeypatch.setattr(cloud_backup, "drive_client_for", lambda db_, conn: fake)
    return connection, fake


def test_run_backup_uploads_export_zip_and_ledgers(client, db, owner, monkeypatch):
    _connection, fake = _connected_owner(db, owner, monkeypatch)
    resp = client.post(
        "/api/core/cloud-backup/run", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert state["history"][0]["status"] == "ok"
    assert state["history"][0]["file_name"].startswith("ToolboxVault-Backup-")
    assert state["history"][0]["drive_url"].startswith(
        "https://drive.google.com/file/d/"
    )
    assert len(fake.files) == 1
    assert fake.files[0]["name"].endswith(".zip")
    assert state["last_backup_at"]


def test_rotation_keeps_newest_seven(db, owner, monkeypatch):
    _connection, fake = _connected_owner(db, owner, monkeypatch)
    for _ in range(9):
        run = cloud_backup.run_backup(db, owner, "scheduled", client=fake)
        assert run.status == "ok"
    assert len(fake.files) == 7
    assert len(fake.deleted) == 2


def test_failed_backup_ledgers_and_notifies(db, owner, monkeypatch):
    _connection, _fake = _connected_owner(db, owner, monkeypatch)

    class ExplodingClient(FakeDriveClient):
        def upload(self, name, folder_id, data):
            raise cloud_backup.DriveError("Drive said no.")

    run = cloud_backup.run_backup(
        db, owner, "scheduled", client=ExplodingClient()
    )
    assert run.status == "failed"
    assert "Drive said no" in run.error
    from app.modules.core import inbox

    notes = [
        e for e in inbox.list_for_user(db, owner.id)
        if e["kind"] == "cloud_backup_failed"
    ]
    assert len(notes) == 1


def test_due_logic(db, owner, monkeypatch):
    connection, _fake = _connected_owner(db, owner, monkeypatch)
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    # Never backed up + weekly: due.
    assert cloud_backup.due_connections(db, now) == [connection]
    connection.last_backup_at = now - timedelta(days=3)
    db.commit()
    assert cloud_backup.due_connections(db, now) == []  # weekly not yet
    connection.schedule = "daily"
    db.commit()
    assert cloud_backup.due_connections(db, now) == [connection]  # 3d > 24h
    connection.schedule = "off"
    db.commit()
    assert cloud_backup.due_connections(db, now) == []


def test_due_logic_monthly(db, owner, monkeypatch):
    """Monthly (owner 2026-10-22): due at >= 30 days, not before."""
    connection, _fake = _connected_owner(db, owner, monkeypatch)
    connection.schedule = "monthly"
    db.commit()
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    # Never backed up + monthly: due.
    assert cloud_backup.due_connections(db, now) == [connection]
    connection.last_backup_at = now - timedelta(days=29)
    db.commit()
    assert cloud_backup.due_connections(db, now) == []  # 29d < 30d
    connection.last_backup_at = now - timedelta(days=30)
    db.commit()
    assert cloud_backup.due_connections(db, now) == [connection]  # due at 30d


def test_schedule_roundtrip_monthly(client, db, owner, monkeypatch):
    _connected_owner(db, owner, monkeypatch)
    resp = client.put(
        "/api/core/cloud-backup/schedule",
        json={"schedule": "monthly"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["schedule"] == "monthly"
    assert cloud_backup.connection_for(db, owner.id).schedule == "monthly"
    # An unknown schedule is refused, never stored.
    resp = client.put(
        "/api/core/cloud-backup/schedule",
        json={"schedule": "yearly"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    assert cloud_backup.connection_for(db, owner.id).schedule == "monthly"


def test_reconnect_keeps_monthly_and_coerces_bogus(db, owner, monkeypatch):
    connection, _fake = _connect(db, owner, monkeypatch)
    connection.schedule = "monthly"
    db.commit()
    connection, _fake = _connect(db, owner, monkeypatch)
    assert connection.schedule == "monthly"  # a valid pick survives reconnect
    connection.schedule = "bogus"
    db.commit()
    connection, _fake = _connect(db, owner, monkeypatch)
    assert connection.schedule == "weekly"  # invalid coerces to the default


def test_scheduler_job_runs_due_backups(db, owner, monkeypatch):
    _connected_owner(db, owner, monkeypatch)
    from app.scripts import run_cloud_backup_jobs

    summary = run_cloud_backup_jobs.run(db)
    assert summary == {"checked": 1, "ran": 1, "ok": 1, "failed": 0}


def test_disconnect_wipes_token_keeps_history(db, owner, monkeypatch):
    _connected_owner(db, owner, monkeypatch)
    cloud_backup.run_backup(
        db, owner, "manual", client=FakeDriveClient.instances[-1]
    )
    revoked = []
    monkeypatch.setattr(
        cloud_backup, "revoke_token", lambda token: revoked.append(token)
    )
    cloud_backup.disconnect(db, owner)
    assert revoked == ["refresh-token-plaintext"]  # best-effort revoke happened
    assert cloud_backup.connection_for(db, owner.id) is None
    state = cloud_backup.state_for(db, owner)
    assert state["connected"] is False
    assert len(state["history"]) == 1  # the ledger survives disconnect


def test_account_deletion_cascades_cloud_rows(db, owner, monkeypatch):
    _connected_owner(db, owner, monkeypatch)
    from app.modules.core import service as core_service

    core_service.delete_account(db, owner)
    assert db.query(core_models.CloudDriveConnection).count() == 0


# -- the failure alert policy (2026-10-30) ---------------------------------------


def test_quiet_successes_stay_quiet(db, owner, monkeypatch):
    """A success with no failure streak before it notifies
    nobody — the recovery notice exists only to close a loop
    an alert opened."""
    _connection, fake = _connected_owner(db, owner, monkeypatch)
    run = cloud_backup.run_backup(db, owner, "scheduled", client=fake)
    assert run.status == "ok"
    assert db.query(core_models.Notification).count() == 0
    assert db.query(core_models.EmailOutbox).count() == 0


def test_failure_streak_alert_policy(db, owner, monkeypatch):
    """The incident shape, end to end: a Drive connection dies
    and every scheduled attempt fails. The owner hears about
    the FIRST failure (bell + email), hears NOTHING for the
    next failure minutes later (the run still ledgers), hears
    a "still failing" update once the last alert is a day old,
    and gets exactly ONE "working again" notice when a backup
    finally lands. All mail in this suite is the dev provider
    (outbox rows, status "logged") — nothing real is sent."""
    _connection, _fake = _connected_owner(db, owner, monkeypatch)

    class ExplodingClient(FakeDriveClient):
        def upload(self, name, folder_id, data):
            raise cloud_backup.DriveError("Drive said no.")

    bad = ExplodingClient()
    good = FakeDriveClient()

    def notes(kind):
        return (
            db.query(core_models.Notification)
            .filter(
                core_models.Notification.user_id == owner.id,
                core_models.Notification.kind == kind,
            )
            .order_by(core_models.Notification.created_at)
            .all()
        )

    def alert_emails():
        return (
            db.query(core_models.EmailOutbox)
            .filter(
                core_models.EmailOutbox.recipient == owner.email,
                core_models.EmailOutbox.kind == "notification_email",
            )
            .all()
        )

    # Failure #1: the streak's first failure alerts.
    run1 = cloud_backup.run_backup(db, owner, "scheduled", client=bad)
    assert run1.status == "failed"
    failed = notes("cloud_backup_failed")
    assert len(failed) == 1
    assert failed[0].title == "Cloud backup failed"
    assert "keeps retrying" in failed[0].body

    # Failure #2, minutes later: ledgered, but NO new alert.
    run2 = cloud_backup.run_backup(db, owner, "scheduled", client=bad)
    assert run2.status == "failed"
    assert len(notes("cloud_backup_failed")) == 1

    # Age the books: the streak began 26h ago and its only
    # alert went out 25h ago, so the next failure re-alerts.
    now = datetime.now(timezone.utc)
    run1.started_at = now - timedelta(hours=26)
    run2.started_at = now - timedelta(hours=25, minutes=30)
    db.commit()
    notes("cloud_backup_failed")[0].created_at = now - timedelta(hours=25)
    db.commit()

    run3 = cloud_backup.run_backup(db, owner, "scheduled", client=bad)
    assert run3.status == "failed"
    failed = notes("cloud_backup_failed")
    assert len(failed) == 2
    assert failed[-1].title == "Cloud backup still failing"
    assert "3 attempt(s)" in failed[-1].body
    assert "Latest error: Drive said no." in failed[-1].body

    # A success closes the loop exactly once.
    run4 = cloud_backup.run_backup(db, owner, "scheduled", client=good)
    assert run4.status == "ok"
    recovered = notes("cloud_backup_recovered")
    assert len(recovered) == 1
    assert recovered[0].title == "Cloud backup working again"
    assert "3 failed attempt(s)" in recovered[0].body

    # Another success: no second all-clear, no new failure alerts.
    run5 = cloud_backup.run_backup(db, owner, "scheduled", client=good)
    assert run5.status == "ok"
    assert len(notes("cloud_backup_recovered")) == 1
    assert len(notes("cloud_backup_failed")) == 2

    # The mail record: exactly one email per alert (2 failure
    # alerts + 1 recovery), none for the suppressed failure or
    # the second success — all dev-provider rows, never sent.
    emails = alert_emails()
    assert len(emails) == 3
    assert all(e.provider == "dev" and e.status == "logged" for e in emails)
    subjects = [e.subject for e in emails]
    assert "Cloud backup failed" in subjects
    assert "Cloud backup still failing" in subjects
    assert "Cloud backup working again" in subjects

    # Every attempt ledgered, alerted or not.
    assert db.query(core_models.CloudBackupRun).count() == 5
