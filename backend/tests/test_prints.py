"""3D Print Files (Downloads Part 2, owner order 2026-11-08):
the community shelf's public/registered split, publishing +
versioning, the rating math, comments, flags + the moderation
queue, removal seats, maker links, the module gate and the
community-block door — proven against the real routes with
storage faked at the storage object (the flyers' pattern).
"""

import struct
import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.forum import blocks as community_blocks
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


def _make_user(db, account_number, email, *, name="Print User", role="user", tier=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role=role,
    )
    if tier is not None:
        user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def publisher(db):
    return _make_user(db, "TV-M-002001", "pub@example.com", name="Pete Publisher")


@pytest.fixture()
def reader(db):
    return _make_user(db, "TV-M-002002", "reader@example.com", name="Rae Reader")


@pytest.fixture()
def third(db):
    return _make_user(db, "TV-M-002003", "third@example.com", name="Theo Third")


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-002004", "pmod@example.com", name="Mo Mod", role="moderator"
    )


@pytest.fixture()
def mod_admin(db):
    return _make_user(
        db, "TV-M-002005", "pma@example.com", name="Ada Admin", tier="moderator_admin"
    )


def _stl(marker=b""):
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 49 + (marker or b"\x00")


def _step():
    return (
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\n"
        b"END-ISO-10303-21;\n"
    )


def _png():
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _publish(client, user, *, title="Socket rail 10mm", with_step=True, **over):
    files = {"print_file": ("rail.stl", _stl(), "application/octet-stream")}
    if with_step:
        files["step_file"] = ("rail.step", _step(), "application/octet-stream")
    data = {
        "title": title,
        "description": "A rail that holds ten sockets.",
        "category": "socket-wrench",
        "note": "First cut.",
    }
    data.update(over)
    return client.post(
        "/api/prints/files", data=data, files=files, headers=auth_headers(user)
    )


# -- publishing + the public shelf ----------------------------------------


def test_publish_and_public_browse(client, publisher, fake_storage):
    resp = _publish(client, publisher)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["current_version"] == 1
    assert body["publisher"]["display_name"] == "Pete Publisher"
    assert body["rating"] == {"average": None, "count": 0}
    assert body["versions"][0]["has_step"] is True

    # Signed-out browse sees the file (the shelf is public).
    browse = client.get("/api/prints/files")
    assert browse.status_code == 200
    assert browse.json()["total"] == 1
    row = browse.json()["files"][0]
    assert row["id"] == body["id"]
    assert row["current_version"] == 1
    assert row["download_count"] == 0

    detail = client.get(f"/api/prints/files/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["description"].startswith("A rail")
    assert detail.json()["comment_count"] == 0

    cats = client.get("/api/prints/categories")
    assert "socket-wrench" in cats.json()["categories"]


def test_browse_search_filter_sort(client, publisher, reader, fake_storage):
    _publish(client, publisher, title="Socket rail")
    _publish(client, publisher, title="Drawer divider", category="toolbox-drawer")
    found = client.get("/api/prints/files", params={"q": "divider"})
    assert found.json()["total"] == 1
    filtered = client.get(
        "/api/prints/files", params={"category": "toolbox-drawer"}
    )
    assert filtered.json()["total"] == 1
    bad = client.get("/api/prints/files", params={"category": "tool-categories"})
    assert bad.status_code == 422
    # Search reaches the publisher's name too.
    by_name = client.get("/api/prints/files", params={"q": "Pete"})
    assert by_name.json()["total"] == 2
    assert reader is not None


def test_publish_validation(client, publisher, fake_storage):
    assert _publish(client, publisher, category="not-a-category").status_code == 422
    # Impostor bytes: text in an .stl costume.
    resp = client.post(
        "/api/prints/files",
        data={"title": "Fake", "description": "", "category": "other-shop"},
        files={"print_file": ("fake.stl", b"just some text", "text/plain")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 422
    # A STEP that isn't a STEP.
    resp = client.post(
        "/api/prints/files",
        data={"title": "Bad step", "description": "", "category": "other-shop"},
        files={
            "print_file": ("ok.stl", _stl(), "application/octet-stream"),
            "step_file": ("bad.step", b"not a step file", "text/plain"),
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 422
    # Signed-out publish is refused by the session gate.
    resp = client.post(
        "/api/prints/files",
        data={"title": "Anon", "description": "", "category": "other-shop"},
        files={"print_file": ("ok.stl", _stl(), "application/octet-stream")},
    )
    assert resp.status_code == 401


def test_preview_photo_roundtrip(client, publisher, fake_storage):
    resp = client.post(
        "/api/prints/files",
        data={
            "title": "With photo",
            "description": "",
            "category": "parts-trays",
        },
        files={
            "print_file": ("tray.stl", _stl(), "application/octet-stream"),
            "preview": ("tray.png", _png(), "image/png"),
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    assert resp.json()["has_preview"] is True
    shot = client.get(f"/api/prints/files/{file_id}/preview")
    assert shot.status_code == 200
    assert shot.content == _png()


# -- downloads + the access split -----------------------------------------


def test_public_print_download_counts(client, publisher, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    resp = client.get(f"/api/prints/files/{file_id}/download")
    assert resp.status_code == 200
    assert resp.content == _stl()
    resp = client.get(f"/api/prints/files/{file_id}/download")
    assert resp.status_code == 200
    detail = client.get(f"/api/prints/files/{file_id}").json()
    assert detail["download_count"] == 2
    assert detail["versions"][0]["downloads"] == 2


def test_step_download_registered_only(client, publisher, reader, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    anon = client.get(f"/api/prints/files/{file_id}/step")
    assert anon.status_code == 401
    ok = client.get(
        f"/api/prints/files/{file_id}/step", headers=auth_headers(reader)
    )
    assert ok.status_code == 200
    assert ok.content == _step()
    detail = client.get(f"/api/prints/files/{file_id}").json()
    assert detail["step_download_count"] == 1
    assert detail["versions"][0]["step_downloads"] == 1


# -- versioning -------------------------------------------------------------


def test_update_flow_keeps_old_versions(client, publisher, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    resp = client.post(
        f"/api/prints/files/{file_id}/versions",
        data={"note": "Stronger walls."},
        files={"print_file": ("rail-v2.stl", _stl(b"\x01"), "application/octet-stream")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["current_version"] == 2
    assert [v["version_number"] for v in body["versions"]] == [2, 1]
    assert body["versions"][0]["note"] == "Stronger walls."
    # v2 has no STEP (none supplied); v1 keeps its own.
    assert body["versions"][0]["has_step"] is False
    assert body["versions"][1]["has_step"] is True

    v1 = client.get(f"/api/prints/files/{file_id}/download", params={"version": 1})
    assert v1.status_code == 200
    assert v1.content == _stl()
    detail = client.get(f"/api/prints/files/{file_id}").json()
    assert detail["versions"][1]["downloads"] == 1
    assert detail["download_count"] == 1


def test_update_is_owner_only(client, publisher, reader, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    resp = client.post(
        f"/api/prints/files/{file_id}/versions",
        data={"note": "Hijack"},
        files={"print_file": ("x.stl", _stl(), "application/octet-stream")},
        headers=auth_headers(reader),
    )
    assert resp.status_code == 404


# -- ratings ------------------------------------------------------------------


def test_rating_math_and_rules(client, publisher, reader, third, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    own = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 5},
        headers=auth_headers(publisher),
    )
    assert own.status_code == 422
    anon = client.post(f"/api/prints/files/{file_id}/rate", json={"stars": 5})
    assert anon.status_code == 401

    r1 = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 5},
        headers=auth_headers(reader),
    )
    assert r1.status_code == 200
    assert r1.json() == {"average": 5.0, "count": 1, "my_rating": 5}

    r2 = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 4},
        headers=auth_headers(third),
    )
    assert r2.json()["average"] == 4.5
    assert r2.json()["count"] == 2

    # Changing a rating moves the average, not the count.
    r3 = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 2},
        headers=auth_headers(reader),
    )
    assert r3.json()["average"] == 3.0
    assert r3.json()["count"] == 2

    detail = client.get(
        f"/api/prints/files/{file_id}", headers=auth_headers(third)
    ).json()
    assert detail["my_rating"] == 4


# -- comments -------------------------------------------------------------------


def test_comments_flow_and_tombstones(client, publisher, reader, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    anon = client.post(
        f"/api/prints/files/{file_id}/comments", json={"body": "Nice"}
    )
    assert anon.status_code == 401
    posted = client.post(
        f"/api/prints/files/{file_id}/comments",
        json={"body": "Printed clean at 0.2."},
        headers=auth_headers(reader),
    )
    assert posted.status_code == 201, posted.text
    comment_id = posted.json()["id"]
    listed = client.get(f"/api/prints/files/{file_id}/comments")
    assert listed.status_code == 200
    assert listed.json()["comments"][0]["body"] == "Printed clean at 0.2."
    assert listed.json()["comments"][0]["author"]["display_name"] == "Rae Reader"

    gone = client.request(
        "DELETE",
        f"/api/prints/comments/{comment_id}",
        headers=auth_headers(reader),
    )
    assert gone.status_code == 200
    listed = client.get(f"/api/prints/files/{file_id}/comments").json()
    assert listed["comments"][0]["status"] == "removed_author"
    assert listed["comments"][0]["body"] == ""
    detail = client.get(f"/api/prints/files/{file_id}").json()
    assert detail["comment_count"] == 0


# -- flags, the queue, removal ---------------------------------------------------


def test_flag_queue_and_admin_removal(
    client, db, publisher, reader, moderator, mod_admin, fake_storage
):
    file_id = _publish(client, publisher).json()["id"]
    report = client.post(
        f"/api/prints/files/{file_id}/report",
        json={"reason": "A pop-can holder for an ATV."},
        headers=auth_headers(reader),
    )
    assert report.status_code == 201, report.text
    # One open flag per member per target.
    again = client.post(
        f"/api/prints/files/{file_id}/report",
        json={"reason": "Still off-topic."},
        headers=auth_headers(reader),
    )
    assert again.status_code == 422
    # The moderation team was notified.
    notes = db.query(core_models.Notification).filter(
        core_models.Notification.user_id == moderator.id
    ).all()
    assert any(n.kind == "community_flag" for n in notes)

    queue = client.get(
        "/api/prints/moderation/reports", headers=auth_headers(moderator)
    )
    assert queue.status_code == 200
    assert queue.json()["reports"][0]["file_id"] == file_id
    # A plain member can't see the queue.
    denied = client.get(
        "/api/prints/moderation/reports", headers=auth_headers(reader)
    )
    assert denied.status_code == 403
    # A plain moderator can't remove another member's file.
    denied = client.post(
        f"/api/prints/moderation/files/{file_id}/remove",
        json={"reason": "Off-topic."},
        headers=auth_headers(moderator),
    )
    assert denied.status_code == 403
    # moderator_admin can — and the file leaves the shelf, its
    # open flags actioned with it.
    removed = client.post(
        f"/api/prints/moderation/files/{file_id}/remove",
        json={"reason": "Off-topic: not a shop print."},
        headers=auth_headers(mod_admin),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "removed"
    assert client.get(f"/api/prints/files/{file_id}").status_code == 404
    assert client.get(f"/api/prints/files/{file_id}/download").status_code == 404
    queue = client.get(
        "/api/prints/moderation/reports", headers=auth_headers(moderator)
    ).json()
    assert queue["reports"] == []


def test_publisher_removes_own_file(client, publisher, fake_storage):
    file_id = _publish(client, publisher).json()["id"]
    removed = client.request(
        "DELETE", f"/api/prints/files/{file_id}", headers=auth_headers(publisher)
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"
    assert client.get("/api/prints/files").json()["total"] == 0


def test_comment_flag_and_dismiss(
    client, publisher, reader, third, moderator, fake_storage
):
    file_id = _publish(client, publisher).json()["id"]
    comment_id = client.post(
        f"/api/prints/files/{file_id}/comments",
        json={"body": "spam spam"},
        headers=auth_headers(reader),
    ).json()["id"]
    report = client.post(
        f"/api/prints/comments/{comment_id}/report",
        json={"reason": "Spam."},
        headers=auth_headers(third),
    )
    assert report.status_code == 201
    queue = client.get(
        "/api/prints/moderation/reports", headers=auth_headers(moderator)
    ).json()
    assert queue["reports"][0]["target_kind"] == "comment"
    assert queue["reports"][0]["comment_id"] == comment_id
    dismissed = client.post(
        f"/api/prints/moderation/reports/{queue['reports'][0]['id']}/dismiss",
        json={"resolution": "One-off, warned."},
        headers=auth_headers(moderator),
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"


# -- maker links ------------------------------------------------------------------


def test_maker_links_crud_and_validation(client, publisher, fake_storage):
    bad = client.post(
        "/api/prints/me/links",
        json={"label": "Files", "url": "javascript:alert(1)"},
        headers=auth_headers(publisher),
    )
    assert bad.status_code == 422
    made = client.post(
        "/api/prints/me/links",
        json={"label": "MakerWorld", "url": "https://makerworld.com/@pete"},
        headers=auth_headers(publisher),
    )
    assert made.status_code == 201, made.text
    link_id = made.json()["id"]
    _publish(client, publisher)
    detail = client.get("/api/prints/files").json()
    file_id = detail["files"][0]["id"]
    page = client.get(f"/api/prints/files/{file_id}").json()
    assert page["maker_links"][0]["url"] == "https://makerworld.com/@pete"

    updated = client.put(
        f"/api/prints/me/links/{link_id}",
        json={"label": "Printables", "url": "https://www.printables.com/@pete"},
        headers=auth_headers(publisher),
    )
    assert updated.json()["label"] == "Printables"
    mine = client.get("/api/prints/me/files", headers=auth_headers(publisher))
    assert mine.json()["files"][0]["id"] == file_id
    gone = client.request(
        "DELETE",
        f"/api/prints/me/links/{link_id}",
        headers=auth_headers(publisher),
    )
    assert gone.status_code == 200


# -- gates -------------------------------------------------------------------------


def test_module_off_closes_writes_and_reads(
    client, db, publisher, fake_storage, monkeypatch
):
    from app.modules.core import module_control

    file_id = _publish(client, publisher).json()["id"]
    monkeypatch.setattr(
        module_control, "globally_enabled", lambda db_, mid: mid != "prints"
    )
    assert client.get("/api/prints/files").status_code == 404
    blocked = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 4},
        headers=auth_headers(publisher),
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "module_unavailable"


def test_community_block_closes_publish_doors(
    client, db, publisher, mod_admin, fake_storage
):
    file_id = _publish(client, publisher).json()["id"]
    community_blocks.block_user(
        db,
        mod_admin,
        user_id=publisher.id,
        feature="print_files",
        reason="Repeated off-topic uploads.",
    )
    assert community_blocks.is_blocked(db, publisher.id, "print_files")
    resp = _publish(client, publisher, title="Another one")
    assert resp.status_code == 403
    comment = client.post(
        f"/api/prints/files/{file_id}/comments",
        json={"body": "hello"},
        headers=auth_headers(publisher),
    )
    assert comment.status_code == 403
    # Rating someone else's file is not a posting door — the
    # block doesn't reach it (the forum's posture).
    rated = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 1},
        headers=auth_headers(publisher),
    )
    assert rated.status_code == 422  # own file — refused on that ground, not the block


def test_global_search_finds_print_files(client, db, publisher, reader, fake_storage):
    _publish(client, publisher, title="Magnetic parts tray")
    resp = client.get(
        "/api/core/search",
        params={"q": "magnetic tray"},
        headers=auth_headers(reader),
    )
    assert resp.status_code == 200, resp.text
    groups = {g["key"]: g for g in resp.json()["groups"]}
    assert "prints" in groups
    hit = groups["prints"]["results"][0]
    assert hit["link"].startswith("/3dprints/")
    assert hit["kind"] == "print_file"
    assert hit["title"] == "Magnetic parts tray"
