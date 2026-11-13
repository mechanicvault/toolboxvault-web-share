"""Package C (owner review round 1, items 15–17, 2026-10-19).

RULE-BASED SHARING: tier sharing gains scope rules (category |
location subtree | tag | all) resolved DYNAMICALLY at read time —
(picks ∪ rule matches) − exclusions — plus per-item exclusions
that beat both. Peer sharing generalizes the same scopes in its
withholding direction (default-include model): rules hide items
from the crew list, payload whitelist untouched.

MY INSURANCE: one profile per user (insurer, agent, policy),
claim create pre-fills insurer + policy from it and SNAPSHOTS the
agent block; later profile edits never rewrite a filed claim.
Profile is journaled/restorable, exported, and deleted with the
account.
"""

import io
import uuid
import zipfile

import pytest

from app.modules.core import journal
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"

LOCKED_PREVIEW_KEYS = {"id", "name", "brand", "model", "serial_number"}
PEER_PAYLOAD_KEYS = {
    "id",
    "name",
    "brand",
    "model",
    "category",
    "photos",
    "owner",
}


def _make_user(db, account_number: str, email: str, account_types: list[str]):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="PkgC User",
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000201", "pkgc-owner@example.com", [MECHANIC])


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000202", "pkgc-other@example.com", [MECHANIC])


def _make_tool(db, owner, **overrides) -> inventory_models.Tool:
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=overrides.pop("name", "Impact wrench"),
        brand=overrides.pop("brand", "Snap-on"),
        model=overrides.pop("model", "CT9075"),
        serial_number=overrides.pop("serial_number", "SN-123"),
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _make_battery(db, owner, **overrides) -> inventory_models.Battery:
    battery = inventory_models.Battery(
        owner_id=owner.id,
        name=overrides.pop("name", "M18 battery"),
        brand=overrides.pop("brand", "Milwaukee"),
        model=overrides.pop("model", "48-11-1850"),
        serial_number=overrides.pop("serial_number", "B-1"),
        **overrides,
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _make_node(db, owner, name: str, parent=None):
    node = inventory_models.InventoryLocation(
        owner_id=owner.id, name=name, parent_id=parent.id if parent else None
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_tag(db, owner, name: str) -> inventory_models.Tag:
    tag = inventory_models.Tag(owner_id=owner.id, name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def _tag_item(db, owner, tag, kind: str, item_id):
    db.add(
        inventory_models.ItemTag(
            owner_id=owner.id,
            tag_id=tag.id,
            item_kind=kind,
            tool_id=item_id if kind == "tool" else None,
            battery_id=item_id if kind == "battery" else None,
        )
    )
    db.commit()


def _enable(client, user, group: str = SHOP, fields=("category",)):
    resp = client.put(
        f"/api/core/sharing/{group}",
        json={"enabled": True, "fields": list(fields)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text


def _preview(client, user, group: str = SHOP) -> list[dict]:
    resp = client.get(
        f"/api/core/sharing/preview?group={group}", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _preview_ids(client, user, group: str = SHOP) -> set[str]:
    return {entry["id"] for entry in _preview(client, user, group)}


def _add_rule(client, user, group: str = SHOP, expect=201, **body):
    resp = client.post(
        f"/api/core/sharing/{group}/rules",
        json=body,
        headers=auth_headers(user),
    )
    assert resp.status_code == expect, resp.text
    return resp


def _group_state(client, user, group: str = SHOP) -> dict:
    resp = client.get("/api/core/sharing", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["recipient_group"] == group)


# -- tier rules: resolution per scope -------------------------------------------


def test_category_rule_shares_existing_items(client, db, owner):
    wrench = _make_tool(db, owner, name="Wrench", category="Wrenches")
    socket = _make_tool(db, owner, name="Socket", category="Sockets")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    assert _preview_ids(client, owner) == {str(wrench.id)}
    assert str(socket.id) not in _preview_ids(client, owner)


def test_category_rule_is_dynamic_for_future_items(client, db, owner):
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    assert _preview_ids(client, owner) == set()
    # Bought tomorrow into the shared category — shared with NO
    # further sharing action.
    late = _make_tool(db, owner, name="Late wrench", category="Wrenches")
    assert _preview_ids(client, owner) == {str(late.id)}


def test_category_matching_tolerates_case_and_padding(client, db, owner):
    tool = _make_tool(db, owner, category="wrenches")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="  Wrenches ")
    assert _preview_ids(client, owner) == {str(tool.id)}


def test_category_rule_covers_batteries(client, db, owner):
    battery = _make_battery(db, owner, category="Power cells")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Power cells")
    entries = _preview(client, owner)
    assert [e["id"] for e in entries] == [str(battery.id)]
    assert entries[0]["kind"] == "battery"


def test_location_rule_covers_the_whole_subtree(client, db, owner):
    toolbox = _make_node(db, owner, "Shop Toolbox")
    drawer = _make_node(db, owner, "Left Drawer 2", parent=toolbox)
    garage = _make_node(db, owner, "Garage")
    in_drawer = _make_tool(db, owner, name="In drawer", location_id=drawer.id)
    in_box = _make_tool(db, owner, name="In box", location_id=toolbox.id)
    elsewhere = _make_tool(db, owner, name="Elsewhere", location_id=garage.id)
    _enable(client, owner)
    _add_rule(
        client, owner, scope="location", scope_ref_id=str(toolbox.id)
    )
    assert _preview_ids(client, owner) == {str(in_drawer.id), str(in_box.id)}
    assert str(elsewhere.id) not in _preview_ids(client, owner)


def test_moving_an_item_out_of_a_shared_location_unshares_it(client, db, owner):
    toolbox = _make_node(db, owner, "Shop Toolbox")
    garage = _make_node(db, owner, "Garage")
    tool = _make_tool(db, owner, location_id=toolbox.id)
    _enable(client, owner)
    _add_rule(client, owner, scope="location", scope_ref_id=str(toolbox.id))
    assert _preview_ids(client, owner) == {str(tool.id)}
    tool.location_id = garage.id
    db.commit()
    assert _preview_ids(client, owner) == set()


def test_tag_rule_shares_tagged_items_only(client, db, owner):
    tag = _make_tag(db, owner, "loaners")
    tagged = _make_tool(db, owner, name="Tagged")
    _tag_item(db, owner, tag, "tool", tagged.id)
    untagged = _make_tool(db, owner, name="Untagged")
    _enable(client, owner)
    _add_rule(client, owner, scope="tag", scope_ref_id=str(tag.id))
    assert _preview_ids(client, owner) == {str(tagged.id)}
    assert str(untagged.id) not in _preview_ids(client, owner)


def test_all_rule_shares_everything_including_batteries(client, db, owner):
    tool = _make_tool(db, owner, name="Any tool")
    battery = _make_battery(db, owner)
    _enable(client, owner)
    _add_rule(client, owner, scope="all")
    assert _preview_ids(client, owner) == {str(tool.id), str(battery.id)}


def test_deleting_a_rule_unshares_its_items(client, db, owner):
    tool = _make_tool(db, owner, category="Wrenches")
    _enable(client, owner)
    state = _add_rule(
        client, owner, scope="category", scope_value="Wrenches"
    ).json()
    rule_id = state["rules"][0]["id"]
    assert _preview_ids(client, owner) == {str(tool.id)}
    resp = client.delete(
        f"/api/core/sharing/{SHOP}/rules/{rule_id}", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert _preview_ids(client, owner) == set()


# -- tier rules: exclusions + precedence ------------------------------------------


def test_exclusion_beats_a_rule_match(client, db, owner):
    kept = _make_tool(db, owner, name="Kept", category="Wrenches")
    withheld = _make_tool(db, owner, name="Withheld", category="Wrenches")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    resp = client.put(
        f"/api/core/sharing/{SHOP}/exclusions",
        json={"tool_ids": [str(withheld.id)], "battery_ids": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert _preview_ids(client, owner) == {str(kept.id)}
    state = _group_state(client, owner)
    assert state["excluded_items"] == [{"kind": "tool", "id": str(withheld.id)}]
    assert state["resolved_count"] == 1


def test_exclusion_beats_a_pick_too(client, db, owner):
    tool = _make_tool(db, owner, category="Wrenches")
    _enable(client, owner)
    resp = client.put(
        f"/api/core/sharing/{SHOP}/items",
        json={"tool_ids": [str(tool.id)]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert _preview_ids(client, owner) == {str(tool.id)}
    resp = client.put(
        f"/api/core/sharing/{SHOP}/exclusions",
        json={"tool_ids": [str(tool.id)], "battery_ids": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    # (picks ∪ rules) − exclusions: the exclusion is the final word.
    assert _preview_ids(client, owner) == set()


def test_exclusion_with_a_foreign_id_refuses_the_write(client, db, owner, other):
    foreign = _make_tool(db, other)
    resp = client.put(
        f"/api/core/sharing/{SHOP}/exclusions",
        json={"tool_ids": [str(foreign.id)], "battery_ids": []},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def _make_set_with_pieces(db, owner, category="Wrenches"):
    tool_set = _make_tool(
        db, owner, name="Master set", category=category, is_set=True
    )
    db.add_all(
        [
            inventory_models.SetPiece(
                owner_id=owner.id,
                set_id=tool_set.id,
                kind="core",
                name="Ratchet",
                part_number="C-1",
            ),
            inventory_models.SetPiece(
                owner_id=owner.id,
                set_id=tool_set.id,
                kind="addon",
                name="Extension bar",
                part_number="A-1",
            ),
        ]
    )
    db.commit()
    return tool_set


def test_rule_include_addons_is_honored_for_matched_sets(client, db, owner):
    tool_set = _make_set_with_pieces(db, owner)
    _enable(client, owner)
    state = _add_rule(
        client,
        owner,
        scope="category",
        scope_value="Wrenches",
        include_addons=True,
    ).json()
    entry = next(e for e in _preview(client, owner) if e["id"] == str(tool_set.id))
    assert entry["set"]["include_addons"] is True
    assert [p["name"] for p in entry["set"]["addon_pieces"]] == ["Extension bar"]
    # Flip the rule's answer off: addons leave, the set stays.
    rule_id = state["rules"][0]["id"]
    resp = client.put(
        f"/api/core/sharing/{SHOP}/rules/{rule_id}",
        json={"include_addons": False},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    entry = next(e for e in _preview(client, owner) if e["id"] == str(tool_set.id))
    assert entry["set"]["include_addons"] is False
    assert entry["set"]["addon_pieces"] == []
    assert [p["name"] for p in entry["set"]["core_pieces"]] == ["Ratchet"]


def test_a_pick_choice_outranks_a_rule_choice_for_its_set(client, db, owner):
    tool_set = _make_set_with_pieces(db, owner)
    _enable(client, owner)
    # Picked explicitly WITHOUT addons…
    resp = client.put(
        f"/api/core/sharing/{SHOP}/items",
        json={
            "tool_ids": [str(tool_set.id)],
            "set_choices": [
                {"tool_id": str(tool_set.id), "include_addons": False}
            ],
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    # …while a rule matches the same set WITH addons. The pick is
    # the more specific decision and wins.
    _add_rule(
        client,
        owner,
        scope="category",
        scope_value="Wrenches",
        include_addons=True,
    )
    entry = next(e for e in _preview(client, owner) if e["id"] == str(tool_set.id))
    assert entry["set"]["include_addons"] is False
    assert entry["set"]["addon_pieces"] == []


def test_field_config_still_gates_rule_matched_items(client, db, owner):
    tool = _make_tool(
        db, owner, category="Wrenches", notes="private note", brand="Snap-on"
    )
    _enable(client, owner, fields=())
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    entry = next(e for e in _preview(client, owner) if e["id"] == str(tool.id))
    # No optional fields chosen: the recipient gets the locked
    # identity fields and NOTHING else — rules changed WHICH items,
    # never WHICH fields.
    assert set(entry.keys()) == LOCKED_PREVIEW_KEYS


# -- tier rules: validation + state shape ------------------------------------------


def test_rule_writes_validate_their_targets(client, db, owner, other):
    foreign_node = _make_node(db, other, "Not yours")
    foreign_tag = _make_tag(db, other, "not-yours")
    _enable(client, owner)
    resp = client.post(
        f"/api/core/sharing/{SHOP}/rules",
        json={"scope": "location", "scope_ref_id": str(foreign_node.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/api/core/sharing/{SHOP}/rules",
        json={"scope": "tag", "scope_ref_id": str(foreign_tag.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/api/core/sharing/{SHOP}/rules",
        json={"scope": "category", "scope_value": "   "},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # Unknown scope names never reach the service.
    resp = client.post(
        f"/api/core/sharing/{SHOP}/rules",
        json={"scope": "brand", "scope_value": "Snap-on"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_recreating_the_same_rule_refreshes_it_instead_of_duplicating(
    client, db, owner
):
    _make_tool(db, owner, category="Wrenches")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    state = _add_rule(
        client,
        owner,
        scope="category",
        scope_value="wrenches",
        include_addons=True,
    ).json()
    assert len(state["rules"]) == 1
    assert state["rules"][0]["include_addons"] is True


def test_group_state_reports_rules_counts_and_picker_vocab(client, db, owner):
    toolbox = _make_node(db, owner, "Shop Toolbox")
    tag = _make_tag(db, owner, "loaners")
    _make_tool(db, owner, name="One", category="Wrenches", location_id=toolbox.id)
    _make_tool(db, owner, name="Two", category="Wrenches")
    _make_tool(db, owner, name="Three", category="Sockets")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    state = _group_state(client, owner)
    assert state["resolved_count"] == 2
    assert state["rules"][0]["scope_label"] == "Wrenches"
    assert state["rules"][0]["match_count"] == 2
    overview = client.get("/api/core/sharing", headers=auth_headers(owner)).json()
    assert "Wrenches" in overview["categories"]
    assert [t["name"] for t in overview["tags"]] == ["loaners"]
    assert overview["tags"][0]["id"] == str(tag.id)
    assert [loc["path"] for loc in overview["locations"]] == ["Shop Toolbox"]


def test_rules_are_per_group(client, db, owner):
    tool = _make_tool(db, owner, category="Wrenches")
    _enable(client, owner, group=SHOP)
    _enable(client, owner, group="insurance")
    _add_rule(client, owner, group=SHOP, scope="category", scope_value="Wrenches")
    assert _preview_ids(client, owner, SHOP) == {str(tool.id)}
    assert _preview_ids(client, owner, "insurance") == set()


def test_sharing_summary_counts(client, db, owner):
    _make_tool(db, owner, name="One", category="Wrenches")
    _make_tool(db, owner, name="Two", category="Wrenches")
    _enable(client, owner)
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    resp = client.get("/api/core/sharing/summary", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    shop = next(g for g in summary["groups"] if g["recipient_group"] == SHOP)
    assert shop == {
        "recipient_group": SHOP,
        "enabled": True,
        "shared_count": 2,
        "rule_count": 1,
    }
    insurance = next(
        g for g in summary["groups"] if g["recipient_group"] == "insurance"
    )
    assert insurance["enabled"] is False
    assert insurance["shared_count"] == 0
    assert summary["peer"] == {
        "given_accepted": 0,
        "given_pending": 0,
        "received_accepted": 0,
        "received_pending": 0,
    }


# -- peer withholding rules ----------------------------------------------------------


def _grant(client, owner, viewer):
    resp = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": viewer.account_number},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    grant_id = resp.json()["id"]
    resp = client.post(
        f"/api/core/sharing/peer/{grant_id}/accept",
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 204, resp.text
    return grant_id


def _peer_list_ids(client, viewer, owner) -> set[str]:
    resp = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


def _peer_search_ids(client, viewer, query: str) -> set[str]:
    resp = client.get(
        f"/api/core/sharing/peer/search?q={query}", headers=auth_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()}


def _add_peer_rule(client, owner, expect=201, **body):
    resp = client.post(
        "/api/core/sharing/peer/exclusion-rules",
        json=body,
        headers=auth_headers(owner),
    )
    assert resp.status_code == expect, resp.text
    return resp


def test_peer_category_rule_withholds_from_list_and_search(client, db, owner, other):
    visible = _make_tool(db, owner, name="Crew wrench", category="Wrenches")
    hidden = _make_tool(db, owner, name="Personal wrench", category="Personal")
    _grant(client, owner, other)
    assert _peer_list_ids(client, other, owner) == {str(visible.id), str(hidden.id)}
    _add_peer_rule(client, owner, scope="category", scope_value="Personal")
    assert _peer_list_ids(client, other, owner) == {str(visible.id)}
    assert _peer_search_ids(client, other, "wrench") == {str(visible.id)}


def test_peer_rules_are_dynamic_and_deleting_one_restores_visibility(
    client, db, owner, other
):
    _grant(client, owner, other)
    rule = _add_peer_rule(
        client, owner, scope="category", scope_value="Personal"
    ).json()
    assert rule["match_count"] == 0
    # Filed into the withheld category AFTER the rule exists —
    # withheld with no further action.
    late = _make_tool(db, owner, name="Late personal", category="Personal")
    assert _peer_list_ids(client, other, owner) == set()
    resp = client.delete(
        f"/api/core/sharing/peer/exclusion-rules/{rule['id']}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text
    assert _peer_list_ids(client, other, owner) == {str(late.id)}


def test_peer_location_rule_covers_the_subtree(client, db, owner, other):
    toolbox = _make_node(db, owner, "Shop Toolbox")
    drawer = _make_node(db, owner, "Drawer", parent=toolbox)
    hidden = _make_tool(db, owner, name="Hidden", location_id=drawer.id)
    visible = _make_tool(db, owner, name="Visible")
    _grant(client, owner, other)
    _add_peer_rule(client, owner, scope="location", scope_ref_id=str(toolbox.id))
    assert _peer_list_ids(client, other, owner) == {str(visible.id)}
    assert str(hidden.id) not in _peer_list_ids(client, other, owner)


def test_peer_rule_validation_and_payload_whitelist(client, db, owner, other):
    foreign_tag = _make_tag(db, other, "not-yours")
    tool = _make_tool(db, owner, name="Crew wrench", category="Wrenches")
    _grant(client, owner, other)
    resp = client.post(
        "/api/core/sharing/peer/exclusion-rules",
        json={"scope": "tag", "scope_ref_id": str(foreign_tag.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # 'all' is not a peer scope: withholding everything is revoke.
    resp = client.post(
        "/api/core/sharing/peer/exclusion-rules",
        json={"scope": "all"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # The visible item's payload is the pinned whitelist — rules
    # changed visibility, never the payload.
    resp = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(other)
    )
    item = next(i for i in resp.json()["items"] if i["id"] == str(tool.id))
    assert set(item.keys()) == PEER_PAYLOAD_KEYS


def test_peer_overview_carries_rules_and_vocab(client, db, owner):
    _make_tool(db, owner, category="Personal")
    _add_peer_rule(client, owner, scope="category", scope_value="Personal")
    resp = client.get("/api/core/sharing/peer", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    overview = resp.json()
    assert len(overview["exclusion_rules"]) == 1
    assert overview["exclusion_rules"][0]["scope_label"] == "Personal"
    assert overview["exclusion_rules"][0]["match_count"] == 1
    assert "Personal" in overview["categories"]


# -- my insurance ---------------------------------------------------------------------


_PROFILE = {
    "insurer_company": "Acme Mutual",
    "agent_name": "Andy Agent",
    "agent_phone": "555-0100",
    "agent_email": "andy@acme.example",
    "policy_number": "POL-123",
    "notes": "Deductible $500",
}


def _put_profile(client, user, **overrides):
    resp = client.put(
        "/api/core/insurance",
        json={**_PROFILE, **overrides},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_insurance_profile_roundtrip(client, owner):
    resp = client.get("/api/core/insurance", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_profile"] is False
    assert resp.json()["insurer_company"] == ""
    saved = _put_profile(client, owner)
    assert saved["has_profile"] is True
    assert saved["agent_name"] == "Andy Agent"
    again = client.get("/api/core/insurance", headers=auth_headers(owner)).json()
    assert again["policy_number"] == "POL-123"
    assert again["notes"] == "Deductible $500"
    updated = _put_profile(client, owner, agent_phone="555-0199")
    assert updated["agent_phone"] == "555-0199"
    # Still one profile, not a second row.
    assert client.get("/api/core/insurance", headers=auth_headers(owner)).json()[
        "agent_name"
    ] == "Andy Agent"


def test_insurance_profile_is_owner_scoped(client, owner, other):
    _put_profile(client, owner)
    resp = client.get("/api/core/insurance", headers=auth_headers(other))
    assert resp.json()["has_profile"] is False


def test_claim_create_prefills_and_snapshots_the_profile(client, owner):
    _put_profile(client, owner)
    resp = client.post("/api/disaster-claims", json={}, headers=auth_headers(owner))
    assert resp.status_code == 201, resp.text
    claim = resp.json()
    assert claim["insurer_name"] == "Acme Mutual"
    assert claim["policy_number"] == "POL-123"
    assert claim["agent_name"] == "Andy Agent"
    assert claim["agent_phone"] == "555-0100"
    assert claim["agent_email"] == "andy@acme.example"
    # The profile moves on; the claim's snapshot does not.
    _put_profile(
        client,
        owner,
        insurer_company="Other Mutual",
        agent_name="Olivia Other",
        policy_number="POL-999",
    )
    resp = client.get(f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    frozen = resp.json()
    assert frozen["insurer_name"] == "Acme Mutual"
    assert frozen["policy_number"] == "POL-123"
    assert frozen["agent_name"] == "Andy Agent"


def test_claim_create_explicit_values_win_over_the_profile(client, owner):
    _put_profile(client, owner)
    resp = client.post(
        "/api/disaster-claims",
        json={"insurer_name": "Typed Insurer", "agent_name": "Typed Agent"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    claim = resp.json()
    assert claim["insurer_name"] == "Typed Insurer"
    assert claim["agent_name"] == "Typed Agent"
    # Untouched fields still fall back to the profile.
    assert claim["policy_number"] == "POL-123"
    assert claim["agent_phone"] == "555-0100"


def test_claim_agent_snapshot_is_editable_on_the_claim_only(client, owner):
    _put_profile(client, owner)
    claim = client.post("/api/disaster-claims", json={}, headers=auth_headers(owner)).json()
    resp = client.patch(
        f"/api/disaster-claims/{claim['id']}",
        json={"agent_phone": "555-7777"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["agent_phone"] == "555-7777"
    profile = client.get("/api/core/insurance", headers=auth_headers(owner)).json()
    assert profile["agent_phone"] == "555-0100"


def test_insurance_profile_is_journaled_and_restorable(client, db, owner):
    marker = journal.create_marker(db, owner.id, kind="manual", label="before")
    _put_profile(client, owner)
    journaled = (
        db.query(core_models.ChangeJournal)
        .filter(
            core_models.ChangeJournal.user_id == owner.id,
            core_models.ChangeJournal.entity_type == "insurance_profile",
        )
        .count()
    )
    assert journaled >= 1
    # Restoring to before the profile existed removes it — the
    # profile is a first-class citizen of the audit trail.
    journal.restore_to_marker(db, owner.id, marker, actor_id=owner.id)
    resp = client.get("/api/core/insurance", headers=auth_headers(owner))
    assert resp.json()["has_profile"] is False


def test_export_includes_insurance_json(client, owner):
    _put_profile(client, owner)
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = archive.namelist()
        assert "insurance.json" in names
        payload = archive.read("insurance.json")
    import json as _json

    data = _json.loads(payload)
    assert data["profile"]["insurer_company"] == "Acme Mutual"
    assert data["profile"]["agent_email"] == "andy@acme.example"


def test_account_deletion_removes_profile_rules_and_exclusions(
    client, db, owner
):
    _put_profile(client, owner)
    _make_tool(db, owner, category="Wrenches")
    _add_rule(client, owner, scope="category", scope_value="Wrenches")
    _add_peer_rule(client, owner, scope="category", scope_value="Wrenches")
    core_service.delete_account(db, owner)
    assert (
        db.query(core_models.InsuranceProfile)
        .filter(core_models.InsuranceProfile.user_id == owner.id)
        .count()
        == 0
    )
    assert (
        db.query(core_models.ShareRule)
        .filter(core_models.ShareRule.owner_id == owner.id)
        .count()
        == 0
    )
    assert (
        db.query(core_models.PeerShareExclusionRule)
        .filter(core_models.PeerShareExclusionRule.owner_id == owner.id)
        .count()
        == 0
    )
