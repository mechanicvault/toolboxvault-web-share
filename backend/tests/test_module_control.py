"""Module control (module doctrine, owner 2026-10-18): every feature
is a module the operator controls — a global switch plus a per-group
assignment, stored in module_state / module_access and enforced by
require_module on the module route trees.

These tests pin:
- the SEEDED DEFAULTS reproduce the pre-doctrine access matrix
  exactly (per group and per union) — the test database starts with
  EMPTY control tables, so this also pins the manifest fallback;
- 403s from a module gate carry detail.code == "module_unavailable";
- the operator surface is operator-only (403 for signed-in
  non-operators, 401 anonymous);
- the kill switch and group (un)assignment take effect immediately;
- dependency blocking: inventory off ⇒ shared_tools ineffective even
  where assigned, its data routes 403, and the matrix says why;
- graph validation flags unknown deps and cycles without the
  service ever calling a broken module usable;
- legacy no-group accounts are untouched: core keeps working and
  the one-time group pick still unlocks modules afterwards.
"""

import uuid

import pytest
from fastapi import APIRouter

from app.core.deps import CurrentUser  # noqa: F401  (documents the DTO home)
from app.modules.core import models as core_models
from app.modules.core import module_control
from app.modules.registry import validate_feature_modules
from app.modules.types import ModuleManifest
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"


@pytest.fixture(autouse=True)
def _peer_tables(db):
    # Peer endpoints read/write these; same pattern as
    # test_peer_sharing.py (per-file tables, shared fixture list
    # stays put). Notifications: a successful invite generates one.
    # Page layouts: the legacy-account test reads a core layout.
    bind = db.get_bind()
    core_models.PeerShare.__table__.create(bind=bind, checkfirst=True)
    core_models.PeerShareExclusion.__table__.create(bind=bind, checkfirst=True)
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)
    core_models.UserPageLayout.__table__.create(bind=bind, checkfirst=True)


def _make_user(db, account_number, email, account_types, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Control User",
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
    return _make_user(db, "TV-M-000201", "mech@example.com", [MECHANIC])


@pytest.fixture()
def shop(db):
    return _make_user(db, "TV-S-000202", "shop@example.com", [SHOP])


@pytest.fixture()
def dealer(db):
    return _make_user(db, "TV-D-000203", "dealer@example.com", [DEALER])


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000209", "op@example.com", [MECHANIC], operator=True
    )


def _module_unavailable(response) -> bool:
    return (
        response.status_code == 403
        and response.json()["detail"]["code"] == "module_unavailable"
    )


# -- the default matrix -------------------------------------------------------


@pytest.mark.parametrize(
    "types,inventory_ok,peer_ok",
    [
        ([MECHANIC], True, True),
        ([SHOP], False, True),
        ([DEALER], False, False),
        ([INSURANCE], False, False),
        ([MECHANIC, SHOP], True, True),
        ([MECHANIC, DEALER], True, True),
        ([SHOP, DEALER], False, True),
        ([DEALER, INSURANCE], False, False),
        ([], False, False),
    ],
)
def test_default_matrix(client, db, types, inventory_ok, peer_ok):
    user = _make_user(db, "TV-X-000210", f"m-{uuid.uuid4()}@example.com", types)
    headers = auth_headers(user)

    inventory = client.get("/api/inventory", headers=headers)
    assert (inventory.status_code == 200) is inventory_ok
    if not inventory_ok:
        assert _module_unavailable(inventory)

    peer = client.get("/api/core/sharing/peer", headers=headers)
    assert (peer.status_code == 200) is peer_ok
    if not peer_ok:
        assert _module_unavailable(peer)

    mine = client.get("/api/core/my-modules", headers=headers)
    assert mine.status_code == 200
    ids = {m["id"] for m in mine.json()}
    assert ("inventory" in ids) is inventory_ok
    assert ("shared_tools" in ids) is peer_ok


def test_my_modules_carry_nav_metadata(client, mechanic):
    mine = client.get("/api/core/my-modules", headers=auth_headers(mechanic))
    by_id = {m["id"]: m for m in mine.json()}
    assert by_id["inventory"]["nav"] == {
        "label": "Inventory",
        "path": "/inventory",
        "order": 10,
    }
    assert "assets" in by_id["inventory"]["provides"]
    assert "inventory stats" in by_id["inventory"]["provides"]
    assert by_id["shared_tools"]["nav"]["path"] == "/shared-tools"
    assert by_id["shared_tools"]["depends_on"] == ["core", "inventory"]


def test_peer_invite_and_search_are_module_gated(client, dealer, mechanic):
    # Invite: refused for a group the module doesn't serve.
    response = client.post(
        "/api/core/sharing/peer/invite",
        json={"email": "crew@example.com"},
        headers=auth_headers(dealer),
    )
    assert _module_unavailable(response)
    # Search: same.
    response = client.get(
        "/api/core/sharing/peer/search?q=impact", headers=auth_headers(dealer)
    )
    assert _module_unavailable(response)
    # ... and open for a mechanic (201 with a real invite).
    response = client.post(
        "/api/core/sharing/peer/invite",
        json={"email": "crew@example.com"},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 201


# -- operator surface ---------------------------------------------------------


def test_admin_matrix_requires_operator(client, mechanic):
    assert client.get("/api/admin/modules").status_code == 401
    assert (
        client.get("/api/admin/modules", headers=auth_headers(mechanic)).status_code
        == 403
    )
    assert (
        client.put(
            "/api/admin/modules/inventory/global",
            json={"enabled": False},
            headers=auth_headers(mechanic),
        ).status_code
        == 403
    )


def test_admin_matrix_defaults(client, operator):
    matrix = client.get("/api/admin/modules", headers=auth_headers(operator))
    assert matrix.status_code == 200
    by_id = {m["id"]: m for m in matrix.json()}
    assert set(by_id) == {
        "inventory",
        "shared_tools",
        "ai_assistant",
        "borrowing",
        "dealers",
        "reports",
        "maintenance",
        "claims",
        "disaster_claims",
        "parts",
        "messaging",
        "marketplace",
        "forum",
        "wishlist",
        "tool_expansion",
        "truck_accounts",
        "feedback",
        "catalog",
        "support",
        "flyers",
        "prints",
    }

    # Flyers (2026-11-06): mechanic + shop + dealer (both sides
    # of the flyer), never insurance.
    flyers = by_id["flyers"]
    assert flyers["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: False,
    }
    assert flyers["depends_on"] == ["core", "dealers", "catalog"]

    # Wave 2 (2026-10-20): the wishlist rides mechanic + shop;
    # truck accounts span mechanic + shop + dealer (both sides of
    # the tab), never insurance.
    wishlist = by_id["wishlist"]
    assert wishlist["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert wishlist["depends_on"] == ["core", "inventory"]
    # Tool Expansion (2026-10-25): an inventory rider like the
    # wishlist — mechanic + shop, dealer + insurance excluded.
    expansion = by_id["tool_expansion"]
    assert expansion["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert expansion["depends_on"] == ["core", "inventory"]
    truck = by_id["truck_accounts"]
    assert truck["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: False,
    }
    assert truck["depends_on"] == ["core", "dealers"]

    inventory = by_id["inventory"]
    assert inventory["globally_enabled"] is True
    assert inventory["groups"] == {
        MECHANIC: True,
        SHOP: False,
        DEALER: False,
        INSURANCE: False,
    }
    assert inventory["dependency_status"] == "ok"

    shared = by_id["shared_tools"]
    assert shared["groups"][MECHANIC] is True
    assert shared["groups"][SHOP] is True
    assert shared["groups"][DEALER] is False
    assert shared["dependency_status"] == "ok"
    assert shared["depends_on"] == ["core", "inventory"]

    # AI Assistant (Phase A1): a purchasable add-on — registered and
    # globally on, but assigned to NO group by default.
    ai = by_id["ai_assistant"]
    assert ai["name"] == "ai_assistant"  # matrix name == module id, as for all modules
    assert ai["globally_enabled"] is True
    assert ai["groups"] == {
        MECHANIC: False,
        SHOP: False,
        DEALER: False,
        INSURANCE: False,
    }
    assert ai["dependency_status"] == "ok"

    # Borrowing (2026-10-18): grows out of peer sharing — mechanic +
    # shop by default, riding on inventory like shared_tools does.
    borrowing = by_id["borrowing"]
    assert borrowing["globally_enabled"] is True
    assert borrowing["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert borrowing["depends_on"] == ["core", "inventory"]
    assert borrowing["dependency_status"] == "ok"

    # Dealers (item structure package, 2026-10-18): the directory +
    # preferred agents serve ALL FOUR groups by default and depend
    # on core ONLY — inventory must never depend on it (the item
    # dealer tag is a bare reference; the module removes cleanly).
    dealers = by_id["dealers"]
    assert dealers["globally_enabled"] is True
    assert dealers["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert dealers["depends_on"] == ["core"]
    assert dealers["dependency_status"] == "ok"

    # Reports (2026-10-19): reads the vault through inventory —
    # mechanic + shop by default, blocked when inventory is.
    reports = by_id["reports"]
    assert reports["globally_enabled"] is True
    assert reports["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert reports["depends_on"] == ["core", "inventory"]
    assert reports["dependency_status"] == "ok"

    # Maintenance (2026-10-19): repairs/schedules/warranty ride on
    # inventory like borrowing does — mechanic + shop by default.
    maintenance = by_id["maintenance"]
    assert maintenance["globally_enabled"] is True
    assert maintenance["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert maintenance["depends_on"] == ["core", "inventory"]
    assert maintenance["dependency_status"] == "ok"

    # Claims (2026-10-19): insurance claims read the vault through
    # inventory — mechanic + shop by default, blocked when
    # inventory is.
    claims = by_id["claims"]
    assert claims["globally_enabled"] is True
    assert claims["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert claims["depends_on"] == ["core", "inventory"]
    assert claims["dependency_status"] == "ok"

    # Used Parts (2026-10-19): the spares shelf stands alone —
    # mechanic + shop by default, depending on core ONLY (inventory
    # off must not block it; the convert bridge gates itself).
    parts = by_id["parts"]
    assert parts["globally_enabled"] is True
    assert parts["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert parts["depends_on"] == ["core"]
    assert parts["dependency_status"] == "ok"

    # Messaging (2026-10-19): the community's conversation layer —
    # ALL FOUR groups by default (every signed-in user may hold a
    # conversation), depending on core ONLY.
    messaging = by_id["messaging"]
    assert messaging["globally_enabled"] is True
    assert messaging["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert messaging["depends_on"] == ["core"]
    assert messaging["dependency_status"] == "ok"

    # Tools For Sale (2026-10-19): the community board — ALL FOUR
    # groups by default (every member may post, subject to the
    # paid gate), depending on core ONLY (listings snapshot their
    # data, so inventory off must not block the board).
    marketplace = by_id["marketplace"]
    assert marketplace["globally_enabled"] is True
    assert marketplace["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert marketplace["depends_on"] == ["core"]
    assert marketplace["dependency_status"] == "ok"

    # Community Forum (2026-10-20): the community's common room —
    # ALL FOUR groups by default (every member may read and,
    # subject to the paid gate, post), depending on core ONLY
    # (it consumes the suite's machinery through service
    # interfaces at request time, so no sibling's kill switch
    # can touch it).
    forum = by_id["forum"]
    assert forum["globally_enabled"] is True
    assert forum["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert forum["depends_on"] == ["core"]
    assert forum["dependency_status"] == "ok"

    # Feedback boards (wave 3, 2026-10-20): public boards — ALL
    # FOUR groups by default (every member may read signed-out
    # and post signed-in, free included — the deliberate
    # deviation from the forum's paid gate), depending on core
    # ONLY.
    feedback = by_id["feedback"]
    assert feedback["globally_enabled"] is True
    assert feedback["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert feedback["depends_on"] == ["core"]
    assert feedback["dependency_status"] == "ok"

    # Community catalog (wave 4, 2026-10-20): the derived product
    # catalog + lookup chain ride inventory for the groups that
    # keep inventories — mechanic + shop, like the wishlist.
    catalog = by_id["catalog"]
    assert catalog["globally_enabled"] is True
    assert catalog["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: False,
        INSURANCE: False,
    }
    assert catalog["depends_on"] == ["core", "inventory"]
    assert catalog["dependency_status"] == "ok"

    # Support tickets (2026-10-24): the Help & Support desk —
    # ALL FOUR groups by default (every member may need help,
    # whatever kind of account they hold), depending on core
    # ONLY.
    support = by_id["support"]
    assert support["globally_enabled"] is True
    assert support["groups"] == {
        MECHANIC: True,
        SHOP: True,
        DEALER: True,
        INSURANCE: True,
    }
    assert support["depends_on"] == ["core"]
    assert support["dependency_status"] == "ok"


def test_operator_flag_in_me(client, operator, mechanic):
    me = client.get("/api/core/me", headers=auth_headers(operator)).json()
    assert me["is_operator"] is True
    me = client.get("/api/core/me", headers=auth_headers(mechanic)).json()
    assert me["is_operator"] is False


def test_unknown_module_and_group_are_refused(client, operator):
    headers = auth_headers(operator)
    assert (
        client.put(
            "/api/admin/modules/nope/global",
            json={"enabled": False},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/admin/modules/inventory/groups/wizard",
            json={"enabled": True},
            headers=headers,
        ).status_code
        == 422
    )


# -- the switches ---------------------------------------------------------------


def test_global_kill_switch_and_dependency_blocking(client, operator, mechanic, shop):
    headers = auth_headers(operator)

    updated = client.put(
        "/api/admin/modules/inventory/global",
        json={"enabled": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["globally_enabled"] is False

    # Inventory is off for its own group...
    response = client.get("/api/inventory", headers=auth_headers(mechanic))
    assert _module_unavailable(response)
    # ...and shared_tools goes with it, for BOTH of its groups.
    for user in (mechanic, shop):
        response = client.get("/api/core/sharing/peer", headers=auth_headers(user))
        assert _module_unavailable(response)
    # The mechanic's effective set shrinks to the core-only modules:
    # dealers, parts, messaging, marketplace, truck accounts, forum,
    # print files and support all depend on core alone (truck accounts ride dealers),
    # so the inventory kill switch can't touch them (the
    # removability proof in reverse — parts' convert bridge gates
    # itself instead). The wishlist DOES depend on inventory, so
    # it went dark with it. The matrix explains why shared_tools
    # went dark.
    mine = client.get("/api/core/my-modules", headers=auth_headers(mechanic))
    assert [m["id"] for m in mine.json()] == [
        "support",
        "parts",
        "marketplace",
        "dealers",
        "messaging",
        "truck_accounts",
        "forum",
        "feedback",
        "prints",
    ]
    matrix = client.get("/api/admin/modules", headers=headers).json()
    shared = next(m for m in matrix if m["id"] == "shared_tools")
    assert shared["dependency_status"] == "blocked by inventory"

    # Switch it back: everything returns on the next request.
    client.put(
        "/api/admin/modules/inventory/global",
        json={"enabled": True},
        headers=headers,
    )
    assert client.get("/api/inventory", headers=auth_headers(mechanic)).status_code == 200
    assert (
        client.get("/api/core/sharing/peer", headers=auth_headers(shop)).status_code
        == 200
    )


def test_killing_shared_tools_leaves_inventory_alone(client, operator, mechanic):
    headers = auth_headers(operator)
    client.put(
        "/api/admin/modules/shared_tools/global",
        json={"enabled": False},
        headers=headers,
    )
    assert _module_unavailable(
        client.get("/api/core/sharing/peer", headers=auth_headers(mechanic))
    )
    assert client.get("/api/inventory", headers=auth_headers(mechanic)).status_code == 200


def test_group_assignment_is_data_driven(client, operator, dealer, mechanic):
    headers = auth_headers(operator)
    # Hand inventory to dealers: the API opens with no code change.
    client.put(
        "/api/admin/modules/inventory/groups/tool_dealer",
        json={"enabled": True},
        headers=headers,
    )
    assert client.get("/api/inventory", headers=auth_headers(dealer)).status_code == 200
    mine = client.get("/api/core/my-modules", headers=auth_headers(dealer)).json()
    # The dealer group ALSO has dealers, messaging, marketplace,
    # forum, flyers, print files and support by default (all four
    # groups do) — inventory joins them here.
    assert [m["id"] for m in mine] == [
        "support",
        "inventory",
        "marketplace",
        "dealers",
        "flyers",
        "messaging",
        "truck_accounts",
        "forum",
        "feedback",
        "prints",
    ]
    # The mechanic's assignment survived the dealer's toggle (the
    # materialization rule: untouched cells keep their defaults).
    assert client.get("/api/inventory", headers=auth_headers(mechanic)).status_code == 200
    # Take it back.
    client.put(
        "/api/admin/modules/inventory/groups/tool_dealer",
        json={"enabled": False},
        headers=headers,
    )
    assert _module_unavailable(client.get("/api/inventory", headers=auth_headers(dealer)))


def test_unassigning_a_dependency_everywhere_blocks_dependents(
    client, operator, mechanic, shop
):
    headers = auth_headers(operator)
    client.put(
        "/api/admin/modules/inventory/groups/mechanic_technician",
        json={"enabled": False},
        headers=headers,
    )
    # Mechanic loses inventory by assignment...
    assert _module_unavailable(
        client.get("/api/inventory", headers=auth_headers(mechanic))
    )
    # ...and because inventory is now assigned NOWHERE, shared_tools
    # is dependency-blocked even for the shop, which never held it.
    assert _module_unavailable(
        client.get("/api/core/sharing/peer", headers=auth_headers(shop))
    )
    matrix = client.get("/api/admin/modules", headers=headers).json()
    shared = next(m for m in matrix if m["id"] == "shared_tools")
    assert shared["dependency_status"] == "blocked by inventory"


# -- legacy accounts --------------------------------------------------------------


def test_no_group_account_is_unaffected_until_it_picks(client, db):
    legacy = _make_user(db, "TV-000299", "legacy@example.com", [])
    headers = auth_headers(legacy)
    # Core is infrastructure: profile + layouts work as always.
    assert client.get("/api/core/me", headers=headers).status_code == 200
    assert client.get("/api/core/layouts/home", headers=headers).status_code == 200
    assert client.get("/api/core/my-modules", headers=headers).json() == []
    # The one-time pick still works and unlocks modules immediately.
    picked = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    assert picked.status_code == 200
    assert client.get("/api/inventory", headers=headers).status_code == 200


# -- graph validation ----------------------------------------------------------------


def _fake_manifest(name, dependencies=()):
    return ModuleManifest(
        name=name,
        version="0.0.1",
        description="test double",
        route_prefix=f"/api/{name}",
        router=APIRouter(),
        always_on=False,
        dependencies=dependencies,
        default_groups=(MECHANIC,),
    )


def test_real_graph_is_healthy():
    assert validate_feature_modules() == []
    assert module_control.graph_blocked() == {}


def test_graph_flags_unknown_dependencies():
    modules = {"alpha": _fake_manifest("alpha", ("ghost",))}
    problems = validate_feature_modules(modules)
    assert any("alpha" in p and "ghost" in p for p in problems)
    assert "alpha" in module_control.graph_blocked(modules)


def test_graph_flags_cycles_and_blocks_dependents():
    modules = {
        "alpha": _fake_manifest("alpha", ("beta",)),
        "beta": _fake_manifest("beta", ("alpha",)),
        "gamma": _fake_manifest("gamma", ("alpha",)),
    }
    problems = validate_feature_modules(modules)
    assert any("cycle" in p.lower() for p in problems)
    blocked = module_control.graph_blocked(modules)
    assert "alpha" in blocked and "beta" in blocked
    assert blocked["gamma"] == "blocked by alpha"


def test_broken_dependency_is_never_effective(db):
    modules = {
        "alpha": _fake_manifest("alpha", ("beta",)),
        "beta": _fake_manifest("beta", ("ghost",)),
    }
    assert (
        module_control.effective_for_user(db, "alpha", [MECHANIC], modules)
        is False
    )
    assert (
        module_control.dependency_blocker(db, "alpha", modules) == "beta"
    )
