"""Community Parts pool (2026-10-19, community suite build 1):
the public face of the Used Parts shelf.

Pins:
- visibility resolution: entry override > category setting >
  owner default, and the default of defaults is PRIVATE;
- the publish gate (the community suite's paid-contribution
  rule): enforced only while the entitlements enforcement
  switch is on, paid sources only, TRIAL excluded — checked on
  part create, part update (merged state), pool settings
  writes, and again at listing read time (a lapsed seller stops
  listing);
- the listing payload's EXACT keys, for signed-in AND anonymous
  readers: no storage location, no notes, no custom data, no
  email, private parts never present;
- the phone rule: shown only on opt-in (profile toggle or the
  part's override), the area rule (part override, else profile);
- search: year / make / model / engine / category filters and
  text over title + notes (notes are searched, never shown);
- the operator pool switch hides the pool entirely (404s);
- the audit journal captures pool changes (parts are registered
  entities; pool settings ride their own spec).
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.core import journal
from app.modules.core import models as core_models
from app.modules.parts import models as parts_models
from app.modules.parts import pool
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"

LISTING_KEYS = {
    "id",
    "title",
    "quantity",
    "condition",
    "category",
    "year",
    "make",
    "model",
    "engine",
    "asking_price",
    "area_label",
    "photos",
    "seller_id",
    "seller_name",
    "seller_member_since",
    "seller_currency",
    "phone",
    "created_at",
    "updated_at",
}


def _make_user(db, account_number, email, account_types, *, operator=False, name="Pool User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seller(db):
    return _make_user(db, "TV-M-000501", "seller@example.com", [MECHANIC], name="Sally Seller")


@pytest.fixture()
def buyer(db):
    return _make_user(db, "TV-S-000502", "buyer@example.com", [SHOP], name="Ben Buyer")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000503", "poolop@example.com", [MECHANIC], operator=True)


def _part(client, user, **fields):
    payload = {"title": fields.pop("title", "Spare part")}
    payload.update(fields)
    response = client.post("/api/parts/parts", json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _community(client, user=None, **params):
    headers = auth_headers(user) if user is not None else {}
    response = client.get("/api/parts/community", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _public(client, **params):
    response = client.get("/api/parts/public/community", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _pay(db, user, *, status="active"):
    sub = billing_models.Subscription(
        user_id=user.id, plan_key="pro", status=status, source="stripe"
    )
    db.add(sub)
    db.commit()
    return sub


def _enforce(db, on=True):
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, on)


# -- visibility resolution ------------------------------------------------------------


def test_default_is_private_and_nothing_leaks(client, seller, buyer):
    _part(client, seller, title="LS alternator", notes="from the blue truck")
    assert _community(client, buyer) == []
    assert _public(client) == []
    mine = client.get("/api/parts/parts", headers=auth_headers(seller)).json()
    assert mine[0]["visibility"] == "private"
    assert mine[0]["is_public"] is False


def test_entry_override_publishes_and_unpublishes(client, seller, buyer):
    part = _part(client, seller, title="Torque converter", visibility="public")
    assert part["visibility"] == "public" and part["is_public"] is True
    assert [row["title"] for row in _community(client, buyer)] == ["Torque converter"]
    updated = client.put(
        f"/api/parts/parts/{part['id']}",
        json={"visibility": "private"},
        headers=auth_headers(seller),
    )
    assert updated.status_code == 200
    assert _community(client, buyer) == []


def test_category_setting_and_override_precedence(client, seller, buyer):
    engine = _part(client, seller, title="Intake", category="Engine")
    brakes = _part(client, seller, title="Caliper", category="Brakes")
    response = client.put(
        "/api/parts/pool/settings",
        json={"category_visibility": {"Engine": "public"}},
        headers=auth_headers(seller),
    )
    assert response.status_code == 200, response.text
    titles = {row["title"] for row in _community(client, buyer)}
    assert titles == {"Intake"}
    # The entry override beats the category setting both ways.
    client.put(
        f"/api/parts/parts/{engine['id']}",
        json={"visibility": "private"},
        headers=auth_headers(seller),
    )
    client.put(
        f"/api/parts/parts/{brakes['id']}",
        json={"visibility": "public"},
        headers=auth_headers(seller),
    )
    titles = {row["title"] for row in _community(client, buyer)}
    assert titles == {"Caliper"}
    # The override STILL beats a public default (entry > global):
    client.put(
        "/api/parts/pool/settings",
        json={"default_visibility": "public"},
        headers=auth_headers(seller),
    )
    titles = {row["title"] for row in _community(client, buyer)}
    assert titles == {"Caliper"}
    # Clearing the override (explicit null) lets the default in.
    client.put(
        f"/api/parts/parts/{engine['id']}",
        json={"visibility": None},
        headers=auth_headers(seller),
    )
    titles = {row["title"] for row in _community(client, buyer)}
    assert titles == {"Intake", "Caliper"}


def test_resolution_matrix_service_level(db, seller):
    settings = pool.get_settings(db, seller.id)
    part = parts_models.Part(owner_id=seller.id, title="X", category="Engine")
    assert pool.resolve_visibility(part, settings) == "private"
    settings.category_visibility = {"Engine": "public"}
    assert pool.resolve_visibility(part, settings) == "public"
    part.visibility = "private"
    assert pool.resolve_visibility(part, settings) == "private"
    part.visibility = "public"
    settings.default_visibility = "private"
    assert pool.resolve_visibility(part, settings) == "public"


# -- the publish gate -----------------------------------------------------------------


def test_gate_open_while_enforcement_off(client, db, seller, buyer):
    # Free account, enforcement OFF (the pre-launch posture):
    # publishing works — the gate mirrors the item cap exactly.
    part = _part(client, seller, title="Open gate part", visibility="public")
    assert part["is_public"] is True
    assert len(_community(client, buyer)) == 1


def test_gate_blocks_free_and_trial_when_enforced(client, db, seller, buyer):
    _enforce(db)
    refused = client.post(
        "/api/parts/parts",
        json={"title": "Gated part", "visibility": "public"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "paid_plan_required"
    # A private part is always fine.
    ok = client.post(
        "/api/parts/parts", json={"title": "Shelf part"}, headers=auth_headers(seller)
    )
    assert ok.status_code == 201
    # Flipping it public is refused too (merged-state update gate).
    refused = client.put(
        f"/api/parts/parts/{ok.json()['id']}",
        json={"visibility": "public"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    # A settings write that would publish it is refused as well.
    refused = client.put(
        "/api/parts/pool/settings",
        json={"default_visibility": "public"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    # A TRIAL is not a paid plan to the gate.
    _pay(db, seller, status="trialing")
    refused = client.put(
        f"/api/parts/parts/{ok.json()['id']}",
        json={"visibility": "public"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    # Private settings writes stay free.
    assert (
        client.put(
            "/api/parts/pool/settings",
            json={"category_visibility": {"Engine": "private"}},
            headers=auth_headers(seller),
        ).status_code
        == 200
    )


def test_gate_admits_paid_and_unpublish_always_works(client, db, seller, buyer):
    _pay(db, seller)
    _enforce(db)
    part = _part(client, seller, title="Paid listing", visibility="public")
    assert len(_community(client, buyer)) == 1
    # Ordinary edits are fine while paid…
    edited = client.put(
        f"/api/parts/parts/{part['id']}",
        json={"title": "Paid listing (revised)"},
        headers=auth_headers(seller),
    )
    assert edited.status_code == 200
    # …the plan lapses: reads stop listing it AND edits that keep
    # it public are refused — but unpublishing always works.
    sub = db.scalars(select(billing_models.Subscription)).first()
    db.delete(sub)
    db.commit()
    assert _community(client, buyer) == []
    refused = client.put(
        f"/api/parts/parts/{part['id']}",
        json={"title": "Still public edit"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    unpublish = client.put(
        f"/api/parts/parts/{part['id']}",
        json={"visibility": "private"},
        headers=auth_headers(seller),
    )
    assert unpublish.status_code == 200


# -- the payload contract ---------------------------------------------------------------


def test_listing_payload_exact_keys_signed_in_and_anonymous(client, db, seller):
    seller.public_area_label = "Northern MN"
    seller.contact_phone = "218-555-0142"
    db.commit()
    location = client.post(
        "/api/parts/locations",
        json={"name": "Warehouse A", "level": "warehouse"},
        headers=auth_headers(seller),
    ).json()
    _part(
        client,
        seller,
        title="6.0L oil cooler",
        notes="bought from Dave, owes a favor",
        location_id=location["id"],
        category="Engine",
        year=2007,
        make="Ford",
        model="F-250",
        engine="6.0L Power Stroke",
        asking_price="249.99",
        visibility="public",
    )
    for rows in (_community(client, seller), _public(client)):
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == LISTING_KEYS
        assert row["year"] == 2007 and row["make"] == "Ford"
        assert row["asking_price"] == "249.99"
        assert row["area_label"] == "Northern MN"
        assert row["seller_name"] == "Sally Seller"
        # The phone is NOT opted in: absent, even though one is
        # on file. The storage location and the notes never ride.
        assert row["phone"] is None
        blob = str(row).lower()
        assert "warehouse" not in blob and "dave" not in blob
        assert "seller@example.com" not in blob


def test_phone_and_area_override_rules(client, db, seller, buyer):
    seller.contact_phone = "218-555-0142"
    seller.public_area_label = "Profile Area"
    db.commit()
    shown = _part(client, seller, title="Phone on", visibility="public",
                  show_phone_override=True, public_area_label="Part Area")
    hidden = _part(client, seller, title="Phone off", visibility="public")
    rows = {row["title"]: row for row in _community(client, buyer)}
    # The part override beats the (off) profile toggle.
    assert rows["Phone on"]["phone"] == "218-555-0142"
    assert rows["Phone on"]["area_label"] == "Part Area"
    assert rows["Phone off"]["phone"] is None
    assert rows["Phone off"]["area_label"] == "Profile Area"
    # Profile toggle on: the plain part shows the phone too…
    seller.show_phone = True
    db.commit()
    rows = {row["title"]: row for row in _community(client, buyer)}
    assert rows["Phone off"]["phone"] == "218-555-0142"
    # …unless the part's override says no.
    client.put(
        f"/api/parts/parts/{hidden['id']}",
        json={"show_phone_override": False},
        headers=auth_headers(seller),
    )
    rows = {row["title"]: row for row in _community(client, buyer)}
    assert rows["Phone off"]["phone"] is None


# -- search ---------------------------------------------------------------------------


def test_search_filters_and_text(client, seller, buyer):
    _part(client, seller, title="Silverado alternator", visibility="public",
          year=2018, make="Chevrolet", model="Silverado 1500", engine="5.3L V8",
          category="Electrical", notes="tested good on the bench")
    _part(client, seller, title="F-150 starter", visibility="public",
          year=2016, make="Ford", model="F-150", engine="5.0L V8",
          category="Electrical")
    _part(client, seller, title="Silverado leaf spring", visibility="public",
          year=2018, make="Chevrolet", model="Silverado 1500", engine="5.3L V8",
          category="Suspension")

    def titles(**params):
        return {row["title"] for row in _community(client, buyer, **params)}

    assert titles(year=2018) == {"Silverado alternator", "Silverado leaf spring"}
    assert titles(make="chev") == {"Silverado alternator", "Silverado leaf spring"}
    assert titles(model="f-150") == {"F-150 starter"}
    assert titles(engine="5.3") == {"Silverado alternator", "Silverado leaf spring"}
    assert titles(category="electrical") == {"Silverado alternator", "F-150 starter"}
    # Text searches the NOTES too (they're indexed, never shown).
    assert titles(q="bench") == {"Silverado alternator"}
    assert titles(q="silverado spring") == {"Silverado leaf spring"}
    assert titles(seller_id=str(seller.id)) == {
        "Silverado alternator",
        "F-150 starter",
        "Silverado leaf spring",
    }
    assert titles(seller_id=str(buyer.id)) == set()


# -- the pool switch + journal ---------------------------------------------------------


def test_pool_switch_hides_everything(client, db, seller, buyer):
    _part(client, seller, title="Switch part", visibility="public")
    assert len(_public(client)) == 1
    entitlements.set_setting(db, pool.POOL_ENABLED_KEY, False)
    assert client.get("/api/parts/public/community").status_code == 404
    assert client.get(
        "/api/parts/community", headers=auth_headers(buyer)
    ).status_code == 404
    mine = client.get("/api/parts/parts", headers=auth_headers(seller)).json()
    assert mine[0]["is_public"] is False
    # The owner's own shelf is untouched.
    assert mine[0]["visibility"] == "public"


def test_admin_settings_carry_spam_and_pool_switch(client, db, operator, seller):
    view = client.get("/api/admin/settings", headers=auth_headers(operator)).json()
    assert view["parts_pool_enabled"] is True
    assert view["spam"]["blast_threshold"] == 3
    assert view["spam"]["tiers"]["0"]["new_threads_per_hour"] == 2
    assert "bit.ly" in view["spam"]["blocked_domains"]
    updated = client.put(
        "/api/admin/settings",
        json={
            "community_parts_pool_enabled": False,
            "spam": {"blast_threshold": 5, "tiers": {"0": {"messages_per_hour": 7}}},
        },
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["parts_pool_enabled"] is False
    assert body["spam"]["blast_threshold"] == 5
    # The per-tier per-cap merge: untouched caps keep their values.
    assert body["spam"]["tiers"]["0"]["messages_per_hour"] == 7
    assert body["spam"]["tiers"]["0"]["new_threads_per_hour"] == 2
    # And the pool really is hidden now.
    assert client.get("/api/parts/public/community").status_code == 404
    # The admin settings writes are audit-logged like the rest.
    page = client.get(
        "/api/admin/audit?action=setting.update", headers=auth_headers(operator)
    ).json()
    rows = page["items"] if isinstance(page, dict) else page
    targets = {row["target"] for row in rows}
    assert pool.POOL_ENABLED_KEY in targets
    assert "spam.config" in targets


def test_journal_captures_pool_changes(client, db, seller):
    part = _part(client, seller, title="Journaled part")
    client.put(
        f"/api/parts/parts/{part['id']}",
        json={"visibility": "public"},
        headers=auth_headers(seller),
    )
    client.put(
        "/api/parts/pool/settings",
        json={"default_visibility": "public"},
        headers=auth_headers(seller),
    )
    entries, _total = journal.list_entries(db, seller.id, limit=100)
    part_updates = [
        e for e in entries if e.entity_type == "part" and e.action == "update"
    ]
    assert part_updates, "the visibility flip must journal as a part update"
    assert part_updates[0].after.get("visibility") == "public"
    settings_entries = [e for e in entries if e.entity_type == "part_pool_setting"]
    assert settings_entries, "pool settings writes must journal"
    assert any(
        (e.after or {}).get("default_visibility") == "public"
        for e in settings_entries
    )


def test_export_carries_pool_facts(client, db, seller):
    _part(client, seller, title="Exported part", visibility="public",
          year=2011, make="Ram", category="Engine")
    from app.modules.parts import service as parts_service

    rows = parts_service.export_rows(db, seller.id)
    assert rows["pool_settings"] is not None
    exported = rows["parts"][0]
    assert exported["visibility"] == "public"
    assert exported["year"] == 2011 and exported["make"] == "Ram"
