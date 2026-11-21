"""Account tiers + module rollout by tier (owner design, 2026-10-31).

Covers the three pieces of the build:

  * GRANT RULES over HTTP — who may set which rung and the beta
    flag (Admin → Users, /api/admin/users/{id}/tier + /beta):
    Moderator Admin is god-only; Moderator and Beta are god or
    moderator-admin work; nobody changes their own rung or flag;
    the god rung is never settable at all (422 — it isn't in the
    request vocabulary).
  * GOD PROTECTION — an operator who is NOT god (operator flag
    with a lower stored rung: the legacy shape) is refused on the
    god account's deactivate / role / tier / beta / operator /
    trial paths alike; the guard, not the gate, does the refusing.
  * TIER GATING in module_control — the staged-rollout sequence
    on the parked messaging module (dark → staff-only → +beta →
    everyone), inheritance (higher rungs carry the lower keys),
    the tier AND group multiplication, the god bypass, and
    PUBLIC PRESENCE = NORMAL TIER for usable_anywhere.
"""

import itertools
import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.core import module_control, service, tiers
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"

_counter = itertools.count(700)


def _make_user(db, types, *, tier="normal", beta=False, operator=False, role=None):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"tier-{n}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Tier {n}",
        password_hash="not-a-real-hash",
        account_types=list(types),
        is_operator=operator,
        role=role if role is not None else tiers.role_for_tier(tier),
        tier=tier,
        beta_tester=beta,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _god(db):
    """The god seat: operator flag + god rung (mechanicvault's
    production shape)."""
    return _make_user(db, [MECHANIC], tier="god", operator=True)


def _mod_admin(db):
    return _make_user(db, [MECHANIC], tier="moderator_admin")


def _effective(db, user, module_id):
    return module_control.effective_for_user(
        db,
        module_id,
        user.account_types,
        user_id=user.id,
        tier=tiers.resolved_tier(user),
        beta_tester=bool(user.beta_tester),
    )


def _set_tiers(db, module_id, **switches):
    for key, enabled in switches.items():
        module_control.set_tier_assignment(db, module_id, key, enabled)


# --------------------------------------------------------------------- #
# Grant rules (HTTP)
# --------------------------------------------------------------------- #


def test_mod_admin_cannot_grant_mod_admin(client, db):
    actor = _mod_admin(db)
    target = _make_user(db, [MECHANIC])
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator_admin"},
    )
    assert resp.status_code == 403
    db.refresh(target)
    assert target.tier == "normal"


def test_mod_admin_cannot_revoke_mod_admin(client, db):
    actor = _mod_admin(db)
    target = _make_user(db, [MECHANIC], tier="moderator_admin")
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator"},
    )
    assert resp.status_code == 403
    db.refresh(target)
    assert target.tier == "moderator_admin"


def test_mod_admin_grants_and_revokes_moderator(client, db):
    actor = _mod_admin(db)
    target = _make_user(db, [MECHANIC])
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator"},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "moderator"
    assert resp.json()["role"] == "moderator"  # the role shadow follows
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "normal"},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "normal"
    assert resp.json()["role"] == "user"


def test_god_grants_mod_admin(client, db):
    actor = _god(db)
    target = _make_user(db, [MECHANIC])
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator_admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "moderator_admin"
    assert resp.json()["role"] == "community_admin"


def test_mod_admin_sets_beta(client, db):
    actor = _mod_admin(db)
    target = _make_user(db, [MECHANIC])
    resp = client.post(
        f"/api/admin/users/{target.id}/beta",
        headers=auth_headers(actor),
        json={"beta_tester": True},
    )
    assert resp.status_code == 200
    assert resp.json()["beta_tester"] is True
    resp = client.post(
        f"/api/admin/users/{target.id}/beta",
        headers=auth_headers(actor),
        json={"beta_tester": False},
    )
    assert resp.status_code == 200
    assert resp.json()["beta_tester"] is False


def test_god_rung_is_not_grantable(client, db):
    actor = _god(db)
    target = _make_user(db, [MECHANIC])
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "god"},
    )
    assert resp.status_code == 422


def test_self_tier_change_refused(client, db):
    actor = _mod_admin(db)
    resp = client.post(
        f"/api/admin/users/{actor.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator"},
    )
    assert resp.status_code == 400


def test_god_cannot_demote_itself(client, db):
    actor = _god(db)
    resp = client.post(
        f"/api/admin/users/{actor.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "normal"},
    )
    assert resp.status_code == 400
    db.refresh(actor)
    assert tiers.resolved_tier(actor) == "god"


def test_self_beta_change_refused(client, db):
    actor = _mod_admin(db)
    resp = client.post(
        f"/api/admin/users/{actor.id}/beta",
        headers=auth_headers(actor),
        json={"beta_tester": True},
    )
    assert resp.status_code == 400


def test_plain_user_cannot_use_user_management(client, db):
    actor = _make_user(db, [MECHANIC])
    target = _make_user(db, [MECHANIC])
    assert client.get("/api/admin/users", headers=auth_headers(actor)).status_code == 403
    resp = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "moderator"},
    )
    assert resp.status_code == 403


def test_mod_admin_reaches_users_but_not_modules_admin(client, db):
    actor = _mod_admin(db)
    assert client.get("/api/admin/users", headers=auth_headers(actor)).status_code == 200
    assert client.get("/api/admin/modules", headers=auth_headers(actor)).status_code == 403


# --------------------------------------------------------------------- #
# God protection: an operator who is NOT god (legacy shape —
# operator flag set, stored rung below god) hits the guard on
# every admin path aimed at the god account.
# --------------------------------------------------------------------- #


@pytest.fixture()
def legacy_operator(db):
    return _make_user(db, [MECHANIC], tier="moderator_admin", operator=True)


def test_non_god_operator_cannot_deactivate_god(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/deactivate",
        headers=auth_headers(legacy_operator),
        json={},
    )
    assert resp.status_code == 403
    assert "God account" in resp.json()["detail"]


def test_non_god_operator_cannot_change_god_tier(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/tier",
        headers=auth_headers(legacy_operator),
        json={"tier": "normal"},
    )
    assert resp.status_code == 403


def test_non_god_operator_cannot_change_god_beta(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/beta",
        headers=auth_headers(legacy_operator),
        json={"beta_tester": True},
    )
    assert resp.status_code == 403


def test_non_god_operator_cannot_change_god_role(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/role",
        headers=auth_headers(legacy_operator),
        json={"role": "user"},
    )
    assert resp.status_code == 403


def test_non_god_operator_cannot_touch_god_operator_flag(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/operator",
        headers=auth_headers(legacy_operator),
        json={"is_operator": False},
    )
    assert resp.status_code == 403


def test_non_god_operator_cannot_grant_god_trial(client, db, legacy_operator):
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/trial",
        headers=auth_headers(legacy_operator),
        json={"plan_key": "pro", "months": 1},
    )
    assert resp.status_code == 403


def test_god_can_edit_itself_via_operator_paths(client, db):
    """The guard refuses OTHER actors, not god itself: god's own
    beta flag CAN be set by god through... no — self-grants are
    refused for everyone, god included. What god CAN do is use
    the ordinary self-service paths; the admin self-targets stay
    refused by the self-rule. This pins that asymmetry."""
    god = _god(db)
    resp = client.post(
        f"/api/admin/users/{god.id}/beta",
        headers=auth_headers(god),
        json={"beta_tester": True},
    )
    assert resp.status_code == 400  # the self-rule, not the god guard


def test_set_user_role_never_strips_god(db):
    god = _god(db)
    service.set_user_role(db, god, "user")
    db.refresh(god)
    assert tiers.resolved_tier(god) == "god"


def test_role_only_moderator_keeps_the_rung(db):
    """The fold-in rule: an account written by the ROLE ladder
    alone (tier column still at its "normal" default — the shape
    of every pre-tier fixture and legacy write) resolves to the
    rung its role implies. Nobody loses a power they had."""
    legacy_mod = _make_user(db, [MECHANIC], tier="normal", role="moderator")
    assert tiers.resolved_tier(legacy_mod) == "moderator"
    legacy_admin = _make_user(db, [MECHANIC], tier="normal", role="community_admin")
    assert tiers.resolved_tier(legacy_admin) == "moderator_admin"


def test_operator_grant_gives_access_not_the_crown(db):
    """An operator grant makes the target god-RUNG for access
    (is_god) but does not make it THE god account
    (is_god_account) — god's edit-guard protects the crowned
    account only, and granted operators stay revocable."""
    granted = _make_user(db, [MECHANIC], tier="normal", operator=True)
    assert tiers.is_god(granted) is True
    assert tiers.is_god_account(granted) is False
    crowned = _god(db)
    assert tiers.is_god_account(crowned) is True


def test_tier_and_role_stay_in_sync(db):
    user = _make_user(db, [MECHANIC])
    service.set_user_tier(db, user, "moderator")
    assert user.tier == "moderator" and user.role == "moderator"
    service.set_user_tier(db, user, "moderator_admin")
    assert user.tier == "moderator_admin" and user.role == "community_admin"
    service.set_user_role(db, user, "moderator")
    assert user.tier == "moderator" and user.role == "moderator"
    with pytest.raises(ValueError):
        service.set_user_tier(db, user, "god")


# --------------------------------------------------------------------- #
# Tier gating — the staged rollout on messaging (spec §4 sequence)
# --------------------------------------------------------------------- #


def _rollout_seats(db):
    return {
        "god": _god(db),
        "mod_admin": _mod_admin(db),
        "moderator": _make_user(db, [MECHANIC], tier="moderator"),
        "normal": _make_user(db, [MECHANIC]),
        "beta": _make_user(db, [MECHANIC], beta=True),
    }


def test_staged_rollout_sequence(db):
    seats = _rollout_seats(db)
    # Messaging globally ON but dark for every tier: the rollout's
    # starting position (a parked module god is about to stage).
    module_control.set_global_enabled(db, "messaging", True)
    _set_tiers(db, "messaging", normal=False, moderator=False,
               moderator_admin=False, beta=False)

    def states():
        return {name: _effective(db, user, "messaging") for name, user in seats.items()}

    assert states() == {
        "god": True,  # god bypasses every layer, parked or not
        "mod_admin": False,
        "moderator": False,
        "normal": False,
        "beta": False,
    }

    # Light staff only.
    _set_tiers(db, "messaging", moderator_admin=True)
    assert states() == {
        "god": True, "mod_admin": True, "moderator": False,
        "normal": False, "beta": False,
    }

    # Light beta testers: beta sees it, normal still does not,
    # and the beta key does NOT flow down to a plain moderator.
    _set_tiers(db, "messaging", beta=True)
    assert states() == {
        "god": True, "mod_admin": True, "moderator": False,
        "normal": False, "beta": True,
    }

    # Light normal: everyone (inheritance carries it up).
    _set_tiers(db, "messaging", normal=True)
    assert states() == {
        "god": True, "mod_admin": True, "moderator": True,
        "normal": True, "beta": True,
    }


def test_rollout_over_http(client, db):
    """The same sequence through the real surfaces: the nav
    payload (my-modules) and the module's own route."""
    seats = _rollout_seats(db)
    module_control.set_global_enabled(db, "messaging", True)
    _set_tiers(db, "messaging", normal=False, moderator=False,
               moderator_admin=True, beta=False)

    def sees(user):
        resp = client.get("/api/core/my-modules", headers=auth_headers(user))
        assert resp.status_code == 200
        return any(m["id"] == "messaging" for m in resp.json())

    assert sees(seats["god"]) is True
    assert sees(seats["mod_admin"]) is True
    assert sees(seats["moderator"]) is False
    assert sees(seats["normal"]) is False
    assert sees(seats["beta"]) is False

    ok = client.get("/api/messaging/threads", headers=auth_headers(seats["mod_admin"]))
    assert ok.status_code == 200
    no = client.get("/api/messaging/threads", headers=auth_headers(seats["normal"]))
    assert no.status_code == 403
    assert no.json()["detail"]["code"] == "module_unavailable"

    _set_tiers(db, "messaging", beta=True)
    assert sees(seats["beta"]) is True
    assert sees(seats["normal"]) is False


def test_inheritance_from_normal_only(db):
    """A module lit ONLY for normal is visible to moderator and
    moderator-admin seats (they carry the normal key)."""
    seats = _rollout_seats(db)
    module_control.set_global_enabled(db, "forum", True)
    _set_tiers(db, "forum", normal=True, moderator=False,
               moderator_admin=False, beta=False)
    assert _effective(db, seats["normal"], "forum") is True
    assert _effective(db, seats["moderator"], "forum") is True
    assert _effective(db, seats["mod_admin"], "forum") is True
    assert _effective(db, seats["beta"], "forum") is True


def test_tier_and_group_multiply(db):
    """Tier allows AND group assigned: claims is lit for every
    tier, but a dealer-only account still gets nothing — claims
    is not assigned to the dealer group."""
    dealer = _make_user(db, [DEALER])
    module_control.set_global_enabled(db, "claims", True)
    _set_tiers(db, "claims", normal=True, moderator=True,
               moderator_admin=True, beta=True)
    assert _effective(db, dealer, "claims") is False
    mechanic = _make_user(db, [MECHANIC])
    assert _effective(db, mechanic, "claims") is True


def test_god_bypass_with_global_off(db):
    seats = _rollout_seats(db)
    module_control.set_global_enabled(db, "messaging", False)
    _set_tiers(db, "messaging", normal=False, moderator=False,
               moderator_admin=False, beta=False)
    assert _effective(db, seats["god"], "messaging") is True
    assert _effective(db, seats["mod_admin"], "messaging") is False
    mine = module_control.effective_modules(
        db, seats["god"].account_types, user_id=seats["god"].id,
        tier="god", beta_tester=False,
    )
    assert any(m["id"] == "messaging" for m in mine)


def test_public_presence_is_the_normal_tier(db):
    """usable_anywhere (the landing's question) keys off NORMAL:
    lit for staff only, the module is still publicly dark; light
    normal and it becomes public."""
    module_control.set_global_enabled(db, "messaging", True)
    _set_tiers(db, "messaging", normal=False, moderator=False,
               moderator_admin=True, beta=True)
    assert module_control.usable_anywhere(db, "messaging") is False
    _set_tiers(db, "messaging", normal=True)
    assert module_control.usable_anywhere(db, "messaging") is True


def test_first_tier_write_materializes_the_rest(db):
    """Writing one cell must not silently change the others: on a
    module with no tier rows, the rest materialize from the
    current effective (global-fallback) values."""
    db.query(core_models.ModuleTierAccess).filter(
        core_models.ModuleTierAccess.module_id == "forum"
    ).delete()
    db.commit()
    module_control.set_global_enabled(db, "forum", True)
    module_control.set_tier_assignment(db, "forum", "beta", False)
    assert module_control.tier_switches(db, "forum") == {
        "normal": True,
        "moderator": True,
        "moderator_admin": True,
        "beta": False,
        # The downloads key (2026-11-09) materializes OFF: the
        # limited level is opt-in, never a fallback accident.
        "downloads": False,
    }


def test_admin_matrix_and_tier_endpoint(client, db):
    god = _god(db)
    resp = client.put(
        "/api/admin/modules/messaging/tiers/moderator_admin",
        headers=auth_headers(god),
        json={"enabled": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tiers"]["moderator_admin"] is True
    assert set(body["tiers"]) == {
        "normal",
        "moderator",
        "moderator_admin",
        "beta",
        "downloads",
    }
    # An unknown tier key never reaches the handler.
    resp = client.put(
        "/api/admin/modules/messaging/tiers/owner",
        headers=auth_headers(god),
        json={"enabled": True},
    )
    assert resp.status_code == 422


def test_me_carries_tier_and_beta(client, db):
    user = _make_user(db, [MECHANIC], tier="moderator_admin", beta=True)
    resp = client.get("/api/core/me", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["tier"] == "moderator_admin"
    assert resp.json()["beta_tester"] is True
    assert resp.json()["role"] == "community_admin"
