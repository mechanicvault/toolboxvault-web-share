"""Preinstalled starter categories (owner spec 2026-10-25).

Every account carries four starter categories — Batteries,
Hand Tools, Power Tools, Pneumatic Tools — permanent, starred
by default, seeded on the ONE account-creation path. The seed
is adoptive (a matching pre-existing category is marked, never
duplicated) and reconciles the legacy battery category text
"Battery" onto "Batteries". Starters can't be deleted or
merged away; Batteries can't be renamed; the tool starters
rename with their star (and system_key) riding along.
"""

import itertools
import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_signup_basics.py).
    counter = itertools.count(903000)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )

STARTER_KEYS = ["batteries", "hand_tools", "power_tools", "pneumatic_tools"]
STARTER_NAMES_EN = ["Batteries", "Hand Tools", "Power Tools", "Pneumatic Tools"]
STARTER_NAMES_ES = [
    "Baterías",
    "Herramientas manuales",
    "Herramientas eléctricas",
    "Herramientas neumáticas",
]


def _make_user(db, account_number, email, *, locale="", name="Starter Owner"):
    """A user built directly in the db — deliberately NOT via
    the creation path, so tests control when the seed runs."""
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-001301", "starter1@example.com")


def _tool(client, user, **payload):
    payload.setdefault("name", "Starter wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Starter pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _categories(client, user):
    resp = client.get("/api/inventory/categories", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _signup(client, db, email, locale="en"):
    resp = client.post(
        "/api/core/signup",
        json={
            "email": email,
            "name": "Fresh Signup",
            "password": "Signup-2026-ok",
            "account_types": [MECHANIC],
            "country": "US",
            "currency": "USD",
            "locale": locale,
        },
    )
    assert resp.status_code == 201, resp.text
    return db.scalars(
        select(core_models.User).where(core_models.User.email == email)
    ).one()


# -- the seed ---------------------------------------------------------------------


def test_signup_seeds_the_four_starters_starred(client, db):
    user = _signup(client, db, "fresh-starter@example.com")
    listed = _categories(client, user)
    assert [c["name"] for c in listed] == STARTER_NAMES_EN
    assert [c["system_key"] for c in listed] == STARTER_KEYS
    assert all(c["starred"] and c["preinstalled"] and c["registered"] for c in listed)
    assert all(c["item_count"] == 0 for c in listed)


def test_signup_seeds_spanish_names_for_a_spanish_account(client, db):
    user = _signup(client, db, "fresh-starter-es@example.com", locale="es")
    listed = _categories(client, user)
    assert [c["name"] for c in listed] == STARTER_NAMES_ES
    assert [c["system_key"] for c in listed] == STARTER_KEYS
    assert all(c["starred"] and c["preinstalled"] for c in listed)


def test_seed_is_idempotent_and_adoptive(client, owner, db):
    # Pre-seed state: items filed under a starter's name, the
    # legacy battery spelling, and a registered starter spelling.
    _tool(client, owner, name="A", category="Hand Tools")
    _battery(client, owner, name="B", category="Battery", model="M18")
    _battery(client, owner, name="C", category="Battery", model="M20")
    created = client.post(
        "/api/inventory/categories",
        json={"name": "power tools"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text

    assert inventory_service.ensure_starter_categories(db, owner.id, "en") is True
    listed = _categories(client, owner)
    # Exactly the four starters — nothing duplicated.
    assert [c["system_key"] for c in listed] == STARTER_KEYS
    by_key = {c["system_key"]: c for c in listed}
    # The item-carried Hand Tools was adopted, items and all.
    assert by_key["hand_tools"]["item_count"] == 1
    assert by_key["hand_tools"]["starred"] is True
    # The registered "power tools" row was adopted in place —
    # the owner's own spelling is the display name.
    assert by_key["power_tools"]["name"] == "power tools"
    # The legacy battery spelling reconciled onto Batteries:
    # the starter holds both batteries, and no item anywhere
    # still carries the singular text.
    assert by_key["batteries"]["name"] == "Batteries"
    assert by_key["batteries"]["item_count"] == 2
    batteries = client.get(
        "/api/inventory/batteries", headers=auth_headers(owner)
    ).json()
    assert {b["category"] for b in batteries} == {"Batteries"}

    # A second run changes nothing.
    assert inventory_service.ensure_starter_categories(db, owner.id, "en") is False
    assert _categories(client, owner) == listed
    rows = db.scalars(
        select(inventory_models.InventoryCategory).where(
            inventory_models.InventoryCategory.owner_id == owner.id
        )
    ).all()
    assert len(rows) == 4


def test_seed_folds_legacy_battery_items_onto_an_existing_batteries_row(
    client, owner, db
):
    # Mixed pre-seed state: a registered "Batteries" category
    # AND items still filed under the legacy singular — the
    # items must land on the starter, or its row link would
    # list an empty category while batteries exist.
    created = client.post(
        "/api/inventory/categories",
        json={"name": "Batteries"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    _battery(client, owner, name="Old", category="Battery", model="M12")

    assert inventory_service.ensure_starter_categories(db, owner.id, "en") is True
    listed = _categories(client, owner)
    assert [c["system_key"] for c in listed] == STARTER_KEYS
    by_key = {c["system_key"]: c for c in listed}
    assert by_key["batteries"]["item_count"] == 1
    assert by_key["batteries"]["starred"] is True
    assert all(c["name"] != "Battery" for c in listed)
    batteries = client.get(
        "/api/inventory/batteries", headers=auth_headers(owner)
    ).json()
    assert {b["category"] for b in batteries} == {"Batteries"}


def test_seed_never_restars_an_unstarred_starter(client, owner, db):
    assert inventory_service.ensure_starter_categories(db, owner.id, "en") is True
    unstarred = client.post(
        "/api/inventory/categories/star",
        json={"name": "Hand Tools", "starred": False},
        headers=auth_headers(owner),
    )
    assert unstarred.status_code == 200, unstarred.text
    # Re-running the seed fills gaps only — the owner's unstar
    # is theirs to keep.
    assert inventory_service.ensure_starter_categories(db, owner.id, "en") is False
    by_key = {c["system_key"]: c for c in _categories(client, owner)}
    assert by_key["hand_tools"]["starred"] is False


def test_seed_stars_count_toward_the_cap(client, db):
    user = _signup(client, db, "cap-starter@example.com")
    # 4 seed stars (cap is 5, owner spec 2026-10-25): ONE more
    # of the owner's own fits, the next total star is refused
    # with the cap code.
    resp = client.post(
        "/api/inventory/categories",
        json={"name": "Extra 0", "starred": True},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["starred"] is True
    listed = _categories(client, user)
    assert sum(1 for c in listed if c["starred"]) == 5
    refused = client.post(
        "/api/inventory/categories/star",
        json={"name": "Extra 0", "starred": True},
        headers=auth_headers(user),
    )
    # Extra 0 is already starred (idempotent) — the cap bites on
    # a fresh star instead (below).
    assert refused.status_code == 200, refused.text
    created = client.post(
        "/api/inventory/categories",
        json={"name": "One Too Many", "starred": True},
        headers=auth_headers(user),
    )
    assert created.status_code == 201, created.text
    assert created.json()["starred"] is False
    assert created.json()["star_capped"] is True
    direct = client.post(
        "/api/inventory/categories/star",
        json={"name": "One Too Many", "starred": True},
        headers=auth_headers(user),
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["detail"]["code"] == "star_limit_reached"


# -- the guards -------------------------------------------------------------------


def test_starters_cannot_be_deleted_or_merged_away(client, db):
    user = _signup(client, db, "guard-starter@example.com")
    for name in ("Batteries", "Hand Tools"):
        refused = client.post(
            "/api/inventory/categories/delete",
            json={"name": name},
            headers=auth_headers(user),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "category_preinstalled"
    refused = client.post(
        "/api/inventory/categories/merge",
        json={"source_name": "Power Tools", "target_name": "Hand Tools"},
        headers=auth_headers(user),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "category_preinstalled"
    # Merging INTO a starter is fine — the target survives.
    _tool(client, user, name="W", category="Welding")
    merged = client.post(
        "/api/inventory/categories/merge",
        json={"source_name": "Welding", "target_name": "Hand Tools"},
        headers=auth_headers(user),
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["system_key"] == "hand_tools"
    assert merged.json()["preinstalled"] is True


def test_batteries_name_is_fixed_but_tool_starters_rename(client, db):
    user = _signup(client, db, "rename-starter@example.com")
    refused = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "Batteries", "new_name": "Cells"},
        headers=auth_headers(user),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "category_preinstalled"

    _tool(client, user, name="Hammer", category="Hand Tools")
    renamed = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "Hand Tools", "new_name": "Hand Tools — Shop"},
        headers=auth_headers(user),
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    # The star AND the starter identity ride the rename.
    assert body["starred"] is True
    assert body["system_key"] == "hand_tools"
    assert body["preinstalled"] is True
    tools = client.get("/api/inventory", headers=auth_headers(user)).json()
    assert {t["category"] for t in tools} == {"Hand Tools — Shop"}


# -- the picker contract (API level) ----------------------------------------------


def test_battery_create_defaults_to_the_batteries_category(client, db):
    user = _signup(client, db, "battery-default@example.com")
    battery = _battery(client, user, name="No category sent")
    assert battery["category"] == "Batteries"
    by_key = {c["system_key"]: c for c in _categories(client, user)}
    assert by_key["batteries"]["item_count"] == 1


def test_picker_create_then_file_and_legacy_value_round_trip(client, owner):
    # The picker's inline add: create through the categories API
    # (NOT born starred — filing is not row display), then file
    # the item under it.
    created = client.post(
        "/api/inventory/categories",
        json={"name": "Welding"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    assert created.json()["starred"] is False
    assert created.json()["preinstalled"] is False
    tool = _tool(client, owner, name="Welder", category="Welding")
    assert tool["category"] == "Welding"

    # A legacy free-typed category (never registered) survives
    # an edit untouched: the value round-trips byte for byte.
    legacy = _tool(client, owner, name="Odd", category="Oddball Stuff")
    listed = {c["name"]: c for c in _categories(client, owner)}
    assert listed["Oddball Stuff"]["registered"] is False
    updated = client.put(
        f"/api/inventory/{legacy['id']}",
        json={"name": "Odd", "category": "Oddball Stuff"},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["category"] == "Oddball Stuff"
