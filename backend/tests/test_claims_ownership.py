"""Claims ownership (owner ruling, 2026-11-06 23:45):

  - a repair claim is ALWAYS filed by the tool's OWNER — a shop
    can claim its OWN items, never an employee's; the mechanic
    does his own claims himself, including while registered
    under the shop (an active crew membership changes nothing);
  - claim money is PURCHASE COST — what the owner paid. A
    warranty claim auto-prices its line from purchase_price;
    an item with a replacement cost but NO purchase price
    starts unpriced rather than letting the replacement figure
    stand in; disaster lines price on the purchase basis too,
    and the retired replacement/MSRP bases are refused;
  - the shop's window into a crew member's tools is the
    member's own shop-group sharing projection — read-only,
    gated on ACTIVE membership + the member's sharing switch;
    membership alone exposes nothing;
  - the flows around the ruling keep working: an owner-filed
    claim's verified agent still works the ladder.

The cast: Sue Shop (shop_company) employs Eddie Employee
(mechanic_technician, active crew member). Dan Dealer is a
verified agent of a directory company and Eddie's agent on
record for it.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.core import models as core_models
from app.modules.core import sharing as sharing_service
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name="Test User"):
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
    return _make_user(
        db, "TV-S-000901", "own-shop@example.com", [SHOP], "Sue Shop"
    )


@pytest.fixture()
def employee(db):
    return _make_user(
        db, "TV-M-000902", "own-employee@example.com", [MECHANIC],
        "Eddie Employee",
    )


@pytest.fixture()
def agent(db):
    return _make_user(
        db, "TV-D-000903", "own-agent@example.com", [DEALER], "Dan Dealer"
    )


@pytest.fixture()
def crew(db, shop, employee):
    """Eddie is an ACTIVE member of Sue's crew."""
    row = core_models.ShopMembership(
        shop_user_id=shop.id,
        employee_user_id=employee.id,
        invite_email=employee.email,
        invite_token=f"tok-{uuid.uuid4().hex[:24]}",
        role_label="Technician",
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 5.0 pack", **overrides):
    battery = inventory_models.Battery(owner_id=owner.id, name=name, **overrides)
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _file_warranty(client, user, target_kind, target_id, **extra):
    payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "dealer_notified": False,
        "problem": "It broke.",
    }
    payload.update(extra)
    return client.post(
        "/api/claims/warranty", json=payload, headers=auth_headers(user)
    )


# -- owner-only filing ----------------------------------------------------------


def test_shop_cannot_file_warranty_claim_on_employee_items(
    client, db, shop, employee, crew
):
    tool = _tool(db, employee, purchase_price=Decimal("100.00"))
    battery = _battery(db, employee, purchase_price=Decimal("50.00"))
    tool_set = _tool(db, employee, name="Socket set", is_set=True)
    piece = inventory_models.SetPiece(
        owner_id=employee.id, set_id=tool_set.id, name="10mm socket",
        kind="core",
    )
    db.add(piece)
    db.commit()
    for kind, target in (
        ("tool", tool),
        ("battery", battery),
        ("set", tool_set),
        ("piece", piece),
    ):
        response = _file_warranty(client, shop, kind, target.id)
        assert response.status_code == 404, (kind, response.text)
        assert "isn't in your vault" in response.json()["detail"]
    # Nothing was born on either side.
    assert client.get("/api/claims", headers=auth_headers(shop)).json() == []
    assert client.get("/api/claims", headers=auth_headers(employee)).json() == []


def test_employee_cannot_file_on_the_shops_tool(client, db, shop, employee, crew):
    shop_tool = _tool(db, shop, purchase_price=Decimal("300.00"))
    response = _file_warranty(client, employee, "tool", shop_tool.id)
    assert response.status_code == 404


def test_employee_files_on_own_tool_and_shop_on_its_own(
    client, db, shop, employee, crew
):
    employee_tool = _tool(db, employee, purchase_price=Decimal("100.00"))
    created = _file_warranty(client, employee, "tool", employee_tool.id)
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    mine = client.get("/api/claims", headers=auth_headers(employee)).json()
    assert [row["id"] for row in mine] == [claim["id"]]
    # The shop does not see the employee's claim in its own list.
    assert client.get("/api/claims", headers=auth_headers(shop)).json() == []

    shop_tool = _tool(db, shop, name="Shop lift", purchase_price=Decimal("900.00"))
    created = _file_warranty(client, shop, "tool", shop_tool.id)
    assert created.status_code == 201, created.text


def test_disaster_lines_are_owner_only_too(client, db, shop, employee, crew):
    employee_tool = _tool(db, employee, purchase_price=Decimal("100.00"))
    shop_tool = _tool(db, shop, purchase_price=Decimal("300.00"))
    # The shop's own draft claim can't take the employee's item.
    claim = client.post(
        "/api/disaster-claims", json={}, headers=auth_headers(shop)
    )
    assert claim.status_code == 201, claim.text
    claim_id = claim.json()["id"]
    response = client.post(
        f"/api/disaster-claims/{claim_id}/lines",
        json={"target_kind": "tool", "target_id": str(employee_tool.id)},
        headers=auth_headers(shop),
    )
    assert response.status_code == 404, response.text
    response = client.post(
        f"/api/disaster-claims/{claim_id}/lines",
        json={"target_kind": "tool", "target_id": str(shop_tool.id)},
        headers=auth_headers(shop),
    )
    assert response.status_code == 201, response.text
    # And the employee can't reach the shop's claim at all.
    employee_claims = client.get(
        "/api/disaster-claims", headers=auth_headers(employee)
    ).json()
    assert employee_claims == []


# -- claim money = purchase cost -------------------------------------------------


def test_warranty_claim_money_is_purchase_cost(client, db, employee):
    tool = _tool(
        db, employee, purchase_price=Decimal("120.00"), quantity=2,
        replacement_cost=Decimal("999.00"), msrp=Decimal("888.00"),
    )
    created = _file_warranty(client, employee, "tool", tool.id)
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    line = claim["lines"][0]
    assert line["value_basis"] == "purchase"
    assert Decimal(line["amount"]) == Decimal("240.00")  # 120 x 2
    assert Decimal(claim["total_amount"]) == Decimal("240.00")


def test_warranty_claim_without_purchase_price_starts_unpriced(
    client, db, employee
):
    # A replacement cost is recorded but no purchase price: the
    # claim is still born (never blocked by a missing price) and
    # the line starts UNPRICED — the replacement figure never
    # silently stands in for what the owner paid.
    tool = _tool(db, employee, replacement_cost=Decimal("500.00"))
    created = _file_warranty(client, employee, "tool", tool.id)
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    line = claim["lines"][0]
    assert line["value_basis"] == "entered"
    assert line["amount"] is None
    assert Decimal(claim["total_amount"]) == Decimal("0.00")


def test_set_warranty_claim_prices_from_purchase_total(client, db, employee):
    tool_set = _tool(
        db, employee, name="Socket set", is_set=True,
        purchase_price=Decimal("300.00"), replacement_cost=Decimal("500.00"),
    )
    addon = inventory_models.SetPiece(
        owner_id=employee.id, set_id=tool_set.id, name="Addon ratchet",
        kind="addon", price=Decimal("45.00"),
    )
    db.add(addon)
    db.commit()
    created = _file_warranty(
        client, employee, "set", tool_set.id, include_addons=True
    )
    assert created.status_code == 201, created.text
    line = created.json()["claim"]["lines"][0]
    assert line["value_basis"] == "purchase"
    assert Decimal(line["amount"]) == Decimal("345.00")  # 300 + 45


# -- the agent still works an owner-filed claim -----------------------------------


def test_agent_still_works_the_employees_claim(
    client, db, shop, employee, agent, crew
):
    company = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(company)
    db.commit()
    db.add(
        dealer_models.CompanyRepresentation(
            company_id=company.id, agent_user_id=agent.id, verified=True
        )
    )
    db.add(
        dealer_models.PreferredAgent(
            user_id=employee.id, company_id=company.id,
            agent_user_id=agent.id,
        )
    )
    db.commit()
    tool = _tool(
        db, employee, purchase_price=Decimal("100.00"),
        dealer_company_id=company.id,
    )
    created = _file_warranty(
        client, employee, "tool", tool.id, dealer_notified=True
    )
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    assert claim["warranty_agent"]["agent_user_id"] == str(agent.id)
    # The agent sees it in the worklist and moves the ladder.
    incoming = client.get(
        "/api/claims/incoming", headers=auth_headers(agent)
    ).json()
    assert [row["id"] for row in incoming] == [claim["id"]]
    moved = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "in_repair"},
        headers=auth_headers(agent),
    )
    assert moved.status_code == 200, moved.text
    # The shop seat has no seat on it at all.
    view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(shop)
    )
    assert view.status_code == 404


# -- the shop's read-only window into a member's list ----------------------------


def _share_with_shop(db, employee, tools, fields):
    sharing_service.update_config(
        db, employee.id, "shop_company", True, fields
    )
    sharing_service.set_shared_items(
        db, employee.id, "shop_company", [t.id for t in tools]
    )


def test_shop_member_tools_follow_the_members_sharing(
    client, db, shop, employee, crew
):
    shared = _tool(
        db, employee, name="Shared wrench",
        purchase_price=Decimal("120.00"), replacement_cost=Decimal("200.00"),
        category="Wrenches",
    )
    _tool(db, employee, name="Unshared drill")  # never put on the list
    url = f"/api/core/crew/members/{employee.id}/tools"

    # Membership alone exposes nothing: no sharing configured.
    view = client.get(url, headers=auth_headers(shop))
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["sharing_enabled"] is False
    assert body["items"] == []

    # The member shares the one tool, purchase fields included.
    _share_with_shop(
        db, employee, [shared],
        ["category", "purchase_price", "replacement_cost"],
    )
    body = client.get(url, headers=auth_headers(shop)).json()
    assert body["sharing_enabled"] is True
    assert body["member_name"] == "Eddie Employee"
    assert [row["name"] for row in body["items"]] == ["Shared wrench"]
    row = body["items"][0]
    assert row["category"] == "Wrenches"
    assert Decimal(row["purchase_price"]) == Decimal("120.00")
    # Fields the member did NOT choose are absent, not nulled.
    assert "notes" not in row
    assert "purchase_date" not in row


def test_member_tools_refuse_non_members_and_non_shops(
    client, db, shop, employee, agent, crew
):
    url = f"/api/core/crew/members/{employee.id}/tools"
    # A stranger's id in the path: not the caller's crew → 404.
    stranger = _make_user(
        db, "TV-M-000904", "own-stranger@example.com", [MECHANIC], "Sam Stranger"
    )
    assert client.get(
        f"/api/core/crew/members/{stranger.id}/tools",
        headers=auth_headers(shop),
    ).status_code == 404
    # The employee is not a shop owner — the surface refuses.
    response = client.get(url, headers=auth_headers(employee))
    assert response.status_code == 422
    # A member who LEFT is no longer visible either.
    crew.status = "left"
    db.commit()
    assert client.get(url, headers=auth_headers(shop)).status_code == 404


def test_shop_write_attempts_on_employee_items_are_refused(
    client, db, shop, employee, crew
):
    tool = _tool(db, employee, purchase_price=Decimal("100.00"))
    # The pure shop seat doesn't even hold the inventory module
    # (its seeded defaults are the mechanic group) — the gate
    # itself refuses before any item is addressed.
    response = client.get(
        f"/api/inventory/{tool.id}", headers=auth_headers(shop)
    )
    assert response.status_code == 403
    # A shop owner who also holds the mechanic group (the common
    # real shape — the owner wrenches too) gets the owner-scope
    # answer: the employee's item doesn't exist for them — not
    # to read, not to delete.
    multi = _make_user(
        db, "TV-S-000905", "own-multi@example.com", [SHOP, MECHANIC],
        "Mike Multi",
    )
    response = client.get(
        f"/api/inventory/{tool.id}", headers=auth_headers(multi)
    )
    assert response.status_code == 404
    response = client.delete(
        f"/api/inventory/{tool.id}", headers=auth_headers(multi)
    )
    assert response.status_code == 404
    db.refresh(tool)
    assert tool.name == "Impact wrench"
