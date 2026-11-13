"""Repairs ∪ claims merge (owner model, 2026-11-03; built 2026-11-04).

Ryan's ruling: "The thought process behind a repair is the same
thing as a warranty claim. Even if it's outside of warranty and
the user has to pay to get it repaired, it still goes through a
warranty claim." These tests pin the merged pipeline:

  - the warranty claim absorbs the repair record's working end:
    send-for-repair (repair_sent_to rides the move to in_repair),
    mark-fixed (repair_cost + repair_completed_at ride the move
    to completed), and closing the claim KEEPS the cost;
  - a paid / out-of-warranty repair is the same claim with a
    cost on it — no separate species, no kind gate;
  - repair payloads on an INSURANCE claim are refused;
  - the claim drives the item's standing: filing marks an
    in-service item broken (the claim IS the break report), the
    send flips it to in_repair, completion returns it to
    in_service; closing an OPEN claim changes nothing;
  - set pieces follow the same model through piece claims;
  - the maintenance out-of-service board links the open claim
    that is driving a break;
  - the reports seam (repair_cost_rows) reads the repair facts
    off claims in the old repair-view shape.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.claims import service as claims_service
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


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
    return _make_user(db, "TV-M-000901", "merge-owner@example.com", [MECHANIC], "Meg Merge")


@pytest.fixture()
def dealer_user(db):
    return _make_user(db, "TV-D-000902", "merge-dealer@example.com", [DEALER], "Dee Dealer")


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _warranty(client, user, target_kind, target_id, problem="It stopped working."):
    response = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": target_kind,
            "target_id": str(target_id),
            "dealer_notified": False,
            "problem": problem,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()["claim"]


def _move(client, user, claim_id, to_status, **extra):
    return client.post(
        f"/api/claims/{claim_id}/transition",
        json={"to_status": to_status, **extra},
        headers=auth_headers(user),
    )


def _standing(client, user, kind, item_id):
    response = client.get(
        f"/api/maintenance/items/{kind}/{item_id}", headers=auth_headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- the working end rides the claim ---------------------------------------


def test_send_and_fix_store_the_repair_facts_on_the_claim(client, owner, db):
    tool = _tool(db, owner)
    claim = _warranty(client, owner, "tool", tool.id, problem="Anvil worn")
    assert claim["repair_sent_to"] == ""
    assert claim["repair_cost"] is None
    assert claim["repair_completed_at"] is None

    moved = _move(client, owner, claim["id"], "reported")
    assert moved.status_code == 200, moved.text

    sent = _move(
        client, owner, claim["id"], "in_repair",
        repair_sent_to="Snap-on warranty center",
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "in_repair"
    assert sent.json()["repair_sent_to"] == "Snap-on warranty center"

    fixed = _move(
        client, owner, claim["id"], "completed", repair_cost="85.50"
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["status"] == "completed"
    assert fixed.json()["repair_cost"] == "85.50"
    assert fixed.json()["repair_completed_at"] is not None

    # Closing keeps the cost (the retired RepairsPanel semantics).
    closed = _move(client, owner, claim["id"], "closed")
    assert closed.status_code == 200, closed.text
    assert closed.json()["repair_cost"] == "85.50"
    assert closed.json()["repair_sent_to"] == "Snap-on warranty center"
    assert closed.json()["repair_completed_at"] is not None


def test_paid_repair_is_the_same_claim_with_a_cost(client, owner, db):
    # No dealer, no warranty coverage involved at all: the owner
    # pays out of pocket and it still runs through the claim.
    tool = _tool(db, owner)
    claim = _warranty(client, owner, "tool", tool.id, problem="Bent shaft")
    _move(client, owner, claim["id"], "reported")
    _move(client, owner, claim["id"], "in_repair", repair_sent_to="Local machine shop")
    fixed = _move(client, owner, claim["id"], "completed", repair_cost="210.00")
    assert fixed.json()["repair_cost"] == "210.00"

    rows = claims_service.repair_cost_rows(db, owner.id)
    (row,) = [r for r in rows if str(r["id"]) == claim["id"]]
    assert row["item_name"] == "Impact wrench"
    assert row["problem"] == "Bent shaft"
    assert row["sent_to"] == "Local machine shop"
    assert row["repair_cost"] == Decimal("210.00")
    assert row["status"] == "completed"
    assert row["completed_at"] is not None


def _move_disaster(client, user, claim_id, to_status, **extra):
    # Separation (2026-11-04): insurance claims move through the
    # Disaster Claims section's transition door, which passes the
    # repair fields through so the service can refuse them.
    return client.post(
        f"/api/disaster-claims/{claim_id}/transition",
        json={"to_status": to_status, **extra},
        headers=auth_headers(user),
    )


def test_repair_payload_refused_on_an_insurance_claim(client, owner, db):
    tool = _tool(db, owner)
    created = client.post(
        "/api/disaster-claims",
        json={"insurer_name": "Acme Mutual", "incident_type": "damage"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    claim = created.json()
    client.post(
        f"/api/disaster-claims/{claim['id']}/lines",
        json={"target_kind": "tool", "target_id": str(tool.id)},
        headers=auth_headers(owner),
    )
    filed = _move_disaster(client, owner, claim["id"], "filed")
    assert filed.status_code == 200, filed.text
    refused = _move_disaster(
        client, owner, claim["id"], "in_review", repair_sent_to="Some shop"
    )
    assert refused.status_code == 422, refused.text
    refused = _move_disaster(
        client, owner, claim["id"], "in_review", repair_cost="10.00"
    )
    assert refused.status_code == 422, refused.text


# -- the claim drives the standing ------------------------------------------


def test_claim_lifecycle_drives_the_item_standing(client, owner, db):
    tool = _tool(db, owner)
    assert _standing(client, owner, "tool", tool.id)["state"] == "in_service"

    # Filing IS the break report: an in-service item the claim
    # opens on reads broken, with the claim's problem text.
    claim = _warranty(client, owner, "tool", tool.id, problem="Trigger dead")
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "broken"
    assert standing["problem"] == "Trigger dead"

    _move(client, owner, claim["id"], "reported")
    _move(client, owner, claim["id"], "in_repair", repair_sent_to="Depot")
    assert _standing(client, owner, "tool", tool.id)["state"] == "in_repair"

    _move(client, owner, claim["id"], "completed", repair_cost="30.00")
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "in_service"
    assert standing["problem"] == ""


def test_claim_on_already_broken_item_keeps_the_owners_problem(client, owner, db):
    tool = _tool(db, owner)
    marked = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": "tool", "id": str(tool.id)}],
            "action": "set_standing",
            "params": {"standing": "broken"},
        },
        headers=auth_headers(owner),
    )
    assert marked.status_code == 200, marked.text
    record = db.get(inventory_models.Tool, tool.id)
    record.repair_problem = "Owner's own words"
    db.commit()

    _warranty(client, owner, "tool", tool.id, problem="Claim text")
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "broken"
    assert standing["problem"] == "Owner's own words"


def test_closing_an_open_claim_leaves_the_standing(client, owner, db):
    tool = _tool(db, owner)
    claim = _warranty(client, owner, "tool", tool.id)
    assert _standing(client, owner, "tool", tool.id)["state"] == "broken"
    # Giving up on the claim doesn't un-break the item.
    closed = _move(client, owner, claim["id"], "closed")
    assert closed.status_code in (200, 422), closed.text
    if closed.status_code == 422:
        # not_reported closes directly; a reported one does too —
        # either way the standing assertion below is the pin.
        _move(client, owner, claim["id"], "reported")
        closed = _move(client, owner, claim["id"], "closed")
        assert closed.status_code == 200, closed.text
    assert _standing(client, owner, "tool", tool.id)["state"] == "broken"


# -- pieces follow the same model --------------------------------------------


def test_piece_claim_drives_the_piece_standing(client, owner, db):
    tool = _tool(db, owner, name="Socket set", is_set=True)
    piece = inventory_models.SetPiece(
        owner_id=owner.id, set_id=tool.id, kind="core",
        name="13mm socket", part_number="S1313",
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)

    claim = _warranty(client, owner, "piece", piece.id, problem="Cracked wall")
    standing = _standing(client, owner, "tool", tool.id)
    assert standing["state"] == "in_service"  # the set itself never went down
    (piece_view,) = standing["pieces"]
    assert piece_view["state"] == "broken"
    assert piece_view["problem"] == "Cracked wall"

    _move(client, owner, claim["id"], "reported")
    _move(client, owner, claim["id"], "in_repair", repair_sent_to="Tool depot")
    (piece_view,) = _standing(client, owner, "tool", tool.id)["pieces"]
    assert piece_view["state"] == "in_repair"

    _move(client, owner, claim["id"], "completed", repair_cost="0.00")
    (piece_view,) = _standing(client, owner, "tool", tool.id)["pieces"]
    assert piece_view["state"] == "in_service"
    assert piece_view["problem"] == ""


# -- the maintenance board links the driving claim ----------------------------


def test_out_of_service_board_links_the_open_claim(client, owner, db):
    tool = _tool(db, owner)
    claim = _warranty(client, owner, "tool", tool.id, problem="Board problem")
    overview = client.get(
        "/api/maintenance/overview", headers=auth_headers(owner)
    ).json()
    (entry,) = overview["out_of_service"]
    assert entry["item_name"] == "Impact wrench"
    assert entry["state"] == "broken"
    assert entry["problem"] == "Board problem"
    assert entry["claim_id"] == claim["id"]
    assert entry["claim_number"] == claim["claim_number"]
    assert entry["since"] is not None


# -- the agent seat moves carry the facts too ---------------------------------


def test_agent_send_stores_sent_to_and_flips_standing(
    client, owner, dealer_user, db
):
    company = dealer_models.DealerCompany(
        id=uuid.uuid4(), name="Matco Tools", is_directory=True,
        email="warranty@matco.example",
    )
    db.add(company)
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(), company_id=company.id,
            agent_user_id=dealer_user.id, verified=True,
        )
    )
    db.add(
        dealer_models.PreferredAgent(
            user_id=owner.id, company_id=company.id,
            agent_user_id=dealer_user.id,
        )
    )
    db.commit()
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": True,
            "problem": "Ratchet slips",
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    assert claim["status"] == "reported"

    sent = _move(
        client, dealer_user, claim["id"], "in_repair",
        repair_sent_to="Matco warranty depot",
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["repair_sent_to"] == "Matco warranty depot"
    assert sent.json()["viewer_role"] == "dealer"
    assert _standing(client, owner, "tool", tool.id)["state"] == "in_repair"

    fixed = _move(
        client, dealer_user, claim["id"], "completed", repair_cost="0.00"
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["repair_completed_at"] is not None
    assert _standing(client, owner, "tool", tool.id)["state"] == "in_service"

    # The facts are the owner's to read back on their own claim.
    mine = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    assert mine["repair_sent_to"] == "Matco warranty depot"
    assert mine["repair_cost"] == "0.00"


def test_repair_cost_rows_carry_the_converted_claim_shape(db, owner):
    # The migration's converted claims (status/cost/dates carried
    # from the retired records) read through the reports seam in
    # the old repair-view shape.
    from app.modules.claims import models as claim_models

    converted = claim_models.Claim(
        owner_id=owner.id, claim_number="CL-2026-001",
        claim_year=2026, number_seq=1, kind="warranty_repair",
        status="completed", description="Smoke break",
        repair_sent_to="Smoke Dealer",
        repair_cost=Decimal("42.50"),
    )
    db.add(converted)
    db.flush()
    db.add(
        claim_models.ClaimLine(
            owner_id=owner.id, claim_id=converted.id,
            target_kind="tool", target_id=uuid.uuid4(),
            target_name="History Story Wrench", value_basis="entered",
        )
    )
    # A costless claim never appears in the cost rows.
    db.add(
        claim_models.Claim(
            owner_id=owner.id, claim_number="CL-2026-002",
            claim_year=2026, number_seq=2, kind="warranty_repair",
            status="reported", description="No cost yet",
        )
    )
    db.commit()
    rows = claims_service.repair_cost_rows(db, owner.id)
    (row,) = rows
    assert row["item_name"] == "History Story Wrench"
    assert row["problem"] == "Smoke break"
    assert row["sent_to"] == "Smoke Dealer"
    assert row["repair_cost"] == Decimal("42.50")
    assert row["status"] == "completed"
