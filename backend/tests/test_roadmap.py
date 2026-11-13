"""Audit A15 (2026-10-22): the operator-published roadmap.

Pins: the public page reads signed-out and starts EMPTY (no
seeded content — a roadmap is the operator's word); CRUD is
operator-only, validates the status vocabulary, orders by
sort_order, and every mutation is audit-logged.
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
        json={"title": "Nope", "status": "planned"},
        headers=auth_headers(member),
    )
    assert denied.status_code == 403

    bad = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "X", "status": "someday"},
        headers=op_headers,
    )
    assert bad.status_code == 422

    second = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "Second thing", "note": "Later.", "status": "planned", "sort_order": 20},
        headers=op_headers,
    )
    assert second.status_code == 201
    first = client.post(
        "/api/admin/roadmap-entries",
        json={"title": "First thing", "status": "in_progress", "sort_order": 10},
        headers=op_headers,
    )
    assert first.status_code == 201

    public = client.get("/api/core/roadmap").json()
    assert [e["title"] for e in public] == ["First thing", "Second thing"]

    updated = client.put(
        f"/api/admin/roadmap-entries/{first.json()['id']}",
        json={"title": "First thing", "status": "shipped", "sort_order": 10},
        headers=op_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "shipped"

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
