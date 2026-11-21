"""Notification channel preferences (owner item 12, 2026-10-24).

Pins: the category vocabulary + kind mapping (unmapped kinds
land in account); the defaults (email ON for support /
messages / claims / account, OFF for the routine categories);
the API (effective view, a flip round-trips, unknown category
and unbuilt channel are 422); and the inbox email hook — a
notification in an email-on category writes a notification_email
outbox row for its recipient, an email-off category writes
none, a commit=False notification emails only AFTER the
event commits (and never on rollback), and message_received
is not double-emailed (its bespoke messaging email is the one
send, gated by the same preference).
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import inbox, models as core_models
from app.modules.core import notification_prefs as prefs
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
    return _make_user(db, "TV-M-000401", "np-member@example.com", "Nina Member")


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000402", "np-op@example.com", "Omar Operator", operator=True
    )


def _outbox(db, *, kind=None, recipient=None):
    stmt = select(core_models.EmailOutbox)
    if kind is not None:
        stmt = stmt.where(core_models.EmailOutbox.kind == kind)
    if recipient is not None:
        stmt = stmt.where(core_models.EmailOutbox.recipient == recipient)
    return list(db.scalars(stmt).all())


# -- vocabulary + defaults ---------------------------------------------------


def test_kind_mapping_and_unmapped_fallback():
    assert prefs.category_for_kind(inbox.KIND_SUPPORT_TICKET_NEW) == "support"
    assert prefs.category_for_kind(inbox.KIND_MESSAGE_RECEIVED) == "messages"
    assert prefs.category_for_kind(inbox.KIND_CLAIM_DEADLINE) == "claims"
    assert prefs.category_for_kind(inbox.KIND_BORROW_RETURNED) == "borrowing"
    assert prefs.category_for_kind("warranty_request_claimed") == "dealers"
    assert prefs.category_for_kind("some_future_kind") == "account"


def test_defaults_email_on_only_for_the_nonroutine(member, db):
    view = {row["category"]: row["email_enabled"] for row in prefs.preferences_view(db, member.id)}
    assert view == {
        "support": True,
        "messages": True,
        "claims": True,
        "borrowing": False,
        "sharing": False,
        "maintenance": False,
        "community": False,
        "truck_accounts": False,
        "crew": False,
        "dealers": False,
        "flyers": False,
        # Release machinery (2026-11-08): feature announcements
        # are an inbox event — their email twin defaults OFF.
        "announcements": False,
        # Content alerts (sweep E4, 2026-11-12): the opt-in
        # new-content kinds — their email twins default OFF.
        "downloads": False,
        "prints": False,
        "account": True,
    }


# -- API ---------------------------------------------------------------------


def test_api_view_and_flip_round_trip(client, member):
    headers = auth_headers(member)
    resp = client.get("/api/core/me/notification-preferences", headers=headers)
    assert resp.status_code == 200
    by_cat = {row["category"]: row["email_enabled"] for row in resp.json()}
    assert by_cat["support"] is True and by_cat["borrowing"] is False

    resp = client.put(
        "/api/core/me/notification-preferences",
        json={"category": "support", "channel": "email", "enabled": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"category": "support", "email_enabled": False}
    resp = client.get("/api/core/me/notification-preferences", headers=headers)
    by_cat = {row["category"]: row["email_enabled"] for row in resp.json()}
    assert by_cat["support"] is False


def test_api_rejects_unknown_category_and_unbuilt_channel(client, member):
    headers = auth_headers(member)
    resp = client.put(
        "/api/core/me/notification-preferences",
        json={"category": "nope", "channel": "email", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 422
    resp = client.put(
        "/api/core/me/notification-preferences",
        json={"category": "support", "channel": "push", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 422


# -- the inbox hook ----------------------------------------------------------


def test_ticket_creation_emails_the_operator_by_default(client, member, operator, db):
    headers = auth_headers(member)
    resp = client.post(
        "/api/support/tickets",
        json={"subject": "Cannot log in", "body": "Help please"},
        headers=headers,
    )
    assert resp.status_code == 201
    rows = _outbox(db, kind="notification_email", recipient="np-op@example.com")
    assert len(rows) == 1
    assert rows[0].subject == "New support ticket"
    assert "Cannot log in" in rows[0].body


def test_ticket_creation_silent_when_operator_turned_support_email_off(
    client, member, operator, db
):
    prefs.set_channel_pref(
        db, operator.id, category="support", channel="email", enabled=False
    )
    headers = auth_headers(member)
    resp = client.post(
        "/api/support/tickets",
        json={"subject": "Cannot log in", "body": "Help please"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert _outbox(db, kind="notification_email", recipient="np-op@example.com") == []
    # The bell still shows it — email is a layer ON the inbox,
    # never a replacement.
    assert [row["kind"] for row in inbox.list_for_user(db, operator.id)] == [
        "support_ticket_new"
    ]


def test_routine_category_writes_no_email(member, db):
    inbox.create_notification(
        db,
        member.id,
        kind=inbox.KIND_BORROW_RETURNED,
        title="Returned",
        body="Sam returned your wrench.",
    )
    assert _outbox(db, kind="notification_email") == []


def test_commit_false_emails_only_after_commit(member, db):
    inbox.create_notification(
        db,
        member.id,
        kind=inbox.KIND_CLAIM_DEADLINE,
        title="Claim deadline",
        body="A deadline is near.",
        commit=False,
    )
    assert _outbox(db, kind="notification_email") == []
    db.commit()
    rows = _outbox(db, kind="notification_email", recipient="np-member@example.com")
    assert len(rows) == 1
    assert rows[0].subject == "Claim deadline"


def test_message_received_is_not_double_emailed(member, db):
    # message_received's email twin is messaging's bespoke
    # content-free send; the central hook must skip the kind or
    # the recipient would get two emails per message.
    inbox.create_notification(
        db,
        member.id,
        kind=inbox.KIND_MESSAGE_RECEIVED,
        title="New message",
        body="Sam sent you a message.",
    )
    assert _outbox(db, kind="notification_email") == []


def test_commit_false_never_emails_on_rollback(member, db):
    inbox.create_notification(
        db,
        member.id,
        kind=inbox.KIND_CLAIM_DEADLINE,
        title="Claim deadline",
        body="A deadline is near.",
        commit=False,
    )
    db.rollback()
    assert _outbox(db, kind="notification_email") == []
