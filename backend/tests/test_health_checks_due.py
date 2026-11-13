"""Health checks due widget read (widget wave 2, build 2).

GET /api/inventory/health-check-due is the Home widget's read:
the inventory Health Check scan (service.health_check) VERBATIM
— same total, same counts, same items, same order — plus each
flagged item's primary-photo thumbnail URLs for the widget
rows. These tests pin the two halves of that contract:

  * THE SCAN IS THE ONLY DEFINITION — the due read and the
    Health Check page's own endpoint agree item for item on a
    mixed population (the identifier rule: NEITHER a model NOR
    a serial flags; either one alone satisfies; set pieces
    surface under their set; a complete item never appears).
  * THE THUMBNAIL IS DISPLAY DATA — a flagged item WITH a
    photo (flagged for another gap) carries its signed
    rendition URLs from the shared primary_photo_thumb minter;
    a photo-less flagged item carries nulls.
  * QUIET IS A STATE — nothing flagged (or an empty inventory)
    is a 200 with total 0, never an error.
  * REACH IS THE INVENTORY MODULE — the downloads level is
    refused 403 module_unavailable at the same gate the Health
    Check page's endpoint uses.
"""

import itertools
import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.core import module_control, tiers
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(7000)


def _make_user(db, account_types=(MECHANIC,), *, tier="normal", name="Due Owner"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"due-{n}@example.com",
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
    payload.setdefault("name", "Due wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Due pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _give_photo(db, kind, item_id, key):
    model = inventory_models.Tool if kind == "tool" else inventory_models.Battery
    row = db.get(model, uuid.UUID(item_id))
    row.attachments = [
        {
            "kind": "photo",
            "key": key,
            "filename": "p.jpg",
            "content_type": "image/jpeg",
        }
    ]
    db.commit()


def _mixed_population(client, db, user):
    """The gap-wave-1 health-check population, rebuilt: one
    complete tool (never flagged), one bare tool (every gap),
    one serial-only tool (identifier satisfied — never
    flagged), one battery with a model (photo + date gaps),
    one set whose present piece lacks a serial."""
    complete = _tool(
        client, user, name="Complete", model="M1", serial_number="S1",
        purchase_date="2026-01-15",
    )
    _give_photo(db, "tool", complete["id"], "due-k-complete")
    _tool(client, user, name="Bare")  # missing everything
    serial_only = _tool(
        client, user, name="Serial only", serial_number="SONLY1",
        purchase_date="2026-03-01",
    )
    _give_photo(db, "tool", serial_only["id"], "due-k-serial")
    _battery(client, user, name="Bare pack", model="M18")
    toolset = _tool(
        client, user, name="Socket set", model="SET1",
        serial_number="SETSN", purchase_date="2026-02-01", is_set=True,
        pieces=[
            {"kind": "core", "name": "10mm socket", "part_number": "P10"},
            {
                "kind": "core",
                "name": "12mm socket",
                "part_number": "P12",
                "serial_number": "PS12",
            },
        ],
    )
    _give_photo(db, "tool", toolset["id"], "due-k-set")
    return toolset


def test_due_read_is_the_scan_verbatim(client, owner, db):
    _mixed_population(client, db, owner)
    scan = client.get(
        "/api/inventory/health-check", headers=auth_headers(owner)
    ).json()
    due = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(owner)
    ).json()
    assert due["total"] == scan["total"] == 3
    assert due["counts"] == scan["counts"]
    # Item for item, in the scan's own (name) order — the
    # widget adds thumbnails, never a second opinion.
    assert [i["name"] for i in due["items"]] == [
        i["name"] for i in scan["items"]
    ]
    for due_item, scan_item in zip(due["items"], scan["items"]):
        for key in (
            "kind", "id", "name", "missing", "pieces_missing_serial",
            "pieces_missing", "sub_limit_warning",
        ):
            assert due_item[key] == scan_item[key], key
    by_name = {row["name"]: row for row in due["items"]}
    assert "Complete" not in by_name
    assert "Serial only" not in by_name
    # NEITHER a model NOR a serial number: the identifier gap —
    # the item the Health Check exists to surface.
    assert set(by_name["Bare"]["missing"]) == {
        "identifier", "photo", "purchase_date",
    }
    assert by_name["Socket set"]["pieces_missing_serial"] == ["10mm socket"]


def test_due_read_thumbnails_are_the_shared_minters(client, owner, db):
    _mixed_population(client, db, owner)
    due = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(owner)
    ).json()
    by_name = {row["name"]: row for row in due["items"]}
    # The set HAS a photo (it is flagged for its piece, not its
    # photo): its row carries the primary photo's renditions,
    # minted by the same signed-URL machinery as every other
    # surface.
    assert by_name["Socket set"]["thumb_url"] is not None
    assert "/api/inventory/thumb/320" in by_name["Socket set"]["thumb_url"]
    assert "/api/inventory/thumb/128" in by_name["Socket set"]["thumb_url_sm"]
    # The bare tool has no photo to show: nulls, the client's
    # no-photo cue.
    assert by_name["Bare"]["thumb_url"] is None
    assert by_name["Bare"]["thumb_url_sm"] is None
    assert by_name["Bare pack"]["thumb_url_sm"] is None


def test_due_read_quiet_states(client, owner, db):
    # An owner with no items at all: total 0, no error.
    due = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(owner)
    )
    assert due.status_code == 200, due.text
    assert due.json() == {
        "total": 0,
        "counts": {
            "identifier": 0, "photo": 0, "purchase_date": 0, "piece_serial": 0,
        },
        "items": [],
    }
    # An owner whose only item is complete: still quiet.
    complete = _tool(
        client, owner, name="Complete", model="M1", serial_number="S1",
        purchase_date="2026-01-15",
    )
    _give_photo(db, "tool", complete["id"], "due-k-quiet")
    due = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(owner)
    ).json()
    assert due["total"] == 0 and due["items"] == []


def test_due_read_is_owner_scoped(client, owner, db):
    other = _make_user(db, name="Other Owner")
    _tool(client, other, name="Not yours")
    due = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(owner)
    ).json()
    assert due["total"] == 0


def test_due_read_refuses_the_downloads_level(client, db):
    # Migration 0096/0097's posture for the module this read
    # lives in: inventory lit for the ordinary tiers, dark for
    # downloads.
    for key in ("normal", "moderator", "moderator_admin", "beta"):
        module_control.set_tier_assignment(db, "inventory", key, True)
    module_control.set_tier_assignment(db, "inventory", "downloads", False)
    downloader = _make_user(db, [], tier="downloads", name="Dee Downloads")
    refused = client.get(
        "/api/inventory/health-check-due", headers=auth_headers(downloader)
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "module_unavailable"
