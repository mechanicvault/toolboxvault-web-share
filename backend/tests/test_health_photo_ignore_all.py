"""Health-check "Ignore all missing photos" (owner order, 2026-11-12).

POST /api/inventory/health-check/photo-ignore-all applies the
EXISTING per-item photo ignore (sweep E3) to every one of the
caller's items that currently has a missing, un-ignored photo —
in one atomic action. The contract pinned here:

  * SAME FLAG, SAME SEMANTICS — after a bulk ignore the scan and
    the Home due read behave exactly as if each item had been
    ignored one by one: photo counts drop to zero, photo-only
    items move to photo_ignored_items, items with other gaps
    keep flagging for those gaps only.
  * ONLY THE AFFECTED — items that HAVE a photo are never
    flagged by the action; items already ignored are untouched
    (and not counted in ignored_count).
  * OWNER-SCOPED — another owner's missing-photo items are not
    the caller's to silence.
  * REVERSIBLE PER ITEM — the single-item un-ignore still works
    after a bulk ignore, restoring exactly that item's flag.
  * The downloads level is refused at the inventory module gate.
"""

import itertools
import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.core import module_control, tiers
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(8800)


def _make_user(db, account_types=(MECHANIC,), *, tier="normal", name="Bulk Owner"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"bulk-{n}@example.com",
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
    payload.setdefault("name", "Bulk wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Bulk pack")
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


def _flag(db, kind, item_id):
    model = inventory_models.Tool if kind == "tool" else inventory_models.Battery
    return db.get(model, uuid.UUID(item_id)).health_photo_ignored


def _ignore(client, user, kind, item_id, ignored=True):
    return client.post(
        "/api/inventory/health-check/photo-ignore",
        json={"kind": kind, "item_id": item_id, "ignored": ignored},
        headers=auth_headers(user),
    )


def _ignore_all(client, user):
    return client.post(
        "/api/inventory/health-check/photo-ignore-all",
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


def _cast(client, user, db):
    """The standard cast: every photo state at once."""
    photo_only = _tool(
        client, user, name="Photo only", model="M1", serial_number="S1",
        purchase_date="2026-01-15",
    )
    bare = _tool(client, user, name="Bare tool")  # every gap
    pack = _battery(client, user, name="Bare pack", model="M18")  # photo+date
    complete = _tool(
        client, user, name="Complete", model="M9", serial_number="S9",
        purchase_date="2026-01-01",
    )
    _give_photo(db, "tool", complete["id"], "bulk-k-photo")
    return photo_only, bare, pack, complete


def test_bulk_ignore_matches_one_by_one_semantics(client, owner, db):
    photo_only, bare, pack, complete = _cast(client, owner, db)
    scan = _scan(client, owner)
    assert scan["total"] == 3 and scan["counts"]["photo"] == 3

    resp = _ignore_all(client, owner)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ignored_count": 3}

    # The complete item was never touched; the three flags are set.
    assert _flag(db, "tool", complete["id"]) is False
    assert _flag(db, "tool", photo_only["id"]) is True
    assert _flag(db, "tool", bare["id"]) is True
    assert _flag(db, "battery", pack["id"]) is True

    scan = _scan(client, owner)
    assert scan["counts"]["photo"] == 0
    # Photo-only item left the list for the reversal surface
    # (the list rides name-sorted, like the scan's items).
    assert [r["name"] for r in scan["photo_ignored_items"]] == [
        "Bare pack", "Bare tool", "Photo only",
    ]
    # …and the other two keep flagging for their remaining gaps.
    by_name = {row["name"]: row for row in scan["items"]}
    assert set(by_name) == {"Bare tool", "Bare pack"}
    assert set(by_name["Bare tool"]["missing"]) == {
        "identifier", "purchase_date",
    }
    assert by_name["Bare pack"]["missing"] == ["purchase_date"]
    assert by_name["Bare tool"]["photo_ignored"] is True
    # The Home due read is the same scan: it agrees.
    due = _due(client, owner)
    assert due["total"] == scan["total"] == 2
    assert due["counts"]["photo"] == 0

    # A second bulk run has nothing left to do.
    resp = _ignore_all(client, owner)
    assert resp.json() == {"ignored_count": 0}


def test_bulk_ignore_leaves_already_ignored_untouched(client, owner, db):
    photo_only, bare, pack, complete = _cast(client, owner, db)
    # Ignore ONE item the single-item way first.
    resp = _ignore(client, owner, "tool", photo_only["id"])
    assert resp.status_code == 200 and resp.json()["photo_ignored"] is True

    resp = _ignore_all(client, owner)
    # Only the two still-unignored missing photos count.
    assert resp.json() == {"ignored_count": 2}
    assert _flag(db, "tool", photo_only["id"]) is True
    scan = _scan(client, owner)
    assert scan["counts"]["photo"] == 0
    assert {r["name"] for r in scan["photo_ignored_items"]} == {
        "Photo only", "Bare tool", "Bare pack",
    }


def test_bulk_ignore_is_owner_scoped(client, owner, db):
    other = _make_user(db, name="Other Owner")
    mine = _tool(
        client, owner, name="Mine", model="M1", serial_number="S1",
        purchase_date="2026-01-15",
    )
    theirs = _tool(
        client, other, name="Theirs", model="M2", serial_number="S2",
        purchase_date="2026-01-15",
    )
    resp = _ignore_all(client, owner)
    assert resp.json() == {"ignored_count": 1}
    assert _flag(db, "tool", mine["id"]) is True
    assert _flag(db, "tool", theirs["id"]) is False
    # The other owner's scan still flags their photo, untouched.
    scan = _scan(client, other)
    assert scan["total"] == 1 and scan["counts"]["photo"] == 1
    assert scan["photo_ignored_items"] == []


def test_single_unignore_still_works_after_bulk(client, owner, db):
    photo_only, bare, pack, complete = _cast(client, owner, db)
    _ignore_all(client, owner)
    assert _scan(client, owner)["counts"]["photo"] == 0

    resp = _ignore(client, owner, "tool", photo_only["id"], ignored=False)
    assert resp.status_code == 200 and resp.json()["photo_ignored"] is False
    scan = _scan(client, owner)
    # Exactly that item's photo flags again; the rest stay ignored.
    assert scan["counts"]["photo"] == 1
    assert {r["name"] for r in scan["items"]} >= {"Photo only"}
    assert {r["name"] for r in scan["photo_ignored_items"]} == {
        "Bare tool", "Bare pack",
    }


def test_bulk_ignore_with_nothing_missing_is_a_no_op(client, owner, db):
    complete = _tool(
        client, owner, name="Complete", model="M9", serial_number="S9",
        purchase_date="2026-01-01",
    )
    _give_photo(db, "tool", complete["id"], "bulk-k-solo")
    resp = _ignore_all(client, owner)
    assert resp.status_code == 200
    assert resp.json() == {"ignored_count": 0}
    assert _flag(db, "tool", complete["id"]) is False


def test_bulk_ignore_refuses_the_downloads_level(client, db):
    for key in ("normal", "moderator", "moderator_admin", "beta"):
        module_control.set_tier_assignment(db, "inventory", key, True)
    module_control.set_tier_assignment(db, "inventory", "downloads", False)
    downloader = _make_user(db, [], tier="downloads", name="Dee Downloads")
    resp = _ignore_all(client, downloader)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
