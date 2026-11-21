"""Background lookup jobs (rebuild Phase 4, 2026-11-20).

A quick lookup that can't answer completely starts — or
joins — a job for the part number and returns at once with
status "working" and the job id. The job runs the FULL
lookup (the agent when enabled, else the walk) on a worker
thread and stores the public result; the wizard polls the
job and fills the form while the user is still inputting.
Once a tool is saved, nothing here ever touches it (row
223).

One live job per part number: the result is catalog data,
so a second user asking for the same part joins the same
job instead of paying for a second run. A finished job's
result is reused for a short window, then a fresh job may
start (catalogs change).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.catalog import models as catalog_models
from app.modules.catalog.normalize import norm_brand, norm_model

_REUSE_DONE_MINUTES = 10
_STALE_RUNNING_MINUTES = 30


def _execute_lookup(db: Session, job: catalog_models.CatalogLookupJob) -> dict:
    """The job's work: the full lookup for the part. A seam —
    tests replace it; production runs the real chain."""
    from app.modules.catalog import lookup

    return lookup.run_lookup(
        db,
        job.requested_by,
        brand=job.brand,
        model=job.model,
        upc=job.upc,
        quick=False,
    )


def _run_job(job_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        job = db.get(catalog_models.CatalogLookupJob, job_id)
        if job is None or job.status == "done":
            return
        job.status = "running"
        db.commit()
        try:
            result = _execute_lookup(db, job)
            job.result = result
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — a failed job is a state, not a crash
            db.rollback()
            job = db.get(catalog_models.CatalogLookupJob, job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _spawn(job_id: uuid.UUID) -> None:
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()


def ensure_job(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    brand: str,
    model: str,
    upc: str = "",
) -> catalog_models.CatalogLookupJob:
    """The live job for this part number, starting one when
    none exists. A job still queued/running is joined; a
    recently finished one is reused; a stale 'running' job
    (its worker died with a restart) is failed and replaced."""
    brand_key = norm_brand(brand)
    model_key = norm_model(model)
    now = datetime.now(timezone.utc)
    existing = db.scalars(
        select(catalog_models.CatalogLookupJob)
        .where(
            catalog_models.CatalogLookupJob.brand_key == brand_key,
            catalog_models.CatalogLookupJob.model_key == model_key,
            catalog_models.CatalogLookupJob.upc == (upc or ""),
        )
        .order_by(catalog_models.CatalogLookupJob.created_at.desc())
    ).first()
    if existing is not None:
        created = existing.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = now - created if created else timedelta(days=1)
        if existing.status in ("queued", "running"):
            if age <= timedelta(minutes=_STALE_RUNNING_MINUTES):
                return existing
            existing.status = "failed"
            existing.error = "The lookup job stalled and was replaced."
            existing.finished_at = now
            db.commit()
        elif existing.status == "done" and age <= timedelta(
            minutes=_REUSE_DONE_MINUTES
        ):
            return existing
    job = catalog_models.CatalogLookupJob(
        brand_key=brand_key,
        model_key=model_key,
        upc=upc or "",
        brand=brand,
        model=model,
        requested_by=user_id,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    _spawn(job.id)
    return job


def job_view(job: catalog_models.CatalogLookupJob) -> dict:
    view = {
        "job_id": str(job.id),
        "status": job.status,
        "brand": job.brand,
        "model": job.model,
    }
    if job.status == "done":
        view["result"] = job.result
    if job.status == "failed":
        view["error"] = job.error or "The lookup failed."
    return view
