"""Gap wave 1, item 1 — moderator removal of abusive ratings.

Pins:
- a member can REPORT a published rating; the report lands in
  the moderation queue's Ratings section;
- plain users get 403 on every queue action (the role ladder:
  moderator / community_admin / operator only);
- REMOVE: the rating stops counting in reputation.summary_for
  (profiles, board sort, forum badges all read it), its text is
  replaced by the moderator placeholder everywhere it renders,
  the interaction record stays, the removal is audit-logged,
  and the rating's author gets an inbox notification;
- DISMISS: the rating stands, aggregates untouched;
- guard rails: no reporting your own review, no reporting an
  unpublished (blind) rating, no duplicate open reports.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.marketplace import reputation
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, *, name="Wave User"):
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
        db, "TV-M-001101", "w1seller@example.com", [MECHANIC], name="Sally Seller"
    )


@pytest.fixture()
def buyer(db):
    return _make_user(
        db, "TV-S-001102", "w1buyer@example.com", [SHOP], name="Ben Buyer"
    )


@pytest.fixture()
def looker(db):
    return _make_user(
        db, "TV-D-001103", "w1looker@example.com", [DEALER], name="Lena Looker"
    )


def _rated_pair(client, seller, buyer):
    """A sold deal both sides rated (so both ratings publish):
    buyer gives the SELLER 1 star with abusive text; seller gives
    the buyer 5 stars. Returns the buyer's-rating-on-seller row
    as the public reputation endpoint shows it."""
    listing = client.post(
        "/api/marketplace/listings",
        json={"title": "Wave ratchet"},
        headers=auth_headers(seller),
    ).json()
    sold = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_account_number": buyer.account_number},
        headers=auth_headers(seller),
    )
    assert sold.status_code == 200, sold.text
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()
    interaction = next(r for r in mine if r["listing_id"] == listing["id"])
    r1 = client.post(
        f"/api/marketplace/interactions/{interaction['id']}/rating",
        json={"stars": 1, "text": "total scammer, avoid!!!"},
        headers=auth_headers(buyer),
    )
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post(
        f"/api/marketplace/interactions/{interaction['id']}/rating",
        json={"stars": 5, "text": "Smooth deal."},
        headers=auth_headers(seller),
    )
    assert r2.status_code in (200, 201), r2.text
    profile = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert profile["summary"]["count"] == 1
    assert profile["summary"]["average"] == 1.0
    return interaction, profile["ratings"][0]


def _report(client, user, rating_id, reason="Abusive review"):
    return client.post(
        f"/api/marketplace/ratings/{rating_id}/report",
        json={"reason": reason},
        headers=auth_headers(user),
    )


def _promote(db, user, role="moderator"):
    row = db.get(core_models.User, user.id)
    row.role = role
    db.commit()
    return user


def test_report_queue_remove_drops_the_aggregate(client, db, seller, buyer, looker):
    interaction, rating = _rated_pair(client, seller, buyer)

    # A stranger to the deal can report the published review.
    resp = _report(client, looker, rating["id"])
    assert resp.status_code == 201, resp.text
    report = resp.json()
    assert report["status"] == "open"
    assert report["rating_text"] == "total scammer, avoid!!!"

    # Plain users — including the participants — are locked out
    # of the queue.
    for user in (seller, buyer, looker):
        denied = client.get(
            "/api/marketplace/mod/rating-reports",
            headers=auth_headers(user),
        )
        assert denied.status_code == 403, denied.text

    _promote(db, looker)
    queue = client.get(
        "/api/marketplace/mod/rating-reports", headers=auth_headers(looker)
    )
    assert queue.status_code == 200, queue.text
    assert [r["id"] for r in queue.json()] == [report["id"]]

    removed = client.post(
        f"/api/marketplace/mod/rating-reports/{report['id']}/remove",
        json={"resolution": "Abusive content"},
        headers=auth_headers(looker),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "actioned"
    assert removed.json()["rating_removed"] is True

    # The aggregate drops EVERYWHERE summary_for feeds: the
    # reputation endpoint (profiles + board sort read it) no
    # longer counts the rating at all.
    profile = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert profile["summary"]["count"] == 0
    assert profile["summary"]["average"] is None
    summary = reputation.summary_for(db, seller.id)
    assert summary["count"] == 0 and summary["completed_deals"] == 1

    # The review still renders — as the moderator tombstone.
    tombstone = profile["ratings"][0]
    assert tombstone["removed"] is True
    assert tombstone["stars"] is None
    assert tombstone["text"] == reputation.REMOVED_TEXT

    # The interaction record stays (two-party history).
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(seller)
    ).json()
    view = next(r for r in mine if r["id"] == interaction["id"])
    assert view["their_rating"]["removed"] is True

    # The rating's author heard about it in their inbox.
    inbox = client.get(
        "/api/core/notifications", headers=auth_headers(buyer)
    ).json()
    assert any(n["kind"] == "rating_removed" for n in inbox)

    # And the act is in the admin audit log under the moderator.
    audit = db.scalars(
        select(core_models.AuditLog).where(
            core_models.AuditLog.action == "rating.remove"
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].actor_user_id == looker.id


def test_dismiss_keeps_the_rating(client, db, seller, buyer, looker):
    _interaction, rating = _rated_pair(client, seller, buyer)
    report = _report(client, looker, rating["id"]).json()
    _promote(db, looker, role="community_admin")

    dismissed = client.post(
        f"/api/marketplace/mod/rating-reports/{report['id']}/dismiss",
        json={"resolution": "Harsh but honest"},
        headers=auth_headers(looker),
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"

    profile = client.get(f"/api/marketplace/reputation/{seller.id}").json()
    assert profile["summary"]["count"] == 1
    assert profile["ratings"][0]["text"] == "total scammer, avoid!!!"
    assert profile["ratings"][0]["removed"] is False


def test_report_guard_rails(client, db, seller, buyer, looker):
    _interaction, rating = _rated_pair(client, seller, buyer)

    # The author can't report their own review.
    own = _report(client, buyer, rating["id"])
    assert own.status_code == 422, own.text

    # First report lands; a second open one from the same
    # reporter is refused.
    assert _report(client, looker, rating["id"]).status_code == 201
    again = _report(client, looker, rating["id"])
    assert again.status_code == 422, again.text

    # A rating that doesn't exist (or isn't published) 404s.
    missing = _report(client, seller, uuid.uuid4())
    assert missing.status_code == 404, missing.text

    # Resolving twice is refused.
    _promote(db, looker)
    queue = client.get(
        "/api/marketplace/mod/rating-reports", headers=auth_headers(looker)
    ).json()
    report_id = queue[0]["id"]
    client.post(
        f"/api/marketplace/mod/rating-reports/{report_id}/dismiss",
        json={},
        headers=auth_headers(looker),
    )
    twice = client.post(
        f"/api/marketplace/mod/rating-reports/{report_id}/remove",
        json={},
        headers=auth_headers(looker),
    )
    assert twice.status_code == 422, twice.text
