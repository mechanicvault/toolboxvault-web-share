"""Warranty claims are AGENT-scoped (owner rulings, 2026-10-31).

The revision (files/claims-agent-scope-revision-2026-10-31.md)
supersedes the 2026-10-25 company seat:

  - a warranty claim's viewers are the OWNER and ONE agent — the
    owner's dealer agent for the claim (default: the agent on
    record, i.e. the earliest preferred-agent row for the dealer;
    changeable at filing and after);
  - the dealer COMPANY gets no access at all: not its other
    agents, not its principal, not even the owner's OTHER
    preferred agents for the same company;
  - the agent's seat is live only when the agent pointer resolves
    to a platform user with a VERIFIED representation of the
    dealer (H-1 at agent level) — an unverified self-claimed
    representation sees nothing, is told nothing;
  - no agent = only the owner can see the claim, and the owner
    drives every status, note and update himself;
  - a claim's seat HOLDS (stage 1, 2026-11-04; multi-preferred,
    2026-11-05 — these supersede the 2026-10-31 follow ruling
    below in the git history): preferred is now a per-agent
    star any number of agents may hold, there is no switch,
    and starring, unstarring or disconnecting NEVER moves a
    claim — a hand re-point is final until the owner himself
    moves it again;
  - reports go to the AGENT (verified inbox seat, else the
    agent's email on record) — never to the company;
  - warranty claims carry a manufacturer claim/case number, not
    an insurance policy; insurance claims are untouched (control
    cases below).
"""

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
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
def owner(db):
    return _make_user(
        db, "TV-M-001101", "scope-owner@example.com", [MECHANIC], "Ollie Owner"
    )


@pytest.fixture()
def agent1(db):
    return _make_user(
        db, "TV-D-001102", "scope-agent1@example.com", [DEALER], "Agent One"
    )


@pytest.fixture()
def agent2(db):
    return _make_user(
        db, "TV-D-001103", "scope-agent2@example.com", [DEALER], "Agent Two"
    )


@pytest.fixture()
def principal(db):
    return _make_user(
        db, "TV-D-001104", "scope-boss@example.com", [DEALER], "Company Boss"
    )


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _company(db, name="Matco Tools", *, email=""):
    company = dealer_models.DealerCompany(
        name=name, email=email, is_directory=True
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _represent(db, company, user, *, verified=True):
    row = dealer_models.CompanyRepresentation(
        company_id=company.id, agent_user_id=user.id, verified=verified
    )
    db.add(row)
    db.commit()
    return row


def _prefer_platform(db, owner, company, agent_user, *, minutes_ago=0):
    row = dealer_models.PreferredAgent(
        user_id=owner.id, company_id=company.id, agent_user_id=agent_user.id
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if minutes_ago:
        # "Agent on record" = the EARLIEST preferred row; rows
        # stamped in the same second would tie and fall to the id
        # tiebreak, so fixtures separate the stamps explicitly.
        from datetime import timedelta

        row.created_at = row.created_at - timedelta(minutes=minutes_ago)
        db.commit()
        db.refresh(row)
    return row


def _private_agent(db, owner, company, name="Pat Private", email=""):
    agent = dealer_models.PrivateAgent(
        owner_id=owner.id, company_id=company.id, name=name, email=email
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _prefer_private(db, owner, company, agent):
    row = dealer_models.PreferredAgent(
        user_id=owner.id, company_id=company.id, private_agent_id=agent.id
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _warranty(client, user, target_kind, target_id, **kwargs):
    payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "dealer_notified": False,
        "problem": "It stopped working.",
    }
    payload.update(kwargs)
    return client.post(
        "/api/claims/warranty", json=payload, headers=auth_headers(user)
    )


def _get_claim(client, user, claim_id):
    return client.get(f"/api/claims/{claim_id}", headers=auth_headers(user))


def _assert_no_access(response):
    """A foreign claim is invisible. Two shapes, both standing
    site discipline (claims routes' _party_view): a caller who
    holds the claims module gets 404-for-foreign; a dealer-only
    account — which holds no claims entitlement at all — gets
    the module gate's uniform 403 for ANY claim id, the same
    answer whether the claim exists or not, so nothing about
    this claim leaks either way."""
    if response.status_code == 404:
        return
    assert response.status_code == 403, response.status_code
    assert response.json()["detail"]["code"] == "module_unavailable"


def _notifications(db, user, kind=None):
    stmt = select(core_models.Notification).where(
        core_models.Notification.user_id == user.id
    )
    if kind:
        stmt = stmt.where(core_models.Notification.kind == kind)
    return list(db.scalars(stmt))


def _outbox(db, recipient=None):
    stmt = select(core_models.EmailOutbox)
    if recipient:
        stmt = stmt.where(core_models.EmailOutbox.recipient == recipient)
    return list(db.scalars(stmt))


def _claim_row(db, claim_id):
    return db.get(claims_models.Claim, uuid.UUID(str(claim_id)))


# -- the seat itself: assigned + verified only -------------------------------


def test_assigned_verified_agent_sees_and_works_the_claim(
    client, db, owner, agent1
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    # The claim names its agent; the owner sees all of his claims.
    assert claim["warranty_agent"]["agent_user_id"] == str(agent1.id)
    assert claim["warranty_agent"]["has_access"] is True
    listing = client.get("/api/claims", headers=auth_headers(owner)).json()
    assert [row["id"] for row in listing] == [claim["id"]]
    assert listing[0]["warranty_agent_name"] == "Agent One"

    # The agent's worklist + detail view.
    incoming = client.get(
        "/api/claims/incoming", headers=auth_headers(agent1)
    ).json()
    assert [row["id"] for row in incoming] == [claim["id"]]
    view = _get_claim(client, agent1, claim["id"])
    assert view.status_code == 200, view.text
    assert view.json()["viewer_role"] == "dealer"

    # The agent drives the middle of the ladder; the owner hears.
    moved = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "in_repair"},
        headers=auth_headers(agent1),
    )
    assert moved.status_code == 200, moved.text
    assert len(_notifications(db, owner, "warranty_claim_update")) == 1


def test_second_agent_and_principal_of_same_company_see_nothing(
    client, db, owner, agent1, agent2, principal
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, agent2, verified=True)
    _represent(db, company, principal, verified=True)
    _prefer_platform(db, owner, company, agent1, minutes_ago=2)
    # agent2 is ALSO the owner's preferred agent for the company
    # (added second) — still not the claim's assigned agent.
    _prefer_platform(db, owner, company, agent2, minutes_ago=1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    assert claim["warranty_agent"]["agent_user_id"] == str(agent1.id)

    for other in (agent2, principal):
        _assert_no_access(_get_claim(client, other, claim["id"]))
        assert (
            client.get(
                "/api/claims/incoming", headers=auth_headers(other)
            ).json()
            == []
        )
        moved = client.post(
            f"/api/claims/{claim['id']}/transition",
            json={"to_status": "in_repair"},
            headers=auth_headers(other),
        )
        _assert_no_access(moved)
        # Not even a notification leaks the claim's existence.
        assert _notifications(db, other, "warranty_claim_new") == []


def test_unverified_agent_link_gets_nothing_until_verified(
    client, db, owner, agent1
):
    company = _company(db)
    rep = _represent(db, company, agent1, verified=False)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    # Assigned — but the seat is dark while the link is unverified.
    assert claim["warranty_agent"]["agent_user_id"] == str(agent1.id)
    assert claim["warranty_agent"]["has_access"] is False
    _assert_no_access(_get_claim(client, agent1, claim["id"]))
    assert (
        client.get("/api/claims/incoming", headers=auth_headers(agent1)).json()
        == []
    )
    assert _notifications(db, agent1, "warranty_claim_new") == []

    # The operator verifies the representation: the seat lights up.
    rep.verified = True
    db.commit()
    view = _get_claim(client, agent1, claim["id"])
    assert view.status_code == 200, view.text
    assert view.json()["viewer_role"] == "dealer"


def test_no_agent_claim_is_owner_only_and_owner_drives(
    client, db, owner, agent1
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = _warranty(
        client, owner, "tool", tool.id, dealer_notified=False, no_agent=True
    )
    assert created.status_code == 201, created.text
    body = created.json()
    claim = body["claim"]
    assert claim["warranty_agent"] is None
    # No agent -> no report step: nothing sent, nothing noticed.
    assert body["reported"] is False
    assert body["report_via"] == []
    assert _outbox(db) == []
    assert _notifications(db, agent1) == []
    _assert_no_access(_get_claim(client, agent1, claim["id"]))

    # The owner runs the whole ladder himself. Closing is the
    # closed LAYER since the claims overhaul (2026-11-06): the
    # status stays where it was (completed) and closed_at stamps.
    for to_status in ("reported", "in_repair", "completed"):
        moved = client.post(
            f"/api/claims/{claim['id']}/transition",
            json={"to_status": to_status},
            headers=auth_headers(owner),
        )
        assert moved.status_code == 200, (to_status, moved.text)
        assert moved.json()["status"] == to_status
    closed = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "closed"},
        headers=auth_headers(owner),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "completed"
    assert closed.json()["closed_at"] is not None


# -- filing choices ------------------------------------------------------------


def test_filing_options_and_explicit_agent_choice(
    client, db, owner, agent1, agent2
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, agent2, verified=True)
    _prefer_platform(db, owner, company, agent1, minutes_ago=2)
    _prefer_platform(db, owner, company, agent2, minutes_ago=1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    options = client.get(
        "/api/claims/warranty/agent-options",
        params={"target_kind": "tool", "target_id": str(tool.id)},
        headers=auth_headers(owner),
    )
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["dealer_company_id"] == str(company.id)
    assert body["dealer_name"] == company.name
    assert [a["name"] for a in body["agents"]] == ["Agent One", "Agent Two"]
    assert body["default_agent_user_id"] == str(agent1.id)

    # The owner picks the SECOND agent at filing: the first
    # agent (the default) never sees this claim.
    created = _warranty(
        client,
        owner,
        "tool",
        tool.id,
        dealer_notified=True,
        agent_user_id=str(agent2.id),
    )
    claim = created.json()["claim"]
    assert claim["warranty_agent"]["agent_user_id"] == str(agent2.id)
    assert _get_claim(client, agent2, claim["id"]).status_code == 200
    _assert_no_access(_get_claim(client, agent1, claim["id"]))


def test_filing_with_agent_not_on_record_is_refused(
    client, db, owner, agent1, agent2
):
    company = _company(db)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    refused = _warranty(
        client,
        owner,
        "tool",
        tool.id,
        dealer_notified=True,
        agent_user_id=str(agent2.id),
    )
    assert refused.status_code == 422, refused.text
    assert "on record" in refused.json()["detail"]


def test_company_email_is_never_a_report_target(client, db, owner):
    # A company WITH an email but no agent on record: the old
    # build emailed the company and reported the claim. Now
    # there is nobody to report TO — the claim waits for the
    # owner, and the company hears nothing.
    company = _company(db, email="service@matco.example")
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=False)
    body = created.json()
    assert body["claim"]["warranty_agent"] is None
    assert body["claim"]["status"] == "not_reported"
    assert body["reported"] is False
    assert _outbox(db, "service@matco.example") == []


def test_piece_claim_report_email_to_private_agent_carries_both_numbers(
    client, db, owner
):
    company = _company(db, email="parts@matco.example")
    agent = _private_agent(db, owner, company, email="pat@agent.example")
    _prefer_private(db, owner, company, agent)
    tool_set = _tool(
        db,
        owner,
        name="Master Socket Set",
        is_set=True,
        model="KRL1033",
        dealer_company_id=company.id,
    )
    piece = inventory_models.SetPiece(
        owner_id=owner.id,
        set_id=tool_set.id,
        name="10mm socket",
        kind="core",
        part_number="84-123",
        price="12.50",
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)

    created = _warranty(client, owner, "piece", piece.id, dealer_notified=False)
    assert created.status_code == 201, created.text
    assert created.json()["report_via"] == ["email"]
    sent = _outbox(db, "pat@agent.example")
    assert len(sent) == 1
    assert "84-123" in sent[0].body
    assert "KRL1033" in sent[0].body
    assert "Master Socket Set" in sent[0].body
    assert _outbox(db, "parts@matco.example") == []


# -- re-pointing + the seat-holds model (stage 1, 2026-11-04) -------------------
#
# The two tests after test_owner_repoints_single_claim_and_choice_sticks
# replace the retired follow-sweep tests
# (test_claims_follow_when_agent_on_record_changes and
# test_first_agent_on_record_pulls_existing_claims): where those
# asserted claims FOLLOW an agent-on-record change, these assert
# the seats HOLD and only the owner's per-claim choices move them.


def test_owner_repoints_single_claim_and_choice_sticks(
    client, db, owner, agent1, agent2
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, agent2, verified=True)
    _prefer_platform(db, owner, company, agent1, minutes_ago=2)
    # agent2 is on record too (second) — the legal re-point
    # target; the claim still defaults to agent1.
    _prefer_platform(db, owner, company, agent2, minutes_ago=1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    assert _get_claim(client, agent1, claim["id"]).status_code == 200

    moved = client.patch(
        f"/api/claims/{claim['id']}/agent",
        json={"agent_user_id": str(agent2.id)},
        headers=auth_headers(owner),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["warranty_agent"]["agent_user_id"] == str(agent2.id)
    _assert_no_access(_get_claim(client, agent1, claim["id"]))
    assert _get_claim(client, agent2, claim["id"]).status_code == 200

    # Adding ANOTHER preferred agent does not change the agent
    # on record — the hand-pointed claim keeps the owner's choice.
    agent3 = _make_user(
        db, "TV-D-001105", "scope-agent3@example.com", [DEALER], "Agent Three"
    )
    added = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": str(company.id),
            "agent_account_number": agent3.account_number,
        },
        headers=auth_headers(owner),
    )
    assert added.status_code in (200, 201), added.text
    row = _claim_row(db, claim["id"])
    assert row.agent_user_id == agent2.id

    # Re-pointing to NO agent darkens every other seat.
    cleared = client.patch(
        f"/api/claims/{claim['id']}/agent",
        json={},
        headers=auth_headers(owner),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["warranty_agent"] is None
    _assert_no_access(_get_claim(client, agent2, claim["id"]))


def test_claims_keep_their_seats_when_agents_are_starred(
    client, db, owner, agent1, agent2
):
    """REWRITTEN for multi-preferred (2026-11-05) — replaces the
    stage-1 switch version. There is no switch anymore: starring
    another agent is a per-agent flag change that asks nothing
    and moves nothing, and disconnecting an agent promotes
    nobody either. Seats hold throughout."""
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, agent2, verified=True)
    _prefer_platform(db, owner, company, agent1, minutes_ago=2)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    assert _claim_row(db, claim["id"]).agent_user_id == agent1.id

    # A second tool's claim, hand-pointed at agent2 meanwhile.
    pref2 = _prefer_platform(db, owner, company, agent2, minutes_ago=1)
    tool2 = _tool(db, owner, name="Torque wrench", dealer_company_id=company.id)
    created2 = _warranty(
        client, owner, "tool", tool2.id,
        dealer_notified=True, agent_user_id=str(agent2.id),
    )
    claim2 = created2.json()["claim"]
    assert _claim_row(db, claim2["id"]).agent_user_id == agent2.id

    # Starring agent2 (agent1 was never flagged in this fixture
    # — his row resolves by the earliest-row fallback) simply
    # lands: no refusal, no prompt, and both seats are exactly
    # where the owner left them.
    starred = client.post(
        "/api/dealers/preferred/flag",
        json={
            "company_id": str(company.id),
            "agent_user_id": str(agent2.id),
            "is_preferred": True,
        },
        headers=auth_headers(owner),
    )
    assert starred.status_code == 201, starred.text
    assert starred.json()["is_preferred"] is True
    assert _claim_row(db, claim["id"]).agent_user_id == agent1.id
    assert _claim_row(db, claim2["id"]).agent_user_id == agent2.id
    assert _get_claim(client, agent1, claim["id"]).status_code == 200
    assert _get_claim(client, agent2, claim2["id"]).status_code == 200

    # Disconnecting agent2 promotes NOBODY and STILL moves no
    # claim: claim2 keeps agent2's seat and his verified seat
    # keeps reaching it.
    removed = client.delete(
        f"/api/dealers/preferred/{pref2.id}", headers=auth_headers(owner)
    )
    assert removed.status_code == 204, removed.text
    assert _claim_row(db, claim["id"]).agent_user_id == agent1.id
    assert _claim_row(db, claim2["id"]).agent_user_id == agent2.id
    assert _get_claim(client, agent2, claim2["id"]).status_code == 200

    # Emptying the roster entirely changes nothing about seats
    # either: both claims keep the agents the owner seated them
    # with (the old test asserted they followed to no agent).
    remaining = client.get(
        "/api/dealers/preferred",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    ).json()
    for row in remaining:
        gone = client.delete(
            f"/api/dealers/preferred/{row['id']}", headers=auth_headers(owner)
        )
        assert gone.status_code == 204, gone.text
    assert _claim_row(db, claim["id"]).agent_user_id == agent1.id
    assert _claim_row(db, claim2["id"]).agent_user_id == agent2.id


def test_first_agent_becomes_preferred_without_pulling_claims(
    client, db, owner, agent1
):
    """REWRITTEN for stage 1 (2026-11-04) — replaces
    test_first_agent_on_record_pulls_existing_claims. The first
    agent connected for a dealer becomes THE preferred — but an
    existing claim filed with no agent keeps its no-agent seat;
    only claims filed AFTER take the new default."""
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    tool = _tool(db, owner, dealer_company_id=company.id)
    # Filed while the owner had NO agent on record: owner-only.
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    assert claim["warranty_agent"] is None
    # Connecting the first agent flags him preferred...
    added = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": str(company.id),
            "agent_account_number": agent1.account_number,
        },
        headers=auth_headers(owner),
    )
    assert added.status_code in (200, 201), added.text
    assert added.json()["is_preferred"] is True
    # ...but the existing claim does NOT follow him.
    assert _claim_row(db, claim["id"]).agent_user_id is None
    _assert_no_access(_get_claim(client, agent1, claim["id"]))
    # A claim filed now defaults to the preferred.
    tool2 = _tool(db, owner, name="Torque wrench", dealer_company_id=company.id)
    created2 = _warranty(client, owner, "tool", tool2.id, dealer_notified=True)
    assert _claim_row(db, created2.json()["claim"]["id"]).agent_user_id == agent1.id
    assert _get_claim(client, agent1, created2.json()["claim"]["id"]).status_code == 200


def test_private_to_platform_switch_moves_claims_to_the_account(
    client, db, owner, agent1
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    agent = _private_agent(db, owner, company, name="Pat Private")
    _prefer_private(db, owner, company, agent)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    assert claim["warranty_agent"]["kind"] == "private"
    _assert_no_access(_get_claim(client, agent1, claim["id"]))

    linked = client.post(
        f"/api/dealers/agents/private/{agent.id}/link",
        json={"agent_account_number": agent1.account_number},
        headers=auth_headers(owner),
    )
    assert linked.status_code == 200, linked.text
    # The claim followed the switch: it now points at the
    # platform user, whose verified seat is live.
    row = _claim_row(db, claim["id"])
    assert row.agent_user_id == agent1.id
    assert row.private_agent_id is None
    assert _get_claim(client, agent1, claim["id"]).status_code == 200


# -- fields: case number vs policy ----------------------------------------------


def test_manufacturer_case_number_and_policy_field_scoping(
    client, db, owner, agent1
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]

    # The owner records the manufacturer's case number; the
    # agent sees it on the shared record.
    updated = client.patch(
        f"/api/claims/{claim['id']}",
        json={"manufacturer_case_number": "MAT-2026-8841"},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["manufacturer_case_number"] == "MAT-2026-8841"
    agent_view = _get_claim(client, agent1, claim["id"]).json()
    assert agent_view["manufacturer_case_number"] == "MAT-2026-8841"

    # Insurance fields never land on a warranty claim.
    sneaky = client.patch(
        f"/api/claims/{claim['id']}",
        json={"policy_number": "POL-123", "insurer_name": "Acme Mutual"},
        headers=auth_headers(owner),
    )
    assert sneaky.status_code == 200, sneaky.text
    assert sneaky.json()["policy_number"] == ""
    assert sneaky.json()["insurer_name"] == ""

    # And the case number never lands on an insurance claim,
    # whose policy fields work exactly as before (control).
    # Separation (2026-11-04): insurance claims are filed and
    # edited through the Disaster Claims section now.
    insurance = client.post(
        "/api/disaster-claims", json={}, headers=auth_headers(owner)
    )
    ins_claim = insurance.json()
    patched = client.patch(
        f"/api/disaster-claims/{ins_claim['id']}",
        json={
            "policy_number": "POL-123",
            "manufacturer_case_number": "SHOULD-NOT-LAND",
        },
        headers=auth_headers(owner),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["policy_number"] == "POL-123"
    assert patched.json()["manufacturer_case_number"] == ""


def test_agent_assignment_refused_on_insurance_claim(client, db, owner):
    # Separation (2026-11-04): the insurance claim is FILED
    # through the Disaster Claims section now, but the agent
    # assignment door's answer is unchanged — it looks the claim
    # up and refuses insurance claims by kind with its tailored
    # 422 (agent assignment is a warranty-only concept, and the
    # refusal says so rather than pretending the claim is gone).
    insurance = client.post(
        "/api/disaster-claims", json={}, headers=auth_headers(owner)
    )
    claim = insurance.json()
    refused = client.patch(
        f"/api/claims/{claim['id']}/agent",
        json={},
        headers=auth_headers(owner),
    )
    assert refused.status_code == 422, refused.text


def test_insurance_claim_invisible_to_dealer_seats(
    client, db, owner, agent1, principal
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, principal, verified=True)
    _prefer_platform(db, owner, company, agent1)
    insurance = client.post(
        "/api/disaster-claims",
        json={"insurer_name": "Acme Mutual", "policy_number": "POL-9"},
        headers=auth_headers(owner),
    )
    claim = insurance.json()
    for other in (agent1, principal):
        _assert_no_access(_get_claim(client, other, claim["id"]))
        # Separation (2026-11-04): the disaster section's own door
        # is shut to dealer seats too — dealer groups hold no
        # disaster_claims entitlement.
        _assert_no_access(
            client.get(
                f"/api/disaster-claims/{claim['id']}",
                headers=auth_headers(other),
            )
        )
        assert (
            client.get(
                "/api/claims/incoming", headers=auth_headers(other)
            ).json()
            == []
        )


def test_agent_search_never_surfaces_the_claim(client, db, owner, agent1):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]

    # Global search is owner-scoped: even the ASSIGNED agent
    # searching the claim number finds no claim (their door is
    # the incoming worklist, not search) — and a non-assigned
    # seat certainly doesn't.
    for user in (agent1,):
        results = client.get(
            "/api/core/search",
            params={"q": claim["claim_number"]},
            headers=auth_headers(user),
        )
        assert results.status_code == 200, results.text
        groups = results.json()["groups"]
        claim_hits = [
            hit
            for group in groups
            for hit in group.get("results", [])
            if hit.get("id") == claim["id"]
        ]
        assert claim_hits == []
    # The owner's own search finds it by its claim number.
    own = client.get(
        "/api/core/search",
        params={"q": claim["claim_number"]},
        headers=auth_headers(owner),
    ).json()["groups"]
    assert any(
        hit.get("id") == claim["id"]
        for group in own
        for hit in group.get("results", [])
    )


def test_dealer_page_records_stay_the_viewers_own(
    client, db, owner, agent1
):
    """The dealer page's claims block is the VIEWER's own records
    for that company — the agent looking at the company page sees
    none of the customer's claims there either."""
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    _warranty(client, owner, "tool", tool.id, dealer_notified=True)

    records = client.get(
        f"/api/dealers/companies/{company.id}/my-records",
        headers=auth_headers(agent1),
    )
    assert records.status_code == 200, records.text
    block = records.json().get("claims")
    if block is not None:
        assert block["current"] == [] and block["history"] == []
    # The owner's own page corner still shows the claim.
    own_records = client.get(
        f"/api/dealers/companies/{company.id}/my-records",
        headers=auth_headers(owner),
    ).json()
    assert len(own_records["claims"]["current"]) == 1


# -- migration -------------------------------------------------------------------


def test_migration_0066_shape_chain_and_backfill_sql(db, owner):
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    path = versions / "0066_claims_agent_scope.py"
    spec = importlib.util.spec_from_file_location("mig0066", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0066_claims_agent_scope"
    assert migration.down_revision == "0065_downloads_subscribers"
    source = path.read_text()
    for needle in (
        '"agent_user_id"',
        '"private_agent_id"',
        '"manufacturer_case_number"',
        "preferred_agents",
        "warranty_repair",
    ):
        assert needle in source, needle
    # Single-head chain, with 0066 in it on top of 0065. (0066
    # was the head when it landed; later migrations chain onto
    # it — what must hold forever is ONE head and 0066's place
    # in the ancestry, not 0066 staying the head.)
    revisions: dict[str, str | None] = {}
    pattern = re.compile(
        r"^(?:down_)?revision(?::[^=]+)? = (\"[^\"]+\"|'[^']+'|None)\s*$", re.M
    )
    for file in versions.glob("*.py"):
        text = file.read_text()
        found = {}
        for match in pattern.finditer(text):
            key = "down" if match.group(0).startswith("down_") else "rev"
            raw = match.group(1)
            found[key] = None if raw == "None" else raw.strip("\"'")
        if "rev" in found:
            revisions[found["rev"]] = found.get("down")
    children = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in children]
    assert len(heads) == 1
    ancestry = []
    cursor: str | None = heads[0]
    while cursor is not None:
        ancestry.append(cursor)
        cursor = revisions.get(cursor)
    assert "0066_claims_agent_scope" in ancestry
    assert (
        revisions["0066_claims_agent_scope"] == "0065_downloads_subscribers"
    )

    # The backfill SQL itself, run against rows in the pre-0066
    # shape (pointers NULL): a warranty claim takes the owner's
    # earliest preferred agent for its dealer; an insurance claim
    # and a dealer-less warranty claim stay untouched.
    company = _company(db)
    agent = _private_agent(db, owner, company)
    _prefer_private(db, owner, company, agent)
    tool = _tool(db, owner, dealer_company_id=company.id)
    from app.modules.claims import service as claims_service

    claim = claims_models.Claim(
        owner_id=owner.id,
        claim_number="CL-2026-901",
        claim_year=2026,
        number_seq=901,
        kind=claims_models.KIND_WARRANTY,
        dealer_company_id=company.id,
        dealer_name=company.name,
        status="reported",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    assert claim.agent_user_id is None and claim.private_agent_id is None

    # The migration's own backfill statement, lifted verbatim
    # from its source (the one triple-quoted block that updates
    # claims) and run against the test engine.
    blocks = re.findall(r'"""(.*?)"""', source, re.S)
    backfill = next(b for b in blocks if "UPDATE claims" in b)
    from sqlalchemy import text

    db.execute(text(backfill))
    db.commit()
    db.refresh(claim)
    assert claim.private_agent_id == agent.id
    assert claim.agent_user_id is None
    # The service agrees with the backfilled pointer.
    view = claims_service.claim_agent_view(db, claim)
    assert view["kind"] == "private" and view["name"] == agent.name
