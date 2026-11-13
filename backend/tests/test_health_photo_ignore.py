"""Health-check photo ignore (sweep E3, busy-work #5).

POST /api/inventory/health-check/photo-ignore sets ONE item's
per-item, photo-only, reversible ignore. The contract pinned
here:

  * THE SCAN HONORS IT — an ignored missing photo leaves the
    item's `missing` list and the photo count; the item's OTHER
    gaps (identifier, purchase date, piece serials) still flag.
  * THE DUE COUNT HONORS IT — the Home widget's read is the same
    scan, so a photo-only item ignored drops the due total to 0.
  * PHOTO-ONLY BY CONSTRUCTION — the request names no field; the
    identifier/date gaps of the same item are untouched.
  * REVERSIBLE — un-ignoring restores the photo flag exactly.
  * REVERSAL SURFACE — a photo-only ignored item is named in
    photo_ignored_items (it drops off `items`, so this list is
    where the page offers Un-ignore); it never enters total.
  * OWNER-SCOPED — another owner's item is a 404; the downloads
    level is refused at the inventory module gate.
"""

import itertools
import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.core import module_control, tiers
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(7300)


def _make_user(db, account_types=(MECHANIC,), *, tier="normal", name="Ignore Owner"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"ignore-{n}@example.com",
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        role=tiers.role_for_tier(tier),
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db)


def _tool(client, user, **payload):
    payload.setdefault("name", "Ignore wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Ignore pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _give_photo(db, kind, item_id, key):
    model = inventory_models.Tool if kind == "tool" else inventory_models.Battery
    row = db.get(model, uuid.UUID(item_id))
    row.attachments = [
        {"kind": "photo", "key": key, "filename": "p.jpg",
         "content_type": "image/jpeg"}
    ]
    db.commit()


def _ignore(client, user, kind, item_id, ignored=True):
    return client.post(
        "/api/inventory/health-check/photo-ignore",
        json={"kind": kind, "item_id": item_id, "ignored": ignored},
        headers=auth_headers(user),
    )


def _scan(client, user):
    resp = client.get("/api/inventory/health-check", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _due(client, user):
    resp = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_ignore_drops_photo_only_item_from_scan_and_due(client, owner, db):
    # Complete except for the photo: the photo is its ONLY gap.
    tool = _tool(
        client, owner, name="Photo only", model="M1", serial_number="S1",
        purchase_date="2026-01-15",
    )
    scan = _scan(client, owner)
    assert scan["total"] == 1 and scan["counts"]["photo"] == 1

    resp = _ignore(client, owner, "tool", tool["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["photo_ignored"] is True

    scan = _scan(client, owner)
    assert scan["total"] == 0 and scan["items"] == []
    assert scan["counts"]["photo"] == 0
    # …but the reversal surface names it, and the due count agrees.
    assert [r["name"] for r in scan["photo_ignored_items"]] == ["Photo only"]
    due = _due(client, owner)
    assert due["total"] == 0 and due["counts"]["photo"] == 0

    # Reversible: un-ignore restores the flag and the due count.
    resp = _ignore(client, owner, "tool", tool["id"], ignored=False)
    assert resp.status_code == 200 and resp.json()["photo_ignored"] is False
    scan = _scan(client, owner)
    assert scan["total"] == 1 and scan["counts"]["photo"] == 1
    assert scan["photo_ignored_items"] == []
    assert _due(client, owner)["total"] == 1


def test_ignore_leaves_other_gaps_untouched(client, owner, db):
    bare = _tool(client, owner, name="Bare")  # every gap
    pack = _battery(client, owner, name="Bare pack", model="M18")
    _ignore(client, owner, "tool", bare["id"])
    _ignore(client, owner, "battery", pack["id"])
    scan = _scan(client, owner)
    by_name = {row["name"]: row for row in scan["items"]}
    # Both items still flag — for their remaining gaps only.
    assert set(by_name["Bare"]["missing"]) == {"identifier", "purchase_date"}
    assert by_name["Bare pack"]["missing"] == ["purchase_date"]
    assert scan["counts"]["photo"] == 0
    assert scan["counts"]["identifier"] == 1
    assert scan["counts"]["purchase_date"] == 2
    # The rows carry the ignore state + wizard identifying data.
    assert by_name["Bare"]["photo_ignored"] is True
    assert by_name["Bare pack"]["photo_ignored"] is True
    assert by_name["Bare pack"]["model"] == "M18"
    assert {r["name"] for r in scan["photo_ignored_items"]} == {
        "Bare", "Bare pack",
    }


def test_ignore_does_not_silence_piece_serials(client, owner, db):
    toolset = _tool(
        client, owner, name="Socket set", model="SET1",
        serial_number="SETSN", purchase_date="2026-02-01", is_set=True,
        pieces=[{"kind": "core", "name": "10mm socket", "part_number": "P10"}],
    )
    _ignore(client, owner, "tool", toolset["id"])
    scan = _scan(client, owner)
    [row] = scan["items"]
    assert row["missing"] == []  # the photo gap is silenced…
    assert row["pieces_missing_serial"] == ["10mm socket"]  # …this is not
    assert scan["counts"]["piece_serial"] == 1


def test_photo_arriving_retires_the_ignore_from_the_list(client, owner, db):
    tool = _tool(
        client, owner, name="Gets a photo", model="M1",
        serial_number="S1", purchase_date="2026-01-15",
    )
    _ignore(client, owner, "tool", tool["id"])
    assert len(_scan(client, owner)["photo_ignored_items"]) == 1
    _give_photo(db, "tool", tool["id"], "ignore-k-photo")
    scan = _scan(client, owner)
    assert scan["photo_ignored_items"] == [] and scan["total"] == 0


def test_ignore_is_owner_scoped(client, owner, db):
    other = _make_user(db, name="Other Owner")
    tool = _tool(client, other, name="Not yours")
    resp = _ignore(client, owner, "tool", tool["id"])
    assert resp.status_code == 404
    missing = _ignore(client, owner, "tool", str(uuid.uuid4()))
    assert missing.status_code == 404
    bad_kind = client.post(
        "/api/inventory/health-check/photo-ignore",
        json={"kind": "widget", "item_id": tool["id"], "ignored": True},
        headers=auth_headers(owner),
    )
    assert bad_kind.status_code == 422


def test_ignore_refuses_the_downloads_level(client, db):
    for key in ("normal", "moderator", "moderator_admin", "beta"):
        module_control.set_tier_assignment(db, "inventory", key, True)
    module_control.set_tier_assignment(db, "inventory", "downloads", False)
    downloader = _make_user(db, [], tier="downloads", name="Dee Downloads")
    resp = _ignore(client, downloader, "tool", str(uuid.uuid4()))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
