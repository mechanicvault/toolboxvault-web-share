"""Wizard reach filter (owner order, 2026-11-09): the onboarding
wizard must not spill the hidden site to a limited account.

Ryan: "You need to filter that onboarding wizard for new accounts
right away, that wizard basically spills the beans of all the
hidden stuff. This is supposed to be basic right now and bare
minimum."

The downloads level holds no account groups BY DESIGN (tiers.py's
group waiver): its world is read off its tier cells. Before this
lane, its wizard opened on the account-type step (the pick that
enumerates every type's features), the type lock then held every
later step hostage to a pick the rung cannot honestly make, and
the server refused every downstream progress write for
typelessness — the wizard was both a leak and a dead end. The
frontend half of the fix assembles the rung's pass without the
account-type and aggregate-modules steps; these tests pin the
server half:

  * the waiver helper names exactly the downloads rung;
  * a downloads account CAN record its reach-filtered steps
    (setting + module) — the typeless refusal does not bind it;
  * a typeless NORMAL account is still refused (the 2026-11-07
    type gate stands untouched for group-layer rungs);
  * the self-serve account-type door refuses a downloads
    account's pick in fact (422, nothing written), while a
    normal account's pick — and a downloads account's pick after
    an admin moves it to normal (the launch move) — lands;
  * the plan's module steps for a downloads account are exactly
    its reach (prints + support under the 0096 seed shape).
"""

import itertools
import uuid

from app.modules.core import (
    models as core_models,
    module_control,
    onboarding,
    tiers,
)
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(7000)


def _make_user(db, types, *, tier="normal"):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"wiz-{n}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Wiz {n}",
        password_hash="not-a-real-hash",
        account_types=list(types),
        is_operator=False,
        role=tiers.role_for_tier(tier),
        tier=tier,
        beta_tester=False,
        locale="en",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _downloads_user(db):
    """A downloads-level account born the public way: no groups,
    wizard-flow marker set."""
    user = _make_user(db, [], tier="downloads")
    onboarding.mark_fresh(db, user)
    return user


def _seed_downloads_world(db):
    """Migration 0096's seed shape (as the open-signup lane's
    tests seed it): prints + support ON for downloads, the rest
    OFF; the pre-existing keys at their global state (on)."""
    for module_id in ("prints", "support", "inventory", "forum", "catalog"):
        for key in ("normal", "moderator", "moderator_admin", "beta"):
            module_control.set_tier_assignment(db, module_id, key, True)
        module_control.set_tier_assignment(
            db, module_id, "downloads", module_id in ("prints", "support")
        )


def _progress(client, user, key, status_="done"):
    return client.post(
        "/api/core/onboarding/progress",
        json={"step_key": key, "status": status_},
        headers=auth_headers(user),
    )


# --------------------------------------------------------------------- #
# The waiver helper
# --------------------------------------------------------------------- #


def test_group_layer_waived_names_only_the_downloads_rung():
    assert tiers.group_layer_waived("downloads") is True
    for rung in ("normal", "moderator", "moderator_admin", "god", "beta"):
        assert tiers.group_layer_waived(rung) is False
    assert tiers.group_layer_waived(None) is False
    assert tiers.group_layer_waived("") is False


# --------------------------------------------------------------------- #
# Progress writes: the refusal binds group-layer rungs only
# --------------------------------------------------------------------- #


def test_downloads_account_records_its_reach_filtered_steps(client, db):
    user = _downloads_user(db)
    resp = _progress(client, user, "setting:appearance", "done")
    assert resp.status_code == 200
    assert resp.json()["progress"]["setting:appearance"] == "done"
    resp = _progress(client, user, "module:prints", "skipped")
    assert resp.status_code == 200
    assert resp.json()["progress"]["module:prints"] == "skipped"


def test_typeless_normal_account_is_still_refused(client, db):
    """The paired control: Ryan's 2026-11-07 ruling stands for
    every rung that uses the group layer."""
    user = _make_user(db, [], tier="normal")
    onboarding.mark_fresh(db, user)
    for key in ("setting:appearance", "module:prints"):
        resp = _progress(client, user, key, "done")
        assert resp.status_code == 422, key
    plan = onboarding.get_plan(db, user)
    assert "setting:appearance" not in plan["progress"]
    assert "module:prints" not in plan["progress"]


# --------------------------------------------------------------------- #
# The account-type door
# --------------------------------------------------------------------- #


def test_downloads_account_cannot_pick_account_types(client, db):
    user = _downloads_user(db)
    resp = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    db.refresh(user)
    assert user.account_types == []


def test_normal_account_type_pick_still_lands(client, db):
    user = _make_user(db, [], tier="normal")
    resp = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    db.refresh(user)
    assert user.account_types == [MECHANIC]


def test_the_launch_move_restores_the_type_door(client, db):
    """The guard keys on the account's CURRENT rung: an admin
    flips the account to normal (the launch move) and the very
    same pick lands."""
    user = _downloads_user(db)
    resp = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    user.tier = "normal"
    db.commit()
    resp = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    db.refresh(user)
    assert user.account_types == [MECHANIC]


# --------------------------------------------------------------------- #
# The plan: a downloads account's module steps are its reach
# --------------------------------------------------------------------- #


def test_downloads_plan_module_steps_are_its_reach_only(client, db):
    _seed_downloads_world(db)
    user = _downloads_user(db)
    resp = client.get("/api/core/onboarding", headers=auth_headers(user))
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["flow"] == "wizard"
    module_ids = {
        s["module_id"] for s in plan["steps"] if s["kind"] == "module"
    }
    assert module_ids == {"prints", "support"}
