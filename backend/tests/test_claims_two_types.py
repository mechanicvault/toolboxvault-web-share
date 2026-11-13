"""Claims two-types build (owner model, confirmed 2026-10-25).

Covers the second kind of claim — WARRANTY & REPAIR — beside the
existing INSURANCE DISASTER kind:

  - every pre-existing claim shape classifies insurance_disaster;
  - the warranty quick-create: auto-report to the dealer by email
    + inbox notice when the data allows (report_method "system"),
    the owner's own "already told them" (report_method "user"),
    and the honest not-reported state when no route exists;
  - a second OPEN warranty claim on the same target is refused;
  - a PIECE claim carries BOTH numbers — the piece's own part
    number and the parent set's model number — on the line, in
    the agent's views, and in the report email (owner steering);
  - the agent side is real (REVISED 2026-10-31, agent scope):
    the claim runs through the owner's ONE agent for the dealer
    (their agent on record by default) — it shows on that agent's
    incoming worklist, the agent opens it as viewer_role
    "dealer", drives the middle of the ladder, and both parties
    are inbox-notified of each other's moves; the rest of the
    company (other agents, an unverified link) and strangers get
    404. The full agent-scope proof lives in
    test_claims_agent_scope.py; the setups here were re-pointed
    at the new model (assigned + verified agent) where they used
    to rely on company-wide access;
  - the ladder refuses illegal moves (no skipping to completed,
    a dealer can't close);
  - the broken prompt's Replace: "same" clones the item with the
    amount spent + today's date and retires the old one to the
    "replaced" standing (out of the cap, the lists and search;
    still readable, still in reports, stamped with the swap
    marker); "different" retires only; an open claim refuses;
  - the insurance machinery stays insurance-only: the package
    refuses a warranty claim.
"""

import importlib.util
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
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
    return _make_user(db, "TV-M-000701", "two-owner@example.com", [MECHANIC], "Walt Owner")


@pytest.fixture()
def dealer_user(db):
    return _make_user(db, "TV-D-000702", "two-dealer@example.com", [DEALER], "Dan Dealer")


@pytest.fixture()
def stranger(db):
    return _make_user(db, "TV-M-000703", "two-stranger@example.com", [MECHANIC], "Sue Stranger")


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _company(db, name="Acme Tool Co", *, email="", is_directory=True):
    company = dealer_models.DealerCompany(
        name=name, email=email, is_directory=is_directory
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _represent(db, company, user, *, verified=False):
    row = dealer_models.CompanyRepresentation(
        company_id=company.id, agent_user_id=user.id, verified=verified
    )
    db.add(row)
    db.commit()
    return row


def _prefer(db, owner, company, agent_user):
    """Make `agent_user` one of the owner's agents on record for
    the company (a platform preferred-agent row)."""
    row = dealer_models.PreferredAgent(
        user_id=owner.id, company_id=company.id, agent_user_id=agent_user.id
    )
    db.add(row)
    db.commit()
    return row


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


def _warranty(client, user, target_kind, target_id, **kwargs):
    payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "dealer_notified": False,
        "problem": "It stopped working.",
    }
    payload.update(kwargs)
    return client.post("/api/claims/warranty", json=payload, headers=auth_headers(user))


# -- migration ---------------------------------------------------------------


def test_migration_0060_shape_and_chain():
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    path = versions / "0060_claims_two_types.py"
    spec = importlib.util.spec_from_file_location("mig0060", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0060_claims_two_types"
    assert migration.down_revision == "0059_set_piece_core_price"
    # The source carries the columns the models declare (the
    # upgrade itself is Postgres DDL — an FK add SQLite's ALTER
    # can't do — so the chain + source are what a test can pin).
    source = path.read_text()
    for needle in (
        '"kind"',
        '"dealer_company_id"',
        '"dealer_name"',
        '"reported_at"',
        '"report_method"',
        '"author_id"',
        '"author_role"',
        '"author_name"',
        '"target_part_number"',
        '"set_model_number"',
    ):
        assert needle in source, needle
    # Revision map: every migration's down_revision resolves and
    # the chain is one line ending in a single head, with 0060
    # linked between the Sets lane's 0059 and whatever follows.
    import re

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
    assert revisions["0060_claims_two_types"] == "0059_set_piece_core_price"
    for rev, down in revisions.items():
        assert down is None or down in revisions, (rev, down)
    children = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in children]
    assert len(heads) == 1
    # Walking down from the head passes through 0060 then 0059.
    chain = []
    cursor = heads[0]
    while cursor is not None:
        chain.append(cursor)
        cursor = revisions[cursor]
    idx = chain.index("0060_claims_two_types")
    assert chain[idx + 1] == "0059_set_piece_core_price"


# -- the kind split ------------------------------------------------------------


def test_existing_claim_shape_defaults_to_insurance(client, owner):
    # Claims separation (2026-11-05): the bare create lives in
    # the Disaster Claims section now and still mints an
    # insurance claim; the warranty Claims list shows none of it.
    response = client.post(
        "/api/disaster-claims", json={}, headers=auth_headers(owner)
    )
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "insurance_disaster"
    listing = client.get("/api/disaster-claims", headers=auth_headers(owner)).json()
    assert listing[0]["kind"] == "insurance_disaster"
    assert client.get("/api/claims", headers=auth_headers(owner)).json() == []


# -- warranty create: the three report outcomes --------------------------------


def test_warranty_create_user_already_notified(client, db, owner, dealer_user):
    company = _company(db)  # no email: the inbox notice is the route
    # Agent scope (2026-10-31): the dealer user is the owner's
    # agent on record for the company, with a VERIFIED link — the
    # claim's second seat.
    _represent(db, company, dealer_user, verified=True)
    _prefer(db, owner, company, dealer_user)
    tool = _tool(db, owner, dealer_company_id=company.id)

    response = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    assert response.status_code == 201, response.text
    body = response.json()
    claim = body["claim"]
    assert claim["kind"] == "warranty_repair"
    assert claim["status"] == "reported"
    assert claim["report_method"] == "user"
    assert claim["dealer_name"] == company.name
    assert body["reported"] is True
    assert body["report_via"] == ["notice"]
    # The assigned agent hears the record arrived.
    notes = _notifications(db, dealer_user, "warranty_claim_new")
    assert len(notes) == 1
    assert notes[0].data["claim_id"] == claim["id"]
    # The comm log holds the "already told them" entry, authored.
    assert len(claim["communications"]) == 1
    entry = claim["communications"][0]
    assert entry["author_role"] == "owner"
    assert entry["author_name"] == owner.name
    # No report email anywhere — the owner did the telling.
    # (The inbox notice's own email twin to the agent is the
    # notification system's standing behavior, not a report.)
    assert [
        row for row in _outbox(db) if row.kind == "warranty_claim_report"
    ] == []


def test_warranty_create_auto_reports_to_agent_email(
    client, db, owner, dealer_user
):
    """REVISED 2026-10-31 (was: auto_reports_by_email_and_notice,
    which emailed the COMPANY + noticed its representatives).
    Under agent scope the report goes to the AGENT: here the
    owner's agent on record is a private record with an email —
    the report lands there, the claim is reported/system, and
    the company's own inbox (and every other company seat) gets
    nothing at all."""
    company = _company(db, email="service@acme.example")
    _represent(db, company, dealer_user, verified=True)
    agent = dealer_models.PrivateAgent(
        owner_id=owner.id,
        company_id=company.id,
        name="Pat Private",
        email="pat@agent.example",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    pref = dealer_models.PreferredAgent(
        user_id=owner.id, company_id=company.id, private_agent_id=agent.id
    )
    db.add(pref)
    db.commit()
    tool = _tool(db, owner, dealer_company_id=company.id)

    response = _warranty(client, owner, "tool", tool.id, dealer_notified=False)
    assert response.status_code == 201, response.text
    body = response.json()
    claim = body["claim"]
    assert claim["status"] == "reported"
    assert claim["report_method"] == "system"
    assert body["reported"] is True
    assert body["report_via"] == ["email"]
    # The AGENT's email got the report; the company's did not.
    sent = _outbox(db, "pat@agent.example")
    assert len(sent) == 1
    assert sent[0].kind == "warranty_claim_report"
    assert claim["claim_number"] in sent[0].subject
    assert _outbox(db, "service@acme.example") == []
    # No inbox notice to the company's verified representative —
    # the claim isn't routed to them.
    assert _notifications(db, dealer_user, "warranty_claim_new") == []
    # And the claim names the private agent as its agent.
    assert claim["warranty_agent"]["kind"] == "private"
    assert claim["warranty_agent"]["name"] == "Pat Private"


def test_warranty_create_no_route_stays_not_reported(client, db, owner):
    tool = _tool(db, owner)  # no dealer tag at all
    response = _warranty(client, owner, "tool", tool.id, dealer_notified=False)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["claim"]["status"] == "not_reported"
    assert body["claim"]["report_method"] == ""
    assert body["reported"] is False
    assert body["report_via"] == []
    assert _outbox(db) == []


def test_warranty_create_offsystem_dealer_owner_drives_by_hand(
    client, db, owner
):
    # A dealer with no email and no on-system agents: nothing can
    # be sent, so the claim waits — and the owner walks the
    # ladder by hand, the off-system posture.
    company = _company(db, is_directory=False)
    tool = _tool(db, owner, dealer_company_id=company.id)
    response = _warranty(client, owner, "tool", tool.id, dealer_notified=False)
    claim = response.json()["claim"]
    assert claim["status"] == "not_reported"
    assert claim["dealer_name"] == company.name

    moved = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "reported"},
        headers=auth_headers(owner),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "reported"
    assert moved.json()["report_method"] == "user"
    assert moved.json()["reported_at"] is not None


def test_second_open_warranty_claim_on_same_target_refused(
    client, db, owner
):
    tool = _tool(db, owner)
    first = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    assert first.status_code == 201, first.text
    number = first.json()["claim"]["claim_number"]
    second = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    assert second.status_code == 422, second.text
    assert number in second.json()["detail"]


# -- piece claims carry both numbers --------------------------------------------


def test_piece_claim_carries_piece_and_set_model_numbers(
    client, db, owner, dealer_user
):
    company = _company(db, email="parts@acme.example")
    # Agent scope (2026-10-31): the dealer user is the owner's
    # assigned, verified agent — the seat that sees the claim.
    _represent(db, company, dealer_user, verified=True)
    _prefer(db, owner, company, dealer_user)
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

    response = _warranty(client, owner, "piece", piece.id, dealer_notified=False)
    assert response.status_code == 201, response.text
    claim = response.json()["claim"]
    (line,) = claim["lines"]
    assert line["target_kind"] == "piece"
    assert line["target_name"] == "10mm socket"
    assert line["set_name"] == "Master Socket Set"
    assert line["target_part_number"] == "84-123"
    assert line["set_model_number"] == "KRL1033"
    # The piece prices from its own recorded price.
    assert line["amount"] == "12.50"

    # The set's own page corner names the piece AND both numbers.
    refs = client.get(
        f"/api/claims/for-item/tool/{tool_set.id}", headers=auth_headers(owner)
    ).json()
    assert len(refs["current"]) == 1
    (named,) = refs["current"][0]["items"]
    assert "10mm socket" in named
    assert "84-123" in named
    assert "KRL1033" in named

    # The assigned agent's incoming row carries the claim too.
    incoming = client.get(
        "/api/claims/incoming", headers=auth_headers(dealer_user)
    ).json()
    assert [row["id"] for row in incoming] == [claim["id"]]
    # REVISED 2026-10-31: the company email is never a report
    # target under agent scope (the agent got the inbox notice
    # instead). The both-numbers report EMAIL — now addressed to
    # a private agent's email on record — is pinned in
    # test_claims_agent_scope.py.
    assert _outbox(db, "parts@acme.example") == []
    notes = _notifications(db, dealer_user, "warranty_claim_new")
    assert len(notes) == 1


# -- the dealer side drives it too ------------------------------------------------


def test_dealer_side_views_and_moves_notify_both_ways(
    client, db, owner, dealer_user, stranger
):
    company = _company(db)
    _represent(db, company, dealer_user, verified=True)
    _prefer(db, owner, company, dealer_user)
    tool = _tool(db, owner, dealer_company_id=company.id)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]

    # The dealer opens the claim from their seat.
    view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(dealer_user)
    )
    assert view.status_code == 200, view.text
    assert view.json()["viewer_role"] == "dealer"
    assert view.json()["owner_name"] == owner.name
    assert "in_repair" in view.json()["allowed_transitions"]
    assert "closed" not in view.json()["allowed_transitions"]

    # A stranger sees nothing — not even that it exists.
    denied = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(stranger)
    )
    assert denied.status_code == 404

    # The dealer moves it; the owner hears about it.
    moved = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "in_repair"},
        headers=auth_headers(dealer_user),
    )
    assert moved.status_code == 200, moved.text
    owner_notes = _notifications(db, owner, "warranty_claim_update")
    assert len(owner_notes) == 1
    # Ryan's status words (2026-11-05) name the move.
    assert "tool sent in for repairs" in owner_notes[0].body

    # The owner writes in the shared log; the dealer hears, and
    # the entry says who wrote it.
    db.expunge_all()
    before = len(_notifications(db, dealer_user, "warranty_claim_update"))
    logged = client.post(
        f"/api/claims/{claim['id']}/communications",
        json={"channel": "portal", "contact": "", "summary": "Any update?"},
        headers=auth_headers(owner),
    )
    assert logged.status_code == 201, logged.text
    assert logged.json()["author_role"] == "owner"
    assert logged.json()["author_name"] == owner.name
    after = _notifications(db, dealer_user, "warranty_claim_update")
    assert len(after) == before + 1


def test_warranty_ladder_refuses_illegal_moves(client, db, owner, dealer_user):
    # No dealer anywhere: the claim starts unreported.
    tool = _tool(db, owner)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=False)
    claim = created.json()["claim"]
    assert claim["status"] == "not_reported"

    # The ladder is FREE-FORM since the claims overhaul
    # (2026-11-06, owner's order): not_reported CAN jump straight
    # to completed — every status reaches every other. What stays
    # refused: staying put, and another kind's statuses.
    skip = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "completed"},
        headers=auth_headers(owner),
    )
    assert skip.status_code == 200, skip.text
    assert skip.json()["status"] == "completed"
    stays = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "completed"},
        headers=auth_headers(owner),
    )
    assert stays.status_code == 422, stays.text
    foreign = client.post(
        f"/api/claims/{claim['id']}/transition",
        json={"to_status": "filed"},
        headers=auth_headers(owner),
    )
    assert foreign.status_code == 422, foreign.text

    # An assigned agent can't close a claim — closing is the
    # owner's call.
    company = _company(db)
    _represent(db, company, dealer_user, verified=True)
    _prefer(db, owner, company, dealer_user)
    tagged = _tool(db, owner, dealer_company_id=company.id)
    reported = _warranty(client, owner, "tool", tagged.id, dealer_notified=True)
    other_claim = reported.json()["claim"]
    assert other_claim["status"] == "reported"
    closed_by_dealer = client.post(
        f"/api/claims/{other_claim['id']}/transition",
        json={"to_status": "closed"},
        headers=auth_headers(dealer_user),
    )
    assert closed_by_dealer.status_code == 422, closed_by_dealer.text

    # The owner CAN close — and closing is a layer, not a status
    # (2026-11-06): the status survives, closed_at stamps, and a
    # closed claim refuses every further move.
    closed = client.post(
        f"/api/claims/{other_claim['id']}/transition",
        json={"to_status": "closed"},
        headers=auth_headers(owner),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "reported"
    assert closed.json()["closed_at"] is not None
    after_close = client.post(
        f"/api/claims/{other_claim['id']}/transition",
        json={"to_status": "in_repair"},
        headers=auth_headers(owner),
    )
    assert after_close.status_code == 422, after_close.text


def test_insurance_flow_unchanged_beside_warranty(client, owner):
    created = client.post(
        "/api/disaster-claims", json={}, headers=auth_headers(owner)
    )
    claim = created.json()
    filed = client.post(
        f"/api/disaster-claims/{claim['id']}/transition",
        json={"to_status": "filed"},
        headers=auth_headers(owner),
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["kind"] == "insurance_disaster"


def test_package_refuses_a_warranty_claim(client, db, owner):
    tool = _tool(db, owner)
    created = _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    claim = created.json()["claim"]
    # Claims separation (2026-11-05): the package lives in the
    # Disaster Claims section, and a warranty claim addressed
    # there is a 404 — the sections never serve each other's
    # claims. (Pre-separation this was a 422 on /api/claims.)
    response = client.get(
        f"/api/disaster-claims/{claim['id']}/package",
        headers=auth_headers(owner),
    )
    assert response.status_code == 404, response.text


def test_stats_count_open_warranty_claims(client, db, owner):
    tool = _tool(db, owner)
    _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    stats = client.get("/api/claims/stats", headers=auth_headers(owner)).json()
    assert stats["open_claims_count"] == 1


# -- replace: the retired state ----------------------------------------------------


def test_replace_same_item_clones_with_spent_amount(
    client, db, owner
):
    tool = _tool(
        db,
        owner,
        name="Impact wrench",
        brand="Matco",
        model="MT2779",
        purchase_price="300.00",
        purchase_date=date(2020, 1, 15),
    )
    response = client.post(
        "/api/claims/replace-item",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "mode": "same",
            "amount_spent": "15.00",
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    new_id = body["new_item"]["id"]
    assert body["retired_id"] == str(tool.id)
    assert new_id != str(tool.id)

    fresh = client.get(f"/api/inventory/{new_id}", headers=auth_headers(owner))
    assert fresh.status_code == 200, fresh.text
    fresh = fresh.json()
    assert fresh["brand"] == "Matco"
    assert fresh["model"] == "MT2779"
    assert fresh["purchase_price"] == "15.00"
    assert fresh["purchase_date"] == date.today().isoformat()

    # The old record: retired standing, swap marker stamped, and
    # still readable on its own page.
    old = client.get(f"/api/inventory/{tool.id}", headers=auth_headers(owner))
    assert old.status_code == 200, old.text
    old = old.json()
    assert old["standing"] == "replaced"
    assert old["replaced_by_item_id"] == new_id
    assert old["replaced_on"] == date.today().isoformat()

    # Out of the active cap and the inventory stream; present in
    # reports, labelled Replaced.
    assert entitlements.asset_count(db, owner.id) == 1
    stream = client.get(
        "/api/inventory/search/all", headers=auth_headers(owner)
    ).json()
    assert [row["id"] for row in stream] == [new_id]
    report = client.post(
        "/api/reports/run",
        json={"columns": ["name", "repair_status"]},
        headers=auth_headers(owner),
    )
    assert report.status_code == 200, report.text
    rows = [r for g in report.json()["groups"] for r in g["rows"]]
    statuses = sorted(
        r["values"]["repair_status"]
        for r in rows
        if r["values"]["name"] == "Impact wrench"
    )
    assert statuses == ["In service", "Replaced"]


def test_replace_different_retires_without_cloning(client, db, owner):
    tool = _tool(db, owner)
    response = client.post(
        "/api/claims/replace-item",
        json={"item_kind": "tool", "item_id": str(tool.id), "mode": "different"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_item"] is None
    db.refresh(tool)
    assert tool.standing == "replaced"
    assert entitlements.asset_count(db, owner.id) == 0


def test_replace_refused_while_a_claim_is_open(client, db, owner):
    tool = _tool(db, owner)
    _warranty(client, owner, "tool", tool.id, dealer_notified=True)
    response = client.post(
        "/api/claims/replace-item",
        json={"item_kind": "tool", "item_id": str(tool.id), "mode": "same"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422, response.text
    db.refresh(tool)
    assert tool.standing != "replaced"
