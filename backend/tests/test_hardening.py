"""Hardening pass (2026-10-19, queue #15): the cross-cutting sweeps
no single module build could own.

- IDOR / ownership: every id-addressed surface added since the
  admin panel, attacked by a second user holding the SAME module
  access (so a module gate can never mask a missing owner check).
  Foreign ids must answer 404 — the same answer a random id gets,
  so existence never leaks — on read AND write paths, and the
  victim's data must be untouched afterwards.
- Abuse: upload validation at both gates (declared at issue time,
  real at attach time), double-submit races, degenerate signups.
- Export completeness: one of everything -> the ZIP diffed against
  the full checklist.
- Job seams: the three scheduler scripts execute and are
  idempotent on a second run.

Surfaces a module's own suite already pins (peer grants, reports
configs, importer sessions, dealer companies/agents) are not
re-litigated here except where the sweep reaches a sub-resource
those suites don't touch.
"""

import io
import uuid
import zipfile
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core import storage as storage_module
from app.core.storage import StorageError
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"
GROUPS = [MECHANIC, DEALER]

RANDOM_ID = uuid.UUID("12345678-1234-4234-9234-1234567890ab")


def _make_user(db, account_number, email, name):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(GROUPS),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def alice(db):
    return _make_user(db, "TV-MD-000901", "alice@example.com", "Alice Owner")


@pytest.fixture()
def bob(db):
    return _make_user(db, "TV-MD-000902", "bob@example.com", "Bob Bystander")


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


def _piece(db, owner, tool_set, name="10mm socket", **overrides):
    piece = inventory_models.SetPiece(
        owner_id=owner.id, set_id=tool_set.id, name=name, **overrides
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece


def _probe(client, user, method, url, **kwargs):
    """One foreign-id attack. Returns the response."""
    return getattr(client, method)(url, headers=auth_headers(user), **kwargs)


def _assert_404(resp, what):
    assert resp.status_code == 404, f"{what}: expected 404, got {resp.status_code}: {resp.text[:200]}"


# ---------------------------------------------------------------------
# Item 3 — IDOR: inventory (tools, batteries, pieces, tags, sets)
# ---------------------------------------------------------------------


def test_idor_inventory_resources(client, db, alice, bob):
    tool = _tool(db, alice, attachments=[])
    battery = _battery(db, alice)
    tool_set = _tool(db, alice, name="Socket Set", is_set=True)
    piece = _piece(db, alice, tool_set)
    tag_resp = client.post(
        "/api/inventory/tags",
        json={"name": "Alice tag", "color": "amber"},
        headers=auth_headers(alice),
    )
    assert tag_resp.status_code == 201, tag_resp.text
    tag = tag_resp.json()

    b = auth_headers(bob)
    # Tools: read / write / delete.
    _assert_404(client.get(f"/api/inventory/{tool.id}", headers=b), "GET tool")
    _assert_404(
        client.put(f"/api/inventory/{tool.id}", json={"name": "Hijacked"}, headers=b),
        "PUT tool",
    )
    _assert_404(client.delete(f"/api/inventory/{tool.id}", headers=b), "DELETE tool")
    # Batteries: read / write / delete.
    _assert_404(
        client.get(f"/api/inventory/batteries/{battery.id}", headers=b), "GET battery"
    )
    _assert_404(
        client.put(
            f"/api/inventory/batteries/{battery.id}",
            json={"name": "Hijacked"},
            headers=b,
        ),
        "PUT battery",
    )
    _assert_404(
        client.delete(f"/api/inventory/batteries/{battery.id}", headers=b),
        "DELETE battery",
    )
    # Set pieces: write / delete (a piece id names its owner's set).
    _assert_404(
        client.put(
            f"/api/inventory/pieces/{piece.id}",
            json={"name": "Hijacked"},
            headers=b,
        ),
        "PUT piece",
    )
    _assert_404(
        client.delete(f"/api/inventory/pieces/{piece.id}", headers=b), "DELETE piece"
    )
    # Set structure: attach Alice's loose tool to a set / detach it.
    # attach-to-set answers the house non-leaking 404 (deep audit
    # round 2, E-02 — it used to speak the validation taxonomy's
    # 422, which confirmed the set/tool exist in someone else's
    # vault). The IDOR property is INDISTINGUISHABILITY: a foreign
    # tool+set pair must answer exactly what a random pair
    # answers — same status, same detail — so existence never leaks.
    foreign = client.post(
        f"/api/inventory/{tool.id}/attach-to-set",
        json={"set_id": str(tool_set.id)},
        headers=b,
    )
    random_pair = client.post(
        f"/api/inventory/{RANDOM_ID}/attach-to-set",
        json={"set_id": str(RANDOM_ID)},
        headers=b,
    )
    assert foreign.status_code == random_pair.status_code == 404
    assert foreign.json() == random_pair.json() == {"detail": "Tool not found"}
    attached = client.post(
        f"/api/inventory/{tool.id}/attach-to-set",
        json={"set_id": str(tool_set.id)},
        headers=auth_headers(alice),
    )
    assert attached.status_code == 200, attached.text
    _assert_404(
        client.post(f"/api/inventory/{tool.id}/detach", headers=b),
        "detach",
    )
    # Tags: rename / delete.
    _assert_404(
        client.put(
            f"/api/inventory/tags/{tag['id']}", json={"name": "Hijacked"}, headers=b
        ),
        "PUT tag",
    )
    _assert_404(
        client.delete(f"/api/inventory/tags/{tag['id']}", headers=b), "DELETE tag"
    )

    # "Email this file" on Alice's attachment: Bob's attempt must be
    # refused exactly as a random item id is (the attachments
    # service's owner check), and must not produce an outbox row.
    key = f"{alice.id}/tools/{tool.id}/photo/pic.jpg"
    tool.attachments = [
        {
            "key": key,
            "filename": "pic.jpg",
            "kind": "photo",
            "content_type": "image/jpeg",
            "size_bytes": 10,
            "uploaded_at": "2026-10-01T00:00:00+00:00",
        }
    ]
    db.commit()
    foreign_mail = client.post(
        f"/api/inventory/{tool.id}/attachments/email",
        json={"key": key, "recipient": "bob@example.com"},
        headers=b,
    )
    random_mail = client.post(
        f"/api/inventory/{RANDOM_ID}/attachments/email",
        json={"key": key, "recipient": "bob@example.com"},
        headers=b,
    )
    assert foreign_mail.status_code == random_mail.status_code == 404
    assert foreign_mail.json() == random_mail.json()
    assert db.scalars(select(core_models.EmailOutbox)).all() == []

    # Alice's world is exactly as she left it.
    a = auth_headers(alice)
    assert client.get(f"/api/inventory/{tool.id}", headers=a).json()["name"] == (
        "Impact wrench"
    )
    assert (
        client.get(f"/api/inventory/batteries/{battery.id}", headers=a).json()["name"]
        == "M18 5.0 pack"
    )
    detail = client.get(f"/api/inventory/{tool_set.id}", headers=a).json()
    assert detail["set"]["core_pieces"][0]["name"] == "10mm socket"
    # Bob's detach also failed: Alice's tool is still an addon.
    addon_names = [t["name"] for t in detail["set"]["attached_tools"]]
    assert addon_names == ["Impact wrench"]
    tags = client.get("/api/inventory/tags", headers=a).json()
    assert [t["name"] for t in tags] == ["Alice tag"]


# ---------------------------------------------------------------------
# Item 3 — IDOR: borrowing actions by a non-party
# ---------------------------------------------------------------------


def test_idor_borrowing_actions(client, db, alice, bob):
    tool = _tool(db, alice)
    created = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "borrower_name": "Manual Mike",
        },
        headers=auth_headers(alice),
    )
    assert created.status_code == 201, created.text
    checkout_id = created.json()["id"]

    b = auth_headers(bob)
    # Bob is neither owner nor borrower: every action 404s, and so
    # does the per-item lending view of Alice's tool.
    for action in ("approve", "decline", "cancel", "return"):
        _assert_404(
            client.post(f"/api/borrowing/{checkout_id}/{action}", headers=b),
            f"checkout {action}",
        )
    _assert_404(
        client.get(f"/api/borrowing/items/tool/{tool.id}", headers=b),
        "item lending view",
    )
    # The lend is still checked out, untouched.
    view = client.get(
        f"/api/borrowing/items/tool/{tool.id}", headers=auth_headers(alice)
    ).json()
    assert view["current"]["id"] == checkout_id
    assert view["current"]["state"] == "checked_out"


# ---------------------------------------------------------------------
# Item 3 — IDOR: maintenance (standing, records, schedules)
# ---------------------------------------------------------------------


def test_idor_maintenance(client, db, alice, bob):
    tool = _tool(db, alice)
    battery = _battery(db, alice)
    a = auth_headers(alice)
    # Merge (2026-11-04): marking broken is the inventory bulk
    # standing write (the Actions menu's path); the repair itself
    # is a warranty CLAIM — Bob's probes aim at the standing read,
    # the claim's transitions, and the schedules that stayed.
    marked = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": "tool", "id": str(tool.id)}],
            "action": "set_standing",
            "params": {"standing": "broken"},
        },
        headers=a,
    )
    assert marked.status_code == 200, marked.text
    claim = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": "Cracked housing",
        },
        headers=a,
    )
    assert claim.status_code == 201, claim.text
    claim = claim.json()["claim"]
    schedule = client.post(
        f"/api/maintenance/items/battery/{battery.id}/schedules",
        json={"kind": "calibration", "label": "Annual cal", "interval_days": 365},
        headers=a,
    )
    assert schedule.status_code == 201, schedule.text
    schedule = schedule.json()

    b = auth_headers(bob)
    _assert_404(
        client.get(f"/api/maintenance/items/tool/{tool.id}", headers=b),
        "GET standing",
    )
    # Bob's bulk write against Alice's tool refuses the batch
    # (the bulk endpoint's whole-batch refusal is a 422, and the
    # standing stays Alice's).
    refused = client.post(
        "/api/inventory/bulk",
        json={
            "items": [{"kind": "tool", "id": str(tool.id)}],
            "action": "set_standing",
            "params": {"standing": "in_service"},
        },
        headers=b,
    )
    assert refused.status_code == 422, refused.text
    _assert_404(
        client.post(
            f"/api/claims/{claim['id']}/transition",
            json={"to_status": "reported"},
            headers=b,
        ),
        "claim transition",
    )
    _assert_404(
        client.get(f"/api/claims/{claim['id']}", headers=b),
        "claim read",
    )
    _assert_404(
        client.patch(
            f"/api/maintenance/schedules/{schedule['id']}",
            json={"label": "hijacked"},
            headers=b,
        ),
        "schedule patch",
    )
    _assert_404(
        client.post(
            f"/api/maintenance/schedules/{schedule['id']}/log",
            json={},
            headers=b,
        ),
        "schedule log",
    )
    _assert_404(
        client.delete(f"/api/maintenance/schedules/{schedule['id']}", headers=b),
        "schedule delete",
    )

    standing = client.get(f"/api/maintenance/items/tool/{tool.id}", headers=a).json()
    assert standing["state"] == "broken"
    assert "history" not in standing
    overview = client.get("/api/maintenance/overview", headers=a).json()
    assert len(overview["schedules"]) == 1
    assert overview["schedules"][0]["label"] == "Annual cal"


# ---------------------------------------------------------------------
# Item 3 — IDOR: claims and every sub-resource
# ---------------------------------------------------------------------


def test_idor_claims(client, db, alice, bob):
    from decimal import Decimal as _Dec

    tool = _tool(
        db, alice, name="Claimed wrench",
        purchase_price=_Dec("50.00"), replacement_cost=_Dec("50.00"),
    )
    tool.attachments = [
        {
            "key": f"{alice.id}/tools/{tool.id}/receipt/receipt.pdf",
            "filename": "receipt.pdf",
            "kind": "receipt",
            "content_type": "application/pdf",
            "size_bytes": 1234,
            "uploaded_at": "2026-10-01T00:00:00+00:00",
        }
    ]
    db.commit()
    from decimal import Decimal

    battery = _battery(
        db, alice,
        purchase_price=Decimal("75.00"), replacement_cost=Decimal("75.00"),
    )
    a = auth_headers(alice)

    claim = client.post("/api/disaster-claims", json={}, headers=a)
    assert claim.status_code == 201, claim.text
    claim = claim.json()
    cid = claim["id"]
    line = client.post(
        f"/api/disaster-claims/{cid}/lines",
        json={"target_kind": "battery", "target_id": str(battery.id)},
        headers=a,
    )
    assert line.status_code == 201, line.text
    line = line.json()
    tool_line = client.post(
        f"/api/disaster-claims/{cid}/lines",
        json={"target_kind": "tool", "target_id": str(tool.id)},
        headers=a,
    )
    assert tool_line.status_code == 201, tool_line.text
    evidence = client.post(
        f"/api/disaster-claims/{cid}/evidence",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "attachment_key": tool.attachments[0]["key"],
        },
        headers=a,
    )
    assert evidence.status_code == 201, evidence.text
    evidence = evidence.json()
    comm = client.post(
        f"/api/disaster-claims/{cid}/communications",
        json={"channel": "phone", "contact": "Adjuster Amy", "summary": "Intake."},
        headers=a,
    )
    assert comm.status_code == 201, comm.text
    comm = comm.json()

    b = auth_headers(bob)
    _assert_404(client.get(f"/api/disaster-claims/{cid}", headers=b), "GET claim")
    _assert_404(
        client.patch(f"/api/disaster-claims/{cid}", json={"insurer_name": "BobCo"}, headers=b),
        "PATCH claim",
    )
    _assert_404(client.delete(f"/api/disaster-claims/{cid}", headers=b), "DELETE claim")
    _assert_404(
        client.post(
            f"/api/disaster-claims/{cid}/transition", json={"to_status": "filed"}, headers=b
        ),
        "transition",
    )
    _assert_404(
        client.post(f"/api/disaster-claims/{cid}/proof-of-loss-sent", json={}, headers=b),
        "proof-of-loss-sent",
    )
    _assert_404(
        client.post(
            f"/api/disaster-claims/{cid}/lines",
            json={"target_kind": "tool", "target_id": str(tool.id)},
            headers=b,
        ),
        "add line",
    )
    _assert_404(
        client.delete(f"/api/disaster-claims/{cid}/lines/{line['id']}", headers=b),
        "delete line",
    )
    _assert_404(
        client.post(
            f"/api/disaster-claims/{cid}/evidence",
            json={
                "item_kind": "tool",
                "item_id": str(tool.id),
                "attachment_key": tool.attachments[0]["key"],
            },
            headers=b,
        ),
        "add evidence",
    )
    _assert_404(
        client.post(
            f"/api/disaster-claims/{cid}/evidence/upload-url",
            json={
                "filename": "x.pdf",
                "content_type": "application/pdf",
                "kind": "document",
                "size_bytes": 10,
            },
            headers=b,
        ),
        "evidence upload-url",
    )
    _assert_404(
        client.delete(f"/api/disaster-claims/{cid}/evidence/{evidence['id']}", headers=b),
        "delete evidence",
    )
    _assert_404(
        client.post(
            f"/api/disaster-claims/{cid}/communications",
            json={"channel": "email", "contact": "Bob", "summary": "forged"},
            headers=b,
        ),
        "add comm",
    )
    _assert_404(
        client.patch(
            f"/api/disaster-claims/{cid}/communications/{comm['id']}",
            json={"summary": "rewritten"},
            headers=b,
        ),
        "patch comm",
    )
    _assert_404(
        client.delete(f"/api/disaster-claims/{cid}/communications/{comm['id']}", headers=b),
        "delete comm",
    )

    detail = client.get(f"/api/disaster-claims/{cid}", headers=a).json()
    assert detail["status"] == "draft"
    assert len(detail["lines"]) == 2
    assert len(detail["evidence"]) == 1
    assert len(detail["communications"]) == 1
    assert detail["communications"][0]["summary"] == "Intake."


# ---------------------------------------------------------------------
# Item 3 — IDOR: dealers (preferred rows, representations, links)
# ---------------------------------------------------------------------


def test_idor_dealers_private_world(client, db, alice, bob):
    a = auth_headers(alice)
    company = client.post(
        "/api/dealers/companies",
        json={"name": "Alice Local Co", "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=a,
    )
    assert company.status_code == 201, company.text
    company = company.json()
    agent = client.post(
        "/api/dealers/agents/private",
        json={"name": "Alice's Dan", "company_id": company["id"], "phone": "", "email": "", "notes": ""},
        headers=a,
    )
    assert agent.status_code == 201, agent.text
    agent = agent.json()
    preferred = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "private_agent_id": agent["id"]},
        headers=a,
    )
    assert preferred.status_code == 201, preferred.text
    preferred = preferred.json()

    # A directory company (platform data) + Alice's representation of it.
    from app.modules.dealers import models as dealers_models

    dir_company = dealers_models.DealerCompany(
        id=uuid.uuid4(), name="Big Brand Tools", is_directory=True
    )
    db.add(dir_company)
    db.commit()
    rep = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": str(dir_company.id)},
        headers=a,
    )
    assert rep.status_code == 201, rep.text
    rep = rep.json()

    b = auth_headers(bob)
    # Alice's private company detail (carries her agents/preferences).
    _assert_404(
        client.get(f"/api/dealers/companies/{company['id']}/detail", headers=b),
        "private company detail",
    )
    # Her preferred row: Bob can't remove it.
    _assert_404(
        client.delete(f"/api/dealers/preferred/{preferred['id']}", headers=b),
        "delete preferred",
    )
    # Her private agent: Bob can't link it to a platform account or unlink it.
    _assert_404(
        client.post(
            f"/api/dealers/agents/private/{agent['id']}/link",
            json={"agent_account_number": bob.account_number},
            headers=b,
        ),
        "link private agent",
    )
    _assert_404(
        client.post(f"/api/dealers/agents/private/{agent['id']}/unlink", headers=b),
        "unlink private agent",
    )
    # Her representation: Bob deleting it under HIS profile must 404
    # (the route is self-scoped; her rep id doesn't exist there).
    _assert_404(
        client.delete(f"/api/dealers/profile/me/representations/{rep['id']}", headers=b),
        "delete representation",
    )
    # Bob's own views stay empty of Alice's private world.
    assert client.get("/api/dealers/agents/private", headers=b).json() == []
    assert client.get("/api/dealers/preferred", headers=b).json() == []

    mine = client.get("/api/dealers/preferred", headers=a).json()
    assert len(mine) == 1
    reps = client.get("/api/dealers/profile/me/representations", headers=a).json()
    assert len(reps) == 1


# ---------------------------------------------------------------------
# Item 3 — IDOR: core leftovers (sessions, notifications) + billing
# ---------------------------------------------------------------------


def test_idor_sessions_and_notifications(client, db, alice, bob):
    from app.modules.core import models as core_models

    from datetime import datetime, timezone

    token = core_models.RefreshToken(
        user_id=alice.id,
        token_hash="a" * 64,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(token)
    note = core_models.Notification(
        user_id=alice.id,
        kind="test",
        title="For Alice",
        body="private",
        data={},
    )
    db.add(note)
    db.commit()
    db.refresh(token)
    db.refresh(note)

    b = auth_headers(bob)
    _assert_404(
        client.delete(f"/api/core/sessions/{token.id}", headers=b),
        "delete foreign session",
    )
    _assert_404(
        client.post(f"/api/core/notifications/{note.id}/read", headers=b),
        "read foreign notification",
    )
    # Alice's session + unread notification survive.
    sessions = client.get("/api/core/sessions", headers=auth_headers(alice)).json()
    assert any(s["id"] == str(token.id) for s in sessions)
    notes = client.get("/api/core/notifications", headers=auth_headers(alice)).json()
    assert any(n["id"] == str(note.id) and not n["read"] for n in notes)


def test_billing_customer_state_is_self_scoped(client, db, alice, bob):
    alice.stripe_customer_id = "cus_alice_only"
    db.commit()
    mine = client.get("/api/billing/me", headers=auth_headers(alice)).json()
    assert mine["has_stripe_customer"] is True
    theirs = client.get("/api/billing/me", headers=auth_headers(bob)).json()
    assert theirs["has_stripe_customer"] is False


# ---------------------------------------------------------------------
# Item 4 — abuse: upload validation at both gates
# ---------------------------------------------------------------------


def _stub_storage(monkeypatch, head):
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    monkeypatch.setattr(storage_module.storage, "head", head)


def test_upload_abuse_matrix(client, db, alice, monkeypatch):
    # Signing is stubbed from the start (the API never touches
    # storage before declarations validate, so the refusal cases
    # below still exercise the real validation path).
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    tool = _tool(db, alice)
    a = auth_headers(alice)
    url = f"/api/inventory/{tool.id}/upload-url"

    def issue(**body):
        return client.post(url, json=body, headers=a)

    # Declared-type lies are refused at issue time: an executable or
    # a PDF offered as a PHOTO (photo kind is images only).
    for bad_type in ("application/x-msdownload", "application/pdf", "text/html"):
        resp = issue(
            filename="evil.png", content_type=bad_type, kind="photo", size_bytes=100
        )
        assert resp.status_code == 422, (bad_type, resp.text)
    # Declared oversize is refused at issue time.
    resp = issue(
        filename="big.jpg",
        content_type="image/jpeg",
        kind="photo",
        size_bytes=10 * 1024 * 1024 + 1,
    )
    assert resp.status_code == 422
    resp = issue(
        filename="big.pdf",
        content_type="application/pdf",
        kind="document",
        size_bytes=25 * 1024 * 1024 + 1,
    )
    assert resp.status_code == 422
    # Exactly at the cap is fine (the boundary is the cap, not below it).
    ok = issue(
        filename="max.jpg",
        content_type="image/jpeg",
        kind="photo",
        size_bytes=10 * 1024 * 1024,
    )
    assert ok.status_code == 200, ok.text
    key = ok.json()["key"]

    # Attach gate: what's really in storage disagrees with the
    # declaration — an executable's content type under a photo key.
    _stub_storage(
        monkeypatch,
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=100, content_type="application/x-msdownload"
        ),
    )
    resp = client.post(
        f"/api/inventory/{tool.id}/attachments",
        json={"key": key, "filename": "evil.png"},
        headers=a,
    )
    assert resp.status_code == 422, resp.text
    # Attach gate: the stored object is really oversize.
    _stub_storage(
        monkeypatch,
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=11 * 1024 * 1024, content_type="image/jpeg"
        ),
    )
    resp = client.post(
        f"/api/inventory/{tool.id}/attachments",
        json={"key": key, "filename": "big.jpg"},
        headers=a,
    )
    assert resp.status_code == 422, resp.text
    # Attach gate: a key under ANOTHER user's prefix never attaches
    # to Alice's item (and the real-size check passes, so the prefix
    # refusal is what fires).
    bob = _make_user(db, "TV-MD-000902", "bob@example.com", "Bob Bystander")
    foreign_key = f"{bob.id}/tools/{tool.id}/photo/stolen.jpg"
    _stub_storage(
        monkeypatch,
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=100, content_type="image/jpeg"
        ),
    )
    resp = client.post(
        f"/api/inventory/{tool.id}/attachments",
        json={"key": foreign_key, "filename": "stolen.jpg"},
        headers=a,
    )
    assert resp.status_code == 422, resp.text
    # Nothing landed on the tool through any of it.
    detail = client.get(f"/api/inventory/{tool.id}", headers=a).json()
    assert detail["attachments"] == []


# ---------------------------------------------------------------------
# Item 4 — abuse: double-submits
# ---------------------------------------------------------------------


def test_double_submit_checkout_creates_one_active_lend(client, db, alice):
    from app.modules.borrowing import models as borrowing_models

    tool = _tool(db, alice)
    a = auth_headers(alice)
    body = {
        "item_kind": "tool",
        "item_id": str(tool.id),
        "borrower_name": "Manual Mike",
    }
    first = client.post("/api/borrowing/checkouts", json=body, headers=a)
    assert first.status_code == 201, first.text
    second = client.post("/api/borrowing/checkouts", json=body, headers=a)
    assert second.status_code == 422, second.text
    rows = db.scalars(
        select(borrowing_models.Checkout).where(
            borrowing_models.Checkout.item_id == tool.id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].state == "checked_out"


def test_claim_double_post_gets_distinct_numbers(client, db, alice):
    a = auth_headers(alice)
    one = client.post("/api/disaster-claims", json={}, headers=a)
    two = client.post("/api/disaster-claims", json={}, headers=a)
    assert one.status_code == two.status_code == 201
    assert one.json()["claim_number"] != two.json()["claim_number"]


def test_claim_number_collision_retries_instead_of_erroring(client, db, alice, monkeypatch):
    """The race the unique constraint creates: two creates read the
    same max; the loser's commit hits the number unique
    constraint. The
    service must recompute and succeed — simulated by making the
    number picker hand back an already-committed number once."""
    from app.modules.claims import service as claims_service

    first = claims_service.create_claim(db, alice)
    real_picker = claims_service._next_number
    calls = {"n": 0}

    def colliding_picker(db_, owner_id, kind):
        calls["n"] += 1
        if calls["n"] == 1:
            return (first.claim_number, first.claim_year, first.number_seq)
        return real_picker(db_, owner_id, kind)

    monkeypatch.setattr(claims_service, "_next_number", colliding_picker)
    second = claims_service.create_claim(db, alice)
    assert second.number_seq == first.number_seq + 1
    assert second.claim_number != first.claim_number


# ---------------------------------------------------------------------
# Item 4 — abuse: degenerate signups rejected cleanly (4xx, no 500)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},  # everything missing
        {"email": "not-an-email", "name": "X", "password": "secret1", "account_types": ["mechanic_technician"]},
        {"email": "ok@example.com", "name": "", "password": "secret1", "account_types": ["mechanic_technician"]},
        {"email": "ok@example.com", "name": "N" * 5000, "password": "secret1", "account_types": ["mechanic_technician"]},
        {"email": "ok@example.com", "name": "X", "password": "short", "account_types": ["mechanic_technician"]},
        {"email": "ok@example.com", "name": "X", "password": "p" * 500, "account_types": ["mechanic_technician"]},
        # (An empty account_types list used to sit here as a
        # degenerate payload. The onboarding design — owner
        # 2026-10-31, built 2026-11-07 — made it the STANDARD
        # signup: types are chosen in the setup wizard, not at
        # signup. Its success is covered positively in
        # tests/test_onboarding.py.)
        {"email": "ok@example.com", "name": "X", "password": "secret1", "account_types": ["superuser"]},
        {"email": "ok@example.com", "name": "X", "password": "secret1", "account_types": "mechanic_technician"},
    ],
)
def test_signup_degenerate_payloads(client, db, payload):
    resp = client.post("/api/core/signup", json=payload)
    assert resp.status_code in (400, 422), (payload, resp.status_code, resp.text[:200])
    # No half-created account leaks out of a rejected signup.
    assert (
        db.scalar(
            select(core_models.User).where(core_models.User.email == "ok@example.com")
        )
        is None
    )


# ---------------------------------------------------------------------
# Item 5 — export completeness: one of everything, diffed
# ---------------------------------------------------------------------


class _FetchAllStorage:
    """Export double: every stored file is fetchable."""

    def fetch(self, key):
        return b"file-bytes"

    def presigned_get_url(self, key):
        return f"https://files.example.test/{key}?sig=stub"


def test_export_contains_every_module(client, db, alice, bob, monkeypatch):
    import json
    from decimal import Decimal

    from app.modules.core import export as export_module

    monkeypatch.setattr(export_module, "storage", _FetchAllStorage())
    a = auth_headers(alice)

    # Inventory: a tool with a photo + a custom field value, a
    # battery, a set with a core piece.
    definition = inventory_models.FieldDefinition(
        owner_id=alice.id,
        item_type="tool",
        name="torque_spec",
        label="Torque spec",
        field_type="text",
        required=False,
        searchable=False,
        options=None,
        sort_order=0,
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)
    photo_key = f"{alice.id}/tools/x/photo/wrench.jpg"
    tool = _tool(
        db,
        alice,
        name="Export Wrench",
        custom_data={str(definition.id): "90 ft-lb"},
        attachments=[
            {
                "key": photo_key,
                "filename": "wrench.jpg",
                "kind": "photo",
                "content_type": "image/jpeg",
                "size_bytes": 10,
                "uploaded_at": "2026-10-01T00:00:00+00:00",
            }
        ],
    )
    # Point the photo key at the real id (cosmetic; the stub fetches all).
    tool.attachments[0]["key"] = f"{alice.id}/tools/{tool.id}/photo/wrench.jpg"
    db.commit()
    battery = _battery(db, alice, name="Export Pack")
    tool_set = _tool(db, alice, name="Export Socket Set", is_set=True)
    _piece(db, alice, tool_set, name="13mm socket")

    # Borrowing: one live checkout.
    checkout = client.post(
        "/api/borrowing/checkouts",
        json={
            "item_kind": "tool",
            "item_id": str(tool.id),
            "borrower_name": "Manual Mike",
        },
        headers=a,
    )
    assert checkout.status_code == 201, checkout.text

    # Maintenance: one schedule. The repair that used to seed
    # here is a warranty CLAIM since the merge (2026-11-04) —
    # it exports through claims.json with its repair facts.
    repair_claim = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": False,
            "problem": "Export break",
        },
        headers=a,
    )
    assert repair_claim.status_code == 201, repair_claim.text
    repair_claim = repair_claim.json()["claim"]
    for to_status, extra in (
        ("reported", {}),
        ("in_repair", {"repair_sent_to": "Export Shop"}),
        ("completed", {"repair_cost": "12.00"}),
    ):
        moved = client.post(
            f"/api/claims/{repair_claim['id']}/transition",
            json={"to_status": to_status, **extra},
            headers=a,
        )
        assert moved.status_code == 200, moved.text
    schedule = client.post(
        f"/api/maintenance/items/battery/{battery.id}/schedules",
        json={"kind": "service", "label": "Export service", "interval_days": 180},
        headers=a,
    )
    assert schedule.status_code == 201, schedule.text

    # Claims: one claim with a line, a comm entry, and an uploaded
    # evidence file (row inserted directly — the upload flow itself
    # is covered by the claims suite).
    from app.modules.claims import models as claims_models

    claim_resp = client.post("/api/disaster-claims", json={}, headers=a)
    assert claim_resp.status_code == 201, claim_resp.text
    claim_id = claim_resp.json()["id"]
    line = client.post(
        f"/api/disaster-claims/{claim_id}/lines",
        json={
            "target_kind": "battery",
            "target_id": str(battery.id),
            "value_basis": "entered",
            "amount": "80.00",
        },
        headers=a,
    )
    assert line.status_code == 201, line.text
    comm = client.post(
        f"/api/disaster-claims/{claim_id}/communications",
        json={"channel": "email", "contact": "Adj", "summary": "Export comm"},
        headers=a,
    )
    assert comm.status_code == 201, comm.text
    upload_key = f"{alice.id}/claims/{claim_id}/document/statement.pdf"
    db.add(
        claims_models.ClaimEvidence(
            claim_id=uuid.UUID(claim_id),
            owner_id=alice.id,
            source="upload",
            attachment={
                "key": upload_key,
                "filename": "statement.pdf",
                "kind": "document",
                "content_type": "application/pdf",
                "size_bytes": 10,
                "uploaded_at": "2026-10-01T00:00:00+00:00",
            },
        )
    )
    db.commit()

    # Dealers: profile + private company + private agent + preference
    # + a representation.
    profile = client.put(
        "/api/dealers/profile/me",
        json={"display_name": "Alice Deals", "publicly_listed": False},
        headers=a,
    )
    assert profile.status_code == 200, profile.text
    company = client.post(
        "/api/dealers/companies",
        json={"name": "Export Co", "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=a,
    ).json()
    agent = client.post(
        "/api/dealers/agents/private",
        json={"name": "Export Dan", "company_id": company["id"], "phone": "", "email": "", "notes": ""},
        headers=a,
    ).json()
    pref = client.post(
        "/api/dealers/preferred",
        json={"company_id": company["id"], "private_agent_id": agent["id"]},
        headers=a,
    )
    assert pref.status_code == 201, pref.text
    from app.modules.dealers import models as dealers_models

    dir_company = dealers_models.DealerCompany(
        id=uuid.uuid4(), name="Export Brand", is_directory=True
    )
    db.add(dir_company)
    db.commit()
    rep = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": str(dir_company.id)},
        headers=a,
    )
    assert rep.status_code == 201, rep.text

    # Sharing: a peer invite out to Bob.
    invite = client.post(
        "/api/core/sharing/peer/invite",
        json={"account_number": bob.account_number},
        headers=a,
    )
    assert invite.status_code == 201, invite.text

    resp = client.get("/api/core/export", headers=a)
    assert resp.status_code == 200, resp.text[:200]
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(archive.namelist())

    expected = {
        "account.json",
        "tools.json",
        "batteries.json",
        "field_definitions.json",
        "sharing.json",
        "borrowing.json",
        "maintenance.json",
        "claims.json",
        "disaster_claims.json",
        "dealers.json",
        "files_manifest.json",
    }
    assert expected <= names, f"missing: {expected - names}"

    def read(name):
        return json.loads(archive.read(name))

    tools = read("tools.json")
    by_name = {t["name"]: t for t in tools}
    assert {"Export Wrench", "Export Socket Set"} <= set(by_name)
    assert by_name["Export Wrench"]["custom_data"] == {
        str(definition.id): "90 ft-lb"
    }
    pieces = by_name["Export Socket Set"]["set"]["core_pieces"]
    assert [p["name"] for p in pieces] == ["13mm socket"]
    assert [b["name"] for b in read("batteries.json")] == ["Export Pack"]
    assert [d["name"] for d in read("field_definitions.json")] == ["torque_spec"]

    borrowing = read("borrowing.json")
    assert len(borrowing) == 1
    assert borrowing[0]["borrower_name"] == "Manual Mike"

    maintenance = read("maintenance.json")
    # Schedules only — repairs export as claims now (merge).
    assert "repairs" not in maintenance
    assert len(maintenance["schedules"]) == 1

    # Claims separation (2026-11-05): the export splits by
    # kind — claims.json carries the warranty claim ONLY, the
    # insurance claim rides disaster_claims.json.
    claims = read("claims.json")
    assert len(claims["claims"]) == 1
    exported_repair = next(
        c for c in claims["claims"] if c["kind"] == "warranty_repair"
    )
    assert exported_repair["description"] == "Export break"
    assert exported_repair["repair_sent_to"] == "Export Shop"
    assert exported_repair["repair_cost"] == "12.00"
    disaster_claims = read("disaster_claims.json")
    assert len(disaster_claims["claims"]) == 1
    claim = next(
        c for c in disaster_claims["claims"] if c["id"] == claim_id
    )
    assert len(claim["lines"]) == 1
    assert len(claim["communications"]) == 1
    uploads = [e for e in claim["evidence"] if e["source"] == "upload"]
    assert len(uploads) == 1 and uploads[0]["zip_path"] in names

    dealers = read("dealers.json")
    assert dealers["agent_profile"]["display_name"] == "Alice Deals"
    assert [c["name"] for c in dealers["private_companies"]] == ["Export Co"]
    assert [p["name"] for p in dealers["private_agents"]] == ["Export Dan"]
    assert len(dealers["preferred_agents"]) == 1
    assert len(dealers["representations"]) == 1

    sharing = read("sharing.json")
    assert "tier" in sharing and "peer" in sharing

    manifest = read("files_manifest.json")
    included = {m["filename"] for m in manifest if m["included"]}
    assert {"wrench.jpg", "statement.pdf"} <= included
    # The photo bytes actually ride in the archive.
    photo_paths = [n for n in names if n.endswith("wrench.jpg")]
    assert photo_paths and archive.read(photo_paths[0]) == b"file-bytes"


# ---------------------------------------------------------------------
# Item 6 — job seams: the scheduler scripts execute + idempotency
# ---------------------------------------------------------------------


def _script_factory(db):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(
        bind=db.get_bind(), class_=type(db), expire_on_commit=False
    )
    return factory


def test_job_scripts_execute_and_are_idempotent(db, alice, monkeypatch, capsys):
    from datetime import datetime, timezone

    from app.modules.billing import entitlements
    from app.modules.claims import service as claims_service
    from app.modules.maintenance import models as maintenance_models
    from app.scripts import (
        run_claims_jobs,
        run_entitlement_jobs,
        run_maintenance_jobs,
    )

    factory = _script_factory(db)
    for module in (run_entitlement_jobs, run_maintenance_jobs, run_claims_jobs):
        monkeypatch.setattr(module, "SessionLocal", factory)

    now = datetime.now(timezone.utc)
    # A lapsed subscription (period + grace both past) for the
    # entitlement script to flip.
    sub = entitlements.upsert_subscription(
        db,
        alice.id,
        plan_key="pro",
        status="canceled",
        current_period_end=now - timedelta(days=30),
        grace_until=now - timedelta(days=10),
    )
    # An overdue schedule for the maintenance script to notify on.
    tool = _tool(db, alice)
    db.add(
        maintenance_models.MaintenanceSchedule(
            owner_id=alice.id,
            item_kind="tool",
            item_id=tool.id,
            kind="service",
            label="Overdue thing",
            due_date=date.today() - timedelta(days=1),
        )
    )
    db.commit()
    # A filed claim with a near deadline for the claims script.
    claim = claims_service.create_claim(
        db, alice, proof_of_loss_due=date.today() + timedelta(days=3)
    )
    claims_service.transition(db, alice, claim.id, "filed")

    run_entitlement_jobs.main()
    run_maintenance_jobs.main()
    run_claims_jobs.main()
    out = capsys.readouterr().out
    assert "1 subscription(s) lapsed" in out
    assert "maintenance jobs" in out
    assert "claims jobs" in out

    db.expire_all()
    db.refresh(sub)
    assert sub.status == "ended"
    notes = db.scalars(select(core_models.Notification)).all()
    kinds = sorted(n.kind for n in notes)
    # Audit A8 (2026-10-22): the claims script also runs the
    # claim-readiness nudges — alice's fixture tool has record
    # gaps, so one claim_readiness nudge joins the set.
    assert kinds == ["claim_deadline", "claim_readiness", "maintenance_overdue"]

    # Second runs: no flips, no duplicate notifications.
    run_entitlement_jobs.main()
    run_maintenance_jobs.main()
    run_claims_jobs.main()
    out = capsys.readouterr().out
    assert "0 subscription(s) lapsed" in out
    assert len(db.scalars(select(core_models.Notification)).all()) == 3
