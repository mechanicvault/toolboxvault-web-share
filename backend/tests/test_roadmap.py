"""Audit A15 (2026-10-22): the operator-published roadmap.

Pins: the public page reads signed-out and starts EMPTY (no
seeded content — a roadmap is the operator's word); CRUD is
operator-only, validates the stage vocabulary, orders by
sort_order, and every mutation is audit-logged.

Stage rebuild (2026-11-12): the vocabulary is the owner's
8 stages (idea .. released); the legacy planned / in_progress /
shipped values were rewritten by migration 0105 and are no
longer accepted.
"""

import uuid

from app.modules.core import models as core_models
from tests.conftest import auth_headers


def _make_user(db, number, email, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=number,
        email=email,
        name="Roadmapper",
        password_hash="x",
        account_types=["mechanic_technician"],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_public_roadmap_starts_empty(client):
    resp = client.get("/api/core/roadmap")
    assert resp.status_code == 200
    assert resp.json() == []


def test_operator_crud_round_trip(client, db):
    operator = _make_user(db, "TV-M-900001", "a15-op@example.com", operator=True)
    member = _make_user(db, "TV-M-900002", "a15-member@example.com")
    op_headers = auth_headers(operator)

    denied = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "Nope", "stage": "idea"},
        headers=auth_headers(member),
    )
    assert denied.status_code == 403

    bad = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "X", "stage": "someday"},
        headers=op_headers,
    )
    assert bad.status_code == 422

    second = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "Second thing", "note": "Later.", "stage": "awaiting_schedule", "sort_order": 20},
        headers=op_headers,
    )
    assert second.status_code == 201
    first = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "First thing", "stage": "building_started", "sort_order": 10},
        headers=op_headers,
    )
    assert first.status_code == 201

    public = client.get("/api/core/roadmap").json()
    assert [e["title"] for e in public] == ["First thing", "Second thing"]

    updated = client.put(
        f"/api/admin/roadmap-entries/{first.json()['id']}",
        json={"title": "First thing", "stage": "released", "sort_order": 10},
        headers=op_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["stage"] == "released"

    deleted = client.delete(
        f"/api/admin/roadmap-entries/{second.json()['id']}", headers=op_headers
    )
    assert deleted.status_code == 204
    assert [e["title"] for e in client.get("/api/core/roadmap").json()] == ["First thing"]

    from app.modules.core import models

    actions = {
        row.action
        for row in db.query(models.AuditLog).all()
        if row.action.startswith("roadmap.")
    }
    assert actions == {"roadmap.create", "roadmap.update", "roadmap.delete"}


def test_all_eight_stages_accepted_and_legacy_rejected(client, db):
    from app.modules.core.roadmap import STAGES

    assert STAGES == (
        "idea",
        "approved_idea",
        "awaiting_schedule",
        "scheduled",
        "building_started",
        "building_finished",
        "testing",
        "released",
    )
    operator = _make_user(db, "TV-M-900003", "a15-stages@example.com", operator=True)
    headers = auth_headers(operator)

    for index, stage in enumerate(STAGES):
        resp = client.post(
            "/api/admin/roadmap-entries",
            json={"title": f"Stage {stage}", "stage": stage, "sort_order": index},
            headers=headers,
        )
        assert resp.status_code == 201, stage
        assert resp.json()["stage"] == stage

    # A create that omits the stage lands on the first stage.
    defaulted = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "No stage given", "sort_order": 99},
        headers=headers,
    )
    assert defaulted.status_code == 201
    assert defaulted.json()["stage"] == "idea"

    # The pre-0105 vocabulary is gone: none of it validates anymore.
    for legacy in ("planned", "in_progress", "shipped"):
        resp = client.post(
            "/api/admin/roadmap-entries",
            json={"title": "Legacy", "stage": legacy},
            headers=headers,
        )
        assert resp.status_code == 422, legacy

    public = client.get("/api/core/roadmap").json()
    assert [e["stage"] for e in public] == [*STAGES, "idea"]
