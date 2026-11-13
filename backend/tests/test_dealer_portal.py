"""Dealer portal core (2026-10-19): agent profiles, company
representations with operator verification, public listings under
the owner's visibility rule (publicly_listed DEFAULT OFF), one-tap
preferred agents, the private -> platform switch (lossless,
reversible), and aggregate-only dealer home stats.

Privacy pins throughout: a public agent card carries EXACTLY the
fields the agent filled in — the account email never falls back
in — and no payload anywhere names the users who prefer an agent.
"""

import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name="Portal User", is_operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        is_operator=is_operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def agent(db):
    return _make_user(
        db, "TV-D-000501", "agent@example.com", (DEALER,), name="Andy Agent"
    )


@pytest.fixture()
def agent2(db):
    return _make_user(
        db, "TV-D-000502", "agent2@example.com", (DEALER,), name="Second Agent"
    )


@pytest.fixture()
def mechanic(db):
    return _make_user(
        db, "TV-M-000501", "mech@example.com", (MECHANIC,), name="Mike Mechanic"
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000500", "op@example.com", (MECHANIC,), is_operator=True
    )


def _directory_company(client, operator, name="Matco Tools"):
    resp = client.post(
        "/api/admin/dealer-companies",
        json={"name": name, "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_profile(client, user, **overrides):
    payload = {
        "display_name": "Andy the Tool Guy",
        "phone": "555-0100",
        "contact_email": "andy@truck.example",
        "service_area": "Central Minnesota",
        "bio": "Matco truck, Tuesdays.",
        # Dealer build rule: a public listing REQUIRES a service
        # area — the fixture's listed profiles carry the blunt
        # ZIP + radius shape (Little Falls, MN, 60 miles).
        "area_type": "radius",
        "area_zip": "56345",
        "area_center_lat": 45.9811,
        "area_center_lng": -94.3604,
        "area_radius_miles": 60,
        "publicly_listed": True,
    }
    payload.update(overrides)
    resp = client.put("/api/dealers/profile/me", json=payload, headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _represent(client, user, company_id):
    resp = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": company_id},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _detail(client, user, company_id):
    resp = client.get(
        f"/api/dealers/companies/{company_id}/detail", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- profiles -----------------------------------------------------------------


def test_profile_defaults_come_from_the_account(client, agent):
    view = client.get("/api/dealers/profile/me", headers=auth_headers(agent)).json()
    assert view == {
        "display_name": "Andy Agent",
        "phone": "",
        "contact_email": "",
        "service_area": "",
        "bio": "",
        "photo_url": None,
        "has_photo": False,
        "publicly_listed": False,  # the owner's rule: OFF until chosen
        # Dealer build: no territory defined yet.
        "has_area": False,
        "area_type": None,
        "area_polygon": None,
        "area_center_lat": None,
        "area_center_lng": None,
        "area_radius_miles": None,
        "area_zip": "",
        # Audit A2: no route schedule until the agent sets one.
        "route_frequency": None,
        "route_day_of_week": None,
        "route_anchor_date": None,
        "route_next_visit": None,
    }


def test_profile_update_round_trip(client, agent):
    saved = _set_profile(client, agent)
    assert saved["display_name"] == "Andy the Tool Guy"
    assert saved["publicly_listed"] is True
    again = client.get("/api/dealers/profile/me", headers=auth_headers(agent)).json()
    assert again == saved


def test_profile_photo_flow(client, agent, monkeypatch):
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    # Non-image refused at issuance (photo kind rules).
    resp = client.post(
        "/api/dealers/profile/me/photo/upload-url",
        json={"filename": "x.pdf", "content_type": "application/pdf", "size_bytes": 10},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/dealers/profile/me/photo/upload-url",
        json={"filename": "me.jpg", "content_type": "image/jpeg", "size_bytes": 100},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 200, resp.text
    key = resp.json()["key"]
    assert key.startswith(f"{agent.id}/dealer-profile/")
    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=100, content_type="image/jpeg"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda k, length=512: b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    )
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_get_url",
        lambda k, expires_in=604800: f"https://files.test/read/{k}",
    )
    attached = client.post(
        "/api/dealers/profile/me/photo",
        json={"key": key, "filename": "me.jpg"},
        headers=auth_headers(agent),
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["has_photo"] is True
    assert attached.json()["photo_url"] == f"https://files.test/read/{key}"

    # A key outside my profile namespace is refused.
    resp = client.post(
        "/api/dealers/profile/me/photo",
        json={"key": "someone/else/photo/x.jpg"},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422

    monkeypatch.setattr(storage_module.storage, "delete", lambda k: None)
    removed = client.delete(
        "/api/dealers/profile/me/photo", headers=auth_headers(agent)
    )
    assert removed.status_code == 200
    assert removed.json()["has_photo"] is False


# -- representations + public listing ------------------------------------------


def test_representation_requires_dealer_group_and_directory(client, mechanic, operator):
    company = _directory_company(client, operator)
    resp = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": company["id"]},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    # A private company can't be represented.
    mine = client.post(
        "/api/dealers/companies",
        json={"name": "Local Co", "phones": []},
        headers=auth_headers(mechanic),
    ).json()
    agent_user = mechanic  # still not a dealer; use a real dealer below
    assert agent_user is not None
    resp = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": mine["id"]},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422


def test_listing_visibility_matrix(client, agent, agent2, mechanic, operator):
    matco = _directory_company(client, operator, "Matco Tools")
    snapon = _directory_company(client, operator, "Snap-on")

    # Represent + profile filled but listing OFF -> nowhere.
    _represent(client, agent, matco["id"])
    _set_profile(client, agent, publicly_listed=False)
    assert _detail(client, mechanic, matco["id"])["agents"] == []

    # Listing ON -> appears on the represented company only.
    _set_profile(client, agent, publicly_listed=True)
    cards = _detail(client, mechanic, matco["id"])["agents"]
    assert [c["display_name"] for c in cards] == ["Andy the Tool Guy"]
    assert _detail(client, mechanic, snapon["id"])["agents"] == []

    # A second agent who represents Snap-on never leaks onto Matco.
    _represent(client, agent2, snapon["id"])
    _set_profile(client, agent2, publicly_listed=True)
    assert [c["display_name"] for c in _detail(client, mechanic, matco["id"])["agents"]] == [
        "Andy the Tool Guy"
    ]

    # Listing back OFF -> gone again.
    _set_profile(client, agent, publicly_listed=False)
    assert _detail(client, mechanic, matco["id"])["agents"] == []


def test_public_card_exact_keys_and_no_account_fallback(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    # Sparse profile: nothing filled but the territory (the dealer
    # build REQUIRES an area before the listing switch will flip)
    # and the switch itself. The card must carry the identity keys
    # and NOTHING else — the geometry never leaks onto the card,
    # and the account email (agent@example.com) appears nowhere.
    resp = client.put(
        "/api/dealers/profile/me",
        json={
            "area_type": "radius",
            "area_zip": "56345",
            "area_center_lat": 45.9811,
            "area_center_lng": -94.3604,
            "area_radius_miles": 60,
        },
        headers=auth_headers(agent),
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        "/api/dealers/profile/me",
        json={"publicly_listed": True},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 200
    card = _detail(client, mechanic, matco["id"])["agents"][0]
    assert set(card.keys()) == {"agent_user_id", "display_name", "verified"}
    assert card["display_name"] == "Andy Agent"  # account name, not email
    assert "agent@example.com" not in str(card)

    # Filled profile: exactly the filled fields join the card.
    _set_profile(client, agent)
    card = _detail(client, mechanic, matco["id"])["agents"][0]
    assert set(card.keys()) == {
        "agent_user_id",
        "display_name",
        "verified",
        "service_area",
        "bio",
        "phone",
        "contact_email",
    }
    assert card["phone"] == "555-0100"
    assert card["contact_email"] == "andy@truck.example"  # THEIR chosen address
    assert card["verified"] is False  # self-asserted = unverified


def test_representation_duplicate_is_idempotent(client, agent, operator):
    matco = _directory_company(client, operator)
    first = _represent(client, agent, matco["id"])
    second = _represent(client, agent, matco["id"])
    assert first["id"] == second["id"]
    rows = client.get(
        "/api/dealers/profile/me/representations", headers=auth_headers(agent)
    ).json()
    assert len(rows) == 1


def test_operator_verify_flips_badge_and_audits(client, db, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    rep = _represent(client, agent, matco["id"])
    _set_profile(client, agent)

    # Non-operators can't touch the review surface.
    assert (
        client.get("/api/admin/dealer-representations", headers=auth_headers(mechanic)).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/admin/dealer-representations/{rep['id']}/verify",
            json={"verified": True},
            headers=auth_headers(mechanic),
        ).status_code
        == 403
    )

    rows = client.get(
        "/api/admin/dealer-representations", headers=auth_headers(operator)
    ).json()
    assert len(rows) == 1
    assert rows[0]["agent_account_number"] == "TV-D-000501"
    assert rows[0]["verified"] is False

    verified = client.put(
        f"/api/admin/dealer-representations/{rep['id']}/verify",
        json={"verified": True},
        headers=auth_headers(operator),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True
    card = _detail(client, mechanic, matco["id"])["agents"][0]
    assert card["verified"] is True

    audit_rows = (
        db.query(core_models.AuditLog)
        .filter(core_models.AuditLog.action == "dealer_representation.verify")
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_email == "op@example.com"

    unverified = client.put(
        f"/api/admin/dealer-representations/{rep['id']}/verify",
        json={"verified": False},
        headers=auth_headers(operator),
    )
    assert unverified.json()["verified"] is False
    card = _detail(client, mechanic, matco["id"])["agents"][0]
    assert card["verified"] is False


# -- one-tap preferred + stats ---------------------------------------------------


def _one_tap(client, user, company_id, agent_user_id):
    return client.post(
        "/api/dealers/preferred/by-agent",
        json={"company_id": company_id, "agent_user_id": str(agent_user_id)},
        headers=auth_headers(user),
    )


def test_one_tap_preferred_and_duplicate_kind_refusal(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    _set_profile(client, agent)

    first = _one_tap(client, mechanic, matco["id"], agent.id)
    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    assert first.json()["preferred"]["kind"] == "platform"

    # Duplicate: kindly refused — same row back, created False, and
    # still exactly ONE preference row.
    second = _one_tap(client, mechanic, matco["id"], agent.id)
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["preferred"]["id"] == first.json()["preferred"]["id"]
    mine = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    assert len(mine) == 1

    # The company detail shows it under MY preferred agents.
    detail = _detail(client, mechanic, matco["id"])
    assert [p["id"] for p in detail["my_preferred_agents"]] == [first.json()["preferred"]["id"]]


def test_one_tap_refuses_unlisted_and_self(client, agent, agent2, mechanic, operator):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    # Not publicly listed -> refused.
    resp = _one_tap(client, mechanic, matco["id"], agent.id)
    assert resp.status_code == 422
    # No representation at all -> refused.
    _set_profile(client, agent2)
    resp = _one_tap(client, mechanic, matco["id"], agent2.id)
    assert resp.status_code == 422
    # Self -> refused.
    _set_profile(client, agent)
    resp = _one_tap(client, agent, matco["id"], agent.id)
    assert resp.status_code == 422


def test_dealer_stats_counts_only(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    snapon = _directory_company(client, operator, "Snap-on")
    _represent(client, agent, matco["id"])
    _represent(client, agent, snapon["id"])
    _set_profile(client, agent)

    stats = client.get("/api/dealers/stats", headers=auth_headers(agent)).json()
    assert stats == {
        "preferred_by_count": 0,
        "companies_represented_count": 2,
        "profile_visibility": "Public",
    }

    _one_tap(client, mechanic, matco["id"], agent.id)
    stats = client.get("/api/dealers/stats", headers=auth_headers(agent)).json()
    assert stats["preferred_by_count"] == 1
    # Aggregate ONLY: the payload has no key that could carry an
    # identity (no list, no names, no account numbers).
    assert set(stats.keys()) == {
        "preferred_by_count",
        "companies_represented_count",
        "profile_visibility",
    }
    assert "mech@example.com" not in str(stats)
    assert "TV-M-000501" not in str(stats)

    # Removing the preference drops the count.
    pref = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    client.delete(f"/api/dealers/preferred/{pref[0]['id']}", headers=auth_headers(mechanic))
    stats = client.get("/api/dealers/stats", headers=auth_headers(agent)).json()
    assert stats["preferred_by_count"] == 0

    _set_profile(client, agent, publicly_listed=False)
    stats = client.get("/api/dealers/stats", headers=auth_headers(agent)).json()
    assert stats["profile_visibility"] == "Private"


# -- private -> platform switch ---------------------------------------------------


def _private_agent_with_preference(client, user, company_id, name="Truck Guy"):
    agent = client.post(
        "/api/dealers/agents/private",
        json={"name": name, "company_id": company_id, "phone": "555-9", "email": "", "notes": ""},
        headers=auth_headers(user),
    )
    assert agent.status_code == 201, agent.text
    agent = agent.json()
    pref = client.post(
        "/api/dealers/preferred",
        json={"company_id": company_id, "private_agent_id": agent["id"]},
        headers=auth_headers(user),
    )
    assert pref.status_code == 201, pref.text
    return agent, pref.json()


def test_switch_repoints_preferences_and_archives(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    private, pref = _private_agent_with_preference(client, mechanic, matco["id"])

    linked = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["archived"] is True
    assert linked.json()["linked_account_number"] == "TV-D-000501"

    # The preference now points at the platform account.
    mine = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    assert len(mine) == 1
    assert mine[0]["id"] == pref["id"]  # same row, re-pointed
    assert mine[0]["kind"] == "platform"
    assert mine[0]["agent_user_id"] == str(agent.id)
    assert mine[0]["private_agent_id"] is None

    # Unlink restores the record AND the row's private pointing.
    restored = client.post(
        f"/api/dealers/agents/private/{private['id']}/unlink",
        headers=auth_headers(mechanic),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived"] is False
    assert restored.json()["linked_account_number"] is None
    mine = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    assert len(mine) == 1
    assert mine[0]["kind"] == "private"
    assert mine[0]["private_agent_id"] == private["id"]


def test_switch_conflict_round_trip_is_lossless(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    private, _pref = _private_agent_with_preference(client, mechanic, matco["id"])
    # The platform agent is ALSO already preferred for this company
    # (added by account number — the pre-existing door).
    platform_pref = client.post(
        "/api/dealers/preferred",
        json={"company_id": matco["id"], "agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    assert platform_pref.status_code == 201, platform_pref.text
    assert len(client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()) == 2

    linked = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    assert linked.status_code == 200, linked.text
    # After the switch: ONE row (the duplicate was absorbed).
    mine = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    assert len(mine) == 1
    assert mine[0]["kind"] == "platform"

    # Unlink recreates the absorbed private row: back to two.
    client.post(
        f"/api/dealers/agents/private/{private['id']}/unlink",
        headers=auth_headers(mechanic),
    )
    mine = client.get("/api/dealers/preferred", headers=auth_headers(mechanic)).json()
    assert len(mine) == 2
    kinds = sorted(p["kind"] for p in mine)
    assert kinds == ["platform", "private"]


def test_switch_error_paths(client, db, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    private, _ = _private_agent_with_preference(client, mechanic, matco["id"])
    stranger = _make_user(db, "TV-M-000509", "stranger@example.com", (MECHANIC,))

    # Unknown account number.
    resp = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": "TV-D-999999"},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    # Link to myself.
    resp = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": mechanic.account_number},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    # Someone else's record: 404, never 403 (existence doesn't leak).
    resp = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404
    # Unlink a record that isn't linked.
    resp = client.post(
        f"/api/dealers/agents/private/{private['id']}/unlink",
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    # Double link refused.
    client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    resp = client.post(
        f"/api/dealers/agents/private/{private['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422


# -- module removability ----------------------------------------------------------


def test_portal_routes_403_when_module_off(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    headers = auth_headers(operator)
    off = client.put(
        "/api/admin/modules/dealers/global",
        json={"enabled": False},
        headers=headers,
    )
    assert off.status_code == 200, off.text
    try:
        for path in (
            "/api/dealers/profile/me",
            "/api/dealers/stats",
            f"/api/dealers/companies/{matco['id']}/detail",
            "/api/dealers/profile/me/representations",
        ):
            resp = client.get(path, headers=auth_headers(mechanic))
            assert resp.status_code == 403, path
            assert resp.json()["detail"]["code"] == "module_unavailable", path
    finally:
        client.put(
            "/api/admin/modules/dealers/global",
            json={"enabled": True},
            headers=headers,
        )
    # Back on: the portal answers again.
    assert (
        client.get("/api/dealers/profile/me", headers=auth_headers(agent)).status_code
        == 200
    )
