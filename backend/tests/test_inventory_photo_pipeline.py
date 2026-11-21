"""Deep audit Round B (F1-04/F1-05/F3-12): the photo pipeline.

Pins:
  * the DEFAULT ("featured") server sort puts items WITH photos
    first (newest first inside each group), while an explicit
    user sort keeps its own convention;
  * attachment serialization mints signed thumb URLs for photos
    only;
  * thumb signatures verify, expire and reject tampering, and a
    rendition is generated once then served from the stored
    variant (resize-on-read with a storage cache).
"""

import io
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from app.modules.core import models as core_models
from app.modules.inventory import models as inv_models
from app.modules.inventory import search, service, thumbs

MECHANIC = "mechanic_technician"
BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture()
def owner(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000902",
        email="photo-owner@example.com",
        name="Photo User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _tool(db, owner, name, *, days, photo=False):
    tool = inv_models.Tool(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name=name,
        updated_at=BASE + timedelta(days=days),
        created_at=BASE + timedelta(days=days),
        attachments=(
            [{"key": f"k/{name}.jpg", "kind": "photo", "content_type": "image/jpeg"}]
            if photo
            else []
        ),
    )
    db.add(tool)
    db.commit()
    return tool


def test_featured_sort_puts_photos_first(db, owner):
    _tool(db, owner, "newest-nophoto", days=30)
    _tool(db, owner, "older-photo", days=5, photo=True)
    _tool(db, owner, "newer-photo", days=20, photo=True)
    _tool(db, owner, "oldest-nophoto", days=1)

    rows, total = search.search_tools_paged(
        db, owner.id, limit=50, offset=0, sort="featured"
    )
    assert total == 4
    assert [r.name for r in rows] == [
        "newer-photo",
        "older-photo",
        "newest-nophoto",
        "oldest-nophoto",
    ]

    # An explicit user sort is untouched by the default ordering.
    rows, _ = search.search_tools_paged(
        db, owner.id, limit=50, offset=0, sort="name"
    )
    assert [r.name for r in rows] == [
        "newer-photo",
        "newest-nophoto",
        "older-photo",
        "oldest-nophoto",
    ]


def test_serializer_mints_thumb_urls_for_photos_only():
    record = SimpleNamespace(
        attachments=[
            {"key": "a/p.jpg", "kind": "photo", "content_type": "image/jpeg",
             "filename": "p.jpg", "size_bytes": 10},
            {"key": "a/r.pdf", "kind": "receipt", "content_type": "application/pdf",
             "filename": "r.pdf", "size_bytes": 10},
        ]
    )
    views = service._serialize_attachments(record)  # noqa: SLF001
    assert views[0]["thumb_url"].startswith("/api/inventory/thumb/320?")
    assert views[0]["thumb_url_sm"].startswith("/api/inventory/thumb/128?")
    assert views[1]["thumb_url"] is None
    assert views[1]["thumb_url_sm"] is None


def test_thumb_signature_roundtrip_and_tamper():
    url = thumbs.signed_thumb_url("owner/tools/x/photo/p.jpg", 320)
    assert url.startswith("/api/inventory/thumb/320?k=")
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(url).query)
    key, expires, sig = qs["k"][0], int(qs["e"][0]), qs["s"][0]
    assert thumbs.verify(key, 320, expires, sig)
    assert not thumbs.verify(key, 128, expires, sig)  # width is signed
    assert not thumbs.verify(key, 320, expires, "0" * 64)
    assert not thumbs.verify(key, 320, 1, sig)  # expired shape fails via sig
    assert not thumbs.verify(key, 999, expires, sig)  # width allowlist


def test_rendition_generates_then_caches(monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (700, 1400), (200, 60, 30)).save(buf, "JPEG")
    original = buf.getvalue()
    store: dict[str, bytes] = {"owner/tools/x/photo/p.jpg": original}
    puts: list[str] = []

    def fake_fetch(key):
        if key not in store:
            from app.core.storage import StorageError

            raise StorageError("missing")
        return store[key]

    def fake_put(key, data, _ct):
        store[key] = data
        puts.append(key)
        return SimpleNamespace(key=key, size_bytes=len(data), content_type="image/jpeg")

    monkeypatch.setattr(thumbs.storage, "fetch", fake_fetch)
    monkeypatch.setattr(thumbs.storage, "put_bytes", fake_put)

    data = thumbs.rendition("owner/tools/x/photo/p.jpg", 128)
    assert data is not None and len(data) < len(original)
    with Image.open(io.BytesIO(data)) as img:
        assert max(img.size) <= 128  # whole portrait, scaled — not cropped
        assert img.size[1] > img.size[0]  # portrait stays portrait
    assert puts == ["owner/tools/x/photo/p.jpg.thumb128.jpg"]

    # Second read is served from the stored variant, no re-encode.
    puts.clear()
    again = thumbs.rendition("owner/tools/x/photo/p.jpg", 128)
    assert again == store["owner/tools/x/photo/p.jpg.thumb128.jpg"]
    assert puts == []
