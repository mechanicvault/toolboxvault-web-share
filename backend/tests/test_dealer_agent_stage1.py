"""Dealer agent records, stage 1 (owner model, 2026-11-04).

Pins the settled model (goals/toolbox-vault-website/files/
dealer-agent-records-model-2026-11-04.md):

  - the private agent RECORD gains location (route area), a
    route schedule (frequency / weekday / anchor, next visit
    computed by route_days), and tenure (started_at / ended_at);
  - the dealer Agents tab is a ROSTER: the viewer's private
    records for the company + the platform agents he is
    CONNECTED with — never unconnected registered agents;
  - preferred is a PER-AGENT star (multi-preferred, owner
    ruling 2026-11-05 — supersedes stage 1's exactly-one):
    any number of agents per (viewer, company) may be starred;
    the first connection takes the flag automatically (the
    connect rule: only when nobody is starred yet); starring
    or unstarring never stamps tenure and never moves a
    claim — tenure tracks the CONNECTION (a platform row's
    start stamps when the row is created), and where one
    agent must be named, the EARLIEST starred is the display
    default;
  - there is no switch anymore: the switch endpoints are
    gone, claims stay seated with the agent who holds them,
    and the owner's per-claim re-point is the only way a seat
    changes hands;
  - deleting a never-linked record keeps its claims (name
    snapshot) and promotes NOBODY — the other agents' stars
    are untouched and the display default re-resolves; a
    linked record refuses deletion with the plain reason;
  - migration 0075: columns, started_at backfill, the earliest
    connection per (user, company) flagged, idempotent.
"""

import importlib.util
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"
TODAY = date.today()


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
        db, "TV-M-003101", "stage1-owner@example.com", [MECHANIC], "Ollie Owner"
    )


@pytest.fixture()
def agent_user(db):
    return _make_user(
        db, "TV-D-003102", "stage1-agent@example.com", [DEALER], "Andy Agent"
    )


@pytest.fixture()
def other_agent(db):
    return _make_user(
        db, "TV-D-003103", "stage1-other@example.com", [DEALER], "Oscar Other"
    )


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _create_agent(client, owner, company, name, **fields):
    payload = {"company_id": str(company.id), "name": name}
    payload.update(fields)
    resp = client.post(
        "/api/dealers/agents/private", json=payload, headers=auth_headers(owner)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _roster(client, owner, company):
    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _detail(client, owner, company, kind, ref_id):
    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster/agent",
        params={"kind": kind, "ref_id": str(ref_id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_flag(client, owner, company, *, private_id=None, user_id=None, is_preferred=True):
    payload = {"company_id": str(company.id), "is_preferred": is_preferred}
    if private_id is not None:
        payload["private_agent_id"] = str(private_id)
    if user_id is not None:
        payload["agent_user_id"] = str(user_id)
    return client.post(
        "/api/dealers/preferred/flag", json=payload, headers=auth_headers(owner)
    )


def _flagged_names(client, owner, company):
    roster = _roster(client, owner, company)
    return [e["name"] for e in roster if e["is_preferred"]]


def _tool(db, owner, company, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id, name=name, dealer_company_id=company.id, **overrides
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _file_claim(client, owner, tool, problem="It stopped working."):
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": problem,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["claim"]


def _claim_row(db, claim_id):
    return db.get(claims_models.Claim, uuid.UUID(str(claim_id)))


def _record(db, record_id):
    return db.get(dealer_models.PrivateAgent, uuid.UUID(str(record_id)))


# -- the record fields ----------------------------------------------------------


def test_record_fields_round_trip_and_route_rules(client, db, owner, company):
    created = _create_agent(
        client,
        owner,
        company,
        "Matt Driver",
        phone="555-0100",
        email="matt@example.com",
        location="Brainerd / Baxter area",
        route_frequency="weekly",
        route_day_of_week=2,
        route_anchor_date="2026-11-04",
        started_at="2023-05-01",
    )
    assert created["location"] == "Brainerd / Baxter area"
    assert created["route_frequency"] == "weekly"
    assert created["route_day_of_week"] == 2
    assert created["route_anchor_date"] == "2026-11-04"
    assert created["started_at"] == "2023-05-01"
    assert created["ended_at"] is None

    updated = client.put(
        f"/api/dealers/agents/private/{created['id']}",
        json={"route_frequency": "biweekly", "location": "North route"},
        headers=auth_headers(owner),
    )
    assert updated.status_code == 200, updated.text
    # A partial route edit merges over the record's schedule.
    assert updated.json()["route_frequency"] == "biweekly"
    assert updated.json()["route_day_of_week"] == 2
    assert updated.json()["route_anchor_date"] == "2026-11-04"
    assert updated.json()["location"] == "North route"

    # N/A clears the whole triple — no half a schedule.
    cleared = client.put(
        f"/api/dealers/agents/private/{created['id']}",
        json={"route_frequency": None},
        headers=auth_headers(owner),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["route_frequency"] is None
    assert cleared.json()["route_day_of_week"] is None
    assert cleared.json()["route_anchor_date"] is None

    bad = client.put(
        f"/api/dealers/agents/private/{created['id']}",
        json={"route_frequency": "daily"},
        headers=auth_headers(owner),
    )
    assert bad.status_code == 422, bad.text


def test_next_visit_renders_from_the_route_triple(client, db, owner, company):
    created = _create_agent(
        client,
        owner,
        company,
        "Matt Driver",
        route_frequency="weekly",
        route_day_of_week=TODAY.weekday(),
        route_anchor_date=TODAY.isoformat(),
    )
    roster = _roster(client, owner, company)
    assert roster[0]["next_visit"] == TODAY.isoformat()
    detail = _detail(client, owner, company, "private", created["id"])
    assert detail["entry"]["next_visit"] == TODAY.isoformat()
    # No truck account with this agent yet: the slot is honestly
    # empty, and no claims are seated with him.
    assert detail["truck_accounts"] == []
    assert detail["claims"] == []
    assert detail["can_delete"] is True


# -- roster + exactly-one preferred ----------------------------------------------


def test_first_agent_auto_preferred_and_roster_pinning(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    second = _create_agent(client, owner, company, "Second Sue")
    roster = _roster(client, owner, company)
    assert [e["name"] for e in roster] == ["First Fred", "Second Sue"]
    assert roster[0]["is_preferred"] is True
    assert roster[1]["is_preferred"] is False
    # The flag rides the preferred read every other surface uses.
    prefs = client.get(
        "/api/dealers/preferred",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    ).json()
    flagged = [p for p in prefs if p["is_preferred"]]
    assert len(flagged) == 1 and flagged[0]["private_agent_id"] == first["id"]
    assert second["id"]


def test_roster_holds_connected_platform_agents_only(
    client, db, owner, company, agent_user, other_agent
):
    # Both platform agents represent the company (verified);
    # NEITHER is on the roster until the owner connects.
    for user in (agent_user, other_agent):
        db.add(
            dealer_models.CompanyRepresentation(
                company_id=company.id, agent_user_id=user.id, verified=True
            )
        )
    db.commit()
    assert _roster(client, owner, company) == []

    connected = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": str(company.id),
            "agent_account_number": agent_user.account_number,
        },
        headers=auth_headers(owner),
    )
    assert connected.status_code in (200, 201), connected.text
    # First connection = THE preferred, automatically.
    assert connected.json()["is_preferred"] is True
    roster = _roster(client, owner, company)
    assert len(roster) == 1
    assert roster[0]["kind"] == "platform"
    assert roster[0]["agent_user_id"] == str(agent_user.id)
    assert roster[0]["is_preferred"] is True


# -- starring: tenure never moves ---------------------------------------------------


def test_starring_never_stamps_tenure_between_private_agents(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    second = _create_agent(client, owner, company, "Second Sue")
    # Fred's real start was long ago (hand-typed); Sue's start is
    # cleared. Under the switch model, starring Sue stamped her
    # start and ended Fred. Multi-preferred: a flag change is
    # not a tenure event — NOTHING about either record's dates
    # may move.
    client.put(
        f"/api/dealers/agents/private/{first['id']}",
        json={"started_at": "2023-05-01"},
        headers=auth_headers(owner),
    )
    record2 = _record(db, second["id"])
    record2.started_at = None
    db.commit()

    resp = _set_flag(client, owner, company, private_id=second["id"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_preferred"] is True
    # BOTH are preferred now — starring Sue did not unstar Fred.
    assert set(_flagged_names(client, owner, company)) == {"First Fred", "Second Sue"}
    assert _record(db, first["id"]).started_at == date(2023, 5, 1)
    assert _record(db, first["id"]).ended_at is None
    assert _record(db, second["id"]).started_at is None
    assert _record(db, second["id"]).ended_at is None

    # Unstarring Fred is just as inert: no end stamp, and Sue
    # keeps her star.
    resp = _set_flag(client, owner, company, private_id=first["id"], is_preferred=False)
    assert resp.status_code == 201, resp.text
    assert _flagged_names(client, owner, company) == ["Second Sue"]
    assert _record(db, first["id"]).ended_at is None


def test_platform_tenure_stamps_at_connection_not_at_the_star(
    client, db, owner, company, agent_user
):
    mine = _create_agent(client, owner, company, "My Guy")
    connected = client.post(
        "/api/dealers/preferred",
        json={
            "company_id": str(company.id),
            "agent_account_number": agent_user.account_number,
        },
        headers=auth_headers(owner),
    )
    assert connected.status_code in (200, 201), connected.text
    # The private record was first, so the platform connection
    # is NOT preferred — but its tenure has ALREADY started:
    # tenure tracks the connection, which was born just now.
    assert connected.json()["is_preferred"] is False
    assert connected.json()["tenure_started_at"] == TODAY.isoformat()
    assert connected.json()["tenure_ended_at"] is None

    # Starring him moves no dates on either seat.
    resp = _set_flag(client, owner, company, user_id=agent_user.id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["tenure_started_at"] == TODAY.isoformat()
    assert resp.json()["tenure_ended_at"] is None
    assert _record(db, mine["id"]).ended_at is None

    # Unstarring him doesn't end his tenure either.
    resp = _set_flag(client, owner, company, user_id=agent_user.id, is_preferred=False)
    assert resp.status_code == 201, resp.text
    row = db.scalars(
        select(dealer_models.PreferredAgent).where(
            dealer_models.PreferredAgent.agent_user_id == agent_user.id
        )
    ).first()
    assert row.tenure_started_at == TODAY
    assert row.tenure_ended_at is None


# -- starring: claims never move ------------------------------------------------------


def test_starring_never_moves_claims_and_repoint_is_per_claim(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    second = _create_agent(client, owner, company, "Second Sue")
    # Separate the creation stamps so roster order (and with it
    # "earliest preferred") is deterministic, not a same-second
    # id tiebreak.
    _record(db, first["id"]).created_at -= timedelta(minutes=2)
    _record(db, second["id"]).created_at -= timedelta(minutes=1)
    # The CONNECTION rows carry their own stamps, and the
    # connection-ordered reads (claims' default seat, the
    # preferred list) sort by THOSE — separate them too
    # (determinism repair, 2026-11-06: with only the agent
    # records stamped, the claim-seat assertions below were a
    # coin flip — 3 of 6 runs failed on the id tiebreak).
    for agent_id, minutes in ((first["id"], 2), (second["id"], 1)):
        connection = db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.private_agent_id
                == uuid.UUID(agent_id)
            )
        ).one()
        connection.created_at -= timedelta(minutes=minutes)
    db.commit()
    claim1 = _file_claim(client, owner, _tool(db, owner, company, "Ratchet"))
    claim2 = _file_claim(client, owner, _tool(db, owner, company, "Wrench"))
    for claim in (claim1, claim2):
        assert _claim_row(db, claim["id"]).private_agent_id == uuid.UUID(first["id"])

    # The old switch endpoints are GONE (404/405 — no route
    # answers a POST there anymore) — there is no
    # move/stay/delete question to answer anymore.
    for url in ("/api/dealers/preferred/set", "/api/dealers/preferred/switch-check"):
        resp = client.post(
            url,
            json={"company_id": str(company.id), "private_agent_id": second["id"]},
            headers=auth_headers(owner),
        )
        assert resp.status_code in (404, 405), (url, resp.status_code)

    # Starring Sue asks nothing and moves nothing: both claims
    # keep Fred's seat, and a claim filed now still defaults to
    # Fred — the EARLIEST preferred is the display default.
    resp = _set_flag(client, owner, company, private_id=second["id"])
    assert resp.status_code == 201, resp.text
    assert _flagged_names(client, owner, company) == ["First Fred", "Second Sue"]
    assert _claim_row(db, claim1["id"]).private_agent_id == uuid.UUID(first["id"])
    assert _claim_row(db, claim2["id"]).private_agent_id == uuid.UUID(first["id"])
    claim3 = _file_claim(client, owner, _tool(db, owner, company, "Driver"))
    assert _claim_row(db, claim3["id"]).private_agent_id == uuid.UUID(first["id"])

    # The owner's per-claim re-point is the one way a seat
    # changes hands: claim1 goes to Sue, by name.
    moved = client.patch(
        f"/api/claims/{claim1['id']}/agent",
        json={"private_agent_id": second["id"]},
        headers=auth_headers(owner),
    )
    assert moved.status_code == 200, moved.text
    assert _claim_row(db, claim1["id"]).private_agent_id == uuid.UUID(second["id"])
    assert _claim_row(db, claim2["id"]).private_agent_id == uuid.UUID(first["id"])

    # His record lists exactly his claims: Sue holds claim1;
    # Fred keeps claim2 + claim3.
    detail2 = _detail(client, owner, company, "private", second["id"])
    assert {c["id"] for c in detail2["claims"]} == {claim1["id"]}
    detail1 = _detail(client, owner, company, "private", first["id"])
    assert {c["id"] for c in detail1["claims"]} == {claim2["id"], claim3["id"]}


def test_starring_asks_nothing_open_or_closed(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    second = _create_agent(client, owner, company, "Second Sue")
    open_claim = _file_claim(client, owner, _tool(db, owner, company, "Ratchet"))
    done_claim = _file_claim(client, owner, _tool(db, owner, company, "Wrench"))
    row = _claim_row(db, done_claim["id"])
    row.status = claims_models.STATUS_COMPLETED
    db.commit()

    # Fred holds an OPEN claim and a finished one; starring Sue
    # used to stop and ask about the open one. Now it simply
    # lands — and neither claim's seat moves.
    resp = _set_flag(client, owner, company, private_id=second["id"])
    assert resp.status_code == 201, resp.text
    assert _claim_row(db, open_claim["id"]).private_agent_id == uuid.UUID(first["id"])
    assert _claim_row(db, done_claim["id"]).private_agent_id == uuid.UUID(first["id"])


# -- deletion ------------------------------------------------------------------------


def test_delete_agent_keeps_closed_claim_with_his_name(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    claim = _file_claim(client, owner, _tool(db, owner, company))
    row = _claim_row(db, claim["id"])
    row.status = claims_models.STATUS_COMPLETED
    db.commit()

    resp = client.delete(
        f"/api/dealers/agents/private/{first['id']}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text
    assert _record(db, first["id"]) is None
    # The claim survives under the dealer, attributed by NAME.
    kept = _claim_row(db, claim["id"])
    assert kept is not None
    assert kept.private_agent_id is None
    assert kept.agent_name_snapshot == "First Fred"
    view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(owner)
    )
    assert view.status_code == 200, view.text
    assert view.json()["warranty_agent"]["name"] == "First Fred"
    assert view.json()["warranty_agent"]["kind"] == "snapshot"


def test_delete_preferred_promotes_nobody(client, db, owner, company):
    first = _create_agent(client, owner, company, "First Fred")
    second = _create_agent(client, owner, company, "Second Sue")
    third = _create_agent(client, owner, company, "Third Tom")
    # "Earliest" is a created_at race at same-second granularity,
    # so the fixtures separate the connection stamps explicitly
    # (the agent-scope suite's convention).
    rows = list(
        db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == owner.id
            )
        )
    )
    by_record = {str(r.private_agent_id): r for r in rows}
    for record, minutes in ((first, 3), (second, 2), (third, 1)):
        by_record[record["id"]].created_at -= timedelta(minutes=minutes)
    db.commit()
    # Two starred at once (Fred auto + Sue starred); Tom plain.
    assert _set_flag(client, owner, company, private_id=second["id"]).status_code == 201
    assert _flagged_names(client, owner, company) == ["First Fred", "Second Sue"]

    # Deleting a preferred agent promotes NOBODY: Sue keeps her
    # star, Tom stays unstarred, and the summary simply
    # re-resolves to Sue — now the ONLY flagged agent, so the
    # preferred-display summary names her (2026-11-06).
    assert client.delete(
        f"/api/dealers/agents/private/{first['id']}",
        headers=auth_headers(owner),
    ).status_code == 204
    assert _flagged_names(client, owner, company) == ["Second Sue"]
    on_record = client.get(
        "/api/dealers/preferred/on-record",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    )
    assert on_record.json()["state"] == "one"
    assert on_record.json()["agent"]["private_agent_id"] == second["id"]

    # Deleting the last starred agent leaves NO star in the
    # data (the preferred read shows Tom unflagged) — the
    # roster read then heals one onto the earliest remaining
    # connection, the standing fallback every surface applies.
    assert client.delete(
        f"/api/dealers/agents/private/{second['id']}",
        headers=auth_headers(owner),
    ).status_code == 204
    prefs = client.get(
        "/api/dealers/preferred",
        params={"company_id": str(company.id)},
        headers=auth_headers(owner),
    ).json()
    assert [p["is_preferred"] for p in prefs] == [False]
    assert _flagged_names(client, owner, company) == ["Third Tom"]
    assert client.delete(
        f"/api/dealers/agents/private/{third['id']}",
        headers=auth_headers(owner),
    ).status_code == 204
    assert _roster(client, owner, company) == []


def test_delete_linked_record_refused_with_reason(client, db, owner, company, agent_user):
    created = _create_agent(client, owner, company, "Taken Tim")
    record = _record(db, created["id"])
    record.linked_user_id = agent_user.id
    record.link_source = "takeover"
    db.commit()

    detail = _detail(client, owner, company, "private", created["id"])
    assert detail["can_delete"] is False
    assert "working agent" in (detail["delete_block_reason"] or "")

    resp = client.delete(
        f"/api/dealers/agents/private/{created['id']}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert "working agent" in resp.json()["detail"]
    assert _record(db, created["id"]) is not None


# -- migration 0075 ---------------------------------------------------------------------


_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0075_agent_records_stage1.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0075", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0075_engine():
    engine = sa.create_engine("sqlite://")
    u1, u2, c1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    a1, a2 = str(uuid.uuid4()), str(uuid.uuid4())
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE private_agents ("
                " id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(36) NOT NULL,"
                " company_id VARCHAR(36), name VARCHAR(300) NOT NULL,"
                " created_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO private_agents (id, owner_id, company_id, name, created_at)"
                " VALUES (:id, :o, :c, 'Old Agent', '2024-03-05 10:30:00')"
            ),
            {"id": a1, "o": u1, "c": c1},
        )
        conn.execute(
            sa.text(
                "INSERT INTO private_agents (id, owner_id, company_id, name, created_at)"
                " VALUES (:id, :o, :c, 'Older Agent', '2023-01-15 08:00:00')"
            ),
            {"id": a2, "o": u1, "c": c1},
        )
        conn.execute(
            sa.text(
                "CREATE TABLE preferred_agents ("
                " id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,"
                " company_id VARCHAR(36) NOT NULL, agent_user_id VARCHAR(36),"
                " private_agent_id VARCHAR(36), created_at DATETIME NOT NULL)"
            )
        )
        # u1 has TWO rows for c1 (earliest must take the flag);
        # u2 has one.
        for pid, uid, created in (
            (p1, u1, "2024-03-05 10:30:00"),
            (p2, u1, "2024-06-01 09:00:00"),
            (p3, u2, "2024-04-01 09:00:00"),
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO preferred_agents"
                    " (id, user_id, company_id, agent_user_id, private_agent_id, created_at)"
                    " VALUES (:id, :u, :c, NULL, :a, :t)"
                ),
                {"id": pid, "u": uid, "c": c1, "a": a1, "t": created},
            )
        conn.execute(sa.text("CREATE TABLE claims (id VARCHAR(36) PRIMARY KEY)"))
    return engine, {"p1": p1, "p2": p2, "p3": p3, "a1": a1, "a2": a2}


def _run_upgrade(engine, migration):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.upgrade()
        conn.commit()


def test_migration_0075_shape_backfill_flag_and_idempotency():
    migration = _load_migration()
    assert migration.revision == "0075_agent_records_stage1"
    assert migration.down_revision == "0074_claims_repairs_merge"
    engine, ids = _pre_0075_engine()
    _run_upgrade(engine, migration)
    _run_upgrade(engine, migration)  # idempotent: a no-op second run
    with engine.connect() as conn:
        agents = {
            row[0]: row[1]
            for row in conn.execute(
                sa.text("SELECT id, started_at FROM private_agents")
            )
        }
        assert str(agents[ids["a1"]])[:10] == "2024-03-05"
        assert str(agents[ids["a2"]])[:10] == "2023-01-15"
        flags = {
            row[0]: bool(row[1])
            for row in conn.execute(
                sa.text("SELECT id, is_preferred FROM preferred_agents")
            )
        }
        assert flags[ids["p1"]] is True  # earliest for (u1, c1)
        assert flags[ids["p2"]] is False  # surplus row: connection kept
        assert flags[ids["p3"]] is True  # u2's only row
        pref_cols = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA table_info(preferred_agents)"))
        }
        assert {"is_preferred", "tenure_started_at", "tenure_ended_at"} <= pref_cols
        agent_cols = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA table_info(private_agents)"))
        }
        assert {
            "location",
            "route_frequency",
            "route_day_of_week",
            "route_anchor_date",
            "started_at",
            "ended_at",
        } <= agent_cols
        claim_cols = {
            row[1] for row in conn.execute(sa.text("PRAGMA table_info(claims)"))
        }
        assert "agent_name_snapshot" in claim_cols
