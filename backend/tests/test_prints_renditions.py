"""3D Print Files photo renditions (prints thumbnails lane,
2026-11-10): browse cards and the detail gallery served each
photo's FULL original bytes (the one live cover: 3.2 MB at
5712×4284 into a small card). Proven here against the real
routes with storage faked at the storage object (the prints
suite's pattern) and REAL decodable JPEGs, so the rendition
pipeline (the inventory thumbs machinery, reused) runs end
to end:

- publishing / adding / versioning a photo generates its
  card (320) + display (1600) renditions at upload, under
  the derived keys, and NEVER touches the original bytes;
- /preview serves the card rendition (display on request),
  /media serves the display rendition for photos;
- a listing with no renditions (legacy) regenerates on read;
- a photo that can't be decoded falls back to its original
  bytes at both doors — never a broken image;
- removing a photo removes its renditions with it;
- a video's bytes and range serving are untouched;
- the backfill script is dry-run-safe and idempotent.
"""

import io
import struct
import uuid

import pytest
from PIL import Image

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.prints import renditions
from app.scripts import backfill_print_renditions
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
            raise storage_module.StorageError(f"missing: {key}")
        return self.objects[key]

    def head(self, key):
        if key not in self.objects:
            raise storage_module.StorageError(f"missing: {key}")
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
    return _make_user(db, "TV-M-002201", "rpub@example.com", name="Ren Maker")


def _stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 50


def _jpeg(width=2400, height=1800, seed=7):
    """A REAL camera-like JPEG: noise so it compresses like a
    photo (a flat color would shrink to nothing and prove
    nothing about sizes)."""
    image = Image.effect_noise((width, height), 110).convert("RGB")
    # A deterministic tint per seed so two photos differ.
    tint = Image.new("RGB", (width, height), (seed * 30 % 255, 40, 90))
    image = Image.blend(image, tint, 0.25)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def _fake_png():
    """Magic-header PNG the validator accepts but Pillow
    can't decode — the fallback fixture."""
    return b"\x89PNG\r\n\x1a\n" + b"\x07" * 64


def _mp4(seconds=5):
    timescale = 600
    units = int(round(seconds * timescale))
    content = (
        b"\x00" * 4
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


def _publish(client, user, *, photo=None, photo_name="cover.jpg",
             photo_type="image/jpeg", title="Rendition mount"):
    files = {"print_file": ("mount.stl", _stl(), "application/octet-stream")}
    if photo is not None:
        files["preview"] = (photo_name, photo, photo_type)
    resp = client.post(
        "/api/prints/files",
        data={"title": title, "description": "Holds things.",
              "category": "shop-fixtures"},
        files=files,
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _dims(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def _variant_keys(fake, key):
    return (
        renditions.variant_key(key, renditions.CARD_WIDTH),
        renditions.variant_key(key, renditions.DISPLAY_WIDTH),
    )


def _drop_variants(fake):
    for key in [k for k in fake.objects if ".thumb" in k]:
        del fake.objects[key]


# -- generation at upload -------------------------------------------------


def test_publish_generates_renditions_and_keeps_original(
    client, publisher, fake_storage
):
    photo = _jpeg()
    assert len(photo) > 500_000  # the fixture is honestly photo-sized
    _publish(client, publisher, photo=photo)
    # The cover's storage key: the single photo object stored.
    photo_keys = [
        k for k in fake_storage.objects
        if k.endswith("cover.jpg") and ".thumb" not in k
    ]
    assert len(photo_keys) == 1
    key = photo_keys[0]
    # The original is byte-identical — never modified.
    assert fake_storage.objects[key] == photo
    card_key, display_key = _variant_keys(fake_storage, key)
    assert card_key in fake_storage.objects
    assert display_key in fake_storage.objects
    assert _dims(fake_storage.objects[card_key]) == (320, 240)
    assert _dims(fake_storage.objects[display_key]) == (1600, 1200)
    assert len(fake_storage.objects[card_key]) < len(photo) // 10
    assert len(fake_storage.objects[display_key]) < len(photo) // 3


def test_add_photo_generates_renditions(client, publisher, fake_storage):
    detail = _publish(client, publisher, photo=_jpeg(seed=1))
    file_id = detail["id"]
    resp = client.post(
        f"/api/prints/files/{file_id}/media/photos",
        files={"photo": ("second.jpg", _jpeg(seed=2), "image/jpeg")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    added = [
        k for k in fake_storage.objects
        if k.endswith("second.jpg") and ".thumb" not in k
    ]
    assert len(added) == 1
    card_key, display_key = _variant_keys(fake_storage, added[0])
    assert card_key in fake_storage.objects
    assert display_key in fake_storage.objects


def test_version_photo_becomes_cover_with_renditions(
    client, publisher, fake_storage
):
    detail = _publish(client, publisher, photo=_jpeg(seed=3))
    file_id = detail["id"]
    new_cover = _jpeg(seed=4)
    resp = client.post(
        f"/api/prints/files/{file_id}/versions",
        data={"note": "v2"},
        files={
            "print_file": ("mount.stl", _stl(), "application/octet-stream"),
            "preview": ("newcover.jpg", new_cover, "image/jpeg"),
        },
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 201, resp.text
    keys = [
        k for k in fake_storage.objects
        if k.endswith("newcover.jpg") and ".thumb" not in k
    ]
    assert len(keys) == 1
    card_key, display_key = _variant_keys(fake_storage, keys[0])
    assert card_key in fake_storage.objects
    assert display_key in fake_storage.objects
    # And the card door now serves the NEW cover's rendition.
    resp = client.get(f"/api/prints/files/{file_id}/preview")
    assert resp.status_code == 200
    assert resp.content == fake_storage.objects[card_key]


# -- the read doors ---------------------------------------------------------


def test_preview_serves_card_then_display(client, publisher, fake_storage):
    photo = _jpeg()
    detail = _publish(client, publisher, photo=photo)
    file_id = detail["id"]

    card = client.get(f"/api/prints/files/{file_id}/preview")
    assert card.status_code == 200
    assert card.headers["content-type"].startswith("image/jpeg")
    assert _dims(card.content) == (320, 240)
    assert len(card.content) < len(photo) // 10

    display = client.get(f"/api/prints/files/{file_id}/preview?size=display")
    assert display.status_code == 200
    assert _dims(display.content) == (1600, 1200)
    assert len(display.content) > len(card.content)
    assert len(display.content) < len(photo) // 3

    # A nonsense size falls back to the card, never an error.
    odd = client.get(f"/api/prints/files/{file_id}/preview?size=huge")
    assert odd.status_code == 200
    assert odd.content == card.content


def test_media_photo_serves_display_rendition(client, publisher, fake_storage):
    photo = _jpeg()
    detail = _publish(client, publisher, photo=photo)
    media_id = detail["media"][0]["id"]
    resp = client.get(f"/api/prints/files/{detail['id']}/media/{media_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert _dims(resp.content) == (1600, 1200)
    assert len(resp.content) < len(photo) // 3


def test_legacy_listing_regenerates_on_read(client, publisher, fake_storage):
    photo = _jpeg()
    detail = _publish(client, publisher, photo=photo)
    file_id = detail["id"]
    _drop_variants(fake_storage)  # a pre-renditions listing
    resp = client.get(f"/api/prints/files/{file_id}/preview")
    assert resp.status_code == 200
    assert _dims(resp.content) == (320, 240)
    assert len(resp.content) < len(photo) // 10
    # ...and the rendition is cached for the next read.
    assert any(".thumb320" in k for k in fake_storage.objects)


def test_undecodable_photo_falls_back_to_original(
    client, publisher, fake_storage
):
    photo = _fake_png()
    detail = _publish(
        client, publisher, photo=photo,
        photo_name="cover.png", photo_type="image/png",
    )
    file_id = detail["id"]
    resp = client.get(f"/api/prints/files/{file_id}/preview")
    assert resp.status_code == 200
    assert resp.content == photo
    assert resp.headers["content-type"].startswith("image/png")
    media_id = detail["media"][0]["id"]
    resp = client.get(f"/api/prints/files/{file_id}/media/{media_id}")
    assert resp.status_code == 200
    assert resp.content == photo


def test_remove_media_deletes_renditions(client, publisher, fake_storage):
    detail = _publish(client, publisher, photo=_jpeg(seed=5))
    file_id = detail["id"]
    resp = client.post(
        f"/api/prints/files/{file_id}/media/photos",
        files={"photo": ("extra.jpg", _jpeg(seed=6), "image/jpeg")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    media_id = resp.json()["media"][-1]["id"]
    key = [
        k for k in fake_storage.objects
        if k.endswith("extra.jpg") and ".thumb" not in k
    ][0]
    card_key, display_key = _variant_keys(fake_storage, key)
    assert card_key in fake_storage.objects

    resp = client.delete(
        f"/api/prints/files/{file_id}/media/{media_id}",
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    assert key not in fake_storage.objects
    assert card_key not in fake_storage.objects
    assert display_key not in fake_storage.objects


def test_video_media_bytes_and_range_untouched(client, publisher, fake_storage):
    detail = _publish(client, publisher, photo=_jpeg(seed=8))
    file_id = detail["id"]
    video = _mp4(5)
    resp = client.post(
        f"/api/prints/files/{file_id}/media/video",
        files={"video": ("clip.mp4", video, "application/octet-stream")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    media_id = resp.json()["media"][-1]["id"]
    full = client.get(f"/api/prints/files/{file_id}/media/{media_id}")
    assert full.status_code == 200
    assert full.content == video
    ranged = client.get(
        f"/api/prints/files/{file_id}/media/{media_id}",
        headers={"Range": "bytes=0-9"},
    )
    assert ranged.status_code == 206
    assert ranged.content == video[:10]


# -- the backfill -----------------------------------------------------------


def test_backfill_dry_run_then_generate_then_noop(
    client, db, publisher, fake_storage
):
    _publish(client, publisher, photo=_jpeg(seed=9))
    detail2 = _publish(client, publisher, photo=_jpeg(seed=10),
                       title="Second mount")
    resp = client.post(
        f"/api/prints/files/{detail2['id']}/media/photos",
        files={"photo": ("extra.jpg", _jpeg(seed=11), "image/jpeg")},
        headers=auth_headers(publisher),
    )
    assert resp.status_code == 200, resp.text
    _drop_variants(fake_storage)  # everything is legacy now

    dry = backfill_print_renditions.run(db, dry_run=True)
    assert dry["keys"] == 3  # cover A, cover B, extra photo
    assert dry["would_generate"] == 6  # 3 keys × card + display
    assert dry["generated"] == 0
    assert not any(".thumb" in k for k in fake_storage.objects)

    done = backfill_print_renditions.run(db)
    assert done["generated"] == 6
    assert done["failed"] == 0
    assert sum(1 for k in fake_storage.objects if ".thumb" in k) == 6

    again = backfill_print_renditions.run(db)
    assert again["generated"] == 0
    assert again["already_present"] == 6
