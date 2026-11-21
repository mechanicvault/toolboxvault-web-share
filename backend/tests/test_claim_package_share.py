"""Audit A10 (2026-10-22): claim package sharing — Save to my
Drive + Email the package.

The Drive client and the mail seam are faked at their module
seams (core.cloud_backup / app.core.notifications), the same
surfaces production wires — no network anywhere near the tests.
"""

import pytest

from app.modules.claims import models as claim_models
from app.modules.core import cloud_backup

from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, number, email):
    from app.modules.core import models as core_models

    user = core_models.User(
        account_number=number,
        email=email,
        name="Share Tester",
        password_hash="x",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000501", "a10-owner@example.com")


def _claim(client, user):
    resp = client.post("/api/disaster-claims", json={}, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


class FakeDriveClient:
    def __init__(self):
        self.uploads = []

    def ensure_folder(self, name):
        return {"id": "folder-1", "name": name}

    def upload(self, name, folder_id, data, *, mime_type="application/zip"):
        self.uploads.append((name, folder_id, len(data), mime_type))
        return {"id": "file-1", "webViewLink": "https://drive.example/file-1"}


@pytest.fixture()
def fake_drive(monkeypatch):
    client = FakeDriveClient()
    monkeypatch.setattr(
        cloud_backup, "connection_for", lambda db, user_id: object()
    )
    monkeypatch.setattr(
        cloud_backup, "drive_client_for", lambda db, connection: client
    )
    return client


@pytest.fixture()
def no_drive(monkeypatch):
    monkeypatch.setattr(cloud_backup, "connection_for", lambda db, user_id: None)


@pytest.fixture()
def sent_mail(monkeypatch):
    from app.core import notifications

    calls = []

    def fake_send(db, to, subject, body, *, kind="generic", attachment=None):
        calls.append(
            {"to": to, "subject": subject, "body": body, "attachment": attachment}
        )
        return True

    monkeypatch.setattr(notifications, "send_email", fake_send)
    return calls


def _comm_summaries(db, claim_id):
    import uuid

    from sqlalchemy import select

    return [
        row.summary
        for row in db.scalars(
            select(claim_models.ClaimCommunication).where(
                claim_models.ClaimCommunication.claim_id == uuid.UUID(str(claim_id))
            )
        )
    ]


def test_save_to_drive_uploads_pdf_and_journals(client, db, owner, fake_drive):
    claim = _claim(client, owner)
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/package/drive", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == f"claim-package-{claim['claim_number']}.pdf"
    assert body["drive_link"] == "https://drive.example/file-1"
    name, folder_id, size, mime = fake_drive.uploads[0]
    assert folder_id == "folder-1" and size > 0 and mime == "application/pdf"
    assert any("saved to Google Drive" in s for s in _comm_summaries(db, claim["id"]))


def test_save_to_drive_without_connection_is_a_clear_409(client, owner, no_drive):
    claim = _claim(client, owner)
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/package/drive", headers=auth_headers(owner)
    )
    assert resp.status_code == 409, resp.text
    assert "isn't connected" in resp.json()["detail"]


def test_email_package_attaches_and_journals(client, db, owner, sent_mail):
    claim = _claim(client, owner)
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/package/email", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["via"] == "attachment"
    assert len(sent_mail) == 1
    filename, content = sent_mail[0]["attachment"]
    assert filename.endswith(".pdf") and len(content) > 0
    assert any("emailed" in s for s in _comm_summaries(db, claim["id"]))


def test_oversized_package_emails_the_drive_link(
    client, db, owner, fake_drive, sent_mail, monkeypatch
):
    from app.modules.claims import package, package_share

    monkeypatch.setattr(
        package, "build_package", lambda db_, owner_, claim_: b"x" * 2048
    )
    monkeypatch.setattr(package_share, "MAX_EMAIL_ATTACHMENT_BYTES", 1024)
    claim = _claim(client, owner)
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/package/email", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["via"] == "drive_link"
    assert sent_mail[0]["attachment"] is None
    assert "drive.example/file-1" in sent_mail[0]["body"]
    assert any("too large to email" in s for s in _comm_summaries(db, claim["id"]))


def test_oversized_without_drive_refuses_rather_than_dropping(
    client, owner, no_drive, sent_mail, monkeypatch
):
    from app.modules.claims import package, package_share

    monkeypatch.setattr(
        package, "build_package", lambda db_, owner_, claim_: b"x" * 2048
    )
    monkeypatch.setattr(package_share, "MAX_EMAIL_ATTACHMENT_BYTES", 1024)
    claim = _claim(client, owner)
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/package/email", headers=auth_headers(owner)
    )
    assert resp.status_code == 409, resp.text
    assert sent_mail == []  # nothing pretended to be sent
