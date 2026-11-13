"""Content alerts (sweep E4, busy-work #6, 2026-11-12):
the new-content opt-ins (Downloads + 3D Print Files boxes,
default OFF) and the per-print-file update opt-in.

Proven at the service + route level:
- both boxes default OFF; flipping one never touches the other;
- a new print file notifies ONLY opted-in users, each in their
  OWN language (EN + ES), never the publisher;
- a followed file's new version notifies its followers (in
  their language), never the publisher, and unfollowing stops it;
- the publisher cannot follow their own file;
- downloads first-appearance: the first catalog sync EVER is
  baseline (watermark stamped, nobody notified); a catalog key
  appearing afterwards notifies opted-in users exactly once.
"""

import struct
import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import content_alerts, inbox, models as core_models
from app.modules.downloads import catalog as catalog_def
from app.modules.downloads import service as downloads_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, content_type):
        self.objects[key] = data
        return storage_module.StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )

    def fetch(self, key):
        if key not in self.objects:
            raise storage_module.ObjectNotFound(key)
        return self.objects[key]

    def head(self, key):
        if key not in self.objects:
            raise storage_module.ObjectNotFound(key)
        return storage_module.StoredObject(
            key=key, size_bytes=len(self.objects[key]), content_type=""
        )

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_put_url(self, key, content_type, expires_in=900):
        return f"https://files.test/put/{key}"

    def presigned_get_url(self, key, expires_in=3600):
        return f"https://files.test/get/{key}"


@pytest.fixture()
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    for name in (
        "put_bytes",
        "fetch",
        "head",
        "delete",
        "presigned_put_url",
        "presigned_get_url",
    ):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    return fake


def _make_user(db, account_number, email, *, name="Alert User", locale=""):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def publisher(db):
    return _make_user(db, "TV-M-004001", "capub@example.com", name="Cap Publisher")


@pytest.fixture()
def fan_en(db):
    return _make_user(db, "TV-M-004002", "caen@example.com", name="En Fan")


@pytest.fixture()
def fan_es(db):
    return _make_user(db, "TV-M-004003", "caes@example.com", name="Es Fan", locale="es")


@pytest.fixture()
def bystander(db):
    return _make_user(db, "TV-M-004004", "cabystander@example.com", name="No Box")


def _notes(db, user_id, kind=None):
    rows = db.scalars(
        __import__("sqlalchemy").select(core_models.Notification).where(
            core_models.Notification.user_id == user_id
        )
    ).all()
    if kind:
        rows = [r for r in rows if r.kind == kind]
    return rows


def _stl(marker=b""):
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 49 + (marker or b"\x00")


def _publish(client, user, *, title="Alert rail"):
    return client.post(
        "/api/prints/files",
        data={
            "title": title,
            "description": "A rail.",
            "category": "socket-wrench",
            "note": "First cut.",
        },
        files={"print_file": ("rail.stl", _stl(), "application/octet-stream")},
        headers=auth_headers(user),
    )


# -- the boxes ---------------------------------------------------


def test_prefs_default_off_and_flip_independently(client, fan_en):
    resp = client.get("/api/core/me/content-alerts", headers=auth_headers(fan_en))
    assert resp.status_code == 200
    assert resp.json() == {"downloads": False, "prints": False}

    resp = client.put(
        "/api/core/me/content-alerts",
        json={"kind": "prints", "enabled": True},
        headers=auth_headers(fan_en),
    )
    assert resp.status_code == 200
    assert resp.json() == {"downloads": False, "prints": True}

    resp = client.put(
        "/api/core/me/content-alerts",
        json={"kind": "bogus", "enabled": True},
        headers=auth_headers(fan_en),
    )
    assert resp.status_code == 422


def test_new_print_notifies_opted_in_only_per_language(
    client, db, publisher, fan_en, fan_es, bystander, fake_storage
):
    content_alerts.set_pref(db, fan_en.id, kind="prints", enabled=True)
    content_alerts.set_pref(db, fan_es.id, kind="prints", enabled=True)
    # Even an opted-in publisher hears nothing about their own publish.
    content_alerts.set_pref(db, publisher.id, kind="prints", enabled=True)

    resp = _publish(client, publisher)
    assert resp.status_code == 201, resp.text

    en_notes = _notes(db, fan_en.id, inbox.KIND_PRINT_FILE_NEW)
    assert len(en_notes) == 1
    assert en_notes[0].title == "New 3D print file"
    assert "Alert rail" in en_notes[0].body

    es_notes = _notes(db, fan_es.id, inbox.KIND_PRINT_FILE_NEW)
    assert len(es_notes) == 1
    assert es_notes[0].title == "Archivo de impresión 3D nuevo"
    assert "Alert rail" in es_notes[0].body
    # Single language: no English stacked into the ES row.
    assert "New 3D print file" not in es_notes[0].body

    assert _notes(db, bystander.id) == []
    assert _notes(db, publisher.id) == []


# -- per-file follow ----------------------------------------------


def test_follow_update_flow(client, db, publisher, fan_en, fan_es, fake_storage):
    file_id = _publish(client, publisher).json()["id"]

    # The publisher cannot follow their own file.
    resp = client.put(
        f"/api/prints/files/{file_id}/follow",
        json={"following": True},
        headers=auth_headers(publisher),
    )
    assert resp.status_code in (400, 422)

    for fan in (fan_en, fan_es):
        resp = client.put(
            f"/api/prints/files/{file_id}/follow",
            json={"following": True},
            headers=auth_headers(fan),
        )
        assert resp.status_code == 200
        assert resp.json() == {"following": True}
    detail = client.get(
        f"/api/prints/files/{file_id}", headers=auth_headers(fan_en)
    ).json()
    assert detail["following"] is True

    resp = client.post(
        f"/api/prints/files/{file_id}/versions",
        data={"note": "Second cut."},
        files={"print_file": ("rail2.stl", _stl(b"x"), "application/octet-stream")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text

    en_notes = _notes(db, fan_en.id, inbox.KIND_PRINT_FILE_UPDATED)
    assert len(en_notes) == 1
    assert "v2" in en_notes[0].body
    es_notes = _notes(db, fan_es.id, inbox.KIND_PRINT_FILE_UPDATED)
    assert len(es_notes) == 1
    assert es_notes[0].title == "Archivo de impresión actualizado"
    assert _notes(db, publisher.id) == []

    # Unfollow stops the next version's notice.
    client.put(
        f"/api/prints/files/{file_id}/follow",
        json={"following": False},
        headers=auth_headers(fan_en),
    )
    resp = client.post(
        f"/api/prints/files/{file_id}/versions",
        data={"note": "Third cut."},
        files={"print_file": ("rail3.stl", _stl(b"y"), "application/octet-stream")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201
    assert len(_notes(db, fan_en.id, inbox.KIND_PRINT_FILE_UPDATED)) == 1
    assert len(_notes(db, fan_es.id, inbox.KIND_PRINT_FILE_UPDATED)) == 2


def test_print_notification_link_resolves_to_listing(
    client, db, publisher, fan_en, fake_storage
):
    from app.modules.core import inbox_links

    content_alerts.set_pref(db, fan_en.id, kind="prints", enabled=True)
    file_id = _publish(client, publisher).json()["id"]
    note = _notes(db, fan_en.id, inbox.KIND_PRINT_FILE_NEW)[0]
    links = inbox_links.resolve_links(db, fan_en, [note])
    assert links[note.id] == f"/3dprints/{file_id}"


# -- downloads first appearance ------------------------------------


def test_downloads_first_sync_is_baseline_then_new_key_notifies_once(
    db, fan_en, fan_es, bystander, monkeypatch
):
    content_alerts.set_pref(db, fan_en.id, kind="downloads", enabled=True)
    content_alerts.set_pref(db, fan_es.id, kind="downloads", enabled=True)

    # First sync ever: the whole shelf is baseline — nobody is told.
    downloads_service.ensure_catalog(db)
    assert content_alerts.downloads_watermark_seen(db)
    assert _notes(db, fan_en.id) == []
    assert _notes(db, fan_es.id) == []

    # A catalog key appearing afterwards is news, exactly once.
    extra = catalog_def.CatalogEntry(
        "e4-proof-sheet", "e4-proof.xlsx", "E4-Proof.xlsx", "xlsx", 999
    )
    monkeypatch.setattr(
        catalog_def, "CATALOG", catalog_def.CATALOG + (extra,)
    )
    downloads_service.ensure_catalog(db)
    en_notes = _notes(db, fan_en.id, inbox.KIND_DOWNLOAD_FILE_NEW)
    assert len(en_notes) == 1
    assert en_notes[0].title == "New file download"
    es_notes = _notes(db, fan_es.id, inbox.KIND_DOWNLOAD_FILE_NEW)
    assert len(es_notes) == 1
    assert es_notes[0].title == "Descarga de archivo nueva"
    assert _notes(db, bystander.id) == []

    downloads_service.ensure_catalog(db)
    assert len(_notes(db, fan_en.id, inbox.KIND_DOWNLOAD_FILE_NEW)) == 1
