"""Gap wave 1, item 6 — borrower address book.

Pins:
- owner-scoped CRUD; another owner's contact is a 404 everywhere;
- deleting a contact NEVER touches checkout history (the lends
  keep their name/contact snapshots; the link just stops
  resolving);
- pick-a-contact at check-out prefills the manual name/contact
  and stamps borrower_contact_id on the ledger row;
- the roll-up: current holds, total lends, full history from
  the ledger;
- the Nudge: composed polite text; delivered through the
  messaging module when the borrower is a linked platform user;
  returned as copy-text otherwise; refused for items not out.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, *, name="Wave User"):
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
    return _make_user(db, "TV-M-001301", "w1lender@example.com", name="Larry Lender")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-001302", "w1stranger@example.com")


@pytest.fixture()
def pal(db):
    return _make_user(db, "TV-M-001303", "w1pal@example.com", name="Paul Pal")


def _contact(client, user, **payload):
    payload.setdefault("name", "Neighbor Ned")
    resp = client.post(
        "/api/borrowing/borrowers", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tool(client, user, name="Loaner drill"):
    resp = client.post(
        "/api/inventory", json={"name": name}, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _lend(client, user, tool_id, **payload):
    payload.setdefault("item_kind", "tool")
    payload.setdefault("item_id", tool_id)
    resp = client.post(
        "/api/borrowing/checkouts", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_contact_crud_and_owner_scoping(client, owner, other):
    contact = _contact(
        client, owner, name="Neighbor Ned", contact="555-0119", notes="Two doors down"
    )
    assert contact["current_holds"] == 0 and contact["total_lends"] == 0

    listed = client.get(
        "/api/borrowing/borrowers", headers=auth_headers(owner)
    ).json()
    assert [c["name"] for c in listed] == ["Neighbor Ned"]
    assert client.get(
        "/api/borrowing/borrowers", headers=auth_headers(other)
    ).json() == []

    edited = client.put(
        f"/api/borrowing/borrowers/{contact['id']}",
        json={"contact": "ned@example.com"},
        headers=auth_headers(owner),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["contact"] == "ned@example.com"

    for verb, url in (
        ("get", f"/api/borrowing/borrowers/{contact['id']}"),
        ("put", f"/api/borrowing/borrowers/{contact['id']}"),
        ("delete", f"/api/borrowing/borrowers/{contact['id']}"),
    ):
        resp = client.request(
            verb, url, json={"name": "X"}, headers=auth_headers(other)
        )
        assert resp.status_code == 404, (verb, resp.text)

    deleted = client.delete(
        f"/api/borrowing/borrowers/{contact['id']}", headers=auth_headers(owner)
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(
        "/api/borrowing/borrowers", headers=auth_headers(owner)
    ).json() == []


def test_checkout_prefill_rollup_and_delete_keeps_history(client, owner):
    contact = _contact(client, owner, contact="555-0119")
    tool = _tool(client, owner)

    # Pick the contact: no name typed — the book fills it in.
    lend = _lend(client, owner, tool["id"], borrower_contact_id=contact["id"])
    assert lend["borrower_name"] == "Neighbor Ned"
    assert lend["borrower_contact"] == "555-0119"
    assert lend["borrower_contact_id"] == contact["id"]

    rollup = client.get(
        f"/api/borrowing/borrowers/{contact['id']}", headers=auth_headers(owner)
    ).json()
    assert rollup["contact"]["current_holds"] == 1
    assert rollup["contact"]["total_lends"] == 1
    assert [c["id"] for c in rollup["current"]] == [lend["id"]]
    assert len(rollup["history"]) == 1

    # Return it: holds drop, lends stay.
    returned = client.post(
        f"/api/borrowing/{lend['id']}/return",
        json={},
        headers=auth_headers(owner),
    )
    assert returned.status_code == 200, returned.text
    rollup = client.get(
        f"/api/borrowing/borrowers/{contact['id']}", headers=auth_headers(owner)
    ).json()
    assert rollup["contact"]["current_holds"] == 0
    assert rollup["contact"]["total_lends"] == 1

    # Delete the contact: the LEDGER is untouched — the lend
    # still shows its snapshots in the item's history.
    client.delete(
        f"/api/borrowing/borrowers/{contact['id']}", headers=auth_headers(owner)
    )
    lending = client.get(
        f"/api/borrowing/items/tool/{tool['id']}", headers=auth_headers(owner)
    ).json()
    history = lending["history"]
    assert len(history) == 1
    assert history[0]["borrower_name"] == "Neighbor Ned"
    assert history[0]["borrower_contact"] == "555-0119"


def test_nudge_copy_text_for_unlinked_borrower(client, owner):
    contact = _contact(client, owner)
    tool = _tool(client, owner)
    due = datetime.now(timezone.utc) - timedelta(days=3)
    lend = _lend(
        client,
        owner,
        tool["id"],
        borrower_contact_id=contact["id"],
        due_at=due.isoformat(),
    )
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered_via"] == "copy"
    assert "Loaner drill" in body["message"]
    assert "Neighbor Ned" in body["message"]
    assert "due back" in body["message"]


def test_nudge_delivered_via_messaging_for_linked_borrower(client, owner, pal, db):
    # Link the pal as a peer counterparty (accepted share both
    # borrowing + messaging need a relationship): lend to the
    # linked user directly, which stamps borrower_user_id.
    from app.modules.core import peer_sharing

    # Peer grants are the borrowing counterparty seam; emulate an
    # accepted grant directly in the ledger's own tables.
    grant = core_models.PeerShare(
        owner_id=pal.id,
        viewer_user_id=owner.id,
        status="accepted",
    )
    db.add(grant)
    db.commit()

    tool = _tool(client, owner)
    lend = _lend(client, owner, tool["id"], borrower_user_id=str(pal.id))
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered_via"] == "message"
    assert body["thread_id"]

    # The pal can open the conversation and read the nudge in it
    # (it arrives as a message REQUEST — first contact from the
    # lender — which is the messaging system's own rule).
    thread = client.get(
        f"/api/messaging/threads/{body['thread_id']}",
        headers=auth_headers(pal),
    )
    assert thread.status_code == 200, thread.text
    bodies = [m["body"] for m in thread.json()["messages"]]
    assert any("Loaner drill" in text for text in bodies)


def _park_messaging(db, enabled=False):
    from app.modules.core import module_control

    module_control.set_global_enabled(db, "messaging", enabled)
    db.commit()
    assert module_control.globally_enabled(db, "messaging") is enabled


def _thread_rows(db):
    from sqlalchemy import func, select

    from app.modules.messaging import models as messaging_models

    threads = db.scalar(select(func.count()).select_from(messaging_models.MessageThread))
    messages = db.scalar(select(func.count()).select_from(messaging_models.Message))
    return threads, messages


def _bell_count(db, user_id):
    from sqlalchemy import func, select

    return db.scalar(
        select(func.count())
        .select_from(core_models.Notification)
        .where(core_models.Notification.user_id == user_id)
    )


def _linked_lend(client, owner, pal, db):
    grant = core_models.PeerShare(
        owner_id=pal.id, viewer_user_id=owner.id, status="accepted"
    )
    db.add(grant)
    db.commit()
    tool = _tool(client, owner)
    return _lend(client, owner, tool["id"], borrower_user_id=str(pal.id))


def test_nudge_copy_text_and_no_writes_when_messaging_parked(
    client, owner, pal, db
):
    """Messaging PARKED via the operator switchboard (owner
    directive, 2026-10-31 hidden-modules list): the nudge must
    not write into the parked module's tables or claim delivery
    — the owner gets the copy-text, exactly as for an unlinked
    borrower. Unparking restores message delivery unchanged."""
    lend = _linked_lend(client, owner, pal, db)

    _park_messaging(db)
    assert _thread_rows(db) == (0, 0)
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered_via"] == "copy"
    assert body["thread_id"] is None
    assert "Loaner drill" in body["message"]
    # Nothing written into the parked module; no bell for the pal.
    assert _thread_rows(db) == (0, 0)
    assert _bell_count(db, pal.id) == 0

    # Unpark: the very same lend delivers via messaging again.
    _park_messaging(db, enabled=True)
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered_via"] == "message"
    assert body["thread_id"]
    assert _thread_rows(db) == (1, 1)


def test_nudge_parked_with_existing_accepted_thread_writes_nothing(
    client, owner, pal, db
):
    """The pair already has an ACCEPTED thread from before the
    park: a parked-era nudge must still fall back to copy-text —
    no extra message in the thread, and no bell notification
    whose click-through would 403 into the parked module."""
    from sqlalchemy import select

    from app.modules.messaging import models as messaging_models

    lend = _linked_lend(client, owner, pal, db)
    first = client.post(
        f"/api/borrowing/{lend['id']}/nudge", json={}, headers=auth_headers(owner)
    ).json()
    assert first["delivered_via"] == "message"
    thread = db.get(messaging_models.MessageThread, uuid.UUID(first["thread_id"]))
    thread.status = "accepted"
    state = list(
        db.scalars(
            select(messaging_models.MessageThreadState).where(
                messaging_models.MessageThreadState.thread_id == thread.id,
                messaging_models.MessageThreadState.user_id == pal.id,
            )
        ).all()
    )
    assert len(state) == 1
    msg = list(
        db.scalars(
            select(messaging_models.Message).where(
                messaging_models.Message.thread_id == thread.id
            )
        ).all()
    )[0]
    state[0].last_read_seq = msg.seq
    db.commit()
    bells_before = _bell_count(db, pal.id)

    _park_messaging(db)
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered_via"] == "copy"
    assert body["thread_id"] is None
    assert _thread_rows(db) == (1, 1)
    assert _bell_count(db, pal.id) == bells_before


def test_nudge_refused_when_not_out(client, owner):
    contact = _contact(client, owner)
    tool = _tool(client, owner)
    lend = _lend(client, owner, tool["id"], borrower_contact_id=contact["id"])
    client.post(
        f"/api/borrowing/{lend['id']}/return",
        json={},
        headers=auth_headers(owner),
    )
    resp = client.post(
        f"/api/borrowing/{lend['id']}/nudge",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_export_carries_borrowers(client, owner):
    _contact(client, owner, name="Exported Ned")
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    import io
    import json
    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    borrowers = json.loads(archive.read("borrowers.json"))
    assert [b["name"] for b in borrowers] == ["Exported Ned"]
    # The rest of the wave rides too.
    assert "loss_reports.json" in archive.namelist()
    assert "categories.json" in archive.namelist()
