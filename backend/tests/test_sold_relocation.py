"""Sold relocation + orphaned listings (owner spec 2026-10-25).

Ryan moved the Sold view out of Inventory into Tools For Sale →
My Listings (the section renders the sale ledger — GET
/inventory/sales), and reported a live bug: he deleted a test
tool he had listed for sale and the listing still showed on the
board.

Pins:
- deleting an item (tool or battery, through the service path
  every delete route funnels into) ENDS its active listings in
  the same transaction — status "removed", off the board, out
  of the counts and out of My Listings;
- a SOLD listing is history: deleting its item leaves it sold
  and visible in My Listings (the deal happened);
- a listing orphaned by ANY other path (here: a raw row delete
  that bypasses the cascade) still never displays — board
  (signed-in + public), single-listing reads, the stats count
  and My Listings all exclude it, while its stored row is never
  rewritten;
- a standalone listing is never an orphan and is untouched by
  item deletions;
- the relocated Sold area's data source (GET /inventory/sales)
  returns the whole sold set: items sold through a listing's
  flow AND items sold without ever being listed, with price
  and date.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.marketplace import models as market_models
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
def seller(db):
    return _make_user(db, "TV-M-000901", "reloc-seller@example.com")


def _tool(client, user, **over):
    body = {"name": "Listed Wrench", "quantity": 1}
    body.update(over)
    resp = client.post("/api/inventory", json=body, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **over):
    body = {"name": "Listed Battery", "platform": "M18"}
    body.update(over)
    resp = client.post(
        "/api/inventory/batteries", json=body, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _listing_from(client, user, kind, item_id, **fields):
    payload = {"source_kind": kind, "source_id": str(item_id), "price": "50.00"}
    payload.update(fields)
    resp = client.post(
        "/api/marketplace/listings", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _board(client, user=None):
    headers = auth_headers(user) if user is not None else {}
    resp = client.get("/api/marketplace/board", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _public_board(client):
    resp = client.get("/api/marketplace/public/board")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mine(client, user):
    resp = client.get("/api/marketplace/mine", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stats(client, user):
    resp = client.get("/api/marketplace/stats", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _listing_row(db, listing_id):
    return db.get(market_models.SaleListing, uuid.UUID(listing_id))


# -- the delete cascade -----------------------------------------------------------


def test_delete_tool_ends_its_active_listing(client, db, seller):
    tool = _tool(client, seller)
    listing = _listing_from(client, seller, "tool", tool["id"])
    assert len(_board(client, seller)) == 1
    assert _stats(client, seller)["active_listings_count"] == 1

    resp = client.delete(
        f"/api/inventory/{tool['id']}", headers=auth_headers(seller)
    )
    assert resp.status_code == 204, resp.text

    # Ended in the same transaction: removed, off every surface.
    assert _listing_row(db, listing["id"]).status == "removed"
    assert _board(client, seller) == []
    assert _public_board(client) == []
    assert _stats(client, seller)["active_listings_count"] == 0
    assert _mine(client, seller) == []


def test_delete_battery_ends_its_active_listing(client, db, seller):
    battery = _battery(client, seller)
    listing = _listing_from(client, seller, "battery", battery["id"])
    assert len(_board(client, seller)) == 1

    resp = client.delete(
        f"/api/inventory/batteries/{battery['id']}",
        headers=auth_headers(seller),
    )
    assert resp.status_code == 204, resp.text

    assert _listing_row(db, listing["id"]).status == "removed"
    assert _board(client, seller) == []
    assert _stats(client, seller)["active_listings_count"] == 0


def test_delete_item_leaves_sold_listing_as_history(client, db, seller):
    tool = _tool(client, seller)
    listing = _listing_from(client, seller, "tool", tool["id"])
    sold = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={},
        headers=auth_headers(seller),
    )
    assert sold.status_code == 200, sold.text

    resp = client.delete(
        f"/api/inventory/{tool['id']}", headers=auth_headers(seller)
    )
    assert resp.status_code == 204, resp.text

    # The deal happened: the sold listing stays sold AND stays
    # visible in the owner's My Listings (history, not clutter).
    assert _listing_row(db, listing["id"]).status == "sold"
    mine = _mine(client, seller)
    assert [row["id"] for row in mine] == [listing["id"]]
    assert mine[0]["status"] == "sold"


def test_delete_item_does_not_touch_other_listings(client, db, seller):
    doomed = _tool(client, seller, name="Doomed")
    keeper = _tool(client, seller, name="Keeper")
    _listing_from(client, seller, "tool", doomed["id"], title="Doomed listing")
    _listing_from(client, seller, "tool", keeper["id"], title="Keeper listing")
    standalone = client.post(
        "/api/marketplace/listings",
        json={"title": "Standalone listing"},
        headers=auth_headers(seller),
    )
    assert standalone.status_code == 201, standalone.text

    resp = client.delete(
        f"/api/inventory/{doomed['id']}", headers=auth_headers(seller)
    )
    assert resp.status_code == 204, resp.text

    titles = sorted(row["title"] for row in _board(client, seller))
    assert titles == ["Keeper listing", "Standalone listing"]


# -- orphan read exclusion (the cascade bypassed) ---------------------------------


def test_orphaned_listing_never_displays(client, db, seller):
    tool = _tool(client, seller)
    listing = _listing_from(client, seller, "tool", tool["id"])
    assert len(_board(client, seller)) == 1

    # Bypass the service delete entirely — the orphan class the
    # read layer exists for (Ryan's production listing was one).
    row = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    db.delete(row)
    db.commit()

    assert _board(client, seller) == []
    assert _public_board(client) == []
    assert _stats(client, seller)["active_listings_count"] == 0
    assert _mine(client, seller) == []
    one = client.get(
        f"/api/marketplace/board/{listing['id']}",
        headers=auth_headers(seller),
    )
    assert one.status_code == 404
    # …and the stored row is never rewritten by any of this.
    stored = _listing_row(db, listing["id"])
    assert stored.status == "active"
    assert stored.title == "Listed Wrench"


# -- the relocated Sold area's set ---------------------------------------------------


def test_sales_feed_covers_listed_and_never_listed_sales(client, db, seller):
    """GET /inventory/sales is what the My Listings "Sold items"
    section renders: the whole sold set, whether or not the
    item was ever listed for sale."""
    listed = _tool(client, seller, name="Sold Via Listing Shelf")
    _listing_from(client, seller, "tool", listed["id"])
    never_listed = _tool(client, seller, name="Sold Off The Truck")
    battery = _battery(client, seller, name="Sold Battery")

    for path, body in (
        (f"/api/inventory/tools/{listed['id']}/mark-sold",
         {"sale_price": "80.00", "sold_on": "2026-10-20"}),
        (f"/api/inventory/tools/{never_listed['id']}/mark-sold",
         {"sale_price": "25.50", "sold_on": "2026-10-21"}),
        (f"/api/inventory/batteries/{battery['id']}/mark-sold",
         {"sale_price": "40.00", "sold_on": "2026-10-22"}),
    ):
        resp = client.post(path, json=body, headers=auth_headers(seller))
        assert resp.status_code == 200, resp.text

    resp = client.get("/api/inventory/sales", headers=auth_headers(seller))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    by_name = {row["item_name"]: row for row in rows}
    assert set(by_name) == {
        "Sold Via Listing Shelf",
        "Sold Off The Truck",
        "Sold Battery",
    }
    assert str(by_name["Sold Via Listing Shelf"]["sale_price"]) == "80.00"
    assert by_name["Sold Via Listing Shelf"]["sold_on"] == "2026-10-20"
    assert by_name["Sold Off The Truck"]["sold_on"] == "2026-10-21"
    assert by_name["Sold Battery"]["item_kind"] == "battery"
