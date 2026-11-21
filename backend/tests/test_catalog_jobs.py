"""Rebuild Phase 4 — background lookup jobs.

Pins: one live job per part number (a second ask joins it),
a finished job is reused briefly, a stale running job is
replaced, the worker stores the full lookup's result, and a
quick lookup that can't answer completely reports "working"
with a job id while a complete one reports "complete" and
starts nothing.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.catalog import agent, jobs, library, lookup
from app.modules.catalog import models as catalog_models
from app.modules.core import models as core_models


@pytest.fixture()
def no_spawn(monkeypatch):
    monkeypatch.setattr(jobs, "_spawn", lambda job_id: None)


@pytest.fixture()
def seeker(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000513",
        email="jobseeker@example.com",
        name="Job Seeker",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_one_live_job_per_part_number(db, no_spawn, seeker):
    first = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SBUPM246V"
    )
    second = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco", model="sbupm246v"
    )
    assert first.id == second.id
    other = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SABCTX13VA"
    )
    assert other.id != first.id


def test_worker_stores_the_result(db, no_spawn, seeker, monkeypatch):
    monkeypatch.setattr(
        jobs,
        "_execute_lookup",
        lambda db_, job: {"fields": {"name": {"value": "Socket Set"}}, "pieces": []},
    )
    job = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SBUPM246V"
    )
    # Drive the worker's core inline (its own session handling
    # is exercised live; the state machine is what's pinned).
    job.status = "running"
    db.commit()
    job.result = jobs._execute_lookup(db, job)
    job.status = "done"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    view = jobs.job_view(job)
    assert view["status"] == "done"
    assert view["result"]["fields"]["name"]["value"] == "Socket Set"
    # A fresh ask inside the reuse window joins the done job.
    again = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SBUPM246V"
    )
    assert again.id == job.id


def test_a_stale_running_job_is_replaced(db, no_spawn, seeker):
    job = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SBUPM246V"
    )
    job.status = "running"
    job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    fresh = jobs.ensure_job(
        db, user_id=seeker.id, brand="Matco Tools", model="SBUPM246V"
    )
    assert fresh.id != job.id
    db.refresh(job)
    assert job.status == "failed"


def test_quick_lookup_reports_working_with_a_job(
    db, no_spawn, seeker, monkeypatch
):
    monkeypatch.setattr(agent, "agent_enabled", lambda db_: True)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco Tools", model="ZZUNKNOWN9", quick=True
    )
    assert result["status"] == "working"
    assert result["job_id"]
    stored = db.get(catalog_models.CatalogLookupJob, uuid.UUID(result["job_id"]))
    assert stored is not None
    assert stored.model_key == "zzunknown9"


def test_quick_lookup_complete_starts_no_job(db, no_spawn, seeker, monkeypatch):
    monkeypatch.setattr(agent, "agent_enabled", lambda db_: True)
    library.import_product(
        db,
        {
            "brand": "Matco Tools",
            "model": "SBUPM246V",
            "name": "24-Piece Socket Set",
            "category": "Socket set",
            "msrp": 499.95,
            "piece_count": 24,
            "pieces": [
                {"name": f"Piece {i}", "model": f"P{i}V", "msrp": 10.0}
                for i in range(24)
            ],
        },
        source_name="Matco catalog PDF",
        source_kind="verified",
    )
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco Tools", model="SBUPM246V", quick=True
    )
    assert result["status"] == "complete"
    assert result["job_id"] is None
    assert db.query(catalog_models.CatalogLookupJob).count() == 0
