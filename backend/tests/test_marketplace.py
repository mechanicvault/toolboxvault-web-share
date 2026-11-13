"""Tools For Sale + reputation (2026-10-19, community suite
build 2).

Pins:
- the board payload's EXACT keys, signed-in AND anonymous: only
  what the seller put on the listing — no email, no serial, no
  inventory notes/prices behind a from-inventory listing, phone
  only on opt-in (listing override > profile toggle > hidden);
- the publish gate (the suite's paid-contribution rule): bites
  only while enforcement is ON, paid sources only, TRIAL
  excluded — checked at create, at edits of active listings, at
  reactivation, and again at read time (a lapsed seller stops
  listing);
- the listing SNAPSHOT: create-from-inventory copies display
  facts; later inventory edits/deletes never rewrite the
  listing's DATA — but deleting the item ends its active
  listings and an orphan never displays (owner spec
  2026-10-25; test_sold_relocation.py pins it);
- mark-sold with an identified buyer creates the rateable
  interaction; buyer from thread participants or by exact
  account number;
- DOUBLE-BLIND ratings: one per side per interaction; a lone
  rating is invisible EVERYWHERE (profile aggregate, public
  reviews, the other side's view) until the pair completes; both
  submitting publishes both together; 14 days after the deal a
  lone rating publishes alone (lazy read + jobs sweep);
- anchored-thread completion: BOTH sides closing an anchored
  thread creates the interaction; one side alone doesn't;
  unanchored threads can't;
- messaging anchors validate "listing" exactly like "part";
- the spam trust tiers read REAL completed deals now;
- the kill switch 404s the board (signed-in + anonymous);
- listings journal as restorable entities; the export carries
  marketplace data; account deletion removes listings but keeps
  the other side's aggregates honest (stars stay, name becomes
  "Former member").
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.core import journal
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.marketplace import models as market_models
from app.modules.marketplace import reputation
from app.modules.messaging import spam
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"

LISTING_KEYS = {
    "id",
    "title",
    "description",
    "listing_type",
    "price",
    "condition",
    "brand",
    "model",
    "delivery_local_pickup",
    "delivery_ships",
    "area_label",
    "photos",
    "seller_id",
    "seller_name",
    "seller_member_since",
    "seller_reputation",
    "seller_currency",
    "phone",
    "created_at",
    "updated_at",
}


def _make_user(db, account_number, email, account_types, *, name="Market User"):
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
def seller(db):
    return _make_user(
        db, "TV-M-000601", "mseller@example.com", [MECHANIC], name="Marta Mechanic"
    )


@pytest.fixture()
def buyer(db):
    return _make_user(
        db, "TV-S-000602", "mbuyer@example.com", [SHOP], name="Bob Buyer"
    )


@pytest.fixture()
def third(db):
    return _make_user(
        db, "TV-D-000603", "mthird@example.com", [DEALER], name="Dee Dealer"
    )


def _listing(client, user, **fields):
    payload = {"title": fields.pop("title", "Snap-on ratchet")}
    payload.update(fields)
    response = client.post(
        "/api/marketplace/listings", json=payload, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _board(client, user=None, **params):
    headers = auth_headers(user) if user is not None else {}
    response = client.get("/api/marketplace/board", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _public_board(client, **params):
    response = client.get("/api/marketplace/public/board", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _pay(db, user, *, status="active"):
    sub = billing_models.Subscription(
        user_id=user.id, plan_key="pro", status=status, source="stripe"
    )
    db.add(sub)
    db.commit()
    return sub


def _enforce(db, on=True):
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, on)


def _tool(db, owner, **fields):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=fields.pop("name", "Secret Wrench"),
        brand=fields.pop("brand", "Snap-on"),
        model=fields.pop("model", "S80"),
        serial_number=fields.pop("serial_number", "SN-12345-PRIVATE"),
        notes=fields.pop("notes", "bought from Dave, owes me a favor"),
        purchase_price=fields.pop("purchase_price", None),
        **fields,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _sold_pair(client, seller, buyer, **fields):
    """A listing sold to buyer -> returns (listing, interaction view for seller)."""
    listing = _listing(client, seller, **fields)
    response = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_account_number": buyer.account_number},
        headers=auth_headers(seller),
    )
    assert response.status_code == 200, response.text
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()
    view = next(row for row in mine if row["listing_id"] == listing["id"])
    return response.json(), view


def _rate(client, user, interaction_id, stars, text=""):
    return client.post(
        f"/api/marketplace/interactions/{interaction_id}/rating",
        json={"stars": stars, "text": text},
        headers=auth_headers(user),
    )


def _profile(client, user_id):
    response = client.get(f"/api/messaging/profiles/{user_id}")
    assert response.status_code == 200, response.text
    return response.json()


# -- payload contract + board -----------------------------------------------


def test_board_payload_exact_keys_and_phone_opt_in(client, db, seller, buyer):
    seller.contact_phone = "555-0100"
    db.commit()
    listing = _listing(
        client, seller, title="Mac impact", price="120.00", condition="Good used"
    )
    # Phone hidden by default (profile toggle OFF, no override).
    for rows in (_board(client, buyer), _public_board(client)):
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == LISTING_KEYS
        assert row["id"] == listing["id"]
        assert row["phone"] is None
        assert row["price"] == "120.00"
        assert row["seller_reputation"] == {
            "average": None,
            "count": 0,
            "completed_deals": 0,
        }
        assert "email" not in str(row).lower()
    # Profile toggle ON shows it; a listing override OFF hides it
    # again (the pool's resolution chain).
    seller.show_phone = True
    db.commit()
    assert _public_board(client)[0]["phone"] == "555-0100"
    client.put(
        f"/api/marketplace/listings/{listing['id']}",
        json={"show_phone_override": False},
        headers=auth_headers(seller),
    )
    assert _public_board(client)[0]["phone"] is None


def test_board_filters_and_rating_sort(client, db, seller, buyer, third):
    cheap = _listing(client, seller, title="Cheap wrench", price="10.00")
    _listing(client, seller, title="Pricey wrench", price="900.00")
    _listing(client, buyer, title="Wanted: torque wrench", listing_type="wanted")
    _listing(client, third, title="Dealer special", price="50.00", area_label=None)
    # Give the dealer a published 5-star reputation (asymmetric
    # on purpose: the return rating gives the buyer a 2, so the
    # rating sort has exactly one leader).
    sold, interaction = _sold_pair(client, third, buyer, title="Rated deal")
    assert _rate(client, buyer, interaction["id"], 5, "great").status_code == 201
    assert _rate(client, third, interaction["id"], 2, "slow").status_code == 201

    titles = {row["title"] for row in _board(client, seller)}
    assert titles == {
        "Cheap wrench",
        "Pricey wrench",
        "Wanted: torque wrench",
        "Dealer special",
    }
    assert [r["title"] for r in _board(client, seller, listing_type="wanted")] == [
        "Wanted: torque wrench"
    ]
    pricey = _board(client, seller, price_min=100)
    assert [r["title"] for r in pricey] == ["Pricey wrench"]
    by_rating = _board(client, seller, sort="rating")
    assert by_rating[0]["seller_id"] == str(third.id)
    assert by_rating[0]["seller_reputation"]["average"] == 5.0
    by_price = _board(client, seller, sort="price_asc")
    assert by_price[0]["title"] == "Cheap wrench"
    q = _board(client, seller, q="torque")
    assert [r["title"] for r in q] == ["Wanted: torque wrench"]


def test_area_resolution_and_filter(client, db, seller, buyer):
    seller.public_area_label = "Little Falls, MN"
    db.commit()
    _listing(client, seller, title="Area tool")
    _listing(
        client, seller, title="Override tool", public_area_label="St. Cloud, MN"
    )
    rows = {r["title"]: r for r in _public_board(client)}
    assert rows["Area tool"]["area_label"] == "Little Falls, MN"
    assert rows["Override tool"]["area_label"] == "St. Cloud, MN"
    assert [r["title"] for r in _public_board(client, area="cloud")] == [
        "Override tool"
    ]


def test_kill_switch_hides_board(client, db, seller, buyer):
    _listing(client, seller)
    entitlements.set_setting(db, "community.marketplace_enabled", False)
    assert client.get("/api/marketplace/board", headers=auth_headers(buyer)).status_code == 404
    assert client.get("/api/marketplace/public/board").status_code == 404
    # The owner's own surfaces keep working.
    mine = client.get("/api/marketplace/mine", headers=auth_headers(seller))
    assert mine.status_code == 200 and len(mine.json()) == 1


def test_sold_and_removed_leave_the_board(client, seller, buyer):
    listing = _listing(client, seller)
    client.post(
        f"/api/marketplace/listings/{listing['id']}/remove",
        headers=auth_headers(seller),
    )
    assert _public_board(client) == []
    client.post(
        f"/api/marketplace/listings/{listing['id']}/reactivate",
        headers=auth_headers(seller),
    )
    assert len(_public_board(client)) == 1
    client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={},
        headers=auth_headers(seller),
    )
    assert _public_board(client) == []
    # Sold with NO buyer: no interaction is created.
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()
    assert mine == []


def test_stats_counts_only_my_active_listings(client, seller, buyer):
    # Phase 3 panel stat: active listings only, owner-scoped.
    first = _listing(client, seller)
    _listing(client, seller, title="Second listing")
    _listing(client, buyer, title="Not mine")
    stats = client.get("/api/marketplace/stats", headers=auth_headers(seller)).json()
    assert stats == {"active_listings_count": 2}
    client.post(
        f"/api/marketplace/listings/{first['id']}/sold",
        json={},
        headers=auth_headers(seller),
    )
    stats = client.get("/api/marketplace/stats", headers=auth_headers(seller)).json()
    assert stats == {"active_listings_count": 1}


# -- the publish gate ----------------------------------------------------------


def test_gate_open_while_enforcement_off(client, seller, buyer):
    _listing(client, seller)
    assert len(_public_board(client)) == 1


def test_gate_blocks_free_and_trial_when_enforced(client, db, seller, buyer):
    _enforce(db)
    refused = client.post(
        "/api/marketplace/listings",
        json={"title": "Gated"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "paid_plan_required"
    _pay(db, seller, status="trialing")
    refused = client.post(
        "/api/marketplace/listings",
        json={"title": "Trial gated"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403


def test_gate_admits_paid_and_read_time_lapse(client, db, seller, buyer):
    _pay(db, seller)
    _enforce(db)
    listing = _listing(client, seller, title="Paid listing")
    assert len(_public_board(client)) == 1
    # The plan lapses (subscription deleted): reads stop listing
    # it, edits of the active listing are refused, and the anchor
    # resolver stops resolving it.
    sub = db.scalars(select(billing_models.Subscription)).first()
    db.delete(sub)
    db.commit()
    assert _public_board(client) == []
    refused = client.put(
        f"/api/marketplace/listings/{listing['id']}",
        json={"title": "Still public edit"},
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403
    # Removing it from the board always works (bookkeeping).
    removed = client.post(
        f"/api/marketplace/listings/{listing['id']}/remove",
        headers=auth_headers(seller),
    )
    assert removed.status_code == 200
    # Reactivating is publishing again — refused while unpaid.
    refused = client.post(
        f"/api/marketplace/listings/{listing['id']}/reactivate",
        headers=auth_headers(seller),
    )
    assert refused.status_code == 403


# -- the inventory snapshot ------------------------------------------------------


def test_create_from_inventory_snapshots_and_never_leaks(client, db, seller, buyer):
    tool = _tool(db, seller)
    response = client.post(
        "/api/marketplace/listings",
        json={"source_kind": "tool", "source_id": str(tool.id), "price": "75.00"},
        headers=auth_headers(seller),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["title"] == "Secret Wrench"
    assert created["brand"] == "Snap-on"
    assert created["model"] == "S80"
    assert created["source_kind"] == "tool"
    # The board payload shows ONLY listing data: no serial, no
    # notes, no purchase price — those keys/values don't exist.
    row = _public_board(client)[0]
    assert set(row) == LISTING_KEYS
    blob = str(row)
    assert "SN-12345-PRIVATE" not in blob
    assert "owes me a favor" not in blob
    # Later inventory edits do NOT rewrite the listing…
    tool.name = "Renamed In Inventory"
    tool.brand = "OtherBrand"
    db.commit()
    assert _public_board(client)[0]["title"] == "Secret Wrench"
    # …and deleting the item doesn't rewrite it either: the
    # snapshot row keeps its facts (the raw owner list below).
    # But since the owner spec of 2026-10-25 an orphaned listing
    # stops DISPLAYING — this raw delete bypassed the delete
    # cascade, and the board's orphan exclusion still hides it.
    db.delete(tool)
    db.commit()
    assert _public_board(client) == []
    from app.modules.marketplace import service as market_service

    raw = market_service.list_mine(db, seller.id)
    assert len(raw) == 1 and raw[0].title == "Secret Wrench"


def test_create_from_foreign_or_missing_item_refused(client, db, seller, buyer):
    tool = _tool(db, buyer)  # belongs to the buyer, not the seller
    response = client.post(
        "/api/marketplace/listings",
        json={"source_kind": "tool", "source_id": str(tool.id)},
        headers=auth_headers(seller),
    )
    assert response.status_code == 422
    assert _public_board(client) == []


# -- mark sold + interactions ------------------------------------------------------


def test_mark_sold_by_account_number_creates_interaction(client, seller, buyer):
    _sold, view = _sold_pair(client, seller, buyer)
    assert view["other_user_id"] == str(buyer.id)
    assert view["source"] == "listing"
    assert view["context_title"] == "Snap-on ratchet"
    assert view["my_rating"] is None
    listing = client.get("/api/marketplace/mine", headers=auth_headers(seller)).json()[0]
    assert listing["status"] == "sold"
    assert listing["buyer_id"] == str(buyer.id)


def test_mark_sold_rejects_self_and_unknown_buyer(client, seller, buyer):
    listing = _listing(client, seller)
    response = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_account_number": seller.account_number},
        headers=auth_headers(seller),
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_account_number": "TV-X-999999"},
        headers=auth_headers(seller),
    )
    assert response.status_code == 422


# -- double-blind ratings ----------------------------------------------------------


def test_one_sided_rating_is_invisible_until_pair_completes(client, seller, buyer):
    _sold, view = _sold_pair(client, seller, buyer)
    interaction_id = view["id"]
    response = _rate(client, buyer, interaction_id, 2, "slow to meet up")
    assert response.status_code == 201
    # The buyer's own view shows their rating, unpublished.
    assert response.json()["my_rating"]["published"] is False
    # The SELLER's side: the rating does not exist for them — no
    # stars, no text, and the aggregate is still honest zeros.
    seller_view = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()[0]
    assert seller_view["their_rating"] is None
    assert _profile(client, seller.id)["reputation"] == {
        "average": None,
        "count": 0,
        "completed_deals": 1,
    }
    public = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert public["ratings"] == []
    assert public["summary"]["count"] == 0
    # The second side submits: BOTH publish together.
    response = _rate(client, seller, interaction_id, 5, "great buyer")
    assert response.status_code == 201
    assert response.json()["my_rating"]["published"] is True
    assert response.json()["their_rating"]["stars"] == 2
    seller_rep = _profile(client, seller.id)["reputation"]
    assert seller_rep == {"average": 2.0, "count": 1, "completed_deals": 1}
    buyer_rep = _profile(client, buyer.id)["reputation"]
    assert buyer_rep == {"average": 5.0, "count": 1, "completed_deals": 1}
    public = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert len(public["ratings"]) == 1
    assert public["ratings"][0]["rater_name"] == "Bob Buyer"
    assert public["ratings"][0]["text"] == "slow to meet up"


def test_one_rating_per_side_and_participants_only(client, seller, buyer, third):
    _sold, view = _sold_pair(client, seller, buyer)
    interaction_id = view["id"]
    assert _rate(client, buyer, interaction_id, 4).status_code == 201
    assert _rate(client, buyer, interaction_id, 1).status_code == 422
    outsider = _rate(client, third, interaction_id, 1)
    assert outsider.status_code == 404


def test_lone_rating_publishes_after_14_days(client, db, seller, buyer):
    _sold, view = _sold_pair(client, seller, buyer)
    interaction_id = view["id"]
    assert _rate(client, buyer, interaction_id, 3, "fine").status_code == 201
    assert _profile(client, seller.id)["reputation"]["count"] == 0
    # 13 days on: still blind (the lazy read must NOT publish).
    interaction = db.get(market_models.DealInteraction, uuid.UUID(interaction_id))
    interaction.completed_at = datetime.now(timezone.utc) - timedelta(days=13)
    db.commit()
    assert _profile(client, seller.id)["reputation"]["count"] == 0
    # Day 15: the lone rating publishes — via the jobs sweep…
    interaction.completed_at = datetime.now(timezone.utc) - timedelta(days=15)
    db.commit()
    assert reputation.publish_due(db) == 1
    rep = _profile(client, seller.id)["reputation"]
    assert rep == {"average": 3.0, "count": 1, "completed_deals": 1}
    # …and the sweep is idempotent.
    assert reputation.publish_due(db) == 0


# -- thread completion ---------------------------------------------------------------


def _anchored_thread(client, buyer, seller, listing_id, body="Still available?"):
    response = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(seller.id),
            "body": body,
            "anchor_type": "listing",
            "anchor_id": str(listing_id),
        },
        headers=auth_headers(buyer),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_listing_anchor_validates_like_part(client, seller, buyer, third):
    listing = _listing(client, seller, title="Anchor wrench")
    thread = _anchored_thread(client, buyer, seller, listing["id"])
    assert thread["anchor_type"] == "listing"
    assert thread["anchor_title"] == "Anchor wrench"
    # Anchored to the listing but addressed to someone else: 422.
    response = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(third.id),
            "body": "wrong seller",
            "anchor_type": "listing",
            "anchor_id": listing["id"],
        },
        headers=auth_headers(buyer),
    )
    assert response.status_code == 422
    # A removed listing can't anchor: 404.
    client.post(
        f"/api/marketplace/listings/{listing['id']}/remove",
        headers=auth_headers(seller),
    )
    response = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(seller.id),
            "body": "about a removed listing",
            "anchor_type": "listing",
            "anchor_id": listing["id"],
        },
        headers=auth_headers(third),
    )
    assert response.status_code == 404


def test_both_sides_close_thread_creates_interaction(client, seller, buyer):
    listing = _listing(client, seller, title="Thread deal wrench")
    thread = _anchored_thread(client, buyer, seller, listing["id"])
    # Buyer closes: nothing rateable yet.
    state = client.post(
        f"/api/marketplace/threads/{thread['id']}/complete",
        headers=auth_headers(buyer),
    ).json()
    assert state["i_closed"] is True and state["interaction_id"] is None
    assert (
        client.get(
            "/api/marketplace/interactions/mine", headers=auth_headers(buyer)
        ).json()
        == []
    )
    # Seller closes: the interaction exists for both.
    state = client.post(
        f"/api/marketplace/threads/{thread['id']}/complete",
        headers=auth_headers(seller),
    ).json()
    assert state["interaction_id"] is not None
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()
    assert len(mine) == 1
    assert mine[0]["source"] == "listing"
    assert mine[0]["context_title"] == "Thread deal wrench"
    # Double-close is harmless (dedupe).
    client.post(
        f"/api/marketplace/threads/{thread['id']}/complete",
        headers=auth_headers(seller),
    )
    assert (
        len(
            client.get(
                "/api/marketplace/interactions/mine", headers=auth_headers(seller)
            ).json()
        )
        == 1
    )


def test_unanchored_thread_cannot_complete(client, seller, buyer):
    response = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(seller.id), "body": "hello"},
        headers=auth_headers(buyer),
    )
    thread = response.json()
    refused = client.post(
        f"/api/marketplace/threads/{thread['id']}/complete",
        headers=auth_headers(buyer),
    )
    assert refused.status_code == 422


def test_buyer_candidates_come_from_anchored_threads(client, seller, buyer, third):
    listing = _listing(client, seller, title="Candidate wrench")
    _anchored_thread(client, buyer, seller, listing["id"])
    response = client.get(
        f"/api/marketplace/listings/{listing['id']}/buyer-candidates",
        headers=auth_headers(seller),
    )
    assert response.status_code == 200
    assert response.json() == [{"user_id": str(buyer.id), "name": "Bob Buyer"}]
    # Marking sold with a picked candidate works.
    sold = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_user_id": str(buyer.id)},
        headers=auth_headers(seller),
    )
    assert sold.status_code == 200
    assert sold.json()["buyer_id"] == str(buyer.id)


# -- spam trust tiers read real deals ---------------------------------------------------


def test_completed_deals_lift_spam_trust_tier(client, db, seller, buyer):
    # Brand-new free account: base tier 0 today.
    assert spam.trust_tier(db, seller) == 0
    assert spam.completed_interactions(db, seller.id) == 0
    for i in range(5):
        _sold_pair(client, seller, buyer, title=f"Deal {i}")
    assert spam.completed_interactions(db, seller.id) == 5
    # 5+ completed deals lifts even a brand-new free account to 2.
    assert spam.trust_tier(db, seller) == 2


# -- journal / export / deletion ---------------------------------------------------------


def test_listing_is_journaled_restorable_entity(client, db, seller):
    listing = _listing(client, seller, title="Journaled wrench")
    entries = list(
        db.scalars(
            select(journal.models.ChangeJournal).where(
                journal.models.ChangeJournal.entity_type == "sale_listing",
                journal.models.ChangeJournal.entity_id == uuid.UUID(listing["id"]),
            )
        ).all()
    )
    assert entries and entries[0].action == "create"
    assert client.delete(
        f"/api/marketplace/listings/{listing['id']}",
        headers=auth_headers(seller),
    ).status_code == 204
    actions = {
        row.action
        for row in db.scalars(
            select(journal.models.ChangeJournal).where(
                journal.models.ChangeJournal.entity_type == "sale_listing",
                journal.models.ChangeJournal.entity_id == uuid.UUID(listing["id"]),
            )
        ).all()
    }
    assert "delete" in actions


def test_export_carries_marketplace(client, db, seller, buyer):
    _sold_pair(client, seller, buyer)
    from app.modules.core import export as core_export

    # Build the ZIP through the service the route uses and read
    # the marketplace member back.
    import io
    import json
    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(core_export.build_export_zip(db, seller)))
    payload = json.loads(archive.read("marketplace.json"))
    assert len(payload["listings"]) == 1
    assert payload["listings"][0]["status"] == "sold"
    assert len(payload["interactions"]) == 1


def test_deletion_keeps_other_side_aggregate_honest(client, db, seller, buyer):
    _sold, view = _sold_pair(client, seller, buyer)
    interaction_id = view["id"]
    assert _rate(client, buyer, interaction_id, 4, "solid seller").status_code == 201
    assert _rate(client, seller, interaction_id, 5, "solid buyer").status_code == 201
    assert _profile(client, seller.id)["reputation"]["count"] == 1
    # The BUYER deletes their account entirely.
    from app.modules.core import service as core_service

    core_service.delete_account(db, buyer)
    # The listing is the seller's and stays; the interaction and
    # the buyer's rating survive — stars still count, the rater
    # displays as a former member.
    rep = _profile(client, seller.id)["reputation"]
    assert rep == {"average": 4.0, "count": 1, "completed_deals": 1}
    public = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert public["ratings"][0]["rater_name"] == "Former member"
    # And the SELLER deleting removes their listings from the board.
    listing = _listing(client, seller, title="Soon orphaned")
    assert len(_public_board(client)) == 1
    core_service.delete_account(db, seller)
    assert _public_board(client) == []
    assert db.scalars(select(market_models.SaleListing)).first() is None


def test_module_gate_covers_owner_surfaces(client, db, seller):
    operator = _make_user(
        db, "TV-M-000699", "mop@example.com", [MECHANIC], name="Op"
    )
    operator.is_operator = True
    db.commit()
    client.put(
        "/api/admin/modules/marketplace/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    refused = client.get("/api/marketplace/mine", headers=auth_headers(seller))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "module_unavailable"
    # The board hides too (the module's global switch is one of
    # its two off conditions).
    assert client.get("/api/marketplace/public/board").status_code == 404
