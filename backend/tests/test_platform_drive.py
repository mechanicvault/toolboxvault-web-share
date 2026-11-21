"""Disaster Vault platform Drive connection (2026-10-24): the
OAuth-as-the-account upload leg that replaces the service
account (which has no storage quota and 403'd forever).

Everything Google is MOCKED (exchange / email lookup / revoke /
token seam / upload are stubbed) — no real Google call happens
here; the live connect is the operator's own click.

Pins:
  - run_bundle: connection + stubbed token/upload with matching
    size/md5 -> ok + uploaded; connection present but the token
    seam raising -> failed + failure alert email;
  - connect endpoint: operator-only, 503 while the Google client
    is unconfigured, and the authorize URL carries the FULL drive
    scope, the registered cloud-backup redirect URI, and a
    platform-purpose state bound to the operator;
  - callback with a platform state: stores the connection row
    with the refresh token ENCRYPTED (decrypt round-trips) and
    redirects to Admin -> Settings with drive=connected; a
    non-operator state is denied and stores nothing;
  - disconnect deletes the row;
  - Admin -> Settings carries the backup_drive posture.
"""

import hashlib
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.backup import job
from app.core.config import settings
from app.modules.core import cloud_backup, cloud_crypto, models
from tests.conftest import auth_headers
from tests.test_backup import _plant_source


def _make_user(db, account_number, email, *, is_operator=False):
    user = models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Platform User",
        password_hash="not-a-real-hash",
        is_operator=is_operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-PD0001", "pd-op@example.com", is_operator=True)


@pytest.fixture()
def plain_user(db):
    return _make_user(db, "TV-M-PD0002", "pd-user@example.com")


@pytest.fixture()
def google_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id-test")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret-test")
    monkeypatch.setattr(settings, "backup_drive_folder_id", "folder123")


def _add_connection(db, folder_id="folder123"):
    row = models.PlatformDriveConnection(
        refresh_token_encrypted=cloud_crypto.encrypt_secret("refresh-plaintext"),
        drive_email="MechanicVault@gmail.com",
        drive_folder_id=folder_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# -- run_bundle with a connection -------------------------------------------------


@pytest.fixture()
def bundle_env(db, tmp_path, monkeypatch):
    """Same stubbing posture as tests/test_backup.py's fixture:
    tmp vault, service stages faked, ledger rebound to the test DB."""
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
    monkeypatch.setattr(job.settings, "backup_drive_folder_id", "folder123")
    return vault


def _stub_archive_and_encrypt(monkeypatch):
    """The archive/encrypt stages need the zstd/age binaries,
    which ship in the backup image but not in every test
    environment — stub them (bytes in -> renamed .age out) so the
    DRIVE behavior these tests pin runs everywhere, never skips."""

    def fake_archive(staging, bundle_id, out_path):
        out_path.write_bytes(b"fake-archive-bytes")

    def fake_encrypt(archive_path, recipient):
        out = archive_path.with_suffix(archive_path.suffix + ".age")
        out.write_bytes(archive_path.read_bytes())
        archive_path.unlink()
        return out

    monkeypatch.setattr(job, "stage_archive", fake_archive)
    monkeypatch.setattr(job, "stage_encrypt", fake_encrypt)
    monkeypatch.setattr(
        job.settings, "backup_age_public_key", "age1fake-recipient-for-tests"
    )


def test_run_with_connection_uploads_and_verifies(db, bundle_env, monkeypatch):
    _stub_archive_and_encrypt(monkeypatch)
    _add_connection(db)
    monkeypatch.setattr(job, "platform_drive_token", lambda: "access-token-1")
    seen = {}

    def fake_upload(token, folder_id, file_path):
        seen.update(token=token, folder_id=folder_id, name=file_path.name)
        return {
            "id": "drive-file-1",
            "size": str(file_path.stat().st_size),
            "md5Checksum": job.md5_file(file_path),
        }

    monkeypatch.setattr(job, "drive_upload", fake_upload)
    monkeypatch.setattr(job, "prune_drive", lambda *a, **k: [])

    run = job.run_bundle()

    assert run.status == "ok"
    assert run.encrypted is True
    assert run.uploaded is True
    assert run.verified is True
    assert seen == {
        "token": "access-token-1",
        "folder_id": "folder123",
        "name": run.bundle_name,
    }
    assert run.detail["drive_file_id"] == "drive-file-1"
    assert run.detail["verification"] == "drive_size+md5"


def test_run_with_connection_but_token_failing_alerts(db, bundle_env, monkeypatch):
    _stub_archive_and_encrypt(monkeypatch)
    _add_connection(db)

    def broken_token():
        raise job.StageError("upload", "Drive token refresh failed: HTTP 400")

    monkeypatch.setattr(job, "platform_drive_token", broken_token)
    sent = []
    monkeypatch.setattr(
        job,
        "_send_report",
        lambda kind, to, subject, body: sent.append((kind, subject, body)) or True,
    )

    run = job.run_bundle()

    assert run.status == "failed"
    assert run.uploaded is False
    assert run.detail["stage"] == "upload"
    assert sent and sent[0][0] == "backup_alert"
    assert "FAILED" in sent[0][1]


# -- connect endpoint ----------------------------------------------------------------


def test_connect_requires_operator(client, plain_user, google_configured):
    resp = client.post(
        "/api/admin/settings/backup-drive/connect",
        headers=auth_headers(plain_user),
    )
    assert resp.status_code == 403


def test_connect_503_without_google_client(client, operator, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    resp = client.post(
        "/api/admin/settings/backup-drive/connect",
        headers=auth_headers(operator),
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "oauth_not_configured"


def test_connect_authorize_url_shape(client, operator, google_configured):
    resp = client.post(
        "/api/admin/settings/backup-drive/connect",
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "accounts.google.com" in url
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == ["https://www.googleapis.com/auth/drive"]
    assert params["redirect_uri"] == [cloud_backup.cloud_redirect_uri()]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    parsed = cloud_backup.parse_connect_state_with_purpose(params["state"][0])
    assert parsed is not None
    user_id, purpose = parsed
    assert user_id == operator.id
    assert purpose == cloud_backup.PLATFORM_CONNECT_PURPOSE
    # The user feature's parser must NOT accept a platform state.
    assert cloud_backup.parse_connect_state(params["state"][0]) is None


# -- callback (platform purpose) -------------------------------------------------------


def _stub_exchange(monkeypatch):
    monkeypatch.setattr(
        cloud_backup,
        "exchange_code",
        lambda code: {
            "refresh_token": "platform-refresh-plaintext",
            "access_token": "access-token-1",
        },
    )
    monkeypatch.setattr(
        cloud_backup, "drive_account_email", lambda token: "MechanicVault@gmail.com"
    )


def test_callback_platform_stores_encrypted_row(
    client, db, operator, google_configured, monkeypatch
):
    _stub_exchange(monkeypatch)
    state = cloud_backup.create_connect_state(
        operator.id, purpose=cloud_backup.PLATFORM_CONNECT_PURPOSE
    )
    resp = client.get(
        "/api/core/cloud-backup/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("/admin/settings")
    assert "drive=connected" in location

    row = cloud_backup.platform_connection(db)
    assert row is not None
    assert row.refresh_token_encrypted != "platform-refresh-plaintext"
    assert (
        cloud_crypto.decrypt_secret(row.refresh_token_encrypted)
        == "platform-refresh-plaintext"
    )
    assert row.drive_email == "MechanicVault@gmail.com"
    assert row.drive_folder_id == "folder123"
    assert row.connected_by_id == operator.id

    # Settings view reports the connection.
    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()
    assert view["backup_drive"]["connected"] is True
    assert view["backup_drive"]["email"] == "MechanicVault@gmail.com"
    assert view["backup_drive"]["oauth_configured"] is True


def test_callback_platform_denies_non_operator(
    client, db, plain_user, google_configured, monkeypatch
):
    _stub_exchange(monkeypatch)
    state = cloud_backup.create_connect_state(
        plain_user.id, purpose=cloud_backup.PLATFORM_CONNECT_PURPOSE
    )
    resp = client.get(
        "/api/core/cloud-backup/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "drive=denied" in resp.headers["location"]
    assert cloud_backup.platform_connection(db) is None


def test_callback_platform_without_refresh_token_fails(
    client, db, operator, google_configured, monkeypatch
):
    monkeypatch.setattr(
        cloud_backup, "exchange_code", lambda code: {"access_token": "only-access"}
    )
    state = cloud_backup.create_connect_state(
        operator.id, purpose=cloud_backup.PLATFORM_CONNECT_PURPOSE
    )
    resp = client.get(
        "/api/core/cloud-backup/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "drive=failed" in resp.headers["location"]
    assert cloud_backup.platform_connection(db) is None


# -- disconnect -------------------------------------------------------------------------


def test_disconnect_deletes_row(client, db, operator, google_configured, monkeypatch):
    _add_connection(db)
    monkeypatch.setattr(cloud_backup, "revoke_token", lambda token: None)

    resp = client.post(
        "/api/admin/settings/backup-drive/disconnect",
        headers=auth_headers(operator),
    )

    assert resp.status_code == 200
    assert resp.json()["backup_drive"]["connected"] is False
    assert cloud_backup.platform_connection(db) is None


def test_settings_backup_drive_defaults_when_not_connected(
    client, operator, google_configured
):
    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()
    assert view["backup_drive"] == {
        "connected": False,
        "email": "",
        "folder_id": "folder123",
        "connected_at": None,
        "oauth_configured": True,
    }
