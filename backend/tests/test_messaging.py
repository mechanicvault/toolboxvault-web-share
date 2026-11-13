"""Messaging module + anti-spam firewall (2026-10-19, community
suite build 1).

Pins:
- threads: two-party, append-only; the first contact from a
  stranger lands as a REQUEST — no inbox notification, no email,
  no read receipts, links inert — until the recipient replies
  (implicit accept) or declines (silent hide);
- read markers + unread counts per participant;
- the email seam: accepted-thread activity sends ONE content-free
  notification email per unread batch (no message text, no links);
- the firewall: trust tiers (trial never raises), thread/message
  budgets with friendly 429s, duplicate-blast holds, the phishing
  domain blocklist, lure-pattern holds, link flagging;
- block silence: a blocked sender's threads/messages land in the
  shadow path — the sender sees a normal conversation, the
  blocked-against side never sees anything;
- report -> moderation queue -> dismiss / release / discard /
  wipe / wipe-all / ban (moderator role + operator);
- the public profile: coarse facts + opt-in phone only, the
  reputation placeholder, deactivated accounts 404;
- module control: messaging off -> 403 module_unavailable, and
  the public profile 404s too.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.messaging import spam
from app.modules.parts import models as parts_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"


def _make_user(db, account_number, email, account_types, *, operator=False, role="user", name="Msg User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
        is_operator=operator,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def alice(db):
    return _make_user(db, "TV-M-000401", "alice@example.com", [MECHANIC], name="Alice Abel")


@pytest.fixture()
def bob(db):
    return _make_user(db, "TV-M-000402", "bob@example.com", [MECHANIC], name="Bob Baker")


@pytest.fixture()
def carol(db):
    return _make_user(db, "TV-S-000403", "carol@example.com", [SHOP], name="Carol Chen")


@pytest.fixture()
def dave(db):
    return _make_user(db, "TV-M-000404", "dave@example.com", [MECHANIC], name="Dave Dorn")


@pytest.fixture()
def mod(db):
    return _make_user(
        db, "TV-M-000405", "mod@example.com", [MECHANIC], role="moderator", name="Marta Mod"
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000406", "op@example.com", [MECHANIC], operator=True, name="Olivia Op"
    )


def _open(client, sender, recipient_id, body="Hey, is this still available?"):
    response = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(recipient_id), "body": body},
        headers=auth_headers(sender),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post(client, user, thread_id, body):
    return client.post(
        f"/api/messaging/threads/{thread_id}/messages",
        json={"body": body},
        headers=auth_headers(user),
    )


def _notifications(db, user_id):
    return list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == user_id
            )
        ).all()
    )


def _outbox(db):
    return list(db.scalars(select(core_models.EmailOutbox)).all())


# -- quarantine -------------------------------------------------------------------


def test_first_contact_is_a_quiet_request(client, db, alice, bob):
    thread = _open(client, alice, bob.id)
    assert thread["status"] == "request"
    assert thread["other_name"] == "Bob Baker"
    assert thread["messages"][0]["body"] == "Hey, is this still available?"
    # Links/receipts are off at the request stage, and the sender
    # can't see the other side's read marker at all.
    assert thread["messages"][0]["links_disabled"] is True
    assert thread["other_last_read_seq"] is None

    # The recipient sees it ONLY in the requests list.
    main = client.get("/api/messaging/threads", headers=auth_headers(bob)).json()
    assert main == []
    requests = client.get(
        "/api/messaging/threads?folder=requests", headers=auth_headers(bob)
    ).json()
    assert [t["id"] for t in requests] == [thread["id"]]
    assert requests[0]["unread_count"] == 1
    # The sender sees the same thread in their MAIN list.
    sender_main = client.get("/api/messaging/threads", headers=auth_headers(alice)).json()
    assert [t["id"] for t in sender_main] == [thread["id"]]

    # NO inbox notification and NO email for a held first contact.
    assert _notifications(db, bob.id) == []
    assert _outbox(db) == []


def test_reply_accepts_and_notifies(client, db, alice, bob):
    thread = _open(client, alice, bob.id)
    reply = _post(client, bob, thread["id"], "It is — come by Saturday?")
    assert reply.status_code == 200, reply.text
    detail = client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(alice)
    ).json()
    assert detail["status"] == "accepted"
    assert detail["messages"][0]["links_disabled"] is False
    # The opener got the acceptance note in their inbox.
    notes = _notifications(db, alice.id)
    assert [n.kind for n in notes] == ["message_request_accepted"]
    # Read receipts are unmasked now — and Bob's reply advanced
    # his own marker to his message (seq 2): replying IS reading.
    assert detail["other_last_read_seq"] == 2


def test_decline_is_silent_and_senders_next_try_is_fresh(client, db, alice, bob):
    thread = _open(client, alice, bob.id)
    response = client.post(
        f"/api/messaging/threads/{thread['id']}/decline", headers=auth_headers(bob)
    )
    assert response.status_code == 204
    assert client.get(
        "/api/messaging/threads?folder=requests", headers=auth_headers(bob)
    ).json() == []
    # Declining never notifies the sender.
    assert _notifications(db, alice.id) == []
    # A fresh contact opens a NEW request thread.
    again = _open(client, alice, bob.id, "Changed my mind — still got it?")
    assert again["id"] != thread["id"]
    assert again["status"] == "request"


def test_unread_counts_and_mark_read(client, alice, bob):
    thread = _open(client, alice, bob.id)
    _post(client, bob, thread["id"], "Yes!")
    _post(client, alice, thread["id"], "Great — Saturday?")
    _post(client, alice, thread["id"], "Morning works best.")
    summary = client.get("/api/messaging/unread", headers=auth_headers(bob)).json()
    assert summary == {"inbox_unread": 2, "requests_count": 0}
    response = client.post(
        f"/api/messaging/threads/{thread['id']}/read", headers=auth_headers(bob)
    )
    assert response.status_code == 200
    summary = client.get("/api/messaging/unread", headers=auth_headers(bob)).json()
    assert summary["inbox_unread"] == 0
    # The sender can now see the read receipt.
    detail = client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(alice)
    ).json()
    seqs = [m["seq"] for m in detail["messages"]]
    assert detail["other_last_read_seq"] == max(seqs)


def test_accepted_thread_notifies_once_per_unread_batch(client, db, alice, bob):
    thread = _open(client, alice, bob.id)
    _post(client, bob, thread["id"], "Accepted.")
    db.expunge_all()
    _post(client, alice, thread["id"], "One")
    _post(client, alice, thread["id"], "Two")
    notes = [n for n in _notifications(db, bob.id) if n.kind == "message_received"]
    assert len(notes) == 1
    emails = [row for row in _outbox(db) if row.kind == "message_notification"]
    assert len(emails) == 1
    # The email is content-free: no message text, no links at all.
    assert "One" not in emails[0].body and "Two" not in emails[0].body
    assert "http" not in emails[0].body
    # After Bob reads, the next message notifies again.
    client.post(f"/api/messaging/threads/{thread['id']}/read", headers=auth_headers(bob))
    _post(client, alice, thread["id"], "Three")
    notes = [n for n in _notifications(db, bob.id) if n.kind == "message_received"]
    assert len(notes) == 2


def test_foreign_thread_is_a_404(client, alice, bob, carol):
    thread = _open(client, alice, bob.id)
    assert client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(carol)
    ).status_code == 404
    assert _post(client, carol, thread["id"], "butting in").status_code == 404


def test_lookup_by_exact_account_number(client, alice, bob):
    found = client.get(
        "/api/messaging/lookup",
        params={"account_number": "TV-M-000402"},
        headers=auth_headers(alice),
    )
    assert found.status_code == 200
    assert found.json() == {"user_id": str(bob.id), "display_name": "Bob Baker"}
    # No partial matches, no probing: a wrong number is a 404.
    missing = client.get(
        "/api/messaging/lookup",
        params={"account_number": "TV-M-000499"},
        headers=auth_headers(alice),
    )
    assert missing.status_code == 404


def test_self_message_refused(client, alice):
    response = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(alice.id), "body": "note to self"},
        headers=auth_headers(alice),
    )
    assert response.status_code == 422


# -- the firewall -------------------------------------------------------------------


def test_thread_budget_429_and_paid_tier_headroom(client, db, alice, bob, carol, dave):
    from app.modules.billing import entitlements

    entitlements.set_setting(
        db, spam.CONFIG_KEY, {"tiers": {"0": {"new_threads_per_hour": 2}}}
    )
    _open(client, alice, bob.id)
    _open(client, alice, carol.id)
    third = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(dave.id), "body": "third"},
        headers=auth_headers(alice),
    )
    assert third.status_code == 429
    assert "too quickly" in third.json()["detail"].lower()
    # A paid plan lifts the tier (and its budget) immediately.
    from app.modules.billing import models as billing_models

    db.add(
        billing_models.Subscription(
            user_id=alice.id, plan_key="pro", status="active", source="stripe"
        )
    )
    db.commit()
    assert spam.trust_tier(db, alice) >= 2
    ok = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(dave.id), "body": "third"},
        headers=auth_headers(alice),
    )
    assert ok.status_code == 201, ok.text


def test_trial_never_raises_the_tier(client, db, alice):
    from app.modules.billing import models as billing_models

    assert spam.trust_tier(db, alice) == 0
    db.add(
        billing_models.Subscription(
            user_id=alice.id, plan_key="pro", status="trialing", source="stripe"
        )
    )
    db.commit()
    # A trialing account is a free account to the firewall.
    assert spam.trust_tier(db, alice) == 0


def test_blast_third_recipient_is_held(client, db, alice, bob, carol, dave):
    from app.modules.billing import models as billing_models

    db.add(
        billing_models.Subscription(
            user_id=alice.id, plan_key="pro", status="active", source="stripe"
        )
    )
    db.commit()
    body = "I have the exact part you need, message me back today"
    _open(client, alice, bob.id, body)
    _open(client, alice, carol.id, body)
    third = _open(client, alice, dave.id, body)
    message = third["messages"][0]
    # The sender sees the hold plainly; Dave sees an empty thread.
    assert message["held"] is True
    assert "blast" in message["flags"]
    dave_view = client.get(
        f"/api/messaging/threads/{third['id']}", headers=auth_headers(dave)
    ).json()
    assert dave_view["messages"] == []
    assert _notifications(db, dave.id) == []


def test_blocked_domain_and_lure_are_held(client, alice, bob):
    thread = _open(client, alice, bob.id, "first")
    _post(client, bob, thread["id"], "go on")
    link = _post(client, alice, thread["id"], "details at https://bit.ly/3xyz now")
    assert link.status_code == 200
    assert link.json()["held"] is True
    assert "blocked_domain:bit.ly" in link.json()["flags"]
    lure = _post(client, alice, thread["id"], "send me a gift card and it's yours")
    assert lure.json()["held"] is True
    assert "lure" in lure.json()["flags"]
    # Neither reached Bob.
    bob_view = client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(bob)
    ).json()
    bodies = [m["body"] for m in bob_view["messages"]]
    assert bodies == ["first", "go on"]


def test_plain_link_is_flagged_not_held(client, alice, bob):
    thread = _open(client, alice, bob.id, "first")
    _post(client, bob, thread["id"], "go on")
    sent = _post(client, alice, thread["id"], "listing: https://example.com/item/1")
    assert sent.json()["held"] is False
    assert sent.json()["flags"] == ["link"]


def test_block_silence(client, db, alice, bob):
    client.post(
        "/api/messaging/blocks",
        json={"user_id": str(alice.id)},
        headers=auth_headers(bob),
    )
    # Alice's thread opens "normally" for her…
    thread = _open(client, alice, bob.id, "hello?")
    assert thread["messages"][0]["held"] is False
    # …but Bob's world contains nothing.
    assert client.get("/api/messaging/threads", headers=auth_headers(bob)).json() == []
    assert client.get(
        "/api/messaging/threads?folder=requests", headers=auth_headers(bob)
    ).json() == []
    assert _notifications(db, bob.id) == []
    # And Bob messaging Alice is refused with the unblock hint.
    refused = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(alice.id), "body": "hi"},
        headers=auth_headers(bob),
    )
    assert refused.status_code == 422
    assert "unblock" in refused.json()["detail"].lower()
    # Unblock restores contact.
    client.delete(f"/api/messaging/blocks/{alice.id}", headers=auth_headers(bob))
    ok = client.post(
        "/api/messaging/threads",
        json={"recipient_id": str(alice.id), "body": "hi again"},
        headers=auth_headers(bob),
    )
    assert ok.status_code == 201


# -- moderation ---------------------------------------------------------------------


def test_report_queue_and_actions(client, db, alice, bob, mod):
    thread = _open(client, alice, bob.id, "sketchy offer")
    report = client.post(
        f"/api/messaging/threads/{thread['id']}/report",
        json={"reason": "Asked for a gift card"},
        headers=auth_headers(bob),
    )
    assert report.status_code == 201, report.text
    # The queue requires the role ladder (or operator).
    assert client.get(
        "/api/messaging/mod/reports", headers=auth_headers(alice)
    ).status_code == 403
    queue = client.get("/api/messaging/mod/reports", headers=auth_headers(mod)).json()
    assert len(queue) == 1 and queue[0]["status"] == "open"
    # A moderator sees the true thread state.
    view = client.get(
        f"/api/messaging/mod/threads/{thread['id']}", headers=auth_headers(mod)
    ).json()
    assert view["messages"][0]["body"] == "sketchy offer"
    dismissed = client.post(
        f"/api/messaging/mod/reports/{queue[0]['id']}/dismiss",
        json={"resolution": "First offense, warned"},
        headers=auth_headers(mod),
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"


def test_moderator_release_discard_wipe_and_ban(client, db, alice, bob, mod, operator):
    thread = _open(client, alice, bob.id, "first")
    _post(client, bob, thread["id"], "ok")
    held = _post(client, alice, thread["id"], "grab a gift card first")
    assert held.json()["held"] is True
    held_id = held.json()["id"]
    # Release delivers it to Bob.
    released = client.post(
        f"/api/messaging/mod/messages/{held_id}/release", headers=auth_headers(mod)
    )
    assert released.status_code == 200 and released.json()["status"] == "sent"
    bob_view = client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(bob)
    ).json()
    assert "gift card" in bob_view["messages"][-1]["body"]
    # Wipe destroys a delivered body for everyone.
    wiped = client.post(
        f"/api/messaging/mod/messages/{held_id}/wipe", headers=auth_headers(operator)
    )
    assert wiped.json()["status"] == "removed"
    bob_view = client.get(
        f"/api/messaging/threads/{thread['id']}", headers=auth_headers(bob)
    ).json()
    assert bob_view["messages"][-1]["body"] == ""
    # Ban uses the core machinery: email banned + account inactive,
    # and the banned sender can no longer sign in.
    banned = client.post(
        f"/api/messaging/mod/users/{alice.id}/ban", headers=auth_headers(mod)
    )
    assert banned.status_code == 200
    row = db.scalars(
        select(core_models.BannedEmail).where(
            core_models.BannedEmail.email == "alice@example.com"
        )
    ).first()
    assert row is not None
    db.refresh(alice)
    assert alice.is_active is False


def test_held_messages_wait_for_a_moderator(client, db, alice, bob, mod):
    thread = _open(client, alice, bob.id, "first")
    _post(client, bob, thread["id"], "ok")
    _post(client, alice, thread["id"], "verify your account at once")
    held_queue = client.get("/api/messaging/mod/held", headers=auth_headers(mod)).json()
    assert len(held_queue) == 1
    discarded = client.post(
        f"/api/messaging/mod/messages/{held_queue[0]['id']}/discard",
        headers=auth_headers(mod),
    )
    assert discarded.json()["status"] == "discarded"
    assert client.get("/api/messaging/mod/held", headers=auth_headers(mod)).json() == []


# -- public profile + contact preferences --------------------------------------------


def test_public_profile_and_phone_opt_in(client, db, alice):
    profile = client.get(
        f"/api/messaging/profiles/{alice.id}", headers=auth_headers(alice)
    ).json()
    assert profile["display_name"] == "Alice Abel"
    assert profile["phone"] is None
    assert profile["reputation"] == {"average": None, "count": 0, "completed_deals": 0}
    # The Settings contact panel: PATCH /core/me partial update.
    updated = client.patch(
        "/api/core/me",
        json={
            "public_area_label": "Central Minnesota",
            "contact_phone": "320-555-0100",
            "show_phone": True,
        },
        headers=auth_headers(alice),
    )
    assert updated.status_code == 200, updated.text
    # A partial update never touches the name.
    assert updated.json()["name"] == "Alice Abel"
    profile = client.get(
        f"/api/messaging/profiles/{alice.id}", headers=auth_headers(alice)
    ).json()
    assert profile["phone"] == "320-555-0100"
    assert profile["area_label"] == "Central Minnesota"
    # Show off again -> the number vanishes from the public shape.
    client.patch(
        "/api/core/me", json={"show_phone": False}, headers=auth_headers(alice)
    )
    profile = client.get(
        f"/api/messaging/profiles/{alice.id}", headers=auth_headers(alice)
    ).json()
    assert profile["phone"] is None


def test_public_profile_404s_for_missing_and_deactivated(client, db, alice, bob):
    assert client.get(
        f"/api/messaging/profiles/{uuid.uuid4()}", headers=auth_headers(bob)
    ).status_code == 404
    alice.is_active = False
    db.commit()
    assert client.get(
        f"/api/messaging/profiles/{alice.id}", headers=auth_headers(bob)
    ).status_code == 404


# -- anchors + module control ----------------------------------------------------------


def test_thread_anchors_to_a_public_part(client, db, alice, bob):
    part = parts_models.Part(
        owner_id=alice.id, title="5.3L intake manifold", visibility="public"
    )
    db.add(part)
    db.commit()
    db.refresh(part)
    response = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(alice.id),
            "body": "Interested in the intake",
            "anchor_type": "part",
            "anchor_id": str(part.id),
        },
        headers=auth_headers(bob),
    )
    assert response.status_code == 201, response.text
    assert response.json()["anchor_title"] == "5.3L intake manifold"
    # A private part can't anchor a thread to its owner.
    part.visibility = None
    db.commit()
    refused = client.post(
        "/api/messaging/threads",
        json={
            "recipient_id": str(alice.id),
            "body": "Interested",
            "anchor_type": "part",
            "anchor_id": str(part.id),
        },
        headers=auth_headers(bob),
    )
    assert refused.status_code == 404


def test_module_off_gates_messaging(client, db, alice, bob, operator):
    client.put(
        "/api/admin/modules/messaging/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    response = client.get("/api/messaging/threads", headers=auth_headers(alice))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"
    assert client.get(
        f"/api/messaging/profiles/{alice.id}", headers=auth_headers(bob)
    ).status_code == 404
