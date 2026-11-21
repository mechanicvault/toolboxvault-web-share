"""Deep Audit Round 2 — backend fix round 1 pins.

One test class per finding, each pinning the FIXED behavior:

  - D-01 reports: the closing-row count (API totals, hence the
    screen + CSV + XLSX) is the top-level ASSET count in every
    sets mode — identical to summary.items — and grand money is
    unchanged across modes.
  - C-01 inbox: warranty-claim notification kinds are visible
    when the user holds the claims seat OR the dealers seat
    (two-seat rule); a user with neither still doesn't see them,
    and no other kind widens.
  - B-02 warranty create: a second create for the same target
    (tool / battery / set / set piece) is refused with the
    existing already-open shape, and exactly one claim exists.
  - B-03 replace: replacing an already-replaced item refuses
    (422), in both modes, for tools and batteries.
  - C-16 error shapes: ExpansionNotFound is 404 on BOTH
    tool-expansion POSTs; the claims party gate's 403 carries the
    full house {code, module, message} shape.
  - E-02 attach: cross-owner set attach is the non-leaking 404,
    byte-identical for foreign and random ids, nothing attaches.
  - E-03 dealer transition copy: a dealer refused at "completed"
    is NOT told the claim is final — the owner can still close it.
  - D-06 validation handler: a malformed multipart body to a
    JSON attach endpoint is a 422, never a 500, and ordinary
    validation bodies keep their documented shape.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.claims import models as claims_models
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
    return _make_user(db, "TV-M-002001", "r2-owner@example.com", [MECHANIC], "Rae Owner")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-002002", "r2-other@example.com", [MECHANIC], "Otto Other")


@pytest.fixture()
def dealer_user(db):
    return _make_user(db, "TV-D-002003", "r2-dealer@example.com", [DEALER], "Dee Dealer")


@pytest.fixture()
def nobody(db):
    # No account group chosen yet: neither claims nor dealers (nor
    # any other feature module) is effective for this user.
    return _make_user(db, "TV-X-002004", "r2-nobody@example.com", [], "No Groups")


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 pack", **overrides):
    battery = inventory_models.Battery(owner_id=owner.id, name=name, **overrides)
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _warranty(client, user, target_kind, target_id, **kwargs):
    payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "dealer_notified": True,
        "problem": "It stopped working.",
    }
    payload.update(kwargs)
    return client.post("/api/claims/warranty", json=payload, headers=auth_headers(user))


def _replace(client, user, item_kind, item_id, mode="same", **extra):
    payload = {"item_kind": item_kind, "item_id": str(item_id), "mode": mode}
    payload.update(extra)
    return client.post("/api/claims/replace-item", json=payload, headers=auth_headers(user))


def _claim_count(db, owner):
    return len(
        list(
            db.scalars(
                select(claims_models.Claim).where(
                    claims_models.Claim.owner_id == owner.id
                )
            )
        )
    )


# -- D-01: reports closing-row count --------------------------------------------


def _d01_vault(db, owner):
    """Set (200) + priced core piece (12) + priced addon piece (30)
    + folded tool (40) + solo tool (50). Asset count = 2 in every
    mode; grand price = 320.00 in every mode (the core piece's own
    12 never joins a total)."""
    set_tool = _tool(db, owner, name="Socket set", is_set=True,
                     purchase_price=Decimal("200"))
    db.add_all([
        inventory_models.SetPiece(
            set_id=set_tool.id, owner_id=owner.id, kind="core",
            name="10mm socket", part_number="S10", status="present",
            price=Decimal("12"),
        ),
        inventory_models.SetPiece(
            set_id=set_tool.id, owner_id=owner.id, kind="addon",
            name="Extension bar", part_number="EXT1", status="present",
            price=Decimal("30"),
        ),
    ])
    folded = _tool(db, owner, name="Folded driver", purchase_price=Decimal("40"))
    folded.attached_to_set_id = set_tool.id
    _tool(db, owner, name="Solo wrench", purchase_price=Decimal("50"))
    db.commit()
    return set_tool


def test_d01_totals_count_is_asset_count_in_every_mode(client, db, owner):
    _d01_vault(db, owner)
    for mode in ("summary", "with_core", "full"):
        resp = client.post(
            "/api/reports/run",
            json={"columns": ["name", "price_total"], "sets_mode": mode},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200, resp.text
        report = resp.json()
        assert report["summary"]["items"] == 2, mode
        # The closing-row count agrees with the summary — always.
        assert report["totals"]["count"] == 2, mode
        assert report["totals"]["count"] == report["summary"]["items"], mode
        # Money does not move with the count fix.
        assert report["totals"]["price_total"] == "320.00", mode
        assert report["summary"]["price_total"] == "320.00", mode


def test_d01_csv_closing_row_uses_asset_count(client, db, owner):
    _d01_vault(db, owner)
    for mode in ("summary", "with_core", "full"):
        resp = client.post(
            "/api/reports/export/csv",
            json={"columns": ["name", "price_total"], "sets_mode": mode},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200, resp.text
        total_lines = [
            line for line in resp.text.splitlines() if line.startswith("Total (")
        ]
        assert total_lines == ["Total (2 items),320.00"], (mode, resp.text)


# -- C-01: dealer-seat inbox ------------------------------------------------------


def _notify(db, user, kind):
    row = core_models.Notification(
        user_id=user.id, kind=kind, title="T", body="B", data={}
    )
    db.add(row)
    db.commit()
    return row


def _inbox_kinds(client, user):
    resp = client.get("/api/core/notifications", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return [n["kind"] for n in resp.json()]


def _disable_module(db, user, module_id):
    db.add(
        core_models.UserModulePref(
            user_id=user.id, module_id=module_id, enabled=False
        )
    )
    db.commit()


def test_c01_dealer_only_user_sees_warranty_notifications(client, db, dealer_user):
    _notify(db, dealer_user, "warranty_claim_new")
    _notify(db, dealer_user, "warranty_claim_update")
    _notify(db, dealer_user, "claim_deadline")
    kinds = _inbox_kinds(client, dealer_user)
    assert "warranty_claim_new" in kinds
    assert "warranty_claim_update" in kinds
    # No widening: a claims-only kind stays hidden for the dealer seat.
    assert "claim_deadline" not in kinds


def test_c01_claims_user_unaffected(client, db, owner):
    _notify(db, owner, "warranty_claim_new")
    _notify(db, owner, "warranty_claim_update")
    _notify(db, owner, "claim_deadline")
    kinds = _inbox_kinds(client, owner)
    assert "warranty_claim_new" in kinds
    assert "warranty_claim_update" in kinds
    assert "claim_deadline" in kinds


def test_c01_user_with_neither_module_sees_no_warranty_kinds(client, db, nobody):
    _notify(db, nobody, "warranty_claim_new")
    _notify(db, nobody, "warranty_claim_update")
    assert _inbox_kinds(client, nobody) == []


def test_c01_either_seat_suffices_and_neither_seat_hides(client, db, owner):
    # owner is mechanic-only: claims on, dealers off via the
    # per-user switch -> still visible through the claims seat.
    _notify(db, owner, "warranty_claim_new")
    _disable_module(db, owner, "dealers")
    assert "warranty_claim_new" in _inbox_kinds(client, owner)
    # Both seats off -> hidden again.
    _disable_module(db, owner, "claims")
    assert "warranty_claim_new" not in _inbox_kinds(client, owner)


# -- B-02: one open warranty claim per target, race-safe --------------------------


def test_b02_second_warranty_claim_refused_for_tool(client, db, owner):
    tool = _tool(db, owner)
    first = _warranty(client, owner, "tool", tool.id)
    assert first.status_code == 201, first.text
    second = _warranty(client, owner, "tool", tool.id)
    assert second.status_code == 422, second.text
    assert "already has an open warranty claim" in second.json()["detail"]
    assert _claim_count(db, owner) == 1


def test_b02_second_warranty_claim_refused_for_battery(client, db, owner):
    battery = _battery(db, owner)
    assert _warranty(client, owner, "battery", battery.id).status_code == 201
    second = _warranty(client, owner, "battery", battery.id)
    assert second.status_code == 422, second.text
    assert "already has an open warranty claim" in second.json()["detail"]
    assert _claim_count(db, owner) == 1


def test_b02_second_warranty_claim_refused_for_set_and_piece(client, db, owner):
    set_tool = _tool(db, owner, name="Socket set", is_set=True)
    piece = inventory_models.SetPiece(
        set_id=set_tool.id, owner_id=owner.id, kind="core",
        name="10mm socket", part_number="S10", status="present",
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)

    # The set itself (the shared ClaimForm's set path).
    assert _warranty(client, owner, "set", set_tool.id).status_code == 201
    second_set = _warranty(client, owner, "set", set_tool.id)
    assert second_set.status_code == 422, second_set.text
    assert "already has an open warranty claim" in second_set.json()["detail"]

    # A single piece of the set (the shared ClaimForm's piece path).
    assert _warranty(client, owner, "piece", piece.id).status_code == 201
    second_piece = _warranty(client, owner, "piece", piece.id)
    assert second_piece.status_code == 422, second_piece.text
    assert "already has an open warranty claim" in second_piece.json()["detail"]
    assert _claim_count(db, owner) == 2


def test_b02_two_callers_at_the_commit_boundary(db, owner):
    """Simulated parallel: two independent sessions call the
    service back to back at the commit boundary — the second
    caller's check runs against the first caller's committed
    claim, exactly as the per-target guard orders it on
    Postgres (where the guard is a session advisory lock)."""
    tool = _tool(db, owner)
    factory = sessionmaker(bind=db.get_bind(), class_=Session,
                           expire_on_commit=False)
    with factory() as s1, factory() as s2:
        claims_service.create_warranty_claim(
            s1, owner, target_kind="tool", target_id=tool.id,
            dealer_notified=True,
        )
        with pytest.raises(claims_service.ClaimsError) as excinfo:
            claims_service.create_warranty_claim(
                s2, owner, target_kind="tool", target_id=tool.id,
                dealer_notified=True,
            )
        assert "already has an open warranty claim" in str(excinfo.value)
    assert _claim_count(db, owner) == 1


# -- B-03: replace of an already-replaced item refuses ----------------------------


def test_b03_second_replace_of_a_tool_refuses(client, db, owner):
    tool = _tool(db, owner, purchase_price=Decimal("300.00"))
    first = _replace(client, owner, "tool", tool.id, amount_spent="15.00")
    assert first.status_code == 200, first.text
    assert len(_tools_of(db, owner)) == 2  # old + exactly one clone

    second = _replace(client, owner, "tool", tool.id, amount_spent="15.00")
    assert second.status_code == 422, second.text
    assert "already been replaced" in second.json()["detail"]
    assert len(_tools_of(db, owner)) == 2  # no second clone

    # The "different" mode refuses too — the standing, not the mode.
    third = _replace(client, owner, "tool", tool.id, mode="different")
    assert third.status_code == 422, third.text
    assert "already been replaced" in third.json()["detail"]


def test_b03_second_replace_of_a_battery_refuses(client, db, owner):
    battery = _battery(db, owner, purchase_price=Decimal("80.00"))
    first = _replace(client, owner, "battery", battery.id, amount_spent="20.00")
    assert first.status_code == 200, first.text
    second = _replace(client, owner, "battery", battery.id, amount_spent="20.00")
    assert second.status_code == 422, second.text
    assert "already been replaced" in second.json()["detail"]
    batteries = list(
        db.scalars(
            select(inventory_models.Battery).where(
                inventory_models.Battery.owner_id == owner.id
            )
        )
    )
    assert len(batteries) == 2


def _tools_of(db, owner):
    return list(
        db.scalars(
            select(inventory_models.Tool).where(
                inventory_models.Tool.owner_id == owner.id
            )
        )
    )


# -- C-16: error shapes ------------------------------------------------------------


def test_c16_expansion_not_found_is_404_on_both_posts(client, db, owner):
    dismiss = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": str(uuid.uuid4()),
            "suggested_model": "XYZ-9",
        },
        headers=auth_headers(owner),
    )
    assert dismiss.status_code == 404, dismiss.text
    # A whitespace model normalizes to nothing -> ExpansionNotFound
    # from the service, the only service path that raises it here.
    report = client.post(
        "/api/tool-expansion/report",
        json={"anchor_model": "ABC-1", "suggested_model": "   "},
        headers=auth_headers(owner),
    )
    assert report.status_code == 404, report.text


def test_c16_claims_party_gate_403_carries_the_full_house_shape(
    client, db, owner, dealer_user, other
):
    # Separation (2026-11-04): the claim under the gate is a
    # WARRANTY claim — the claims section's own population now.
    tool = _tool(db, owner)
    created = _warranty(client, owner, "tool", tool.id)
    assert created.status_code == 201, created.text
    claim_id = created.json()["claim"]["id"]

    # A dealer-only account (no claims module) asking for a claim
    # it is not a party to: the gate's 403, full shape.
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(dealer_user))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == {
        "code": "module_unavailable",
        "module": "claims",
        "message": "This module isn't enabled for your account.",
    }
    # Same full shape for an id that doesn't exist at all.
    resp = client.get(
        f"/api/claims/{uuid.uuid4()}", headers=auth_headers(dealer_user)
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["message"] == (
        "This module isn't enabled for your account."
    )
    # Control: a claims-module user who is not a party still gets
    # the plain non-leaking 404.
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(other))
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "That claim doesn't exist."}


# -- E-02: cross-owner set attach is a non-leaking 404 ------------------------------


def test_e02_cross_owner_attach_is_404_and_attaches_nothing(client, db, owner, other):
    a_set = _tool(db, owner, name="A set", is_set=True)
    a_tool = _tool(db, owner, name="A tool")
    b_set = _tool(db, other, name="B set", is_set=True)
    b_tool = _tool(db, other, name="B tool")

    # B attaching A's tool into B's own set.
    resp = client.post(
        f"/api/inventory/{a_tool.id}/attach-to-set",
        json={"set_id": str(b_set.id)},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "Tool not found"}

    # B attaching B's tool into A's set — byte-identical answer.
    resp2 = client.post(
        f"/api/inventory/{b_tool.id}/attach-to-set",
        json={"set_id": str(a_set.id)},
        headers=auth_headers(other),
    )
    assert resp2.status_code == 404, resp2.text
    assert resp2.json() == resp.json()

    # A random pair answers the same again — no existence oracle.
    resp3 = client.post(
        f"/api/inventory/{uuid.uuid4()}/attach-to-set",
        json={"set_id": str(uuid.uuid4())},
        headers=auth_headers(other),
    )
    assert resp3.status_code == 404, resp3.text
    assert resp3.json() == resp.json()

    db.refresh(a_tool)
    db.refresh(b_tool)
    assert a_tool.attached_to_set_id is None
    assert b_tool.attached_to_set_id is None


# -- E-03: dealer transition refusal tells the truth --------------------------------


def test_e03_dealer_refused_at_completed_is_not_told_it_is_final(
    client, db, owner, dealer_user
):
    company = dealer_models.DealerCompany(name="R2 Tool Co", email="")
    db.add(company)
    db.commit()
    db.refresh(company)
    # Agent scope (2026-10-31): the dealer drives the claim as
    # the owner's ASSIGNED agent with a VERIFIED link — the seat
    # E-03's refusal wording is about.
    db.add(
        dealer_models.CompanyRepresentation(
            company_id=company.id, agent_user_id=dealer_user.id,
            verified=True,
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
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    assert created.status_code == 201, created.text
    claim_id = created.json()["claim"]["id"]

    for to_status in ("in_repair", "completed"):
        moved = client.post(
            f"/api/claims/{claim_id}/transition",
            json={"to_status": to_status},
            headers=auth_headers(dealer_user),
        )
        assert moved.status_code == 200, moved.text

    refused = client.post(
        f"/api/claims/{claim_id}/transition",
        json={"to_status": "closed"},
        headers=auth_headers(dealer_user),
    )
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    # The claim is NOT final — the owner can still close it, and
    # the refusal now says so instead of declaring it final.
    assert "it is final" not in detail
    assert "only the owner can take it from this point" in detail
    assert "closed" in detail

    # And the owner really can still close it.
    closed = client.post(
        f"/api/claims/{claim_id}/transition",
        json={"to_status": "closed"},
        headers=auth_headers(owner),
    )
    assert closed.status_code == 200, closed.text


# -- D-06: validation failures never 500 --------------------------------------------


def test_d06_garbage_multipart_to_json_attach_endpoint_is_422(client, db, owner):
    tool = _tool(db, owner)
    resp = client.post(
        f"/api/inventory/{tool.id}/attachments",
        content=b"\xff\xfe\x00\x01 not a form, not json \x80\x81",
        headers={
            "Content-Type": "multipart/form-data; boundary=----r2garbage",
            **auth_headers(owner),
        },
    )
    assert resp.status_code == 422, resp.text


def test_d06_ordinary_validation_shape_unchanged(client, db, owner):
    tool = _tool(db, owner)
    resp = client.post(
        f"/api/inventory/{tool.id}/attachments",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, list) and detail
    assert {"type", "loc", "msg"} <= set(detail[0])
