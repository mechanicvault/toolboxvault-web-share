"""Catalog routes: the community aggregate, the layered
lookup behind Quick Add, the AI item-identification assist, and
the AI seam's public posture.

The dark-seam contract: while no AI provider is configured,
/identify answers 503 {code: ai_not_configured} — the UI hides
the affordance from /ai-status and never shows an error for a
feature that was never offered. A wallet that can't cover a
priced action answers 402 {code: insufficient_credits}.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module, require_operator
from app.modules.billing import ai_service, wallet
from app.modules.catalog import grounded, library, lookup, schemas, service

router = APIRouter()

_catalog_module = require_module("catalog")


def _ai_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "ai_not_configured",
            "message": "AI features aren't switched on for this site yet.",
        },
    )


def _insufficient() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "insufficient_credits",
            "message": "Your AI credit balance doesn't cover this action.",
        },
    )


@router.get(
    "/lookup",
    response_model=schemas.LookupResponse,
    response_model_exclude_none=True,
)
def run_lookup(
    brand: str = Query(default="", max_length=200),
    model: str = Query(default="", max_length=200),
    upc: str = Query(default="", max_length=64),
    link: str = Query(default="", max_length=2000),
    depth: str = Query(default="full", pattern="^(quick|full)$"),
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """The layered chain behind Quick Add: community catalog ->
    barcode database -> grounded web (a real product page,
    found by search or pasted as `link`) -> hardened AI assist,
    first hit wins per field, every value source-labeled.
    Nothing found = empty fields (the form simply stays
    manual); details without a verified name answer partial.

    depth=quick (row 203) is the wizard's first pass — the
    basic facts fast, no browser walk; depth=full (the
    default, every other caller) runs the complete walk."""
    try:
        return lookup.run_lookup(
            db,
            user.id,
            brand=brand.strip(),
            model=model.strip(),
            upc=upc.strip(),
            link=link.strip(),
            quick=depth == "quick",
        )
    except wallet.InsufficientCredits as exc:
        raise _insufficient() from exc


@router.get("/lookup/jobs/{job_id}")
def lookup_job(
    job_id: str,
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """One background lookup job (rebuild Phase 4): the wizard
    polls this while a quick answer is still "working". The
    result is public catalog data in the lookup response
    shape; it fills a form only while the user is inputting
    (row 223) and never touches a saved record."""
    import uuid as _uuid

    from app.modules.catalog import jobs as lookup_jobs
    from app.modules.catalog import models as catalog_models

    try:
        parsed = _uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "That lookup job doesn't exist."},
        )
    job = db.get(catalog_models.CatalogLookupJob, parsed)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "That lookup job doesn't exist."},
        )
    return lookup_jobs.job_view(job)


@router.get("/admin/review")
def catalog_review_queue(
    status_filter: str = Query(default="", alias="status", max_length=20),
    user: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """The catalog review queue (rebuild Phase 5): candidate
    and conflicted library entries awaiting an admin's word."""
    return {"entries": library.review_queue(db, status=status_filter)}


@router.post("/admin/review/{product_id}/approve")
def catalog_review_approve(
    product_id: str,
    user: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    updated = library.set_status(db, product_id, "verified")
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "entry_not_found", "message": "That catalog entry doesn't exist."},
        )
    return updated


@router.post("/admin/review/{product_id}/reject")
def catalog_review_reject(
    product_id: str,
    user: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    updated = library.set_status(db, product_id, "quarantined")
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "entry_not_found", "message": "That catalog entry doesn't exist."},
        )
    return updated


@router.post("/admin/review/{product_id}/resolve")
def catalog_review_resolve(
    product_id: str,
    payload: dict,
    user: CurrentUser = Depends(require_operator),
    db: Session = Depends(get_db),
):
    keep = str((payload or {}).get("keep") or "stored")
    if keep not in ("stored", "challenger"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "bad_keep", "message": "keep must be 'stored' or 'challenger'."},
        )
    updated = library.resolve_conflict(db, product_id, keep=keep)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "entry_not_found", "message": "That catalog entry isn't in conflict."},
        )
    return updated


@router.post("/fetch-photo", response_model=schemas.FetchPhotoResponse)
def fetch_photo(
    payload: schemas.FetchPhotoRequest,
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """Download the product photo a grounded page offered, so
    the wizard can stage it exactly like an uploaded photo.
    SSRF-guarded like a manual import; anything that isn't a
    real photo file answers 422 {code: photo_unreadable}."""
    try:
        data, content_type, filename = grounded.fetch_photo(payload.url.strip())
    except grounded.PageFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "photo_unreadable", "message": str(exc)},
        ) from exc
    return {
        "filename": filename,
        "content_type": content_type,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


@router.get("/suggestions", response_model=schemas.CatalogSuggestions)
def suggestions(
    brand: str = Query(default="", max_length=200),
    model: str = Query(default="", max_length=200),
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """The community catalog's own aggregate for one key (the
    lookup chain's first layer, exposed for transparency)."""
    return service.suggestions_for(db, brand.strip(), model.strip())


@router.post(
    "/identify",
    response_model=schemas.LookupResponse,
    response_model_exclude_none=True,
)
def identify(
    payload: schemas.IdentifyRequest,
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """AI item identification from a free-text description."""
    try:
        return lookup.identify(db, user.id, payload.text)
    except ai_service.AiNotConfigured as exc:
        raise _ai_unavailable() from exc
    except ai_service.AiProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_provider_error", "message": str(exc)},
        ) from exc
    except wallet.InsufficientCredits as exc:
        raise _insufficient() from exc


@router.post(
    "/identify-photo",
    response_model=schemas.LookupResponse,
    response_model_exclude_none=True,
)
def identify_photo(
    payload: schemas.IdentifyPhotoRequest,
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """AI item identification from one uploaded photo of the
    item or its label. The
    answer is a labeled proposal with the model's stated
    confidence — the wizard confirms it with the user and
    feeds it into the ordinary grounded lookup, so the facts
    that fill the form still come from a verified page. Same
    error contract as /identify, plus 422 for bytes that are
    not a usable photo."""
    try:
        image_data = base64.b64decode(payload.image_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "photo_unreadable",
                "message": "That photo couldn't be read.",
            },
        ) from exc
    try:
        return lookup.identify_photo(db, user.id, image_data)
    except lookup.PhotoUnreadable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "photo_unreadable", "message": str(exc)},
        ) from exc
    except ai_service.AiNotConfigured as exc:
        raise _ai_unavailable() from exc
    except ai_service.AiProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_provider_error", "message": str(exc)},
        ) from exc
    except wallet.InsufficientCredits as exc:
        raise _insufficient() from exc


@router.get("/ai-status")
def ai_status(
    user: CurrentUser = Depends(_catalog_module),
    db: Session = Depends(get_db),
):
    """Whether AI surfaces may render for this site (provider +
    model only — never key material)."""
    return ai_service.status(db)
