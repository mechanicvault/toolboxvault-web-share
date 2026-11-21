"""Sheet row 83: /sitemap.xml is generated from the public
surface — the standing public pages plus every live, public
3D print file — and nothing members-only leaks into it."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.prints import models as prints_models


def _print_file(db, user, **overrides):
    row = prints_models.PrintFile(
        id=uuid.uuid4(),
        publisher_id=user.id,
        title="Sitemap probe file",
        description="",
        category_key="tool-holders",
        status="live",
        is_public=True,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_sitemap_lists_the_standing_public_pages(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    for path in ("/", "/landing", "/downloads", "/3dprints"):
        assert f"<loc>https://toolboxvault.com{path}</loc>" in body


def test_sitemap_includes_public_print_files_only(client, db, user_a):
    public = _print_file(db, user_a)
    _print_file(db, user_a, is_public=False)
    _print_file(db, user_a, status="removed")
    body = client.get("/sitemap.xml").text
    assert f"<loc>https://toolboxvault.com/3dprints/{public.id}</loc>" in body
    assert body.count("/3dprints/") == 1
    # The file's own lastmod rides along, and the shelf entry
    # takes the newest public file's date.
    assert "<lastmod>2026-11-10</lastmod>" in body


def test_sitemap_is_well_formed_xml(client, db, user_a):
    import xml.etree.ElementTree as ET

    _print_file(db, user_a)
    root = ET.fromstring(client.get("/sitemap.xml").text)
    assert root.tag.endswith("urlset")
    locs = [el.text for el in root.iter() if el.tag.endswith("loc")]
    assert len(locs) == 5  # 4 standing pages + the one public file
