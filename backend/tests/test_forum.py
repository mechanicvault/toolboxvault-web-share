"""Community Forum (2026-10-20, community suite build 3).

Pins:
- READING IS PUBLIC: the signed-in and anonymous category /
  thread / search payloads carry the EXACT same key sets — no
  email anywhere; the author block is the public profile fields
  only (name, account number, member since, role, reputation).
- POSTING IS PAID-GATED (the suite's rule): enforcement OFF →
  open; ON → free accounts refused 403 {code: paid_plan_required}
  on new threads AND replies, a TRIAL never counts, paid passes.
- The spam firewall screens posts: a blocklisted-domain reply is
  HELD — the author sees it (held), the public doesn't; the mod
  queue lists it; release publishes it (and notifies like a
  fresh reply); tier budgets 429 an over-poster.
- Reports feed the forum queue: a moderator removes the post
  (tombstone keeps the thread's shape), the report actions out,
  and an audit row lands. The role ladder gates the queue.
- Pin sorts first; lock refuses replies with friendly copy.
- ONE community reference per post, validated live at post time
  (a non-public target is a friendly 422); the card resolves
  live and a dead reference renders the honest unavailable card
  with the snapshotted title.
- The author reputation badge IS reputation.summary_for — the
  one aggregate, compared value-for-value after a real
  double-blind deal publishes.
- Quotes snapshot: a quote survives its original's removal.
- Replies notify the thread author once per unread window
  (kind forum_reply); a second reply while unread stays quiet.
- The kill switch 404s both faces; the operator curates
  categories (create / rename / archive) and members can't.
- Journal: forum_thread / forum_post are visibility-only specs
  (a restore must never resurrect moderated content).
- Export carries forum.json; account deletion tombstones the
  author's posts ("Former member", bodies wiped) without
  breaking the thread for everyone else.
"""

import uuid
import zipfile
from io import BytesIO

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
from app.modules.billing import models as billing_models
from app.modules.core import journal
from app.modules.core import models as core_models
from app.modules.forum import models as forum_models
from app.modules.forum import service as forum_service
from app.modules.marketplace import models as market_models
from app.modules.marketplace import reputation
from app.modules.messaging import spam
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"

CATEGORY_KEYS = {
    "id", "name", "description", "sort_order", "is_active",
    "system_key",
    "thread_count", "post_count", "last_thread_id",
    "last_thread_title", "last_activity_at",
}
AUTHOR_KEYS = {
    "user_id", "display_name", "account_number", "member_since",
    "role", "reputation",
}
THREAD_KEYS = {
    "id", "category_id", "title", "author", "pinned", "locked",
    "held", "reply_count", "post_count", "excerpt", "created_at",
    "last_post_at",
}
POST_KEYS = {
    "id", "thread_id", "author", "body", "status", "removed_by",
    "is_opener", "quote", "link", "flags", "edited_at",
    "created_at", "mine",
}


def _make_user(db, account_number, email, account_types, *, name="Forum User", role="user", operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
        role=role,
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(
        db, "TV-M-001101", "fposter@example.com", [MECHANIC], name="Pat Poster"
    )


@pytest.fixture()
def replier(db):
    return _make_user(
        db, "TV-S-001102", "freplier@example.com", [SHOP], name="Rae Replier"
    )


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-001103", "fmod@example.com", [MECHANIC],
        name="Mo Moderator", role="moderator",
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-001104", "fop@example.com", [MECHANIC],
        name="Olive Operator", operator=True,
    )


def _category(client, operator, name="General Discussion", **fields):
    payload = {"name": name, "description": fields.pop("description", ""), "sort_order": fields.pop("sort_order", 0)}
    payload.update(fields)
    response = client.post(
        "/api/forum/admin/categories", json=payload, headers=auth_headers(operator)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _thread(client, user, category_id, **fields):
    payload = {
        "category_id": category_id,
        "title": fields.pop("title", "Best torque wrench under $200?"),
        "body": fields.pop("body", "Looking for recommendations."),
    }
    payload.update(fields)
    response = client.post(
        "/api/forum/threads", json=payload, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _reply(client, user, thread_id, **fields):
    payload = {"body": fields.pop("body", "I use the Gearwrench one daily.")}
    payload.update(fields)
    return client.post(
        f"/api/forum/threads/{thread_id}/replies",
        json=payload,
        headers=auth_headers(user),
    )


def _pay(db, user, *, status="active", source="stripe"):
    sub = billing_models.Subscription(
        user_id=user.id, plan_key="pro", status=status, source=source
    )
    db.add(sub)
    db.commit()
    return sub


def _enforce(db, on=True):
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, on)


# -- public reading ------------------------------------------------------------


def test_public_reads_exact_keys_and_no_email(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    reply = _reply(client, replier, thread["id"])
    assert reply.status_code == 201, reply.text

    anon_categories = client.get("/api/forum/public/categories")
    assert anon_categories.status_code == 200
    rows = anon_categories.json()
    assert len(rows) == 1
    assert set(rows[0].keys()) == CATEGORY_KEYS
    assert rows[0]["thread_count"] == 1
    assert rows[0]["post_count"] == 2
    assert rows[0]["last_thread_title"] == thread["title"]

    anon_threads = client.get(f"/api/forum/public/categories/{category['id']}/threads")
    assert anon_threads.status_code == 200
    summaries = anon_threads.json()
    assert set(summaries[0].keys()) == THREAD_KEYS
    assert set(summaries[0]["author"].keys()) == AUTHOR_KEYS
    assert summaries[0]["reply_count"] == 1

    anon_thread = client.get(f"/api/forum/public/threads/{thread['id']}")
    assert anon_thread.status_code == 200
    view = anon_thread.json()
    assert set(view.keys()) == THREAD_KEYS | {"posts"}
    assert len(view["posts"]) == 2
    for post in view["posts"]:
        assert set(post.keys()) == POST_KEYS
        assert set(post["author"].keys()) == AUTHOR_KEYS
        assert post["mine"] is False

    # Signed-in reads carry the identical key sets.
    signed = client.get(
        f"/api/forum/threads/{thread['id']}", headers=auth_headers(poster)
    )
    assert signed.status_code == 200
    assert set(signed.json().keys()) == set(view.keys())
    assert set(signed.json()["posts"][0].keys()) == POST_KEYS

    # The whole public surface, as text: no email anywhere.
    blob = (
        anon_categories.text + anon_threads.text + anon_thread.text
    )
    assert "@example.com" not in blob
    assert "fposter" not in blob


def test_search_matches_titles_and_bodies_publicly(client, poster, operator):
    category = _category(client, operator)
    thread = _thread(
        client, poster, category["id"],
        title="Impact gun roundup", body="Comparing the big three.",
    )
    _reply(client, poster, thread["id"], body="The Milwaukee mid-torque wins.")
    hits = client.get("/api/forum/public/search", params={"q": "Milwaukee"})
    assert hits.status_code == 200
    assert [row["id"] for row in hits.json()] == [thread["id"]]
    hits = client.get("/api/forum/public/search", params={"q": "roundup"})
    assert [row["id"] for row in hits.json()] == [thread["id"]]
    assert client.get("/api/forum/public/search", params={"q": "nonexistent"}).json() == []


def test_kill_switch_404s_both_faces(client, db, poster, operator):
    category = _category(client, operator)
    _thread(client, poster, category["id"])
    entitlements.set_setting(db, forum_service.FORUM_ENABLED_KEY, False)
    assert client.get("/api/forum/public/categories").status_code == 404
    assert client.get(
        "/api/forum/categories", headers=auth_headers(poster)
    ).status_code == 404
    entitlements.set_setting(db, forum_service.FORUM_ENABLED_KEY, True)
    assert client.get("/api/forum/public/categories").status_code == 200


# -- the paid gate ----------------------------------------------------------------


def test_paid_gate_thread_and_reply_trial_excluded(client, db, poster, replier, operator):
    category = _category(client, operator)
    _enforce(db, True)

    free_thread = client.post(
        "/api/forum/threads",
        json={"category_id": category["id"], "title": "T", "body": "B"},
        headers=auth_headers(poster),
    )
    assert free_thread.status_code == 403
    assert free_thread.json()["detail"]["code"] == "paid_plan_required"

    _pay(db, poster)
    thread = _thread(client, poster, category["id"])

    free_reply = _reply(client, replier, thread["id"])
    assert free_reply.status_code == 403
    assert free_reply.json()["detail"]["code"] == "paid_plan_required"

    # A trial never counts.
    trial = billing_models.Subscription(
        user_id=replier.id, plan_key="pro", status="trialing", source="trial"
    )
    db.add(trial)
    db.commit()
    assert _reply(client, replier, thread["id"]).status_code == 403

    db.delete(trial)
    db.commit()
    _pay(db, replier)
    assert _reply(client, replier, thread["id"]).status_code == 201


def test_paid_gate_off_means_open(client, db, poster, operator):
    category = _category(client, operator)
    _enforce(db, False)
    thread = _thread(client, poster, category["id"])
    assert thread["held"] is False


# -- the firewall -----------------------------------------------------------------


def test_lured_reply_held_author_sees_public_doesnt(client, db, poster, replier, moderator, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    lured = _reply(
        client, replier, thread["id"],
        body="Short link, big prize: https://bit.ly/claim-now — act now!",
    )
    assert lured.status_code == 201, lured.text
    assert lured.json()["status"] == "held"

    public = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    assert len(public["posts"]) == 1  # opener only

    author_view = client.get(
        f"/api/forum/threads/{thread['id']}", headers=auth_headers(replier)
    ).json()
    assert len(author_view["posts"]) == 2
    held_post = author_view["posts"][1]
    assert held_post["status"] == "held"
    assert any(f.startswith("blocked_domain") for f in held_post["flags"])

    queue = client.get("/api/forum/mod/held", headers=auth_headers(moderator))
    assert queue.status_code == 200
    assert [row["id"] for row in queue.json()] == [lured.json()["id"]]

    released = client.post(
        f"/api/forum/mod/posts/{lured.json()['id']}/release",
        headers=auth_headers(moderator),
    )
    assert released.status_code == 200
    public = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    assert len(public["posts"]) == 2
    assert public["posts"][1]["status"] == "visible"


def test_lured_thread_opener_hides_whole_thread(client, poster, operator):
    category = _category(client, operator)
    thread = _thread(
        client, poster, category["id"],
        title="Easy money", body="Visit https://bit.ly/easy-money now",
    )
    assert thread["held"] is True
    listing = client.get(f"/api/forum/public/categories/{category['id']}/threads")
    assert listing.json() == []
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 404
    mine = client.get("/api/forum/mine/threads", headers=auth_headers(poster))
    assert [row["id"] for row in mine.json()] == [thread["id"]]


def test_tier_budget_429s(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    # Cap every tier the same so the pin doesn't depend on the
    # fresh account's age-derived tier.
    config = {
        "tiers": {
            tier: {"messages_per_hour": 2} for tier in ("0", "1", "2", "3")
        }
    }
    entitlements.set_setting(db, spam.CONFIG_KEY, config)
    assert _reply(client, replier, thread["id"], body="one").status_code == 201
    assert _reply(client, replier, thread["id"], body="two").status_code == 201
    third = _reply(client, replier, thread["id"], body="three")
    assert third.status_code == 429


def test_edit_into_lure_holds_the_post(client, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    opener_id = thread["posts"][0]["id"]
    edited = client.put(
        f"/api/forum/posts/{opener_id}",
        json={"body": "Updated: see https://bit.ly/updated-deal"},
        headers=auth_headers(poster),
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "held"
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 404


# -- reports + moderation ------------------------------------------------------------


def test_report_queue_remove_and_audit(client, db, poster, replier, moderator, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    reply = _reply(client, replier, thread["id"], body="Sketchy reply here.")
    post_id = reply.json()["id"]

    reported = client.post(
        f"/api/forum/posts/{post_id}/report",
        json={"reason": "Looks like a scam"},
        headers=auth_headers(poster),
    )
    assert reported.status_code == 201, reported.text

    queue = client.get("/api/forum/mod/reports", headers=auth_headers(moderator))
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert queue.json()[0]["post_author_name"] == "Rae Replier"

    removed = client.post(
        f"/api/forum/mod/posts/{post_id}/remove",
        json={"resolution": "Scam content"},
        headers=auth_headers(moderator),
    )
    assert removed.status_code == 200

    public = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    tombstone = public["posts"][1]
    assert tombstone["status"] == "removed"
    assert tombstone["removed_by"] == "moderator"
    assert tombstone["body"] == ""

    queue = client.get("/api/forum/mod/reports", headers=auth_headers(moderator))
    assert queue.json() == []  # actioned out of the open queue

    audit_rows = db.scalars(
        select(core_models.AuditLog).where(
            core_models.AuditLog.action == "forum.post_remove"
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_user_id == moderator.id


def test_mod_queue_role_gate(client, poster, replier, operator):
    category = _category(client, operator)
    _thread(client, poster, category["id"])
    assert client.get(
        "/api/forum/mod/reports", headers=auth_headers(replier)
    ).status_code == 403
    assert client.get(
        "/api/forum/mod/held", headers=auth_headers(replier)
    ).status_code == 403


def test_pin_sorts_first_and_lock_refuses_replies(client, poster, replier, moderator, operator):
    category = _category(client, operator)
    first = _thread(client, poster, category["id"], title="First thread")
    second = _thread(
        client, poster, category["id"], title="Second thread", body="Newer."
    )
    rows = client.get(f"/api/forum/public/categories/{category['id']}/threads").json()
    assert [row["id"] for row in rows] == [second["id"], first["id"]]

    pinned = client.post(
        f"/api/forum/mod/threads/{first['id']}/pin", headers=auth_headers(moderator)
    )
    assert pinned.status_code == 200 and pinned.json()["pinned"] is True
    rows = client.get(f"/api/forum/public/categories/{category['id']}/threads").json()
    assert [row["id"] for row in rows] == [first["id"], second["id"]]

    locked = client.post(
        f"/api/forum/mod/threads/{first['id']}/lock", headers=auth_headers(moderator)
    )
    assert locked.json()["locked"] is True
    refused = _reply(client, replier, first["id"])
    assert refused.status_code == 422
    assert "locked" in refused.json()["detail"]


def test_wipe_all_from_user(client, poster, replier, moderator, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _reply(client, replier, thread["id"], body="spam one")
    _reply(client, replier, thread["id"], body="spam two")
    result = client.post(
        f"/api/forum/mod/users/{replier.id}/wipe-posts",
        headers=auth_headers(moderator),
    )
    assert result.status_code == 200
    assert result.json()["posts_removed"] == 2
    public = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    assert [p["status"] for p in public["posts"]] == ["visible", "removed", "removed"]


# -- links --------------------------------------------------------------------------


def _board_listing(client, db, seller, **fields):
    payload = {"title": fields.pop("title", "Mac impact wrench")}
    payload.update(fields)
    response = client.post(
        "/api/marketplace/listings", json=payload, headers=auth_headers(seller)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_link_card_lifecycle(client, db, poster, operator):
    category = _category(client, operator)
    listing = _board_listing(client, db, poster, price="120.00")

    # A non-public target is refused at post time.
    refused = client.post(
        "/api/forum/threads",
        json={
            "category_id": category["id"],
            "title": "Check this out",
            "body": "Great deal here",
            "link_type": "listing",
            "link_id": str(uuid.uuid4()),
        },
        headers=auth_headers(poster),
    )
    assert refused.status_code == 422

    thread = _thread(
        client, poster, category["id"],
        title="Deal on an impact",
        body="Someone should grab this",
        link_type="listing",
        link_id=listing["id"],
    )
    card = thread["posts"][0]["link"]
    assert card["available"] is True
    assert card["title"] == "Mac impact wrench"
    assert card["type"] == "listing"

    # The listing dies -> the card turns honest, title snapshotted.
    gone = client.delete(
        f"/api/marketplace/listings/{listing['id']}", headers=auth_headers(poster)
    )
    assert gone.status_code in (200, 204), gone.text
    view = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    card = view["posts"][0]["link"]
    assert card["available"] is False
    assert card["title"] == "Mac impact wrench"


def test_link_card_carries_seller_currency(client, db, poster, operator):
    """Wave 3 currency on the forum card (2026-10-26 fix): the
    price rides in the SELLER's currency — an EUR seller's €100
    listing must not render as $100 to anyone. The amount itself
    never converts; a dead card carries no currency."""
    from decimal import Decimal

    from app.modules.parts import models as part_models

    poster.currency = "EUR"
    db.commit()
    category = _category(client, operator)

    listing = _board_listing(client, db, poster, price="100.00")
    listing_thread = _thread(
        client, poster, category["id"],
        title="EUR deal", body="Priced in euros",
        link_type="listing", link_id=listing["id"],
    )
    card = listing_thread["posts"][0]["link"]
    assert card["available"] is True
    assert card["seller_currency"] == "EUR"
    assert Decimal(str(card["price"])) == Decimal("100.00")

    part = part_models.Part(
        owner_id=poster.id, title="Alternator", quantity=1,
        asking_price=Decimal("250"), visibility="public",
        attachments=[],
    )
    db.add(part)
    db.commit()
    db.refresh(part)
    part_thread = _thread(
        client, poster, category["id"],
        title="EUR part", body="Also priced in euros",
        link_type="part", link_id=str(part.id),
    )
    card = part_thread["posts"][0]["link"]
    assert card["available"] is True
    assert card["seller_currency"] == "EUR"
    assert Decimal(str(card["price"])) == Decimal("250")

    gone = client.delete(
        f"/api/marketplace/listings/{listing['id']}", headers=auth_headers(poster)
    )
    assert gone.status_code in (200, 204), gone.text
    view = client.get(f"/api/forum/public/threads/{listing_thread['id']}").json()
    card = view["posts"][0]["link"]
    assert card["available"] is False
    assert card["seller_currency"] is None


# -- quotes, edits, deletes -------------------------------------------------------------


def test_quote_snapshot_survives_removal(client, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    opener_id = thread["posts"][0]["id"]
    quoted = _reply(
        client, replier, thread["id"],
        body="Agreed, great advice.", quote_post_id=opener_id,
    )
    assert quoted.status_code == 201, quoted.text
    assert quoted.json()["quote"]["author_name"] == "Pat Poster"
    assert "recommendations" in quoted.json()["quote"]["excerpt"]

    removed = client.delete(
        f"/api/forum/posts/{opener_id}", headers=auth_headers(poster)
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"
    view = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    assert view["posts"][0]["status"] == "removed"
    assert view["posts"][0]["body"] == ""
    assert view["posts"][1]["quote"]["author_name"] == "Pat Poster"


def test_edit_marks_edited(client, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    opener_id = thread["posts"][0]["id"]
    assert thread["posts"][0]["edited_at"] is None
    edited = client.put(
        f"/api/forum/posts/{opener_id}",
        json={"body": "Updated recommendation: the Tekton set."},
        headers=auth_headers(poster),
    )
    assert edited.status_code == 200
    assert edited.json()["edited_at"] is not None
    assert edited.json()["body"].startswith("Updated recommendation")


# -- reputation ---------------------------------------------------------------------------


def test_author_reputation_comes_from_summary_for(client, db, poster, replier, operator):
    category = _category(client, operator)
    listing = _board_listing(client, db, poster)
    sold = client.post(
        f"/api/marketplace/listings/{listing['id']}/sold",
        json={"buyer_account_number": replier.account_number},
        headers=auth_headers(poster),
    )
    assert sold.status_code == 200, sold.text
    mine = client.get(
        "/api/marketplace/interactions/mine", headers=auth_headers(poster)
    ).json()
    interaction_id = mine[0]["id"]
    for user, stars in ((poster, 4), (replier, 5)):
        rated = client.post(
            f"/api/marketplace/interactions/{interaction_id}/rating",
            json={"stars": stars, "text": ""},
            headers=auth_headers(user),
        )
        assert rated.status_code in (200, 201), rated.text

    expected = reputation.summary_for(db, poster.id)
    assert expected["count"] == 1 and expected["average"] == 5.0

    thread = _thread(client, poster, category["id"])
    badge = thread["author"]["reputation"]
    assert badge["average"] == expected["average"]
    assert badge["count"] == expected["count"]
    assert badge["completed_deals"] == expected["completed_deals"]


# -- notifications -------------------------------------------------------------------------


def test_reply_notifies_once_per_unread_window(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _reply(client, replier, thread["id"], body="First reply")
    _reply(client, replier, thread["id"], body="Second reply")

    notes = client.get(
        "/api/core/notifications", headers=auth_headers(poster)
    ).json()
    forum_notes = [n for n in notes if n["kind"] == "forum_reply"]
    assert len(forum_notes) == 1
    assert forum_notes[0]["data"]["thread_id"] == thread["id"]

    # Read it -> the next reply notifies again.
    client.post(
        f"/api/core/notifications/{forum_notes[0]['id']}/read",
        headers=auth_headers(poster),
    )
    _reply(client, replier, thread["id"], body="Third reply")
    notes = client.get(
        "/api/core/notifications", headers=auth_headers(poster)
    ).json()
    assert len([n for n in notes if n["kind"] == "forum_reply"]) == 2

    # My own reply to my own thread never notifies me.
    _reply(client, poster, thread["id"], body="Author follow-up")
    notes = client.get(
        "/api/core/notifications", headers=auth_headers(poster)
    ).json()
    assert len([n for n in notes if n["kind"] == "forum_reply"]) == 2


# -- categories admin ------------------------------------------------------------------------


def test_category_admin_operator_only(client, poster, operator):
    made = _category(client, operator, name="Announcements", sort_order=1)
    assert made["is_active"] is True
    assert client.post(
        "/api/forum/admin/categories",
        json={"name": "Nope"},
        headers=auth_headers(poster),
    ).status_code == 403

    renamed = client.put(
        f"/api/forum/admin/categories/{made['id']}",
        json={"name": "News & Announcements"},
        headers=auth_headers(operator),
    )
    assert renamed.json()["name"] == "News & Announcements"

    archived = client.put(
        f"/api/forum/admin/categories/{made['id']}",
        json={"is_active": False},
        headers=auth_headers(operator),
    )
    assert archived.json()["is_active"] is False
    public = client.get("/api/forum/public/categories").json()
    assert all(row["id"] != made["id"] for row in public)
    admin_list = client.get(
        "/api/forum/admin/categories", headers=auth_headers(operator)
    ).json()
    assert any(row["id"] == made["id"] for row in admin_list)


# -- journal / export / deletion ----------------------------------------------------------------


def test_journal_specs_are_visibility_only():
    thread_spec = journal._SPEC_BY_TYPE["forum_thread"]
    post_spec = journal._SPEC_BY_TYPE["forum_post"]
    assert thread_spec.visibility_only is True
    assert post_spec.visibility_only is True
    assert thread_spec.owner_attr == "author_id"
    assert post_spec.owner_attr == "author_id"


def test_export_and_deletion_tombstone(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _reply(client, replier, thread["id"], body="Replier was here.")

    exported = client.get("/api/core/export", headers=auth_headers(replier))
    assert exported.status_code == 200, exported.text
    archive = zipfile.ZipFile(BytesIO(exported.content))
    import json

    payload = json.loads(archive.read("forum.json"))
    assert payload["threads"] == []
    assert len(payload["posts"]) == 1
    assert payload["posts"][0]["body"] == "Replier was here."

    deleted = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(replier),
    )
    assert deleted.status_code == 204, deleted.text

    view = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    tombstone = view["posts"][1]
    assert tombstone["author"]["display_name"] == "Former member"
    assert tombstone["body"] == ""
    assert view["posts"][0]["status"] == "visible"  # thread unbroken

    row = db.get(forum_models.ForumPost, uuid.UUID(tombstone["id"]))
    assert row.author_gone is True
