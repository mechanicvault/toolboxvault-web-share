"""Global search statuses (busy work #2, owner order 2026-11-10):
every result whose record HAS a status carries it in the payload,
resolved server-side from the record itself — the claim's ladder
word (a warranty claim under its closed layer reads Closed), the
loan's state with overdue computed by the borrowing service, the
item's one primary status composed as the item page's header
pill composes it, and so on per family.

Pins:
  - per-family status key + tone against records in known states;
  - records without a meaningful status (parts, people, print
    files — every print result is live by construction) carry
    status=None;
  - listings / support tickets no longer smuggle their raw status
    value through the detail field;
  - the item pill's sub-reads follow module visibility: with the
    borrowing module switched off, a lent-out tool does NOT read
    Checked out (the item page's best-effort posture);
  - a downloads-rung seat's reachable results carry statuses too,
    and its out-of-reach records stay invisible.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.modules.borrowing import models as borrowing_models
from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.maintenance import models as maintenance_models
from app.modules.marketplace import models as marketplace_models
from app.modules.parts import models as parts_models
from app.modules.prints import models as print_models
from app.modules.support import models as support_models
from app.modules.truck_accounts import models as truck_models
from app.modules.wishlist import models as wishlist_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PROBE = "statusprobe"


def _make_user(db, account_number, email, name, account_types=(MECHANIC,), tier=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000911", "gss-owner@example.com", "Status Owner")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000912", "gss-other@example.com", "Other Person")


def _search(client, user, q=PROBE):
    resp = client.get("/api/core/search", params={"q": q}, headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return {g["key"]: g for g in resp.json()["groups"]}


def _by_title(group, title):
    return next(r for r in group["results"] if r["title"] == title)


def test_claim_statuses(owner, db, client):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            # Warranty claim mid-repair: its ladder word.
            claims_models.Claim(
                id=uuid.uuid4(), owner_id=owner.id, claim_number="2026-101",
                claim_year=2026, number_seq=101, kind="warranty_repair",
                status="in_repair", description=f"{PROBE} head slips",
            ),
            # Warranty claim under the closed layer: reads Closed
            # even though its ladder status is preserved underneath.
            claims_models.Claim(
                id=uuid.uuid4(), owner_id=owner.id, claim_number="2026-102",
                claim_year=2026, number_seq=102, kind="warranty_repair",
                status="reported", closed_at=now,
                description=f"{PROBE} snapped stud",
            ),
            # Insurance claim: its own ladder.
            claims_models.Claim(
                id=uuid.uuid4(), owner_id=owner.id, claim_number="2026-103",
                claim_year=2026, number_seq=103, kind="insurance_disaster",
                status="filed", insurer_name="Acme Mutual",
                description=f"{PROBE} flood damage",
            ),
            claims_models.Claim(
                id=uuid.uuid4(), owner_id=owner.id, claim_number="2026-104",
                claim_year=2026, number_seq=104, kind="insurance_disaster",
                status="closed", insurer_name="Acme Mutual",
                description=f"{PROBE} fire damage",
            ),
        ]
    )
    db.commit()
    groups = _search(client, owner)
    claims = {r["title"]: r for r in groups["claims"]["results"]}
    assert claims["Claim 2026-101"]["status"] == {
        "key": "claims.status.in_repair",
        "tone": "warning",
    }
    assert claims["Claim 2026-102"]["status"] == {
        "key": "claims.status.closed",
        "tone": "neutral",
    }
    disaster = {r["title"]: r for r in groups["disaster_claims"]["results"]}
    assert disaster["Claim 2026-103"]["status"] == {
        "key": "claims.status.filed",
        "tone": "accent",
    }
    assert disaster["Claim 2026-104"]["status"] == {
        "key": "claims.status.closed",
        "tone": "neutral",
    }


def test_checkout_statuses(owner, db, client):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} drill out",
                borrower_name="Nate", state="checked_out",
                due_at=now + timedelta(days=3),
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} saw late",
                borrower_name="Nate", state="checked_out",
                due_at=now - timedelta(days=2),
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} wrench back",
                borrower_name="Nate", state="returned",
                returned_at=now - timedelta(days=1),
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} level asked",
                borrower_name="Nate", state="requested",
            ),
        ]
    )
    db.commit()
    rows = {r["title"]: r for r in _search(client, owner)["borrowing"]["results"]}
    assert rows[f"{PROBE} drill out"]["status"] == {
        "key": "borrowing.state.checked_out",
        "tone": "accent",
    }
    assert rows[f"{PROBE} saw late"]["status"] == {
        "key": "borrowing.state.overdue",
        "tone": "danger",
    }
    assert rows[f"{PROBE} wrench back"]["status"] == {
        "key": "borrowing.state.returned",
        "tone": "success",
    }
    assert rows[f"{PROBE} level asked"]["status"] == {
        "key": "borrowing.state.requested",
        "tone": "warning",
    }


def test_item_statuses(owner, db, client):
    now = datetime.now(timezone.utc)
    plain_id, broken_id, out_id, late_id, sale_id, sent_id = (uuid.uuid4() for _ in range(6))
    claim_id = uuid.uuid4()
    db.add_all(
        [
            inventory_models.Tool(
                id=plain_id, owner_id=owner.id, name=f"{PROBE} plain wrench",
            ),
            inventory_models.Tool(
                id=broken_id, owner_id=owner.id, name=f"{PROBE} broken wrench",
                standing="broken",
            ),
            inventory_models.Tool(
                id=out_id, owner_id=owner.id, name=f"{PROBE} lent wrench",
            ),
            inventory_models.Tool(
                id=late_id, owner_id=owner.id, name=f"{PROBE} late wrench",
            ),
            inventory_models.Tool(
                id=sale_id, owner_id=owner.id, name=f"{PROBE} sale wrench",
            ),
            inventory_models.Tool(
                id=sent_id, owner_id=owner.id, name=f"{PROBE} sent wrench",
                standing="broken",
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=out_id, item_name=f"{PROBE} lent wrench",
                borrower_name="Nate", state="checked_out",
                due_at=now + timedelta(days=3),
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=late_id, item_name=f"{PROBE} late wrench",
                borrower_name="Nate", state="checked_out",
                due_at=now - timedelta(days=1),
            ),
            marketplace_models.SaleListing(
                id=uuid.uuid4(), owner_id=owner.id, title="Unrelated listing",
                status="active", source_kind="tool", source_id=sale_id,
            ),
            claims_models.Claim(
                id=claim_id, owner_id=owner.id, claim_number="2026-105",
                claim_year=2026, number_seq=105, kind="warranty_repair",
                status="in_repair", description="at the repair depot",
            ),
            claims_models.ClaimLine(
                id=uuid.uuid4(), owner_id=owner.id, claim_id=claim_id,
                target_kind="tool", target_id=sent_id,
            ),
        ]
    )
    db.commit()
    rows = {r["title"]: r for r in _search(client, owner)["inventory"]["results"]}
    assert rows[f"{PROBE} plain wrench"]["status"] == {
        "key": "inventory.status.available",
        "tone": "success",
    }
    assert rows[f"{PROBE} broken wrench"]["status"] == {
        "key": "inventory.status.broken",
        "tone": "danger",
    }
    assert rows[f"{PROBE} lent wrench"]["status"] == {
        "key": "inventory.status.checkedOut",
        "tone": "accent",
    }
    # The pill's overdue treatment: same word, red.
    assert rows[f"{PROBE} late wrench"]["status"] == {
        "key": "inventory.status.checkedOut",
        "tone": "danger",
    }
    assert rows[f"{PROBE} sale wrench"]["status"] == {
        "key": "inventory.status.forSale",
        "tone": "success",
    }
    assert rows[f"{PROBE} sent wrench"]["status"] == {
        "key": "inventory.status.sentOut",
        "tone": "warning",
    }


def test_item_status_subreads_follow_module_visibility(owner, db, client):
    now = datetime.now(timezone.utc)
    tool_id = uuid.uuid4()
    db.add_all(
        [
            inventory_models.Tool(
                id=tool_id, owner_id=owner.id, name=f"{PROBE} gated wrench",
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=tool_id, item_name=f"{PROBE} gated wrench",
                borrower_name="Nate", state="checked_out",
                due_at=now + timedelta(days=3),
            ),
            core_models.UserModulePref(
                user_id=owner.id, module_id="borrowing", enabled=False
            ),
        ]
    )
    db.commit()
    groups = _search(client, owner)
    # The borrowing family is off entirely...
    assert "borrowing" not in groups
    # ...and the item's pill does not borrow its state either.
    row = _by_title(groups["inventory"], f"{PROBE} gated wrench")
    assert row["status"] == {"key": "inventory.status.available", "tone": "success"}


def test_item_status_subreads_follow_claims_and_marketplace_visibility(
    owner, db, client
):
    sent_id, sale_id = uuid.uuid4(), uuid.uuid4()
    claim_id = uuid.uuid4()
    db.add_all(
        [
            inventory_models.Tool(
                id=sent_id, owner_id=owner.id, name=f"{PROBE} gated sent",
                standing="broken",
            ),
            inventory_models.Tool(
                id=sale_id, owner_id=owner.id, name=f"{PROBE} gated sale",
            ),
            claims_models.Claim(
                id=claim_id, owner_id=owner.id, claim_number="2026-106",
                claim_year=2026, number_seq=106, kind="warranty_repair",
                status="in_repair", description="at the repair depot",
            ),
            claims_models.ClaimLine(
                id=uuid.uuid4(), owner_id=owner.id, claim_id=claim_id,
                target_kind="tool", target_id=sent_id,
            ),
            marketplace_models.SaleListing(
                id=uuid.uuid4(), owner_id=owner.id, title="Unrelated listing 2",
                status="active", source_kind="tool", source_id=sale_id,
            ),
            core_models.UserModulePref(
                user_id=owner.id, module_id="claims", enabled=False
            ),
            core_models.UserModulePref(
                user_id=owner.id, module_id="marketplace", enabled=False
            ),
        ]
    )
    db.commit()
    groups = _search(client, owner)
    assert "claims" not in groups
    assert "listings" not in groups
    rows = {r["title"]: r for r in groups["inventory"]["results"]}
    # Claims off: the broken tool no longer reads Sent out.
    assert rows[f"{PROBE} gated sent"]["status"] == {
        "key": "inventory.status.broken",
        "tone": "danger",
    }
    # Marketplace off: the listed tool no longer reads For sale.
    assert rows[f"{PROBE} gated sale"]["status"] == {
        "key": "inventory.status.available",
        "tone": "success",
    }


def test_ticket_listing_wishlist_truck_schedule_statuses(owner, other, db, client):
    db.add_all(
        [
            support_models.SupportTicket(
                id=uuid.uuid4(), user_id=owner.id,
                subject=f"{PROBE} upload fails", status="open",
            ),
            support_models.SupportTicket(
                id=uuid.uuid4(), user_id=owner.id,
                subject=f"{PROBE} billing question", status="under_review",
            ),
            support_models.SupportTicket(
                id=uuid.uuid4(), user_id=owner.id,
                subject=f"{PROBE} old question", status="closed",
            ),
            marketplace_models.SaleListing(
                id=uuid.uuid4(), owner_id=owner.id,
                title=f"{PROBE} socket set", status="sold",
            ),
            wishlist_models.WishlistItem(
                id=uuid.uuid4(), owner_id=owner.id,
                title=f"{PROBE} torque wrench", status="wanted",
            ),
            wishlist_models.WishlistItem(
                id=uuid.uuid4(), owner_id=owner.id,
                title=f"{PROBE} impact gun", status="purchased",
            ),
            truck_models.TruckAccount(
                id=uuid.uuid4(), dealer_user_id=owner.id,
                customer_user_id=other.id,
                customer_name=f"{PROBE} Carl", customer_email="carl@example.com",
                status="invited", invite_token="probe-token",
            ),
            maintenance_models.MaintenanceSchedule(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} press",
                kind="service", label="Hydraulic service",
                due_date=date.today() - timedelta(days=2),
            ),
            maintenance_models.MaintenanceSchedule(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} lift",
                kind="inspection", label="Lift inspection",
            ),
        ]
    )
    db.commit()
    groups = _search(client, owner)

    tickets = {r["title"]: r for r in groups["support"]["results"]}
    assert tickets[f"{PROBE} upload fails"]["status"] == {
        "key": "help.statusOpen",
        "tone": "accent",
    }
    assert tickets[f"{PROBE} billing question"]["status"] == {
        "key": "help.statusUnderReview",
        "tone": "warning",
    }
    assert tickets[f"{PROBE} old question"]["status"] == {
        "key": "help.statusClosed",
        "tone": "neutral",
    }
    # The raw status value no longer rides the detail field.
    assert all(r["detail"] == "" for r in tickets.values())

    listing = groups["listings"]["results"][0]
    assert listing["status"] == {"key": "marketplace.row.sold", "tone": "accent"}
    assert listing["detail"] == ""

    wish = {r["title"]: r for r in groups["wishlist"]["results"]}
    assert wish[f"{PROBE} torque wrench"]["status"] == {
        "key": "wishlist.status.wanted",
        "tone": "neutral",
    }
    assert wish[f"{PROBE} impact gun"]["status"] == {
        "key": "wishlist.status.purchased",
        "tone": "success",
    }

    truck = groups["truck_accounts"]["results"][0]
    assert truck["status"] == {"key": "truck.status.invited", "tone": "warning"}

    schedules = {r["title"]: r for r in groups["maintenance"]["results"]}
    assert schedules[f"{PROBE} press"]["status"] == {
        "key": "maintenance.dueStatus.overdue",
        "tone": "danger",
    }
    assert schedules[f"{PROBE} lift"]["status"] == {
        "key": "maintenance.dueStatus.unknown",
        "tone": "neutral",
    }


def test_statusless_families_carry_none(owner, db, client):
    db.add_all(
        [
            parts_models.Part(
                id=uuid.uuid4(), owner_id=owner.id, title=f"{PROBE} gear",
            ),
            borrowing_models.BorrowerContact(
                id=uuid.uuid4(), owner_id=owner.id, name=f"{PROBE} Person",
                contact="555-0100",
            ),
            print_models.PrintFile(
                id=uuid.uuid4(), publisher_id=owner.id,
                title=f"{PROBE} tray", category_key="socket-wrench",
                status="live",
            ),
        ]
    )
    db.commit()
    groups = _search(client, owner)
    assert groups["parts"]["results"][0]["status"] is None
    assert groups["people"]["results"][0]["status"] is None
    assert groups["prints"]["results"][0]["status"] is None


def test_downloads_rung_statuses_and_reach(db, client):
    rung = _make_user(
        db, "TV-MS-000913", "gss-rung@example.com", "Rung User",
        account_types=(), tier="downloads",
    )
    # The rung reads NO tier fallback (module_control): support
    # reaches it only through an explicit tier cell, the seed
    # migration 0096 makes in production; inventory stays dark.
    db.add(
        core_models.ModuleTierAccess(
            id=uuid.uuid4(), module_id="support", tier="downloads", enabled=True
        )
    )
    db.add(
        core_models.ModuleTierAccess(
            id=uuid.uuid4(), module_id="prints", tier="downloads", enabled=True
        )
    )
    db.add_all(
        [
            support_models.SupportTicket(
                id=uuid.uuid4(), user_id=rung.id,
                subject=f"{PROBE} rung ticket", status="open",
            ),
            print_models.PrintFile(
                id=uuid.uuid4(), publisher_id=rung.id,
                title=f"{PROBE} rung tray", category_key="socket-wrench",
                status="live",
            ),
            # Out of the rung's reach: must stay invisible, status
            # or no status.
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=rung.id, name=f"{PROBE} rung tool",
            ),
            claims_models.Claim(
                id=uuid.uuid4(), owner_id=rung.id, claim_number="2026-107",
                claim_year=2026, number_seq=107, kind="warranty_repair",
                status="filed", description=f"{PROBE} rung claim",
            ),
            borrowing_models.Checkout(
                id=uuid.uuid4(), owner_id=rung.id, item_kind="tool",
                item_id=uuid.uuid4(), item_name=f"{PROBE} rung loan",
                borrower_name="Nate", state="checked_out",
            ),
        ]
    )
    db.commit()
    groups = _search(client, rung)
    assert "inventory" not in groups
    assert "claims" not in groups
    assert "borrowing" not in groups
    ticket = groups["support"]["results"][0]
    assert ticket["status"] == {"key": "help.statusOpen", "tone": "accent"}
    # A family the rung CAN reach (prints, via its tier cell)
    # answers normally — and carries no invented status.
    assert groups["prints"]["results"][0]["status"] is None
