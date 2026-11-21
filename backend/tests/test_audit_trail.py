"""User audit trail + restore (2026-10-19).

The journal captures every create / update / delete of a user's
OWN content with full before/after snapshots; restore markers are
rollback points; the restore engine inverts everything after a
marker in ONE transaction. Two-party records (borrowing rows,
peer shares) and filed claims are journaled for VISIBILITY only
and never inverted. Deleted files are tombstoned, not destroyed,
until the retention purge.

Coverage map (the build's test brief):
  (a) delete-entire-inventory → restore → everything back, ids +
      photos intact        — test_restore_brings_back_a_wiped_inventory
  (b) edit rollback        — test_restore_rolls_back_an_edit
  (c) add rollback         — test_restore_removes_an_addition
  (d) restore-the-restore  — test_pre_restore_marker_undoes_the_restore
  (e) borrowing row in the window untouched + counted
                           — test_restore_leaves_borrowing_rows_alone
  (f) filed claim untouched, draft restored
                           — test_restore_respects_claim_lifecycle
  (g) poisoned entry aborts atomically
                           — test_poisoned_entry_aborts_the_whole_restore
  (h) admin on-behalf + both audit trails
                           — test_admin_restore_writes_both_trails
  (i) retention purge seam  — test_purge_removes_only_expired_tombstones
  (j) attachment visibility unchanged (sharing preview + export)
                           — test_deleted_item_files_follow_the_record
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.core import storage as storage_module
from app.modules.core import journal, models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import attachments as inv_attachments
from app.modules.inventory import schemas as inv_schemas
from app.modules.inventory import service as inv_service
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_oauth.py).
    counter = itertools.count(900200)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


@pytest.fixture()
def owner(db):
    """A user created through the real signup path — baseline
    marker included."""
    return core_service.create_user(
        db,
        "owner@example.com",
        "Owner",
        "hunter22",
        ["mechanic_technician", "tool_dealer"],
    )


def _entries(db, user_id, entity_type=None):
    stmt = select(core_models.ChangeJournal).where(
        core_models.ChangeJournal.user_id == user_id
    )
    if entity_type:
        stmt = stmt.where(core_models.ChangeJournal.entity_type == entity_type)
    return list(db.scalars(stmt.order_by(core_models.ChangeJournal.seq)))


def _marker(db, user_id, label="Point"):
    return journal.create_marker(db, user_id, kind="manual", label=label)


def _restore(db, user, marker):
    return journal.restore_to_marker(db, user.id, marker, actor_id=user.id)


def _attach_photo(db, user, record, collection="tools", filename="photo.jpg"):
    """Attach a photo through the real flow with storage HEAD
    stubbed by the caller (see the `storage_stub` fixture)."""
    key = f"{user.id}/{collection}/{record.id}/photo/{filename}"
    return inv_attachments.attach_file(
        db,
        user.id,
        record.id,
        inv_schemas.AttachRequest(key=key, filename=filename),
        collection=collection,
    )


@pytest.fixture()
def storage_stub(monkeypatch):
    """Storage that pretends every object exists and records
    deletes: attach flows verify, delete paths must NOT call it."""
    deleted: list[str] = []
    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=128, content_type="image/jpeg"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda k, length=512: b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    )
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    monkeypatch.setattr(storage_module.storage, "delete", deleted.append)
    return deleted


# -- capture ---------------------------------------------------------------------


def test_signup_writes_a_baseline_marker(db, owner):
    markers = journal.list_markers(db, owner.id)
    assert len(markers) == 1
    assert markers[0].kind == "baseline"
    assert markers[0].journal_seq == 0


def test_journal_captures_create_update_delete(db, owner):
    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="QA Prompt Wrench")
    )
    inv_service.update_tool(
        db, owner.id, tool.id, inv_schemas.ToolUpdate(name="QA Prompt Wrench II")
    )
    inv_service.delete_tool(db, owner.id, tool.id)

    entries = _entries(db, owner.id, "tool")
    assert [e.action for e in entries] == ["create", "update", "delete"]
    create, update, delete = entries
    assert create.before is None
    assert create.after["name"] == "QA Prompt Wrench"
    assert create.entity_id == tool.id
    assert update.before["name"] == "QA Prompt Wrench"
    assert update.after["name"] == "QA Prompt Wrench II"
    assert delete.before["name"] == "QA Prompt Wrench II"
    assert delete.after is None
    assert all(e.restorable for e in entries)
    assert update.label == "Changed tool 'QA Prompt Wrench II'"
    assert delete.label == "Deleted tool 'QA Prompt Wrench II'"
    assert [e.seq for e in entries] == sorted(e.seq for e in entries)


def test_journal_covers_batteries_sets_pieces_tags_and_fields(db, owner):
    from app.modules.inventory import custom_fields

    definition = custom_fields.create_definition(
        db,
        owner.id,
        inv_schemas.FieldDefinitionCreate(
            name="torque", label="Torque spec", field_type="text"
        ),
    )
    tag = inv_service.create_tag(db, owner.id, "favorites")
    tool = inv_service.create_tool(
        db,
        owner.id,
        inv_schemas.ToolCreate(
            name="Socket set",
            is_set=True,
            custom_data={str(definition.id): "90 ft-lb"},
            tag_ids=[tag.id],
        ),
    )
    piece = inv_service.add_set_piece(
        db, owner.id, tool.id, inv_schemas.SetPieceCreate(name="10mm socket")
    )
    battery = inv_service.create_battery(
        db, owner.id, inv_schemas.BatteryCreate(name="M18 5.0")
    )

    seen = {(e.entity_type, e.action) for e in _entries(db, owner.id)}
    assert ("field_definition", "create") in seen
    assert ("tag", "create") in seen
    assert ("item_tag", "create") in seen
    assert ("set_piece", "create") in seen
    assert ("battery", "create") in seen
    tool_create = next(
        e for e in _entries(db, owner.id, "tool") if e.action == "create"
    )
    assert tool_create.after["custom_data"] == {str(definition.id): "90 ft-lb"}
    assert piece is not None and battery is not None

    # A definition delete scrubs the value through the ORM: the
    # tool earns an update entry, and RESTORING the delete brings
    # definition + value back together.
    marker = _marker(db, owner.id, "before field delete")
    custom_fields.delete_definition(db, owner.id, definition.id)
    db.refresh(tool)
    assert tool.custom_data == {}
    result = _restore(db, owner, marker)
    assert result["restored"] >= 2
    assert custom_fields.get_definition(db, owner.id, definition.id) is not None
    db.refresh(tool)
    assert tool.custom_data == {str(definition.id): "90 ft-lb"}


# -- restore scenarios --------------------------------------------------------------


def test_restore_brings_back_a_wiped_inventory(db, owner, storage_stub):
    """(a) The owner's headline scenario: the whole inventory is
    deleted, and one restore brings back every tool, battery, set,
    piece, custom value and attachment — original ids, photos
    live again, tombstones lifted, bytes never destroyed."""
    from app.modules.inventory import custom_fields

    definition = custom_fields.create_definition(
        db,
        owner.id,
        inv_schemas.FieldDefinitionCreate(
            name="bin", label="Bin", field_type="text"
        ),
    )
    tag = inv_service.create_tag(db, owner.id, "red")
    tool = inv_service.create_tool(
        db,
        owner.id,
        inv_schemas.ToolCreate(
            name="Impact wrench", custom_data={str(definition.id): "B4"}
        ),
    )
    photo = _attach_photo(db, owner, tool)
    photo_key = photo["key"]
    set_tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Socket set", is_set=True)
    )
    piece = inv_service.add_set_piece(
        db, owner.id, set_tool.id, inv_schemas.SetPieceCreate(name="8mm")
    )
    battery = inv_service.create_battery(
        db, owner.id, inv_schemas.BatteryCreate(name="M18")
    )
    inv_service.update_tool(
        db, owner.id, tool.id, inv_schemas.ToolUpdate(tag_ids=[tag.id])
    )

    marker = _marker(db, owner.id, "Everything in place")
    tool_id, set_id, piece_id, battery_id = (
        tool.id,
        set_tool.id,
        piece.id,
        battery.id,
    )

    # The wipe: every record deleted through the real services.
    inv_service.delete_tool(db, owner.id, tool_id)
    inv_service.delete_tool(db, owner.id, set_id)
    inv_service.delete_battery(db, owner.id, battery_id)
    assert inv_service.list_tools(db, owner.id) == []
    # The photo's bytes were NOT destroyed — tombstoned.
    assert storage_stub == []
    tombstones = list(
        db.scalars(
            select(core_models.RetainedFile).where(
                core_models.RetainedFile.storage_key == photo_key
            )
        )
    )
    assert len(tombstones) == 1

    result = _restore(db, owner, marker)
    assert result["restored"] >= 4

    back = inv_service.get_tool(db, owner.id, tool_id)
    assert back is not None and back.name == "Impact wrench"
    assert back.custom_data == {str(definition.id): "B4"}
    # The photo is live again: on the record, URL minted, and its
    # tombstone is gone (nothing left for the purge to destroy).
    view = inv_service.serialize_tool(db, back)
    assert [a["key"] for a in view["attachments"]] == [photo_key]
    assert db.scalar(
        select(func.count(core_models.RetainedFile.id)).where(
            core_models.RetainedFile.storage_key == photo_key
        )
    ) == 0
    # Set + piece + battery back with their original ids.
    assert inv_service.get_tool(db, owner.id, set_id) is not None
    piece_back = inv_service.get_set_piece(db, owner.id, piece_id)
    assert piece_back is not None and piece_back.set_id == set_id
    assert inv_service.get_battery(db, owner.id, battery_id) is not None
    # The tag link made in the window… was applied BEFORE the
    # marker, so the link survives: deletion inverted, link kept.
    assert [t.id for t in inv_service.get_item_tags(db, owner.id, "tool", tool_id)] == [
        tag.id
    ]


def test_restore_rolls_back_an_edit(db, owner):
    """(b) An edit after the marker unwinds to the before snapshot."""
    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Torque wrench", brand="Old")
    )
    marker = _marker(db, owner.id)
    inv_service.update_tool(
        db,
        owner.id,
        tool.id,
        inv_schemas.ToolUpdate(name="Torque wrench X", brand="New"),
    )
    _restore(db, owner, marker)
    db.refresh(tool)
    assert tool.name == "Torque wrench"
    assert tool.brand == "Old"


def test_restore_removes_an_addition(db, owner):
    """(c) A record created after the marker is removed by the
    restore — and a record created BEFORE it is untouched."""
    kept = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Keeper")
    )
    marker = _marker(db, owner.id)
    added = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Mistake")
    )
    result = _restore(db, owner, marker)
    assert result["restored"] == 1
    assert inv_service.get_tool(db, owner.id, added.id) is None
    assert inv_service.get_tool(db, owner.id, kept.id) is not None


def test_pre_restore_marker_undoes_the_restore(db, owner):
    """(d) Every restore writes a pre_restore marker first:
    restoring to THAT marker replays the changes the restore
    undid (the restore-the-restore path)."""
    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Ratchet")
    )
    marker = _marker(db, owner.id, "Before the rename")
    inv_service.update_tool(
        db, owner.id, tool.id, inv_schemas.ToolUpdate(name="Ratchet Pro")
    )
    result = _restore(db, owner, marker)
    db.refresh(tool)
    assert tool.name == "Ratchet"

    pre = journal.get_marker(db, owner.id, result["pre_restore_marker_id"])
    assert pre is not None and pre.kind == "pre_restore"
    _restore(db, owner, pre)
    db.refresh(tool)
    assert tool.name == "Ratchet Pro"
    # The trail shows both restores as events.
    events = [
        e for e in _entries(db, owner.id) if e.action == "restore"
    ]
    assert len(events) == 2
    assert all(e.restorable is False for e in events)


def test_restore_leaves_borrowing_rows_alone(db, owner):
    """(e) A checkout created inside the window is shared history:
    the restore skips it, counts it, and never touches the row."""
    from app.modules.borrowing import models as borrowing_models

    marker = _marker(db, owner.id)
    row = borrowing_models.Checkout(
        owner_id=owner.id,
        item_kind="tool",
        item_id=uuid.uuid4(),
        item_name="Loaned drill",
        borrower_name="Pat",
    )
    db.add(row)
    db.commit()
    entry = _entries(db, owner.id, "checkout")
    assert len(entry) == 1 and entry[0].restorable is False

    inv_service.create_tool(db, owner.id, inv_schemas.ToolCreate(name="New"))
    result = _restore(db, owner, marker)
    assert result["not_changed"] == 1
    assert db.get(borrowing_models.Checkout, row.id) is not None


def test_restore_respects_claim_lifecycle(db, owner):
    """(f) Draft claims restore; filed claims — and anything done
    to them after filing — are never rewound."""
    from app.modules.claims import service as claims_service

    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Claimed saw")
    )
    # Both claims are born (as drafts, with their lines) BEFORE the
    # marker; everything after it is what the restore must judge.
    draft = claims_service.create_claim(db, owner, insurer_name="Acme")
    claims_service.add_line(
        db, owner, draft.id, target_kind="tool", target_id=tool.id,
        value_basis="entered", amount=250,
    )
    filed = claims_service.create_claim(db, owner, insurer_name="Beta")
    claims_service.add_line(
        db, owner, filed.id, target_kind="tool", target_id=tool.id,
        value_basis="entered", amount=250,
    )
    marker = _marker(db, owner.id, "Both drafts on file")

    # After the marker: the draft is DELETED, the other claim is
    # FILED and gains a comm entry.
    claims_service.delete_claim(db, owner, draft.id)
    claims_service.transition(db, owner, filed.id, "filed")
    claims_service.add_communication(
        db, owner, filed.id, channel="phone", summary="Adjuster called"
    )

    result = _restore(db, owner, marker)
    # The draft comes back whole — claim row and its line.
    back = claims_service.get_claim(db, owner, draft.id)
    assert back is not None and back.status == "draft"
    lines = claims_service._lines(db, draft.id)
    assert len(lines) == 1 and lines[0].target_id == tool.id
    # The filed claim is exactly as it stands: still filed, line
    # and comm intact, and its post-filing life was counted as
    # not changed (transition + comm are visibility-only entries).
    still = claims_service.get_claim(db, owner, filed.id)
    assert still is not None and still.status == "filed"
    assert len(claims_service._lines(db, filed.id)) == 1
    assert len(claims_service._comm_rows(db, filed.id)) == 1
    assert result["not_changed"] == 2


def test_poisoned_entry_aborts_the_whole_restore(db, owner):
    """(g) A record changed through the journal and then removed
    OUTSIDE it (raw SQL) poisons its update entry: the restore
    refuses, and even the clean inversions in the same run are
    rolled back — no partial state."""
    tool_a = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Poisoned")
    )
    tool_b = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Innocent")
    )
    marker = _marker(db, owner.id)
    inv_service.update_tool(
        db, owner.id, tool_a.id, inv_schemas.ToolUpdate(name="Poisoned v2")
    )
    inv_service.update_tool(
        db, owner.id, tool_b.id, inv_schemas.ToolUpdate(name="Innocent v2")
    )
    # SQLite stores UUIDs as unhyphenated hex; Postgres takes the
    # canonical form. Either way the row dies OUTSIDE the journal.
    db.execute(
        text("DELETE FROM tools WHERE id = :id"),
        {"id": tool_a.id.hex},
    )
    db.commit()
    db.expire_all()

    with pytest.raises(journal.RestoreConflict):
        _restore(db, owner, marker)
    db.expire_all()
    # Atomic: the innocent edit was NOT rolled back either.
    survivor = inv_service.get_tool(db, owner.id, tool_b.id)
    assert survivor is not None and survivor.name == "Innocent v2"


# -- markers + jobs -------------------------------------------------------------------


def test_daily_markers_only_for_active_users_once_a_day(db, owner):
    other = core_service.create_user(
        db, "quiet@example.com", "Quiet", "hunter22", ["mechanic_technician"]
    )
    inv_service.create_tool(db, owner.id, inv_schemas.ToolCreate(name="Active"))
    assert journal.run_daily_markers(db) == 1
    markers = journal.list_markers(db, owner.id)
    assert [m.kind for m in markers] == ["daily", "baseline"]
    assert journal.list_markers(db, other.id)[0].kind == "baseline"
    # Same day, no new activity: nothing more.
    assert journal.run_daily_markers(db) == 0
    # New activity earns tomorrow's marker (simulated by clearing
    # today's): the watermark moved, so exactly one more.
    inv_service.create_tool(db, owner.id, inv_schemas.ToolCreate(name="More"))
    db.execute(
        text("DELETE FROM restore_markers WHERE kind = 'daily'")
    )
    db.commit()
    assert journal.run_daily_markers(db) == 1


def test_purge_removes_only_expired_tombstones(db, owner, storage_stub):
    """(i) The purge seam destroys only tombstones older than the
    retention window; fresh ones keep their bytes."""
    now = datetime.now(timezone.utc)
    old = core_models.RetainedFile(
        user_id=owner.id, storage_key="k/old.jpg", entity_type="tool"
    )
    fresh = core_models.RetainedFile(
        user_id=owner.id, storage_key="k/new.jpg", entity_type="tool"
    )
    db.add_all([old, fresh])
    db.commit()
    db.execute(
        text("UPDATE retained_files SET deleted_at = :ts WHERE storage_key = 'k/old.jpg'"),
        {"ts": (now - timedelta(days=400)).isoformat()},
    )
    db.commit()

    assert journal.purge_expired_files(db, days=180) == 1
    assert storage_stub == ["k/old.jpg"]
    remaining = list(db.scalars(select(core_models.RetainedFile)))
    assert [r.storage_key for r in remaining] == ["k/new.jpg"]
    # Idempotent: nothing left to purge.
    assert journal.purge_expired_files(db, days=180) == 0


# -- module coverage -----------------------------------------------------------------


def test_journal_and_restore_cover_maintenance(db, owner):
    from app.modules.maintenance import service as maint_service

    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Bench grinder")
    )
    schedule = maint_service.create_schedule(
        db, owner, item_kind="tool", item_id=tool.id,
        kind="service", label="Wheel check", interval_days=90,
    )
    entry = maint_service.log_done(db, owner, schedule.id)
    marker = _marker(db, owner.id, "All maintained")

    # Merge (2026-11-04): maintenance's own journaled world is
    # schedules + their logs now — the repair cycle that used to
    # be restored here is a claim (claims' own restore coverage),
    # and the retired repair_record entity is non-restorable by
    # design (migration 0074 flipped its journal rows).
    maint_service.delete_schedule(db, owner, schedule.id)

    result = _restore(db, owner, marker)
    assert result["restored"] >= 1
    # The deleted schedule returns WITH its log history.
    back = maint_service.schedules_for_item(db, owner.id, "tool", tool.id)
    assert [s.id for s in back] == [schedule.id]
    view = maint_service.schedule_view(db, back[0])
    assert [row["id"] for row in view["log"]] == [entry.id]
    db.refresh(tool)
    assert tool.repair_state == "in_service"


def test_journal_and_restore_cover_dealers(db, owner):
    from app.modules.dealers import portal as dealer_portal
    from app.modules.dealers import service as dealer_service

    company = dealer_service.create_company(
        db, owner_id=owner.id, data={"name": "My Tool Truck"}
    )
    agent = dealer_service.create_private_agent(
        db, owner.id, {"name": "Sam", "company_id": company.id}
    )
    pref = dealer_service.add_preferred(
        db, owner.id, company_id=company.id, private_agent_id=agent.id
    )
    dealer_portal.update_profile(db, owner, {"display_name": "Sam's Tools"})
    marker = _marker(db, owner.id, "Dealer book in place")

    dealer_service.delete_company(db, company)
    assert dealer_service.get_own_private_company(db, owner.id, company.id) is None
    assert dealer_service.list_preferred(db, owner.id) == []
    db.refresh(agent)
    assert agent.company_id is None

    _restore(db, owner, marker)
    back = dealer_service.get_own_private_company(db, owner.id, company.id)
    assert back is not None and back.name == "My Tool Truck"
    prefs = dealer_service.list_preferred(db, owner.id)
    assert [p.id for p in prefs] == [pref.id]
    db.refresh(agent)
    assert agent.company_id == company.id


def test_journal_and_restore_cover_parts_tree(db, owner):
    from app.modules.parts import schemas as part_schemas
    from app.modules.parts import service as parts_service

    warehouse = parts_service.create_location(
        db, owner.id,
        part_schemas.PartLocationCreate(name="Warehouse", level="warehouse"),
    )
    aisle = parts_service.create_location(
        db, owner.id,
        part_schemas.PartLocationCreate(
            name="Aisle 3", level="aisle", parent_id=warehouse.id
        ),
    )
    part = parts_service.create_part(
        db, owner.id,
        part_schemas.PartCreate(title="Alternator", location_id=aisle.id),
    )
    marker = _marker(db, owner.id, "Parts shelved")

    parts_service.delete_part(db, owner.id, part.id)
    parts_service.delete_location(
        db, owner.id, aisle.id, part_schemas.PartLocationDelete()
    )
    parts_service.delete_location(
        db, owner.id, warehouse.id, part_schemas.PartLocationDelete()
    )
    assert parts_service.list_locations(db, owner.id) == []

    _restore(db, owner, marker)
    locations = {loc["id"]: loc for loc in parts_service.list_locations(db, owner.id)}
    assert warehouse.id in locations and aisle.id in locations
    assert locations[aisle.id]["parent_id"] == warehouse.id
    back = parts_service.get_part(db, owner.id, part.id)
    assert back is not None and back.location_id == aisle.id


def test_peer_sharing_is_visibility_only_but_configs_restore(db, owner, user_b):
    from app.modules.core import peer_sharing, sharing

    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Shared drill")
    )
    view = peer_sharing.invite(db, owner, account_number=user_b.account_number)
    grant_id = uuid.UUID(view["id"])
    entries = _entries(db, owner.id, "peer_share")
    assert len(entries) == 1 and entries[0].restorable is False

    marker = _marker(db, owner.id, "Invite pending")
    peer_sharing.accept(db, user_b, grant_id)
    peer_sharing.set_exclusions(db, owner, [tool.id], [])
    result = _restore(db, owner, marker)
    # The accepted grant is shared history: untouched, and both
    # its entries counted as not changed.
    grant = db.get(core_models.PeerShare, grant_id)
    assert grant is not None and grant.status == "accepted"
    assert result["not_changed"] >= 1
    # …but the owner's own exclusion config DID rewind.
    assert peer_sharing._excluded_tool_ids(db, owner.id) == []

    # Tier sharing config is the owner's own too: it restores.
    sharing.update_config(db, owner.id, "shop_company", True, ["brand"])
    marker2 = _marker(db, owner.id, "Sharing on")
    sharing.set_shared_items(db, owner.id, "shop_company", [tool.id])
    _restore(db, owner, marker2)
    state = sharing.group_state(db, owner.id, "shop_company")
    assert state["shared_items"] == []


def test_importer_confirm_writes_a_pre_bulk_marker(client, db, owner):
    upload = client.post(
        "/api/inventory/import/upload",
        files={"file": ("tools.csv", b"name,brand\nImported wrench,Acme\n", "text/csv")},
        data={"kind": "tool"},
        headers=auth_headers(owner),
    )
    assert upload.status_code in (200, 201), upload.text
    session_id = upload.json()["session_id"]
    confirm = client.post(
        f"/api/inventory/import/{session_id}/confirm",
        json={
            "kind": "tool",
            "mapping": {"0": "name", "1": "brand"},
            # Smart matching (2026-10-19): "Acme" is a brand-new
            # brand for this vault — the Resolve step's answer
            # ("use as new") rides along, or the confirm refuses.
            "resolutions": {"brand": {"Acme": {"action": "create"}}},
        },
        headers=auth_headers(owner),
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["imported"] == 1

    pre_bulk = [m for m in journal.list_markers(db, owner.id) if m.kind == "pre_bulk"]
    assert len(pre_bulk) == 1
    # Restoring to it unwinds the whole import.
    assert len(inv_service.list_tools(db, owner.id)) == 1
    journal.restore_to_marker(db, owner.id, pre_bulk[0], actor_id=owner.id)
    assert inv_service.list_tools(db, owner.id) == []


# -- API surface ---------------------------------------------------------------------


def test_history_api_end_to_end(client, db, owner, user_b):
    headers = auth_headers(owner)
    markers = client.get("/api/core/history/markers", headers=headers)
    assert markers.status_code == 200
    assert [m["kind"] for m in markers.json()] == ["baseline"]

    created = client.post(
        "/api/inventory",
        json={"name": "API wrench"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    tool_id = created.json()["id"]

    point = client.post(
        "/api/core/history/markers",
        json={"label": "Before the storm"},
        headers=headers,
    )
    assert point.status_code == 201
    marker_id = point.json()["id"]
    assert point.json()["label"] == "Before the storm"

    edited = client.put(
        f"/api/inventory/{tool_id}",
        json={"name": "API wrench v2"},
        headers=headers,
    )
    assert edited.status_code == 200
    deleted = client.delete(f"/api/inventory/{tool_id}", headers=headers)
    assert deleted.status_code == 204

    entries = client.get("/api/core/history/entries", headers=headers)
    assert entries.status_code == 200
    labels = [e["label"] for e in entries.json()["entries"]]
    assert "Deleted tool 'API wrench v2'" in labels
    assert "Added tool 'API wrench'" in labels
    assert all(e["actor"] == "you" for e in entries.json()["entries"])

    preview = client.get(
        "/api/core/history/restore-preview",
        params={"marker_id": marker_id},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["changes_to_undo"] == 2
    assert preview.json()["shared_not_changed"] == 0

    restored = client.post(
        "/api/core/history/restore",
        json={"marker_id": marker_id},
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] == 2
    back = client.get(f"/api/inventory/{tool_id}", headers=headers)
    assert back.status_code == 200
    assert back.json()["name"] == "API wrench"

    # Another account cannot preview or use this marker at all.
    foreign = client.get(
        "/api/core/history/restore-preview",
        params={"marker_id": marker_id},
        headers=auth_headers(user_b),
    )
    assert foreign.status_code == 404
    foreign_restore = client.post(
        "/api/core/history/restore",
        json={"marker_id": marker_id},
        headers=auth_headers(user_b),
    )
    assert foreign_restore.status_code == 404


def test_admin_restore_writes_both_trails(client, db, owner):
    """(h) An operator restoring a user's account lands in BOTH
    trails: the user's journal (restore event, actor = operator)
    and the admin audit log (user.restore)."""
    operator = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000900",
        email="op@example.com",
        name="Operator",
        password_hash="not-a-real-hash",
        is_operator=True,
    )
    db.add(operator)
    db.commit()

    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Op target")
    )
    marker = _marker(db, owner.id, "Safe point")
    inv_service.delete_tool(db, owner.id, tool.id)

    history = client.get(
        f"/api/admin/users/{owner.id}/history",
        headers=auth_headers(operator),
    )
    assert history.status_code == 200, history.text
    assert any(m["id"] == str(marker.id) for m in history.json()["markers"])
    assert any(
        e["label"] == "Deleted tool 'Op target'"
        for e in history.json()["entries"]
    )

    result = client.post(
        f"/api/admin/users/{owner.id}/history/restore",
        json={"marker_id": str(marker.id)},
        headers=auth_headers(operator),
    )
    assert result.status_code == 200, result.text
    assert result.json()["restored"] == 1
    assert inv_service.get_tool(db, owner.id, tool.id) is not None

    audit_rows = list(
        db.scalars(
            select(core_models.AuditLog).where(
                core_models.AuditLog.action == "user.restore"
            )
        )
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_user_id == operator.id
    assert audit_rows[0].detail["restored"] == 1

    events = [
        e for e in _entries(db, owner.id) if e.action == "restore"
    ]
    assert len(events) == 1
    assert events[0].actor_id == operator.id

    # Non-operators get nothing here.
    refused = client.get(
        f"/api/admin/users/{owner.id}/history",
        headers=auth_headers(owner),
    )
    assert refused.status_code == 403


def test_admin_settings_retention_roundtrip(client, db):
    operator = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000901",
        email="op2@example.com",
        name="Operator Two",
        password_hash="not-a-real-hash",
        is_operator=True,
    )
    db.add(operator)
    db.commit()
    headers = auth_headers(operator)

    view = client.get("/api/admin/settings", headers=headers)
    assert view.status_code == 200
    assert view.json()["audit_retention_days"] == 180  # the default

    saved = client.put(
        "/api/admin/settings",
        json={"audit_retention_days": 90},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["audit_retention_days"] == 90
    assert journal.retention_days(db) == 90

    refused = client.put(
        "/api/admin/settings",
        json={"audit_retention_days": 3},
        headers=headers,
    )
    assert refused.status_code == 422


def test_deleted_item_files_follow_the_record(db, owner, storage_stub, monkeypatch):
    """(j) Public behavior is unchanged by tombstoning: a deleted
    item vanishes from sharing previews and the data export
    exactly as before — and a restore brings it back to both,
    photo included, because the bytes were retained."""
    import io
    import json as json_module
    import zipfile

    from app.modules.core import export as export_service
    from app.modules.core import sharing

    monkeypatch.setattr(
        storage_module.storage, "fetch", lambda key: b"jpeg-bytes"
    )
    tool = inv_service.create_tool(
        db, owner.id, inv_schemas.ToolCreate(name="Shared saw")
    )
    _attach_photo(db, owner, tool)
    sharing.update_config(db, owner.id, "shop_company", True, ["photos"])
    sharing.set_shared_items(db, owner.id, "shop_company", [tool.id])
    marker = _marker(db, owner.id, "Shared and sound")

    preview = sharing.build_preview(db, owner.id, "shop_company")
    assert len(preview) == 1 and preview[0]["photos"]["count"] == 1

    def exported_tool_names() -> list[str]:
        archive = zipfile.ZipFile(
            io.BytesIO(export_service.build_export_zip(db, owner))
        )
        tools = json_module.loads(archive.read("tools.json"))
        return [row["name"] for row in tools]

    assert exported_tool_names() == ["Shared saw"]

    inv_service.delete_tool(db, owner.id, tool.id)
    # Gone from both surfaces, exactly as a hard delete behaved…
    assert sharing.build_preview(db, owner.id, "shop_company") == []
    assert exported_tool_names() == []
    # …but the bytes were NOT destroyed.
    assert storage_stub == []

    _restore(db, owner, marker)
    preview = sharing.build_preview(db, owner.id, "shop_company")
    assert len(preview) == 1 and preview[0]["photos"]["count"] == 1
    assert exported_tool_names() == ["Shared saw"]
