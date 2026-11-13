"""Agent codes + takeover (owner model, 2026-11-03).

The owner's shape, end to end:

  - a user-entered private agent record carries a unique agent
    code — a property of the record, shown only to its owner;
  - the record is private: no other seat sees a trace of it;
  - a signed-in agent enters the code -> a takeover REQUEST to
    the owner (bell + the record's own area); wrong codes answer
    generically and are rate-limited;
  - DECLINE changes nothing and notifies the requester; ACCEPT
    links the record to the agent's account IN PLACE — claims
    and the truck account keep referencing the record, and the
    agent inherits both seats (the takeover link is the verified
    link for that one customer relationship; H-1's rule — no
    seat without a verified link to the claim's agent record —
    is preserved, and a second agent sees nothing);
  - the code is used up by a successful claim;
  - when the linked agent DELETES their account, the record
    reverts to the owner whole (claims, truck account + ledger,
    preference), the code ROTATES, the old code is refused, and
    a new agent can claim with the fresh code.
"""

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from app.modules.truck_accounts import service as truck_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"
CODE_RE = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}$")


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
        db, "TV-M-002101", "takeover-owner@example.com", [MECHANIC], "Ollie Owner"
    )


@pytest.fixture()
def agent_a(db):
    return _make_user(
        db, "TV-D-002102", "takeover-agent-a@example.com", [DEALER], "Agent A"
    )


@pytest.fixture()
def agent_b(db):
    return _make_user(
        db, "TV-D-002103", "takeover-agent-b@example.com", [DEALER], "Agent B"
    )


@pytest.fixture()
def stranger(db):
    return _make_user(
        db, "TV-M-002104", "takeover-stranger@example.com", [MECHANIC], "Sue Stranger"
    )


@pytest.fixture()
def dual(db):
    """A multi-group seat: mechanic AND dealer (access is a
    union — the dealer half carries the agent side)."""
    return _make_user(
        db,
        "TV-MD-002105",
        "takeover-dual@example.com",
        [MECHANIC, DEALER],
        "Drew Dual",
    )


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _create_record(client, owner, company, name="Matt Driver"):
    resp = client.post(
        "/api/dealers/agents/private",
        json={
            "company_id": str(company.id),
            "name": name,
            "phone": "555-0100",
            "email": "matt@example.com",
            "notes": "",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _prefer_private(client, owner, company, record_id):
    resp = client.post(
        "/api/dealers/preferred",
        json={"company_id": str(company.id), "private_agent_id": record_id},
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _enter(client, user, code):
    return client.post(
        "/api/dealers/agents/takeover/enter-code",
        json={"code": code},
        headers=auth_headers(user),
    )


def _notifications(db, user, kind=None):
    stmt = select(core_models.Notification).where(
        core_models.Notification.user_id == user.id
    )
    rows = list(db.scalars(stmt))
    if kind:
        rows = [r for r in rows if r.kind == kind]
    return rows


def _record(db, record_id):
    return db.get(dealer_models.PrivateAgent, uuid.UUID(record_id))


def _file_claim(client, owner, company, db):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name="Impact wrench",
        model="M18-2767",
        dealer_company_id=company.id,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": "It stopped working.",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json(), tool


# -- the code -----------------------------------------------------------------


def test_record_created_with_unique_displayable_code(client, db, owner, company):
    first = _create_record(client, owner, company)
    second = _create_record(client, owner, company, name="Second Agent")
    assert CODE_RE.match(first["agent_code_display"]), first["agent_code_display"]
    assert CODE_RE.match(second["agent_code_display"])
    assert first["agent_code"] != second["agent_code"]
    assert first["agent_code_display"].replace("-", "") == first["agent_code"]
    assert first["link_source"] is None
    assert first["claimed_by_name"] is None
    # The owner's list read carries the same code.
    mine = client.get(
        "/api/dealers/agents/private", headers=auth_headers(owner)
    ).json()
    assert {row["id"] for row in mine} == {first["id"], second["id"]}


def test_record_is_private_to_its_owner(client, db, owner, agent_a, stranger, company):
    record = _create_record(client, owner, company)
    _prefer_private(client, owner, company, record["id"])
    # Another user's private-agent list: nothing.
    theirs = client.get(
        "/api/dealers/agents/private", headers=auth_headers(stranger)
    ).json()
    assert theirs == []
    # The stranger's company page: no preferred agents, and the
    # record's name/code appear nowhere in the payload.
    detail = client.get(
        f"/api/dealers/companies/{company.id}/detail", headers=auth_headers(stranger)
    )
    assert detail.status_code == 200, detail.text
    body = detail.text
    assert record["agent_code"] not in body
    assert "Matt Driver" not in body
    assert detail.json()["my_preferred_agents"] == []
    # The agent-facing public list for the company doesn't carry
    # it either.
    assert detail.json()["agents"] == []
    # And the record's takeover-requests read is owner-only.
    resp = client.get(
        f"/api/dealers/agents/private/{record['id']}/takeover-requests",
        headers=auth_headers(agent_a),
    )
    assert resp.status_code == 404


# -- code entry ----------------------------------------------------------------


def test_enter_unknown_code_generic_and_rate_limited(client, db, owner, agent_a, company):
    _create_record(client, owner, company)
    for _ in range(5):
        resp = _enter(client, agent_a, "ZZZZ9999")
        assert resp.status_code == 422, resp.text
        assert "doesn't match an agent record" in resp.json()["detail"]
    # The failure budget (5 / window, the login limiter's shape)
    # is spent: even a well-formed entry now waits.
    resp = _enter(client, agent_a, "ZZZZ9999")
    assert resp.status_code == 429, resp.text


def test_enter_own_code_is_a_resolution_not_a_request(client, db, dual, company):
    # The own-record resolution lives on the agent side of the
    # flow, so its seat is a dual-group owner (mechanic + dealer):
    # entering the code on his OWN record resolves as own_record,
    # never as a request to himself.
    record = _create_record(client, dual, company)
    resp = _enter(client, dual, record["agent_code"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "own_record"
    assert db.scalars(select(dealer_models.AgentTakeoverRequest)).all() == []


# -- the audience gate (owner, 2026-11-04): the agent side of the
# code flow is dealer-group only, on the server as on the panel ---


def test_enter_code_refused_for_mechanic_only_callers(client, db, owner, stranger, company):
    record = _create_record(client, owner, company)
    # A mechanic-only stranger with the VALID code gets exactly
    # the generic refusal a wrong code gets — the endpoint never
    # explains itself — and nothing is created or notified.
    resp = _enter(client, stranger, record["agent_code"])
    assert resp.status_code == 422, resp.text
    assert "doesn't match an agent record" in resp.json()["detail"]
    # The record's own (mechanic-only) owner is outside the
    # audience too: his own code refuses the same way.
    resp = _enter(client, owner, record["agent_code"])
    assert resp.status_code == 422, resp.text
    assert "doesn't match an agent record" in resp.json()["detail"]
    assert db.scalars(select(dealer_models.AgentTakeoverRequest)).all() == []
    assert _notifications(db, owner) == []


def test_enter_code_works_for_multi_group_agent(client, db, owner, dual, company):
    record = _create_record(client, owner, company)
    resp = _enter(client, dual, record["agent_code"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    rows = db.scalars(select(dealer_models.AgentTakeoverRequest)).all()
    assert len(rows) == 1
    assert rows[0].requester_user_id == dual.id
    assert _notifications(db, owner) != []


def test_takeover_mine_is_dealer_only(client, db, owner, agent_a, dual):
    resp = client.get(
        "/api/dealers/agents/takeover/mine", headers=auth_headers(owner)
    )
    assert resp.status_code == 422, resp.text
    assert "dealer accounts" in resp.json()["detail"]
    for seat in (agent_a, dual):
        resp = client.get(
            "/api/dealers/agents/takeover/mine", headers=auth_headers(seat)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["requests"] == []
        assert resp.json()["claimed"] == []


# -- the lifecycle ---------------------------------------------------------------


def test_decline_then_accept_full_lifecycle(
    client, db, owner, agent_a, agent_b, company
):
    record = _create_record(client, owner, company)
    _prefer_private(client, owner, company, record["id"])
    claim_body, _tool = _file_claim(client, owner, company, db)
    claim_id = claim_body["claim"]["id"]

    # The claim defaults to the private record as its agent.
    mine = client.get(f"/api/claims/{claim_id}", headers=auth_headers(owner))
    assert mine.status_code == 200, mine.text
    assert mine.json()["warranty_agent"]["kind"] == "private"
    assert mine.json()["warranty_agent"]["has_access"] is False

    # A truck self-tab lands under the record.
    account = truck_service.open_self_tab(db, owner, company)
    db.commit()
    assert account.private_agent_id == _record(db, record["id"]).id
    assert account.dealer_user_id is None

    # Before any claim of the record, the agent sees nothing.
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(agent_a))
    assert resp.status_code in (403, 404)
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(agent_a)
    ).json()
    assert rows == []

    # Enter the code — typed lowercase with the dash, proving
    # normalization. A request lands; the owner is notified.
    resp = _enter(client, agent_a, record["agent_code_display"].lower())
    assert resp.status_code == 200, resp.text
    outcome = resp.json()
    assert outcome["status"] == "pending"
    assert outcome["agent_name"] == "Matt Driver"
    assert _notifications(db, owner, "agent_takeover_requested")

    # Entering again is idempotent — same request, no duplicate.
    again = _enter(client, agent_a, record["agent_code"])
    assert again.json()["request_id"] == outcome["request_id"]
    pending = client.get(
        f"/api/dealers/agents/private/{record['id']}/takeover-requests",
        headers=auth_headers(owner),
    ).json()
    assert len(pending) == 1
    assert pending[0]["requester_account_number"] == agent_a.account_number

    # DECLINE: nothing changes; the requester hears the no.
    resp = client.post(
        f"/api/dealers/agents/takeover/{outcome['request_id']}/decline",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text
    assert _notifications(db, agent_a, "agent_takeover_declined")
    after = _record(db, record["id"])
    assert after.linked_user_id is None and after.link_source is None
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(agent_a))
    assert resp.status_code in (403, 404)

    # RE-REQUEST, then ACCEPT: the record links in place.
    resp = _enter(client, agent_a, record["agent_code"])
    request_id = resp.json()["request_id"]
    resp = client.post(
        f"/api/dealers/agents/takeover/{request_id}/accept",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert view["link_source"] == "takeover"
    assert view["claimed_by_account_number"] == agent_a.account_number
    assert _notifications(db, agent_a, "agent_takeover_accepted")
    after = _record(db, record["id"])
    assert after.linked_user_id == agent_a.id
    # The preference still points at the RECORD (nothing re-pointed).
    prefs = list(
        db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == owner.id
            )
        )
    )
    assert prefs and prefs[0].private_agent_id == after.id

    # The code is used up.
    resp = _enter(client, agent_b, record["agent_code"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_claimed"

    # The claim seat is live for agent A — and only agent A.
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(agent_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["warranty_agent"]["has_access"] is True
    incoming = client.get("/api/claims/incoming", headers=auth_headers(agent_a))
    assert incoming.status_code == 200
    assert claim_id in {row["id"] for row in incoming.json()}
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(agent_b))
    assert resp.status_code in (403, 404)

    # The truck seat resolves to agent A: listed as dealer.
    # Stage 2 semantics (2026-11-05): the tab stays CUSTOMER-
    # KEPT after the claim — the agent sees what the customer
    # keeps; his pen on it is a payment he received (or a
    # payment REQUEST), never a charge.
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(agent_a)
    ).json()
    assert len(rows) == 1
    assert rows[0]["my_role"] == "dealer"
    assert rows[0]["customer_maintained"] is True
    resp = client.post(
        f"/api/truck-accounts/accounts/{account.id}/entries",
        json={
            "kind": "charge",
            "amount": "25.00",
            "note": "Sockets",
            "item_link_id": None,
            "entry_date": None,
        },
        headers=auth_headers(agent_a),
    )
    assert resp.status_code == 422, resp.text
    resp = client.post(
        f"/api/truck-accounts/accounts/{account.id}/entries",
        json={
            "kind": "payment",
            "amount": "25.00",
            "note": "Cash at the truck",
            "item_link_id": None,
            "entry_date": None,
        },
        headers=auth_headers(agent_a),
    )
    assert resp.status_code in (200, 201), resp.text
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(agent_b)
    ).json()
    assert rows == []


def test_answer_by_non_owner_is_404(client, db, owner, agent_a, stranger, company):
    record = _create_record(client, owner, company)
    outcome = _enter(client, agent_a, record["agent_code"]).json()
    resp = client.post(
        f"/api/dealers/agents/takeover/{outcome['request_id']}/accept",
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404
    assert _record(db, record["id"]).linked_user_id is None


# -- the deletion safeguard -------------------------------------------------------


def test_agent_account_deletion_reverts_and_rotates(
    client, db, owner, agent_a, agent_b, company
):
    record = _create_record(client, owner, company)
    _prefer_private(client, owner, company, record["id"])
    claim_body, _tool = _file_claim(client, owner, company, db)
    claim_id = claim_body["claim"]["id"]
    account = truck_service.open_self_tab(db, owner, company)
    db.commit()
    # The owner posts a payment on the tab before any takeover.
    resp = client.post(
        f"/api/truck-accounts/accounts/{account.id}/entries",
        json={
            "kind": "payment",
            "amount": "10.00",
            "note": "",
            "item_link_id": None,
            "entry_date": None,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text

    outcome = _enter(client, agent_a, record["agent_code"]).json()
    resp = client.post(
        f"/api/dealers/agents/takeover/{outcome['request_id']}/accept",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    old_code = record["agent_code"]

    # The agent deletes their account.
    resp = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(agent_a),
    )
    assert resp.status_code == 204, resp.text

    # The record is the owner's again, whole: unlinked, code
    # ROTATED, preference intact, claim + truck account standing.
    after = _record(db, record["id"])
    assert after is not None
    assert after.linked_user_id is None
    assert after.link_source is None
    assert after.agent_code != old_code
    assert CODE_RE.match(
        f"{after.agent_code[:4]}-{after.agent_code[4:]}"
    )
    prefs = list(
        db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == owner.id
            )
        )
    )
    assert prefs and prefs[0].private_agent_id == after.id
    mine = client.get(f"/api/claims/{claim_id}", headers=auth_headers(owner))
    assert mine.status_code == 200
    assert mine.json()["warranty_agent"]["kind"] == "private"
    rows = client.get(
        "/api/truck-accounts/accounts", headers=auth_headers(owner)
    ).json()
    assert len(rows) == 1
    assert rows[0]["balance"] in ("-10.00", -10.0, "-10")
    # The departed agent's requests are gone.
    leftovers = list(
        db.scalars(
            select(dealer_models.AgentTakeoverRequest).where(
                dealer_models.AgentTakeoverRequest.requester_user_id == agent_a.id
            )
        )
    )
    assert leftovers == []

    # The OLD code no longer resolves; the NEW code starts the
    # cycle again with a second agent.
    resp = _enter(client, agent_b, old_code)
    assert resp.status_code == 422
    resp = _enter(client, agent_b, after.agent_code)
    assert resp.status_code == 200, resp.text
    request_id = resp.json()["request_id"]
    resp = client.post(
        f"/api/dealers/agents/takeover/{request_id}/accept",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    resp = client.get(f"/api/claims/{claim_id}", headers=auth_headers(agent_b))
    assert resp.status_code == 200, resp.text


# -- migration chain ----------------------------------------------------------------


def test_migration_0082_is_the_single_chain_head():
    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    revisions = {}
    down_revisions = set()
    for path in sorted(versions.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        revisions[module.revision] = module.down_revision
        if isinstance(module.down_revision, str):
            down_revisions.add(module.down_revision)
    heads = set(revisions) - down_revisions
    # 0104 (sweep E4 / busy-work #6 lane, 2026-11-12:
    # the content-alert opt-in tables —
    # new_content_alert_prefs + content_alert_state in
    # core, print_file_follows in prints) closed over
    # 0103 (sweep E3 / busy-work #5 lane, 2026-11-12:
    # tools + batteries gain the health_photo_ignored
    # flag — the health check's per-item, photo-only
    # opt-out, honored by the scan and its consumers)
    # closed over
    # 0102 (member email single-language lane, 2026-11-10:
    # feature_announcements gains the per-language email
    # parts — title_es / body_en / body_es) closed over
    # 0101 (tier conversion lane, 2026-11-10: the
    # conversion_requests table) closed over
    # 0100 (home dashboard shell lane, 2026-11-10: the
    # stats-only Home reset — every user's home layout becomes
    # the stats widget alone, god's row and the panel
    # pseudo-entry preserved) closed over
    # 0099 (downloads-in-shell lane, 2026-11-10: the
    # visitor_counter prints row) closed over
    # 0098 (dashboard-flare lane, 2026-11-09: the
    # download_events table — the dated record behind the
    # Downloads widget's top-this-week ranking) closed over
    # 0097 (boards-for-all lane, 2026-11-09: the feedback
    # boards join the downloads level's standing definition —
    # one tier cell) closed over
    # 0096 (open signup lane, 2026-11-09: the downloads tier
    # cells + release-scoped announcement columns) closed over
    # 0095 (prints showcase media lane, 2026-11-08: the
    # print_media table — a listing's photos + its one
    # video, the existing preview backfilled as photo #1)
    # closed over
    # 0094 (downloads small fixes lane, 2026-11-08: the
    # visitor_counter Downloads row) closed over
    # 0093 (prints lane, 2026-11-08: the print file
    # tables), which closed over
    # 0092 (downloads-documents lane, 2026-11-08: the
    # download_files documents catalog) closed over
    # 0091 (release machinery lane, 2026-11-08: the
    # feature_announcements history table) closed over
    # 0090 (per-mode accent lane, 2026-11-08: the users
    # appearance_accent_light column) closed over
    # 0089 (agent invite reminder lane, 2026-11-07: the
    # private_agents invite_reminded_at stamp) closed over
    # 0088 (cancellation counts lane, 2026-11-07: subscription
    # status-change history), which closed over
    # 0087 (admin polish lane, 2026-11-07: the AI usage
    # metering table), which closed over
    # 0086 (onboarding lane, 2026-11-07), which closed over
    # 0085 (admin lane, 2026-11-07), which closed over
    # 0084 (boards urgency, 2026-11-07), which closed over
    # 0083 (flyer official links, 2026-11-06), which closed over
    # 0082 (reports library, 2026-11-06), which closed over
    # 0081 (flyer module, 2026-11-06), which closed over
    # 0080 (truck highest balance, 2026-11-06), which closed
    # over 0079 (claims overhaul, 2026-11-06), which closed over
    # 0078 (personal dealer edits, 2026-11-05), which closed
    # over 0077 (truck accounts stage 2, 2026-11-05), which
    # closed over 0076 (claims separation, 2026-11-05), which
    # closed over 0075 (dealer agent records stage 1,
    # 2026-11-04), which closed over the claims lane's 0074.
    assert heads == {"0104_content_alert_prefs"}, heads
    assert (
        revisions["0104_content_alert_prefs"]
        == "0103_health_photo_ignored"
    )
    assert (
        revisions["0103_health_photo_ignored"]
        == "0102_announcement_locale_parts"
    )
    assert (
        revisions["0102_announcement_locale_parts"]
        == "0101_conversion_requests"
    )
    assert (
        revisions["0101_conversion_requests"] == "0100_home_stats_reset"
    )
    assert (
        revisions["0100_home_stats_reset"] == "0099_prints_visitor_counter"
    )
    assert (
        revisions["0099_prints_visitor_counter"] == "0098_download_events"
    )
    assert (
        revisions["0098_download_events"] == "0097_feedback_for_downloads"
    )
    assert (
        revisions["0097_feedback_for_downloads"] == "0096_downloads_tier"
    )
    assert revisions["0096_downloads_tier"] == "0095_print_media"
    assert (
        revisions["0095_print_media"] == "0094_downloads_visitor_counter"
    )
    assert (
        revisions["0094_downloads_visitor_counter"] == "0093_print_files"
    )
    assert (
        revisions["0093_print_files"] == "0092_download_files"
    )
    assert (
        revisions["0092_download_files"]
        == "0091_feature_announcements"
    )
    assert (
        revisions["0091_feature_announcements"]
        == "0090_appearance_accent_light"
    )
    assert (
        revisions["0090_appearance_accent_light"]
        == "0089_agent_invite_reminder"
    )
    assert (
        revisions["0089_agent_invite_reminder"]
        == "0088_subscription_status_changes"
    )
    assert (
        revisions["0088_subscription_status_changes"] == "0087_ai_usage"
    )
    assert revisions["0087_ai_usage"] == "0086_onboarding"
    assert revisions["0086_onboarding"] == "0085_admin_lane"
    assert revisions["0084_boards_urgency"] == "0083_flyer_official_links"
    assert revisions["0083_flyer_official_links"] == "0082_reports_library"
    assert revisions["0082_reports_library"] == "0081_flyer_module"
    assert revisions["0081_flyer_module"] == "0080_truck_highest_balance"
    assert revisions["0080_truck_highest_balance"] == "0079_claims_overhaul"
    assert revisions["0079_claims_overhaul"] == "0078_dealer_personal_edits"
    assert revisions["0078_dealer_personal_edits"] == "0077_truck_accounts_stage2"
    assert revisions["0077_truck_accounts_stage2"] == "0076_claims_separation"
    assert revisions["0076_claims_separation"] == "0075_agent_records_stage1"
    assert revisions["0075_agent_records_stage1"] == "0074_claims_repairs_merge"
    assert revisions["0074_claims_repairs_merge"] == "0073_agent_takeover"
    assert revisions["0073_agent_takeover"] == "0072_forum_favorites"


# -- workstream B data shape ------------------------------------------------------


def test_company_records_items_carry_serial(client, db, owner, company):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name="Ratchet",
        model="S80",
        serial_numbers=["SN-12345"],
        dealer_company_id=company.id,
    )
    db.add(tool)
    battery = inventory_models.Battery(
        owner_id=owner.id,
        name="M18 pack",
        serial_number="BAT-777",
        dealer_company_id=company.id,
    )
    db.add(battery)
    db.commit()
    resp = client.get(
        f"/api/dealers/companies/{company.id}/my-records",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    items = {row["name"]: row for row in resp.json()["items"]}
    assert items["Ratchet"]["serial"] == "SN-12345"
    assert items["M18 pack"]["serial"] == "BAT-777"
