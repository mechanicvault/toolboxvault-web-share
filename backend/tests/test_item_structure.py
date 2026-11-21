"""Item structure package (2026-10-18): fields + sets.

Fields: quantity (money is PER UNIT — stats multiply), multi-value
model/serial lists with the primary columns kept in sync, size,
consumable, tags (vocabulary, links, filter), location vocabulary.

Sets: a set is a tool record + pieces (any piece may carry its own
price since 2026-10-25; a core piece's price never joins the set's
totals), standalone tools attach/detach as addons — including via
the create/update payloads (build-a-set from inventory) — the
list shows the set as ONE row, billing counts the set once, search
by a piece's part number finds the set, and the addon choice is
asked + stored by tier sharing, peer sharing and borrowing —
all consuming inventory.resolve_set_members.
"""

import uuid

import pytest

from app.modules.billing import entitlements
from app.modules.core import models as core_models
from app.modules.inventory import models as inv_models
from app.modules.inventory import service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, account_types=(MECHANIC,), name="Structure User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000301", "owner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "other@example.com")


def _create_tool(client, user, **overrides):
    payload = {"name": "Wrench"}
    payload.update(overrides)
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- fields ---------------------------------------------------------------------


def test_quantity_and_per_unit_money_in_stats(client, owner):
    _create_tool(
        client,
        owner,
        name="Sockets",
        quantity=3,
        purchase_price="50.00",
        msrp="100.00",
        replacement_cost="80.00",
    )
    tool = client.get("/api/inventory", headers=auth_headers(owner)).json()[0]
    assert tool["quantity"] == 3
    assert tool["purchase_price"] == "50.00"

    stats = client.get("/api/inventory/stats", headers=auth_headers(owner)).json()
    assert stats["total_items"] == 1
    # Per-unit money x quantity: 100 x 3 and 80 x 3.
    assert stats["total_market_value"] == "300.00"
    assert stats["total_replacement_cost"] == "240.00"


def test_quantity_must_be_at_least_one(client, owner):
    resp = client.post(
        "/api/inventory",
        json={"name": "Zero", "quantity": 0},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_battery_quantity_counts_in_stats(client, owner):
    resp = client.post(
        "/api/inventory/batteries",
        json={"name": "M18 5.0", "quantity": 2, "msrp": "149.00"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["quantity"] == 2
    stats = client.get("/api/inventory/stats", headers=auth_headers(owner)).json()
    assert stats["total_items"] == 1
    assert stats["total_market_value"] == "298.00"


def test_multi_value_numbers_sync_primary(client, owner):
    tool = _create_tool(
        client,
        owner,
        model_numbers=["2467-20", "2467-22"],
        serial_numbers=["S1", "S2", "S1"],  # duplicate drops out
    )
    assert tool["model"] == "2467-20"
    assert tool["model_numbers"] == ["2467-20", "2467-22"]
    assert tool["serial_number"] == "S1"
    assert tool["serial_numbers"] == ["S1", "S2"]

    updated = client.put(
        f"/api/inventory/{tool['id']}",
        json={"model_numbers": ["9999-00"]},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["model"] == "9999-00"
    assert updated.json()["model_numbers"] == ["9999-00"]


def test_single_value_seeds_the_list(client, owner):
    tool = _create_tool(client, owner, model="ABC-1", serial_number="ZZ9")
    assert tool["model_numbers"] == ["ABC-1"]
    assert tool["serial_numbers"] == ["ZZ9"]


def test_size_and_consumable_round_trip(client, owner):
    tool = _create_tool(client, owner, size="1/2 in drive", consumable=True)
    assert tool["size"] == "1/2 in drive"
    assert tool["consumable"] is True
    plain = _create_tool(client, owner, name="Plain")
    assert plain["size"] == ""
    assert plain["consumable"] is False


# -- tags -------------------------------------------------------------------------


def _create_tag(client, user, name, color="amber"):
    resp = client.post(
        "/api/inventory/tags",
        json={"name": name, "color": color},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_tag_create_dedupes_case_insensitively(client, owner):
    first = _create_tag(client, owner, "Truck Box")
    again = _create_tag(client, owner, "truck box")
    assert again["id"] == first["id"]
    listed = client.get("/api/inventory/tags", headers=auth_headers(owner)).json()
    assert len(listed) == 1


def test_tags_attach_filter_and_delete(client, owner):
    tag = _create_tag(client, owner, "Warranty 2027")
    tagged = _create_tool(client, owner, name="Tagged", tag_ids=[tag["id"]])
    _create_tool(client, owner, name="Untagged")
    assert [t["name"] for t in tagged["tags"]] == ["Warranty 2027"]

    filtered = client.get(
        f"/api/inventory/search?tag_id={tag['id']}", headers=auth_headers(owner)
    ).json()
    assert [t["name"] for t in filtered] == ["Tagged"]

    listed = client.get("/api/inventory/tags", headers=auth_headers(owner)).json()
    assert listed[0]["item_count"] == 1

    assert (
        client.delete(
            f"/api/inventory/tags/{tag['id']}", headers=auth_headers(owner)
        ).status_code
        == 204
    )
    after = client.get(
        f"/api/inventory/{tagged['id']}", headers=auth_headers(owner)
    ).json()
    assert after["tags"] == []


def test_tag_rename_conflict_refused(client, owner):
    _create_tag(client, owner, "Alpha")
    beta = _create_tag(client, owner, "Beta")
    resp = client.put(
        f"/api/inventory/tags/{beta['id']}",
        json={"name": "alpha"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_foreign_tag_id_refused_on_tool_create(client, owner, other):
    foreign = _create_tag(client, other, "Theirs")
    resp = client.post(
        "/api/inventory",
        json={"name": "Nope", "tag_ids": [foreign["id"]]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_locations_vocabulary(client, owner):
    _create_tool(client, owner, name="A", location="Truck box 2")
    _create_tool(client, owner, name="B", location="Shop shelf")
    _create_tool(client, owner, name="C", location="Truck box 2")
    locations = client.get("/api/inventory/locations", headers=auth_headers(owner))
    assert locations.json() == ["Shop shelf", "Truck box 2"]


# -- sets -------------------------------------------------------------------------


def _make_set(client, user, **overrides):
    payload = {"name": "Socket Set", "is_set": True, "purchase_price": "200.00",
               "replacement_cost": "250.00", "model": "SET-819"}
    payload.update(overrides)
    return _create_tool(client, user, **payload)


def _add_piece(client, user, set_id, **overrides):
    payload = {"kind": "core", "name": "10mm socket", "part_number": "PN-10"}
    payload.update(overrides)
    resp = client.post(
        f"/api/inventory/{set_id}/pieces", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_core_piece_price_is_accepted_and_never_rolls_up(client, owner):
    """Owner 2026-10-25: a core piece may carry its OWN price (what
    that piece cost / would cost to replace). It shows on the piece
    and NEVER changes the set's totals."""
    tool_set = _make_set(client, owner)
    piece = _add_piece(
        client, owner, tool_set["id"],
        name="12mm", part_number="PN-12", price="9.99",
    )
    assert piece["price"] == "9.99"
    # Inline editor path: a priced core piece rides the set's save.
    view = client.get(
        f"/api/inventory/{tool_set['id']}", headers=auth_headers(owner)
    ).json()
    assert view["set"]["price_total"] == "200.00"  # set price only
    resp = client.put(
        f"/api/inventory/{tool_set['id']}",
        json={
            "pieces": [
                {"id": piece["id"], "kind": "core", "name": "12mm",
                 "part_number": "PN-12", "price": "12.50"},
                {"kind": "core", "name": "14mm", "part_number": "PN-14",
                 "price": "11.00"},
            ]
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    view = client.get(
        f"/api/inventory/{tool_set['id']}", headers=auth_headers(owner)
    ).json()
    prices = {p["name"]: p["price"] for p in view["set"]["core_pieces"]}
    assert prices == {"12mm": "12.50", "14mm": "11.00"}
    # Still no rollup: two priced core pieces, set total unmoved.
    assert view["set"]["price_total"] == "200.00"
    # And the single-piece update path prices a core piece too.
    target = view["set"]["core_pieces"][0]
    resp = client.put(
        f"/api/inventory/pieces/{target['id']}",
        json={"price": "13.25"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["price"] == "13.25"


def test_build_set_from_inventory_on_create(client, db, owner, other):
    """attach_tool_ids on the CREATE payload folds existing tools
    into the new set: one inventory line, their data intact, and
    the billing count moves by the set alone."""
    ratchet = _create_tool(
        client, owner, name="Ratchet", model="R-100", purchase_price="25.00"
    )
    driver = _create_tool(
        client, owner, name="Driver", model="D-200", purchase_price="40.00"
    )
    assert entitlements.asset_count(db, owner.id) == 2
    tool_set = _create_tool(
        client, owner, name="Built set", is_set=True, purchase_price="100.00",
        attach_tool_ids=[ratchet["id"], driver["id"]],
    )
    # One line in the list — the set — with both tools inside it.
    listed = client.get("/api/inventory", headers=auth_headers(owner)).json()
    assert [t["name"] for t in listed] == ["Built set"]
    inside = {t["name"]: t for t in tool_set["set"]["attached_tools"]}
    assert set(inside) == {"Ratchet", "Driver"}
    assert inside["Ratchet"]["model"] == "R-100"
    assert inside["Ratchet"]["purchase_total"] == "25.00"
    # 2 standalone + the new set record -> the set counts ONCE.
    assert entitlements.asset_count(db, owner.id) == 1
    # A foreign id refuses the WHOLE create — nothing is saved.
    foreign = _create_tool(client, other, name="Not yours")
    resp = client.post(
        "/api/inventory",
        json={"name": "Bad set", "is_set": True,
              "attach_tool_ids": [foreign["id"]]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    names = [t["name"] for t in client.get("/api/inventory", headers=auth_headers(owner)).json()]
    assert names == ["Built set"]


def test_build_set_from_inventory_on_update_round_trip(client, db, owner):
    """The update payload's list is the desired attached set:
    adding folds a tool in; removing it restores it standalone."""
    tool_set = _make_set(client, owner)
    loose = _create_tool(
        client, owner, name="Loose wrench", model="W-9", purchase_price="15.00"
    )
    resp = client.put(
        f"/api/inventory/{tool_set['id']}",
        json={"attach_tool_ids": [loose["id"]]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    names = [t["name"] for t in client.get("/api/inventory", headers=auth_headers(owner)).json()]
    assert names == ["Socket Set"]
    assert entitlements.asset_count(db, owner.id) == 1
    # Un-pick: the tool returns as a standalone line, data intact.
    resp = client.put(
        f"/api/inventory/{tool_set['id']}",
        json={"attach_tool_ids": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    listed = client.get("/api/inventory", headers=auth_headers(owner)).json()
    by_name = {t["name"]: t for t in listed}
    assert set(by_name) == {"Socket Set", "Loose wrench"}
    assert by_name["Loose wrench"]["model"] == "W-9"
    assert by_name["Loose wrench"]["purchase_price"] == "15.00"
    assert entitlements.asset_count(db, owner.id) == 2
    # Attachments on a non-set are refused.
    resp = client.put(
        f"/api/inventory/{loose['id']}",
        json={"attach_tool_ids": [tool_set["id"]]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_pieces_require_a_set(client, owner):
    plain = _create_tool(client, owner, name="Not a set")
    resp = client.post(
        f"/api/inventory/{plain['id']}/pieces",
        json={"kind": "core", "name": "x"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_set_totals_attach_detach_and_counting(client, db, owner):
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="8mm", part_number="PN-8")
    _add_piece(client, owner, tool_set["id"], name="19mm", part_number="PN-19")
    _add_piece(
        client, owner, tool_set["id"],
        kind="addon", name="21mm", part_number="PN-21", price="45.00",
    )
    addon_tool = _create_tool(
        client, owner, name="Extension bar", purchase_price="30.00",
        quantity=2, replacement_cost="40.00",
    )

    attached = client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["attached_to_set"]["name"] == "Socket Set"

    # ONE row in the list: the set. The attached tool is inside it.
    listed = client.get("/api/inventory", headers=auth_headers(owner)).json()
    assert [t["name"] for t in listed] == ["Socket Set"]
    assert listed[0]["set_summary"] == {"core_count": 2, "addon_count": 2}

    # Totals: set 200 + addon piece 45 + attached 30 x 2 = 305.
    # Replacement: set 250 + attached 40 x 2 = 330.
    assert listed[0]["set"]["price_total"] == "305.00"
    assert listed[0]["set"]["replacement_total"] == "330.00"
    assert len(listed[0]["set"]["attached_tools"]) == 1

    # Billing counts the set ONCE; the attached tool doesn't count.
    assert entitlements.asset_count(db, owner.id) == 1
    stats = client.get("/api/inventory/stats", headers=auth_headers(owner)).json()
    assert stats["total_items"] == 1

    # Detach: standalone again, with its prices, counted again.
    detached = client.post(
        f"/api/inventory/{addon_tool['id']}/detach", headers=auth_headers(owner)
    )
    assert detached.status_code == 200, detached.text
    assert detached.json()["attached_to_set"] is None
    names = [t["name"] for t in client.get("/api/inventory", headers=auth_headers(owner)).json()]
    assert sorted(names) == ["Extension bar", "Socket Set"]
    assert entitlements.asset_count(db, owner.id) == 2


def test_attach_refusals(client, owner):
    tool_set = _make_set(client, owner)
    other_set = _make_set(client, owner, name="Second Set")
    # A set can't go into a set.
    resp = client.post(
        f"/api/inventory/{other_set['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # Nor into itself.
    resp = client.post(
        f"/api/inventory/{tool_set['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_gone_addon_piece_drops_out_of_totals(client, owner):
    tool_set = _make_set(client, owner)
    piece = _add_piece(
        client, owner, tool_set["id"],
        kind="addon", name="22mm", part_number="PN-22", price="45.00",
    )
    view = client.get(f"/api/inventory/{tool_set['id']}", headers=auth_headers(owner)).json()
    assert view["set"]["price_total"] == "245.00"
    updated = client.put(
        f"/api/inventory/pieces/{piece['id']}",
        json={"status": "sold"},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200
    view = client.get(f"/api/inventory/{tool_set['id']}", headers=auth_headers(owner)).json()
    # The piece still shows in the owner's full structure (history),
    # but the totals exclude it — gone pieces drop out of totals.
    assert len(view["set"]["addon_pieces"]) == 1
    assert view["set"]["price_total"] == "200.00"
    assert _resolved_totals(client, owner, tool_set["id"]) == "200.00"


def _resolved_totals(client, owner, set_id):
    # resolve_set_members against the test session behind the client:
    # pull the session from the app's dependency override.
    from app.core.db import get_db

    override = client.app.dependency_overrides[get_db]
    db = override()
    tool = service.get_tool(db, owner.id, uuid.UUID(set_id))
    members = service.resolve_set_members(db, tool, True)
    return str(members["price_total"])


def test_search_by_piece_part_number_finds_the_set(client, owner):
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="13mm socket", part_number="SN-13X")
    results = client.get(
        "/api/inventory/search?q=SN-13X", headers=auth_headers(owner)
    ).json()
    assert len(results) == 1
    assert results[0]["id"] == tool_set["id"]
    assert results[0]["matched_via"] == "piece"
    assert "13mm socket" in results[0]["matched_label"]


def test_search_by_attached_tool_name_finds_the_set(client, owner):
    tool_set = _make_set(client, owner)
    addon_tool = _create_tool(client, owner, name="Flex head ratchet")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    results = client.get(
        "/api/inventory/search?q=Flex head", headers=auth_headers(owner)
    ).json()
    hits = [r for r in results if r["id"] == tool_set["id"]]
    assert len(hits) == 1
    assert hits[0]["matched_via"] == "attached"


# -- sets x sharing / borrowing ---------------------------------------------------


def _enable_peer(client, owner, viewer):
    """An accepted peer grant owner -> viewer, through the real
    invite/accept API (the same path the crew list uses)."""
    invite = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": viewer.account_number},
        headers=auth_headers(owner),
    )
    assert invite.status_code == 201, invite.text
    grant_id = invite.json()["id"]
    accepted = client.post(
        f"/api/core/sharing/peer/{grant_id}/accept", headers=auth_headers(viewer)
    )
    assert accepted.status_code == 204, accepted.text


def test_peer_list_carries_set_members_and_choice(client, db, owner, other):
    _enable_peer(client, owner, other)
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="8mm", part_number="PN-8")
    _add_piece(
        client, owner, tool_set["id"],
        kind="addon", name="21mm", part_number="PN-21", price="45.00",
    )
    addon_tool = _create_tool(client, owner, name="Breaker bar")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )

    listing = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    ).json()
    names = [item["name"] for item in listing["items"]]
    # The set is ONE entry; the attached tool never appears top-level.
    assert names == ["Socket Set"]
    entry = listing["items"][0]
    assert entry["is_set"] is True
    # Default peer choice: addons included.
    assert entry["set"]["include_addons"] is True
    assert [p["part_number"] for p in entry["set"]["core_pieces"]] == ["PN-8"]
    assert [p["part_number"] for p in entry["set"]["addon_pieces"]] == ["PN-21"]
    assert [t["name"] for t in entry["set"]["attached_tools"]] == ["Breaker bar"]

    # Owner stores "keep addons home": pieces/addons vanish from the
    # member lists; the core stays.
    resp = client.put(
        "/api/core/sharing/peer/set-choices",
        json={"tool_id": tool_set["id"], "include_addons": False},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    listing = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    ).json()
    entry = listing["items"][0]
    assert entry["set"]["include_addons"] is False
    assert entry["set"]["addon_pieces"] == []
    assert entry["set"]["attached_tools"] == []
    assert len(entry["set"]["core_pieces"]) == 1


def test_tier_sharing_stores_the_addon_choice(client, owner):
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="8mm", part_number="PN-8")
    addon_tool = _create_tool(client, owner, name="Breaker bar")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    client.put(
        "/api/core/sharing/shop_company",
        json={"enabled": True, "fields": ["category", "photos"]},
        headers=auth_headers(owner),
    )
    state = client.put(
        "/api/core/sharing/shop_company/items",
        json={
            "tool_ids": [tool_set["id"]],
            "battery_ids": [],
            "set_choices": [{"tool_id": tool_set["id"], "include_addons": False}],
        },
        headers=auth_headers(owner),
    ).json()
    assert state["set_choices"] == [
        {"tool_id": tool_set["id"], "include_addons": False}
    ]
    preview = client.get(
        "/api/core/sharing/preview?group=shop_company", headers=auth_headers(owner)
    ).json()
    assert len(preview) == 1
    assert preview[0]["set"]["include_addons"] is False
    assert preview[0]["set"]["attached_tools"] == []
    assert len(preview[0]["set"]["core_pieces"]) == 1

    # Flip the choice: the attached tool rides.
    client.put(
        "/api/core/sharing/shop_company/items",
        json={
            "tool_ids": [tool_set["id"]],
            "battery_ids": [],
            "set_choices": [{"tool_id": tool_set["id"], "include_addons": True}],
        },
        headers=auth_headers(owner),
    )
    preview = client.get(
        "/api/core/sharing/preview?group=shop_company", headers=auth_headers(owner)
    ).json()
    assert preview[0]["set"]["include_addons"] is True
    assert [t["name"] for t in preview[0]["set"]["attached_tools"]] == ["Breaker bar"]


def test_borrowing_set_checkout_is_a_group(client, owner):
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="8mm", part_number="PN-8")
    addon_tool = _create_tool(client, owner, name="Breaker bar")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    checkout = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool_set["id"],
            "borrower_name": "Neighbor Nate",
            "include_addons": True,
        },
        headers=auth_headers(owner),
    )
    assert checkout.status_code == 201, checkout.text
    group_id = checkout.json()["group_id"]
    assert group_id

    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    out = overview["lent_out"]
    assert sorted(r["item_name"] for r in out) == ["Breaker bar", "Socket Set"]
    assert all(r["group_id"] == group_id for r in out)

    # Returning the SET row returns the whole bundle.
    client.post(
        f"/api/borrowing/{checkout.json()['id']}/return",
        headers=auth_headers(owner),
    )
    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    assert overview["lent_out"] == []
    assert overview["counts"]["checked_out"] == 0
    history = overview["history"]
    assert sorted(r["item_name"] for r in history) == ["Breaker bar", "Socket Set"]
    assert all(r["state"] == "returned" for r in history)


def test_borrowing_set_checkout_without_addons_is_single(client, owner):
    tool_set = _make_set(client, owner)
    addon_tool = _create_tool(client, owner, name="Breaker bar")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    checkout = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool_set["id"],
            "borrower_name": "Neighbor Nate",
            "include_addons": False,
        },
        headers=auth_headers(owner),
    )
    assert checkout.status_code == 201, checkout.text
    assert checkout.json()["group_id"] is None
    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    assert [r["item_name"] for r in overview["lent_out"]] == ["Socket Set"]


# -- attachments: per-kind acceptance + email -------------------------------------

from app.core import storage as storage_module  # noqa: E402


def _stub_put(monkeypatch):
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )


def _upload_url(client, user, tool_id, *, kind, content_type, size=1000):
    return client.post(
        f"/api/inventory/{tool_id}/upload-url",
        json={
            "filename": "file.bin",
            "content_type": content_type,
            "kind": kind,
            "size_bytes": size,
        },
        headers=auth_headers(user),
    )


def test_document_kind_accepts_files_and_images(client, owner, monkeypatch):
    _stub_put(monkeypatch)
    tool = _create_tool(client, owner)
    # Owner clarification 2026-10-18: documents/receipts accept real
    # document files AND photos of documents.
    for content_type in (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "image/jpeg",
    ):
        for kind in ("document", "receipt"):
            resp = _upload_url(
                client, owner, tool["id"], kind=kind, content_type=content_type
            )
            assert resp.status_code == 200, (kind, content_type, resp.text)


def test_photo_kind_is_image_only_and_exe_refused_everywhere(client, owner, monkeypatch):
    _stub_put(monkeypatch)
    tool = _create_tool(client, owner)
    # A PDF is refused in the Photos picker...
    resp = _upload_url(client, owner, tool["id"], kind="photo", content_type="application/pdf")
    assert resp.status_code == 422
    # ...and an executable is refused for EVERY kind.
    for kind in ("photo", "document", "receipt"):
        resp = _upload_url(
            client, owner, tool["id"], kind=kind, content_type="application/x-msdownload"
        )
        assert resp.status_code == 422, kind


def test_size_caps_follow_the_kind(client, owner, monkeypatch):
    _stub_put(monkeypatch)
    tool = _create_tool(client, owner)
    # Photos keep the 10 MB limit; documents/receipts get 25 MB.
    resp = _upload_url(
        client, owner, tool["id"], kind="photo",
        content_type="image/jpeg", size=11 * 1024 * 1024,
    )
    assert resp.status_code == 422
    resp = _upload_url(
        client, owner, tool["id"], kind="document",
        content_type="application/pdf", size=20 * 1024 * 1024,
    )
    assert resp.status_code == 200, resp.text
    resp = _upload_url(
        client, owner, tool["id"], kind="document",
        content_type="application/pdf", size=26 * 1024 * 1024,
    )
    assert resp.status_code == 422


def _attach_document(client, user, tool_id, monkeypatch, filename="invoice.pdf"):
    _stub_put(monkeypatch)
    resp = _upload_url(
        client, user, tool_id, kind="document", content_type="application/pdf"
    )
    assert resp.status_code == 200, resp.text
    key = resp.json()["key"]
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
        f"/api/inventory/{tool_id}/attachments",
        json={"key": key, "filename": filename},
        headers=auth_headers(user),
    )
    assert attached.status_code == 200, attached.text
    return key


def test_email_attachment_owner_scoped_and_recorded(client, db, owner, other, monkeypatch):
    from app.modules.core import models as core_models

    tool = _create_tool(client, owner)
    key = _attach_document(client, owner, tool["id"], monkeypatch)
    monkeypatch.setattr(
        storage_module.storage, "fetch", lambda k: b"%PDF-fake-bytes"
    )

    # Someone else's item: refused (the record isn't theirs).
    resp = client.post(
        f"/api/inventory/{tool['id']}/attachments/email",
        json={"key": key, "recipient": "crew@example.com"},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404, resp.text

    # A key that isn't on the item: refused.
    resp = client.post(
        f"/api/inventory/{tool['id']}/attachments/email",
        json={"key": f"{owner.id}/tools/{tool['id']}/document/nope.pdf", "recipient": "crew@example.com"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text

    sent = client.post(
        f"/api/inventory/{tool['id']}/attachments/email",
        json={"key": key, "recipient": "crew@example.com"},
        headers=auth_headers(owner),
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["sent"] is True
    assert sent.json()["kind"] == "document"

    outbox = db.query(core_models.EmailOutbox).all()
    assert len(outbox) == 1
    row = outbox[0]
    assert row.recipient == "crew@example.com"
    assert row.kind == "attachment_share"
    # The drill record proves the file rode along (name + size; the
    # bytes themselves are never persisted).
    assert "invoice.pdf" in row.body
    assert "Attachment:" in row.body


# -- export + deletion carry the full structure -------------------------------------


def test_export_includes_full_set_structure(client, owner):
    tool_set = _make_set(client, owner)
    _add_piece(client, owner, tool_set["id"], name="8mm", part_number="PN-8")
    _add_piece(
        client, owner, tool_set["id"],
        kind="addon", name="21mm", part_number="PN-21", price="45.00",
    )
    addon_tool = _create_tool(client, owner, name="Extension bar")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    import io
    import json
    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    tools = json.loads(archive.read("tools.json"))
    exported_set = next(t for t in tools if t["id"] == tool_set["id"])
    assert exported_set["is_set"] is True
    assert {p["part_number"] for p in exported_set["set"]["core_pieces"]} == {"PN-8"}
    assert {p["part_number"] for p in exported_set["set"]["addon_pieces"]} == {"PN-21"}
    assert [t["name"] for t in exported_set["set"]["attached_tools"]] == ["Extension bar"]


def test_account_deletion_with_sets_and_dealers_data(client, db, owner):
    from app.modules.core import models as core_models
    from app.modules.dealers import models as dealer_models
    from app.modules.inventory import models as inv_models

    resp = client.post(
        "/api/dealers/companies",
        json={"name": "Mine", "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    company = resp.json()

    tool_set = _make_set(client, owner, dealer_company_id=company["id"])
    _add_piece(client, owner, tool_set["id"])
    addon_tool = _create_tool(client, owner, name="Attached")
    client.post(
        f"/api/inventory/{addon_tool['id']}/attach-to-set",
        json={"set_id": tool_set["id"]},
        headers=auth_headers(owner),
    )
    _create_tag(client, owner, "Doomed tag")

    deleted = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(owner),
    )
    assert deleted.status_code == 204, deleted.text

    assert db.query(core_models.User).filter_by(id=owner.id).first() is None
    assert db.query(inv_models.Tool).count() == 0
    assert db.query(inv_models.SetPiece).count() == 0
    assert db.query(inv_models.Tag).count() == 0
    assert db.query(dealer_models.DealerCompany).filter(
        dealer_models.DealerCompany.owner_id == owner.id
    ).count() == 0


def test_rebuy_fields_round_trip(client, owner):
    """Audit A7: the consumable flag's payload — store / website /
    SKU / notes ride create, read and update like any tool field,
    and default empty on tools that never set them."""
    tool = _create_tool(
        client,
        owner,
        name="Cutting discs",
        consumable=True,
        rebuy_store="Fleet Farm",
        rebuy_url="https://www.fleetfarm.com",
        rebuy_sku="FF-009988",
        rebuy_notes="Buy the 10-pack; the singles are overpriced.",
    )
    assert tool["rebuy_store"] == "Fleet Farm"
    assert tool["rebuy_url"] == "https://www.fleetfarm.com"
    assert tool["rebuy_sku"] == "FF-009988"
    assert tool["rebuy_notes"].startswith("Buy the 10-pack")
    plain = _create_tool(client, owner, name="Plain")
    assert plain["rebuy_store"] == ""
    assert plain["rebuy_url"] == ""
    assert plain["rebuy_sku"] == ""
    assert plain["rebuy_notes"] == ""
    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={"rebuy_store": "Fastenal"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rebuy_store"] == "Fastenal"
    # Untouched rebuy fields survive a partial update.
    assert resp.json()["rebuy_sku"] == "FF-009988"
