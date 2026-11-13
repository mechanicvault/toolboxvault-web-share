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

from PIL import Image
from sqlalchemy import select

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
    # pieces all live in Abstract).
    assert len(wallpapers) == 60
    branded = [w for w in wallpapers if w["branded"]]
    assert len(branded) == 10
    assert len(wallpapers) - len(branded) == 50
    assert branded[0]["key"] == "brand-cabinet-wall-cover"
    for removed in (
        "brand-navy-pegboard",
        "brand-drawer-front",
        "brand-steel-wall",
    ):
        assert removed not in catalog_def.WALLPAPERS_BY_KEY
    general = [w for w in wallpapers if not w["branded"]]
    # The depth pieces (Sweep E2) close the general shelf now;
    # corvette-c8 still closes the original car run.
    assert general[-1]["key"] == "tech-cnc-mill"
    assert general[33]["key"] == "corvette-c8"
    # Categories (Sweep E2): exactly one per piece, from the
    # fixed set, branded pieces in Abstract, 10+ per category.
    from collections import Counter

    counts = Counter(w["category"] for w in wallpapers)
    assert set(counts) == set(catalog_def.WALLPAPER_CATEGORIES)
    assert all(n >= 10 for n in counts.values()), counts
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
    # The pieces the owner removed (Sweep E2) are gone end to
    # end: no view, no counted download, in any size.
    for removed in (
        "brand-navy-pegboard",
        "brand-drawer-front",
        "brand-steel-wall",
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
