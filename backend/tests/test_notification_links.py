"""Notification click-through links (owner spec, 2026-10-25).

Clicking a notification marks it read AND goes to its source.
The destination is resolved on the server (inbox_links) and
shipped as `link` on every inbox row. Pins:

  - COMPLETENESS: every kind the system can create (inbox's
    KIND_* constants + the dealer warranty kinds + the truck
    transfer kind) has a destination in inbox_links.KIND_LINKS
    — a new kind cannot ship without one, and a stale entry
    fails too.
  - The ticket deep links, end to end through the real support
    flow: an operator's support_ticket_new lands on the desk
    with THAT ticket (/admin/support?ticket=…); the owner's
    support_reply lands on their own view (/help?ticket=…).
  - Record families resolve to the record (claim, tool, battery,
    message thread, forum thread, feedback post, truck account,
    checkout) and a missing/deleted record downgrades to the
    module's main page — never an error.
  - Creation payloads: messaging's notify helpers carry the
    thread id (they used to carry nothing); rating_removed
    carries the deal thread and resolves to it.
  - crew_left tells its two audiences apart (owner → the crew
    roster, member → My Shop).
  - The always-visible warranty kinds respect the dealers
    module switch at click time: off → Home, never the
    module-off page.
"""

import uuid

import pytest

from app.modules.borrowing import models as borrowing_models
from app.modules.claims import models as claims_models
from app.modules.core import inbox, inbox_links
from app.modules.core import models as core_models
from app.modules.dealers import warranty as warranty_module
from app.modules.feedback import models as feedback_models
from app.modules.forum import models as forum_models
from app.modules.inventory import models as inventory_models
from app.modules.messaging import models as messaging_models
from app.modules.messaging import service as messaging_service
from app.modules.truck_accounts import models as truck_models
from app.modules.truck_accounts import service as truck_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"


def _make_user(db, account_number, email, name, *, operator=False, groups=(MECHANIC,)):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(groups),
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def member(db):
    return _make_user(db, "TV-M-000401", "link-member@example.com", "Lena Link")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000402", "link-other@example.com", "Omar Other")


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000409", "link-desk@example.com", "Dee Desk", operator=True
    )


def _inbox(client, user) -> list[dict]:
    resp = client.get("/api/core/notifications", headers=auth_headers(user))
    assert resp.status_code == 200
    return resp.json()


def _only_link(client, user, kind: str) -> str | None:
    rows = [r for r in _inbox(client, user) if r["kind"] == kind]
    assert len(rows) == 1, f"expected exactly one {kind}, got {len(rows)}"
    return rows[0]["link"]


def _notify(db, user, kind: str, data: dict | None = None) -> None:
    inbox.create_notification(
        db, user.id, kind=kind, title="T", body="B", data=data or {}
    )


# -- completeness ------------------------------------------------------------------


def test_every_creatable_kind_has_a_destination():
    kinds = {
        value
        for name, value in vars(inbox).items()
        if name.startswith("KIND_") and isinstance(value, str)
    }
    kinds |= {
        warranty_module.KIND_REQUEST_RECEIVED,
        warranty_module.KIND_REQUEST_CLAIMED,
        warranty_module.KIND_REQUEST_STATUS,
    }
    # The truck transfer kind (2026-10-31) likewise lives with its
    # emitter (truck_accounts.service), not in inbox.
    kinds |= {truck_service.KIND_TRUCK_TRANSFERRED}
    assert kinds == set(inbox_links.KIND_LINKS), (
        "kinds without a click-through destination: "
        f"{sorted(kinds - set(inbox_links.KIND_LINKS))}; "
        "destinations with no kind: "
        f"{sorted(set(inbox_links.KIND_LINKS) - kinds)}"
    )


# -- support tickets: the owner's example, end to end -----------------------------


def test_ticket_links_operator_desk_and_member_view(client, member, operator):
    created = client.post(
        "/api/support/tickets",
        json={"subject": "Gate remote dead", "body": "It stopped clicking."},
        headers=auth_headers(member),
    )
    assert created.status_code == 201, created.text
    ticket_id = created.json()["id"]

    # The operator's new-ticket notification lands on the desk,
    # on THAT ticket.
    assert (
        _only_link(client, operator, inbox.KIND_SUPPORT_TICKET_NEW)
        == f"/admin/support?ticket={ticket_id}"
    )

    reply = client.post(
        f"/api/admin/support/tickets/{ticket_id}/messages",
        json={"body": "Try a fresh battery first."},
        headers=auth_headers(operator),
    )
    assert reply.status_code == 200, reply.text

    # The owner's reply notification lands on their own ticket.
    assert (
        _only_link(client, member, inbox.KIND_SUPPORT_REPLY)
        == f"/help?ticket={ticket_id}"
    )


def test_ticket_link_downgrades_when_ticket_is_gone(client, db, member, operator):
    ghost = uuid.uuid4()
    _notify(db, member, inbox.KIND_SUPPORT_REPLY, {"ticket_id": str(ghost)})
    _notify(db, operator, inbox.KIND_SUPPORT_TICKET_NEW, {"ticket_id": str(ghost)})
    assert _only_link(client, member, inbox.KIND_SUPPORT_REPLY) == "/help"
    assert (
        _only_link(client, operator, inbox.KIND_SUPPORT_TICKET_NEW)
        == "/admin/support"
    )


# -- record families -----------------------------------------------------------------


def test_claim_link_and_fallback(client, db, member):
    claim = claims_models.Claim(
        owner_id=member.id, claim_year=2026, number_seq=777001
    )
    db.add(claim)
    db.commit()
    _notify(db, member, inbox.KIND_CLAIM_DEADLINE, {"claim_id": str(claim.id)})
    _notify(db, member, inbox.KIND_CLAIM_DEADLINE, {"claim_id": str(uuid.uuid4())})
    links = {
        r["data"]["claim_id"]: r["link"]
        for r in _inbox(client, member)
        if r["kind"] == inbox.KIND_CLAIM_DEADLINE
    }
    # Claims separation (2026-11-05): deadline notifications are
    # the DISASTER section's — the claim (kind defaults to
    # insurance) links into /disaster-claims, and the fallback
    # for a vanished claim is the disaster list, never Claims.
    assert links[str(claim.id)] == f"/disaster-claims/{claim.id}"
    assert set(links.values()) == {
        f"/disaster-claims/{claim.id}",
        "/disaster-claims",
    }


def test_warranty_claim_link_and_fallback(client, db, member):
    claim = claims_models.Claim(
        owner_id=member.id,
        kind=claims_models.KIND_WARRANTY,
        claim_year=2026,
        number_seq=777002,
    )
    db.add(claim)
    db.commit()
    _notify(db, member, inbox.KIND_WARRANTY_CLAIM_NEW, {"claim_id": str(claim.id)})
    _notify(db, member, inbox.KIND_WARRANTY_CLAIM_NEW, {"claim_id": str(uuid.uuid4())})
    links = {
        r["data"]["claim_id"]: r["link"]
        for r in _inbox(client, member)
        if r["kind"] == inbox.KIND_WARRANTY_CLAIM_NEW
    }
    # The claim itself still links to its detail page (the merge
    # did not move claim records); a vanished claim falls back
    # to the merged page's Repair claims tab (Repairs &
    # Maintenance merge, 2026-11-05) — never the retired
    # /claims list.
    assert links[str(claim.id)] == f"/claims/{claim.id}"
    assert set(links.values()) == {
        f"/claims/{claim.id}",
        "/repairs#repair-claims",
    }


def test_item_links_tool_and_battery(client, db, member):
    tool = inventory_models.Tool(owner_id=member.id, name="Link Hammer")
    battery = inventory_models.Battery(owner_id=member.id, name="Link Cell")
    db.add_all([tool, battery])
    db.commit()
    _notify(
        db,
        member,
        inbox.KIND_MAINTENANCE_OVERDUE,
        {"item_kind": "tool", "item_id": str(tool.id)},
    )
    _notify(
        db,
        member,
        inbox.KIND_MANUAL_SAVED,
        {"item_kind": "battery", "item_id": str(battery.id)},
    )
    _notify(
        db,
        member,
        inbox.KIND_MANUAL_NOT_FOUND,
        {"item_kind": "tool", "item_id": str(uuid.uuid4())},
    )
    rows = {r["kind"]: r["link"] for r in _inbox(client, member)}
    assert rows[inbox.KIND_MAINTENANCE_OVERDUE] == f"/inventory/{tool.id}"
    assert rows[inbox.KIND_MANUAL_SAVED] == f"/inventory/batteries/{battery.id}"
    assert rows[inbox.KIND_MANUAL_NOT_FOUND] == "/inventory"


def test_checkout_link_and_fallback(client, db, member, other):
    tool = inventory_models.Tool(owner_id=member.id, name="Checkout Drill")
    db.add(tool)
    db.commit()
    checkout = borrowing_models.Checkout(
        owner_id=member.id,
        item_kind="tool",
        item_id=tool.id,
        seq=1,
    )
    db.add(checkout)
    db.commit()
    _notify(db, member, inbox.KIND_BORROW_REQUESTED, {"checkout_id": str(checkout.id)})
    _notify(db, member, inbox.KIND_BORROW_RETURNED, {"checkout_id": str(uuid.uuid4())})
    rows = {r["kind"]: r["link"] for r in _inbox(client, member)}
    assert rows[inbox.KIND_BORROW_REQUESTED] == f"/borrowing?checkout={checkout.id}"
    assert rows[inbox.KIND_BORROW_RETURNED] == "/borrowing"
    assert other is not None  # fixture symmetry; nothing leaks cross-user below


def test_forum_feedback_truck_links(client, db, member, other):
    category = forum_models.ForumCategory(name="Link Talk")
    db.add(category)
    db.commit()
    thread = forum_models.ForumThread(
        category_id=category.id, author_id=member.id, title="Torque specs?"
    )
    post = feedback_models.FeedbackPost(
        board="features", author_id=member.id, title="Dark mode", body="Please."
    )
    account = truck_models.TruckAccount(
        dealer_user_id=other.id, invite_token="link-token"
    )
    db.add_all([thread, post, account])
    db.commit()
    _notify(db, member, inbox.KIND_FORUM_REPLY, {"thread_id": str(thread.id)})
    _notify(db, member, inbox.KIND_FEEDBACK_COMMENT, {"post_id": str(post.id)})
    _notify(db, member, inbox.KIND_TRUCK_CHARGE, {"account_id": str(account.id)})
    _notify(db, member, inbox.KIND_TRUCK_DUE, {"account_id": str(uuid.uuid4())})
    rows = {r["kind"]: r["link"] for r in _inbox(client, member)}
    assert rows[inbox.KIND_FORUM_REPLY] == f"/forum/thread/{thread.id}"
    assert rows[inbox.KIND_FEEDBACK_COMMENT] == f"/feedback/post/{post.id}"
    assert rows[inbox.KIND_TRUCK_CHARGE] == f"/truck-accounts/{account.id}"
    assert rows[inbox.KIND_TRUCK_DUE] == "/truck-accounts"


# -- messaging payloads: the thread id now rides along -------------------------------


def _thread(db, low, high) -> messaging_models.MessageThread:
    lo, hi = sorted([low.id, high.id], key=str)
    thread = messaging_models.MessageThread(
        participant_low_id=lo, participant_high_id=hi, created_by_id=low.id
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def test_message_notifications_carry_thread_and_link(client, db, member, other):
    thread = _thread(db, member, other)
    messaging_service._notify_message(
        db, other.id, member.name, thread_id=thread.id
    )
    messaging_service._notify_request_accepted(
        db, member.id, other.name, thread_id=thread.id
    )
    db.commit()
    received = [r for r in _inbox(client, other) if r["kind"] == inbox.KIND_MESSAGE_RECEIVED]
    assert len(received) == 1
    assert received[0]["data"]["thread_id"] == str(thread.id)
    assert received[0]["link"] == f"/messages/{thread.id}"
    accepted = [
        r for r in _inbox(client, member)
        if r["kind"] == inbox.KIND_MESSAGE_REQUEST_ACCEPTED
    ]
    assert len(accepted) == 1
    assert accepted[0]["link"] == f"/messages/{thread.id}"


def test_message_link_falls_back_for_a_foreign_thread(client, db, member, other):
    # A thread the recipient doesn't take part in is not a
    # destination — its page would refuse them.
    third = _make_user(db, "TV-M-000403", "link-third@example.com", "Tess Third")
    foreign = _thread(db, member, third)
    _notify(
        db, other, inbox.KIND_MESSAGE_RECEIVED, {"thread_id": str(foreign.id)}
    )
    assert _only_link(client, other, inbox.KIND_MESSAGE_RECEIVED) == "/messages"


def test_rating_removed_carries_thread_and_links_to_it(client, db, member, other):
    thread = _thread(db, member, other)
    inbox.rating_removed(
        db, rater_id=member.id, context_title="Widget", thread_id=thread.id
    )
    inbox.rating_removed(db, rater_id=other.id, context_title="Gadget")
    row = [r for r in _inbox(client, member) if r["kind"] == inbox.KIND_RATING_REMOVED]
    assert len(row) == 1
    assert row[0]["data"]["thread_id"] == str(thread.id)
    assert row[0]["link"] == f"/messages/{thread.id}"
    assert _only_link(client, other, inbox.KIND_RATING_REMOVED) == "/marketplace"


# -- crew: one kind, two audiences -----------------------------------------------------


def test_crew_left_lands_each_audience_on_its_own_page(client, db, member):
    shop = _make_user(
        db, "TV-S-000401", "link-shop@example.com", "Sharon Shop", groups=(SHOP,)
    )
    membership = core_models.ShopMembership(
        shop_user_id=shop.id,
        employee_user_id=member.id,
        invite_token="crew-link-token",
        status="left",
    )
    db.add(membership)
    db.commit()
    for user in (shop, member):
        _notify(
            db, user, inbox.KIND_CREW_LEFT, {"membership_id": str(membership.id)}
        )
    assert _only_link(client, shop, inbox.KIND_CREW_LEFT) == "/settings/crew"
    assert _only_link(client, member, inbox.KIND_CREW_LEFT) == "/settings/my-shop"


# -- statics ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,data,expected",
    [
        (inbox.KIND_PEER_INVITE_RECEIVED, {"grant_id": str(uuid.uuid4())}, "/shared-tools#shared-with-me"),
        (inbox.KIND_CLAIM_READINESS, {"gaps": {}}, "/inventory/health"),
        (inbox.KIND_CLOUD_BACKUP_FAILED, {"run_id": str(uuid.uuid4())}, "/settings/cloud-backup"),
        (inbox.KIND_DEALER_ROUTE_DAY, {"route_date": "2026-10-25"}, "/settings/dealer-profile"),
        (inbox.KIND_CREW_INVITE, {"membership_id": str(uuid.uuid4())}, "/settings/my-shop"),
        (inbox.KIND_CREW_ACCEPTED, {"membership_id": str(uuid.uuid4())}, "/settings/crew"),
        (inbox.KIND_CREW_GRACE_EXPIRED, {"membership_id": str(uuid.uuid4())}, "/settings/my-shop"),
    ],
)
def test_static_destinations(client, db, member, kind, data, expected):
    _notify(db, member, kind, data)
    assert _only_link(client, member, kind) == expected


# -- warranty kinds vs the dealers switch -------------------------------------------------


def test_warranty_link_respects_the_dealers_switch(client, db, member):
    _notify(
        db, member, warranty_module.KIND_REQUEST_STATUS, {"request_id": str(uuid.uuid4())}
    )
    assert (
        _only_link(client, member, warranty_module.KIND_REQUEST_STATUS) == "/dealers"
    )

    db.add(
        core_models.UserModulePref(
            user_id=member.id, module_id="dealers", enabled=False
        )
    )
    db.commit()
    # The kind stays VISIBLE (it is not in the module-hide map)
    # but its click now lands on Home instead of the
    # module-off page.
    assert _only_link(client, member, warranty_module.KIND_REQUEST_STATUS) == "/"
