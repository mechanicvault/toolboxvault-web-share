"""Peer sharing (owner directive 2026-10-17): a person shares their
tool LIST with specific people — crew-mates who can browse it and
search "who has this tool?".

These tests pin: nothing visible before acceptance; decline /
revoke / leave cut access immediately; exclusions hide items from
list AND search; the payload is a fixed whitelist (no pricing,
notes, serials, documents, custom data — asserted by exact key set);
search matches only payload fields (a notes-only term finds
nothing); email invites never reveal whether the address has an
account and attach when that email signs up; peer items never leak
into the viewer's own inventory, stats, or tier-sharing surfaces.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"

PAYLOAD_KEYS = {
    "id",
    "name",
    "brand",
    "model",
    "category",
    # Package B (Ryan-directed): condition left the peer whitelist —
    # this exact key set is the privacy pin.
    "photos",
    "owner",
}


@pytest.fixture(autouse=True)
def _peer_tables(db):
    # Same pattern as test_sharing.py: the peer tables are created
    # here so the shared conftest fixture list stays put. The tier
    # tables come along because one test reads the tier overview to
    # prove the two systems stay independent. The notifications
    # table too: the peer lifecycle generates inbox rows (inbox.py),
    # so every flow here writes to it.
    bind = db.get_bind()
    core_models.PeerShare.__table__.create(bind=bind, checkfirst=True)
    core_models.PeerShareExclusion.__table__.create(bind=bind, checkfirst=True)
    core_models.ShareConfig.__table__.create(bind=bind, checkfirst=True)
    core_models.SharedItem.__table__.create(bind=bind, checkfirst=True)
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)


def _make_user(db, account_number: str, email: str, account_types: list[str], name="Peer User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000101", "owner@example.com", [MECHANIC], "Olive Owner")


@pytest.fixture()
def viewer(db):
    return _make_user(db, "TV-M-000102", "viewer@example.com", [MECHANIC], "Vic Viewer")


@pytest.fixture()
def second_owner(db):
    return _make_user(db, "TV-S-000103", "shop@example.com", [SHOP, MECHANIC], "Sue Shop")


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


def _photo_tool(db, owner) -> inventory_models.Tool:
    tool = _make_tool(
        db,
        owner,
        category="Power tools",
        condition="Good",
        notes="apple rattles in the case",  # notes-only term: "apple"
        purchase_price="450.00",
    )
    tool.attachments = [
        {
            "key": f"{owner.id}/tools/{tool.id}/photo/front.jpg",
            "filename": "front.jpg",
            "kind": "photo",
            "content_type": "image/jpeg",
            "size_bytes": 100,
            "uploaded_at": None,
        },
        {
            "key": f"{owner.id}/tools/{tool.id}/document/manual.pdf",
            "filename": "manual.pdf",
            "kind": "document",
            "content_type": "application/pdf",
            "size_bytes": 200,
            "uploaded_at": None,
        },
    ]
    db.commit()
    db.refresh(tool)
    return tool


def _invite(client, owner, **kwargs):
    response = client.post(
        "/api/core/sharing/peer/invite",
        json=kwargs,
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _invite_and_accept(client, owner, viewer):
    grant = _invite(client, owner, account_number=viewer.account_number)
    accepted = client.post(
        f"/api/core/sharing/peer/{grant['id']}/accept",
        headers=auth_headers(viewer),
    )
    assert accepted.status_code == 204, accepted.text
    return grant


# -- auth + owner gating -------------------------------------------------------


def test_peer_endpoints_require_auth(client, owner):
    assert client.get("/api/core/sharing/peer").status_code == 401
    assert client.get("/api/core/sharing/peer/search?q=x").status_code == 401
    assert (
        client.get(f"/api/core/sharing/peer/lists/{owner.id}").status_code == 401
    )
    assert (
        client.post(
            "/api/core/sharing/peer/invite", json={"email": "x@example.com"}
        ).status_code
        == 401
    )
    assert (
        client.put(
            "/api/core/sharing/peer/exclusions", json={"tool_ids": []}
        ).status_code
        == 401
    )


@pytest.mark.parametrize("types", [[DEALER], [INSURANCE], []])
def test_only_tool_groups_can_invite(client, db, types):
    user = _make_user(db, "TV-X-000109", f"gate-{types}@example.com", types)
    response = client.post(
        "/api/core/sharing/peer/invite",
        json={"email": "crew@example.com"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    response = client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": []},
        headers=auth_headers(user),
    )
    assert response.status_code == 403


def test_shop_owner_can_invite(client, second_owner, viewer):
    grant = _invite(client, second_owner, account_number=viewer.account_number)
    assert grant["status"] == "pending"


# -- invite flow -----------------------------------------------------------------


def test_invite_by_account_number_is_pending_until_accepted(client, owner, viewer):
    grant = _invite(client, owner, account_number=viewer.account_number.lower())
    assert grant["status"] == "pending"
    # Account-number invite: the owner named the account, identity shown.
    assert grant["viewer"]["account_number"] == viewer.account_number
    assert grant["invited_email"] is None

    # The viewer sees the pending invite with the owner's identity.
    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(viewer)
    ).json()
    assert len(overview["pending_for_me"]) == 1
    assert overview["pending_for_me"][0]["owner"]["name"] == "Olive Owner"
    assert overview["pending_for_me"][0]["owner"]["account_number"] == "TV-M-000101"
    assert overview["shared_with_me"] == []

    # The owner's side lists it as pending.
    mine = client.get("/api/core/sharing/peer", headers=auth_headers(owner)).json()
    assert [g["status"] for g in mine["sharing_with"]] == ["pending"]


def test_nothing_visible_before_acceptance(client, db, owner, viewer):
    tool = _photo_tool(db, owner)
    _invite(client, owner, account_number=viewer.account_number)

    assert (
        client.get(
            f"/api/core/sharing/peer/lists/{owner.id}",
            headers=auth_headers(viewer),
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/core/sharing/peer/search?q=impact",
            headers=auth_headers(viewer),
        ).json()
        == []
    )
    assert tool.name  # (the tool exists; it is simply not visible)


def test_unknown_account_number_and_self_invite(client, owner):
    missing = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": "TV-M-999999"},
        headers=auth_headers(owner),
    )
    assert missing.status_code == 404
    own = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": owner.account_number},
        headers=auth_headers(owner),
    )
    assert own.status_code == 422
    own_email = client.post(
        "/api/core/sharing/peer/invite",
        json={"email": owner.email},
        headers=auth_headers(owner),
    )
    assert own_email.status_code == 422
    both = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": "TV-M-000102", "email": "v@example.com"},
        headers=auth_headers(owner),
    )
    assert both.status_code == 422
    neither = client.post(
        "/api/core/sharing/peer/invite", json={}, headers=auth_headers(owner)
    )
    assert neither.status_code == 422


def test_invite_is_idempotent(client, owner, viewer):
    first = _invite(client, owner, account_number=viewer.account_number)
    second = _invite(client, owner, account_number=viewer.account_number)
    assert first["id"] == second["id"]
    mine = client.get("/api/core/sharing/peer", headers=auth_headers(owner)).json()
    assert len(mine["sharing_with"]) == 1
    # Inviting by the same person's email also lands on the same grant.
    by_email = _invite(client, owner, email=viewer.email)
    assert by_email["id"] == first["id"]


# -- browse + search after acceptance ---------------------------------------------


def test_browse_list_payload_is_the_fixed_whitelist(client, db, owner, viewer):
    tool = _photo_tool(db, owner)
    _make_tool(db, owner, name="Torque wrench", brand="Tekton")
    _invite_and_accept(client, owner, viewer)

    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=auth_headers(viewer)
    ).json()
    assert body["owner"] == {
        "id": str(owner.id),
        "name": "Olive Owner",
        "account_number": "TV-M-000101",
    }
    assert len(body["items"]) == 2
    item = next(i for i in body["items"] if i["id"] == str(tool.id))
    assert set(item.keys()) == PAYLOAD_KEYS
    assert item["name"] == "Impact wrench"
    assert item["brand"] == "Snap-on"
    assert item["model"] == "CT9075"
    assert item["category"] == "Power tools"
    assert "condition" not in item  # Package B: never shared anymore
    # Photos: exactly the photo attachment's URL — the document never rides.
    assert len(item["photos"]) == 1
    assert "front.jpg" in item["photos"][0]
    assert item["owner"]["account_number"] == "TV-M-000101"
    for forbidden in (
        "serial_number",
        "notes",
        "purchase_price",
        "purchase_date",
        "msrp",
        "replacement_cost",
        "location",
        "documents",
        "custom_data",
        "attachments",
        "owner_id",
    ):
        assert forbidden not in item


def test_search_matches_payload_fields_only(client, db, owner, viewer):
    _photo_tool(db, owner)  # "apple" lives ONLY in its notes
    _invite_and_accept(client, owner, viewer)
    headers = auth_headers(viewer)

    by_name = client.get(
        "/api/core/sharing/peer/search?q=impact", headers=headers
    ).json()
    assert len(by_name) == 1
    assert by_name[0]["owner"]["name"] == "Olive Owner"
    assert set(by_name[0].keys()) == PAYLOAD_KEYS

    by_brand = client.get(
        "/api/core/sharing/peer/search?q=snap-on", headers=headers
    ).json()
    assert len(by_brand) == 1

    # A term that appears only in notes can NEVER surface the tool.
    assert (
        client.get("/api/core/sharing/peer/search?q=apple", headers=headers).json()
        == []
    )
    # Nor can the serial number.
    assert (
        client.get("/api/core/sharing/peer/search?q=SN-123", headers=headers).json()
        == []
    )
    # Deliberate search: empty q returns nothing.
    assert client.get("/api/core/sharing/peer/search?q=", headers=headers).json() == []
    assert client.get("/api/core/sharing/peer/search", headers=headers).json() == []


def test_search_spans_all_owners_who_share_with_me(client, db, owner, viewer, second_owner):
    _make_tool(db, owner, name="Crew drill", brand="DeWalt")
    _make_tool(db, second_owner, name="Shop drill", brand="Milwaukee")
    _invite_and_accept(client, owner, viewer)
    _invite_and_accept(client, second_owner, viewer)

    results = client.get(
        "/api/core/sharing/peer/search?q=drill", headers=auth_headers(viewer)
    ).json()
    assert len(results) == 2
    by_owner = {r["owner"]["account_number"]: r["name"] for r in results}
    assert by_owner == {"TV-M-000101": "Crew drill", "TV-S-000103": "Shop drill"}


# -- ending access: decline / revoke / leave ---------------------------------------


def test_decline_removes_invite_and_allows_reinvite(client, owner, viewer):
    grant = _invite(client, owner, account_number=viewer.account_number)
    declined = client.post(
        f"/api/core/sharing/peer/{grant['id']}/decline",
        headers=auth_headers(viewer),
    )
    assert declined.status_code == 204
    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(viewer)
    ).json()
    assert overview["pending_for_me"] == []
    mine = client.get("/api/core/sharing/peer", headers=auth_headers(owner)).json()
    assert mine["sharing_with"] == []
    # The owner can invite again — decline leaves no residue.
    again = _invite(client, owner, account_number=viewer.account_number)
    assert again["status"] == "pending"


def test_revoke_cuts_access_immediately(client, db, owner, viewer):
    _photo_tool(db, owner)
    grant = _invite_and_accept(client, owner, viewer)
    headers = auth_headers(viewer)
    assert (
        client.get(
            f"/api/core/sharing/peer/lists/{owner.id}", headers=headers
        ).status_code
        == 200
    )
    revoked = client.post(
        f"/api/core/sharing/peer/{grant['id']}/revoke",
        headers=auth_headers(owner),
    )
    assert revoked.status_code == 204
    assert (
        client.get(
            f"/api/core/sharing/peer/lists/{owner.id}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get("/api/core/sharing/peer/search?q=impact", headers=headers).json()
        == []
    )


def test_leave_cuts_access_immediately(client, db, owner, viewer):
    _photo_tool(db, owner)
    grant = _invite_and_accept(client, owner, viewer)
    headers = auth_headers(viewer)
    left = client.post(
        f"/api/core/sharing/peer/{grant['id']}/leave", headers=headers
    )
    assert left.status_code == 204
    assert (
        client.get(
            f"/api/core/sharing/peer/lists/{owner.id}", headers=headers
        ).status_code
        == 404
    )
    mine = client.get("/api/core/sharing/peer", headers=auth_headers(owner)).json()
    assert mine["sharing_with"] == []


def test_actions_are_scoped_to_the_right_person(client, db, owner, viewer, second_owner):
    grant = _invite(client, owner, account_number=viewer.account_number)
    # A third party can't accept, decline, revoke, or leave it.
    stranger = auth_headers(second_owner)
    for action in ("accept", "decline", "revoke", "leave"):
        assert (
            client.post(
                f"/api/core/sharing/peer/{grant['id']}/{action}", headers=stranger
            ).status_code
            == 404
        )
    # The owner can't accept their own invite; the viewer can't revoke it.
    assert (
        client.post(
            f"/api/core/sharing/peer/{grant['id']}/accept",
            headers=auth_headers(owner),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/core/sharing/peer/{grant['id']}/revoke",
            headers=auth_headers(viewer),
        ).status_code
        == 404
    )
    # And the grant still stands for the real viewer.
    assert (
        client.post(
            f"/api/core/sharing/peer/{grant['id']}/accept",
            headers=auth_headers(viewer),
        ).status_code
        == 204
    )


# -- exclusions ---------------------------------------------------------------------


def test_exclusions_hide_items_from_list_and_search(client, db, owner, viewer):
    kept = _make_tool(db, owner, name="Kept wrench")
    hidden = _make_tool(db, owner, name="Hidden wrench")
    _invite_and_accept(client, owner, viewer)
    headers = auth_headers(viewer)

    saved = client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": [str(hidden.id)]},
        headers=auth_headers(owner),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["excluded_tool_ids"] == [str(hidden.id)]

    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=headers
    ).json()
    assert [i["name"] for i in body["items"]] == ["Kept wrench"]
    results = client.get(
        "/api/core/sharing/peer/search?q=wrench", headers=headers
    ).json()
    assert [r["name"] for r in results] == ["Kept wrench"]
    assert kept.id  # silence linter; identity asserted via names above

    # Clearing the exclusions restores the item.
    client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": []},
        headers=auth_headers(owner),
    )
    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}", headers=headers
    ).json()
    assert len(body["items"]) == 2


def test_exclusions_refuse_foreign_tools(client, db, owner, viewer):
    mine = _make_tool(db, owner, name="Mine")
    foreign = _make_tool(db, viewer, name="Foreign")
    client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": [str(mine.id)]},
        headers=auth_headers(owner),
    )
    response = client.put(
        "/api/core/sharing/peer/exclusions",
        json={"tool_ids": [str(mine.id), str(foreign.id)]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    # Nothing partial was applied.
    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(owner)
    ).json()
    assert overview["excluded_tool_ids"] == [str(mine.id)]


# -- email invites -------------------------------------------------------------------


def test_email_invite_to_existing_account(client, owner, viewer):
    grant = _invite(client, owner, email=viewer.email)
    # Same response shape as an account-number invite, and the
    # pending email invite does NOT disclose the account behind it.
    assert grant["invited_email"] == viewer.email
    assert grant["viewer"] is None
    assert grant["status"] == "pending"

    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(viewer)
    ).json()
    assert len(overview["pending_for_me"]) == 1
    accepted = client.post(
        f"/api/core/sharing/peer/{grant['id']}/accept",
        headers=auth_headers(viewer),
    )
    assert accepted.status_code == 204
    # After acceptance the owner sees who accepted.
    mine = client.get("/api/core/sharing/peer", headers=auth_headers(owner)).json()
    assert mine["sharing_with"][0]["viewer"]["account_number"] == "TV-M-000102"


def test_email_invite_response_never_reveals_account_existence(client, owner, viewer):
    existing = _invite(client, owner, email=viewer.email)
    ghost = _invite(client, owner, email="ghost@example.com")
    assert set(existing.keys()) == set(ghost.keys())
    assert existing["viewer"] is None and ghost["viewer"] is None
    assert existing["status"] == ghost["status"] == "pending"


def test_pre_signup_email_invite_attaches_at_signup(client, db, owner, monkeypatch):
    tool = _photo_tool(db, owner)
    grant = _invite(client, owner, email="newtech@example.com")
    assert grant["viewer"] is None

    # The invitee signs up later (through the real service path; the
    # Postgres sequence allocator is stubbed like the rest of the
    # suite — SQLite has no sequences).
    monkeypatch.setattr(
        core_service, "_next_account_number", lambda _db: "TV-000777"
    )
    newcomer = core_service.create_user(
        db, "newtech@example.com", "New Tech", "hunter22", [MECHANIC]
    )
    overview = client.get(
        "/api/core/sharing/peer", headers=auth_headers(newcomer)
    ).json()
    assert len(overview["pending_for_me"]) == 1
    assert overview["pending_for_me"][0]["owner"]["name"] == "Olive Owner"

    accepted = client.post(
        f"/api/core/sharing/peer/{grant['id']}/accept",
        headers=auth_headers(newcomer),
    )
    assert accepted.status_code == 204
    body = client.get(
        f"/api/core/sharing/peer/lists/{owner.id}",
        headers=auth_headers(newcomer),
    ).json()
    assert [i["name"] for i in body["items"]] == [tool.name]


# -- no leakage into the viewer's own surfaces ---------------------------------------


def test_peer_items_never_enter_viewer_surfaces(client, db, owner, viewer):
    _photo_tool(db, owner)
    _invite_and_accept(client, owner, viewer)
    headers = auth_headers(viewer)

    # Own inventory: only the viewer's tools (none) — never the owner's.
    assert client.get("/api/inventory", headers=headers).json() == []
    stats = client.get("/api/inventory/stats", headers=headers).json()
    assert stats["total_items"] == 0

    # Tier-sharing overview (the pickers' data source): the viewer's
    # own items only, so a peer's tools can't be picked for sharing on.
    overview = client.get("/api/core/sharing", headers=headers).json()
    assert overview["items"] == []

    # And tier sharing is independent: the owner's tier config is
    # untouched by the peer grant existing.
    owner_overview = client.get(
        "/api/core/sharing", headers=auth_headers(owner)
    ).json()
    assert all(g["enabled"] is False for g in owner_overview["groups"])
