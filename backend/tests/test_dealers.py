"""Dealers module (item structure package, owner 2026-10-18: "this
dealer stuff, as integrated as it will be, should still be a module
— add, edit or remove at anytime").

Directory (platform) vs private companies, private agent records,
preferred agents (several per company, platform agents linked by
EXACT account number only), the item dealer tag, the operator
directory surface, and the removability contract: module OFF ->
tags hide, routes 403, stored data preserved, inventory untouched.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import models as inv_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types=(MECHANIC,), name="Dealer User", is_operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        is_operator=is_operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "owner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000402", "other@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000400", "operator@example.com", is_operator=True
    )


def _directory_company(client, operator, name="Directory Co", **overrides):
    payload = {"name": name, "email": "", "website": "", "address": "", "phones": [], "notes": ""}
    payload.update(overrides)
    resp = client.post("/api/admin/dealer-companies", json=payload, headers=auth_headers(operator))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _private_company(client, user, name="My Local Co", **overrides):
    payload = {"name": name, "email": "", "website": "", "address": "", "phones": [], "notes": ""}
    payload.update(overrides)
    resp = client.post("/api/dealers/companies", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_tool(client, user, **overrides):
    payload = {"name": "Wrench"}
    payload.update(overrides)
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- companies ---------------------------------------------------------------------


def test_directory_and_private_visibility(client, owner, other, operator):
    directory = _directory_company(client, operator)
    mine = _private_company(client, owner)

    listed = client.get("/api/dealers/companies", headers=auth_headers(owner)).json()
    assert {c["name"] for c in listed} == {"Directory Co", "My Local Co"}
    assert next(c for c in listed if c["name"] == "Directory Co")["is_directory"] is True
    assert next(c for c in listed if c["name"] == "My Local Co")["is_mine"] is True

    # The other user sees the directory, never my private company.
    listed_other = client.get("/api/dealers/companies", headers=auth_headers(other)).json()
    assert {c["name"] for c in listed_other} == {"Directory Co"}
    assert (
        client.get(f"/api/dealers/companies/{mine['id']}", headers=auth_headers(other)).status_code
        == 404
    )
    # And cannot edit or delete it either.
    assert (
        client.put(
            f"/api/dealers/companies/{mine['id']}",
            json={"name": "Hijacked", "phones": []},
            headers=auth_headers(other),
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/dealers/companies/{mine['id']}", headers=auth_headers(other)).status_code
        == 404
    )


def test_admin_directory_crud_and_audit(client, db, owner, operator):
    assert (
        client.get("/api/admin/dealer-companies", headers=auth_headers(owner)).status_code
        == 403
    )
    company = _directory_company(
        client, operator,
        phones=[{"label": "Customer Service", "number": "800-555-0100"}],
    )
    assert company["phones"] == [{"label": "Customer Service", "number": "800-555-0100"}]

    updated = client.put(
        f"/api/admin/dealer-companies/{company['id']}",
        json={"name": "Renamed Co", "email": "help@co.example", "website": "", "address": "", "phones": [], "notes": ""},
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Co"

    actions = [row.action for row in db.query(core_models.AuditLog).all()]
    assert "dealer_company.create" in actions
    assert "dealer_company.update" in actions

    assert (
        client.delete(f"/api/admin/dealer-companies/{company['id']}", headers=auth_headers(operator)).status_code
        == 204
    )
    assert client.get("/api/admin/dealer-companies", headers=auth_headers(operator)).json() == []


# -- item dealer tag -----------------------------------------------------------------


def test_item_dealer_tag_and_privacy(client, owner, other, operator):
    directory = _directory_company(client, operator)
    mine = _private_company(client, owner)
    theirs = _private_company(client, other, name="Their Co")

    tagged = _create_tool(client, owner, dealer_company_id=directory["id"])
    assert tagged["dealer_company_id"] == directory["id"]
    assert tagged["dealer_company_name"] == "Directory Co"

    tagged_mine = _create_tool(client, owner, name="Mine", dealer_company_id=mine["id"])
    assert tagged_mine["dealer_company_name"] == "My Local Co"

    # Another user's private company can't be tagged (it's invisible).
    resp = client.post(
        "/api/inventory",
        json={"name": "Nope", "dealer_company_id": theirs["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422

    # Battery tags follow the same rules.
    battery = client.post(
        "/api/inventory/batteries",
        json={"name": "M18", "dealer_company_id": directory["id"]},
        headers=auth_headers(owner),
    )
    assert battery.status_code == 201, battery.text
    assert battery.json()["dealer_company_name"] == "Directory Co"


# -- agents ----------------------------------------------------------------------------


def _private_agent(client, user, **overrides):
    payload = {"name": "Route Driver Dan", "phone": "555-0101", "email": "", "notes": ""}
    payload.update(overrides)
    resp = client.post("/api/dealers/agents/private", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_private_agents_are_owner_only(client, owner, other, operator):
    company = _directory_company(client, operator)
    agent = _private_agent(client, owner, company_id=company["id"])
    assert agent["company_name"] == "Directory Co"

    listed = client.get("/api/dealers/agents/private", headers=auth_headers(owner)).json()
    assert [a["name"] for a in listed] == ["Route Driver Dan"]
    assert client.get("/api/dealers/agents/private", headers=auth_headers(other)).json() == []
    assert (
        client.delete(f"/api/dealers/agents/private/{agent['id']}", headers=auth_headers(other)).status_code
        == 404
    )


def test_preferred_agents_multiple_and_platform_link(client, owner, other, operator):
    company = _directory_company(client, operator)
    dan = _private_agent(client, owner, name="Dan", company_id=company["id"])
    sue = _private_agent(client, owner, name="Sue", company_id=company["id"])

    for agent in (dan, sue):
        resp = client.post(
            "/api/dealers/preferred",
            json={"company_id": company["id"], "private_agent_id": agent["id"]},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 201, resp.text

    # A platform agent links by EXACT account number only.
    linked = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "agent_account_number": other.account_number},
        headers=auth_headers(owner),
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["kind"] == "platform"
    assert linked.json()["account_number"] == other.account_number

    preferred = client.get(
        f"/api/dealers/preferred?company_id={company['id']}", headers=auth_headers(owner)
    ).json()
    # Several preferred agents per company is the model: two private
    # records + one platform link.
    assert len(preferred) == 3
    assert sorted(p["name"] for p in preferred if p["kind"] == "private") == ["Dan", "Sue"]
    assert [p["kind"] for p in preferred].count("platform") == 1

    # Unknown account number: refused, no enumeration hints.
    resp = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "agent_account_number": "TV-M-999999"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # Yourself: refused.
    resp = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "agent_account_number": owner.account_number},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    # Another user's private agent: refused.
    foreign = _private_agent(client, other, name="Foreign")
    resp = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "private_agent_id": foreign["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_agent_on_record_is_the_earliest_preferred(client, db, owner, other, operator):
    """The Warranty tab's read (owner batch 2026-11-03): the
    agent on record is the EARLIEST preferred row — the same
    resolution a warranty claim defaults to — and a company with
    no preferred rows answers None."""
    from datetime import timedelta

    from app.modules.dealers import models as dealer_models

    company = _directory_company(client, operator)
    dan = _private_agent(client, owner, name="Dan", company_id=company["id"])
    sue = _private_agent(client, owner, name="Sue", company_id=company["id"])
    for agent in (dan, sue):
        resp = client.post(
            "/api/dealers/preferred",
            json={"company_id": company["id"], "private_agent_id": agent["id"]},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 201, resp.text
    # The two API adds can land inside the same timestamp tick;
    # pin the record order explicitly (Dan first, Sue an hour
    # later) so the earliest-row rule is what decides.
    rows = (
        db.query(dealer_models.PreferredAgent)
        .filter(dealer_models.PreferredAgent.user_id == owner.id)
        .all()
    )
    by_agent = {str(r.private_agent_id): r for r in rows}
    by_agent[sue["id"]].created_at = by_agent[dan["id"]].created_at + timedelta(hours=1)
    db.commit()

    on_record = client.get(
        f"/api/dealers/preferred/on-record?company_id={company['id']}",
        headers=auth_headers(owner),
    )
    assert on_record.status_code == 200, on_record.text
    # Exactly one flagged (Dan — Sue joined unstarred), so the
    # summary names him (preferred-display rule, 2026-11-06).
    assert on_record.json()["state"] == "one"
    assert on_record.json()["agent"]["name"] == "Dan"
    assert on_record.json()["agent"]["kind"] == "private"

    # Another user has no agent on record for the company.
    stranger = client.get(
        f"/api/dealers/preferred/on-record?company_id={company['id']}",
        headers=auth_headers(other),
    )
    assert stranger.status_code == 200
    assert stranger.json() == {"state": "none", "agent": None}


# -- the removability contract ----------------------------------------------------------


def test_dealers_module_off_hides_tags_and_preserves_data(client, db, owner, operator):
    company = _directory_company(client, operator)
    tagged = _create_tool(client, owner, dealer_company_id=company["id"])
    assert tagged["dealer_company_name"] == "Directory Co"

    db.add(core_models.ModuleState(module_id="dealers", globally_enabled=False))
    db.commit()

    # Routes gate with the module code...
    resp = client.get("/api/dealers/companies", headers=auth_headers(owner))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"
    mine = client.get("/api/core/my-modules", headers=auth_headers(owner)).json()
    assert "dealers" not in [m["id"] for m in mine]

    # ...the tag HIDES on item payloads...
    view = client.get(f"/api/inventory/{tagged['id']}", headers=auth_headers(owner)).json()
    assert view["dealer_company_id"] is None
    assert view["dealer_company_name"] is None

    # ...inventory itself is fully functional...
    assert client.get("/api/inventory", headers=auth_headers(owner)).status_code == 200
    created = _create_tool(client, owner, name="Still works")
    assert created["name"] == "Still works"

    # ...and the stored tag is untouched (data preserved).
    row = db.get(inv_models.Tool, uuid.UUID(tagged["id"]))
    assert str(row.dealer_company_id) == company["id"]


def test_dealers_unassigned_group_loses_module_but_not_inventory(client, db, owner):
    # Operator unassigns dealers from every group.
    for group in ("mechanic_technician", "shop_company", "tool_dealer", "insurance"):
        db.add(
            core_models.ModuleAccess(
                module_id="dealers", account_group=group, enabled=False
            )
        )
    db.commit()
    assert client.get("/api/dealers/companies", headers=auth_headers(owner)).status_code == 403
    assert client.get("/api/inventory", headers=auth_headers(owner)).status_code == 200
