"""Onboarding wizard system (owner design 2026-10-31, built
2026-11-07).

Pins:
- signup is just an account: email + name + password creates an
  ungrouped account (plain number, no basics) that carries the
  wizard-flow marker; the full old payload is still honored.
- the plan: wizard flow for fresh accounts, registry-driven
  module steps (the step set IS the module-control prefs read),
  probe steps that follow the account itself.
- progress writes: done/skipped persist, bad keys are 422.
- dismissal waives the banner, reopening restores it; neither
  marks anything done.
- existing accounts are untouched: a complete pre-wizard account
  reads as the existing flow, takes its baseline silently, and is
  never handed first-pass steps.
- the living part: a module that joins the registry AFTER an
  account's baseline surfaces as a new-feature step with exactly
  ONE inbox notification; resolving it ends the prompting.
- a legacy incomplete account (no marker, no bare bones) reads
  as the legacy flow — the old completion gate's population.
- account deletion sweeps the progress rows.

Account creation runs at the service level with the allocator
stubbed (Postgres nextval, the suite's standing pattern); the
plan endpoints run over real HTTP.
"""

import itertools
import json

import pytest
from fastapi import APIRouter

from app.modules.core import models, onboarding, service
from app.modules.types import ModuleManifest
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture()
def allocator(monkeypatch):
    counter = itertools.count(500)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _fresh_user(db, email="new@example.com"):
    """An account born the new way: no groups, no basics."""
    return service.create_user(db, email, "New User", "some-password", [])


def _legacy_user(db, email="old@example.com", *, complete=True):
    """An account that predates the wizard: built directly, so
    no creation path runs and no marker exists."""
    user = models.User(
        account_number="TV-000777",
        account_types=[MECHANIC] if complete else [],
        email=email,
        name="Old User",
        password_hash="x",
        email_verified=True,
        country="US" if complete else "",
        currency="USD",
        locale="en",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _plan(client, user):
    resp = client.get("/api/core/onboarding", headers=auth_headers(user))
    assert resp.status_code == 200
    return resp.json()


def _rows(db, user):
    return {
        r.step_key: r
        for r in db.query(models.OnboardingProgress)
        .filter(models.OnboardingProgress.user_id == user.id)
        .all()
    }


# -- signup is just an account --------------------------------------


def test_minimal_signup_creates_ungrouped_marked_account(db, allocator):
    user = _fresh_user(db)
    assert user.account_types == []
    assert user.country == ""
    # No segment until the wizard's step 1 picks the groups.
    assert user.account_number.startswith("TV-0")
    assert "-" not in user.account_number.removeprefix("TV-")
    rows = _rows(db, user)
    assert onboarding.FRESH_KEY in rows


def test_full_signup_payload_still_honored(db, allocator):
    user = service.create_user(
        db,
        "full@example.com",
        "Full User",
        "some-password",
        [MECHANIC],
        country="CA",
        currency="CAD",
        locale="es",
    )
    assert user.account_types == [MECHANIC]
    assert user.country == "CA"
    assert user.account_number.startswith("TV-M-")


# -- the plan ---------------------------------------------------------


def test_fresh_plan_is_wizard_flow_with_probes_pending(client, db, allocator):
    user = _fresh_user(db)
    plan = _plan(client, user)
    assert plan["flow"] == "wizard"
    assert plan["dismissed"] is False
    by_key = {s["key"]: s for s in plan["steps"]}
    assert by_key["account_type"]["status"] == "pending"
    assert by_key["basics"]["status"] == "pending"
    # No groups yet → the module steps haven't branched in.
    assert [s for s in plan["steps"] if s["kind"] == "module"] == []
    assert plan["new_feature_modules"] == []


def test_module_steps_are_the_registry_read(client, db, allocator):
    user = _fresh_user(db)
    headers = auth_headers(user)
    resp = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    assert resp.status_code == 200
    plan = _plan(client, user)
    by_key = {s["key"]: s for s in plan["steps"]}
    assert by_key["account_type"]["status"] == "done"
    prefs = client.get("/api/core/my-module-prefs", headers=headers).json()
    expected = {f"module:{p['id']}" for p in prefs}
    got = {s["key"] for s in plan["steps"] if s["kind"] == "module"}
    assert got == expected
    assert len(got) > 5  # a real registry, not a stub list


def test_registry_driven_new_module_joins_the_plan(
    client, db, allocator, monkeypatch
):
    """The registry-driven proof: a module that appears in
    FEATURE_MODULES becomes a wizard step with no code change."""
    user = _fresh_user(db)
    headers = auth_headers(user)
    client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    fake = ModuleManifest(
        name="fake_feature",
        version="1.0",
        description="A feature that did not exist yesterday.",
        route_prefix="/api/fake",
        router=APIRouter(),
        always_on=False,
        default_groups=(MECHANIC,),
        nav_label="Fake feature",
        nav_path="/fake",
        nav_order=999,
    )
    from app.modules import registry

    monkeypatch.setattr(
        registry, "FEATURE_MODULES", {**registry.FEATURE_MODULES, "fake_feature": fake}
    )
    plan = _plan(client, user)
    keys = {s["key"] for s in plan["steps"]}
    assert "module:fake_feature" in keys


# -- progress writes ----------------------------------------------------


def test_progress_round_trip_and_skip(client, db, allocator):
    user = _fresh_user(db)
    headers = auth_headers(user)
    # The pass starts with the account-type pick (owner ruling
    # 2026-11-07: the settings walk and module steps build on
    # it, and cannot be recorded before it — see the type-gate
    # test below). This test pins the round-trip itself, so it
    # picks first, like the real pass does.
    client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    resp = client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "setting:appearance", "status": "done"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["progress"]["setting:appearance"] == "done"
    resp = client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "setting:sharing", "status": "skipped"},
        headers=headers,
    )
    assert resp.json()["progress"]["setting:sharing"] == "skipped"
    plan = _plan(client, user)
    assert plan["progress"]["setting:appearance"] == "done"


def test_progress_rejects_bad_keys_and_statuses(client, db, allocator):
    user = _fresh_user(db)
    headers = auth_headers(user)
    for body in (
        {"step_key": "hax", "status": "done"},
        {"step_key": "module:no_such_module", "status": "done"},
        {"step_key": "__fresh__", "status": "done"},
        {"step_key": "setting:appearance", "status": "notified"},
        {"step_key": "setting:appearance", "status": "bogus"},
    ):
        resp = client.post(
            "/api/core/onboarding/progress", json=body, headers=headers
        )
        assert resp.status_code == 422, body


def test_downstream_steps_cannot_complete_before_the_type_pick(
    client, db, allocator
):
    """Ryan's ruling (2026-11-07): "an account type is required
    during the onboarding wizard. You cant pick available modules
    without an account type." The settings walk is group-filtered
    and the module list is type-filtered, so a typeless account
    cannot record a settings or module step done OR skipped —
    the API refuses (422) and nothing is written. The probe
    steps stay writable (they are the account's own record), and
    the very same downstream writes land the moment a type
    exists."""
    user = _fresh_user(db)
    headers = auth_headers(user)
    for key in ("setting:appearance", "module:borrowing"):
        for status_ in ("done", "skipped"):
            resp = client.post(
                "/api/core/onboarding/progress",
                json={"step_key": key, "status": status_},
                headers=headers,
            )
            assert resp.status_code == 422, (key, status_)
    plan = _plan(client, user)
    assert "setting:appearance" not in plan["progress"]
    assert "module:borrowing" not in plan["progress"]
    # Probe records are the account's own — still accepted.
    resp = client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "basics", "status": "skipped"},
        headers=headers,
    )
    assert resp.status_code == 200
    # Pick the type → the same downstream writes land.
    client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    resp = client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "setting:appearance", "status": "done"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["progress"]["setting:appearance"] == "done"


def test_probe_outranks_a_recorded_skip(client, db, allocator):
    """Account type is the required step: skipping it in the pass
    records the deferral, but the step stays pending until the
    account actually has groups — the probe is the truth."""
    user = _fresh_user(db)
    headers = auth_headers(user)
    client.post(
        "/api/core/onboarding/progress",
        json={"step_key": "account_type", "status": "skipped"},
        headers=headers,
    )
    plan = _plan(client, user)
    by_key = {s["key"]: s for s in plan["steps"]}
    assert by_key["account_type"]["status"] == "pending"
    client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    plan = _plan(client, user)
    by_key = {s["key"]: s for s in plan["steps"]}
    assert by_key["account_type"]["status"] == "done"


# -- dismissal ------------------------------------------------------------


def test_dismiss_and_reopen(client, db, allocator):
    user = _fresh_user(db)
    headers = auth_headers(user)
    resp = client.post("/api/core/onboarding/dismiss", headers=headers)
    assert resp.json()["dismissed"] is True
    # Dismissal marks nothing done.
    plan = _plan(client, user)
    assert plan["progress"].get("account_type") is None
    resp = client.post("/api/core/onboarding/reopen", headers=headers)
    assert resp.json()["dismissed"] is False


# -- existing + legacy flows ------------------------------------------------


def test_existing_account_takes_a_silent_baseline(client, db):
    user = _legacy_user(db)
    plan = _plan(client, user)
    assert plan["flow"] == "existing"
    assert plan["new_feature_modules"] == []
    # Silence means: nothing prompts. The plan still lists the
    # account's baseline modules as plain steps (the hub shows
    # the whole picture) — every one a baseline member, none
    # flagged new, none notified.
    module_steps = [s for s in plan["steps"] if s["kind"] == "module"]
    assert module_steps
    assert all(s["new"] is False for s in module_steps)
    assert all(s["status"] != "notified" for s in module_steps)
    rows = _rows(db, user)
    assert onboarding.FRESH_KEY not in rows
    baseline = json.loads(rows[onboarding.BASELINE_KEY].detail)
    assert "claims" in baseline
    notes = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .all()
    )
    assert notes == []


def test_legacy_incomplete_account_reads_legacy(client, db):
    user = _legacy_user(db, complete=False)
    plan = _plan(client, user)
    assert plan["flow"] == "legacy"


def _add_fake_module(monkeypatch, name="brand_new_feature"):
    from app.modules import registry

    fake = ModuleManifest(
        name=name,
        version="1.0",
        description="Shipped after your baseline.",
        route_prefix="/api/new",
        router=APIRouter(),
        always_on=False,
        default_groups=(MECHANIC,),
        nav_label="Brand new",
        nav_path="/new",
        nav_order=998,
    )
    monkeypatch.setattr(
        registry, "FEATURE_MODULES", {**registry.FEATURE_MODULES, name: fake}
    )
    return name


def test_new_feature_prompts_an_existing_account_exactly_once(
    client, db, monkeypatch
):
    user = _legacy_user(db)
    _plan(client, user)  # baseline taken
    name = _add_fake_module(monkeypatch)
    plan = _plan(client, user)
    assert plan["new_feature_modules"] == [name]
    step = next(s for s in plan["steps"] if s["key"] == f"module:{name}")
    assert step["status"] == "notified"
    assert step["new"] is True
    notes = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.kind == "onboarding_new_feature",
        )
        .all()
    )
    assert len(notes) == 1
    assert notes[0].data["module"] == name
    # Second read: no second note, still listed until resolved.
    plan = _plan(client, user)
    assert plan["new_feature_modules"] == [name]
    notes = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.kind == "onboarding_new_feature",
        )
        .all()
    )
    assert len(notes) == 1
    # Resolving it ends the prompting for good.
    headers = auth_headers(user)
    client.post(
        "/api/core/onboarding/progress",
        json={"step_key": f"module:{name}", "status": "skipped"},
        headers=headers,
    )
    plan = _plan(client, user)
    assert plan["new_feature_modules"] == []


def test_fresh_account_baseline_after_first_pass_settles(
    client, db, allocator, monkeypatch
):
    user = _fresh_user(db)
    headers = auth_headers(user)
    client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC]},
        headers=headers,
    )
    client.patch(
        "/api/core/me", json={"country": "US"}, headers=headers
    )
    plan = _plan(client, user)
    module_keys = [s["key"] for s in plan["steps"] if s["kind"] == "module"]
    assert module_keys
    for key in module_keys:
        client.post(
            "/api/core/onboarding/progress",
            json={"step_key": key, "status": "done"},
            headers=headers,
        )
    plan = _plan(client, user)
    rows = _rows(db, user)
    assert onboarding.BASELINE_KEY in rows
    # The settled plan still LISTS the pass's module steps with
    # their recorded state — the hub's progress panel shows the
    # whole pass after finishing, not only what is new. (A
    # browser-proof catch, 2026-11-07: the modules row vanished
    # from the finished panel when the baseline branch returned
    # only not-yet-baselined modules.)
    settled_modules = {
        s["key"]: s for s in plan["steps"] if s["kind"] == "module"
    }
    assert set(settled_modules) == set(module_keys)
    assert all(
        s["status"] == "done" and s["new"] is False
        for s in settled_modules.values()
    )
    assert plan["new_feature_modules"] == []
    # A module arriving after the pass reads as new, with a note.
    name = _add_fake_module(monkeypatch)
    plan = _plan(client, user)
    assert plan["new_feature_modules"] == [name]
    notes = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.kind == "onboarding_new_feature",
        )
        .all()
    )
    assert len(notes) == 1


# -- deletion ----------------------------------------------------------------


def test_delete_account_sweeps_onboarding_rows(db, allocator):
    user = _fresh_user(db)
    assert _rows(db, user)
    service.delete_account(db, user)
    assert _rows(db, user) == {}
