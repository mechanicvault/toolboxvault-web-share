"""Claims overhaul (owner orders, 2026-11-05 #6–#9; built 2026-11-06).

Pins the four orders:

  1. FILING CHOICE — a warranty claim is filed one of three
     ways: with the agent (the standing agent-scope flow), by
     the owner himself (self — no second seat), or straight with
     the dealer COMPANY (corporate — the company's VERIFIED reps
     form the second seat, for those claims only). Migration
     0079's backfill maps history honestly (agent pointer or
     snapshot -> agent; otherwise self).
  2. THE NEW LADDER — Ryan's 8 statuses, FREE-FORM for owner and
     seated counterparty alike; closing is a layer (closed_at),
     never a status, and it alone moves a claim to history.
  3. BACKORDER REMINDERS — while a claim is Backordered, owner +
     seated counterparty get one inbox reminder a month, first a
     month after entering; the claim's own stamps dedupe re-runs.
  4./5. (frontend orders — evidence tiles, comm-log date only):
     the comm half is pinned here at the API: a bare DATE is a
     valid occurred_at and stores as that day's midnight, while
     a full datetime still parses (history keeps its times).

Disaster claims are the control group throughout: the overhaul
never touches their statuses, filing, or pages.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.claims import models as claims_models
from app.modules.claims import service as claims_service
from app.modules.core import inbox
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
        db, "TV-M-002101", "overhaul-owner@example.com", [MECHANIC], "Ollie Owner"
    )


@pytest.fixture()
def agent1(db):
    return _make_user(
        db, "TV-D-002102", "overhaul-agent1@example.com", [DEALER], "Agent One"
    )


@pytest.fixture()
def rep(db):
    """A platform user who represents the company but is NOT any
    owner's agent — the pure corporate seat."""
    return _make_user(
        db, "TV-D-002103", "overhaul-rep@example.com", [DEALER], "Rita Rep"
    )


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _company(db, name="Matco Tools"):
    company = dealer_models.DealerCompany(name=name, is_directory=True)
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


def _prefer_platform(db, owner, company, agent_user):
    row = dealer_models.PreferredAgent(
        user_id=owner.id, company_id=company.id, agent_user_id=agent_user.id
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


def _transition(client, user, claim_id, to_status, **extra):
    return client.post(
        f"/api/claims/{claim_id}/transition",
        json={"to_status": to_status, **extra},
        headers=auth_headers(user),
    )


def _get_claim(client, user, claim_id):
    return client.get(f"/api/claims/{claim_id}", headers=auth_headers(user))


def _incoming_ids(client, user):
    rows = client.get(
        "/api/claims/incoming", headers=auth_headers(user)
    ).json()
    return [row["id"] for row in rows]


def _notifications(db, user, kind=None):
    stmt = select(core_models.Notification).where(
        core_models.Notification.user_id == user.id
    )
    if kind:
        stmt = stmt.where(core_models.Notification.kind == kind)
    return list(db.scalars(stmt))


def _claim_row(db, claim_id):
    return db.get(claims_models.Claim, uuid.UUID(str(claim_id)))


# -- order 1: the three filing routes -----------------------------------------


def test_corporate_filing_seats_the_companys_verified_reps(
    client, db, owner, agent1, rep
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, rep, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    created = _warranty(
        client, owner, "tool", tool.id, filed_with="corporate"
    )
    assert created.status_code == 201, created.text
    body = created.json()
    claim = body["claim"]
    assert claim["filed_with"] == "corporate"
    assert claim["warranty_agent"] is None
    # The system reported it to the reps (their inboxes are the
    # company's channel): REPORTED by system, via notice, and
    # BOTH verified reps heard about it.
    assert claim["status"] == "reported"
    assert claim["report_method"] == "system"
    assert body["reported"] is True
    assert body["report_via"] == ["notice"]
    for user in (agent1, rep):
        news = _notifications(db, user, inbox.KIND_WARRANTY_CLAIM_NEW)
        assert len(news) == 1

    # The pure rep (never anyone's agent) can open and work it,
    # and it sits in her worklist carrying its mode.
    view = _get_claim(client, rep, claim["id"])
    assert view.status_code == 200, view.text
    assert view.json()["viewer_role"] == "dealer"
    assert view.json()["filed_with"] == "corporate"
    assert claim["id"] in _incoming_ids(client, rep)

    # The rep drives the free ladder on it, too.
    moved = _transition(client, rep, claim["id"], "waiting_on_parts")
    assert moved.status_code == 200, moved.text


def test_corporate_seat_never_reaches_agent_or_self_claims(
    client, db, owner, agent1, rep
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, rep, verified=True)
    _prefer_platform(db, owner, company, agent1)

    agent_tool = _tool(db, owner, name="Agent drill", dealer_company_id=company.id)
    agent_claim = _warranty(client, owner, "tool", agent_tool.id).json()["claim"]
    assert agent_claim["filed_with"] == "agent"

    self_tool = _tool(db, owner, name="Self saw", dealer_company_id=company.id)
    self_claim = _warranty(
        client, owner, "tool", self_tool.id, filed_with="self"
    ).json()["claim"]
    assert self_claim["filed_with"] == "self"
    assert self_claim["warranty_agent"] is None

    # The rep sees NEITHER — the company seat is corporate-only.
    for other in (agent_claim, self_claim):
        assert _get_claim(client, rep, other["id"]).status_code in (403, 404)
    assert _incoming_ids(client, rep) == []
    # And the self claim is invisible to the preferred agent too.
    assert _get_claim(client, agent1, self_claim["id"]).status_code in (403, 404)
    # The agent claim still seats its agent exactly as before.
    assert _get_claim(client, agent1, agent_claim["id"]).status_code == 200


def test_corporate_filing_refusals_and_no_rep_fallback(
    client, db, owner, agent1
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)

    # Corporate + an agent pointer is two routes at once.
    both = _warranty(
        client,
        owner,
        "tool",
        tool.id,
        filed_with="corporate",
        agent_user_id=str(agent1.id),
    )
    assert both.status_code == 422, both.text

    # A claim with no dealer has no company to file with.
    plain = _tool(db, owner, name="No dealer drill")
    no_dealer = _warranty(
        client, owner, "tool", plain.id, filed_with="corporate"
    )
    assert no_dealer.status_code == 422, no_dealer.text

    # Corporate with NO verified reps anywhere: the claim exists,
    # unreported — the owner tells the company himself.
    other_company = _company(db, name="Rep-less Tools")
    _prefer_platform(db, owner, other_company, agent1)
    lonely = _tool(db, owner, name="Lonely saw", dealer_company_id=other_company.id)
    created = _warranty(client, owner, "tool", lonely.id, filed_with="corporate")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["claim"]["filed_with"] == "corporate"
    assert body["claim"]["status"] == "not_reported"
    assert body["reported"] is False
    assert body["report_via"] == []


def test_unverified_rep_gets_nothing(client, db, owner, rep):
    company = _company(db)
    _represent(db, company, rep, verified=False)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(
        client, owner, "tool", tool.id, filed_with="corporate",
        dealer_notified=True,
    )
    claim = created.json()["claim"]
    assert _get_claim(client, rep, claim["id"]).status_code in (403, 404)
    assert _incoming_ids(client, rep) == []
    assert _notifications(db, rep) == []


def test_repointing_moves_the_filed_with_mode(client, db, owner, agent1, rep):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, rep, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    claim = _warranty(
        client, owner, "tool", tool.id, filed_with="corporate"
    ).json()["claim"]

    # Point it at the agent: the mode follows the seat, and the
    # company seat lets go.
    repointed = client.patch(
        f"/api/claims/{claim['id']}/agent",
        json={"agent_user_id": str(agent1.id)},
        headers=auth_headers(owner),
    )
    assert repointed.status_code == 200, repointed.text
    assert repointed.json()["filed_with"] == "agent"
    assert _get_claim(client, rep, claim["id"]).status_code in (403, 404)

    # Clear the agent: the claim becomes the owner's alone.
    cleared = client.patch(
        f"/api/claims/{claim['id']}/agent",
        json={},
        headers=auth_headers(owner),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["filed_with"] == "self"
    assert _get_claim(client, agent1, claim["id"]).status_code in (403, 404)


# -- order 2: the free ladder + the closed layer -------------------------------


def test_free_ladder_both_seats_and_close_layer(client, db, owner, agent1):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    claim = _warranty(client, owner, "tool", tool.id).json()["claim"]
    # The live agent seat means the system reported it at filing.
    assert claim["status"] == "reported"

    # The agent sets statuses the old ladder forbade him.
    for to_status in ("waiting_on_agent", "backordered", "reported"):
        moved = _transition(client, agent1, claim["id"], to_status)
        assert moved.status_code == 200, (to_status, moved.text)
        assert moved.json()["status"] == to_status
    # Entering Backordered stamped the clock.
    row = _claim_row(db, claim["id"])
    assert row.backorder_entered_at is not None
    assert row.backorder_last_reminded_at is None

    # The counterparty still cannot close — owner only.
    refused = _transition(client, agent1, claim["id"], "closed")
    assert refused.status_code == 422, refused.text

    # The owner closes from an open status: the STATUS SURVIVES,
    # closed_at stamps, and the record is then final.
    moved = _transition(client, owner, claim["id"], "waiting_on_parts")
    assert moved.status_code == 200, moved.text
    closed = _transition(client, owner, claim["id"], "closed")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "waiting_on_parts"
    assert closed.json()["closed_at"] is not None
    after = _transition(client, owner, claim["id"], "reported")
    assert after.status_code == 422, after.text


def test_item_standing_follows_the_new_statuses(client, db, owner):
    tool = _tool(db, owner)
    claim = _warranty(
        client, owner, "tool", tool.id, filed_with="self"
    ).json()["claim"]

    def standing():
        db.expire_all()
        return db.get(inventory_models.Tool, tool.id).standing

    assert standing() == inventory_models.STANDING_BROKEN
    # "Agent has tool" = the tool is away, like sent in.
    moved = _transition(client, owner, claim["id"], "agent_has_tool")
    assert moved.status_code == 200, moved.text
    assert standing() == inventory_models.STANDING_IN_REPAIR
    # A waiting status = the tool is back here, still broken.
    moved = _transition(client, owner, claim["id"], "waiting_on_parts")
    assert moved.status_code == 200, moved.text
    assert standing() == inventory_models.STANDING_BROKEN
    # Repaired returns it to service.
    moved = _transition(client, owner, claim["id"], "completed")
    assert moved.status_code == 200, moved.text
    assert standing() == inventory_models.STANDING_IN_SERVICE


def test_closed_claim_frees_its_target_and_leaves_the_open_count(
    client, db, owner
):
    tool = _tool(db, owner)
    first = _warranty(
        client, owner, "tool", tool.id, filed_with="self"
    ).json()["claim"]
    # A second open claim for the same break is refused...
    again = _warranty(client, owner, "tool", tool.id, filed_with="self")
    assert again.status_code == 422, again.text
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 1
    # ...until the first is CLOSED (from an open status — the
    # closed layer, not completion, is what frees the target).
    closed = _transition(client, owner, first["id"], "closed")
    assert closed.status_code == 200, closed.text
    second = _warranty(client, owner, "tool", tool.id, filed_with="self")
    assert second.status_code == 201, second.text
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 1


def test_repaired_claim_leaves_the_open_count(client, db, owner):
    tool = _tool(db, owner)
    claim = _warranty(
        client, owner, "tool", tool.id, filed_with="self"
    ).json()["claim"]
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 1
    moved = _transition(client, owner, claim["id"], "completed")
    assert moved.status_code == 200, moved.text
    # Repaired is the ladder's terminal: finished work leaves
    # the open count (and reads as history) right there — the
    # closed layer is a SEPARATE shelving act, not what makes a
    # repaired claim done. (This corrects the lane's first-cut
    # reading, which kept Repaired "open" until closing; the
    # settled surfaces — item-page history, the home stat —
    # never treated completion as open work.)
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 0
    closed = _transition(client, owner, claim["id"], "closed")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "completed"
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 0


# -- order 3: backorder reminders ----------------------------------------------

_ENTERED = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _backordered_claim(client, db, owner, tool, **kwargs):
    claim = _warranty(client, owner, "tool", tool.id, **kwargs).json()["claim"]
    moved = _transition(client, owner, claim["id"], "backordered")
    assert moved.status_code == 200, moved.text
    row = _claim_row(db, claim["id"])
    row.backorder_entered_at = _ENTERED
    db.commit()
    return claim


def test_backorder_reminder_cadence_and_dedupe(client, db, owner, agent1):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _prefer_platform(db, owner, company, agent1)
    tool = _tool(db, owner, dealer_company_id=company.id)
    claim = _backordered_claim(client, db, owner, tool)

    # Not yet a month in: nothing.
    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=20)
    ) == 0
    # A month in: owner AND agent reminded, once each.
    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=32)
    ) == 1
    for user in (owner, agent1):
        notes = _notifications(db, user, inbox.KIND_CLAIM_BACKORDER)
        assert len(notes) == 1
        assert notes[0].data["claim_id"] == claim["id"]
    # A re-run inside the month double-reminds nobody.
    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=40)
    ) == 0
    # The next month earns the next reminder.
    row = _claim_row(db, claim["id"])
    row.backorder_last_reminded_at = _ENTERED + timedelta(days=32)
    db.commit()
    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=65)
    ) == 1
    assert len(_notifications(db, owner, inbox.KIND_CLAIM_BACKORDER)) == 2


def test_backorder_reminder_recipients_follow_the_mode(
    client, db, owner, agent1, rep
):
    company = _company(db)
    _represent(db, company, agent1, verified=True)
    _represent(db, company, rep, verified=True)
    _prefer_platform(db, owner, company, agent1)

    self_tool = _tool(db, owner, name="Self saw", dealer_company_id=company.id)
    _backordered_claim(client, db, owner, self_tool, filed_with="self")
    corp_tool = _tool(db, owner, name="Corp saw", dealer_company_id=company.id)
    _backordered_claim(client, db, owner, corp_tool, filed_with="corporate")

    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=32)
    ) == 2
    # Self-filed: the owner alone (2 claims -> 2 reminders).
    assert len(_notifications(db, owner, inbox.KIND_CLAIM_BACKORDER)) == 2
    # Corporate: the rep is reminded; the owner's agent is NOT
    # (he is not this claim's counterparty, rep hat or not —
    # agent1 holds a rep too, so he is reminded ONCE, qua rep).
    assert len(_notifications(db, rep, inbox.KIND_CLAIM_BACKORDER)) == 1
    assert len(_notifications(db, agent1, inbox.KIND_CLAIM_BACKORDER)) == 1


def test_backorder_reminders_stop_and_restart(client, db, owner):
    tool = _tool(db, owner)
    claim = _backordered_claim(client, db, owner, tool, filed_with="self")
    # Leaving the status stops future reminders.
    moved = _transition(client, owner, claim["id"], "waiting_on_agent")
    assert moved.status_code == 200, moved.text
    assert claims_service.run_backorder_reminders(
        db, now=_ENTERED + timedelta(days=90)
    ) == 0
    # Re-entering restarts the clock from the new entry.
    moved = _transition(client, owner, claim["id"], "backordered")
    assert moved.status_code == 200, moved.text
    row = _claim_row(db, claim["id"])
    entered = row.backorder_entered_at
    if entered.tzinfo is None:
        entered = entered.replace(tzinfo=timezone.utc)  # SQLite reads back naive
    assert entered > _ENTERED
    assert row.backorder_last_reminded_at is None
    assert claims_service.run_backorder_reminders(
        db, now=entered + timedelta(days=20)
    ) == 0


# -- order 5 (API half): the comm log takes a date ------------------------------


def test_communication_takes_a_date_only(client, db, owner):
    tool = _tool(db, owner)
    claim = _warranty(
        client, owner, "tool", tool.id, filed_with="self"
    ).json()["claim"]
    added = client.post(
        f"/api/claims/{claim['id']}/communications",
        json={
            "channel": "phone",
            "contact": "Dealer counter",
            "summary": "Called about the part.",
            "occurred_at": "2026-10-15",
        },
        headers=auth_headers(owner),
    )
    assert added.status_code in (200, 201), added.text
    view = _get_claim(client, owner, claim["id"]).json()
    entries = [
        e for e in view["communications"] if e["summary"] == "Called about the part."
    ]
    assert len(entries) == 1
    # Stored day-precise: that date at midnight, no time rides in.
    assert entries[0]["occurred_at"].startswith("2026-10-15T00:00:00")

    # A full datetime from an older client still parses.
    added = client.post(
        f"/api/claims/{claim['id']}/communications",
        json={
            "channel": "email",
            "contact": "Dealer counter",
            "summary": "Emailed the receipt.",
            "occurred_at": "2026-10-16T14:30:00Z",
        },
        headers=auth_headers(owner),
    )
    assert added.status_code in (200, 201), added.text


# -- migration 0079 --------------------------------------------------------------


def test_migration_0079_backfill_and_status_remap():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0079_claims_overhaul.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0079", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0078_dealer_personal_edits"

    engine = sa.create_engine("sqlite://")
    closed_at = "2026-11-05 04:25:50+00:00"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE claims ("
                "id TEXT PRIMARY KEY, kind TEXT, status TEXT, "
                "closed_at TEXT, agent_user_id TEXT, "
                "private_agent_id TEXT, agent_name_snapshot TEXT)"
            )
        )
        rows = [
            # warranty closed WITH a private agent -> agent + completed
            ("w1", "warranty_repair", "closed", closed_at, None, "pa1", ""),
            # warranty closed, no agent anywhere -> self + completed
            ("w2", "warranty_repair", "closed", closed_at, None, None, ""),
            # warranty open with a platform agent -> agent, status kept
            ("w3", "warranty_repair", "reported", None, "au1", None, ""),
            # warranty open, agent only as a snapshot -> agent
            ("w4", "warranty_repair", "in_repair", None, None, None, "Gone Gary"),
            # warranty open, nobody -> self
            ("w5", "warranty_repair", "not_reported", None, None, None, ""),
            # insurance rows: never rewritten
            ("i1", "insurance_disaster", "closed", closed_at, None, None, ""),
            ("i2", "insurance_disaster", "filed", None, None, None, ""),
        ]
        for row in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO claims VALUES (:id, :kind, :status, "
                    ":closed_at, :au, :pa, :snap)"
                ),
                {
                    "id": row[0], "kind": row[1], "status": row[2],
                    "closed_at": row[3], "au": row[4], "pa": row[5],
                    "snap": row[6],
                },
            )
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
    with engine.connect() as conn:
        result = {
            r[0]: (r[1], r[2], r[3])
            for r in conn.execute(
                sa.text("SELECT id, filed_with, status, closed_at FROM claims")
            )
        }
    assert result["w1"] == ("agent", "completed", closed_at)
    assert result["w2"] == ("self", "completed", closed_at)
    assert result["w3"] == ("agent", "reported", None)
    assert result["w4"] == ("agent", "in_repair", None)
    assert result["w5"] == ("self", "not_reported", None)
    # Disaster rows byte-identical in every column the migration
    # could touch (filed_with reads the column default "self",
    # which the disaster flow never reads).
    assert result["i1"] == ("self", "closed", closed_at)
    assert result["i2"] == ("self", "filed", None)
    with engine.connect() as conn:
        cols = {
            r[1] for r in conn.execute(sa.text("PRAGMA table_info(claims)"))
        }
    assert "backorder_entered_at" in cols
    assert "backorder_last_reminded_at" in cols
