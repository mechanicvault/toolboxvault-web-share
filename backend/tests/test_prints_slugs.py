"""Print file URL slugs (sheet row 99): a published file gets
a short plain-words slug from its title, unique across the
shelf; the detail route resolves the slug AND the old id
(old links keep working); a title edit never rewrites an
existing slug; the sitemap names the slug URL.
"""

import struct
import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
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


@pytest.fixture()
def publisher(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-002101",
        email="slugpub@example.com",
        name="Slug Publisher",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 49 + b"\x00"


def _publish(client, user, *, title):
    files = {"print_file": ("rail.stl", _stl(), "application/octet-stream")}
    data = {
        "title": title,
        "description": "A thing that holds things.",
        "category": "socket-wrench",
        "note": "First cut.",
    }
    return client.post(
        "/api/prints/files", data=data, files=files, headers=auth_headers(user)
    )


def test_publish_assigns_a_plain_words_slug(client, publisher, fake_storage):
    resp = _publish(client, publisher, title="Impact Swivel Mount — 1/2in!")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "impact-swivel-mount-1-2in"


def test_duplicate_titles_get_numbered_slugs(client, publisher, fake_storage):
    first = _publish(client, publisher, title="Socket Rail").json()
    second = _publish(client, publisher, title="Socket Rail").json()
    assert first["slug"] == "socket-rail"
    assert second["slug"] == "socket-rail-2"


def test_detail_resolves_by_slug_and_by_id(client, publisher, fake_storage):
    body = _publish(client, publisher, title="Drawer Divider Set").json()
    by_slug = client.get(f"/api/prints/files/{body['slug']}")
    assert by_slug.status_code == 200, by_slug.text
    assert by_slug.json()["id"] == body["id"]
    by_id = client.get(f"/api/prints/files/{body['id']}")
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["slug"] == "drawer-divider-set"
    missing = client.get("/api/prints/files/no-such-file-here")
    assert missing.status_code == 404


def test_title_edit_never_rewrites_the_slug(client, publisher, fake_storage):
    body = _publish(client, publisher, title="Original Name").json()
    resp = client.put(
        f"/api/prints/files/{body['id']}",
        json={
            "title": "A Totally Different Name",
            "description": "Edited.",
            "category": "socket-wrench",
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["slug"] == "original-name"
    assert resp.json()["title"] == "A Totally Different Name"


def test_sitemap_names_the_slug_url(client, publisher, fake_storage):
    body = _publish(client, publisher, title="Sitemap Probe File").json()
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert f"/3dprints/{body['slug']}" in resp.text
    assert f"/3dprints/{body['id']}" not in resp.text
