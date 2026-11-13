"""Support tickets (support module, 2026-10-24).

Pins: a member opens a ticket and the first message rides the
creation; the member face is owner-scoped (a foreign id is a 404
on read AND reply — no oracle); the list is newest-activity
first with message_count + last_message_preview; the operator
desk (operator-only, /api/admin/support/*) sees every ticket
with the owner's identity; an operator reply sets
"under_review" and lands a support_reply notification in the
owner's inbox; an operator status change lands support_status;
a member reply on an under-review ticket hands it back to
"open"; a closed ticket refuses member replies with 422;
validation refuses empty / oversized subject and body with
422; anonymous calls are 401.

Operator-side notifications (Phase 2, 2026-10-24): creating a
ticket lands support_ticket_new in EVERY operator's inbox
(sender + subject in the copy, ticket id in the data); a member
follow-up lands support_ticket_reply the same way; nobody is
ever notified about their own action — an operator working
their own ticket stays silent on the operator kinds.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number: str, email: str, name: str, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def member(db):
    return _make_user(db, "TV-M-000301", "member@example.com", "Manny Member")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "other@example.com", "Olga Other")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000309", "desk@example.com", "Dee Desk", operator=True)


def _create(client, user, subject="Printer is broken", body="It jams on page two."):
    resp = client.post(
        "/api/support/tickets",
        json={"subject": subject, "body": body},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _inbox(client, user) -> list[dict]:
    resp = client.get("/api/core/notifications", headers=auth_headers(user))
    assert resp.status_code == 200
    return resp.json()


# -- member face: create / list / detail -------------------------------------------


def test_create_list_detail_round_trip(client, member):
    created = _create(client, member)
    assert created["subject"] == "Printer is broken"
    assert created["status"] == "open"
    assert created["message_count"] == 1
    assert created["last_message_preview"] == "It jams on page two."

    listing = client.get("/api/support/tickets", headers=auth_headers(member))
    assert listing.status_code == 200
    rows = listing.json()
    assert [r["id"] for r in rows] == [created["id"]]
    row = rows[0]
    assert row["subject"] == "Printer is broken"
    assert row["status"] == "open"
    assert row["message_count"] == 1
    assert row["last_message_preview"] == "It jams on page two."
    assert "messages" not in row  # the list shape carries no thread

    detail = client.get(
        f"/api/support/tickets/{created['id']}", headers=auth_headers(member)
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == created["id"]
    assert len(body["messages"]) == 1
    message = body["messages"][0]
    assert message["author_kind"] == "user"
    assert message["body"] == "It jams on page two."


def test_first_message_rides_creation(client, member):
    created = _create(client, member, body="The very first words.")
    assert len(created["messages"]) == 1
    assert created["messages"][0]["body"] == "The very first words."
    assert created["messages"][0]["author_kind"] == "user"


def test_list_is_newest_activity_first(client, member):
    first = _create(client, member, subject="First", body="one")
    second = _create(client, member, subject="Second", body="two")
    rows = client.get("/api/support/tickets", headers=auth_headers(member)).json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]]
    # A reply bumps the older ticket back to the top.
    resp = client.post(
        f"/api/support/tickets/{first['id']}/messages",
        json={"body": "Adding detail."},
        headers=auth_headers(member),
    )
    assert resp.status_code == 200
    rows = client.get("/api/support/tickets", headers=auth_headers(member)).json()
    assert [r["id"] for r in rows] == [first["id"], second["id"]]
    assert rows[0]["message_count"] == 2
    assert rows[0]["last_message_preview"] == "Adding detail."


def test_my_tickets_only_shows_mine(client, member, other):
    _create(client, member)
    _create(client, other, subject="Not yours", body="private")
    rows = client.get("/api/support/tickets", headers=auth_headers(member)).json()
    assert len(rows) == 1
    assert rows[0]["subject"] == "Printer is broken"


# -- ownership: no oracle ------------------------------------------------------------


def test_foreign_ticket_get_and_reply_are_404(client, member, other):
    created = _create(client, member)
    resp = client.get(
        f"/api/support/tickets/{created['id']}", headers=auth_headers(other)
    )
    assert resp.status_code == 404
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": "Sneaking in."},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404
    # The ticket is untouched.
    detail = client.get(
        f"/api/support/tickets/{created['id']}", headers=auth_headers(member)
    ).json()
    assert len(detail["messages"]) == 1


def test_unknown_ticket_is_404(client, member):
    missing = uuid.uuid4()
    assert (
        client.get(
            f"/api/support/tickets/{missing}", headers=auth_headers(member)
        ).status_code
        == 404
    )


# -- operator desk ---------------------------------------------------------------------


def test_operator_list_sees_ticket_with_owner_identity(client, member, operator):
    created = _create(client, member)
    resp = client.get("/api/admin/support/tickets", headers=auth_headers(operator))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == created["id"]
    assert row["user_name"] == "Manny Member"
    assert row["user_email"] == "member@example.com"
    assert row["user_account_number"] == member.account_number
    assert row["message_count"] == 1
    assert row["last_message_preview"] == "It jams on page two."
    # The status filter agrees.
    filtered = client.get(
        "/api/admin/support/tickets?status=open", headers=auth_headers(operator)
    ).json()
    assert [r["id"] for r in filtered] == [created["id"]]
    filtered = client.get(
        "/api/admin/support/tickets?status=closed", headers=auth_headers(operator)
    ).json()
    assert filtered == []


def test_operator_detail_has_owner_identity_and_thread(client, member, operator):
    created = _create(client, member)
    resp = client.get(
        f"/api/admin/support/tickets/{created['id']}",
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_email"] == "member@example.com"
    assert body["user_account_number"] == member.account_number
    assert [m["author_kind"] for m in body["messages"]] == ["user"]


def test_operator_reply_marks_under_review_and_notifies_owner(client, member, operator):
    created = _create(client, member)
    resp = client.post(
        f"/api/admin/support/tickets/{created['id']}/messages",
        json={"body": "Try a new toner cartridge."},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "under_review"
    assert [m["author_kind"] for m in body["messages"]] == ["user", "operator"]
    assert body["messages"][-1]["body"] == "Try a new toner cartridge."

    inbox = _inbox(client, member)
    notes = [n for n in inbox if n["kind"] == "support_reply"]
    assert len(notes) == 1
    assert notes[0]["data"]["ticket_id"] == created["id"]
    assert "Printer is broken" in notes[0]["text"]
    # The operator hears nothing about their OWN action: their
    # inbox holds only the creation fan-out, no support_reply.
    op_kinds = [n["kind"] for n in _inbox(client, operator)]
    assert op_kinds == ["support_ticket_new"]


def test_operator_status_change_notifies_owner(client, member, operator):
    created = _create(client, member)
    resp = client.post(
        f"/api/admin/support/tickets/{created['id']}/status",
        json={"status": "closed"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    notes = [n for n in _inbox(client, member) if n["kind"] == "support_status"]
    assert len(notes) == 1
    assert notes[0]["data"]["ticket_id"] == created["id"]
    assert "Printer is broken" in notes[0]["text"]
    assert "Closed" in notes[0]["text"]


def test_user_reply_on_under_review_ticket_returns_to_open(client, member, operator):
    created = _create(client, member)
    client.post(
        f"/api/admin/support/tickets/{created['id']}/messages",
        json={"body": "Fixed it?"},
        headers=auth_headers(operator),
    )
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": "Still jams, sorry."},
        headers=auth_headers(member),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    assert [m["author_kind"] for m in resp.json()["messages"]] == [
        "user",
        "operator",
        "user",
    ]


def test_closed_ticket_refuses_user_reply(client, member, operator):
    created = _create(client, member)
    client.post(
        f"/api/admin/support/tickets/{created['id']}/status",
        json={"status": "closed"},
        headers=auth_headers(operator),
    )
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": "Wait, one more thing."},
        headers=auth_headers(member),
    )
    assert resp.status_code == 422


# -- operator-side notifications (Phase 2) ---------------------------------------------


@pytest.fixture()
def operator_two(db):
    return _make_user(db, "TV-M-000310", "desk2@example.com", "Dan Desk", operator=True)


def test_create_ticket_notifies_every_operator(client, member, other, operator, operator_two):
    created = _create(client, member)
    for op in (operator, operator_two):
        notes = [n for n in _inbox(client, op) if n["kind"] == "support_ticket_new"]
        assert len(notes) == 1
        assert notes[0]["data"]["ticket_id"] == created["id"]
        assert "Manny Member" in notes[0]["text"]
        assert "Printer is broken" in notes[0]["text"]
    # Non-operators hear nothing, and the owner gets no
    # notification about their own new ticket.
    assert _inbox(client, other) == []
    assert _inbox(client, member) == []


def test_user_followup_notifies_operators(client, member, operator):
    created = _create(client, member)
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": "More detail from me."},
        headers=auth_headers(member),
    )
    assert resp.status_code == 200
    notes = [n for n in _inbox(client, operator) if n["kind"] == "support_ticket_reply"]
    assert len(notes) == 1
    assert notes[0]["data"]["ticket_id"] == created["id"]
    assert "Manny Member" in notes[0]["text"]
    assert "Printer is broken" in notes[0]["text"]
    # The member is never notified about their own follow-up.
    assert _inbox(client, member) == []


def test_operator_actor_is_never_self_notified(client, operator, operator_two):
    # An operator opens a ticket of their own: the OTHER
    # operator hears about it; the actor does not.
    created = _create(client, operator, subject="Desk needs a key", body="Spare key?")
    assert _inbox(client, operator) == []
    notes = [n for n in _inbox(client, operator_two) if n["kind"] == "support_ticket_new"]
    assert len(notes) == 1
    assert notes[0]["data"]["ticket_id"] == created["id"]
    # Same on a follow-up: actor silent, the other operator pings.
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": "Adding the key number."},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert _inbox(client, operator) == []
    notes = [n for n in _inbox(client, operator_two) if n["kind"] == "support_ticket_reply"]
    assert len(notes) == 1
    assert notes[0]["data"]["ticket_id"] == created["id"]


def test_status_notification_uses_display_name(client, member, operator):
    created = _create(client, member)
    resp = client.post(
        f"/api/admin/support/tickets/{created['id']}/status",
        json={"status": "under_review"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "under_review"
    notes = [n for n in _inbox(client, member) if n["kind"] == "support_status"]
    assert len(notes) == 1
    assert "Under Review" in notes[0]["text"]
    assert "under_review" not in notes[0]["text"]


def test_stats_counts_unclosed_tickets(client, member, operator):
    # Phase 3 panel stat: open + under_review count, closed not.
    first = _create(client, member)
    _create(client, member, subject="Second", body="two")
    stats = client.get("/api/support/stats", headers=auth_headers(member)).json()
    assert stats == {"open_tickets_count": 2}
    client.post(
        f"/api/admin/support/tickets/{first['id']}/messages",
        json={"body": "Looking at it."},
        headers=auth_headers(operator),
    )
    stats = client.get("/api/support/stats", headers=auth_headers(member)).json()
    assert stats == {"open_tickets_count": 2}  # under review still counts
    client.post(
        f"/api/admin/support/tickets/{first['id']}/status",
        json={"status": "closed"},
        headers=auth_headers(operator),
    )
    stats = client.get("/api/support/stats", headers=auth_headers(member)).json()
    assert stats == {"open_tickets_count": 1}
    # Owner-scoped: the operator's own count is their own (zero).
    stats = client.get("/api/support/stats", headers=auth_headers(operator)).json()
    assert stats == {"open_tickets_count": 0}


def test_answered_status_value_is_refused(client, member, operator):
    created = _create(client, member)
    resp = client.post(
        f"/api/admin/support/tickets/{created['id']}/status",
        json={"status": "answered"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 422


# -- gates -------------------------------------------------------------------------------


def test_non_operator_cannot_use_the_desk(client, member):
    created = _create(client, member)
    headers = auth_headers(member)
    assert client.get("/api/admin/support/tickets", headers=headers).status_code == 403
    assert (
        client.get(
            f"/api/admin/support/tickets/{created['id']}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/support/tickets/{created['id']}/messages",
            json={"body": "I am not the desk."},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/support/tickets/{created['id']}/status",
            json={"status": "closed"},
            headers=headers,
        ).status_code
        == 403
    )


def test_unauthenticated_is_401(client, member):
    created = _create(client, member)
    assert client.get("/api/support/tickets").status_code == 401
    assert (
        client.post(
            "/api/support/tickets", json={"subject": "Hi", "body": "There."}
        ).status_code
        == 401
    )
    assert (
        client.get(f"/api/support/tickets/{created['id']}").status_code == 401
    )
    assert client.get("/api/admin/support/tickets").status_code == 401


# -- validation ----------------------------------------------------------------------------


def test_validation_refuses_empty_and_oversized(client, member):
    headers = auth_headers(member)
    for payload in (
        {"subject": "", "body": "Something."},
        {"subject": "   ", "body": "Something."},
        {"subject": "A subject", "body": ""},
        {"subject": "A subject", "body": "   "},
        {"subject": "x" * 201, "body": "Something."},
        {"subject": "A subject", "body": "x" * 10001},
    ):
        resp = client.post("/api/support/tickets", json=payload, headers=headers)
        assert resp.status_code == 422, (payload, resp.text)
    # Nothing was created by the refused calls.
    assert client.get("/api/support/tickets", headers=headers).json() == []

    created = _create(client, member)
    resp = client.post(
        f"/api/support/tickets/{created['id']}/messages",
        json={"body": ""},
        headers=headers,
    )
    assert resp.status_code == 422
