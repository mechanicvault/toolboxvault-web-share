"""3D Print Files showcase media + listing edit (owner
orders 2026-11-08 21:31–23:44): up to 5 photos and ONE video
(30 seconds max, the length VERIFIED on the server from the
container's own bytes) belong to the LISTING; the publisher
edits the listing (text + media) without ever moving the
file version. Proven against the real routes with storage
faked at the storage object (the prints suite's pattern).
"""

import struct
import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.prints import service
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


def _make_user(db, account_number, email, *, name="Print User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def publisher(db):
    return _make_user(db, "TV-M-002101", "mpub@example.com", name="Moe Maker")


@pytest.fixture()
def reader(db):
    return _make_user(db, "TV-M-002102", "mreader@example.com", name="Rae Reader")


def _stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 50


def _png(marker=b""):
    return b"\x89PNG\r\n\x1a\n" + marker + b"\x00" * 24


def _mp4(seconds, *, version1=False):
    """A container-shaped MP4: ftyp + moov/mvhd carrying the
    given duration. No frames — the server's rule reads the
    header, and so does this fixture."""
    timescale = 600
    units = int(round(seconds * timescale))
    if version1:
        content = (
            b"\x01\x00\x00\x00"
            + b"\x00" * 16
            + struct.pack(">I", timescale)
            + struct.pack(">Q", units)
            + b"\x00" * 80
        )
    else:
        content = (
            b"\x00\x00\x00\x00"
            + b"\x00" * 8
            + struct.pack(">I", timescale)
            + struct.pack(">I", units)
            + b"\x00" * 80
        )
    mvhd = struct.pack(">I", 8 + len(content)) + b"mvhd" + content
    moov = struct.pack(">I", 8 + len(mvhd)) + b"moov" + mvhd
    ftyp = (
        struct.pack(">I", 24)
        + b"ftyp"
        + b"isom"
        + struct.pack(">I", 0x200)
        + b"isomiso2"
    )
    return ftyp + moov


def _vint(n):
    return bytes([0x80 | n])


def _webm(seconds):
    """A container-shaped WebM: EBML header (webm DocType) +
    a Segment holding Info with TimecodeScale + Duration."""
    doctype = b"\x42\x82" + _vint(4) + b"webm"
    header = b"\x1a\x45\xdf\xa3" + _vint(len(doctype)) + doctype
    scale = b"\x2a\xd7\xb1" + _vint(3) + (1_000_000).to_bytes(3, "big")
    duration = b"\x44\x89" + _vint(8) + struct.pack(">d", seconds * 1000.0)
    info_body = scale + duration
    info = b"\x15\x49\xa9\x66" + _vint(len(info_body)) + info_body
    segment = b"\x18\x53\x80\x67" + b"\xff" + info
    return header + segment


def _publish(client, user, *, photo=None, title="Media mount"):
    files = {"print_file": ("mount.stl", _stl(), "application/octet-stream")}
    if photo is not None:
        files["preview"] = ("cover.png", photo, "image/png")
    resp = client.post(
        "/api/prints/files",
        data={"title": title, "description": "Holds things.", "category": "shop-fixtures"},
        files=files,
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_photo(client, user, file_id, name, data):
    return client.post(
        f"/api/prints/files/{file_id}/media/photos",
        files={"photo": (name, data, "image/png")},
        headers=auth_headers(user),
    )


def _add_video(client, user, file_id, name, data):
    return client.post(
        f"/api/prints/files/{file_id}/media/video",
        files={"video": (name, data, "application/octet-stream")},
        headers=auth_headers(user),
    )


def _detail(client, file_id):
    resp = client.get(f"/api/prints/files/{file_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- the duration prober (the server's own measurement) -------------------


def test_video_duration_prober_reads_containers():
    assert service.probe_video_duration(_mp4(5)) == pytest.approx(5.0)
    assert service.probe_video_duration(_mp4(12.5)) == pytest.approx(12.5)
    assert service.probe_video_duration(_mp4(7, version1=True)) == pytest.approx(7.0)
    assert service.probe_video_duration(_webm(12)) == pytest.approx(12.0)
    assert service.probe_video_duration(_webm(0.5)) == pytest.approx(0.5)
    assert service.probe_video_duration(b"not a video at all") is None
    # An .mp4 costume with no movie header: unverifiable.
    impostor = struct.pack(">I", 24) + b"ftyp" + b"isom" + b"\x00" * 12
    assert service.probe_video_duration(impostor) is None


def test_validate_video_upload_rules():
    ctype, duration = service.validate_video_upload("clip.mp4", _mp4(29))
    assert ctype == "video/mp4"
    assert duration == pytest.approx(29.0)
    ctype, _ = service.validate_video_upload("clip.webm", _webm(3))
    assert ctype == "video/webm"
    with pytest.raises(service.PrintsError, match="30 seconds"):
        service.validate_video_upload("long.mp4", _mp4(35))
    with pytest.raises(service.PrintsError, match="30 seconds"):
        service.validate_video_upload("long.webm", _webm(90))
    with pytest.raises(service.PrintsError, match="couldn't be verified"):
        # A real ftyp header but no movie header anywhere:
        # the length simply can't be read off this file.
        headless = struct.pack(">I", 24) + b"ftyp" + b"qt  " + b"\x00" * 12
        service.validate_video_upload("mystery.mov", headless)
    with pytest.raises(service.PrintsError, match="must be"):
        service.validate_video_upload("notes.txt", _mp4(5))
    with pytest.raises(service.PrintsError, match="don't read as"):
        service.validate_video_upload("fake.mp4", b"plain text in a costume")


# -- photos: the publish photo is #1; the set's lifecycle -------------------


def test_publish_photo_is_first_media(client, publisher, fake_storage):
    body = _publish(client, publisher, photo=_png(b"ONE"))
    media = body["media"]
    assert len(media) == 1
    assert media[0]["kind"] == "photo"
    assert media[0]["filename"] == "cover.png"
    # Public bytes: the media door and the cover door agree.
    via_media = client.get(f"/api/prints/files/{body['id']}/media/{media[0]['id']}")
    assert via_media.status_code == 200
    assert via_media.content == _png(b"ONE")
    via_cover = client.get(f"/api/prints/files/{body['id']}/preview")
    assert via_cover.status_code == 200
    assert via_cover.content == _png(b"ONE")


def test_photo_set_lifecycle_and_cover(client, publisher, fake_storage):
    body = _publish(client, publisher)
    fid = body["id"]
    assert body["media"] == []
    assert body["has_preview"] is False

    resp = _add_photo(client, publisher, fid, "a.png", _png(b"AAA"))
    assert resp.status_code == 200, resp.text
    resp = _add_photo(client, publisher, fid, "b.png", _png(b"BBB"))
    media = resp.json()["media"]
    assert [m["filename"] for m in media] == ["a.png", "b.png"]
    # The cover is the FIRST photo.
    assert client.get(f"/api/prints/files/{fid}/preview").content == _png(b"AAA")

    # Fill to the cap: 5 in, the 6th refused in plain words.
    for name in ("c.png", "d.png", "e.png"):
        assert _add_photo(client, publisher, fid, name, _png()).status_code == 200
    sixth = _add_photo(client, publisher, fid, "f.png", _png())
    assert sixth.status_code == 422
    assert "5 photos" in sixth.json()["detail"]

    # Reorder: B to the front makes B the cover.
    media = _detail(client, fid)["media"]
    ids = [m["id"] for m in media]
    by_name = {m["filename"]: m["id"] for m in media}
    reordered = [by_name["b.png"], by_name["a.png"], ids[2], ids[3], ids[4]]
    resp = client.put(
        f"/api/prints/files/{fid}/media/order",
        json={"media_ids": reordered},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"/api/prints/files/{fid}/preview").content == _png(b"BBB")

    # A stranger in the order — or a dropped id — is refused.
    resp = client.put(
        f"/api/prints/files/{fid}/media/order",
        json={"media_ids": reordered[:-1]},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 422

    # Remove the cover: the next photo takes its place.
    resp = client.delete(
        f"/api/prints/files/{fid}/media/{by_name['b.png']}",
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200
    assert client.get(f"/api/prints/files/{fid}/preview").content == _png(b"AAA")

    # Remove every photo: the listing honestly has no picture.
    for m in list(_detail(client, fid)["media"]):
        client.delete(
            f"/api/prints/files/{fid}/media/{m['id']}",
            headers=auth_headers(publisher),
        )
    detail = _detail(client, fid)
    assert detail["media"] == []
    assert detail["has_preview"] is False
    assert client.get(f"/api/prints/files/{fid}/preview").status_code == 404


# -- the one video ----------------------------------------------------------


def test_video_lifecycle(client, publisher, fake_storage):
    body = _publish(client, publisher)
    fid = body["id"]
    resp = _add_video(client, publisher, fid, "spin.mp4", _mp4(6))
    assert resp.status_code == 200, resp.text
    media = resp.json()["media"]
    assert len(media) == 1
    video = media[0]
    assert video["kind"] == "video"
    assert video["duration_seconds"] == pytest.approx(6.0)

    # ONE video: a second is refused until the first goes.
    again = _add_video(client, publisher, fid, "again.webm", _webm(4))
    assert again.status_code == 422
    assert "already has a video" in again.json()["detail"]

    # Public bytes, plus the range a player asks for.
    got = client.get(f"/api/prints/files/{fid}/media/{video['id']}")
    assert got.status_code == 200
    assert got.content == _mp4(6)
    ranged = client.get(
        f"/api/prints/files/{fid}/media/{video['id']}",
        headers={"Range": "bytes=4-7"},
    )
    assert ranged.status_code == 206
    assert ranged.content == _mp4(6)[4:8]
    assert ranged.headers["content-range"].startswith("bytes 4-7/")

    resp = client.delete(
        f"/api/prints/files/{fid}/media/{video['id']}",
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200
    assert resp.json()["media"] == []
    # ... and a fresh video can take the seat.
    assert _add_video(client, publisher, fid, "again.webm", _webm(4)).status_code == 200


def test_video_over_limit_never_lands(client, publisher, fake_storage):
    body = _publish(client, publisher)
    fid = body["id"]
    resp = _add_video(client, publisher, fid, "long.mp4", _mp4(35))
    assert resp.status_code == 422
    assert "30 seconds" in resp.json()["detail"]
    assert _detail(client, fid)["media"] == []
    assert fake_storage.objects == {
        k: v for k, v in fake_storage.objects.items() if "/media/" not in k
    }


# -- listing edit: text moves, the version never does ------------------------


def test_listing_edit_moves_text_not_version(client, publisher, fake_storage):
    body = _publish(client, publisher, photo=_png(b"ONE"))
    fid = body["id"]
    resp = client.put(
        f"/api/prints/files/{fid}",
        json={
            "title": "Renamed mount",
            "description": "New words.",
            "category": "tool-holders",
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    edited = resp.json()
    assert edited["title"] == "Renamed mount"
    assert edited["description"] == "New words."
    assert edited["category"] == "tool-holders"
    assert edited["current_version"] == 1
    assert len(edited["versions"]) == 1
    assert edited["media"][0]["filename"] == "cover.png"

    bad = client.put(
        f"/api/prints/files/{fid}",
        json={"title": "X", "description": "", "category": "not-a-category"},
        headers=auth_headers(publisher),
    )
    assert bad.status_code == 422


def test_edit_and_media_are_the_publishers_alone(
    client, publisher, reader, fake_storage
):
    body = _publish(client, publisher)
    fid = body["id"]
    # Another member meets the same wall as a missing file.
    resp = client.put(
        f"/api/prints/files/{fid}",
        json={"title": "Hijack", "description": "", "category": "other-shop"},
        headers=auth_headers(reader),
    )
    assert resp.status_code == 404
    assert _add_photo(client, reader, fid, "x.png", _png()).status_code == 404
    assert _add_video(client, reader, fid, "x.mp4", _mp4(3)).status_code == 404
    # Signed-out writes are refused by the session gate.
    assert client.put(
        f"/api/prints/files/{fid}",
        json={"title": "Anon", "description": "", "category": "other-shop"},
    ).status_code == 401
    assert client.post(
        f"/api/prints/files/{fid}/media/photos",
        files={"photo": ("x.png", _png(), "image/png")},
    ).status_code == 401


# -- the version flow's photo seat under the set ------------------------------


def test_update_photo_becomes_cover_without_nuking_the_set(
    client, publisher, fake_storage
):
    body = _publish(client, publisher, photo=_png(b"P0"))
    fid = body["id"]
    for i in range(1, 5):
        resp = _add_photo(client, publisher, fid, f"p{i}.png", _png())
        assert resp.status_code == 200
    assert len(_detail(client, fid)["media"]) == 5

    resp = client.post(
        f"/api/prints/files/{fid}/versions",
        data={"note": "Second cut."},
        files={
            "print_file": ("mount.stl", _stl(), "application/octet-stream"),
            "preview": ("fresh.png", _png(b"NEW"), "image/png"),
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["current_version"] == 2
    photos = [m for m in detail["media"] if m["kind"] == "photo"]
    # At the cap: the new cover takes the front, the displaced
    # front photo goes, the other four stay — still five.
    assert len(photos) == 5
    assert photos[0]["filename"] == "fresh.png"
    assert client.get(f"/api/prints/files/{fid}/preview").content == _png(b"NEW")


def test_update_photo_joins_the_front_under_the_cap(
    client, publisher, fake_storage
):
    body = _publish(client, publisher, photo=_png(b"P0"))
    fid = body["id"]
    resp = client.post(
        f"/api/prints/files/{fid}/versions",
        data={"note": "Second cut."},
        files={
            "print_file": ("mount.stl", _stl(), "application/octet-stream"),
            "preview": ("fresh.png", _png(b"NEW"), "image/png"),
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text
    photos = [m for m in resp.json()["media"] if m["kind"] == "photo"]
    assert [p["filename"] for p in photos] == ["fresh.png", "cover.png"]
