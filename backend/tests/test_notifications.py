"""In-app notifications (the inbox behind GET /api/core/notifications).

Pins: notifications are generated ONLY for the peer-sharing
lifecycle's cross-party events — invite received (invitee), invite
accepted (owner), invite declined (owner) — in the same flow as the
event; a repeated/idempotent invite does NOT duplicate; a
pre-signup email invite notifies nobody (no inbox exists yet);
reads are owner-scoped (a foreign id is a 404, no oracle); read-all
touches only the caller's rows; the list is newest-first over a
30-DAY window (gap wave 1, 2026-10-20 — everything inside 30 days
returns, older rows fall out); and every row carries the header
ticker's contract keys (id + text, optional tone) in a bare
top-level array.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture(autouse=True)
def _inbox_tables(db):
    bind = db.get_bind()
    core_models.PeerShare.__table__.create(bind=bind, checkfirst=True)
    core_models.PeerShareExclusion.__table__.create(bind=bind, checkfirst=True)
    core_models.Notification.__table__.create(bind=bind, checkfirst=True)


def _make_user(db, account_number: str, email: str, name: str):
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
    return _make_user(db, "TV-M-000201", "owner@example.com", "Olive Owner")


@pytest.fixture()
def invitee(db):
    return _make_user(db, "TV-M-000202", "invitee@example.com", "Ian Invitee")


def _inbox(client, user) -> list[dict]:
    resp = client.get("/api/core/notifications", headers=auth_headers(user))
    assert resp.status_code == 200
    return resp.json()


def _invite(client, owner, **payload) -> str:
    resp = client.post(
        "/api/core/sharing/peer/invite",
        json=payload,
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -- generation ------------------------------------------------------------------


def test_invite_by_account_number_notifies_invitee_only(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)

    inbox = _inbox(client, invitee)
    assert len(inbox) == 1
    note = inbox[0]
    assert note["kind"] == "peer_invite_received"
    assert "invited you to see their tool list" in note["text"]
    assert "Olive Owner" in note["text"]
    assert note["read"] is False
    assert note["read_at"] is None
    assert note["data"]["actor_account_number"] == owner.account_number
    # The owner hears nothing about their own action.
    assert _inbox(client, owner) == []


def test_invite_by_email_to_existing_account_notifies(client, owner, invitee):
    _invite(client, owner, email=invitee.email)
    inbox = _inbox(client, invitee)
    assert [n["kind"] for n in inbox] == ["peer_invite_received"]


def test_repeat_invite_does_not_duplicate_notification(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    _invite(client, owner, account_number=invitee.account_number)
    assert len(_inbox(client, invitee)) == 1


def test_pre_signup_email_invite_notifies_nobody(client, owner, invitee):
    _invite(client, owner, email="ghost@example.com")
    assert _inbox(client, owner) == []
    assert _inbox(client, invitee) == []


def test_accept_notifies_owner(client, owner, invitee):
    grant_id = _invite(client, owner, account_number=invitee.account_number)
    resp = client.post(
        f"/api/core/sharing/peer/{grant_id}/accept", headers=auth_headers(invitee)
    )
    assert resp.status_code == 204

    inbox = _inbox(client, owner)
    assert len(inbox) == 1
    note = inbox[0]
    assert note["kind"] == "peer_invite_accepted"
    assert note["tone"] == "success"
    assert "Ian Invitee" in note["text"]
    assert "accepted your tool-list invite" in note["text"]
    # The invitee gains nothing new from their own acceptance.
    assert [n["kind"] for n in _inbox(client, invitee)] == ["peer_invite_received"]


def test_decline_notifies_owner(client, owner, invitee):
    grant_id = _invite(client, owner, account_number=invitee.account_number)
    resp = client.post(
        f"/api/core/sharing/peer/{grant_id}/decline", headers=auth_headers(invitee)
    )
    assert resp.status_code == 204

    inbox = _inbox(client, owner)
    assert [n["kind"] for n in inbox] == ["peer_invite_declined"]
    assert "declined your tool-list invite" in inbox[0]["text"]


def test_revoke_and_leave_generate_nothing(client, owner, invitee):
    grant_id = _invite(client, owner, account_number=invitee.account_number)
    client.post(
        f"/api/core/sharing/peer/{grant_id}/accept", headers=auth_headers(invitee)
    )
    assert len(_inbox(client, owner)) == 1  # the acceptance
    client.post(
        f"/api/core/sharing/peer/{grant_id}/leave", headers=auth_headers(invitee)
    )
    # Leave/revoke are the actor ending their own view — not events
    # the brief generates inbox rows for.
    assert len(_inbox(client, owner)) == 1
    assert len(_inbox(client, invitee)) == 1


# -- read flows -------------------------------------------------------------------


def test_mark_read_flow(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    note = _inbox(client, invitee)[0]

    resp = client.post(
        f"/api/core/notifications/{note['id']}/read", headers=auth_headers(invitee)
    )
    assert resp.status_code == 204

    after = _inbox(client, invitee)
    assert after[0]["read"] is True
    assert after[0]["read_at"] is not None
    # Idempotent: reading again is still a 204.
    resp = client.post(
        f"/api/core/notifications/{note['id']}/read", headers=auth_headers(invitee)
    )
    assert resp.status_code == 204


def test_mark_read_foreign_id_is_404(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    note = _inbox(client, invitee)[0]
    resp = client.post(
        f"/api/core/notifications/{note['id']}/read", headers=auth_headers(owner)
    )
    assert resp.status_code == 404
    # And the row is untouched.
    assert _inbox(client, invitee)[0]["read"] is False


def test_read_all_marks_only_mine(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    grant_id = _invite(client, invitee, account_number=owner.account_number)
    client.post(
        f"/api/core/sharing/peer/{grant_id}/accept", headers=auth_headers(owner)
    )
    # invitee: received(owner's) + accepted(owner accepted theirs) = 2
    # owner: received(invitee's) = 1... plus accepted? No — owner was
    # the accepter of invitee's grant? grant above: invitee invited
    # owner; owner accepted → invitee hears "accepted". Both have 2/1.
    resp = client.post(
        "/api/core/notifications/read-all", headers=auth_headers(invitee)
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2
    assert all(n["read"] for n in _inbox(client, invitee))
    assert not all(n["read"] for n in _inbox(client, owner))
    # Second call: nothing left to change.
    resp = client.post(
        "/api/core/notifications/read-all", headers=auth_headers(invitee)
    )
    assert resp.json()["updated"] == 0


# -- list shape: ticker contract, order, cap ---------------------------------------


def test_list_shape_matches_ticker_contract(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    resp = client.get("/api/core/notifications", headers=auth_headers(invitee))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)  # the ticker requires a bare array
    item = data[0]
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["text"], str) and item["text"]
    assert item["tone"] is None or isinstance(item["tone"], str)


def test_list_is_newest_first_over_the_30_day_window(client, db, invitee):
    # Gap wave 1 (2026-10-20, DELIBERATE pin change): the window is
    # 30 days, not a 20-row cap — a 25-item history inside the
    # window ALL returns, newest first; a 31-day-old row is out.
    base = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(25):
        db.add(
            core_models.Notification(
                user_id=invitee.id,
                kind="peer_invite_received",
                title=f"N{i}",
                body=f"body {i}",
                data={},
                created_at=base + timedelta(minutes=i),
            )
        )
    db.add(
        core_models.Notification(
            user_id=invitee.id,
            kind="peer_invite_received",
            title="ancient",
            body="body old",
            data={},
            created_at=datetime.now(timezone.utc) - timedelta(days=31),
        )
    )
    db.commit()
    inbox = _inbox(client, invitee)
    assert len(inbox) == 25
    assert inbox[0]["body"] == "body 24"  # newest first
    assert inbox[-1]["body"] == "body 0"
    assert all(row["body"] != "body old" for row in inbox)


def test_list_paging_through_the_window(client, db, invitee):
    base = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(7):
        db.add(
            core_models.Notification(
                user_id=invitee.id,
                kind="peer_invite_received",
                title=f"P{i}",
                body=f"page {i}",
                data={},
                created_at=base + timedelta(minutes=i),
            )
        )
    db.commit()
    headers = auth_headers(invitee)
    page1 = client.get(
        "/api/core/notifications?limit=3&offset=0", headers=headers
    ).json()
    page2 = client.get(
        "/api/core/notifications?limit=3&offset=3", headers=headers
    ).json()
    page3 = client.get(
        "/api/core/notifications?limit=3&offset=6", headers=headers
    ).json()
    assert [r["body"] for r in page1] == ["page 6", "page 5", "page 4"]
    assert [r["body"] for r in page2] == ["page 3", "page 2", "page 1"]
    assert [r["body"] for r in page3] == ["page 0"]


def test_inbox_requires_auth(client):
    assert client.get("/api/core/notifications").status_code == 401
    assert client.post("/api/core/notifications/read-all").status_code == 401


# -- delete flows (2026-10-24) ------------------------------------------------------


def test_delete_own_notification(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    note = _inbox(client, invitee)[0]

    resp = client.delete(
        f"/api/core/notifications/{note['id']}", headers=auth_headers(invitee)
    )
    assert resp.status_code == 204
    # It's gone from the list — and deleting it again is a 404.
    assert _inbox(client, invitee) == []
    resp = client.delete(
        f"/api/core/notifications/{note['id']}", headers=auth_headers(invitee)
    )
    assert resp.status_code == 404


def test_delete_foreign_notification_is_404_and_row_survives(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    note = _inbox(client, invitee)[0]

    resp = client.delete(
        f"/api/core/notifications/{note['id']}", headers=auth_headers(owner)
    )
    assert resp.status_code == 404
    # The row survives, untouched, in the invitee's inbox.
    after = _inbox(client, invitee)
    assert len(after) == 1
    assert after[0]["id"] == note["id"]


def test_delete_requires_auth(client, owner, invitee):
    _invite(client, owner, account_number=invitee.account_number)
    note = _inbox(client, invitee)[0]
    assert client.delete(f"/api/core/notifications/{note['id']}").status_code == 401
