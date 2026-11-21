"""Downloads wallpaper shelf (Downloads Part 3, owner order
2026-11-08): one artwork, three device sizes, all public.

Proves:
- the shelf lists every artwork in shelf order, branded
  flags intact, each with its three sizes at their honest
  labelled dimensions and zeroed counts;
- the Documents shelf (/catalog) still lists exactly the
  nine documents — wallpaper rows share the table (they ride
  the same counted path) but never leak into the list;
- the views (thumbnail + device-size previews) serve the
  packaged bytes inline as image/jpeg and move NO counter —
  looking is not downloading;
- a size download rides /files/{key}-{size}: right bytes,
  right media type, friendly filename, and exactly that
  size's count (and the artwork's total) moves by one;
- unknown artwork/size/view is a plain 404;
- every packaged file (3 sizes + thumbnail per artwork)
  exists and really is the labelled pixel size — the art
  pipeline is pinned by the same numbers the gallery shows.
"""

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.core import storage as storage_module
from app.core.storage import StorageError, StoredObject
from app.modules.downloads import catalog as catalog_def
from app.modules.downloads import service
from app.modules.downloads.models import DownloadFile

_FILES_DIR = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
    / "downloads"
    / "files"
    / "wallpapers"
)


def test_wallpaper_shelf_lists_every_artwork(client):
    res = client.get("/api/downloads/wallpapers")
    assert res.status_code == 200
    wallpapers = res.json()["wallpapers"]
    assert [w["key"] for w in wallpapers] == [
        entry.key for entry in catalog_def.WALLPAPERS
    ]
    # Exact shelf composition (Sweep E2, 2026-11-12: the owner
    # removed brand-navy-pegboard, brand-drawer-front and
    # brand-steel-wall, and 16 depth pieces joined — 7 engines
    # + 9 high tech — so every category holds 10+; the branded
    # pieces all live in Abstract. Row 157, 2026-11-19: the 12
    # dealer pieces joined under their own Dealers category.)
    assert len(wallpapers) == 68
    branded = [w for w in wallpapers if w["branded"]]
    assert len(branded) == 8
    assert len(wallpapers) - len(branded) == 60
    assert branded[0]["key"] == "brand-cabinet-wall-cover"
    for removed in (
        "brand-navy-pegboard",
        "brand-drawer-front",
        "brand-steel-wall",
        "impact-wrench-macro",
        "tool-truck-dawn",
        "brand-doorway-dawn",
        "brand-steel-door",
    ):
        assert removed not in catalog_def.WALLPAPERS_BY_KEY
    general = [w for w in wallpapers if not w["branded"]]
    # The dealer pieces (row 157) close the general shelf now;
    # corvette-c8 still closes the original car run.
    assert general[-1]["key"] == "cornwell-heritage-emblem"
    assert general[31]["key"] == "corvette-c8"
    # Categories (Sweep E2): exactly one per piece, from the
    # fixed set, branded pieces in Abstract. The 10+ floor held
    # until the owner's 2026-11-19 removals took Abstract to 8.
    from collections import Counter

    counts = Counter(w["category"] for w in wallpapers)
    assert set(counts) == set(catalog_def.WALLPAPER_CATEGORIES)
    assert all(n >= 8 for n in counts.values()), counts
    for w in wallpapers:
        entry = catalog_def.WALLPAPERS_BY_KEY[w["key"]]
        assert w["branded"] == entry.branded
        assert w["category"] == entry.category
        if w["branded"]:
            assert w["category"] == "abstract"
        assert w["download_count"] == 0
        assert [s["size"] for s in w["sizes"]] == list(
            catalog_def.WALLPAPER_SIZES
        )
        for s in w["sizes"]:
            assert (s["width"], s["height"]) == (
                catalog_def.WALLPAPER_SIZE_DIMS[s["size"]]
            )
            assert s["download_count"] == 0


def test_wallpapers_never_leak_into_the_documents_shelf(client):
    client.get("/api/downloads/wallpapers")
    res = client.get("/api/downloads/catalog")
    assert res.status_code == 200
    files = res.json()["files"]
    assert [f["key"] for f in files] == [
        entry.key for entry in catalog_def.CATALOG
    ]
    assert len(files) == 9


def test_view_serves_packaged_bytes_and_counts_nothing(client, db):
    key = catalog_def.WALLPAPERS[0].key
    res = client.get(f"/api/downloads/wallpapers/{key}/view/thumb")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content == (_FILES_DIR / f"{key}-thumb.jpg").read_bytes()
    res = client.get(f"/api/downloads/wallpapers/{key}/view/desktop")
    assert res.status_code == 200
    assert res.content == (_FILES_DIR / f"{key}-desktop.jpg").read_bytes()
    total = sum(
        row.download_count for row in db.scalars(select(DownloadFile)).all()
    )
    assert total == 0


def test_size_download_counts_that_size_and_the_total(client, db):
    key = catalog_def.WALLPAPERS[0].key
    res = client.get(f"/api/downloads/files/{key}-tablet")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    entry = catalog_def.BY_KEY[f"{key}-tablet"]
    assert res.headers["content-disposition"] == (
        f'attachment; filename="{entry.filename}"'
    )
    assert res.content == (_FILES_DIR / f"{key}-tablet.jpg").read_bytes()

    shelf = {
        w["key"]: w
        for w in client.get("/api/downloads/wallpapers").json()["wallpapers"]
    }
    assert shelf[key]["download_count"] == 1
    sizes = {s["size"]: s["download_count"] for s in shelf[key]["sizes"]}
    assert sizes == {"desktop": 0, "tablet": 1, "mobile": 0}
    others = [w for k, w in shelf.items() if k != key]
    assert all(w["download_count"] == 0 for w in others)


def test_unknown_wallpaper_routes_are_404(client):
    assert client.get("/api/downloads/wallpapers/nope/view/thumb").status_code == 404
    # The pieces the owner removed (Sweep E2, plus the four
    # removed 2026-11-19) are gone end to end: no view, no
    # counted download, in any size.
    for removed in (
        "brand-navy-pegboard",
        "brand-drawer-front",
        "brand-steel-wall",
        "impact-wrench-macro",
        "tool-truck-dawn",
        "brand-doorway-dawn",
        "brand-steel-door",
    ):
        assert (
            client.get(f"/api/downloads/wallpapers/{removed}/view/thumb").status_code
            == 404
        )
        assert (
            client.get(f"/api/downloads/files/{removed}-desktop").status_code == 404
        )
    key = catalog_def.WALLPAPERS[0].key
    assert (
        client.get(f"/api/downloads/wallpapers/{key}/view/huge").status_code
        == 404
    )
    assert client.get(f"/api/downloads/files/{key}-huge").status_code == 404


def test_packaged_wallpapers_match_their_labelled_sizes():
    for entry in catalog_def.WALLPAPERS:
        for size in catalog_def.WALLPAPER_SIZES:
            path = _FILES_DIR / f"{entry.key}-{size}.jpg"
            assert path.exists(), f"missing packaged file {path.name}"
            with Image.open(path) as img:
                assert img.size == catalog_def.WALLPAPER_SIZE_DIMS[size], (
                    f"{path.name} is {img.size}, labelled "
                    f"{catalog_def.WALLPAPER_SIZE_DIMS[size]}"
                )
                assert img.format == "JPEG"
        thumb = _FILES_DIR / f"{entry.key}-thumb.jpg"
        assert thumb.exists(), f"missing thumbnail {thumb.name}"
        with Image.open(thumb) as img:
            assert img.size == (640, 400)


class _FakeStorage:
    """In-memory stand-in for the storage service, following
    the suite's fake-storage pattern: an objects dict plus a
    record of every put, so a test can prove whether a re-seed
    happened."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def head(self, key):
        if key not in self.objects:
            raise StorageError("Uploaded file not found in storage")
        return StoredObject(
            key=key, size_bytes=len(self.objects[key]), content_type="image/jpeg"
        )

    def fetch(self, key):
        if key not in self.objects:
            raise StorageError("Uploaded file not found in storage")
        return self.objects[key]

    def put_bytes(self, key, data, content_type):
        self.puts.append(key)
        self.objects[key] = data
        return StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )


@pytest.fixture()
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    for name in ("put_bytes", "fetch", "head"):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    # The service confirms each storage key at most once per
    # process; start every storage test with a clean slate.
    service._storage_ready.clear()
    yield fake
    service._storage_ready.clear()


def test_stale_storage_object_is_reseeded_from_the_package(
    client, fake_storage
):
    """The Charger case (2026-11-12): an artwork redone in
    place keeps its storage key, so the object storage seeded
    from the OLD package still answers head() — presence is
    not currency. The serve must notice the drift, re-seed
    from the package, and hand back the packaged (new) bytes
    on both the uncounted view and the counted download."""
    key = "dodge-charger-modern"
    thumb_storage_key = f"downloads/wallpapers/{key}-thumb.jpg"
    desktop_storage_key = f"downloads/wallpapers/{key}-desktop.jpg"
    fake_storage.objects[thumb_storage_key] = b"the-old-charger-art"
    fake_storage.objects[desktop_storage_key] = b"the-old-charger-art"

    res = client.get(f"/api/downloads/wallpapers/{key}/view/thumb")
    assert res.status_code == 200
    assert res.content == (_FILES_DIR / f"{key}-thumb.jpg").read_bytes()
    assert fake_storage.objects[thumb_storage_key] == res.content

    res = client.get(f"/api/downloads/files/{key}-desktop")
    assert res.status_code == 200
    assert res.content == (_FILES_DIR / f"{key}-desktop.jpg").read_bytes()
    assert fake_storage.objects[desktop_storage_key] == res.content
    assert fake_storage.puts == [thumb_storage_key, desktop_storage_key]


def test_current_storage_object_is_not_rewritten(client, fake_storage):
    """When the stored object already IS the packaged bytes,
    the serve leaves storage untouched — the drift check is a
    comparison, not a rewrite-on-every-boot."""
    key = "dodge-charger-modern"
    thumb_storage_key = f"downloads/wallpapers/{key}-thumb.jpg"
    packaged = (_FILES_DIR / f"{key}-thumb.jpg").read_bytes()
    fake_storage.objects[thumb_storage_key] = packaged

    res = client.get(f"/api/downloads/wallpapers/{key}/view/thumb")
    assert res.status_code == 200
    assert res.content == packaged
    assert fake_storage.puts == []


def test_missing_storage_object_is_seeded_from_the_package(
    client, fake_storage
):
    key = catalog_def.WALLPAPERS[0].key
    thumb_storage_key = f"downloads/wallpapers/{key}-thumb.jpg"
    res = client.get(f"/api/downloads/wallpapers/{key}/view/thumb")
    assert res.status_code == 200
    assert res.content == (_FILES_DIR / f"{key}-thumb.jpg").read_bytes()
    assert fake_storage.objects[thumb_storage_key] == res.content


def test_ensure_wallpapers_is_idempotent_and_keeps_counts(db):
    service.ensure_wallpapers(db)
    service.ensure_wallpapers(db)
    rows = db.scalars(select(DownloadFile)).all()
    assert len(rows) == len(catalog_def.WALLPAPER_SIZE_ENTRIES)
    key = f"{catalog_def.WALLPAPERS[0].key}-mobile"
    row = next(r for r in rows if r.key == key)
    row.download_count = 4
    db.commit()
    service.ensure_wallpapers(db)
    db.expire_all()
    row = db.scalars(
        select(DownloadFile).where(DownloadFile.key == key)
    ).first()
    assert row.download_count == 4
