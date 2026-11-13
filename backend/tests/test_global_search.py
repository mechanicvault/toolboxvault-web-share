"""Global search (owner spec, 2026-10-25): the header bar searches
the user's OWN records everywhere, grouped by kind of record.

Pins:
  - one word ("ratchet") hits many families at once, each under
    its own heading, each with its deep link;
  - loose substring matching: "ratchet" finds the borrower named
    "Ratched" and a word buried in a part's descriptive text and
    in a dealer's notes;
  - own data only — another user's matching records never appear;
  - a module the user switched OFF contributes nothing;
  - forums are excluded entirely, even when a forum post the user
    wrote contains the word;
  - the group cap shows GROUP_CAP rows with the TRUE total;
  - empty / no-match queries answer cleanly with no groups.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.borrowing import models as borrowing_models
from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.dealers import models as dealers_models
from app.modules.forum import models as forum_models
from app.modules.inventory import models as inventory_models
from app.modules.maintenance import models as maintenance_models
from app.modules.marketplace import models as marketplace_models
from app.modules.messaging import models as messaging_models
from app.modules.parts import models as parts_models
from app.modules.support import models as support_models
from app.modules.truck_accounts import models as truck_models
from app.modules.wishlist import models as wishlist_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, name, account_types=(MECHANIC,)):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000901", "gs-owner@example.com", "Search Owner")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000902", "gs-other@example.com", "Other Person")


def _search(client, user, q):
    resp = client.get("/api/core/search", params={"q": q}, headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _groups(payload):
    return {g["key"]: g for g in payload["groups"]}


def test_one_word_hits_many_families(owner, other, db, client):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=owner.id, name="Ratchet wrench 1/2in",
                brand="Tekton",
            ),
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=owner.id, name="Plain hammer",
                notes="the ratchet lives in the red box",
            ),
            inventory_models.Battery(
                id=uuid.uuid4(), owner_id=owner.id, name="M18 pack",
                notes="pairs with the ratchet driver",
            ),
            parts_models.Part(
                id=uuid.uuid4(), owner_id=owner.id, title="Spare gear",
                notes="fits the ratchet assembly from the donor truck",
            ),
            wishlist_models.WishlistItem(
                id=uuid.uuid4(), owner_id=owner.id, title="Torque ratchet 3/8",
            ),
            dealers_models.DealerCompany(
                id=(dealer_id := uuid.uuid4()), owner_id=owner.id,
                name="Acme Tool Supply", notes="ask about the ratchet promo",
            ),
            borrowing_models.BorrowerContact(
                id=uuid.uuid4(), owner_id=owner.id, name="Ratched",
                contact="555-0100",
            ),
            borrowing_models.Checkout(
                id=(checkout_id := uuid.uuid4()), owner_id=owner.id,
                item_kind="tool", item_id=uuid.uuid4(),
                item_name="Ratchet set", borrower_name="Ratched",
            ),
            claims_models.Claim(
                id=(claim_id := uuid.uuid4()), owner_id=owner.id,
                claim_number="2026-001", claim_year=2026, number_seq=1,
                insurer_name="Acme Mutual",
                description="the ratchet set was stolen from the truck",
            ),
            # The repair record this seed used to carry is a
            # WARRANTY CLAIM since the merge (2026-11-04): its
            # words are found by the claims group now.
            claims_models.Claim(
                id=(warranty_id := uuid.uuid4()), owner_id=owner.id,
                claim_number="2026-002", claim_year=2026, number_seq=2,
                kind="warranty_repair",
                description="ratchet head slips under load",
            ),
            # And the maintenance group answers through what it
            # still owns: schedules.
            maintenance_models.MaintenanceSchedule(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name="Impact driver",
                kind="inspection", label="Ratchet head inspection",
            ),
            marketplace_models.SaleListing(
                id=(listing_id := uuid.uuid4()), owner_id=owner.id,
                title="Used socket set", description="ratchet included",
                status="active",
            ),
            support_models.SupportTicket(
                id=(ticket_id := uuid.uuid4()), user_id=owner.id,
                subject="ratchet photo upload fails", status="open",
            ),
            messaging_models.MessageThread(
                id=(thread_id := uuid.uuid4()),
                participant_low_id=min(owner.id, other.id),
                participant_high_id=max(owner.id, other.id),
                created_by_id=owner.id, status="accepted",
            ),
            truck_models.TruckAccount(
                id=(truck_id := uuid.uuid4()), dealer_user_id=owner.id,
                customer_user_id=other.id, customer_name="Carl Customer",
                customer_email="carl@example.com", status="active",
                invite_token="test-token",
            ),
        ]
    )
    db.commit()
    db.add(
        messaging_models.Message(
            thread_id=thread_id, sender_id=other.id,
            body="did the ratchet arrive yet?", status="sent",
        )
    )
    db.add(
        truck_models.TruckEntry(
            account_id=truck_id, dealer_user_id=owner.id, kind="charge",
            amount=10, note="ratchet handle replacement", entry_date=now.date(),
        )
    )
    db.commit()

    payload = _search(client, owner, "ratchet")
    groups = _groups(payload)

    assert set(groups) == {
        "inventory", "parts", "wishlist", "dealers", "people",
        "borrowing", "claims", "disaster_claims", "maintenance",
        "listings", "messages", "support", "truck_accounts",
    }
    # Inventory: the named tool, the notes-only tool, the battery.
    inv = groups["inventory"]
    assert inv["total"] == 3
    kinds = {r["kind"] for r in inv["results"]}
    assert kinds == {"tool", "battery"}
    links = {r["link"] for r in inv["results"]}
    assert all(link.startswith("/inventory/") for link in links)
    # The notes-only match explains itself with an excerpt.
    hammer = next(r for r in inv["results"] if r["title"] == "Plain hammer")
    assert "ratchet" in hammer["excerpt"]

    assert groups["parts"]["results"][0]["link"].startswith("/parts/")
    assert "ratchet" in groups["parts"]["results"][0]["excerpt"]
    assert groups["wishlist"]["results"][0]["link"] == "/wishlist"

    dealer = groups["dealers"]["results"][0]
    assert dealer["link"] == f"/dealers/{dealer_id}"
    assert "ratchet" in dealer["excerpt"]

    # The spec's own example: "ratchet" finds the person "Ratched".
    person = groups["people"]["results"][0]
    assert person["title"] == "Ratched"
    assert person["link"] == "/borrowing"

    assert groups["borrowing"]["results"][0]["link"] == f"/borrowing?checkout={checkout_id}"
    # Claims separation (2026-11-05): the insurance claim lives
    # in the disaster_claims group, linking into its own
    # section; the claims group carries the warranty claim ONLY.
    disaster = groups["disaster_claims"]
    assert disaster["results"][0]["link"] == f"/disaster-claims/{claim_id}"
    assert disaster["results"][0]["title"] == "Claim 2026-001"
    assert disaster["results"][0]["kind"] == "disaster_claim"
    assert {r["link"] for r in groups["claims"]["results"]} == {
        f"/claims/{warranty_id}"
    }
    # Repairs & Maintenance merge (2026-11-05): a maintenance hit
    # whose item is gone lands on the merged page's Tool
    # Maintenance tab, not the retired /maintenance route.
    assert groups["maintenance"]["results"][0]["link"] == "/repairs#tool-maintenance"
    assert groups["listings"]["results"][0]["link"] == f"/marketplace/{listing_id}"
    assert groups["support"]["results"][0]["link"] == f"/help?ticket={ticket_id}"
    assert groups["messages"]["results"][0]["link"] == f"/messages/{thread_id}"
    assert groups["truck_accounts"]["results"][0]["link"] == f"/truck-accounts/{truck_id}"


def test_own_data_only(owner, other, db, client):
    db.add_all(
        [
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=other.id, name="Ratchet of someone else",
            ),
            parts_models.Part(
                id=uuid.uuid4(), owner_id=other.id, title="Ratchet part",
            ),
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=owner.id, name="My ratchet",
            ),
        ]
    )
    db.commit()
    groups = _groups(_search(client, owner, "ratchet"))
    assert set(groups) == {"inventory"}
    assert groups["inventory"]["total"] == 1
    assert groups["inventory"]["results"][0]["title"] == "My ratchet"


def test_module_switched_off_contributes_nothing(owner, db, client):
    db.add_all(
        [
            parts_models.Part(
                id=uuid.uuid4(), owner_id=owner.id, title="Ratchet part",
            ),
            wishlist_models.WishlistItem(
                id=uuid.uuid4(), owner_id=owner.id, title="Ratchet wanted",
            ),
        ]
    )
    db.add(
        core_models.UserModulePref(
            user_id=owner.id, module_id="parts", enabled=False
        )
    )
    db.commit()
    groups = _groups(_search(client, owner, "ratchet"))
    assert "parts" not in groups
    assert groups["wishlist"]["total"] == 1


def test_forum_is_never_searched(owner, db, client):
    category = forum_models.ForumCategory(id=uuid.uuid4(), name="General")
    db.add(category)
    db.flush()
    thread = forum_models.ForumThread(
        id=uuid.uuid4(), category_id=category.id, author_id=owner.id,
        title="Best ratchet for tight bays?",
    )
    db.add(thread)
    db.flush()
    db.add(
        forum_models.ForumPost(
            thread_id=thread.id, author_id=owner.id,
            body="my ratchet recommendation thread", status="posted",
        )
    )
    db.add(
        inventory_models.Tool(
            id=uuid.uuid4(), owner_id=owner.id, name="Ratchet",
        )
    )
    db.commit()
    payload = _search(client, owner, "ratchet")
    groups = _groups(payload)
    assert set(groups) == {"inventory"}


def test_group_cap_reports_true_total(owner, db, client):
    db.add_all(
        parts_models.Part(
            id=uuid.uuid4(), owner_id=owner.id, title=f"Ratchet part {i}"
        )
        for i in range(30)
    )
    db.commit()
    groups = _groups(_search(client, owner, "ratchet"))
    assert groups["parts"]["total"] == 30
    assert len(groups["parts"]["results"]) == 25


def test_empty_and_no_match_queries(owner, db, client):
    db.add(
        inventory_models.Tool(id=uuid.uuid4(), owner_id=owner.id, name="Hammer")
    )
    db.commit()
    assert _search(client, owner, "")["groups"] == []
    assert _search(client, owner, "zzznomatch")["groups"] == []


def test_every_word_must_match(owner, db, client):
    db.add_all(
        [
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=owner.id, name="Red ratchet",
            ),
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=owner.id, name="Blue ratchet",
            ),
        ]
    )
    db.commit()
    groups = _groups(_search(client, owner, "red ratchet"))
    assert groups["inventory"]["total"] == 1
    assert groups["inventory"]["results"][0]["title"] == "Red ratchet"


def test_borrower_side_loans_are_found(owner, other, db, client):
    """Sweep B4 F5: a loan where the SEARCHER is the borrower is
    their record too — searching the item (or the owner's name)
    finds the loan, with the owner as the row's counterparty
    detail and the loan's own status. Before the fix the
    borrowing family read owner-side rows only, so the item the
    searcher was holding was invisible to their search."""
    loan_id = uuid.uuid4()
    db.add(
        borrowing_models.Checkout(
            id=loan_id, owner_id=other.id,
            item_kind="tool", item_id=uuid.uuid4(),
            item_name="Torque wrench", borrower_name=owner.name,
            borrower_user_id=owner.id, state="checked_out",
        )
    )
    db.commit()

    groups = _groups(_search(client, owner, "Torque"))
    assert groups["borrowing"]["total"] == 1
    row = groups["borrowing"]["results"][0]
    assert row["link"] == f"/borrowing?checkout={loan_id}"
    assert row["detail"] == other.name
    assert row["status"]["key"] == "borrowing.state.checked_out"

    # The owner's name finds the loan too (counterparty text).
    groups = _groups(_search(client, owner, other.name.split()[0]))
    assert groups["borrowing"]["total"] == 1
    # And the owner's own search still sees it from their seat,
    # with the borrower as the detail.
    groups = _groups(_search(client, other, "Torque"))
    assert groups["borrowing"]["total"] == 1
    assert groups["borrowing"]["results"][0]["detail"] == owner.name
