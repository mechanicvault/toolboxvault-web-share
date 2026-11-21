"""Claims separation (owner order 2026-11-04 22:35 CST; name
decided by Ryan the same night: "Disaster Claims").

Warranty/repair claims and disaster (insurance) claims are two
completely separate sections with two modules, two APIs, and two
number ledgers over ONE kind-scoped claims table. These tests pin
the separation itself — the behavior of each kind lives in
test_claims.py / test_claims_two_types.py:

  - each section's list and stats carry ONLY its own kind;
  - a claim addressed through the OTHER section's routes is a
    404 on every verb (the site's foreign-object discipline),
    and the claim survives untouched in its own section;
  - numbering: disaster claims mint DC-<year>-<seq> from their
    own per-owner sequence; warranty CL- numbering is untouched
    and independent (the same owner can hold CL-…-001 AND
    DC-…-001);
  - the disaster module gates ONLY the disaster section — its
    global kill switch and the per-user switch both leave the
    Claims section standing;
  - global search splits: the claims group is warranty-only,
    the disaster_claims group insurance-only, each linking into
    its own section;
  - the service seams: claims_for_item is warranty-only (the
    item page's Claims panel), while claims_for_dealer carries
    BOTH kinds — the dealer page is a factual record surface
    (the dealers API's my-records block), not a claims-section
    surface, and the confirmed two-types model puts every claim
    whose lines resolve to the company on the dealer's page in
    full; each ref names its kind so the page links the row
    into the claim's OWN section.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.claims import models as claims_models
from app.modules.claims import service as claims_service
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, account_types, name="Test User"):
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
    return _make_user(
        db, "TV-M-000701", "separation@example.com", [MECHANIC], "Sue Separation"
    )


@pytest.fixture(autouse=True)
def _pref_table(db):
    # The per-user switch test writes pref rows; the table exists
    # suite-wide in production (migration) — make sure of it here.
    core_models.UserModulePref.__table__.create(
        bind=db.get_bind(), checkfirst=True
    )


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _warranty(client, user, tool, problem="Motor burned out"):
    response = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": problem,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()["claim"]


def _disaster(client, user, **fields):
    response = client.post(
        "/api/disaster-claims", json=fields, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _disaster_with_line(client, user, tool):
    claim = _disaster(client, user)
    response = client.post(
        f"/api/disaster-claims/{claim['id']}/lines",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "value_basis": "entered",
            "amount": "10.00",
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return claim, response.json()


# -- list + stats separation -------------------------------------------------------


def test_lists_and_stats_carry_only_their_own_kind(client, db, owner):
    tool = _tool(db, owner)
    warranty = _warranty(client, owner, tool)
    disaster_a, _line = _disaster_with_line(client, owner, tool)
    disaster_b = _disaster(client, owner)

    warranty_rows = client.get("/api/claims", headers=auth_headers(owner)).json()
    assert [row["id"] for row in warranty_rows] == [warranty["id"]]
    assert warranty_rows[0]["kind"] == claims_models.KIND_WARRANTY

    disaster_rows = client.get(
        "/api/disaster-claims", headers=auth_headers(owner)
    ).json()
    assert {row["id"] for row in disaster_rows} == {disaster_a["id"], disaster_b["id"]}
    assert all(
        row["kind"] == claims_models.KIND_INSURANCE for row in disaster_rows
    )

    warranty_stats = client.get(
        "/api/claims/stats", headers=auth_headers(owner)
    ).json()
    disaster_stats = client.get(
        "/api/disaster-claims/stats", headers=auth_headers(owner)
    ).json()
    assert warranty_stats["open_claims_count"] == 1
    assert disaster_stats["open_claims_count"] == 2


# -- numbering ---------------------------------------------------------------------


def test_numbering_sequences_are_independent(client, db, owner):
    year = datetime.now(timezone.utc).year
    tool = _tool(db, owner)

    warranty = _warranty(client, owner, tool)
    assert warranty["claim_number"] == f"CL-{year}-001"

    disaster = _disaster(client, owner)
    assert disaster["claim_number"] == f"DC-{year}-001"

    second_disaster = _disaster(client, owner)
    assert second_disaster["claim_number"] == f"DC-{year}-002"

    second_tool = _tool(db, owner, "Second wrench")
    second_warranty = _warranty(client, owner, second_tool)
    assert second_warranty["claim_number"] == f"CL-{year}-002"


# -- cross-kind 404s -----------------------------------------------------------------


def test_cross_kind_routes_404_and_claims_survive(client, db, owner):
    tool = _tool(db, owner)
    warranty = _warranty(client, owner, tool)
    disaster, line = _disaster_with_line(client, owner, tool)
    headers = auth_headers(owner)
    wid, did = warranty["id"], disaster["id"]

    # Reads.
    assert client.get(f"/api/claims/{did}", headers=headers).status_code == 404
    assert client.get(f"/api/disaster-claims/{wid}", headers=headers).status_code == 404
    # Updates.
    assert client.patch(
        f"/api/claims/{did}", json={"insurer_name": "Nope"}, headers=headers
    ).status_code == 404
    assert client.patch(
        f"/api/disaster-claims/{wid}", json={"description": "Nope"}, headers=headers
    ).status_code == 404
    # Transitions (each kind's own first legal move, wrong door).
    assert client.post(
        f"/api/claims/{did}", json={}, headers=headers
    ).status_code in (404, 405)  # no bare create exists on claims anymore
    assert client.post(
        f"/api/claims/{did}/transition",
        json={"to_status": "filed"},
        headers=headers,
    ).status_code == 404
    assert client.post(
        f"/api/disaster-claims/{wid}/transition",
        json={"to_status": "reported"},
        headers=headers,
    ).status_code == 404
    # Archive both ways.
    assert client.post(
        f"/api/claims/{did}/archive", json={"archived": True}, headers=headers
    ).status_code == 404
    assert client.post(
        f"/api/disaster-claims/{wid}/archive",
        json={"archived": True},
        headers=headers,
    ).status_code == 404
    # Disaster-only verbs addressed at a warranty claim.
    assert client.post(
        f"/api/disaster-claims/{wid}/duplicate", json={}, headers=headers
    ).status_code == 404
    assert client.post(
        f"/api/disaster-claims/{wid}/proof-of-loss-sent",
        json={},
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"/api/disaster-claims/{wid}/package", headers=headers
    ).status_code == 404
    # Lines through the wrong door.
    assert client.post(
        f"/api/disaster-claims/{wid}/lines",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "value_basis": "entered",
            "amount": "1.00",
        },
        headers=headers,
    ).status_code == 404
    assert client.delete(
        f"/api/disaster-claims/{wid}/lines/{line['id']}", headers=headers
    ).status_code == 404
    assert client.patch(
        f"/api/disaster-claims/{wid}/lines/{line['id']}/package",
        json={"include_in_package": False},
        headers=headers,
    ).status_code == 404
    # Evidence + communications through the wrong door, both ways.
    assert client.post(
        f"/api/claims/{did}/evidence/upload-url",
        json={"kind": "photo", "filename": "x.jpg", "content_type": "image/jpeg"},
        headers=headers,
    ).status_code == 404
    assert client.post(
        f"/api/disaster-claims/{wid}/evidence/upload-url",
        json={"kind": "photo", "filename": "x.jpg", "content_type": "image/jpeg"},
        headers=headers,
    ).status_code == 404
    assert client.post(
        f"/api/claims/{did}/communications",
        json={"channel": "phone", "summary": "called"},
        headers=headers,
    ).status_code == 404
    assert client.post(
        f"/api/disaster-claims/{wid}/communications",
        json={"channel": "phone", "summary": "called"},
        headers=headers,
    ).status_code == 404
    # Deletes through the wrong door — refused, and nothing dies.
    assert client.delete(f"/api/claims/{did}", headers=headers).status_code == 404
    assert client.delete(
        f"/api/disaster-claims/{wid}", headers=headers
    ).status_code == 404

    # Both claims are still whole in their OWN sections.
    assert client.get(f"/api/claims/{wid}", headers=headers).status_code == 200
    detail = client.get(f"/api/disaster-claims/{did}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["lines"]) == 1
    # And the disaster package renders for its own kind.
    package = client.get(f"/api/disaster-claims/{did}/package", headers=headers)
    assert package.status_code == 200
    assert package.headers["content-type"] == "application/pdf"


# -- module gating -------------------------------------------------------------------


def test_disaster_module_kill_switch_leaves_claims_up(client, db, owner):
    headers = auth_headers(owner)
    assert client.get("/api/disaster-claims", headers=headers).status_code == 200

    db.add(
        core_models.ModuleState(
            module_id="disaster_claims", globally_enabled=False
        )
    )
    db.commit()
    assert client.get("/api/disaster-claims", headers=headers).status_code == 403
    assert client.get(
        "/api/disaster-claims/stats", headers=headers
    ).status_code == 403
    # The warranty section never noticed.
    assert client.get("/api/claims", headers=headers).status_code == 200
    assert client.get("/api/claims/stats", headers=headers).status_code == 200

    # Switch it back: the disaster section returns exactly.
    row = db.get(core_models.ModuleState, "disaster_claims")
    row.globally_enabled = True
    db.commit()
    assert client.get("/api/disaster-claims", headers=headers).status_code == 200


def test_user_pref_toggle_hides_disaster_only(client, db, owner):
    headers = auth_headers(owner)
    response = client.put(
        "/api/core/my-modules/disaster_claims",
        json={"enabled": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert client.get("/api/disaster-claims", headers=headers).status_code == 403
    assert client.get("/api/claims", headers=headers).status_code == 200
    module_ids = {
        m["id"]
        for m in client.get("/api/core/my-modules", headers=headers).json()
    }
    assert "disaster_claims" not in module_ids
    assert "claims" in module_ids

    response = client.put(
        "/api/core/my-modules/disaster_claims",
        json={"enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/disaster-claims", headers=headers).status_code == 200


# -- search split ----------------------------------------------------------------------


def test_search_groups_split_by_kind(client, db, owner):
    tool = _tool(db, owner)
    warranty = _warranty(client, owner, tool, problem="quixotic motor failure")
    disaster = _disaster(client, owner)
    response = client.patch(
        f"/api/disaster-claims/{disaster['id']}",
        json={"description": "quixotic flood loss"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text

    payload = client.get(
        "/api/core/search",
        params={"q": "quixotic"},
        headers=auth_headers(owner),
    ).json()
    groups = {g["key"]: g for g in payload["groups"]}
    assert {r["link"] for r in groups["claims"]["results"]} == {
        f"/claims/{warranty['id']}"
    }
    assert {r["link"] for r in groups["disaster_claims"]["results"]} == {
        f"/disaster-claims/{disaster['id']}"
    }
    assert groups["disaster_claims"]["results"][0]["kind"] == "disaster_claim"


# -- service seams ---------------------------------------------------------------------


def test_item_seam_warranty_only_dealer_seam_all_kinds(client, db, owner):
    matco = dealer_models.DealerCompany(name="Matco", is_directory=True)
    db.add(matco)
    db.commit()
    db.refresh(matco)
    tool = _tool(db, owner, dealer_company_id=matco.id)
    warranty = _warranty(client, owner, tool)
    disaster, _line = _disaster_with_line(client, owner, tool)

    # The item page's claims endpoint: warranty only, by API…
    body = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    ids = [row["id"] for row in body["current"] + body["history"]]
    assert ids == [warranty["id"]]

    # …and by the service seam behind it (raw UUIDs at this layer).
    split = claims_service.claims_for_item(db, owner, "tool", tool.id)
    ids = [str(row["id"]) for row in split["current"] + split["history"]]
    assert ids == [warranty["id"]]

    # The DEALER seam is the recorded exception: the dealer page
    # is a factual record surface, so both kinds appear there —
    # each ref naming its kind for the kind-aware link.
    dealer_split = claims_service.claims_for_dealer(db, owner, matco.id)
    refs = {
        str(row["id"]): row
        for row in dealer_split["current"] + dealer_split["history"]
    }
    assert set(refs) == {warranty["id"], disaster["id"]}
    assert refs[warranty["id"]]["kind"] == claims_models.KIND_WARRANTY
    assert refs[disaster["id"]]["kind"] == claims_models.KIND_INSURANCE
