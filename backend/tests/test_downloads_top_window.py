"""The top-downloads window (dashboard-flare lane, owner
order 2026-11-09): the Downloads widget's "top downloads this
week" strip reads a DATED event record (0098), never the
cumulative counters — so this file proves the record is what
moves:

- a counted download writes exactly one event, in step with
  the counter (documents by their key; a wallpaper's sizes as
  their size keys);
- GET /api/downloads/top-window ranks by downloads INSIDE the
  last 7 days, folds a wallpaper's size keys onto the artwork,
  and reports when tracking began;
- an event older than the window does not rank (but it does
  start the tracking clock — the record is honest about its
  own age);
- with no events at all the answer is an empty list and a
  null tracking_since, not a dressed-up all-time chart.
"""

from datetime import datetime, timedelta, timezone

from app.modules.downloads import catalog as catalog_def
from app.modules.downloads.models import DownloadEvent

_DOC = catalog_def.CATALOG[0]
_WALLPAPER = catalog_def.WALLPAPERS[0]


def _download(client, key):
    res = client.get(f"/api/downloads/files/{key}")
    assert res.status_code == 200, res.text


def test_top_window_ranks_the_week(client, db):
    _download(client, _DOC.key)
    _download(client, _DOC.key)
    _download(client, f"{_WALLPAPER.key}-desktop")
    _download(client, f"{_WALLPAPER.key}-mobile")

    res = client.get("/api/downloads/top-window")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["window_days"] == 7
    assert body["tracking_since"] is not None
    items = {(i["key"], i["kind"]): i["count"] for i in body["items"]}
    assert items[(_DOC.key, "document")] == 2
    # Two sizes of one artwork fold into ONE wallpaper entry.
    assert items[(_WALLPAPER.key, "wallpaper")] == 2
    # Ranked: both at 2 — order between equals is by key, so
    # only the multiset is pinned here.
    assert sorted(i["count"] for i in body["items"]) == [2, 2]

    # The event record moved in step with the counters:
    # exactly one event per counted download.
    assert db.query(DownloadEvent).count() == 4


def test_top_window_ignores_events_older_than_the_window(client, db):
    old = datetime.now(timezone.utc) - timedelta(days=10)
    db.add(DownloadEvent(file_key=_DOC.key, created_at=old))
    db.commit()

    _download(client, f"{_WALLPAPER.key}-tablet")
    res = client.get("/api/downloads/top-window")
    assert res.status_code == 200, res.text
    body = res.json()
    items = {(i["key"], i["kind"]): i["count"] for i in body["items"]}
    # The old download does not rank...
    assert (_DOC.key, "document") not in items
    assert items[(_WALLPAPER.key, "wallpaper")] == 1
    # ...but the record's age is reported truthfully.
    tracked = datetime.fromisoformat(body["tracking_since"])
    if tracked.tzinfo is None:  # sqlite round-trips the stamp naive
        tracked = tracked.replace(tzinfo=timezone.utc)
    assert tracked <= old + timedelta(seconds=5)


def test_top_window_empty_record(client):
    res = client.get("/api/downloads/top-window")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == []
    assert body["tracking_since"] is None
