"""Used Parts module (blueprint §18, owner spec 2026-10-04):
customizable spare-part entries in the owner's own location tree.

Pins:
- CRUD + ownership: a foreign part/location id is a 404 on every
  verb (existence never leaks), exactly like the other modules;
- the custom-fields axis: 'part' definitions validate part values
  through the shared engine; part definitions never leak into tool
  forms and tool definitions never leak into part forms; 'both'
  keeps its tools+batteries meaning and does NOT apply to parts;
- tree rules: moves refuse cycles (under itself / under a
  descendant), foreign parents refuse, deleting a node with parts
  or children requires reassign or detach — never a silent orphan;
- subtree filtering + rollup counts: filing under a warehouse finds
  parts in its aisles and bins;
- search covers title + notes + SEARCHABLE custom values;
- convert-to-tool: a one-way COPY through inventory's service —
  core fields mapped from matching custom fields (make -> brand),
  remaining slug-matching values carried into the tool's custom
  data, photos copied into the tool's namespace, the part remains
  stamped with the link; conversion respects the inventory module
  gate and the entitlement doorway;
- parts NEVER count toward the entitlement item cap;
- module control: parts off (or a group it doesn't serve) -> 403
  module_unavailable on every surface.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.parts import models as parts_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Parts User",
        password_hash="not-a-real-hash",
        account_types=account_types,
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def mechanic(db):
    return _make_user(db, "TV-M-000301", "parts-mech@example.com", [MECHANIC])


@pytest.fixture()
def shop(db):
    return _make_user(db, "TV-S-000302", "parts-shop@example.com", [SHOP])


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000303", "parts-other@example.com", [MECHANIC])


@pytest.fixture()
def dealer(db):
    return _make_user(db, "TV-D-000304", "parts-dealer@example.com", [DEALER])


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000300", "parts-op@example.com", [MECHANIC], operator=True
    )


def _module_unavailable(response) -> bool:
    return (
        response.status_code == 403
        and response.json()["detail"]["code"] == "module_unavailable"
    )


def _location(client, user, name, level="other", parent_id=None):
    response = client.post(
        "/api/parts/locations",
        json={"name": name, "level": level, "parent_id": parent_id},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _part(client, user, **overrides):
    payload = {"title": "Alternator, reman", "quantity": 1}
    payload.update(overrides)
    response = client.post(
        "/api/parts/parts", json=payload, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _definition(client, user, *, item_type, name, label=None, field_type="text",
                searchable=True, required=False):
    response = client.post(
        "/api/inventory/field-definitions",
        json={
            "item_type": item_type,
            "name": name,
            "label": label or name.replace("_", " ").title(),
            "field_type": field_type,
            "required": required,
            "searchable": searchable,
            "options": [],
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- CRUD + ownership ---------------------------------------------------------


def test_part_crud_round_trip(client, mechanic):
    created = _part(
        client, mechanic, quantity=3, condition="Used", notes="Bench tested"
    )
    assert created["title"] == "Alternator, reman"
    assert created["quantity"] == 3
    assert created["location"] is None
    assert created["converted_tool_id"] is None

    fetched = client.get(
        f"/api/parts/parts/{created['id']}", headers=auth_headers(mechanic)
    )
    assert fetched.status_code == 200
    assert fetched.json()["notes"] == "Bench tested"

    updated = client.put(
        f"/api/parts/parts/{created['id']}",
        json={"quantity": 2, "condition": "Core"},
        headers=auth_headers(mechanic),
    )
    assert updated.status_code == 200
    assert updated.json()["quantity"] == 2
    assert updated.json()["condition"] == "Core"
    # Untouched fields survive a partial update.
    assert updated.json()["notes"] == "Bench tested"

    listed = client.get("/api/parts/parts", headers=auth_headers(mechanic))
    assert [p["id"] for p in listed.json()] == [created["id"]]

    deleted = client.delete(
        f"/api/parts/parts/{created['id']}", headers=auth_headers(mechanic)
    )
    assert deleted.status_code == 204
    assert (
        client.get(
            f"/api/parts/parts/{created['id']}", headers=auth_headers(mechanic)
        ).status_code
        == 404
    )


def test_foreign_part_ids_are_404_on_every_verb(client, mechanic, other):
    mine = _part(client, mechanic)
    headers = auth_headers(other)
    assert client.get(f"/api/parts/parts/{mine['id']}", headers=headers).status_code == 404
    assert (
        client.put(
            f"/api/parts/parts/{mine['id']}", json={"title": "Stolen"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/parts/parts/{mine['id']}", headers=headers).status_code
        == 404
    )
    # Convert: the route resolves the part owner-scoped, so a
    # foreign id is the same 404.
    assert (
        client.post(
            f"/api/parts/parts/{mine['id']}/convert-to-tool", headers=headers
        ).status_code
        == 404
    )
    # The owner's copy is untouched.
    assert (
        client.get(
            f"/api/parts/parts/{mine['id']}", headers=auth_headers(mechanic)
        ).json()["title"]
        == "Alternator, reman"
    )


def test_foreign_location_ids_are_404(client, mechanic, other):
    mine = _location(client, mechanic, "Warehouse A", "warehouse")
    headers = auth_headers(other)
    assert (
        client.put(
            f"/api/parts/locations/{mine['id']}",
            json={"name": "Hijacked"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/parts/locations/{mine['id']}", headers=headers).status_code
        == 404
    )
    # Filing a part under a foreign location refuses as not-found.
    response = client.post(
        "/api/parts/parts",
        json={"title": "X", "location_id": mine["id"]},
        headers=headers,
    )
    assert response.status_code == 404
    # Parenting under a foreign location refuses the same way.
    response = client.post(
        "/api/parts/locations",
        json={"name": "Sneaky", "parent_id": mine["id"]},
        headers=headers,
    )
    assert response.status_code == 404


def test_quantity_must_be_at_least_one(client, mechanic):
    response = client.post(
        "/api/parts/parts",
        json={"title": "Zero", "quantity": 0},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422


# -- custom-fields axis ---------------------------------------------------------


def test_part_custom_fields_validate_through_shared_engine(client, mechanic):
    definition = _definition(
        client, mechanic, item_type="part", name="part_number", label="Part number"
    )
    created = _part(
        client, mechanic, custom_data={definition["id"]: "ALT-2201-X"}
    )
    assert created["custom_data"] == {definition["id"]: "ALT-2201-X"}

    # An unknown key is refused by the engine.
    response = client.post(
        "/api/parts/parts",
        json={"title": "Bad", "custom_data": {"nope": "value"}},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422


def test_definitions_do_not_leak_across_the_axis(client, mechanic):
    part_def = _definition(client, mechanic, item_type="part", name="vin")
    tool_def = _definition(client, mechanic, item_type="tool", name="torque_spec")

    # The part form's definition list (item_type=part) holds ONLY
    # part definitions — no tool def, and no 'both' def either.
    both_def = _definition(client, mechanic, item_type="both", name="shared_note")
    part_defs = client.get(
        "/api/inventory/field-definitions?item_type=part",
        headers=auth_headers(mechanic),
    ).json()
    assert [d["id"] for d in part_defs] == [part_def["id"]]

    tool_defs = client.get(
        "/api/inventory/field-definitions?item_type=tool",
        headers=auth_headers(mechanic),
    ).json()
    tool_ids = {d["id"] for d in tool_defs}
    assert tool_def["id"] in tool_ids
    assert both_def["id"] in tool_ids  # 'both' still serves tools
    assert part_def["id"] not in tool_ids

    # A tool definition's key is refused on a part...
    response = client.post(
        "/api/parts/parts",
        json={"title": "Leak", "custom_data": {tool_def["id"]: "90"}},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422
    # ...and a 'both' definition's key is refused on a part too:
    # 'both' means tools+batteries, parts take only their own.
    response = client.post(
        "/api/parts/parts",
        json={"title": "Leak 2", "custom_data": {both_def["id"]: "note"}},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422
    # ...while a part definition's key is refused on a tool.
    response = client.post(
        "/api/inventory",
        json={"name": "Wrench", "custom_data": {part_def["id"]: "1HG..."}},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422


def test_deleting_a_definition_scrubs_the_parts_table(db, mechanic, shop):
    """A 'part' definition's values live on part records: deleting
    the definition strips the value from the owner's parts — and
    from NOTHING of another user's (the scrub is owner-scoped
    across tools, batteries AND parts; audit-trail build
    2026-10-19 rewrote the Postgres-only bulk UPDATE as an ORM
    walk so the removals are journaled, verified here
    behaviorally instead of at the SQL level)."""
    from app.modules.inventory import custom_fields, schemas as inv_schemas

    definition = custom_fields.create_definition(
        db,
        mechanic.id,
        inv_schemas.FieldDefinitionCreate(
            name="oem_number",
            label="OEM number",
            field_type="text",
            item_type="part",
        ),
    )
    key = str(definition.id)
    mine = parts_models.Part(
        owner_id=mechanic.id, title="Alternator", custom_data={key: "OEM-1"}
    )
    theirs = parts_models.Part(
        owner_id=shop.id, title="Starter", custom_data={key: "OEM-2"}
    )
    db.add_all([mine, theirs])
    db.commit()

    assert custom_fields.delete_definition(db, mechanic.id, definition.id) is True

    db.refresh(mine)
    db.refresh(theirs)
    assert mine.custom_data == {}
    assert theirs.custom_data == {key: "OEM-2"}


# -- location tree ----------------------------------------------------------------


@pytest.fixture()
def tree(client, mechanic):
    warehouse = _location(client, mechanic, "Main Warehouse", "warehouse")
    aisle = _location(client, mechanic, "Aisle 3", "aisle", warehouse["id"])
    bin12 = _location(client, mechanic, "Bin 12", "bin", aisle["id"])
    return warehouse, aisle, bin12


def test_tree_move_refuses_cycles(client, mechanic, tree):
    warehouse, aisle, bin12 = tree
    headers = auth_headers(mechanic)
    # Under itself.
    response = client.put(
        f"/api/parts/locations/{warehouse['id']}",
        json={"parent_id": warehouse["id"]},
        headers=headers,
    )
    assert response.status_code == 422
    # Under its own descendant.
    response = client.put(
        f"/api/parts/locations/{warehouse['id']}",
        json={"parent_id": bin12["id"]},
        headers=headers,
    )
    assert response.status_code == 422
    # A legal move: the bin up to the warehouse directly.
    response = client.put(
        f"/api/parts/locations/{bin12['id']}",
        json={"parent_id": warehouse["id"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] == warehouse["id"]


def test_delete_with_parts_requires_a_decision(client, mechanic, tree):
    warehouse, aisle, bin12 = tree
    _part(client, mechanic, location_id=bin12["id"])
    headers = auth_headers(mechanic)

    # Bare delete: refused with friendly copy, nothing moves.
    response = client.request(
        "DELETE", f"/api/parts/locations/{bin12['id']}", headers=headers
    )
    assert response.status_code == 422
    assert "still holds" in response.json()["detail"]
    listed = client.get("/api/parts/parts", headers=headers).json()
    assert listed[0]["location_id"] == bin12["id"]

    # Reassign: the part moves to the aisle, the bin goes.
    response = client.request(
        "DELETE",
        f"/api/parts/locations/{bin12['id']}",
        json={"reassign_to_id": aisle["id"]},
        headers=headers,
    )
    assert response.status_code == 204
    listed = client.get("/api/parts/parts", headers=headers).json()
    assert listed[0]["location_id"] == aisle["id"]
    assert listed[0]["location"]["path"] == "Main Warehouse / Aisle 3"


def test_delete_detach_moves_children_up_and_unfiles_parts(client, mechanic, tree):
    warehouse, aisle, bin12 = tree
    _part(client, mechanic, location_id=aisle["id"])
    headers = auth_headers(mechanic)
    response = client.request(
        "DELETE",
        f"/api/parts/locations/{aisle['id']}",
        json={"detach": True},
        headers=headers,
    )
    assert response.status_code == 204
    locations = {
        loc["id"]: loc
        for loc in client.get("/api/parts/locations", headers=headers).json()
    }
    # The bin stepped up to the warehouse; the part is unfiled.
    assert locations[bin12["id"]]["parent_id"] == warehouse["id"]
    listed = client.get("/api/parts/parts", headers=headers).json()
    assert listed[0]["location_id"] is None
    assert listed[0]["location"] is None


def test_delete_reassign_into_own_subtree_refused(client, mechanic, tree):
    warehouse, aisle, bin12 = tree
    _part(client, mechanic, location_id=aisle["id"])
    response = client.request(
        "DELETE",
        f"/api/parts/locations/{aisle['id']}",
        json={"reassign_to_id": bin12["id"]},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 422


def test_subtree_filter_and_rollup_counts(client, mechanic, tree):
    warehouse, aisle, bin12 = tree
    in_bin = _part(client, mechanic, title="Bin part", location_id=bin12["id"])
    in_aisle = _part(client, mechanic, title="Aisle part", location_id=aisle["id"])
    _part(client, mechanic, title="Unfiled part")
    headers = auth_headers(mechanic)

    # Filtering by the warehouse finds the whole subtree, not the
    # unfiled part.
    found = client.get(
        f"/api/parts/parts?location_id={warehouse['id']}", headers=headers
    ).json()
    assert {p["id"] for p in found} == {in_bin["id"], in_aisle["id"]}
    # The bin's part shows its full path.
    bin_view = next(p for p in found if p["id"] == in_bin["id"])
    assert bin_view["location"]["path"] == "Main Warehouse / Aisle 3 / Bin 12"

    # Rollup counts: warehouse 2 (subtree), aisle 2, bin 1.
    locations = {
        loc["name"]: loc
        for loc in client.get("/api/parts/locations", headers=headers).json()
    }
    assert locations["Main Warehouse"]["part_count"] == 2
    assert locations["Main Warehouse"]["own_count"] == 0
    assert locations["Aisle 3"]["part_count"] == 2
    assert locations["Aisle 3"]["own_count"] == 1
    assert locations["Bin 12"]["part_count"] == 1


# -- search ---------------------------------------------------------------------


def test_search_covers_title_notes_and_custom_values(client, mechanic):
    definition = _definition(
        client, mechanic, item_type="part", name="part_number", label="Part number"
    )
    _part(
        client,
        mechanic,
        title="Water pump",
        notes="Fits the 5.3",
        custom_data={definition["id"]: "WP-5531-Z"},
    )
    _part(client, mechanic, title="Oil filter")
    headers = auth_headers(mechanic)

    by_number = client.get("/api/parts/parts?q=WP-5531", headers=headers).json()
    assert [p["title"] for p in by_number] == ["Water pump"]
    by_notes = client.get("/api/parts/parts?q=5.3", headers=headers).json()
    assert [p["title"] for p in by_notes] == ["Water pump"]
    by_title = client.get("/api/parts/parts?q=filter", headers=headers).json()
    assert [p["title"] for p in by_title] == ["Oil filter"]
    # AND semantics: both terms must hit the same part.
    none = client.get("/api/parts/parts?q=water filter", headers=headers).json()
    assert none == []


def test_search_skips_non_searchable_custom_values(client, mechanic):
    definition = _definition(
        client,
        mechanic,
        item_type="part",
        name="internal_code",
        label="Internal code",
        searchable=False,
    )
    _part(client, mechanic, title="Gasket", custom_data={definition["id"]: "SECRET7"})
    found = client.get(
        "/api/parts/parts?q=SECRET7", headers=auth_headers(mechanic)
    ).json()
    assert found == []


# -- convert to tool ---------------------------------------------------------------


def test_convert_to_tool_copies_fields_and_stamps_the_part(client, mechanic, db):
    make = _definition(client, mechanic, item_type="part", name="make")
    model = _definition(client, mechanic, item_type="part", name="model")
    part_number_part = _definition(
        client, mechanic, item_type="part", name="part_number"
    )
    tool_part_number = _definition(
        client, mechanic, item_type="tool", name="part_number", label="Part number"
    )
    part = _part(
        client,
        mechanic,
        title="Impact wrench, rebuilt",
        quantity=2,
        condition="Good",
        notes="Shelf spare",
        custom_data={
            make["id"]: "Ingersoll Rand",
            model["id"]: "2235Ti",
            part_number_part["id"]: "IR-2235-PN",
        },
    )
    response = client.post(
        f"/api/parts/parts/{part['id']}/convert-to-tool",
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    tool_id = body["tool_id"]
    # The part remains, stamped with the link.
    assert body["part"]["converted_tool_id"] == tool_id
    assert body["part"]["title"] == "Impact wrench, rebuilt"

    tool = client.get(f"/api/inventory/{tool_id}", headers=auth_headers(mechanic))
    assert tool.status_code == 200
    tool = tool.json()
    assert tool["name"] == "Impact wrench, rebuilt"
    assert tool["brand"] == "Ingersoll Rand"  # make -> brand
    assert tool["model"] == "2235Ti"
    assert tool["quantity"] == 2
    # Package B: condition is dormant — never in an item payload,
    # but the conversion still preserves it on the stored record.
    assert "condition" not in tool
    assert db.get(inventory_models.Tool, uuid.UUID(tool_id)).condition == "Good"
    assert tool["notes"] == "Shelf spare"
    # The same-slug custom value carried into the tool's own field.
    assert tool["custom_data"] == {tool_part_number["id"]: "IR-2235-PN"}
    # And the tool is a normal inventory citizen.
    assert db.get(inventory_models.Tool, uuid.UUID(tool_id)) is not None


def test_convert_copies_photos_into_the_tool_namespace(
    client, mechanic, db, monkeypatch
):
    from app.core import storage as storage_module

    copied = {}

    def fake_copy(source_key, dest_key):
        copied["source"] = source_key
        copied["dest"] = dest_key
        return storage_module.StoredObject(
            key=dest_key, size_bytes=10, content_type="image/jpeg"
        )

    monkeypatch.setattr(storage_module.storage, "copy", fake_copy)
    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda key: storage_module.StoredObject(
            key=key, size_bytes=10, content_type="image/jpeg"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda key, length=512: b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    )
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_get_url",
        lambda key, expires_in=604800: f"https://files.test/{key}",
    )

    part = _part(client, mechanic)
    # Give the part a photo at the row level (the upload flow that
    # would have put it there is storage-stubbed the same way in
    # the inventory suites).
    part_row = db.get(parts_models.Part, uuid.UUID(part["id"]))
    source_key = f"{mechanic.id}/parts/{part['id']}/photo/abc-pump.jpg"
    part_row.attachments = [
        {
            "key": source_key,
            "filename": "pump.jpg",
            "kind": "photo",
            "content_type": "image/jpeg",
            "size_bytes": 10,
            "uploaded_at": "2026-10-19T00:00:00+00:00",
        }
    ]
    db.commit()

    response = client.post(
        f"/api/parts/parts/{part['id']}/convert-to-tool",
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 200, response.text
    tool_id = response.json()["tool_id"]

    # The copy moved namespaces: parts/... -> tools/...
    assert copied["source"] == source_key
    assert copied["dest"].startswith(f"{mechanic.id}/tools/{tool_id}/photo/")

    tool = client.get(
        f"/api/inventory/{tool_id}", headers=auth_headers(mechanic)
    ).json()
    assert [a["key"] for a in tool["attachments"]] == [copied["dest"]]
    # The part kept its own photo — a copy, never a move.
    part_after = client.get(
        f"/api/parts/parts/{part['id']}", headers=auth_headers(mechanic)
    ).json()
    assert [a["key"] for a in part_after["attachments"]] == [source_key]


# -- entitlement: parts never count -----------------------------------------------


def test_parts_do_not_count_toward_the_item_cap(client, mechanic, db):
    from app.modules.billing import entitlements, models as billing_models

    # Flip the launch switch on and pin the free plan's cap at 1:
    # one tool max. (The engine's own suite pins cap semantics; here
    # only the parts exclusion matters.)
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    db.add(
        billing_models.Plan(plan_key="free", name="Free", item_limit=1)
    )
    db.commit()

    headers = auth_headers(mechanic)
    tool = client.post("/api/inventory", json={"name": "Only tool"}, headers=headers)
    assert tool.status_code == 201, tool.text
    blocked = client.post(
        "/api/inventory", json={"name": "One too many"}, headers=headers
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "item_limit_reached"

    # Parts sail past the cap — a shelf of spares is not the vault.
    for index in range(3):
        created = client.post(
            "/api/parts/parts",
            json={"title": f"Spare {index}"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
    assert entitlements.can_add_tool(db, mechanic.id) is False


# -- module control -------------------------------------------------------------------


def test_module_gate_covers_parts_surfaces(client, mechanic, dealer, operator):
    # A group the module doesn't serve: 403 module_unavailable.
    assert _module_unavailable(client.get("/api/parts/parts", headers=auth_headers(dealer)))
    assert _module_unavailable(
        client.get("/api/parts/locations", headers=auth_headers(dealer))
    )
    assert _module_unavailable(client.get("/api/parts/stats", headers=auth_headers(dealer)))

    # The kill switch takes the module down for its own groups too.
    client.put(
        "/api/admin/modules/parts/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert _module_unavailable(
        client.get("/api/parts/parts", headers=auth_headers(mechanic))
    )
    client.put(
        "/api/admin/modules/parts/global",
        json={"enabled": True},
        headers=auth_headers(operator),
    )
    assert client.get("/api/parts/parts", headers=auth_headers(mechanic)).status_code == 200


def test_stats_count_records_and_units(client, mechanic):
    _part(client, mechanic, title="A", quantity=4)
    _part(client, mechanic, title="B", quantity=2)
    stats = client.get("/api/parts/stats", headers=auth_headers(mechanic)).json()
    assert stats == {"parts_count": 2, "total_units": 6}
