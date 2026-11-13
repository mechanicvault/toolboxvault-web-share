"""Dealer build (2026-10-20): service-area geometry + the listing
rule, Find-an-Agent (dataset ZIPs, cached geocoding, overlap is
normal), agent-deletion snapshots (both preference paths), and
warranty service requests end to end (eligibility, snapshot
payload, routing, claim race, status flow, notifications,
tombstones, the messaging anchor).

Geocoding never touches the network here: ZIPs resolve from the
bundled centroid dataset, and Nominatim is monkeypatched where a
test needs a city lookup.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.modules.core import models as core_models
from app.modules.dealers import areas as areas_module
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"

# Dataset ground truth (GeoNames): Little Falls, MN 56345.
LF_LAT, LF_LNG = 45.9811, -94.3604
# A polygon drawn around Little Falls — any shape, any size.
LF_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-94.62, 45.80],
            [-94.10, 45.84],
            [-94.14, 46.15],
            [-94.60, 46.10],
            [-94.62, 45.80],
        ]
    ],
}


def _make_user(db, account_number, email, account_types, name="User", **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def agent(db):
    return _make_user(
        db, "TV-D-000601", "agent1@example.com", (DEALER,), name="Andy Agent"
    )


@pytest.fixture()
def agent2(db):
    return _make_user(
        db, "TV-D-000602", "agent2@example.com", (DEALER,), name="Beth Agent"
    )


@pytest.fixture()
def mechanic(db):
    user = _make_user(
        db, "TV-M-000601", "mech1@example.com", (MECHANIC,), name="Mike Mechanic"
    )
    user.contact_phone = "555-777-0100"
    db.commit()
    return user


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000600", "op1@example.com", (MECHANIC,),
        name="Op Erator", is_operator=True,
    )


def _directory_company(client, operator, name="Matco Tools"):
    resp = client.post(
        "/api/admin/dealer-companies",
        json={"name": name, "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _represent(client, user, company_id):
    resp = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": company_id},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _verify(client, operator, rep_id):
    resp = client.put(
        f"/api/admin/dealer-representations/{rep_id}/verify",
        json={"verified": True},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text


def _profile(client, user, **overrides):
    payload = {
        "display_name": "",
        "phone": "555-0100",
        "contact_email": "agent@truck.example",
        "service_area": "Central Minnesota",
        "bio": "",
    }
    payload.update(overrides)
    resp = client.put(
        "/api/dealers/profile/me", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _listed_polygon_agent(client, user, company_id):
    _represent(client, user, company_id)
    _profile(
        client, user,
        area_type="polygon", area_polygon=LF_POLYGON, publicly_listed=True,
    )


def _delete_account(client, user):
    resp = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 204, resp.text


# -- 1. area validation + the listing rule -------------------------------------


def test_listing_refused_without_an_area(client, agent):
    resp = client.put(
        "/api/dealers/profile/me",
        json={"publicly_listed": True},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    assert "service area" in resp.json()["detail"].lower()
    view = client.get(
        "/api/dealers/profile/me", headers=auth_headers(agent)
    ).json()
    assert view["publicly_listed"] is False  # refused save changed nothing


def test_polygon_needs_three_points(client, agent):
    resp = client.put(
        "/api/dealers/profile/me",
        json={
            "area_type": "polygon",
            "area_polygon": {
                "type": "Polygon",
                "coordinates": [[[-94.4, 46.0], [-94.3, 46.0], [-94.4, 46.0]]],
            },
        },
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    resp = client.put(
        "/api/dealers/profile/me",
        json={
            "area_type": "polygon",
            "area_polygon": {
                "type": "Polygon",
                "coordinates": [[[999.0, 46.0], [-94.3, 46.0], [-94.2, 46.1]]],
            },
        },
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422  # off the map


def test_radius_bounds_and_round_trip(client, agent):
    for miles in (0.5, 501):
        resp = client.put(
            "/api/dealers/profile/me",
            json={
                "area_type": "radius", "area_zip": "56345",
                "area_center_lat": LF_LAT, "area_center_lng": LF_LNG,
                "area_radius_miles": miles,
            },
            headers=auth_headers(agent),
        )
        assert resp.status_code == 422, miles
    saved = _profile(
        client, agent,
        area_type="radius", area_zip="56345",
        area_center_lat=LF_LAT, area_center_lng=LF_LNG,
        area_radius_miles=25, publicly_listed=True,
    )
    assert saved["has_area"] is True
    assert saved["area_type"] == "radius"
    assert saved["area_radius_miles"] == 25
    assert saved["publicly_listed"] is True


def test_clearing_area_under_a_live_listing_is_refused(client, agent):
    _profile(
        client, agent,
        area_type="radius", area_zip="56345",
        area_center_lat=LF_LAT, area_center_lng=LF_LNG,
        area_radius_miles=25, publicly_listed=True,
    )
    resp = client.put(
        "/api/dealers/profile/me",
        json={"area_type": None},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 422
    # Unlist + clear in one save works.
    resp = client.put(
        "/api/dealers/profile/me",
        json={"area_type": None, "publicly_listed": False},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 200
    assert resp.json()["has_area"] is False


# -- 2. Find an Agent ------------------------------------------------------------


def test_find_agent_polygon_contains_and_honest_empty(client, agent, mechanic, operator):
    matco = _directory_company(client, operator)
    _listed_polygon_agent(client, agent, matco["id"])

    found = client.get(
        "/api/dealers/find-agent", params={"q": "56345"},
        headers=auth_headers(mechanic),
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["point"]["display_name"].startswith("Little Falls, MN")
    assert [r["display_name"] for r in body["results"]] == ["Andy Agent"]
    card = body["results"][0]
    assert card["phone"] == "555-0100"  # published contact rides along
    assert card["companies"][0]["company_name"] == "Matco Tools"

    far = client.get(
        "/api/dealers/find-agent", params={"q": "90210"},
        headers=auth_headers(mechanic),
    ).json()
    assert far["results"] == []  # honest empty, not an error


def test_find_agent_radius_overlap_and_verified_first(
    client, agent, agent2, mechanic, operator
):
    matco = _directory_company(client, operator)
    _listed_polygon_agent(client, agent, matco["id"])
    rep2 = _represent(client, agent2, matco["id"])
    _profile(
        client, agent2, display_name="Beth Agent",
        area_type="radius", area_zip="56345",
        area_center_lat=LF_LAT, area_center_lng=LF_LNG,
        area_radius_miles=10, publicly_listed=True,
    )
    _verify(client, operator, rep2["id"])

    body = client.get(
        "/api/dealers/find-agent", params={"q": "56345"},
        headers=auth_headers(mechanic),
    ).json()
    # OVERLAP IS NORMAL: both cover the point; verified first.
    assert [r["display_name"] for r in body["results"]] == [
        "Beth Agent", "Andy Agent",
    ]
    assert body["results"][0]["verified"] is True

    other = _directory_company(client, operator, "Snap-on")
    filtered = client.get(
        "/api/dealers/find-agent",
        params={"q": "56345", "company_id": other["id"]},
        headers=auth_headers(mechanic),
    ).json()
    assert filtered["results"] == []  # neither represents Snap-on


def test_find_agent_anonymous_card_has_no_contact_actions(
    client, agent, mechanic, operator
):
    matco = _directory_company(client, operator)
    _listed_polygon_agent(client, agent, matco["id"])
    anon = client.get(
        "/api/dealers/public/find-agent", params={"q": "56345"}
    )
    assert anon.status_code == 200, anon.text
    card = anon.json()["results"][0]
    assert "phone" not in card and "contact_email" not in card
    assert card["display_name"] == "Andy Agent"
    assert card["service_area"] == "Central Minnesota"


def test_geocode_cache_and_unresolvable_place(client, mechanic, monkeypatch):
    calls = {"n": 0}

    def fake_lookup(query):
        calls["n"] += 1
        return (44.9778, -93.2650, "Minneapolis, MN")

    monkeypatch.setattr(areas_module, "_nominatim_lookup", fake_lookup)
    for _ in range(2):
        resp = client.get(
            "/api/dealers/geocode", params={"q": "Minneapolis"},
            headers=auth_headers(mechanic),
        )
        assert resp.status_code == 200
        assert resp.json()["lat"] == 44.9778
    assert calls["n"] == 1  # second answer came from the cache

    monkeypatch.setattr(areas_module, "_nominatim_lookup", lambda q: None)
    resp = client.get(
        "/api/dealers/find-agent", params={"q": "Zxqvville, Nowhere"},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    assert "couldn't find that place" in resp.json()["detail"]


def test_zip_dataset_resolves_without_network(client, mechanic, monkeypatch):
    monkeypatch.setattr(
        areas_module, "_nominatim_lookup",
        lambda q: (_ for _ in ()).throw(AssertionError("network used")),
    )
    resp = client.get(
        "/api/dealers/geocode", params={"q": "56345"},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert abs(body["lat"] - LF_LAT) < 0.01
    assert body["display_name"].startswith("Little Falls, MN")


# -- 3. agent-deletion snapshots ---------------------------------------------------


def _prefer_by_agent(client, user, company_id, agent_user_id):
    resp = client.post(
        "/api/dealers/preferred/by-agent",
        json={"company_id": company_id, "agent_user_id": str(agent_user_id)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_agent_deletion_snapshots_direct_preference(
    client, agent, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    _listed_polygon_agent(client, agent, matco["id"])
    _prefer_by_agent(client, mechanic, matco["id"], agent.id)

    _delete_account(client, agent)

    preferred = client.get(
        "/api/dealers/preferred", headers=auth_headers(mechanic)
    ).json()
    assert len(preferred) == 1
    row = preferred[0]
    assert row["kind"] == "private"  # re-pointed at the snapshot
    assert row["name"] == "Andy Agent"
    assert row["phone"] == "555-0100"
    assert row["email"] == "agent@truck.example"
    assert row["company_name"] == "Matco Tools"
    agents = client.get(
        "/api/dealers/agents/private", headers=auth_headers(mechanic)
    ).json()
    visible = [a for a in agents if not a["archived"]]
    assert len(visible) == 1
    assert visible[0]["notes"].startswith("Agent left the platform")


def test_agent_deletion_snapshots_account_number_preference(
    client, agent, mechanic, operator, db
):
    # Preferred by typed account number; the agent never made a
    # profile. The snapshot still lands — name from the account.
    matco = _directory_company(client, operator)
    resp = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": matco["id"],
            "agent_account_number": agent.account_number,
        },
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 201, resp.text

    _delete_account(client, agent)

    preferred = client.get(
        "/api/dealers/preferred", headers=auth_headers(mechanic)
    ).json()
    assert len(preferred) == 1
    assert preferred[0]["kind"] == "private"
    assert preferred[0]["name"] == "Andy Agent"


def test_agent_deletion_link_switch_path_unarchives_no_snapshot(
    client, agent, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    resp = client.post(
        "/api/dealers/agents/private",
        json={"name": "Andy (my guy)", "company_id": matco["id"],
              "phone": "555-9999", "email": "", "notes": "Tuesday route"},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 201, resp.text
    record = resp.json()
    resp = client.post(
        "/api/dealers/preferred",
        json={"company_id": matco["id"], "private_agent_id": record["id"]},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        f"/api/dealers/agents/private/{record['id']}/link",
        json={"agent_account_number": agent.account_number},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived"] is True

    _delete_account(client, agent)

    agents = client.get(
        "/api/dealers/agents/private", headers=auth_headers(mechanic)
    ).json()
    # Exactly the original record, unarchived — NO snapshot twin.
    assert len(agents) == 1
    assert agents[0]["id"] == record["id"]
    assert agents[0]["archived"] is False
    assert agents[0]["linked_account_number"] is None
    # Its platform preference rows died with the account (existing
    # link-switch behavior, unregressed).
    preferred = client.get(
        "/api/dealers/preferred", headers=auth_headers(mechanic)
    ).json()
    assert preferred == []


# -- 4. warranty service requests ---------------------------------------------------


def _tool(db, owner, **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name="Impact wrench", **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _break(client, user, item_id, problem="Cracked housing"):
    """The merged pipeline (2026-11-04): there is no repair
    record to break anymore — the item's repair IS its warranty
    claim, and the dealer warranty seam hangs off the CLAIM.
    This helper files the claim (which also marks the tool
    broken) and returns the claim view; callers keep calling the
    result `record` — only its id is ever used."""
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(item_id),
            "dealer_notified": False,
            "problem": problem,
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["claim"]


def _warranty_tool(db, mechanic, company_id):
    return _tool(
        db, mechanic,
        brand="Matco", model="MT2769", serial_number="SN-1",
        serial_numbers=["SN-1", "SN-2"],
        purchase_date=date.today() - timedelta(days=30),
        warranty_months=24,
        dealer_company_id=uuid.UUID(str(company_id)),
    )


def _send(client, user, claim_id):
    resp = client.post(
        "/api/dealers/warranty-requests",
        json={"claim_id": str(claim_id)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_warranty_eligibility_reasons(client, agent, mechanic, operator, db):
    matco = _directory_company(client, operator)

    # No company tag at all.
    plain = _tool(db, mechanic)
    record = _break(client, mechanic, plain.id)
    elig = client.get(
        f"/api/dealers/warranty-requests/eligibility/{record['id']}",
        headers=auth_headers(mechanic),
    ).json()
    assert elig["available"] is False and elig["reason"] == "no_company"

    # Company tag, but nobody registered represents it yet.
    tagged = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tagged.id)
    elig = client.get(
        f"/api/dealers/warranty-requests/eligibility/{record['id']}",
        headers=auth_headers(mechanic),
    ).json()
    assert elig["available"] is False and elig["reason"] == "no_agents"
    assert elig["company_name"] == "Matco Tools"

    # Not my record: 404-shaped.
    resp = client.get(
        f"/api/dealers/warranty-requests/eligibility/{record['id']}",
        headers=auth_headers(agent),
    )
    assert resp.status_code == 404


def test_warranty_send_snapshot_routing_and_claim_flow(
    client, agent, agent2, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    _represent(client, agent2, matco["id"])
    # The mechanic prefers agent2 — the send routes to them ONLY.
    client.post(
        "/api/dealers/preferred",
        json={"company_id": matco["id"],
              "agent_account_number": agent2.account_number},
        headers=auth_headers(mechanic),
    )
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)

    elig = client.get(
        f"/api/dealers/warranty-requests/eligibility/{record['id']}",
        headers=auth_headers(mechanic),
    ).json()
    assert elig["available"] is True
    assert elig["has_preferred_agent"] is True
    payload = elig["payload"]
    assert payload["requester_name"] == "Mike Mechanic"
    assert payload["requester_phone"] == "555-777-0100"
    assert payload["requester_email"] == "mech1@example.com"
    assert payload["serials"] == ["SN-1", "SN-2"]
    assert payload["warranty_status"] == "in_warranty"
    assert payload["problem"] == "Cracked housing"

    sent = _send(client, mechanic, record["id"])
    assert sent["status"] == "unclaimed"
    assert [a["display_name"] for a in sent["routed_agents"]] == ["Beth Agent"]

    # Duplicate send refused while one is in flight.
    resp = client.post(
        "/api/dealers/warranty-requests",
        json={"claim_id": record["id"]},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422

    # The un-routed agent's queue is empty; the routed one sees it.
    assert client.get(
        "/api/dealers/warranty-requests/incoming", headers=auth_headers(agent)
    ).json() == []
    queue = client.get(
        "/api/dealers/warranty-requests/incoming", headers=auth_headers(agent2)
    ).json()
    assert [r["id"] for r in queue] == [sent["id"]]

    # An un-routed agent cannot claim (404 — not in their queue).
    resp = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/claim",
        headers=auth_headers(agent),
    )
    assert resp.status_code == 404

    claimed = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/claim",
        headers=auth_headers(agent2),
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "received"
    notes = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == mechanic.id)
        .all()
    )
    assert any(n.kind == "warranty_request_claimed" for n in notes)

    # Status flow, dealer-driven; the requester is told each step.
    moved = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/status",
        json={"status": "in_process"}, headers=auth_headers(agent2),
    )
    assert moved.status_code == 200
    # The requester can't drive the dealer's side.
    resp = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/status",
        json={"status": "resolved"}, headers=auth_headers(mechanic),
    )
    assert resp.status_code == 404
    done = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/status",
        json={"status": "resolved"}, headers=auth_headers(agent2),
    )
    assert done.status_code == 200
    assert done.json()["resolved_at"] is not None
    kinds = [
        n.kind
        for n in db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == mechanic.id)
        .all()
    ]
    assert kinds.count("warranty_request_status") == 2

    # Backwards moves are refused.
    resp = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/status",
        json={"status": "in_process"}, headers=auth_headers(agent2),
    )
    assert resp.status_code == 422


def test_warranty_first_claim_wins(client, agent, agent2, mechanic, operator, db):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    _represent(client, agent2, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    # No preferred, no area info anywhere: everyone is routed.
    sent = _send(client, mechanic, record["id"])
    assert len(sent["routed_agents"]) == 2
    first = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/claim",
        headers=auth_headers(agent),
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/claim",
        headers=auth_headers(agent2),
    )
    assert second.status_code == 422  # taken — first come, first served
    view = client.get(
        f"/api/dealers/warranty-requests/{sent['id']}",
        headers=auth_headers(agent2),
    ).json()
    assert view["claimed_by"]["display_name"] == "Andy Agent"


def test_warranty_routing_uses_coverage_when_no_preferred(
    client, agent, agent2, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    _listed_polygon_agent(client, agent, matco["id"])  # covers 56345
    _represent(client, agent2, matco["id"])
    _profile(  # far-away radius only
        client, agent2, display_name="Beth Agent",
        area_type="radius", area_zip="90210",
        area_center_lat=34.0901, area_center_lng=-118.4065,
        area_radius_miles=10, publicly_listed=True,
    )
    mechanic.public_area_label = "56345"
    db.commit()
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    sent = _send(client, mechanic, record["id"])
    assert [a["display_name"] for a in sent["routed_agents"]] == ["Andy Agent"]


def test_warranty_detail_hidden_from_third_parties(
    client, agent, mechanic, operator, db
):
    third = _make_user(
        db, "TV-M-000699", "third@example.com", (MECHANIC,), name="Third Party"
    )
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    sent = _send(client, mechanic, record["id"])
    resp = client.get(
        f"/api/dealers/warranty-requests/{sent['id']}",
        headers=auth_headers(third),
    )
    assert resp.status_code == 404


def test_warranty_requester_deletion_tombstones(
    client, agent, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    sent = _send(client, mechanic, record["id"])

    _delete_account(client, mechanic)

    queue = client.get(
        "/api/dealers/warranty-requests/incoming", headers=auth_headers(agent)
    ).json()
    assert len(queue) == 1
    view = queue[0]
    assert view["requester_deleted"] is True
    assert view["requester_name"] == "Former member"
    assert view["requester_email"] == "" and view["requester_phone"] == ""
    assert view["item_name"] == "Impact wrench"  # item facts stay


def test_warranty_claimer_deletion_returns_request_to_queue(
    client, agent, agent2, mechanic, operator, db
):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    _represent(client, agent2, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    sent = _send(client, mechanic, record["id"])
    client.post(
        f"/api/dealers/warranty-requests/{sent['id']}/claim",
        headers=auth_headers(agent),
    )

    _delete_account(client, agent)

    view = client.get(
        f"/api/dealers/warranty-requests/{sent['id']}",
        headers=auth_headers(mechanic),
    ).json()
    assert view["status"] == "unclaimed"
    assert view["claimed_by"] is None
    # Re-routed to the remaining representing agent.
    assert [a["user_id"] for a in view["routed_agents"]] == [str(agent2.id)]
    queue = client.get(
        "/api/dealers/warranty-requests/incoming", headers=auth_headers(agent2)
    ).json()
    assert [r["id"] for r in queue] == [sent["id"]]


def test_warranty_messaging_anchor(client, agent, mechanic, operator, db):
    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    sent = _send(client, mechanic, record["id"])

    resp = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(agent.id),
            "body": "About my impact wrench",
            "anchor_type": "warranty_request",
            "anchor_id": sent["id"],
        },
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["anchor_title"] == "Warranty: Impact wrench"

    third = _make_user(
        db, "TV-M-000698", "third2@example.com", (MECHANIC,), name="Out Sider"
    )
    resp = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(agent.id),
            "body": "not my request",
            "anchor_type": "warranty_request",
            "anchor_id": sent["id"],
        },
        headers=auth_headers(third),
    )
    assert resp.status_code == 422


def test_warranty_requester_id_carries_no_fk():
    """The tombstone doctrine, pinned at the schema: requester_id
    is a PLAIN column. An FK to users.id makes a requester's
    account undeletable on Postgres (SQLite tests don't enforce
    FKs — the 2026-10-20 live smoke caught exactly this)."""
    from app.modules.dealers import models as dealers_models

    column = dealers_models.WarrantyServiceRequest.__table__.c.requester_id
    assert column.foreign_keys == set()


def test_export_carries_warranty_summaries(
    client, agent, mechanic, operator, db
):
    import io
    import json
    import zipfile

    from app.modules.core import export as core_export

    matco = _directory_company(client, operator)
    _represent(client, agent, matco["id"])
    tool = _warranty_tool(db, mechanic, matco["id"])
    record = _break(client, mechanic, tool.id)
    _send(client, mechanic, record["id"])

    def dealers_json(user):
        archive = zipfile.ZipFile(
            io.BytesIO(core_export.build_export_zip(db, user))
        )
        return json.loads(archive.read("dealers.json"))

    sent_export = dealers_json(mechanic)
    assert len(sent_export["warranty_requests_sent"]) == 1
    assert sent_export["warranty_requests_sent"][0]["item_name"] == "Impact wrench"
    received_export = dealers_json(agent)
    assert len(received_export["warranty_requests_received"]) == 1
