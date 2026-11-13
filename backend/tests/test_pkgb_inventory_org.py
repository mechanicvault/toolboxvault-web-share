"""Review Round 1 · Package B — inventory organization (2026-10-19).

Pins:
- the location TREE: CRUD + paths, item text = node path kept in
  sync through renames/moves, subtree filtering (filter by a place
  shows everything under it), delete = reassign-or-detach, never a
  silent orphan; text writes find-or-create a top-level node;
- condition is GONE from every user-facing payload (item payloads,
  peer whitelist — pinned in test_peer_sharing/test_batteries,
  reports columns/filters, tier sharing) while the stored value
  survives (exports/conversions keep it — test_parts pins that);
- the inline set editor: one save creates/updates a set WITH its
  pieces, atomically (a bad piece row saves nothing);
- a first maintenance schedule rides the item form, validated
  BEFORE the item saves;
- maintenance log entries carry documents via the item attachment
  machinery (collection "log_entries");
- standing: in_service | broken | in_repair | lost | stolen —
  borrowing refuses the four non-service standings and always
  allows returns; the repair trio mirrors into repair_state;
- bulk edit: every action, whole-batch refusal on a foreign id,
  one journal entry per mutated item;
- field suggestions are the caller's OWN values, never another's.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"


def _make_user(db, account_number, email, account_types):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="PkgB User",
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "pkgb-owner@example.com", [MECHANIC])


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000402", "pkgb-other@example.com", [MECHANIC])


def _tool(client, user, **payload):
    payload.setdefault("name", "Wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "M18 pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _node(client, user, name, parent_id=None):
    resp = client.post(
        "/api/inventory/location-tree",
        json={"name": name, "parent_id": str(parent_id) if parent_id else None},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tree(client, user):
    resp = client.get("/api/inventory/location-tree", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bulk(client, user, items, action, params=None):
    return client.post(
        "/api/inventory/bulk",
        json={"items": items, "action": action, "params": params or {}},
        headers=auth_headers(user),
    )


# -- location tree ------------------------------------------------------------


def test_tree_crud_paths_and_counts(client, owner):
    root = _node(client, owner, "Shop Toolbox")
    drawer = _node(client, owner, "Left Drawer 2", parent_id=root["id"])
    assert drawer["path"] == "Shop Toolbox / Left Drawer 2"

    tool = _tool(client, owner, name="Ratchet", location_id=drawer["id"])
    assert tool["location"] == "Shop Toolbox / Left Drawer 2"
    assert tool["location_id"] == drawer["id"]

    tree = {n["name"]: n for n in _tree(client, owner)}
    assert tree["Shop Toolbox"]["item_count"] == 0
    assert tree["Shop Toolbox"]["subtree_item_count"] == 1
    assert tree["Left Drawer 2"]["item_count"] == 1


def test_subtree_counts_roll_up_through_tier3(client, owner):
    """The Location / Sub Location dropdown counts (owner spec
    2026-10-24): a node's subtree_item_count is every tool AND
    battery filed at or below it — tier-3 items roll up into
    their tier-2 and tier-1 ancestors, never double-counted."""
    bay = _node(client, owner, "Bay 1")
    cabinet = _node(client, owner, "Cabinet", parent_id=bay["id"])
    shelf = _node(client, owner, "Top Shelf", parent_id=cabinet["id"])
    _tool(client, owner, name="Bay tool", location_id=bay["id"])
    _tool(client, owner, name="Cabinet tool", location_id=cabinet["id"])
    _tool(client, owner, name="Shelf tool", location_id=shelf["id"])
    _battery(client, owner, name="Shelf pack", location_id=shelf["id"])
    _tool(client, owner, name="Unfiled")

    tree = {n["name"]: n for n in _tree(client, owner)}
    assert tree["Bay 1"]["item_count"] == 1
    assert tree["Bay 1"]["subtree_item_count"] == 4
    assert tree["Cabinet"]["item_count"] == 1
    assert tree["Cabinet"]["subtree_item_count"] == 3
    assert tree["Top Shelf"]["item_count"] == 2
    assert tree["Top Shelf"]["subtree_item_count"] == 2


def test_subtree_filter_shows_everything_under_a_place(client, owner):
    root = _node(client, owner, "Shop Toolbox")
    drawer = _node(client, owner, "Drawer 1", parent_id=root["id"])
    deep = _tool(client, owner, name="Deep tool", location_id=drawer["id"])
    shallow = _tool(client, owner, name="Top tool", location_id=root["id"])
    pack = _battery(client, owner, name="Drawer pack", location_id=drawer["id"])
    _tool(client, owner, name="Unfiled")

    def ids(**params):
        resp = client.get(
            "/api/inventory/search/all", params=params, headers=auth_headers(owner)
        )
        assert resp.status_code == 200, resp.text
        return {row["id"] for row in resp.json()}

    assert ids(location_id=root["id"]) == {deep["id"], shallow["id"], pack["id"]}
    assert ids(location_id=drawer["id"]) == {deep["id"], pack["id"]}
    # The plain tool search honors the same subtree.
    resp = client.get(
        "/api/inventory/search",
        params={"location_id": root["id"]},
        headers=auth_headers(owner),
    )
    assert {row["id"] for row in resp.json()} == {deep["id"], shallow["id"]}


def test_tree_rename_and_move_resync_item_text(client, owner):
    root = _node(client, owner, "Shop Toolbox")
    drawer = _node(client, owner, "Drawer 1", parent_id=root["id"])
    tool = _tool(client, owner, location_id=drawer["id"])

    renamed = client.put(
        f"/api/inventory/location-tree/{drawer['id']}",
        json={"name": "Deep Drawer"},
        headers=auth_headers(owner),
    )
    assert renamed.status_code == 200, renamed.text
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner))
    assert view.json()["location"] == "Shop Toolbox / Deep Drawer"

    garage = _node(client, owner, "Garage Box")
    moved = client.put(
        f"/api/inventory/location-tree/{drawer['id']}",
        json={"parent_id": garage["id"]},
        headers=auth_headers(owner),
    )
    assert moved.status_code == 200, moved.text
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner))
    assert view.json()["location"] == "Garage Box / Deep Drawer"


def test_tree_move_refuses_cycles(client, owner):
    root = _node(client, owner, "Shop Toolbox")
    drawer = _node(client, owner, "Drawer 1", parent_id=root["id"])
    resp = client.put(
        f"/api/inventory/location-tree/{root['id']}",
        json={"parent_id": drawer["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_tree_delete_reassign_or_detach_never_orphans(client, owner):
    root = _node(client, owner, "Shop Toolbox")
    drawer = _node(client, owner, "Drawer 1", parent_id=root["id"])
    tool = _tool(client, owner, location_id=drawer["id"])

    # No decision -> friendly refusal, nothing changes.
    refused = client.request(
        "DELETE",
        f"/api/inventory/location-tree/{drawer['id']}",
        json={},
        headers=auth_headers(owner),
    )
    assert refused.status_code == 422, refused.text

    # Reassign: the item (and the path text) move to the target.
    spare = _node(client, owner, "Spare Box")
    gone = client.request(
        "DELETE",
        f"/api/inventory/location-tree/{drawer['id']}",
        json={"reassign_to_id": spare["id"]},
        headers=auth_headers(owner),
    )
    assert gone.status_code == 204, gone.text
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner))
    assert view.json()["location_id"] == spare["id"]
    assert view.json()["location"] == "Spare Box"

    # Detach: the item unfiles, its text clears.
    gone = client.request(
        "DELETE",
        f"/api/inventory/location-tree/{spare['id']}",
        json={"detach": True},
        headers=auth_headers(owner),
    )
    assert gone.status_code == 204, gone.text
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner))
    assert view.json()["location_id"] is None
    assert view.json()["location"] == ""


def test_tree_foreign_nodes_never_leak(client, owner, other):
    mine = _node(client, owner, "My Box")
    resp = client.put(
        f"/api/inventory/location-tree/{mine['id']}",
        json={"name": "Hijacked"},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404, resp.text
    resp = client.post(
        "/api/inventory",
        json={"name": "Sneaky", "location_id": mine["id"]},
        headers=auth_headers(other),
    )
    assert resp.status_code == 422, resp.text


def test_text_location_write_creates_top_level_node(client, owner):
    tool = _tool(client, owner, name="Legacy", location="Garage")
    tree = _tree(client, owner)
    assert [n["name"] for n in tree] == ["Garage"]
    assert tool["location_id"] == tree[0]["id"]
    # A second item with the same text files under the SAME node.
    tool2 = _tool(client, owner, name="Legacy 2", location="Garage")
    assert tool2["location_id"] == tree[0]["id"]
    assert len(_tree(client, owner)) == 1


# -- self-learning fields -------------------------------------------------------


def test_suggestions_are_the_callers_own_values(client, owner, other):
    _tool(
        client, owner, name="A", brand="Snap-on", category="Power tools",
        size="1/2 in", tag_ids=[],
    )
    _battery(client, owner, name="B", brand="Milwaukee", category="Battery")
    tag = client.post(
        "/api/inventory/tags", json={"name": "fav"}, headers=auth_headers(owner)
    ).json()
    tool = _tool(client, owner, name="C", tag_ids=[tag["id"]])
    _tool(client, other, name="D", brand="Matco", category="Truck tools")

    def suggestions(user, field):
        resp = client.get(
            "/api/inventory/suggestions",
            params={"field": field},
            headers=auth_headers(user),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert suggestions(owner, "brand") == ["Milwaukee", "Snap-on"]
    assert suggestions(owner, "category") == ["Battery", "Power tools"]
    assert suggestions(owner, "size") == ["1/2 in"]
    assert suggestions(owner, "tag") == ["fav"]
    assert suggestions(other, "brand") == ["Matco"]


# -- condition removal ------------------------------------------------------------


def test_condition_absent_from_item_payloads(client, owner):
    tool = _tool(client, owner, name="T", condition="Good")
    assert "condition" not in tool
    battery = _battery(client, owner, name="B", condition="Worn")
    assert "condition" not in battery
    detail = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert "condition" not in detail
    rows = client.get("/api/inventory/search/all", headers=auth_headers(owner)).json()
    assert rows and all("condition" not in row for row in rows)


def test_reports_have_no_condition_column_or_filter(client, owner, db):
    _tool(client, owner, name="Blue drill", condition="Worn")
    meta = client.get("/api/reports/meta", headers=auth_headers(owner))
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert "conditions" not in body
    assert all(c["key"] != "condition" for c in body["columns"])

    # A spec naming the retired column still runs — the column is
    # dropped, and a retired sort key falls back to the default.
    report = client.post(
        "/api/reports/run",
        json={
            "columns": ["name", "condition"],
            "filters": {},
            "grouping": "none",
            "sets_mode": "summary",
            "sort": {"key": "condition", "direction": "asc"},
        },
        headers=auth_headers(owner),
    )
    assert report.status_code == 200, report.text
    assert [c["key"] for c in report.json()["columns"]] == ["name"]


# -- inline set editor ------------------------------------------------------------


def test_inline_set_create_with_pieces_one_save(client, owner):
    tool = _tool(
        client,
        owner,
        name="Socket set",
        is_set=True,
        purchase_price="100.00",
        pieces=[
            {"kind": "core", "name": "Ratchet", "part_number": "R1"},
            {"kind": "core", "name": "10mm socket", "part_number": "S10"},
            {
                "kind": "addon", "name": "Extension", "price": "12.50",
                "purchase_date": "2025-01-15",
            },
        ],
    )
    assert tool["is_set"] is True
    assert len(tool["set"]["core_pieces"]) == 2
    (addon,) = tool["set"]["addon_pieces"]
    assert addon["name"] == "Extension"
    assert tool["set"]["price_total"] == "112.50"


def test_inline_set_create_priced_core_piece_is_accepted(client, owner):
    # Owner rule change 2026-10-25 (Sets lane, migration 0059): a price is
    # optional on EVERY piece, core included — it is the piece's own figure
    # (what replacing that one piece costs) and never rolls into the set's
    # totals. This replaces the pre-0059 contract, under which a priced
    # core piece was refused outright.
    tool = _tool(
        client,
        owner,
        name="Priced-core set",
        is_set=True,
        pieces=[{"kind": "core", "name": "Priced core", "price": "5.00"}],
    )
    (piece,) = tool["set"]["core_pieces"]
    assert piece["price"] == "5.00"
    assert tool["set"]["price_total"] == "0.00"


def test_inline_set_create_bad_piece_saves_nothing(client, owner):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "Bad set",
            "is_set": True,
            "pieces": [{"kind": "bogus", "name": "Not a piece kind"}],
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    listing = client.get("/api/inventory", headers=auth_headers(owner)).json()
    assert listing == []


def test_inline_set_update_syncs_pieces_by_id(client, owner, db):
    tool = _tool(
        client,
        owner,
        name="Socket set",
        is_set=True,
        pieces=[
            {"kind": "core", "name": "Ratchet"},
            {"kind": "core", "name": "10mm socket"},
        ],
    )
    ratchet, socket = tool["set"]["core_pieces"]
    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={
            "pieces": [
                {"id": ratchet["id"], "kind": "core", "name": "Ratchet Pro"},
                {"kind": "addon", "name": "Case", "price": "20.00"},
            ]
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    (kept,) = body["set"]["core_pieces"]
    assert kept["id"] == ratchet["id"]  # same piece — files/history survive
    assert kept["name"] == "Ratchet Pro"
    assert [p["name"] for p in body["set"]["addon_pieces"]] == ["Case"]
    assert db.get(inventory_models.SetPiece, uuid.UUID(socket["id"])) is None


def test_unmarking_a_set_requires_emptying_pieces(client, owner):
    tool = _tool(
        client, owner, name="Socket set", is_set=True,
        pieces=[{"kind": "core", "name": "Ratchet"}],
    )
    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={"is_set": False},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={"is_set": False, "pieces": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_set"] is False


# -- maintenance on the item form ---------------------------------------------------


def test_first_schedule_rides_item_create(client, owner):
    tool = _tool(
        client,
        owner,
        name="Torque wrench",
        initial_schedule={"kind": "calibration", "interval_days": 180},
    )
    standing = client.get(
        f"/api/maintenance/items/tool/{tool['id']}", headers=auth_headers(owner)
    )
    assert standing.status_code == 200, standing.text
    (schedule,) = standing.json()["schedules"]
    assert schedule["kind"] == "calibration"
    assert schedule["interval_days"] == 180

    battery = _battery(
        client,
        owner,
        name="Pack",
        initial_schedule={"kind": "service", "due_date": "2027-03-01"},
    )
    standing = client.get(
        f"/api/maintenance/items/battery/{battery['id']}",
        headers=auth_headers(owner),
    ).json()
    assert standing["schedules"][0]["due_date"] == "2027-03-01"


def test_bad_first_schedule_fails_the_whole_save(client, owner):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "Doomed",
            "initial_schedule": {"kind": "service"},  # no interval, no date
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert client.get("/api/inventory", headers=auth_headers(owner)).json() == []


# -- log entry documents ------------------------------------------------------------


def test_log_entry_documents_ride_the_attachment_machinery(
    client, owner, monkeypatch
):
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_get_url",
        lambda key, expires_in=900: f"https://files.test/{key}",
    )
    tool = _tool(client, owner, name="Torque wrench")
    schedule = client.post(
        f"/api/maintenance/items/tool/{tool['id']}/schedules",
        json={"kind": "calibration", "interval_days": 365},
        headers=auth_headers(owner),
    )
    assert schedule.status_code == 201, schedule.text
    entry = client.post(
        f"/api/maintenance/schedules/{schedule.json()['id']}/log",
        json={"done_date": "2026-10-01", "technician": "Cal Lab"},
        headers=auth_headers(owner),
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]

    url = client.post(
        f"/api/maintenance/log-entries/{entry_id}/upload-url",
        json={
            "filename": "cert.pdf",
            "content_type": "application/pdf",
            "kind": "document",
            "size_bytes": 2048,
        },
        headers=auth_headers(owner),
    )
    assert url.status_code == 200, url.text
    key = url.json()["key"]
    assert f"/log_entries/{entry_id}/" in key

    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=2048, content_type="application/pdf"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda k, length=512: b"%PDF-1.7\n" + b"\x00" * 32,
    )
    attached = client.post(
        f"/api/maintenance/log-entries/{entry_id}/attachments",
        json={"key": key, "filename": "cert.pdf"},
        headers=auth_headers(owner),
    )
    assert attached.status_code == 200, attached.text

    standing = client.get(
        f"/api/maintenance/items/tool/{tool['id']}", headers=auth_headers(owner)
    ).json()
    (logged,) = standing["schedules"][0]["log"]
    assert [a["filename"] for a in logged["attachments"]] == ["cert.pdf"]


# -- standing + borrowing ------------------------------------------------------------


def test_standing_mirrors_the_repair_trio(client, owner, db):
    tool = _tool(client, owner, name="Impact")
    # Merge (2026-11-04): the break is the bulk standing write —
    # apply_standing still mirrors the repair trio.
    broken = _bulk(
        client, owner,
        [{"kind": "tool", "id": tool["id"]}],
        "set_standing", {"standing": "broken"},
    )
    assert broken.status_code == 200, broken.text
    record = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    db.refresh(record)
    assert record.standing == "broken"
    assert record.repair_state == "broken"  # the mirror holds


@pytest.mark.parametrize("standing", ["broken", "in_repair", "lost", "stolen"])
def test_borrowing_refuses_every_non_service_standing(client, owner, standing):
    tool = _tool(client, owner, name=f"Tool {standing}")
    applied = _bulk(
        client, owner,
        [{"kind": "tool", "id": tool["id"]}],
        "set_standing", {"standing": standing},
    )
    assert applied.status_code == 200, applied.text
    resp = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool["id"],
            "borrower_name": "Neighbor Nate",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_return_is_always_allowed_even_when_lost(client, owner):
    tool = _tool(client, owner, name="Lent then lost")
    lent = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool["id"],
            "borrower_name": "Neighbor Nate",
        },
        headers=auth_headers(owner),
    )
    assert lent.status_code == 201, lent.text
    applied = _bulk(
        client, owner,
        [{"kind": "tool", "id": tool["id"]}],
        "set_standing", {"standing": "lost"},
    )
    assert applied.status_code == 200, applied.text
    returned = client.post(
        f"/api/borrowing/{lent.json()['id']}/return", headers=auth_headers(owner)
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["state"] == "returned"


def test_lost_items_stay_in_the_active_set(client, owner):
    tool = _tool(client, owner, name="Lost but mine")
    _bulk(
        client, owner,
        [{"kind": "tool", "id": tool["id"]}],
        "set_standing", {"standing": "lost"},
    )
    view = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert view["standing"] == "lost"
    assert view["active"] is True


# -- bulk edit ------------------------------------------------------------------------


def test_bulk_actions_apply_across_kinds(client, owner, db):
    box = _node(client, owner, "Shop Toolbox")
    t1 = _tool(client, owner, name="One")
    t2 = _tool(client, owner, name="Two")
    b1 = _battery(client, owner, name="Pack")
    refs = [
        {"kind": "tool", "id": t1["id"]},
        {"kind": "tool", "id": t2["id"]},
        {"kind": "battery", "id": b1["id"]},
    ]

    resp = _bulk(client, owner, refs, "set_brand", {"brand": "Snap-on"})
    assert resp.status_code == 200 and resp.json()["affected"] == 3, resp.text
    resp = _bulk(client, owner, refs, "move_location", {"location_id": box["id"]})
    assert resp.status_code == 200, resp.text
    resp = _bulk(client, owner, refs, "add_tag", {"tag_name": "truck kit"})
    assert resp.status_code == 200, resp.text
    resp = _bulk(client, owner, refs, "set_category", {"category": "Truck"})
    assert resp.status_code == 200, resp.text

    view = client.get(f"/api/inventory/{t1['id']}", headers=auth_headers(owner)).json()
    assert view["brand"] == "Snap-on"
    assert view["location"] == "Shop Toolbox"
    assert view["category"] == "Truck"
    assert [t["name"] for t in view["tags"]] == ["truck kit"]
    pack = client.get(
        f"/api/inventory/batteries/{b1['id']}", headers=auth_headers(owner)
    ).json()
    assert pack["location_id"] == box["id"]

    # The journal recorded the mutations per item (the audit
    # listener sees ORM writes — bulk edits are no exception).
    entries = (
        db.query(core_models.ChangeJournal)
        .filter(
            core_models.ChangeJournal.user_id == owner.id,
            core_models.ChangeJournal.entity_type == "tool",
            core_models.ChangeJournal.action == "update",
        )
        .all()
    )
    assert {str(e.entity_id) for e in entries} >= {t1["id"], t2["id"]}


def test_bulk_foreign_id_refuses_the_whole_batch(client, owner, other):
    mine = _tool(client, owner, name="Mine", brand="OldBrand")
    foreign = _tool(client, other, name="Theirs")
    resp = _bulk(
        client,
        owner,
        [
            {"kind": "tool", "id": mine["id"]},
            {"kind": "tool", "id": foreign["id"]},
        ],
        "set_brand",
        {"brand": "NewBrand"},
    )
    assert resp.status_code == 422, resp.text
    view = client.get(
        f"/api/inventory/{mine['id']}", headers=auth_headers(owner)
    ).json()
    assert view["brand"] == "OldBrand"  # nothing was applied


def test_bulk_delete_removes_the_selection(client, owner):
    t1 = _tool(client, owner, name="One")
    t2 = _tool(client, owner, name="Two")
    resp = _bulk(
        client,
        owner,
        [{"kind": "tool", "id": t1["id"]}, {"kind": "tool", "id": t2["id"]}],
        "delete",
    )
    assert resp.status_code == 200 and resp.json()["affected"] == 2, resp.text
    assert client.get("/api/inventory", headers=auth_headers(owner)).json() == []


# -- drawer-grid positions (audit A3) -------------------------------------------


def test_drawer_fields_round_trip_and_clear(client, owner):
    box = _node(client, owner, "Shop Toolbox")
    resp = client.post(
        "/api/inventory/location-tree",
        json={
            "name": "Top Drawer",
            "parent_id": box["id"],
            "parent_layout_id": box["id"],
            "drawer_index": 0,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    drawer = resp.json()
    assert drawer["parent_layout_id"] == box["id"]
    assert drawer["drawer_index"] == 0
    # Ordinary nodes carry nulls — no structure invented.
    assert box["parent_layout_id"] is None
    assert box["drawer_index"] is None
    # Update the position; then clear it with explicit nulls.
    resp = client.put(
        f"/api/inventory/location-tree/{drawer['id']}",
        json={"drawer_index": 3},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["drawer_index"] == 3
    assert resp.json()["parent_layout_id"] == box["id"]  # untouched
    resp = client.put(
        f"/api/inventory/location-tree/{drawer['id']}",
        json={"parent_layout_id": None, "drawer_index": None},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["parent_layout_id"] is None
    assert resp.json()["drawer_index"] is None


def test_drawer_layout_must_be_owned(client, owner, other):
    foreign = _node(client, other, "Someone else's toolbox")
    resp = client.post(
        "/api/inventory/location-tree",
        json={
            "name": "Drawer",
            "parent_layout_id": foreign["id"],
            "drawer_index": 0,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_deleting_a_layout_clears_drawer_links(client, owner):
    box = _node(client, owner, "Doomed Toolbox")
    resp = client.post(
        "/api/inventory/location-tree",
        json={
            "name": "Drawer",
            "parent_id": box["id"],
            "parent_layout_id": box["id"],
            "drawer_index": 1,
        },
        headers=auth_headers(owner),
    )
    drawer = resp.json()
    # Detach-delete the toolbox: the child lifts out and its layout
    # link clears instead of dangling.
    resp = client.request(
        "DELETE",
        f"/api/inventory/location-tree/{box['id']}",
        json={"detach": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text
    tree = {n["id"]: n for n in _tree(client, owner)}
    assert tree[drawer["id"]]["parent_layout_id"] is None
    assert tree[drawer["id"]]["drawer_index"] == 1  # position kept
