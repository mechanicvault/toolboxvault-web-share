"""Wave 3 — shop employee invites (crew).

Pins:
- invite by email (no existence oracle: the same 201 + shape
  whether or not the address has an account) and by exact
  account number; only shop_company-group holders can invite;
- the pre-signup attach: an invite addressed to an email with no
  account claims onto the account when it appears;
- accept / decline / remove / leave lifecycle + notifications;
- the 30-DAY RULE: leave starts the clock; the scheduler job
  sends the day-25 ("5 days left") and expiry notices
  idempotently, and stays silent for members who rejoined a crew
  or hold their own paid plan;
- BRACKET TRUTH: the crew summary reads the subscription's
  STORED bracket and notes a mismatch — no enforcement;
- HARD PIN: membership alone exposes ZERO inventory — the
  tier-sharing preview stays empty until the owner shares
  through the sharing settings; the gate is sharing, never
  membership.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.billing import models as billing_models
from app.modules.core import crew as crew_service
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"


def _make_user(db, account_number, email, account_types, name="Crew User"):
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
def shop(db):
    return _make_user(db, "TV-S-000301", "crew-shop@example.com", [SHOP], "The Shop")


@pytest.fixture()
def tech(db):
    return _make_user(db, "TV-M-000302", "crew-tech@example.com", [MECHANIC], "Tech One")


def _notifications(db, user_id, kind=None):
    stmt = select(core_models.Notification).where(
        core_models.Notification.user_id == user_id
    )
    if kind:
        stmt = stmt.where(core_models.Notification.kind == kind)
    return list(db.scalars(stmt))


def _invite_and_accept(client, db, shop, tech, role="Technician"):
    response = client.post(
        "/api/core/crew/invite",
        json={"email": tech.email, "role_label": role},
        headers=auth_headers(shop),
    )
    assert response.status_code == 201, response.text
    membership = response.json()
    accepted = client.post(
        f"/api/core/crew/invites/{membership['id']}/respond",
        json={"accept": True},
        headers=auth_headers(tech),
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


# -- inviting -----------------------------------------------------------------


def test_only_shop_group_holders_can_invite(client, db, shop, tech):
    response = client.post(
        "/api/core/crew/invite",
        json={"email": "someone@example.com"},
        headers=auth_headers(tech),
    )
    assert response.status_code == 422
    assert client.get("/api/core/crew", headers=auth_headers(tech)).status_code == 422
    assert client.get("/api/core/crew", headers=auth_headers(shop)).status_code == 200


def test_invite_by_email_no_oracle(client, db, shop):
    # Address WITH an account vs WITHOUT: identical surface.
    known = client.post(
        "/api/core/crew/invite",
        json={"email": "crew-shop@example.com"},
        headers=auth_headers(shop),
    )
    # (inviting your own address is refused — that's not the oracle case)
    assert known.status_code == 422
    existing = _make_user(db, "TV-M-000303", "has-account@example.com", [MECHANIC])
    with_account = client.post(
        "/api/core/crew/invite",
        json={"email": existing.email, "role_label": "Tech"},
        headers=auth_headers(shop),
    )
    without_account = client.post(
        "/api/core/crew/invite",
        json={"email": "no-account-yet@example.com", "role_label": "Tech"},
        headers=auth_headers(shop),
    )
    assert with_account.status_code == without_account.status_code == 201
    assert set(with_account.json()) == set(without_account.json())
    assert with_account.json()["status"] == "invited"
    # The account holder was notified; the unknown address simply waits.
    assert len(_notifications(db, existing.id, "crew_invite_received")) == 1


def test_invite_by_account_number(client, db, shop, tech):
    response = client.post(
        "/api/core/crew/invite",
        json={"account_number": tech.account_number, "role_label": "Lead"},
        headers=auth_headers(shop),
    )
    assert response.status_code == 201, response.text
    assert response.json()["employee_user_id"] == str(tech.id)
    missing = client.post(
        "/api/core/crew/invite",
        json={"account_number": "TV-M-999999"},
        headers=auth_headers(shop),
    )
    assert missing.status_code == 422
    both = client.post(
        "/api/core/crew/invite",
        json={"email": tech.email, "account_number": tech.account_number},
        headers=auth_headers(shop),
    )
    assert both.status_code == 422


def test_pre_signup_invite_attaches_when_the_account_appears(client, db, shop):
    invited = client.post(
        "/api/core/crew/invite",
        json={"email": "future-tech@example.com", "role_label": "Apprentice"},
        headers=auth_headers(shop),
    )
    assert invited.status_code == 201
    assert invited.json()["employee_user_id"] is None
    # The account is created later (direct row = the signup's effect).
    newcomer = _make_user(
        db, "TV-M-000304", "future-tech@example.com", [MECHANIC], "New Tech"
    )
    inbox = client.get("/api/core/crew/invites", headers=auth_headers(newcomer))
    assert inbox.status_code == 200
    assert [row["id"] for row in inbox.json()] == [invited.json()["id"]]
    assert len(_notifications(db, newcomer.id, "crew_invite_received")) == 1


# -- lifecycle -------------------------------------------------------------------


def test_accept_decline_remove_leave(client, db, shop, tech):
    membership = _invite_and_accept(client, db, shop, tech)
    assert membership["status"] == "active"
    assert membership["accepted_at"] is not None
    roster = client.get("/api/core/crew", headers=auth_headers(shop)).json()
    assert [r["status"] for r in roster] == ["active"]
    assert len(_notifications(db, shop.id, "crew_invite_accepted")) == 1
    my_shops = client.get("/api/core/crew/my-shops", headers=auth_headers(tech))
    assert [r["id"] for r in my_shops.json()] == [membership["id"]]

    # The member leaves: status left, clock running, both sides notified.
    left = client.post(
        f"/api/core/crew/my-shops/{membership['id']}/leave",
        headers=auth_headers(tech),
    )
    assert left.status_code == 200
    assert left.json()["status"] == "left"
    assert left.json()["grace_days_left"] == 30
    assert len(_notifications(db, tech.id, "crew_left")) == 1
    assert len(_notifications(db, shop.id, "crew_left")) == 1

    # Decline path.
    second = _make_user(db, "TV-M-000305", "crew-tech2@example.com", [MECHANIC])
    invite = client.post(
        "/api/core/crew/invite",
        json={"email": second.email},
        headers=auth_headers(shop),
    ).json()
    declined = client.post(
        f"/api/core/crew/invites/{invite['id']}/respond",
        json={"accept": False},
        headers=auth_headers(second),
    )
    assert declined.json()["status"] == "declined"
    assert len(_notifications(db, shop.id, "crew_invite_declined")) == 1

    # Owner removes an active member.
    third = _make_user(db, "TV-M-000306", "crew-tech3@example.com", [MECHANIC])
    membership3 = _invite_and_accept(client, db, shop, third)
    removed = client.post(
        f"/api/core/crew/{membership3['id']}/remove", headers=auth_headers(shop)
    )
    assert removed.json()["status"] == "left"
    assert len(_notifications(db, third.id, "crew_left")) == 1


# -- the 30-day rule ----------------------------------------------------------------


def _leave_long_ago(db, shop, tech, days_ago):
    row = core_models.ShopMembership(
        shop_user_id=shop.id,
        employee_user_id=tech.id,
        invite_email=tech.email,
        invite_token=f"tok-{uuid.uuid4()}",
        role_label="Tech",
        status="left",
        accepted_at=datetime.now(timezone.utc) - timedelta(days=days_ago + 5),
        left_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_grace_notices_day25_and_expiry_are_idempotent(client, db, shop, tech):
    row = _leave_long_ago(db, shop, tech, days_ago=25)
    sent = crew_service.run_grace_notifications(db)
    assert sent == {"day25": 1, "expired": 0}
    assert len(_notifications(db, tech.id, "crew_grace_ending")) == 1
    # Re-run: nothing twice.
    assert crew_service.run_grace_notifications(db) == {"day25": 0, "expired": 0}
    assert len(_notifications(db, tech.id, "crew_grace_ending")) == 1

    row.left_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    sent = crew_service.run_grace_notifications(db)
    assert sent == {"day25": 0, "expired": 1}
    assert len(_notifications(db, tech.id, "crew_grace_expired")) == 1
    assert crew_service.run_grace_notifications(db) == {"day25": 0, "expired": 0}


def test_grace_notices_skip_settled_members(client, db, shop, tech):
    # Departed 40 days ago but REJOINED another crew since: silent.
    _leave_long_ago(db, shop, tech, days_ago=40)
    other_shop = _make_user(db, "TV-S-000307", "crew-shop2@example.com", [SHOP])
    _invite_and_accept(client, db, other_shop, tech)
    assert crew_service.run_grace_notifications(db) == {"day25": 0, "expired": 0}
    assert _notifications(db, tech.id, "crew_grace_expired") == []

    # A member with their own PAID plan is settled too.
    payer = _make_user(db, "TV-M-000308", "crew-payer@example.com", [MECHANIC])
    _leave_long_ago(db, shop, payer, days_ago=40)
    db.add(
        billing_models.Subscription(
            user_id=payer.id,
            plan_key="pro",
            status="active",
            source="test",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    db.commit()
    assert crew_service.run_grace_notifications(db) == {"day25": 0, "expired": 0}
    assert _notifications(db, payer.id, "crew_grace_expired") == []


# -- bracket truth ---------------------------------------------------------------------


def test_crew_summary_bracket_truth(client, db, shop):
    db.add(
        billing_models.BusinessBracket(
            plan_key="business", bracket_key="biz_5", up_to_employees=1
        )
    )
    db.add(
        billing_models.Subscription(
            user_id=shop.id,
            plan_key="business",
            status="active",
            source="test",
            bracket_key="biz_5",
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    db.commit()
    first = _make_user(db, "TV-M-000309", "crew-b1@example.com", [MECHANIC])
    second = _make_user(db, "TV-M-000310", "crew-b2@example.com", [MECHANIC])
    _invite_and_accept(client, db, shop, first)
    _invite_and_accept(client, db, shop, second)
    summary = client.get("/api/core/crew/summary", headers=auth_headers(shop))
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["active_count"] == 2
    assert body["bracket"]["bracket_key"] == "biz_5"
    assert body["bracket"]["label"] == "up to 1 employees"
    # 2 active > bracket of 1: the friendly mismatch note shows.
    assert "nothing is enforced automatically" in body["bracket_note"]


def test_crew_summary_without_subscription_has_no_bracket(client, db, shop):
    body = client.get("/api/core/crew/summary", headers=auth_headers(shop)).json()
    assert body["active_count"] == 0
    assert body["bracket"] is None
    assert body["bracket_note"] == ""


# -- HARD PIN: membership exposes zero inventory -----------------------------------------


def test_membership_alone_exposes_zero_inventory(client, db, shop, tech):
    tool = inventory_models.Tool(
        owner_id=shop.id, name="Shop press", brand="OTC", model="",
        serial_number="", purchase_price=500,
    )
    db.add(tool)
    db.commit()
    membership = _invite_and_accept(client, db, shop, tech)
    assert membership["status"] == "active"

    # The owner's tier-sharing preview for the shop group — what
    # crew-side recipients would receive — is EMPTY: no sharing
    # was ever configured, and membership is not sharing.
    from app.modules.core import sharing

    assert sharing.build_preview(db, shop.id, "shop_company") == []
    # The member's own inventory surface shows only their own
    # (empty) vault: the shop's press is not reachable through it.
    mine = client.get("/api/inventory", headers=auth_headers(tech))
    assert mine.status_code == 200
    assert mine.json() == []

    # Now the owner turns tier sharing ON and picks the tool:
    # the preview fills — proving the gate was sharing all along.
    db.add(
        core_models.ShareConfig(
            owner_id=shop.id, recipient_group="shop_company",
            enabled=True, fields=[],
        )
    )
    db.add(
        core_models.SharedItem(
            owner_id=shop.id, item_kind="tool", tool_id=tool.id,
            recipient_group="shop_company",
        )
    )
    db.commit()
    preview = sharing.build_preview(db, shop.id, "shop_company")
    assert [row["name"] for row in preview] == ["Shop press"]
