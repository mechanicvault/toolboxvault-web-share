"""Borrowing (module doctrine build, 2026-10-18): the check-out
ledger converted from the app's embedded lending (feature map
row 28) — one row per lend, never deleted, state transitions only.

These pin:
- the state machine: owner checkout enters at checked_out; a peer
  request waits in requested until the owner decides; decline and
  cancel are terminal; either party can mark returned and the row
  records who;
- ONE active lend per item (tool AND battery), service error plus
  the database's partial unique index as backstop;
- the request gates: accepted grant required (non-grantee = 404),
  peer-excluded items are unrequestable (404), inactive
  (over-plan-limit) items cannot START a lend but a running lend
  can always be returned;
- notifications exactly once per transition, to the right party;
- the module gate: globally off or group-unassigned = 403
  module_unavailable, and my-modules nav exclusion follows;
- the Checked Out stat counts the owner's live checkouts.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.billing import entitlements
from app.modules.borrowing import models as borrowing_models
from app.modules.borrowing import service
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _make_user(db, account_number, email, account_types, name):
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
    return _make_user(db, "TV-M-000201", "owner@example.com", [MECHANIC], "Olive Owner")


@pytest.fixture()
def borrower(db):
    return _make_user(db, "TV-M-000202", "borrower@example.com", [MECHANIC], "Bob Borrower")


@pytest.fixture()
def stranger(db):
    return _make_user(db, "TV-M-000203", "stranger@example.com", [MECHANIC], "Sue Stranger")


@pytest.fixture()
def shop_user(db):
    return _make_user(db, "TV-S-000204", "shop@example.com", [SHOP], "Sam Shop")


@pytest.fixture()
def dealer(db):
    return _make_user(db, "TV-D-000205", "dealer@example.com", [DEALER], "Dee Dealer")


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=name,
        brand=overrides.pop("brand", "Snap-on"),
        model=overrides.pop("model", "CT9075"),
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 5.0 pack", **overrides):
    battery = inventory_models.Battery(
        owner_id=owner.id, name=name, brand="Milwaukee", **overrides
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _grant(db, owner, viewer):
    """An accepted peer grant: owner's list is shared with viewer."""
    grant = core_models.PeerShare(
        owner_id=owner.id, viewer_user_id=viewer.id, status="accepted"
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


def _checkout(client, user, **payload):
    return client.post(
        "/api/borrowing/checkouts", json=payload, headers=auth_headers(user)
    )


def _request(client, user, **payload):
    return client.post(
        "/api/borrowing/requests", json=payload, headers=auth_headers(user)
    )


def _notifications(db, user_id):
    return (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == user_id)
        .all()
    )


# -- owner-initiated checkout -----------------------------------------------------


def test_owner_checkout_manual_borrower(client, db, owner):
    tool = _tool(db, owner)
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_name="Neighbor Nate",
        borrower_contact="555-0100",
        due_at=(NOW + timedelta(days=7)).isoformat(),
        notes="For the fence job",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "checked_out"
    assert body["borrower_name"] == "Neighbor Nate"
    assert body["borrower_user_id"] is None
    assert body["checked_out_at"] is not None
    assert body["item_name"] == "Impact wrench"
    assert body["overdue"] is False

    stats = client.get("/api/borrowing/stats", headers=auth_headers(owner))
    assert stats.json() == {"checked_out_count": 1, "borrowed_by_me_count": 0}

    lending = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(owner)
    )
    assert lending.status_code == 200
    assert lending.json()["current"]["id"] == body["id"]
    assert len(lending.json()["history"]) == 1


def test_owner_checkout_requires_a_borrower(client, db, owner):
    tool = _tool(db, owner)
    resp = _checkout(client, owner, item_kind="tool", item_id=str(tool.id))
    assert resp.status_code == 422


def test_owner_checkout_linked_counterparty(client, db, owner, borrower):
    _grant(db, owner, borrower)  # I share with them: linked
    tool = _tool(db, owner)
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_user_id=str(borrower.id),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["borrower_name"] == "Bob Borrower"

    overview = client.get("/api/borrowing/overview", headers=auth_headers(borrower))
    assert overview.json()["counts"]["borrowed"] == 1
    assert overview.json()["borrowed_by_me"][0]["item_name"] == "Impact wrench"


def test_owner_checkout_counterparty_via_reverse_grant(client, db, owner, borrower):
    _grant(db, borrower, owner)  # THEY share with me: also linked
    tool = _tool(db, owner)
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_user_id=str(borrower.id),
    )
    assert resp.status_code == 201, resp.text


def test_owner_checkout_unlinked_user_refused(client, db, owner, stranger):
    tool = _tool(db, owner)
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_user_id=str(stranger.id),
    )
    assert resp.status_code == 422


def test_owner_checkout_self_refused(client, db, owner):
    tool = _tool(db, owner)
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_user_id=str(owner.id),
    )
    assert resp.status_code == 422


def test_owner_checkout_foreign_item_404(client, db, owner, borrower):
    tool = _tool(db, borrower)  # not the owner's item
    resp = _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_name="Nate",
    )
    assert resp.status_code == 404


def test_counterparties_endpoint(client, db, owner, borrower, stranger):
    _grant(db, owner, borrower)
    resp = client.get("/api/borrowing/counterparties", headers=auth_headers(owner))
    assert resp.status_code == 200
    people = resp.json()
    assert [p["name"] for p in people] == ["Bob Borrower"]
    assert people[0]["account_number"] == "TV-M-000202"


# -- one active lend per item -------------------------------------------------------


def test_double_checkout_blocked_tool(client, db, owner):
    tool = _tool(db, owner)
    first = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="A"
    )
    assert first.status_code == 201
    second = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="B"
    )
    assert second.status_code == 422
    assert "already checked out" in second.json()["detail"]


def test_double_checkout_blocked_battery(client, db, owner):
    battery = _battery(db, owner)
    first = _checkout(
        client, owner, item_kind="battery", item_id=str(battery.id), borrower_name="A"
    )
    assert first.status_code == 201, first.text
    second = _checkout(
        client, owner, item_kind="battery", item_id=str(battery.id), borrower_name="B"
    )
    assert second.status_code == 422


def test_pending_request_blocks_second_request(client, db, owner, borrower, stranger):
    _grant(db, owner, borrower)
    _grant(db, owner, stranger)
    tool = _tool(db, owner)
    first = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert first.status_code == 201, first.text
    second = _request(
        client, stranger, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert second.status_code == 422


def test_partial_unique_index_backstop(db, owner):
    tool = _tool(db, owner)
    for state in ("requested", "checked_out"):
        db.add(
            borrowing_models.Checkout(
                owner_id=owner.id,
                item_kind="tool",
                item_id=tool.id,
                item_name=tool.name,
                borrower_name="A",
                state=state,
            )
        )
        db.commit()  # the first active row is fine
        db.add(
            borrowing_models.Checkout(
                owner_id=owner.id,
                item_kind="tool",
                item_id=tool.id,
                item_name=tool.name,
                borrower_name="B",
                state=state,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()  # a second ACTIVE row for the same item is not
        db.rollback()
        db.query(borrowing_models.Checkout).delete()
        db.commit()


def test_return_frees_the_item(client, db, owner):
    tool = _tool(db, owner)
    first = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="A"
    ).json()
    returned = client.post(
        f"/api/borrowing/{first['id']}/return", headers=auth_headers(owner)
    )
    assert returned.status_code == 200
    second = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="B"
    )
    assert second.status_code == 201


# -- peer request flow ----------------------------------------------------------------


def test_request_approve_cycle(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    resp = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "requested"
    assert body["checked_out_at"] is None

    # The owner was notified, exactly once.
    notes = _notifications(db, owner.id)
    assert [n.kind for n in notes] == ["borrow_requested"]

    # The owner's queue shows it; the borrower's too.
    owner_view = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    assert owner_view["counts"]["pending_requests"] == 1
    assert owner_view["requests_for_me"][0]["borrower_name"] == "Bob Borrower"
    borrower_view = client.get(
        "/api/borrowing/overview", headers=auth_headers(borrower)
    ).json()
    assert len(borrower_view["my_requests"]) == 1

    approved = client.post(
        f"/api/borrowing/{body['id']}/approve", headers=auth_headers(owner)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "checked_out"
    assert approved.json()["checked_out_at"] is not None
    assert approved.json()["decided_at"] is not None

    notes = _notifications(db, borrower.id)
    assert [n.kind for n in notes] == ["borrow_approved"]

    stats = client.get("/api/borrowing/stats", headers=auth_headers(owner))
    assert stats.json() == {"checked_out_count": 1, "borrowed_by_me_count": 0}
    # The other side of the same lend (Phase 3): the borrower
    # holds one item that is not theirs.
    bstats = client.get("/api/borrowing/stats", headers=auth_headers(borrower))
    assert bstats.json() == {"checked_out_count": 0, "borrowed_by_me_count": 1}


def test_request_from_non_grantee_404(client, db, owner, stranger):
    tool = _tool(db, owner)  # stranger has NO grant
    resp = _request(
        client, stranger, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert resp.status_code == 404


def test_request_pending_grant_only_404(client, db, owner, borrower):
    grant = core_models.PeerShare(
        owner_id=owner.id, viewer_user_id=borrower.id, status="pending"
    )
    db.add(grant)
    db.commit()
    tool = _tool(db, owner)
    resp = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert resp.status_code == 404


def test_request_excluded_item_404(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    db.add(
        core_models.PeerShareExclusion(
            owner_id=owner.id, item_kind="tool", tool_id=tool.id
        )
    )
    db.commit()
    resp = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert resp.status_code == 404


def test_request_battery(client, db, owner, borrower):
    _grant(db, owner, borrower)
    battery = _battery(db, owner)
    resp = _request(
        client,
        borrower,
        owner_id=str(owner.id),
        item_kind="battery",
        item_id=str(battery.id),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["item_kind"] == "battery"


def test_decline_is_terminal(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    req = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    ).json()
    declined = client.post(
        f"/api/borrowing/{req['id']}/decline", headers=auth_headers(owner)
    )
    assert declined.status_code == 200
    assert declined.json()["state"] == "declined"
    # No deciding twice — and no second notification.
    again = client.post(
        f"/api/borrowing/{req['id']}/approve", headers=auth_headers(owner)
    )
    assert again.status_code == 422
    assert [n.kind for n in _notifications(db, borrower.id)] == ["borrow_declined"]
    # Declined frees the item for a fresh request.
    retry = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    )
    assert retry.status_code == 201


def test_only_owner_decides(client, db, owner, borrower, stranger):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    req = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    ).json()
    for actor in (borrower, stranger):
        resp = client.post(
            f"/api/borrowing/{req['id']}/approve", headers=auth_headers(actor)
        )
        assert resp.status_code == 404


def test_borrower_cancels_pending_request(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    req = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    ).json()
    cancelled = client.post(
        f"/api/borrowing/{req['id']}/cancel", headers=auth_headers(borrower)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert [n.kind for n in _notifications(db, owner.id)] == [
        "borrow_requested",
        "borrow_request_cancelled",
    ]


def test_cancel_after_approval_fails(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    req = _request(
        client, borrower, owner_id=str(owner.id), item_kind="tool", item_id=str(tool.id)
    ).json()
    client.post(f"/api/borrowing/{req['id']}/approve", headers=auth_headers(owner))
    resp = client.post(
        f"/api/borrowing/{req['id']}/cancel", headers=auth_headers(borrower)
    )
    assert resp.status_code == 422


# -- returns ---------------------------------------------------------------------------


def _lent(client, db, owner, borrower):
    _grant(db, owner, borrower)
    tool = _tool(db, owner)
    return _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_user_id=str(borrower.id),
    ).json()


def test_return_by_owner_records_actor_and_notifies(client, db, owner, borrower):
    lent = _lent(client, db, owner, borrower)
    resp = client.post(
        f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "returned"
    assert resp.json()["returned_by"] == "owner"
    assert resp.json()["returned_at"] is not None
    assert [n.kind for n in _notifications(db, borrower.id)] == ["borrow_returned"]
    assert _notifications(db, owner.id) == []  # the actor hears nothing


def test_return_by_borrower_records_actor_and_notifies(client, db, owner, borrower):
    lent = _lent(client, db, owner, borrower)
    resp = client.post(
        f"/api/borrowing/{lent['id']}/return", headers=auth_headers(borrower)
    )
    assert resp.status_code == 200
    assert resp.json()["returned_by"] == "borrower"
    assert [n.kind for n in _notifications(db, owner.id)] == ["borrow_returned"]


def test_return_by_stranger_404(client, db, owner, borrower, stranger):
    lent = _lent(client, db, owner, borrower)
    resp = client.post(
        f"/api/borrowing/{lent['id']}/return", headers=auth_headers(stranger)
    )
    assert resp.status_code == 404


def test_double_return_fails(client, db, owner):
    tool = _tool(db, owner)
    lent = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="A"
    ).json()
    assert (
        client.post(
            f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner)
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner)
        ).status_code
        == 422
    )


def test_history_accumulates_newest_first(client, db, owner):
    tool = _tool(db, owner)
    for name in ("First", "Second"):
        lent = _checkout(
            client, owner, item_kind="tool", item_id=str(tool.id), borrower_name=name
        ).json()
        client.post(f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner))
    lending = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    assert lending["current"] is None
    assert [h["borrower_name"] for h in lending["history"]] == ["Second", "First"]


def test_history_order_is_deterministic_under_same_tick_creates(client, db, owner):
    """Regression for the same-tick race (hardening 2026-10-19):
    on SQLite every row below lands in the SAME created_at second,
    so created_at can't order them at all. The monotonic seq
    (migration 0023) must still emit exact reverse insertion order
    on every history surface — item lending, the overview, and the
    data export — not just most of the time."""
    from app.modules.borrowing import models as borrowing_models
    from app.modules.borrowing import service

    tool = _tool(db, owner)
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    for name in names:
        lent = _checkout(
            client, owner, item_kind="tool", item_id=str(tool.id), borrower_name=name
        ).json()
        client.post(f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner))

    expected = list(reversed(names))
    lending = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    assert [h["borrower_name"] for h in lending["history"]] == expected

    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    assert [h["borrower_name"] for h in overview["history"]] == expected
    exported = service.export_rows(db, owner.id)
    assert [r["borrower_name"] for r in exported] == expected

    # And the mechanism itself: seq is assigned, unique, and rises
    # strictly with insertion order (so any two rows ever created
    # can be ordered without consulting the random id).
    from sqlalchemy import select as sa_select

    rows = db.scalars(sa_select(borrowing_models.Checkout)).all()
    seqs = [r.seq for r in rows]
    assert all(s is not None for s in seqs)
    assert len(set(seqs)) == len(seqs) == len(names)
    by_seq = sorted(rows, key=lambda r: r.seq)
    assert [r.borrower_name for r in by_seq] == names


def test_item_lending_foreign_item_404(client, db, owner, borrower):
    tool = _tool(db, owner)
    resp = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(borrower)
    )
    assert resp.status_code == 404


# -- overdue ------------------------------------------------------------------------------


def test_overdue_marking_and_boundary(db, owner):
    tool = _tool(db, owner)
    row = service.create_checkout(
        db,
        owner,
        item_kind="tool",
        item_id=tool.id,
        borrower_name="A",
        due_at=NOW - timedelta(seconds=1),
    )
    assert service.is_overdue(row, now=NOW) is True
    view = service.checkout_view(row, now=NOW)
    assert view["overdue"] is True

    # Due exactly now is NOT overdue (strict boundary).
    row2_tool = _tool(db, owner, name="Boundary wrench")
    row2 = service.create_checkout(
        db,
        owner,
        item_kind="tool",
        item_id=row2_tool.id,
        borrower_name="B",
        due_at=NOW,
    )
    assert service.is_overdue(row2, now=NOW) is False

    # No due date: never overdue.
    row3_tool = _tool(db, owner, name="Open-ended wrench")
    row3 = service.create_checkout(
        db, owner, item_kind="tool", item_id=row3_tool.id, borrower_name="C"
    )
    assert service.is_overdue(row3, now=NOW + timedelta(days=365)) is False


def test_overdue_counts_in_overview(client, db, owner):
    tool = _tool(db, owner)
    _checkout(
        client,
        owner,
        item_kind="tool",
        item_id=str(tool.id),
        borrower_name="Late Larry",
        due_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    )
    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    assert overview["counts"]["overdue"] == 1
    assert overview["lent_out"][0]["overdue"] is True


# -- stats -----------------------------------------------------------------------------------


def test_stat_count_accuracy(client, db, owner):
    t1 = _tool(db, owner, name="One")
    t2 = _tool(db, owner, name="Two")
    for tool in (t1, t2):
        _checkout(
            client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="A"
        )
    stats = client.get("/api/borrowing/stats", headers=auth_headers(owner)).json()
    assert stats == {"checked_out_count": 2, "borrowed_by_me_count": 0}
    overview = client.get("/api/borrowing/overview", headers=auth_headers(owner)).json()
    first = overview["lent_out"][0]
    client.post(f"/api/borrowing/{first['id']}/return", headers=auth_headers(owner))
    stats = client.get("/api/borrowing/stats", headers=auth_headers(owner)).json()
    assert stats == {"checked_out_count": 1, "borrowed_by_me_count": 0}


# -- module gate ------------------------------------------------------------------------------


def test_module_globally_off_403(client, db, owner):
    db.add(core_models.ModuleState(module_id="borrowing", globally_enabled=False))
    db.commit()
    resp = client.get("/api/borrowing/overview", headers=auth_headers(owner))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
    mine = client.get("/api/core/my-modules", headers=auth_headers(owner)).json()
    assert "borrowing" not in [m["id"] for m in mine]


def test_group_not_assigned_excluded(client, db, dealer, shop_user, owner):
    # Dealer is not in borrowing's default groups: API refuses and
    # the nav payload omits the module.
    resp = client.get("/api/borrowing/overview", headers=auth_headers(dealer))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
    mine = client.get("/api/core/my-modules", headers=auth_headers(dealer)).json()
    assert "borrowing" not in [m["id"] for m in mine]
    # Shop and mechanic are in.
    for user in (shop_user, owner):
        mine = client.get("/api/core/my-modules", headers=auth_headers(user)).json()
        assert "borrowing" in [m["id"] for m in mine]
        assert (
            client.get("/api/borrowing/overview", headers=auth_headers(user)).status_code
            == 200
        )


def test_dependency_blocked_when_inventory_off(client, db, owner):
    db.add(core_models.ModuleState(module_id="inventory", globally_enabled=False))
    db.commit()
    resp = client.get("/api/borrowing/overview", headers=auth_headers(owner))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"


def test_anonymous_401(client):
    assert client.get("/api/borrowing/overview").status_code == 401


# -- entitlement interplay ------------------------------------------------------------------------


def _make_oldest_tool_inactive(db, owner):
    """21 tools on the free plan (limit 20, enforcement on): the
    OLDEST falls out of the active set. Returns that tool."""
    base = NOW - timedelta(days=30)
    tools = []
    for i in range(21):
        tool = inventory_models.Tool(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name=f"Aged tool {i:02d}",
            created_at=base + timedelta(minutes=i),
        )
        db.add(tool)
        tools.append(tool)
    db.commit()
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    return tools[0]


def test_inactive_item_cannot_be_checked_out(client, db, owner):
    oldest = _make_oldest_tool_inactive(db, owner)
    resp = _checkout(
        client, owner, item_kind="tool", item_id=str(oldest.id), borrower_name="A"
    )
    assert resp.status_code == 422
    assert "inactive" in resp.json()["detail"]


def test_inactive_item_cannot_be_requested(client, db, owner, borrower):
    _grant(db, owner, borrower)
    oldest = _make_oldest_tool_inactive(db, owner)
    resp = _request(
        client,
        borrower,
        owner_id=str(owner.id),
        item_kind="tool",
        item_id=str(oldest.id),
    )
    # Inactive items are off the peer-visible list entirely: a 404,
    # indistinguishable from an item that was never shared.
    assert resp.status_code == 404


def test_checked_out_item_that_goes_inactive_still_returns(client, db, owner):
    tool = _tool(db, owner)
    lent = _checkout(
        client, owner, item_kind="tool", item_id=str(tool.id), borrower_name="A"
    ).json()
    # Now bury the tool: 20 newer tools + enforcement on push it out
    # of the active set WHILE it is out.
    base = tool.created_at + timedelta(minutes=1)
    for i in range(20):
        db.add(
            inventory_models.Tool(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=f"Newer tool {i:02d}",
                created_at=base + timedelta(minutes=i),
            )
        )
    db.commit()
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    active = entitlements.active_tool_ids(db, owner.id)
    assert active is not None and tool.id not in active  # really inactive now
    resp = client.post(
        f"/api/borrowing/{lent['id']}/return", headers=auth_headers(owner)
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "returned"
