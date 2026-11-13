"""Asset history timeline (owner spec 2026-10-20).

Every asset shows its life story on its detail page: purchased,
repaired (warranty repairs named as such), lent/returned,
claimed, lost/recovered, replaced — one feed merged from
per-module providers registered into inventory's history
registry (the billing pin-provider pattern).

Pinned here:
- the inventory events (created / purchased-on-its-own-date /
  journal milestones with noise filtered / standing transitions
  that no module record covers, told ONCE);
- the maintenance, borrowing, claims, dealers providers;
- the replaced marker: payload fields, both directions of the
  story, un-replace, validation, and the deliberate rule that a
  replaced item STAYS in the active set;
- owner scoping (foreign id = 404 everywhere);
- the provider-registry seam wave 2 registers into.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import history as inventory_history
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types=(MECHANIC,), *, name="Hist Owner"):
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
    return _make_user(db, "TV-M-002001", "hist-owner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-002002", "hist-other@example.com")


def _tool(client, user, **payload):
    payload.setdefault("name", "Story wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Story pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _events(client, user, kind, item_id):
    segment = "tools" if kind == "tool" else "batteries"
    resp = client.get(
        f"/api/inventory/{segment}/{item_id}/history", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def _titles(events):
    return [e["title"] for e in events]


# -- inventory's own events ---------------------------------------------------


def test_created_and_purchased_on_the_purchase_date(client, owner):
    tool = _tool(
        client,
        owner,
        purchase_date="2024-01-15",
        purchase_price="250.00",
    )
    events = _events(client, owner, "tool", tool["id"])
    kinds = [e["kind"] for e in events]
    assert kinds == ["created", "purchased"]  # newest first
    purchased = events[1]
    assert purchased["title"] == "Purchased"
    assert purchased["ts"].startswith("2024-01-15")
    assert "250" in purchased["detail"]

    bare = _tool(client, owner, name="No dates")
    events = _events(client, owner, "tool", bare["id"])
    assert [e["kind"] for e in events] == ["created"]


def test_journal_milestone_and_attachment_noise(client, db, owner):
    tool = _tool(client, owner, name="Old name")
    resp = client.put(
        f"/api/inventory/{tool['id']}",
        json={"name": "New name"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    events = _events(client, owner, "tool", tool["id"])
    edited = [e for e in events if e["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["title"] == "Changed tool 'New name'"

    # Attachment REORDER (same files, new sequence) is trivia:
    # no new milestone. ADDING a file is a real edit: one more.
    record = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    first = {"key": "k1", "filename": "a.jpg", "kind": "photo"}
    second = {"key": "k2", "filename": "b.jpg", "kind": "photo"}
    record.attachments = [first, second]
    db.commit()
    baseline = len(
        [e for e in _events(client, owner, "tool", tool["id"]) if e["kind"] == "edited"]
    )
    assert baseline == 2  # the add itself was a real edit
    record.attachments = [second, first]
    db.commit()
    events = _events(client, owner, "tool", tool["id"])
    assert (
        len([e for e in events if e["kind"] == "edited"]) == baseline
    ), "a photo reorder must not add a milestone"


# -- maintenance provider -------------------------------------------------------


def test_repair_story_break_send_fix(client, db, owner):
    # Merge (2026-11-04): the repair story is told by the CLAIM —
    # the claims history provider carries the filing and the
    # ladder milestones, with the repair facts (sent-to, cost)
    # riding the milestone details. The retired repair-record
    # titles ("Reported broken", "In repair", "Repaired") never
    # appear.
    tool = _tool(client, owner)
    # Determinism (the a61b962 pattern): the feed sorts newest
    # first and same-timestamp events keep provider order with
    # inventory first — so when the tool's birth and the claim
    # milestones land in the same tick, "Added to inventory"
    # wins the tie and the story-above-creation assertion below
    # coin-flips. Backdate the seeded tool's birth so the claim
    # events are strictly newer, by construction.
    record = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    record.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": tool["id"],
            "dealer_notified": False,
            "problem": "Cracked handle",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    claim = resp.json()["claim"]
    number = claim["claim_number"]

    titles = _titles(_events(client, owner, "tool", tool["id"]))
    assert f"Claim {number} filed" in titles
    assert "Reported broken — Cracked handle" not in titles
    assert "Repaired" not in titles

    def _move(to_status, **extra):
        resp = client.post(
            f"/api/claims/{claim['id']}/transition",
            json={"to_status": to_status, **extra},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    _move("reported")
    _move("in_repair", repair_sent_to="Snap-on truck")
    events = _events(client, owner, "tool", tool["id"])
    in_repair = next(e for e in events if e["title"] == f"Claim {number} in_repair")
    assert "Snap-on truck" in in_repair["detail"]

    _move("completed", repair_cost="85.50")
    events = _events(client, owner, "tool", tool["id"])
    titles = _titles(events)
    completed = next(e for e in events if e["title"] == f"Claim {number} completed")
    assert "85.50" in completed["detail"]
    assert "Snap-on truck" in completed["detail"]
    # Newest first: the whole claim story sits above the item's
    # own creation event. (The milestones share a second, so
    # their order among themselves is not asserted.)
    assert titles.index(f"Claim {number} completed") < titles.index(
        "Added to inventory"
    )


def test_schedule_log_entry_is_a_service_event(client, owner):
    tool = _tool(client, owner)
    resp = client.post(
        f"/api/maintenance/items/tool/{tool['id']}/schedules",
        json={"kind": "calibration", "label": "Annual cal", "interval_days": 365},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    schedule = resp.json()
    resp = client.post(
        f"/api/maintenance/schedules/{schedule['id']}/log",
        json={
            "done_date": "2026-09-01",
            "cost": "45.00",
            "technician": "Cal Lab",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    events = _events(client, owner, "tool", tool["id"])
    service = next(e for e in events if e["kind"] == "service")
    assert service["title"] == "Calibration done"
    assert service["ts"].startswith("2026-09-01")
    assert "Annual cal" in service["detail"]
    assert "Cal Lab" in service["detail"]


def test_set_page_carries_piece_repairs(client, owner):
    # Merge (2026-11-04): a piece's repair is its own warranty
    # claim; the claim lands on the SET's history (the set is the
    # asset) with the piece named in the detail.
    tool = _tool(
        client,
        owner,
        name="Socket set",
        is_set=True,
        pieces=[
            {"kind": "core", "name": "10mm socket", "part_number": "S-10"},
        ],
    )
    piece = tool["set"]["core_pieces"][0]
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "piece",
            "target_id": piece["id"],
            "dealer_notified": False,
            "problem": "Rounded flats",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    claim = resp.json()["claim"]
    events = _events(client, owner, "tool", tool["id"])
    filed = next(
        e for e in events if e["title"] == f"Claim {claim['claim_number']} filed"
    )
    assert "10mm socket" in filed["detail"]


# -- borrowing provider -----------------------------------------------------------


def test_lending_story(client, owner):
    tool = _tool(client, owner)
    resp = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": tool["id"],
            "borrower_name": "Sam Neighbor",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    checkout = resp.json()
    titles = _titles(_events(client, owner, "tool", tool["id"]))
    assert "Lent to Sam Neighbor" in titles

    resp = client.post(
        f"/api/borrowing/{checkout['id']}/return",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    events = _events(client, owner, "tool", tool["id"])
    titles = _titles(events)
    assert "Returned" in titles
    assert titles.index("Returned") < titles.index("Lent to Sam Neighbor")


# -- claims provider ---------------------------------------------------------------


def test_claim_story_with_milestones(client, owner):
    tool = _tool(
        client, owner, purchase_price="300.00", replacement_cost="300.00"
    )
    resp = client.post(
        "/api/disaster-claims",
        json={"insurer_name": "Acme Mutual", "incident_type": "theft"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    claim = resp.json()
    resp = client.post(
        f"/api/disaster-claims/{claim['id']}/lines",
        json={
            "target_kind": "tool",
            "target_id": tool["id"],
            # Claim money is purchase cost (ruling 2026-11-06).
            "value_basis": "purchase",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text
    for step in ("filed", "in_review", "approved"):
        resp = client.post(
            f"/api/disaster-claims/{claim['id']}/transition",
            json={"to_status": step},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200, resp.text
    events = _events(client, owner, "tool", tool["id"])
    claim_events = [e for e in events if e["kind"] == "claim"]
    titles = _titles(claim_events)
    number = claim["claim_number"]
    assert f"Claim {number} filed" in titles
    assert f"Claim {number} approved" in titles
    assert all(e["link"] == f"/disaster-claims/{claim['id']}" for e in claim_events)
    filed = next(e for e in claim_events if e["title"].endswith("filed"))
    assert "Acme Mutual" in filed["detail"]


# -- loss reports (inventory) + uncovered standing changes -------------------------


def test_loss_story_without_duplicate_standing_event(client, owner):
    tool = _tool(client, owner)
    resp = client.post(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        json={
            "standing": "stolen",
            "reported_date": "2026-10-01",
            "police_report_number": "26-1042",
            "police_department": "Morrison County Sheriff",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    report = resp.json()
    events = _events(client, owner, "tool", tool["id"])
    lost = next(e for e in events if e["kind"] == "lost")
    assert lost["title"] == "Reported stolen"
    assert lost["ts"].startswith("2026-10-01")
    assert "26-1042" in lost["detail"]
    assert "Marked stolen" not in _titles(events)

    resp = client.post(
        f"/api/inventory/loss-reports/{report['id']}/recover",
        json={"recovered_date": "2026-10-12"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    events = _events(client, owner, "tool", tool["id"])
    recovered = next(e for e in events if e["kind"] == "recovered")
    assert recovered["ts"].startswith("2026-10-12")


def test_bulk_standing_mark_still_lands_in_the_story(client, owner):
    # A bulk mark creates NO repair/loss record — the journal
    # standing transition is the only telling, and it survives.
    tool = _tool(client, owner)
    resp = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": "tool", "id": tool["id"]}],
            "action": "set_standing",
            "params": {"standing": "lost"},
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    titles = _titles(_events(client, owner, "tool", tool["id"]))
    assert "Marked lost" in titles


# -- dealers provider: the warranty repair naming -----------------------------------


def test_warranty_repair_and_dealer_events(client, db, owner):
    from app.modules.dealers import models as dealer_models
    from app.modules.dealers import warranty as dealers_warranty

    company = dealer_models.DealerCompany(
        id=uuid.uuid4(), name="Matco Tools", is_directory=True
    )
    db.add(company)
    agent = _make_user(
        db, "TV-D-002003", "hist-agent@example.com",
        account_types=(DEALER,), name="Agent Amy",
    )
    db.add(
        dealer_models.CompanyRepresentation(
            id=uuid.uuid4(), company_id=company.id, agent_user_id=agent.id
        )
    )
    db.commit()

    tool = _tool(client, owner, dealer_company_id=str(company.id))
    # Merge (2026-11-04): the warranty request rides the CLAIM.
    resp = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": tool["id"],
            "dealer_notified": False,
            "problem": "Ratchet slips",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    claim = resp.json()["claim"]

    request = dealers_warranty.send_request(db, owner, uuid.UUID(claim["id"]))
    dealers_warranty.claim(db, agent, request.id)
    dealers_warranty.set_status(db, agent, request.id, "in_process")
    dealers_warranty.set_status(db, agent, request.id, "resolved")

    # The repair completes on the claim itself.
    for to_status, extra in (
        ("reported", {}),
        ("in_repair", {"repair_sent_to": "Matco Tools"}),
        ("completed", {"repair_cost": "40.00"}),
    ):
        resp = client.post(
            f"/api/claims/{claim['id']}/transition",
            json={"to_status": to_status, **extra},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    events = _events(client, owner, "tool", tool["id"])
    titles = _titles(events)
    # The retired repair-record vocabulary never appears; the
    # completion is the claim's own milestone.
    assert "Warranty repaired" not in titles
    assert "Repaired" not in titles
    assert f"Claim {claim['claim_number']} completed" in titles
    # The dealers provider still tells the request's own story.
    warranty_titles = [e["title"] for e in events if e["kind"] == "warranty"]
    assert warranty_titles[0] == "Resolved"
    assert "Sent to Matco Tools for warranty" in warranty_titles
    assert any(t.startswith("Claimed by") for t in warranty_titles)
    assert "In process" in warranty_titles


# -- the replaced marker ------------------------------------------------------------


def test_replaced_flow_both_directions_and_stays_active(client, owner):
    old = _tool(client, owner, name="Old torque wrench")
    new = _tool(client, owner, name="New torque wrench")
    resp = client.post(
        f"/api/inventory/tools/{old['id']}/replaced",
        json={
            "replaced_on": "2026-08-01",
            "replaced_by_item_id": new["id"],
            "note": "Warranty swap",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    marked = resp.json()
    assert marked["replaced_on"] == "2026-08-01"
    assert marked["replaced_by_item_id"] == new["id"]
    assert marked["replaced_by_name"] == "New torque wrench"
    assert marked["replaced_note"] == "Warranty swap"
    # Deliberate: replaced items stay in the active set.
    assert marked["active"] is True
    listed = client.get("/api/inventory", headers=auth_headers(owner)).json()
    assert old["id"] in {row["id"] for row in listed}

    events = _events(client, owner, "tool", old["id"])
    replaced = next(e for e in events if e["kind"] == "replaced")
    assert replaced["title"] == "Replaced by New torque wrench"
    assert replaced["ts"].startswith("2026-08-01")
    assert replaced["link"] == f"/inventory/{new['id']}"
    assert replaced["detail"] == "Warranty swap"

    events = _events(client, owner, "tool", new["id"])
    reverse = next(e for e in events if e["kind"] == "replaced")
    assert reverse["title"] == "Replaced Old torque wrench"
    assert reverse["link"] == f"/inventory/{old['id']}"

    # Un-replace clears the marker AND the event.
    resp = client.delete(
        f"/api/inventory/tools/{old['id']}/replaced", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    cleared = resp.json()
    assert cleared["replaced_on"] is None
    assert cleared["replaced_by_item_id"] is None
    assert cleared["replaced_by_name"] is None
    assert cleared["replaced_note"] == ""
    events = _events(client, owner, "tool", old["id"])
    assert not [e for e in events if e["kind"] == "replaced"]


def test_replaced_defaults_to_today_and_validates(client, owner, other):
    tool = _tool(client, owner)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/replaced",
        json={"replaced_by_item_id": tool["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text  # can't replace itself

    foreign = _tool(client, other, name="Not yours")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/replaced",
        json={"replaced_by_item_id": foreign["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text  # replacement must be the owner's

    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/replaced",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["replaced_on"] == date.today().isoformat()


def test_battery_history_and_cross_kind_replacement(client, owner):
    battery = _battery(
        client, owner, purchase_date="2025-05-20", purchase_price="120.00"
    )
    tool = _tool(client, owner, name="Replacement kit")
    events = _events(client, owner, "battery", battery["id"])
    assert [e["kind"] for e in events] == ["created", "purchased"]

    resp = client.post(
        f"/api/inventory/batteries/{battery['id']}/replaced",
        json={"replaced_on": "2026-02-01", "replaced_by_item_id": tool["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["replaced_by_name"] == "Replacement kit"
    events = _events(client, owner, "battery", battery["id"])
    replaced = next(e for e in events if e["kind"] == "replaced")
    assert replaced["title"] == "Replaced by Replacement kit"
    assert replaced["link"] == f"/inventory/{tool['id']}"
    # The tool's story opens with what it replaced.
    events = _events(client, owner, "tool", tool["id"])
    reverse = next(e for e in events if e["kind"] == "replaced")
    assert reverse["title"] == f"Replaced {battery['name']}"
    assert reverse["link"] == f"/inventory/batteries/{battery['id']}"


# -- owner scoping ---------------------------------------------------------------------


def test_foreign_item_is_404_everywhere(client, owner, other):
    tool = _tool(client, owner)
    battery = _battery(client, owner)
    for kind, item_id, segment in (
        ("tool", tool["id"], "tools"),
        ("battery", battery["id"], "batteries"),
    ):
        resp = client.get(
            f"/api/inventory/{segment}/{item_id}/history",
            headers=auth_headers(other),
        )
        assert resp.status_code == 404, (kind, resp.text)
        resp = client.post(
            f"/api/inventory/{segment}/{item_id}/replaced",
            json={},
            headers=auth_headers(other),
        )
        assert resp.status_code == 404, (kind, resp.text)
        resp = client.delete(
            f"/api/inventory/{segment}/{item_id}/replaced",
            headers=auth_headers(other),
        )
        assert resp.status_code == 404, (kind, resp.text)
    # A missing id is the same 404 (no existence oracle).
    ghost = str(uuid.uuid4())
    resp = client.get(
        f"/api/inventory/tools/{ghost}/history", headers=auth_headers(owner)
    )
    assert resp.status_code == 404


# -- the provider registry seam (wave 2 registers sales the same way) -------------------


def test_provider_registry_seam(client, owner):
    tool = _tool(client, owner)

    def sale_provider(db, owner_id, item_kind, item_id):
        yield inventory_history.HistoryEvent(
            ts=inventory_history.day_start(date(2026, 1, 5)),
            kind="sold",
            title="Sold (test provider)",
        )

    inventory_history.register_history_provider("test_sales", sale_provider)
    try:
        assert "test_sales" in inventory_history.registered_providers()
        events = _events(client, owner, "tool", tool["id"])
        sold = next(e for e in events if e["kind"] == "sold")
        assert sold["title"] == "Sold (test provider)"
    finally:
        inventory_history.unregister_history_provider(sale_provider)
    events = _events(client, owner, "tool", tool["id"])
    assert not [e for e in events if e["kind"] == "sold"]


def test_old_item_predating_features_still_reads(client, db, owner):
    # An item with nothing but a created_at (the migration-era
    # shape): the feed answers with its birth, no provider noise.
    record = inventory_models.Tool(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Legacy hammer",
        created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    db.add(record)
    db.commit()
    events = _events(client, owner, "tool", str(record.id))
    assert [e["kind"] for e in events] == ["created"]
