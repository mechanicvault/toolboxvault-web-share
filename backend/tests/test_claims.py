"""Claims module — filing, snapshots, pins, guards, jobs, gating.

Covers the rules the module was specified with (blueprint §15 +
owner spec 2026-10-18/19):

  - lines target an asset, a whole SET (the include-addons choice
    asked and STORED), or a single set PIECE; every line snapshots
    its name/value at add time and never drifts afterwards;
  - value math per basis: PURCHASE cost is per-unit x quantity
    (claim money is what the owner paid — ruling 2026-11-06),
    sets price through the shared membership service's purchase
    total, pieces are owner-entered only; the retired
    replacement/MSRP bases are refused at the schema door;
  - the status flow refuses illegal moves; only drafts delete;
    incident facts freeze at filing;
  - the checklist is computed from contents (police report only
    for theft; proof-of-loss tracks the mark-sent action);
  - evidence by reference resolves live and refuses non-targets;
    claim uploads run the same kind/size machinery as items;
  - the lapse pin (the A1 seam, wired): an OPEN claim's items stay
    active past the limit; drafts pin nothing; closing releases;
    a piece line pins its parent set;
  - delete/detach guards: an item on an open claim can't be
    deleted and a claimed set can't be taken apart; closing the
    claim unblocks; account deletion still cascades cleanly;
  - deadline jobs notify once per claim + deadline (idempotent);
  - module gating: dealer/insurance 403, mechanic/shop allowed,
    and the pin/guard registration disappears with the module's
    claims — never for other users.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core import storage as storage_module
from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.claims import service as claims_service
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"


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
    return _make_user(db, "TV-M-000501", "claims@example.com", [MECHANIC], "Cal Claimant")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000502", "claims-other@example.com", [MECHANIC], "Otto Other")


@pytest.fixture()
def shop(db):
    return _make_user(db, "TV-S-000503", "claims-shop@example.com", [SHOP], "Sue Shop")


@pytest.fixture()
def dealer(db):
    return _make_user(db, "TV-D-000504", "claims-dealer@example.com", [DEALER], "Dan Dealer")


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 5.0 pack", **overrides):
    battery = inventory_models.Battery(owner_id=owner.id, name=name, **overrides)
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _set(db, owner, name="Socket Set", **overrides):
    overrides.setdefault("is_set", True)
    return _tool(db, owner, name=name, **overrides)


def _piece(db, owner, tool_set, name="10mm socket", **overrides):
    piece = inventory_models.SetPiece(
        owner_id=owner.id, set_id=tool_set.id, name=name, **overrides
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece


def _create_claim(client, user, **payload):
    response = client.post("/api/disaster-claims", json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _add_line(client, user, claim_id, **payload):
    return client.post(
        f"/api/disaster-claims/{claim_id}/lines", json=payload, headers=auth_headers(user)
    )


def _transition(client, user, claim_id, to_status):
    return client.post(
        f"/api/disaster-claims/{claim_id}/transition",
        json={"to_status": to_status},
        headers=auth_headers(user),
    )


def _file_claim(client, user, claim_id):
    response = _transition(client, user, claim_id, "filed")
    assert response.status_code == 200, response.text
    return response.json()


# -- numbering + lifecycle ---------------------------------------------------


def test_claim_numbers_are_sequential_per_owner(client, db, owner, other):
    first = _create_claim(client, owner)
    second = _create_claim(client, owner)
    year = date.today().year
    assert first["claim_number"] == f"DC-{year}-001"
    assert second["claim_number"] == f"DC-{year}-002"
    # Another owner's sequence is their own.
    theirs = _create_claim(client, other)
    assert theirs["claim_number"] == f"DC-{year}-001"
    # A deleted DRAFT's number returns to the pool — it was never
    # filed or shared. (Filed claims can't be deleted at all, so a
    # number that reached an insurer is permanent.)
    assert client.delete(
        f"/api/disaster-claims/{second['id']}", headers=auth_headers(owner)
    ).status_code == 204
    third = _create_claim(client, owner)
    assert third["claim_number"] == f"DC-{year}-002"


def test_status_flow_and_illegal_moves(client, db, owner):
    claim = _create_claim(client, owner)
    cid = claim["id"]
    # From draft, only "filed" is legal.
    for target in ("in_review", "approved", "denied", "paid", "closed"):
        response = _transition(client, owner, cid, target)
        assert response.status_code == 422, target
    view = _file_claim(client, owner, cid)
    assert view["status"] == "filed"
    assert view["filed_at"] is not None
    # A filed claim can't be deleted — it closes.
    response = client.delete(f"/api/disaster-claims/{cid}", headers=auth_headers(owner))
    assert response.status_code == 422
    # The happy path, end to end.
    for target in ("in_review", "approved", "paid", "closed"):
        response = _transition(client, owner, cid, target)
        assert response.status_code == 200, (target, response.text)
    view = response.json()
    assert view["status"] == "closed"
    assert view["closed_at"] is not None
    assert view["allowed_transitions"] == []
    # A closed claim is final.
    assert _transition(client, owner, cid, "closed").status_code == 422


def test_denied_branch_closes(client, db, owner):
    claim = _create_claim(client, owner)
    _file_claim(client, owner, claim["id"])
    response = _transition(client, owner, claim["id"], "denied")
    assert response.status_code == 200
    assert _transition(client, owner, claim["id"], "paid").status_code == 422
    assert _transition(client, owner, claim["id"], "closed").status_code == 200


def test_incident_facts_freeze_at_filing(client, db, owner):
    claim = _create_claim(
        client, owner, incident_type="theft", incident_date="2026-10-01",
        insurer_name="Acme Mutual",
    )
    cid = claim["id"]
    # Draft: incident facts editable.
    response = client.patch(
        f"/api/disaster-claims/{cid}", json={"incident_date": "2026-10-02"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    _file_claim(client, owner, cid)
    # Filed: the incident is the insurer's record — frozen...
    response = client.patch(
        f"/api/disaster-claims/{cid}", json={"incident_date": "2026-10-03"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    response = client.patch(
        f"/api/disaster-claims/{cid}", json={"incident_type": "fire"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    # ...but follow-up facts (insurer, deadlines) still correct.
    response = client.patch(
        f"/api/disaster-claims/{cid}",
        json={"policy_number": "POL-123", "proof_of_loss_due": "2026-12-01"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    assert response.json()["policy_number"] == "POL-123"


def test_other_users_claim_is_invisible(client, db, owner, other):
    claim = _create_claim(client, owner)
    assert client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(other)
    ).status_code == 404
    assert client.get("/api/disaster-claims", headers=auth_headers(other)).json() == []


# -- lines: shapes and value math ----------------------------------------------


def test_tool_line_purchase_times_quantity_and_snapshot(client, db, owner):
    # Claim money is PURCHASE COST (owner ruling, 2026-11-06):
    # the line prices from what the owner PAID — the replacement
    # cost and MSRP on the same record are decoys it must ignore.
    tool = _tool(
        db, owner, purchase_price=Decimal("120.00"), quantity=3,
        replacement_cost=Decimal("999.00"), msrp=Decimal("150.00"),
    )
    claim = _create_claim(client, owner)
    response = _add_line(
        client, owner, claim["id"], target_kind="tool", target_id=str(tool.id)
    )
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["target_name"] == "Impact wrench"
    assert line["value_basis"] == "purchase"
    assert Decimal(line["amount"]) == Decimal("360.00")  # 120 x 3

    # The snapshot never drifts: re-price and rename the tool and
    # the line keeps what it was filed with.
    tool.purchase_price = Decimal("555.00")
    tool.name = "Renamed wrench"
    db.commit()
    view = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    assert view["lines"][0]["target_name"] == "Impact wrench"
    assert Decimal(view["lines"][0]["amount"]) == Decimal("360.00")
    assert Decimal(view["total_amount"]) == Decimal("360.00")


def test_purchase_basis_and_missing_value_copy(client, db, owner):
    tool = _tool(
        db, owner, purchase_price=None, replacement_cost=Decimal("200.00"),
        msrp=Decimal("200.00"), quantity=2,
    )
    claim = _create_claim(client, owner)
    # No purchase price recorded → a friendly refusal naming the
    # fix. The replacement cost sitting on the record does NOT
    # stand in for it (owner ruling, 2026-11-06).
    response = _add_line(
        client, owner, claim["id"], target_kind="tool", target_id=str(tool.id)
    )
    assert response.status_code == 422
    assert "no purchase price recorded" in response.json()["detail"]
    # The retired bases are refused at the schema door.
    for retired in ("replacement", "msrp"):
        response = _add_line(
            client, owner, claim["id"], target_kind="tool",
            target_id=str(tool.id), value_basis=retired,
        )
        assert response.status_code == 422, retired
    # Purchase works once recorded: 200 x 2.
    tool.purchase_price = Decimal("200.00")
    db.commit()
    response = _add_line(
        client, owner, claim["id"], target_kind="tool",
        target_id=str(tool.id), value_basis="purchase",
    )
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["amount"]) == Decimal("400.00")
    # Entered basis takes the owner's figure as given.
    other_tool = _tool(db, owner, name="Entered tool")
    response = _add_line(
        client, owner, claim["id"], target_kind="tool",
        target_id=str(other_tool.id), value_basis="entered", amount="75.50",
    )
    assert response.status_code == 201
    assert Decimal(response.json()["amount"]) == Decimal("75.50")


def test_battery_line(client, db, owner):
    battery = _battery(
        db, owner, purchase_price=Decimal("89.99"), quantity=2,
        replacement_cost=Decimal("129.99"),
    )
    claim = _create_claim(client, owner)
    response = _add_line(
        client, owner, claim["id"], target_kind="battery",
        target_id=str(battery.id),
    )
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["value_basis"] == "purchase"
    assert Decimal(line["amount"]) == Decimal("179.98")  # 89.99 x 2


def test_set_line_addons_choice_is_stored_and_priced(client, db, owner):
    tool_set = _set(
        db, owner, purchase_price=Decimal("300.00"), quantity=1,
        replacement_cost=Decimal("500.00"),
    )
    _piece(db, owner, tool_set, name="Core socket", kind="core", part_number="SK-1")
    addon = _piece(
        db, owner, tool_set, name="Addon ratchet", kind="addon",
        part_number="SK-2", price=Decimal("45.00"),
    )
    attached = _tool(
        db, owner, name="Extension bar", purchase_price=Decimal("80.00"),
        replacement_cost=Decimal("120.00"), quantity=1,
    )
    attached.attached_to_set_id = tool_set.id
    db.commit()

    claim = _create_claim(client, owner)
    # Without addons: the set's own purchase cost only.
    response = _add_line(
        client, owner, claim["id"], target_kind="set",
        target_id=str(tool_set.id), include_addons=False,
    )
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["include_addons"] is False
    assert line["set_id"] == str(tool_set.id)
    assert Decimal(line["amount"]) == Decimal("300.00")
    _remove = client.delete(
        f"/api/disaster-claims/{claim['id']}/lines/{line['id']}", headers=auth_headers(owner)
    )
    assert _remove.status_code == 204
    # With addons: the addon piece's recorded price and the
    # attached tool's purchase price join the set's own — the
    # membership service's purchase total (300 + 45 + 80).
    response = _add_line(
        client, owner, claim["id"], target_kind="set",
        target_id=str(tool_set.id), include_addons=True,
    )
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["include_addons"] is True
    assert Decimal(line["amount"]) == Decimal("425.00")
    # A set added as a plain "tool" is refused with the reason.
    response = _add_line(
        client, owner, claim["id"], target_kind="tool",
        target_id=str(tool_set.id),
    )
    assert response.status_code == 422
    assert "as a set" in response.json()["detail"]


def test_piece_line_is_entered_value_only(client, db, owner):
    tool_set = _set(db, owner, replacement_cost=Decimal("300.00"))
    piece = _piece(db, owner, tool_set, name="Lost socket", kind="core")
    claim = _create_claim(client, owner)
    # Pieces have no replacement value of their own.
    response = _add_line(
        client, owner, claim["id"], target_kind="piece",
        target_id=str(piece.id),
    )
    assert response.status_code == 422
    assert "Enter the amount" in response.json()["detail"]
    response = _add_line(
        client, owner, claim["id"], target_kind="piece",
        target_id=str(piece.id), value_basis="entered", amount="25.00",
    )
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["set_id"] == str(tool_set.id)
    assert line["set_name"] == "Socket Set"
    assert line["value_basis"] == "entered"
    assert Decimal(line["amount"]) == Decimal("25.00")


def test_duplicate_line_and_filed_lines_are_fixed(client, db, owner):
    tool = _tool(
        db, owner, replacement_cost=Decimal("10.00"),
        purchase_price=Decimal("10.00"),
    )
    claim = _create_claim(client, owner)
    assert _add_line(
        client, owner, claim["id"], target_kind="tool", target_id=str(tool.id)
    ).status_code == 201
    response = _add_line(
        client, owner, claim["id"], target_kind="tool", target_id=str(tool.id)
    )
    assert response.status_code == 422
    assert "already on this claim" in response.json()["detail"]
    _file_claim(client, owner, claim["id"])
    line_id = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()["lines"][0]["id"]
    # Filed claims' contents are the insurer's record.
    assert _add_line(
        client, owner, claim["id"], target_kind="tool",
        target_id=str(_tool(db, owner, name="Late tool").id),
    ).status_code == 422
    assert client.delete(
        f"/api/disaster-claims/{claim['id']}/lines/{line_id}", headers=auth_headers(owner)
    ).status_code == 422


# -- checklist -------------------------------------------------------------------


def test_checklist_computes_from_contents(client, db, owner):
    claim = _create_claim(client, owner)  # incident_type "other"
    items = {i["key"]: i["done"] for i in claim["checklist"]}
    assert items == {
        "incident": False,
        "items": False,
        "evidence": False,
        "proof_of_loss": False,
    }  # no police_report item for non-theft
    cid = claim["id"]
    tool = _tool(
        db, owner, replacement_cost=Decimal("10.00"),
        purchase_price=Decimal("10.00"),
    )
    _add_line(client, owner, cid, target_kind="tool", target_id=str(tool.id))
    client.patch(
        f"/api/disaster-claims/{cid}",
        json={
            "incident_date": "2026-10-10",
            "description": "Garage broken into overnight.",
        },
        headers=auth_headers(owner),
    )
    view = client.get(f"/api/disaster-claims/{cid}", headers=auth_headers(owner)).json()
    items = {i["key"]: i["done"] for i in view["checklist"]}
    assert items["incident"] is True
    assert items["items"] is True
    assert items["evidence"] is False


def test_checklist_police_report_only_for_theft(client, db, owner):
    claim = _create_claim(
        client, owner, incident_type="theft",
        incident_date="2026-10-01", description="Trailer stolen.",
    )
    items = {i["key"]: i["done"] for i in claim["checklist"]}
    assert items["police_report"] is False
    client.patch(
        f"/api/disaster-claims/{claim['id']}",
        json={"police_report_number": "26-1042", "police_department": "Morrison County Sheriff"},
        headers=auth_headers(owner),
    )
    view = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    items = {i["key"]: i["done"] for i in view["checklist"]}
    assert items["police_report"] is True


def test_proof_of_loss_mark_sent(client, db, owner):
    claim = _create_claim(client, owner)
    cid = claim["id"]
    # A draft has sent nothing to anyone.
    response = client.post(
        f"/api/disaster-claims/{cid}/proof-of-loss-sent", json={},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    _file_claim(client, owner, cid)
    response = client.post(
        f"/api/disaster-claims/{cid}/proof-of-loss-sent",
        json={"sent_date": "2026-10-15"}, headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["proof_of_loss_sent_at"] == "2026-10-15"
    items = {i["key"]: i["done"] for i in view["checklist"]}
    assert items["proof_of_loss"] is True


# -- evidence -----------------------------------------------------------------------


def _tool_with_receipt(db, owner):
    tool = _tool(
        db, owner, replacement_cost=Decimal("50.00"),
        purchase_price=Decimal("50.00"),
    )
    tool.attachments = [
        {
            "key": f"{owner.id}/tools/{tool.id}/receipt/receipt.pdf",
            "filename": "receipt.pdf",
            "kind": "receipt",
            "content_type": "application/pdf",
            "size_bytes": 1234,
            "uploaded_at": "2026-10-01T00:00:00+00:00",
        }
    ]
    db.commit()
    db.refresh(tool)
    return tool


def test_evidence_reference_resolves_live(client, db, owner):
    tool = _tool_with_receipt(db, owner)
    claim = _create_claim(client, owner)
    _add_line(client, owner, claim["id"], target_kind="tool", target_id=str(tool.id))
    key = tool.attachments[0]["key"]
    response = client.post(
        f"/api/disaster-claims/{claim['id']}/evidence",
        json={"item_kind": "tool", "item_id": str(tool.id), "attachment_key": key},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["source"] == "reference"
    assert view["filename"] == "receipt.pdf"
    assert view["kind"] == "receipt"
    assert view["available"] is True
    assert view["url"]  # a fresh presigned link was minted
    # Duplicates refused; the checklist's evidence item flips.
    assert client.post(
        f"/api/disaster-claims/{claim['id']}/evidence",
        json={"item_kind": "tool", "item_id": str(tool.id), "attachment_key": key},
        headers=auth_headers(owner),
    ).status_code == 422
    detail = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    items = {i["key"]: i["done"] for i in detail["checklist"]}
    assert items["evidence"] is True


def test_evidence_reference_requires_a_target_item(client, db, owner):
    tool = _tool_with_receipt(db, owner)
    stranger = _tool_with_receipt(db, owner)  # not on the claim
    claim = _create_claim(client, owner)
    _add_line(client, owner, claim["id"], target_kind="tool", target_id=str(tool.id))
    response = client.post(
        f"/api/disaster-claims/{claim['id']}/evidence",
        json={
            "item_kind": "tool", "item_id": str(stranger.id),
            "attachment_key": stranger.attachments[0]["key"],
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    assert "add the item to the claim first" in response.json()["detail"]


def test_evidence_reference_survives_file_removal(client, db, owner):
    tool = _tool_with_receipt(db, owner)
    claim = _create_claim(client, owner)
    _add_line(client, owner, claim["id"], target_kind="tool", target_id=str(tool.id))
    key = tool.attachments[0]["key"]
    client.post(
        f"/api/disaster-claims/{claim['id']}/evidence",
        json={"item_kind": "tool", "item_id": str(tool.id), "attachment_key": key},
        headers=auth_headers(owner),
    )
    # The file leaves the item later: the reference row stays
    # readable (snapshot filename) and reports itself unavailable.
    tool.attachments = []
    db.commit()
    detail = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    row = detail["evidence"][0]
    assert row["available"] is False
    assert row["url"] is None
    assert row["filename"] == "receipt.pdf"


def test_evidence_upload_kinds_and_attach(client, db, owner, monkeypatch):
    claim = _create_claim(client, owner)
    cid = claim["id"]
    monkeypatch.setattr(
        storage_module.storage, "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    # An executable is refused for every kind, like item uploads.
    response = client.post(
        f"/api/disaster-claims/{cid}/evidence/upload-url",
        json={
            "kind": "document", "filename": "x.exe",
            "content_type": "application/x-msdownload", "size_bytes": 100,
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    # A PDF document is fine; a photo must be an image.
    response = client.post(
        f"/api/disaster-claims/{cid}/evidence/upload-url",
        json={
            "kind": "photo", "filename": "scene.pdf",
            "content_type": "application/pdf", "size_bytes": 100,
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/disaster-claims/{cid}/evidence/upload-url",
        json={
            "kind": "document", "filename": "statement.pdf",
            "content_type": "application/pdf", "size_bytes": 2048,
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    key = response.json()["key"]
    assert key.startswith(f"{owner.id}/claims/{cid}/document/")
    monkeypatch.setattr(
        storage_module.storage, "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=2048, content_type="application/pdf"
        ),
    )
    # F4-06 sniff: the fake object's bytes must match its type.
    monkeypatch.setattr(
        storage_module.storage, "fetch_prefix",
        lambda k, length=512: b"%PDF-1.7\n" + b"\x00" * 32,
    )
    monkeypatch.setattr(
        storage_module.storage, "presigned_get_url",
        lambda k, expires_in=900: f"https://files.test/get/{k}",
    )
    attached = client.post(
        f"/api/disaster-claims/{cid}/evidence/attach",
        json={"key": key, "filename": "statement.pdf"},
        headers=auth_headers(owner),
    )
    assert attached.status_code == 201, attached.text
    view = attached.json()
    assert view["source"] == "upload"
    assert view["available"] is True
    assert view["filename"] == "statement.pdf"
    # A key namespaced to another claim is refused.
    foreign = client.post(
        f"/api/disaster-claims/{cid}/evidence/attach",
        json={"key": f"{owner.id}/claims/{uuid.uuid4()}/document/x.pdf"},
        headers=auth_headers(owner),
    )
    assert foreign.status_code == 422


# -- communications log ------------------------------------------------------------


def test_communications_log_crud(client, db, owner):
    claim = _create_claim(client, owner)
    cid = claim["id"]
    created = client.post(
        f"/api/disaster-claims/{cid}/communications",
        json={
            "channel": "phone", "contact": "Adjuster Amy",
            "summary": "Intake call; claim acknowledged.",
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["channel"] == "phone"
    assert entry["occurred_at"] is not None
    updated = client.patch(
        f"/api/disaster-claims/{cid}/communications/{entry['id']}",
        json={"summary": "Intake call; inspection scheduled Friday."},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200
    assert "inspection scheduled" in updated.json()["summary"]
    detail = client.get(f"/api/disaster-claims/{cid}", headers=auth_headers(owner)).json()
    assert len(detail["communications"]) == 1
    assert client.delete(
        f"/api/disaster-claims/{cid}/communications/{entry['id']}",
        headers=auth_headers(owner),
    ).status_code == 204
    detail = client.get(f"/api/disaster-claims/{cid}", headers=auth_headers(owner)).json()
    assert detail["communications"] == []


def test_comms_log_freezes_when_closed(client, db, owner):
    claim = _create_claim(client, owner)
    cid = claim["id"]
    _file_claim(client, owner, cid)
    _transition(client, owner, cid, "closed")
    response = client.post(
        f"/api/disaster-claims/{cid}/communications",
        json={"channel": "email", "summary": "Late note."},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422


# -- stats + targets ------------------------------------------------------------------


def test_open_claims_stat_counts_in_flight_including_drafts(client, db, owner):
    # Deep audit F1-23: the home stat counts every claim still in
    # flight — drafts included, matching the live work the Claims
    # page lists — and only terminal claims (paid here) drop out.
    assert claims_service.stats(
        db, owner.id, claims_service.models.KIND_INSURANCE
    ) == {"open_claims_count": 0}
    draft = _create_claim(client, owner)
    filed = _create_claim(client, owner)
    _file_claim(client, owner, filed["id"])
    paid = _create_claim(client, owner)
    _file_claim(client, owner, paid["id"])
    for target in ("in_review", "approved", "paid"):
        _transition(client, owner, paid["id"], target)
    response = client.get("/api/disaster-claims/stats", headers=auth_headers(owner))
    assert response.status_code == 200
    assert response.json() == {"open_claims_count": 2}  # draft + filed


def test_targets_picker_shape(client, db, owner):
    tool_set = _set(db, owner, replacement_cost=Decimal("300.00"))
    _piece(db, owner, tool_set, name="Core socket", kind="core")
    _tool(db, owner, name="Plain tool", replacement_cost=Decimal("10.00"))
    _battery(db, owner, replacement_cost=Decimal("50.00"))
    response = client.get("/api/disaster-claims/targets", headers=auth_headers(owner))
    assert response.status_code == 200, response.text
    payload = response.json()
    kinds = {t["name"]: t["kind"] for t in payload["tools"]}
    assert kinds == {"Socket Set": "set", "Plain tool": "tool"}
    set_entry = next(t for t in payload["tools"] if t["kind"] == "set")
    assert [p["name"] for p in set_entry["pieces"]] == ["Core socket"]
    assert [b["name"] for b in payload["batteries"]] == ["M18 5.0 pack"]


# -- damage claims show repair records -----------------------------------------------


def test_damage_claim_detail_has_no_repair_block(client, db, owner):
    # Merge (2026-11-04): the claims->maintenance repair block is
    # RETIRED. A damage claim's detail carries no "repairs" key —
    # an item's repair history is its own warranty claims now,
    # and the repair facts ride those claims (and the item's
    # claims list) instead of a borrowed maintenance panel.
    tool = _tool(db, owner, replacement_cost=Decimal("100.00"))
    claim = _create_claim(
        client, owner, incident_type="damage",
        incident_date="2026-10-12", description="Dropped off the lift.",
    )
    _add_line(client, owner, claim["id"], target_kind="tool", target_id=str(tool.id))
    detail = client.get(
        f"/api/disaster-claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    assert "repairs" not in detail

    # The same item's repair story, told by its warranty claim:
    # break -> send -> fixed with the cost ON THE CLAIM.
    created = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": "Motor burned out",
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    warranty = created.json()["claim"]
    assert warranty["repair_sent_to"] == ""
    assert warranty["repair_cost"] is None

    reported = client.post(
        f"/api/claims/{warranty['id']}/transition",
        json={"to_status": "reported"},
        headers=auth_headers(owner),
    )
    assert reported.status_code == 200, reported.text
    sent = client.post(
        f"/api/claims/{warranty['id']}/transition",
        json={"to_status": "in_repair", "repair_sent_to": "Motor Shop"},
        headers=auth_headers(owner),
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["repair_sent_to"] == "Motor Shop"
    fixed = client.post(
        f"/api/claims/{warranty['id']}/transition",
        json={"to_status": "completed", "repair_cost": "85.50"},
        headers=auth_headers(owner),
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["repair_cost"] == "85.50"
    assert fixed.json()["repair_completed_at"] is not None

    # The item's claims list surfaces the repair facts inline.
    listing = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    refs = {ref["id"]: ref for ref in listing["current"] + listing["history"]}
    ref = refs[warranty["id"]]
    assert ref["repair_sent_to"] == "Motor Shop"
    assert Decimal(ref["repair_cost"]) == Decimal("85.50")


# -- the lapse pin ---------------------------------------------------------------------


def _seed_plans(db):
    db.add_all(
        [
            billing_models.Plan(
                plan_key="free", name="Free", item_limit=20,
                ai_monthly_credits=0, is_paid=False, sort_order=0,
            ),
            billing_models.Plan(
                plan_key="pro", name="Pro", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=1,
            ),
            billing_models.Plan(
                plan_key="business", name="Business", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=2,
            ),
        ]
    )
    db.add_all(
        [
            billing_models.BusinessBracket(
                plan_key="business", up_to_employees=limit,
                bracket_key=key, sort_order=order,
            )
            for order, (limit, key) in enumerate(
                [(5, "up_to_5"), (10, "up_to_10"), (25, "up_to_25"), (None, "unlimited")]
            )
        ]
    )
    db.commit()


def _aged_tool(db, owner, name, age_minutes):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return _tool(
        db, owner, name=name, replacement_cost=Decimal("10.00"),
        purchase_price=Decimal("10.00"),
        created_at=base + timedelta(minutes=age_minutes),
    )


def test_open_claim_pins_item_past_the_limit(db, owner, client):
    _seed_plans(db)
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    # 21 tools on a 20-item free plan: the OLDEST falls outside.
    oldest = _aged_tool(db, owner, "Oldest tool", 0)
    for i in range(1, 21):
        _aged_tool(db, owner, f"Tool {i:02d}", i)
    active = entitlements.active_tool_ids(db, owner.id)
    assert oldest.id not in active
    assert len(active) == 20

    # A DRAFT claim pins nothing.
    claim = claims_service.create_claim(db, owner, incident_type="theft")
    claims_service.add_line(
        db, owner, claim.id, target_kind="tool", target_id=oldest.id
    )
    assert oldest.id not in entitlements.active_tool_ids(db, owner.id)

    # Filing pins it — in ADDITION to the newest 20.
    claims_service.transition(db, owner, claim.id, "filed")
    active = entitlements.active_tool_ids(db, owner.id)
    assert oldest.id in active
    assert len(active) == 21
    pinned_tools, _ = entitlements.pinned_asset_ids(db, owner.id)
    assert pinned_tools == {oldest.id}

    # Closing releases the pin; the item greys again.
    claims_service.transition(db, owner, claim.id, "closed")
    assert oldest.id not in entitlements.active_tool_ids(db, owner.id)


def test_battery_pin_and_piece_line_pins_parent_set(db, owner, client):
    _seed_plans(db)
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # The set is the oldest asset; 20 newer tools push it out.
    tool_set = _set(
        db, owner, replacement_cost=Decimal("300.00"),
        purchase_price=Decimal("300.00"),
        created_at=base,
    )
    piece = _piece(db, owner, tool_set, name="Claimed socket", kind="core")
    battery = _battery(
        db, owner, replacement_cost=Decimal("50.00"),
        purchase_price=Decimal("50.00"),
        created_at=base + timedelta(minutes=1),
    )
    for i in range(20):
        _aged_tool(db, owner, f"Filler {i:02d}", 10 + i)
    active_tools = entitlements.active_tool_ids(db, owner.id)
    active_batteries = entitlements.active_battery_ids(db, owner.id)
    assert tool_set.id not in active_tools
    assert battery.id not in active_batteries

    # One open claim: a piece line (pins the parent SET) and a
    # battery line (pins the battery).
    claim = claims_service.create_claim(db, owner, incident_type="theft")
    claims_service.add_line(
        db, owner, claim.id, target_kind="piece", target_id=piece.id,
        value_basis="entered", amount=Decimal("25.00"),
    )
    claims_service.add_line(
        db, owner, claim.id, target_kind="battery", target_id=battery.id
    )
    claims_service.transition(db, owner, claim.id, "filed")
    assert tool_set.id in entitlements.active_tool_ids(db, owner.id)
    assert battery.id in entitlements.active_battery_ids(db, owner.id)


# -- delete / detach guards -------------------------------------------------------------


def test_delete_guard_blocks_open_claim_and_close_unblocks(client, db, owner):
    tool = _tool(
        db, owner, replacement_cost=Decimal("10.00"),
        purchase_price=Decimal("10.00"),
    )
    # A draft claim blocks nothing.
    draft = _create_claim(client, owner)
    _add_line(client, owner, draft["id"], target_kind="tool", target_id=str(tool.id))
    claim = _create_claim(client, owner)
    _add_line(client, owner, claim["id"], target_kind="tool", target_id=str(tool.id))
    _file_claim(client, owner, claim["id"])
    response = client.delete(
        f"/api/inventory/{tool.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 422, response.text
    assert claim["claim_number"] in response.json()["detail"]
    # Close the claim → the delete goes through.
    _transition(client, owner, claim["id"], "closed")
    response = client.delete(
        f"/api/inventory/{tool.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 204, response.text


def test_battery_and_piece_guards(client, db, owner):
    battery = _battery(
        db, owner, replacement_cost=Decimal("50.00"),
        purchase_price=Decimal("50.00"),
    )
    claim = _create_claim(client, owner)
    _add_line(
        client, owner, claim["id"], target_kind="battery", target_id=str(battery.id)
    )
    _file_claim(client, owner, claim["id"])
    response = client.delete(
        f"/api/inventory/batteries/{battery.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 422
    # A piece of a claimed set can't be removed either.
    tool_set = _set(
        db, owner, replacement_cost=Decimal("300.00"),
        purchase_price=Decimal("300.00"),
    )
    piece = _piece(db, owner, tool_set, name="Guarded socket", kind="core")
    set_claim = _create_claim(client, owner)
    _add_line(
        client, owner, set_claim["id"], target_kind="set",
        target_id=str(tool_set.id),
    )
    _file_claim(client, owner, set_claim["id"])
    response = client.delete(
        f"/api/inventory/pieces/{piece.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 422
    assert set_claim["claim_number"] in response.json()["detail"]


def test_detach_guard_protects_claimed_set(client, db, owner):
    tool_set = _set(
        db, owner, replacement_cost=Decimal("300.00"),
        purchase_price=Decimal("300.00"),
    )
    attached = _tool(
        db, owner, name="Addon drill", replacement_cost=Decimal("80.00"),
        purchase_price=Decimal("80.00"),
    )
    attached.attached_to_set_id = tool_set.id
    db.commit()
    claim = _create_claim(client, owner)
    _add_line(
        client, owner, claim["id"], target_kind="set",
        target_id=str(tool_set.id), include_addons=True,
    )
    _file_claim(client, owner, claim["id"])
    response = client.post(
        f"/api/inventory/{attached.id}/detach", headers=auth_headers(owner)
    )
    assert response.status_code == 422, response.text
    assert claim["claim_number"] in response.json()["detail"]
    _transition(client, owner, claim["id"], "closed")
    response = client.post(
        f"/api/inventory/{attached.id}/detach", headers=auth_headers(owner)
    )
    assert response.status_code == 200, response.text
    assert response.json()["attached_to_set_id"] is None


def test_account_deletion_cascades_through_open_claims(db, owner):
    tool = _tool(
        db, owner, replacement_cost=Decimal("10.00"),
        purchase_price=Decimal("10.00"),
    )
    claim = claims_service.create_claim(db, owner, incident_type="theft")
    claims_service.add_line(
        db, owner, claim.id, target_kind="tool", target_id=tool.id
    )
    claims_service.transition(db, owner, claim.id, "filed")
    # The guard would refuse this delete directly...
    from app.modules.inventory import service as inventory_service

    with pytest.raises(inventory_service.ToolValidationError):
        inventory_service.delete_tool(db, owner.id, tool.id)
    # ...but account deletion removes the claims FIRST, so the
    # cascade completes and leaves nothing behind.
    core_service.delete_account(db, owner)
    assert db.get(core_models.User, owner.id) is None
    assert claims_service.list_claims(db, owner) == []
    assert db.get(inventory_models.Tool, tool.id) is None


# -- deadline jobs ------------------------------------------------------------------------


def _filed_claim_with(db, owner, **fields):
    claim = claims_service.create_claim(db, owner, **fields)
    claims_service.transition(db, owner, claim.id, "filed")
    return claim


def test_deadline_jobs_notify_once_per_claim_and_deadline(db, owner):
    today = date(2026, 10, 19)
    due_soon = _filed_claim_with(
        db, owner, incident_type="theft",
        proof_of_loss_due=today + timedelta(days=3),
    )
    overdue = _filed_claim_with(
        db, owner, incident_type="fire",
        proof_of_loss_due=today - timedelta(days=2),
    )
    far = _filed_claim_with(
        db, owner, incident_type="loss",
        proof_of_loss_due=today + timedelta(days=30),
    )
    draft = claims_service.create_claim(
        db, owner, incident_type="theft",
        proof_of_loss_due=today + timedelta(days=1),
    )
    created = claims_service.run_deadline_notifications(db, today=today)
    assert created == 2  # due-soon + overdue; far and draft silent
    # Idempotent: a re-run creates nothing.
    assert claims_service.run_deadline_notifications(db, today=today) == 0
    rows = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.kind == "claim_deadline")
        .all()
    )
    assert len(rows) == 2
    numbers = {r.data["claim_number"] for r in rows}
    assert numbers == {due_soon.claim_number, overdue.claim_number}
    # Marking the proof of loss sent retires that deadline: move
    # the due date and it earns no new notification either way.
    claims_service.mark_proof_of_loss_sent(db, owner, due_soon.id, today)
    due_soon.proof_of_loss_due = today + timedelta(days=1)
    db.commit()
    assert claims_service.run_deadline_notifications(db, today=today) == 0
    # A MOVED deadline (unsent claim) earns a fresh notification.
    overdue.proof_of_loss_due = today + timedelta(days=5)
    db.commit()
    assert claims_service.run_deadline_notifications(db, today=today) == 1


def test_depreciation_deadline_notifies_after_approval(db, owner):
    today = date(2026, 10, 19)
    claim = claims_service.create_claim(
        db, owner, incident_type="damage",
        depreciation_deadline=today + timedelta(days=4),
    )
    # Not yet approved: the depreciation window hasn't opened.
    claims_service.transition(db, owner, claim.id, "filed")
    assert claims_service.run_deadline_notifications(db, today=today) == 0
    claims_service.transition(db, owner, claim.id, "in_review")
    claims_service.transition(db, owner, claim.id, "approved")
    assert claims_service.run_deadline_notifications(db, today=today) == 1
    assert claims_service.run_deadline_notifications(db, today=today) == 0


# -- module gating ---------------------------------------------------------------------------


def test_module_gating_by_group(client, db, owner, shop, dealer):
    assert client.get("/api/disaster-claims", headers=auth_headers(owner)).status_code == 200
    assert client.get("/api/disaster-claims", headers=auth_headers(shop)).status_code == 200
    response = client.get("/api/disaster-claims", headers=auth_headers(dealer))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"
    # The home stat rides the same gate.
    assert client.get(
        "/api/disaster-claims/stats", headers=auth_headers(dealer)
    ).status_code == 403


def test_claims_in_my_modules_for_mechanic_not_dealer(client, db, owner, dealer):
    mine = client.get("/api/core/my-modules", headers=auth_headers(owner)).json()
    assert "claims" in {m["name"] for m in mine}
    theirs = client.get("/api/core/my-modules", headers=auth_headers(dealer)).json()
    assert "claims" not in {m["name"] for m in theirs}


# -- export -----------------------------------------------------------------------------------


def test_export_rows_carry_the_full_claim(db, owner):
    tool = _tool(
        db, owner, replacement_cost=Decimal("42.00"),
        purchase_price=Decimal("42.00"),
    )
    claim = claims_service.create_claim(
        db, owner, incident_type="theft", insurer_name="Acme Mutual"
    )
    claims_service.add_line(
        db, owner, claim.id, target_kind="tool", target_id=tool.id
    )
    claims_service.add_communication(
        db, owner, claim.id, channel="email", contact="Desk",
        summary="Sent the inventory list.",
    )
    payload = claims_service.export_rows(db, owner.id)
    assert len(payload["claims"]) == 1
    exported = payload["claims"][0]
    assert exported["claim_number"] == claim.claim_number
    assert exported["insurer_name"] == "Acme Mutual"
    assert exported["lines"][0]["target_name"] == "Impact wrench"
    assert exported["communications"][0]["summary"] == "Sent the inventory list."
