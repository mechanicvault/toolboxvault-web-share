"""Sold tracking (Wave 2, 2026-10-20): the sale ledger, full /
partial / piece sales, the active-set exit, guards (checked out,
open claim), LIFO undo with reversal rows, totals, reports
columns, history events, and the for-sale poster."""

from __future__ import annotations

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Seller"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000802", "seller@example.com")


def _tool(client, user, **over):
    body = {"name": "Snap-on ratchet", "quantity": 1}
    body.update(over)
    resp = client.post("/api/inventory", json=body, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sell_tool(client, user, tool_id, **over):
    body = {"sale_price": "120.00"}
    body.update(over)
    return client.post(
        f"/api/inventory/tools/{tool_id}/mark-sold", json=body, headers=auth_headers(user)
    )


def _asset_count(db, user):
    """The billing active-set count — the number that decides the
    plan cap. Sold must drop it; lost/stolen must not."""
    from app.modules.billing import entitlements

    return entitlements.asset_count(db, user.id)


def test_full_sale_exits_active_set_and_records(client, db, owner):
    tool = _tool(client, owner)
    assert _asset_count(db, owner) == 1
    resp = _sell_tool(client, owner, tool["id"], buyer_name="Joe",
                      sold_on="2026-10-15")
    assert resp.status_code == 200, resp.text
    assert resp.json()["standing"] == "sold"
    # Sold leaves the active set (billing follows), unlike lost.
    assert _asset_count(db, owner) == 0
    sales = client.get("/api/inventory/sales", headers=auth_headers(owner)).json()
    assert len(sales) == 1
    assert sales[0]["buyer_name"] == "Joe"
    assert sales[0]["sale_price"] == "120.00"
    assert sales[0]["item_name"] == "Snap-on ratchet"
    # The item still reads (history kept) and shows sold standing.
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner)).json()
    assert view["standing"] == "sold"


def test_partial_sale_records_portion_and_reduces(client, db, owner):
    tool = _tool(client, owner, quantity=5, purchase_price="20.00")
    resp = _sell_tool(client, owner, tool["id"], quantity_sold=2, sale_price="50.00")
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 3
    assert resp.json()["standing"] == "in_service"
    assert _asset_count(db, owner) == 1  # still active for the rest
    sales = client.get("/api/inventory/sales", headers=auth_headers(owner)).json()
    assert len(sales) == 1
    assert sales[0]["quantity_sold"] == 2
    # Selling more than remains is refused.
    resp = _sell_tool(client, owner, tool["id"], quantity_sold=4, sale_price="1.00")
    assert resp.status_code == 422


def test_undo_full_sale_restores_and_writes_reversal(client, db, owner):
    tool = _tool(client, owner)
    _sell_tool(client, owner, tool["id"])
    sale = client.get("/api/inventory/sales", headers=auth_headers(owner)).json()[0]
    undo = client.post(
        f"/api/inventory/sales/{sale['id']}/undo", headers=auth_headers(owner)
    )
    assert undo.status_code == 201, undo.text
    assert undo.json()["kind"] == "reversal"
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner)).json()
    assert view["standing"] == "in_service"
    assert _asset_count(db, owner) == 1
    rows = client.get("/api/inventory/sales", headers=auth_headers(owner)).json()
    assert len(rows) == 2
    original = [r for r in rows if r["kind"] == "sale"][0]
    assert original["reversed"] is True
    # Totals net out to zero.
    totals = client.get("/api/inventory/sales/totals", headers=auth_headers(owner)).json()
    assert totals["total_sold_value"] == "0"
    assert totals["sale_count"] == 0


def test_undo_is_lifo_per_item(client, owner):
    tool = _tool(client, owner, quantity=5)
    _sell_tool(client, owner, tool["id"], quantity_sold=1, sale_price="10.00")
    _sell_tool(client, owner, tool["id"], quantity_sold=1, sale_price="20.00")
    sales = client.get("/api/inventory/sales", headers=auth_headers(owner)).json()
    older = [s for s in sales if s["sale_price"] == "10.00"][0]
    resp = client.post(
        f"/api/inventory/sales/{older['id']}/undo", headers=auth_headers(owner)
    )
    assert resp.status_code == 422  # newer sale must be undone first
    newer = [s for s in sales if s["sale_price"] == "20.00"][0]
    assert client.post(
        f"/api/inventory/sales/{newer['id']}/undo", headers=auth_headers(owner)
    ).status_code == 201
    view = client.get(f"/api/inventory/{tool['id']}", headers=auth_headers(owner)).json()
    assert view["quantity"] == 4  # one unit restored


def test_checked_out_item_cannot_be_sold(client, db, owner):
    tool = _tool(client, owner)
    # Owner-initiated checkout (borrowing's own flow) puts the
    # item out with a manual borrower.
    resp = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool["id"],
            "borrower_name": "Neighbor Nate",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["state"] == "checked_out"
    resp = _sell_tool(client, owner, tool["id"])
    assert resp.status_code == 422
    assert "checked out" in resp.json()["detail"].lower()


def test_open_claim_blocks_sale(client, owner):
    tool = _tool(
        client, owner, purchase_price="500.00", replacement_cost="500.00"
    )
    claim = client.post("/api/disaster-claims", json={}, headers=auth_headers(owner))
    assert claim.status_code == 201, claim.text
    cid = claim.json()["id"]
    line = client.post(
        f"/api/disaster-claims/{cid}/lines",
        json={"target_kind": "tool", "target_id": tool["id"]},
        headers=auth_headers(owner),
    )
    assert line.status_code in (200, 201), line.text
    filed = client.post(
        f"/api/disaster-claims/{cid}/transition",
        json={"to_status": "filed"},
        headers=auth_headers(owner),
    )
    assert filed.status_code == 200, filed.text
    resp = _sell_tool(client, owner, tool["id"])
    assert resp.status_code == 422
    assert "claim" in resp.json()["detail"].lower()


def test_draft_claim_does_not_block_sale(client, owner):
    """The guard mirrors the claims deletion guard: only OPEN
    claims (filed onward) pin the item — a draft is still just
    the owner's own paperwork."""
    tool = _tool(client, owner, replacement_cost="500.00")
    claim = client.post("/api/disaster-claims", json={}, headers=auth_headers(owner))
    cid = claim.json()["id"]
    client.post(
        f"/api/disaster-claims/{cid}/lines",
        json={"target_kind": "tool", "target_id": tool["id"]},
        headers=auth_headers(owner),
    )
    assert _sell_tool(client, owner, tool["id"]).status_code == 200


def test_piece_sale_and_set_sale(client, owner):
    created = client.post(
        "/api/inventory",
        json={"name": "Master set", "is_set": True},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    tool_set = created.json()
    piece = client.post(
        f"/api/inventory/{tool_set['id']}/pieces",
        json={"kind": "addon", "name": "22mm socket", "price": "45.00"},
        headers=auth_headers(owner),
    )
    assert piece.status_code in (200, 201), piece.text
    piece = piece.json()
    sold = client.post(
        f"/api/inventory/sets/{tool_set['id']}/pieces/{piece['id']}/mark-sold",
        json={"sale_price": "30.00", "buyer_name": "Pat"},
        headers=auth_headers(owner),
    )
    assert sold.status_code == 201, sold.text
    assert sold.json()["item_kind"] == "set_piece"
    view = client.get(f"/api/inventory/{tool_set['id']}", headers=auth_headers(owner)).json()
    statuses = {p["id"]: p["status"] for p in view["set"]["addon_pieces"]}
    assert statuses[piece["id"]] == "sold"
    # Whole-set sale: record on the set tool itself.
    resp = _sell_tool(client, owner, tool_set["id"], sale_price="900.00")
    assert resp.status_code == 200
    assert resp.json()["standing"] == "sold"


def test_sold_never_occupies_an_active_slot_when_enforced(client, db, owner):
    """The active-set pin with enforcement ON: 21 items on the
    20-item free plan — sell the NEWEST and the remaining 20 all
    stay active (the sold one takes no slot). Without the sold
    exclusion the slice would include the sold tool and grey the
    oldest survivor."""
    from app.modules.billing import entitlements

    # Build 22 items with enforcement OFF (the create doorway
    # would refuse past the limit), then flip enforcement on.
    tools = [_tool(client, owner, name=f"Tool {i}") for i in range(22)]
    entitlements.set_setting(db, "entitlements.enforcement_enabled", True)
    db.commit()
    newest = tools[-1]
    resp = _sell_tool(client, owner, newest["id"])
    assert resp.status_code == 200
    active = entitlements.active_tool_ids(db, owner.id)
    assert active is not None and len(active) == 20
    assert uuid.UUID(newest["id"]) not in active
    # Exactly ONE survivor is greyed (the oldest): if the sold
    # tool still took a slot, two survivors would be greyed.
    greyed = [t for t in tools[:-1] if uuid.UUID(t["id"]) not in active]
    assert len(greyed) == 1


def test_bulk_standing_refuses_sold(client, owner):
    tool = _tool(client, owner)
    resp = client.post(
        "/api/inventory/bulk",
        json={"action": "set_standing", "item_ids": [tool["id"]], "standing": "sold"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_history_and_reports_carry_the_sale(client, owner):
    tool = _tool(client, owner)
    _sell_tool(client, owner, tool["id"], buyer_name="Dana", sale_price="75.00")
    history = client.get(
        f"/api/inventory/tools/{tool['id']}/history", headers=auth_headers(owner)
    ).json()
    titles = [e["title"] for e in history["events"]]
    assert any("Sold to Dana" in t and "$75" in t for t in titles), titles
    catalog = client.get("/api/reports/meta", headers=auth_headers(owner)).json()
    keys = {c["key"] for c in catalog["columns"]}
    assert {"sale_price", "sold_on", "buyer"} <= keys
    run = client.post(
        "/api/reports/run",
        json={"columns": ["name", "status", "sale_price", "sold_on", "buyer"]},
        headers=auth_headers(owner),
    )
    assert run.status_code == 200, run.text
    rows = [r for g in run.json()["groups"] for r in g["rows"]]
    row = [r for r in rows if r["values"]["name"] == "Snap-on ratchet"]
    assert row and row[0]["values"]["buyer"] == "Dana"
    assert row[0]["values"]["status"] == "Sold"


def test_poster_pdf(client, owner):
    tool = _tool(client, owner)
    resp = client.post(
        "/api/inventory/sales/poster",
        json={"items": [{"item_kind": "tool", "item_id": tool["id"], "price": "99.00"}]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"%PDF"
    foreign = client.post(
        "/api/inventory/sales/poster",
        json={"items": [{"item_kind": "tool", "item_id": str(uuid.uuid4())}]},
        headers=auth_headers(owner),
    )
    assert foreign.status_code == 422


def test_export_contains_sales_json(client, owner):
    import io
    import json as jsonlib
    import zipfile

    tool = _tool(client, owner)
    _sell_tool(client, owner, tool["id"])
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "sales.json" in archive.namelist()
    rows = jsonlib.loads(archive.read("sales.json"))
    assert len(rows) == 1 and rows[0]["item_name"] == "Snap-on ratchet"
