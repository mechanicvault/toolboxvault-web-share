"""Dealer intermingling (2026-10-25) — the dealer triangle.

Ryan's rule: if one thing affects another, you can see the
affected thing wherever it affects. This round wires Dealer ↔
Tools ↔ Claims in every direction:

  - Inventory: a Dealer filter (the item's dealer TAG — the one
    canonical link — exact company match, composing with the
    other filters) and Dealer as a sort key (by company name;
    untagged items trail);
  - the claims list summary names the dealers each claim touches
    (through its lines' items' LIVE tags), which is what the
    list's dealer filter/sort reads;
  - the company page's own-records payload: the viewer's items
    from the dealer, honest stats (recorded purchase totals only,
    never estimated), and their claims for the dealer split
    current/history — present only when the claims module is
    effective for the viewer;
  - the item page's claims endpoint: an item's claims split
    current/history, piece lines resolving through their set.

Attribution doctrine (asserted below): claim lines snapshot
names/values but never the dealer, so dealer attribution reads
the item's CURRENT tag — re-tagging moves the claims, deleting
the item strands them (they attribute to no dealer).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

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
    return _make_user(db, "TV-M-000601", "triangle@example.com", [MECHANIC], "Tess Triangle")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000602", "triangle-other@example.com", [MECHANIC], "Otto Other")


@pytest.fixture()
def dealer_user(db):
    # Dealer-group only: dealers module on (core for all groups),
    # claims module off (mechanic/shop only) — the gate probe.
    return _make_user(db, "TV-D-000603", "triangle-dealer@example.com", [DEALER], "Dan Dealer")


def _company(db, name, *, owner_id=None, is_directory=False):
    company = dealer_models.DealerCompany(
        name=name, owner_id=owner_id, is_directory=is_directory
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


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


def _claim_with_line(client, user, target_kind, target_id, **line_kwargs):
    # Separation (2026-11-04): a claim built by hand with lines
    # is a DISASTER claim now — multi-line filing lives in the
    # disaster section. Dealer attribution reads the lines the
    # same way for either kind, so these helpers file disaster
    # claims and the attribution tests read the disaster list.
    response = client.post("/api/disaster-claims", json={}, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    claim = response.json()
    payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "value_basis": "entered",
        "amount": "10.00",
    }
    payload.update(line_kwargs)
    response = client.post(
        f"/api/disaster-claims/{claim['id']}/lines",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return claim


def _transition(client, user, claim_id, to_status):
    response = client.post(
        f"/api/disaster-claims/{claim_id}/transition",
        json={"to_status": to_status},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _warranty_claim(client, user, target_kind, target_id):
    # The item page's claims endpoint is WARRANTY-only since the
    # separation, so its tests file through the warranty flow:
    # one item per claim, born `not_reported`.
    response = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": target_kind,
            "target_id": str(target_id),
            "dealer_notified": False,
            "problem": "Stopped working",
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()["claim"]


def _warranty_transition(client, user, claim_id, to_status):
    response = client.post(
        f"/api/claims/{claim_id}/transition",
        json={"to_status": to_status},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- Inventory: dealer filter + sort ------------------------------------------


def test_inventory_dealer_filter_isolates_the_tag(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    local = _company(db, "Local Co", owner_id=owner.id)
    _tool(db, owner, "Matco wrench", dealer_company_id=matco.id)
    _battery(db, owner, "Matco pack", dealer_company_id=matco.id)
    _tool(db, owner, "Local wrench", dealer_company_id=local.id)
    _tool(db, owner, "Untagged wrench")

    response = client.get(
        f"/api/inventory/search/all?dealer_id={matco.id}",
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    names = {row["name"] for row in response.json()}
    assert names == {"Matco wrench", "Matco pack"}
    assert response.headers["X-Total-Count"] == "2"

    # The tools-only search honors it too.
    response = client.get(
        f"/api/inventory/search?dealer_id={local.id}",
        headers=auth_headers(owner),
    )
    assert [row["name"] for row in response.json()] == ["Local wrench"]

    # Composes with the category filter.
    response = client.get(
        f"/api/inventory/search/all?dealer_id={matco.id}&category=Nope",
        headers=auth_headers(owner),
    )
    assert response.json() == []


def test_inventory_dealer_sort_orders_by_company_name(client, db, owner):
    zebra = _company(db, "Zebra Tools", is_directory=True)
    acme = _company(db, "Acme Supply", is_directory=True)
    _tool(db, owner, "From zebra", dealer_company_id=zebra.id)
    _tool(db, owner, "From acme", dealer_company_id=acme.id)
    _battery(db, owner, "Acme pack", dealer_company_id=acme.id)
    _tool(db, owner, "No dealer")

    response = client.get(
        "/api/inventory/search/all?sort=dealer&sort_dir=asc",
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    names = [row["name"] for row in response.json()]
    # Acme's two items first (either order between them), then
    # Zebra's, and the untagged item trails — the sort convention.
    assert set(names[:2]) == {"From acme", "Acme pack"}
    assert names[2] == "From zebra"
    assert names[3] == "No dealer"

    # Reversed: dealer names run Z→A and the untagged item STILL
    # trails (missing values trail whichever direction runs).
    response = client.get(
        "/api/inventory/search/all?sort=dealer&sort_dir=desc",
        headers=auth_headers(owner),
    )
    names = [row["name"] for row in response.json()]
    assert names[0] == "From zebra"
    assert set(names[1:3]) == {"From acme", "Acme pack"}
    assert names[3] == "No dealer"


# -- Claims list: dealer attribution -------------------------------------------


def test_claim_summary_names_its_dealers(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    tool = _tool(db, owner, dealer_company_id=matco.id)
    claim = _claim_with_line(client, owner, "tool", tool.id)
    plain = _tool(db, owner, "Plain tool")
    _claim_with_line(client, owner, "tool", plain.id)

    summaries = client.get("/api/disaster-claims", headers=auth_headers(owner)).json()
    by_id = {row["id"]: row for row in summaries}
    assert by_id[claim["id"]]["dealers"] == [{"id": str(matco.id), "name": "Matco"}]
    # The other claim (untagged item) attributes nowhere.
    others = [row for row in summaries if row["id"] != claim["id"]]
    assert others[0]["dealers"] == []


def test_claim_attribution_follows_the_live_tag(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    acme = _company(db, "Acme", is_directory=True)
    tool = _tool(db, owner, dealer_company_id=matco.id)
    claim = _claim_with_line(client, owner, "tool", tool.id)

    # Re-tag the item and the claim's dealer moves with it — the
    # line holds no dealer snapshot, by design.
    tool.dealer_company_id = acme.id
    db.commit()
    summaries = client.get("/api/disaster-claims", headers=auth_headers(owner)).json()
    assert summaries[0]["dealers"] == [{"id": str(acme.id), "name": "Acme"}]

    # Delete the item outright and the claim attributes nowhere —
    # the line itself (and its snapshot) survives untouched.
    db.delete(tool)
    db.commit()
    summaries = client.get("/api/disaster-claims", headers=auth_headers(owner)).json()
    assert summaries[0]["dealers"] == []
    assert summaries[0]["line_count"] == 1


def test_piece_line_attributes_through_its_set(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    socket_set = _tool(
        db, owner, "Socket set", is_set=True, dealer_company_id=matco.id
    )
    piece = inventory_models.SetPiece(
        owner_id=owner.id, set_id=socket_set.id, name="10mm socket"
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    claim = _claim_with_line(client, owner, "piece", piece.id)

    summaries = client.get("/api/disaster-claims", headers=auth_headers(owner)).json()
    assert summaries[0]["dealers"] == [{"id": str(matco.id), "name": "Matco"}]
    assert summaries[0]["id"] == claim["id"]


# -- Company page: my records ---------------------------------------------------


def test_company_my_records_items_stats_and_claims(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    wrench = _tool(
        db,
        owner,
        "Matco wrench",
        dealer_company_id=matco.id,
        purchase_price=Decimal("100.00"),
        quantity=2,
        replacement_cost=Decimal("120.00"),
        purchase_date=date(2026, 1, 15),
    )
    _battery(
        db,
        owner,
        "Matco pack",
        dealer_company_id=matco.id,
        purchase_price=Decimal("50.00"),
        purchase_date=date(2026, 3, 1),
    )
    socket_set = _tool(
        db,
        owner,
        "Matco set",
        is_set=True,
        dealer_company_id=matco.id,
        purchase_price=Decimal("300.00"),
    )
    _tool(db, owner, "Someone else's brand", dealer_company_id=None)

    claim = _claim_with_line(client, owner, "tool", wrench.id)
    _transition(client, owner, claim["id"], "filed")

    response = client.get(
        f"/api/dealers/companies/{matco.id}/my-records",
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    names = {row["name"] for row in body["items"]}
    assert names == {"Matco wrench", "Matco pack", "Matco set"}
    stats = body["stats"]
    assert stats["items_count"] == 3
    # 100x2 (wrench) + 50 (pack) + 300 (set's own price) = 550.
    assert Decimal(stats["total_spent"]) == Decimal("550.00")
    # Only the wrench carries a replacement cost: 120 x 2.
    assert Decimal(stats["replacement_value"]) == Decimal("240.00")
    assert stats["last_purchase_date"] == "2026-03-01"
    assert stats["open_claims"] == 1
    assert stats["total_claims"] == 1

    current = body["claims"]["current"]
    assert [row["claim_number"] for row in current] == [claim["claim_number"]]
    assert current[0]["items"] == ["Matco wrench"]
    # Separation judgment call: the dealer page is a factual
    # record surface (dealers API), so it carries EITHER kind —
    # and each ref names its kind so the page can link the row
    # into the claim's OWN section.
    assert current[0]["kind"] == "insurance_disaster"
    # Dealer page pass (2026-11-06): the claim rows carry the
    # dates their date + last-update columns render.
    assert "reported_at" in current[0]
    assert current[0]["updated_at"] is not None
    assert body["claims"]["history"] == []

    # Close the claim and it moves to history on the dealer page.
    _transition(client, owner, claim["id"], "closed")
    body = client.get(
        f"/api/dealers/companies/{matco.id}/my-records",
        headers=auth_headers(owner),
    ).json()
    assert body["claims"]["current"] == []
    assert [row["id"] for row in body["claims"]["history"]] == [claim["id"]]
    assert body["stats"]["open_claims"] == 0
    assert body["stats"]["total_claims"] == 1


def test_company_my_records_empty_dealer_is_clean(client, db, owner):
    empty = _company(db, "Nothing Bought Co", is_directory=True)
    response = client.get(
        f"/api/dealers/companies/{empty.id}/my-records",
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["stats"]["items_count"] == 0
    assert Decimal(body["stats"]["total_spent"]) == Decimal("0.00")
    # No item carries a replacement value: null, never a fake $0.
    assert body["stats"]["replacement_value"] is None
    assert body["stats"]["last_purchase_date"] is None
    assert body["claims"] == {"current": [], "history": []}


def test_company_my_records_privacy_and_claims_gate(client, db, owner, other, dealer_user):
    theirs = _company(db, "Theirs", owner_id=other.id)
    # Another user's private company: a plain 404 (existence
    # never leaks), exactly like the company page itself.
    response = client.get(
        f"/api/dealers/companies/{theirs.id}/my-records",
        headers=auth_headers(owner),
    )
    assert response.status_code == 404

    # A dealer-group account (claims module off for them, dealers
    # module on) DOES get the claims block: the two-seat gate
    # (C-13, Deep Audit Round 2) rides the block when EITHER module
    # is effective, mirroring the claim pages. The block is scoped
    # to the viewer's own claims, so this viewer — who has none
    # touching this company — sees empty lists and real zero
    # counts, not a silent null. (Pre-C-13 this asserted
    # claims is None; that gate was the defect C-13 fixed.)
    directory = _company(db, "Directory Co", is_directory=True)
    response = client.get(
        f"/api/dealers/companies/{directory.id}/my-records",
        headers=auth_headers(dealer_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claims"] == {"current": [], "history": []}
    assert body["stats"]["open_claims"] == 0
    assert body["stats"]["total_claims"] == 0


def test_set_spend_includes_priced_addons(client, db, owner):
    matco = _company(db, "Matco", is_directory=True)
    socket_set = _tool(
        db,
        owner,
        "Matco set",
        is_set=True,
        dealer_company_id=matco.id,
        purchase_price=Decimal("300.00"),
    )
    addon = inventory_models.SetPiece(
        owner_id=owner.id,
        set_id=socket_set.id,
        name="Extra socket",
        kind="addon",
        price=Decimal("25.00"),
    )
    db.add(addon)
    db.commit()

    body = client.get(
        f"/api/dealers/companies/{matco.id}/my-records",
        headers=auth_headers(owner),
    ).json()
    assert Decimal(body["stats"]["total_spent"]) == Decimal("325.00")
    row = body["items"][0]
    assert Decimal(row["spent"]) == Decimal("325.00")
    assert row["is_set"] is True


# -- Item page: claims for item ---------------------------------------------------


def test_claims_for_item_current_then_history(client, db, owner):
    # Separation: the item page's claims endpoint serves WARRANTY
    # claims only, so this files through the warranty flow. A
    # warranty claim is current from birth (not_reported) until
    # it reaches a warranty terminal (completed / closed).
    tool = _tool(db, owner, "Claimed wrench")
    battery = _battery(db, owner, "Claimed pack")
    claim = _warranty_claim(client, owner, "tool", tool.id)
    _warranty_claim(client, owner, "battery", battery.id)

    response = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["id"] for row in body["current"]] == [claim["id"]]
    assert body["current"][0]["items"] == ["Claimed wrench"]
    assert body["history"] == []

    # The battery's claim (not yet reported) is its own current list.
    body = client.get(
        f"/api/claims/for-item/battery/{battery.id}", headers=auth_headers(owner)
    ).json()
    assert len(body["current"]) == 1
    assert body["current"][0]["status"] == "not_reported"

    # Walk the warranty ladder to completed — a terminal — and
    # the claim moves to the item's history.
    _warranty_transition(client, owner, claim["id"], "reported")
    _warranty_transition(client, owner, claim["id"], "in_repair")
    _warranty_transition(client, owner, claim["id"], "completed")
    body = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    assert body["current"] == []
    assert [row["id"] for row in body["history"]] == [claim["id"]]


def test_claims_for_item_via_set_piece_line(client, db, owner):
    socket_set = _tool(db, owner, "Socket set", is_set=True)
    piece = inventory_models.SetPiece(
        owner_id=owner.id, set_id=socket_set.id, name="10mm socket"
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    claim = _warranty_claim(client, owner, "piece", piece.id)

    body = client.get(
        f"/api/claims/for-item/tool/{socket_set.id}", headers=auth_headers(owner)
    ).json()
    assert [row["id"] for row in body["current"]] == [claim["id"]]


def test_claims_for_item_privacy_and_gating(client, db, owner, other, dealer_user):
    tool = _tool(db, owner)
    # Another owner's item id: 404, never a leak.
    response = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(other)
    )
    assert response.status_code == 404
    # A bad kind is a 404 too.
    response = client.get(
        f"/api/claims/for-item/widget/{tool.id}", headers=auth_headers(owner)
    )
    assert response.status_code == 404
    # Claims module off for dealer-group accounts: 403.
    response = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(dealer_user)
    )
    assert response.status_code == 403
