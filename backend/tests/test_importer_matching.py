"""Importer smart value matching (2026-10-19, Ryan's spec).

Pins: the normalization table (case / punctuation / company-suffix
folding); normalized-exact matches apply SILENTLY but are LISTED
in the plan and the run summaries; fuzzy candidates ALWAYS ask —
the standing trap is Mac Tools vs Matco Tools, two different
companies a similarity score cannot tell apart, so BOTH are
offered and nothing imports until the user picks; one answer fans
out across every row carrying the value; "create" as an explicit
answer mints a private dealer company / location tree node;
answers are REMEMBERED per user (learned mappings), pre-answer the
next import, and deleting one in Settings makes the importer ask
again; locations resolve against the Package B tree by name or by
path.
"""

import io
import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.dealers import service as dealers_service
from app.modules.inventory import importer, matching
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Match User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def mechanic(db):
    return _make_user(db, "TV-M-000401", "match-mech@example.com")


@pytest.fixture()
def other_mechanic(db):
    return _make_user(db, "TV-M-000402", "match-other@example.com")


@pytest.fixture()
def matco(db):
    return dealers_service.create_company(
        db, owner_id=None, data={"name": "Matco Tools"}
    )


def _upload(client, user, data: bytes, kind="tool"):
    response = client.post(
        "/api/inventory/import/upload",
        files={"file": ("tools.csv", io.BytesIO(data), "text/csv")},
        data={"kind": kind},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def _resolve(client, user, session_id, mapping, kind="tool"):
    return client.post(
        f"/api/inventory/import/{session_id}/resolve",
        json={"kind": kind, "mapping": mapping},
        headers=auth_headers(user),
    )


def _run(client, user, session_id, mapping, resolutions=None, confirm=False):
    return client.post(
        f"/api/inventory/import/{session_id}/{'confirm' if confirm else 'dry-run'}",
        json={
            "kind": "tool",
            "mapping": mapping,
            "skip_duplicates": True,
            "resolutions": resolutions or {},
        },
        headers=auth_headers(user),
    )


def _tools(client, user):
    response = client.get("/api/inventory", headers=auth_headers(user))
    assert response.status_code == 200
    return response.json()


# -- normalization -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Matco Tools", "matco tools"),
        ("matco tools", "matco tools"),
        ("Matco Tools, Inc.", "matco tools"),
        ("MATCO INCORPORATED", "matco"),
        ("Matco Tools Inc LLC", "matco tools"),
        ("GearWrench LLC", "gearwrench"),
        ("The Home Depot", "home depot"),
        ("Snap-on", "snap on"),
        ("A & B Co.", "a b"),
        ("  Husky  ", "husky"),
        ("Mac Tools", "mac tools"),
        ("SK Hand Tool Corporation", "sk hand tool"),
    ],
)
def test_normalize_match_value(raw, expected):
    assert matching.normalize_match_value(raw) == expected


# -- tier 1: silent but listed ---------------------------------------------------


def test_exact_match_is_silent_but_listed(client, mechanic, matco):
    data = b"Name,Dealer\nWrench,matco tools inc.\nHammer,MATCO TOOLS\n"
    mapping = {"0": "name", "1": "dealer_name"}
    session_id = _upload(client, mechanic, data)

    plan = _resolve(client, mechanic, session_id, mapping).json()
    entries = {(e["field"], e["raw"]): e for e in plan["entries"]}
    for raw in ("matco tools inc.", "MATCO TOOLS"):
        entry = entries[("dealer_name", raw)]
        assert entry["status"] == "auto"
        assert entry["source"] == "exact"
        assert entry["resolution"]["target_id"] == str(matco.id)
    assert plan["unresolved"] == 0

    # No answers needed — and the applied mappings are LISTED.
    dry = _run(client, mechanic, session_id, mapping)
    assert dry.status_code == 200
    applied = {
        (m["field"], m["raw"]): m for m in dry.json()["mappings"]
    }
    assert applied[("dealer_name", "matco tools inc.")]["source"] == "exact"
    assert applied[("dealer_name", "matco tools inc.")]["target_label"] == "Matco Tools"
    assert applied[("dealer_name", "matco tools inc.")]["rows"] == 1
    assert applied[("dealer_name", "MATCO TOOLS")]["rows"] == 1

    summary = _run(client, mechanic, session_id, mapping, confirm=True).json()
    assert summary["imported"] == 2
    assert {t["dealer_company_id"] for t in _tools(client, mechanic)} == {
        str(matco.id)
    }


# -- tier 2: fuzzy ALWAYS asks (the Mac / Matco trap) ----------------------------


def test_fuzzy_never_merges_silently_mac_vs_matco(client, mechanic, db, matco):
    mac = dealers_service.create_company(
        db, owner_id=None, data={"name": "Mac Tools"}
    )
    data = b"Name,Dealer\nWrench,Mac Tool\nDriver,matco\n"
    mapping = {"0": "name", "1": "dealer_name"}
    session_id = _upload(client, mechanic, data)

    plan = _resolve(client, mechanic, session_id, mapping).json()
    entry = next(e for e in plan["entries"] if e["raw"] == "Mac Tool")
    assert entry["status"] == "ask"
    # BOTH lookalikes are offered — a score never picks between them.
    offered = {c["label"] for c in entry["candidates"]}
    assert {"Mac Tools", "Matco Tools"} <= offered
    assert plan["unresolved"] == 2

    # No answer, no import — dry run AND confirm both refuse.
    for confirm in (False, True):
        refused = _run(client, mechanic, session_id, mapping, confirm=confirm)
        assert refused.status_code == 422
        assert "Mac Tool" in refused.json()["detail"]
    assert _tools(client, mechanic) == []

    resolutions = {
        "dealer_name": {
            "Mac Tool": {"action": "map", "target_id": str(mac.id)},
            "matco": {"action": "map", "target_id": str(matco.id)},
        }
    }
    summary = _run(
        client, mechanic, session_id, mapping, resolutions, confirm=True
    ).json()
    assert summary["imported"] == 2
    by_name = {t["name"]: t for t in _tools(client, mechanic)}
    assert by_name["Wrench"]["dealer_company_id"] == str(mac.id)
    assert by_name["Driver"]["dealer_company_id"] == str(matco.id)


def test_decision_fans_out_across_all_rows(client, mechanic, matco):
    data = (
        b"Name,Dealer\nA,matco\nB,matco\nC,matco\n"
    )
    mapping = {"0": "name", "1": "dealer_name"}
    session_id = _upload(client, mechanic, data)
    resolutions = {
        "dealer_name": {"matco": {"action": "map", "target_id": str(matco.id)}}
    }
    dry = _run(client, mechanic, session_id, mapping, resolutions).json()
    applied = {(m["field"], m["raw"]): m for m in dry["mappings"]}
    assert applied[("dealer_name", "matco")]["rows"] == 3
    summary = _run(
        client, mechanic, session_id, mapping, resolutions, confirm=True
    ).json()
    assert summary["imported"] == 3
    assert {t["dealer_company_id"] for t in _tools(client, mechanic)} == {
        str(matco.id)
    }


# -- tier 3 + explicit create ------------------------------------------------------


def test_dealer_create_new_mints_a_private_company(client, mechanic, db, matco):
    data = b"Name,Dealer\nWrench,Overby Mobile Service\n"
    mapping = {"0": "name", "1": "dealer_name"}
    session_id = _upload(client, mechanic, data)
    plan = _resolve(client, mechanic, session_id, mapping).json()
    entry = plan["entries"][0]
    assert entry["status"] == "ask"

    resolutions = {"dealer_name": {"Overby Mobile Service": {"action": "create"}}}
    summary = _run(
        client, mechanic, session_id, mapping, resolutions, confirm=True
    ).json()
    assert summary["imported"] == 1
    company = (
        db.query(dealer_models.DealerCompany)
        .filter(dealer_models.DealerCompany.name == "Overby Mobile Service")
        .first()
    )
    assert company is not None
    assert company.owner_id == mechanic.id
    assert company.is_directory is False
    tool = _tools(client, mechanic)[0]
    assert tool["dealer_company_id"] == str(company.id)


def test_unanswered_new_brand_blocks_until_answered(client, mechanic):
    data = b"Name,Brand\nWrench,NewBrand\n"
    mapping = {"0": "name", "1": "brand"}
    session_id = _upload(client, mechanic, data)
    # Tier 3: nothing existing to confuse it with — the plan asks
    # with an empty candidate list (create new, or leave unset).
    plan = _resolve(client, mechanic, session_id, mapping).json()
    assert plan["entries"][0]["status"] == "ask"
    assert plan["entries"][0]["candidates"] == []
    assert _run(client, mechanic, session_id, mapping).status_code == 422
    resolutions = {"brand": {"NewBrand": {"action": "create"}}}
    summary = _run(
        client, mechanic, session_id, mapping, resolutions, confirm=True
    ).json()
    assert summary["imported"] == 1
    assert _tools(client, mechanic)[0]["brand"] == "NewBrand"


# -- brand / category / tags ------------------------------------------------------


def test_brand_maps_to_the_canonical_spelling(client, mechanic):
    created = client.post(
        "/api/inventory",
        json={"name": "Old Wrench", "brand": "Snap-on"},
        headers=auth_headers(mechanic),
    )
    assert created.status_code == 201
    data = b"Name,Brand\nNew Wrench,Snapon\n"
    mapping = {"0": "name", "1": "brand"}
    session_id = _upload(client, mechanic, data)
    plan = _resolve(client, mechanic, session_id, mapping).json()
    entry = plan["entries"][0]
    assert entry["status"] == "ask"
    assert {c["label"] for c in entry["candidates"]} == {"Snap-on"}
    resolutions = {
        "brand": {"Snapon": {"action": "map", "target_value": "Snap-on"}}
    }
    _run(client, mechanic, session_id, mapping, resolutions, confirm=True)
    brands = {t["name"]: t["brand"] for t in _tools(client, mechanic)}
    assert brands["New Wrench"] == "Snap-on"


def test_category_unset_and_tag_resolution(client, mechanic, db):
    inventory_service.create_tag(db, mechanic.id, "truck")
    db.commit()
    data = b"Name,Category,Tags\nWrench,Power Tools,Truck; shop\n"
    mapping = {"0": "name", "1": "category", "2": "tags"}
    session_id = _upload(client, mechanic, data)
    plan = _resolve(client, mechanic, session_id, mapping).json()
    by_raw = {(e["field"], e["raw"]): e for e in plan["entries"]}
    # "Truck" is the owner's existing tag spelled differently:
    # normalized-exact -> automatic, canonicalized to "truck".
    assert by_raw[("tags", "Truck")]["status"] == "auto"
    assert by_raw[("tags", "Truck")]["resolution"]["target_value"] == "truck"
    resolutions = {
        "category": {"Power Tools": {"action": "unset"}},
        "tags": {"shop": {"action": "create"}},
    }
    _run(client, mechanic, session_id, mapping, resolutions, confirm=True)
    tool = next(t for t in _tools(client, mechanic) if t["name"] == "Wrench")
    assert tool["category"] == ""
    assert {tag["name"] for tag in tool["tags"]} == {"truck", "shop"}


# -- locations resolve against the tree -------------------------------------------


@pytest.fixture()
def shop_tree(db, mechanic):
    root = inventory_service.create_location_node(
        db, mechanic.id, name="Shop Toolbox"
    )
    child = inventory_service.create_location_node(
        db, mechanic.id, name="Drawer 1", parent_id=root.id
    )
    return root, child


def test_location_matches_node_by_name_and_path(client, mechanic, shop_tree):
    root, child = shop_tree
    data = b"Name,Location\nWrench,Drawer 1\nHammer,Shop Toolbox / Drawer 1\n"
    mapping = {"0": "name", "1": "location"}
    session_id = _upload(client, mechanic, data)
    plan = _resolve(client, mechanic, session_id, mapping).json()
    by_raw = {e["raw"]: e for e in plan["entries"]}
    assert by_raw["Drawer 1"]["status"] == "auto"
    assert by_raw["Drawer 1"]["resolution"]["target_id"] == str(child.id)
    assert by_raw["Shop Toolbox / Drawer 1"]["status"] == "auto"
    assert by_raw["Shop Toolbox / Drawer 1"]["resolution"]["target_id"] == str(
        child.id
    )
    _run(client, mechanic, session_id, mapping, confirm=True)
    tools = {t["name"]: t for t in _tools(client, mechanic)}
    for name in ("Wrench", "Hammer"):
        assert tools[name]["location_id"] == str(child.id)
        assert tools[name]["location"] == "Shop Toolbox / Drawer 1"


def test_location_create_under_chosen_parent(client, mechanic, shop_tree, db):
    root, _child = shop_tree
    data = b"Name,Location\nWrench,Bottom Drawer\n"
    mapping = {"0": "name", "1": "location"}
    session_id = _upload(client, mechanic, data)
    resolutions = {
        "location": {
            "Bottom Drawer": {"action": "create", "parent_id": str(root.id)}
        }
    }
    _run(client, mechanic, session_id, mapping, resolutions, confirm=True)
    tool = _tools(client, mechanic)[0]
    assert tool["location"] == "Shop Toolbox / Bottom Drawer"
    node = inventory_service.get_location_node(
        db, mechanic.id, uuid.UUID(tool["location_id"])
    )
    assert node is not None
    assert node.parent_id == root.id


# -- learned answers ----------------------------------------------------------------


CSV_MATCO_LOOSE = b"Name,Dealer\nWrench,matco\n"
DEALER_MAPPING = {"0": "name", "1": "dealer_name"}


def _learn_matco(client, mechanic, matco):
    session_id = _upload(client, mechanic, CSV_MATCO_LOOSE)
    resolutions = {
        "dealer_name": {"matco": {"action": "map", "target_id": str(matco.id)}}
    }
    summary = _run(
        client, mechanic, session_id, DEALER_MAPPING, resolutions, confirm=True
    )
    assert summary.status_code == 200
    return resolutions


def test_learned_answer_pre_answers_the_next_import(client, mechanic, matco):
    _learn_matco(client, mechanic, matco)

    learned = client.get(
        "/api/inventory/import/learned", headers=auth_headers(mechanic)
    )
    assert learned.status_code == 200
    rows = learned.json()
    assert len(rows) == 1
    assert rows[0]["field"] == "dealer_name"
    assert rows[0]["raw_value"] == "matco"
    assert rows[0]["target_label"] == "Matco Tools"

    # Second import: pre-answered (listed as learned), no decision
    # needs sending at all.
    session_id = _upload(client, mechanic, CSV_MATCO_LOOSE)
    plan = _resolve(client, mechanic, session_id, DEALER_MAPPING).json()
    entry = plan["entries"][0]
    assert entry["status"] == "auto"
    assert entry["source"] == "learned"
    dry = _run(client, mechanic, session_id, DEALER_MAPPING)
    assert dry.status_code == 200
    assert dry.json()["mappings"][0]["source"] == "learned"
    summary = _run(
        client, mechanic, session_id, DEALER_MAPPING, confirm=True
    ).json()
    assert summary["imported"] == 1


def test_deleting_a_learned_answer_makes_it_ask_again(client, mechanic, matco):
    _learn_matco(client, mechanic, matco)
    rows = client.get(
        "/api/inventory/import/learned", headers=auth_headers(mechanic)
    ).json()
    deleted = client.delete(
        f"/api/inventory/import/learned/{rows[0]['id']}",
        headers=auth_headers(mechanic),
    )
    assert deleted.status_code == 204

    session_id = _upload(client, mechanic, CSV_MATCO_LOOSE)
    plan = _resolve(client, mechanic, session_id, DEALER_MAPPING).json()
    assert plan["entries"][0]["status"] == "ask"
    assert _run(client, mechanic, session_id, DEALER_MAPPING).status_code == 422


def test_learned_answers_are_owner_scoped(client, mechanic, other_mechanic, matco):
    _learn_matco(client, mechanic, matco)
    # The other user's importer learned nothing from my answers.
    assert (
        client.get(
            "/api/inventory/import/learned",
            headers=auth_headers(other_mechanic),
        ).json()
        == []
    )
    session_id = _upload(client, other_mechanic, CSV_MATCO_LOOSE)
    plan = _resolve(client, other_mechanic, session_id, DEALER_MAPPING).json()
    assert plan["entries"][0]["status"] == "ask"
    # And they cannot delete my remembered answer.
    rows = client.get(
        "/api/inventory/import/learned", headers=auth_headers(mechanic)
    ).json()
    response = client.delete(
        f"/api/inventory/import/learned/{rows[0]['id']}",
        headers=auth_headers(other_mechanic),
    )
    assert response.status_code == 404


def test_learned_writes_are_journaled(client, mechanic, matco, db):
    _learn_matco(client, mechanic, matco)
    entries = (
        db.query(core_models.ChangeJournal)
        .filter(
            core_models.ChangeJournal.user_id == mechanic.id,
            core_models.ChangeJournal.entity_type == "import_value_mapping",
        )
        .all()
    )
    assert entries, "the learned answer should land in the audit trail"
    assert any(e.action == "create" for e in entries)


def test_decision_pointing_at_a_foreign_company_is_refused(
    client, mechanic, other_mechanic, db
):
    # A company only the OTHER user can see (their private one).
    foreign = dealers_service.create_company(
        db, owner_id=other_mechanic.id, data={"name": "Other's Private Co"}
    )
    session_id = _upload(client, mechanic, CSV_MATCO_LOOSE)
    resolutions = {
        "dealer_name": {"matco": {"action": "map", "target_id": str(foreign.id)}}
    }
    refused = _run(client, mechanic, session_id, DEALER_MAPPING, resolutions)
    assert refused.status_code == 422


def test_override_of_an_exact_match_is_honored_and_learned(
    client, mechanic, matco
):
    data = b"Name,Dealer\nWrench,Matco Tools\n"
    session_id = _upload(client, mechanic, data)
    # "Matco Tools" would match automatically; the user says
    # leave it unset instead — the override wins and is learned.
    resolutions = {"dealer_name": {"Matco Tools": {"action": "unset"}}}
    _run(client, mechanic, session_id, DEALER_MAPPING, resolutions, confirm=True)
    assert _tools(client, mechanic)[0]["dealer_company_id"] is None
    rows = client.get(
        "/api/inventory/import/learned", headers=auth_headers(mechanic)
    ).json()
    assert rows[0]["action"] == "unset"
