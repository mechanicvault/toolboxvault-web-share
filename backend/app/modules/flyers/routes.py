"""Flyers HTTP surface — thin: parse, gate, call the service,
map errors. Gated on the flyers module like its siblings: a
user the module isn't effective for gets 403
module_unavailable, and the menu item, Home widget, dealer
tab and notifications ride the same switch (service + inbox
KIND_MODULE).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.flyers import models, schemas, service

router = APIRouter(tags=["flyers"])

_flyers_module = require_module("flyers")


def _as_http(exc: service.FlyerError) -> HTTPException:
    if isinstance(exc, service.FlyerNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _view(db, user, source, **kw) -> schemas.SourceView:
    return schemas.SourceView(
        **service.source_view(db, user, source, **kw)
    )


@router.get("/feed", response_model=list[schemas.SourceView])
def get_feed(
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    """Connected sources with a live flyer (Home widget +
    flyer page)."""
    return [
        schemas.SourceView(**view) for view in service.feed(db, user)
    ]


@router.get("/sources", response_model=list[schemas.SourceView])
def list_sources(
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    """Every source the caller is connected to, with its
    current flyer (spots without a live flyer included — the
    flyer page's tabs)."""
    return [
        _view(db, user, source)
        for source in service.visible_sources(db, user.id)
    ]


@router.get("/sources/{source_id}", response_model=schemas.SourceView)
def get_source_detail(
    source_id: uuid.UUID,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_source(db, source_id)
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    if not service.source_visible_to(
        db, user.id, source
    ) and not service.can_post_source(db, user, source):
        raise HTTPException(status_code=404, detail="Flyer spot not found")
    return _view(db, user, source, with_history=True)


@router.get("/postable", response_model=list[schemas.SourceView])
def list_postable(
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    return [
        schemas.SourceView(**view)
        for view in service.postable_sources(db, user)
    ]


@router.post("/sources", response_model=schemas.SourceView)
def create_source(
    payload: schemas.SourceCreate,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_or_create_source(
            db,
            user,
            kind=payload.kind,
            company_id=payload.company_id,
            agent_user_id=payload.agent_user_id,
            private_agent_id=payload.private_agent_id,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return _view(db, user, source, with_history=True)


@router.patch("/sources/{source_id}", response_model=schemas.SourceView)
def update_source(
    source_id: uuid.UUID,
    payload: schemas.SourceSettings,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_source(db, source_id)
        source = service.update_source_settings(
            db,
            user,
            source,
            visible=payload.visible,
            history_visible=payload.history_visible,
            standing_url=payload.standing_url,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return _view(db, user, source, with_history=True)


@router.post(
    "/sources/{source_id}/flyers/link", response_model=schemas.FlyerView
)
def post_link(
    source_id: uuid.UUID,
    payload: schemas.LinkPost,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_source(db, source_id)
        flyer = service.post_from_link(
            db,
            user,
            source,
            url=payload.url,
            label=payload.label,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.FlyerView(**service.flyer_view(flyer, is_current=True))


@router.post(
    "/sources/{source_id}/flyers/upload", response_model=schemas.FlyerView
)
def post_upload(
    source_id: uuid.UUID,
    payload: schemas.UploadPost,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_source(db, source_id)
        flyer = service.post_from_upload(
            db,
            user,
            source,
            key=payload.key,
            label=payload.label,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.FlyerView(**service.flyer_view(flyer, is_current=True))


@router.post(
    "/sources/{source_id}/flyers/photos", response_model=schemas.FlyerView
)
def post_photos(
    source_id: uuid.UUID,
    payload: schemas.PhotosPost,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    try:
        source = service.get_source(db, source_id)
        flyer = service.post_from_photos(
            db,
            user,
            source,
            pages=[page.model_dump() for page in payload.pages],
            label=payload.label,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.FlyerView(**service.flyer_view(flyer, is_current=True))


@router.delete("/flyers/{flyer_id}")
def delete_flyer(
    flyer_id: uuid.UUID,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    flyer = db.get(models.Flyer, flyer_id)
    if flyer is None:
        raise HTTPException(status_code=404, detail="Flyer not found")
    try:
        service.delete_flyer(db, user, flyer)
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return {"deleted": True}


@router.post("/uploads/pdf-url", response_model=schemas.UploadUrlResponse)
def pdf_upload_url(
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_flyers_module),
):
    try:
        result = service.issue_pdf_upload_url(
            user,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.UploadUrlResponse(**result)


@router.post("/uploads/photo-url", response_model=schemas.UploadUrlResponse)
def photo_upload_url(
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_flyers_module),
):
    try:
        result = service.issue_photo_upload_url(
            user,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.UploadUrlResponse(**result)


@router.post("/scan/detect", response_model=list[schemas.DetectPage])
def scan_detect(
    payload: schemas.DetectRequest,
    user: CurrentUser = Depends(_flyers_module),
):
    try:
        pages = service.detect_pages(user, payload.keys)
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return [schemas.DetectPage(**page) for page in pages]


@router.get(
    "/companies/{company_id}", response_model=schemas.CompanyTabView
)
def company_tab(
    company_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    if as_visitor:
        # "View as visitor" (Sweep D5): the dealer page's
        # preview fetch for its Flyers tab — the same company
        # tab read, shaped by the visitor stand-in (no
        # connections, no posting rights), gated on the caller
        # representing this company, exactly like the dealers
        # module's own preview fetches.
        from app.modules.core import visitor_preview
        from app.modules.dealers import service as dealers_service

        company = dealers_service.visible_company(db, user.id, company_id)
        if (
            company is None
            or not company.is_directory
            or service._representation(db, user.id, company_id) is None
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a representative of this company can preview its page as a visitor.",
            )
        try:
            result = service.company_tab(
                db, visitor_preview.visitor_viewer(), company_id
            )
        except service.FlyerError as exc:
            raise _as_http(exc) from exc
        return schemas.CompanyTabView(**result)
    try:
        result = service.company_tab(db, user, company_id)
    except service.FlyerError as exc:
        raise _as_http(exc) from exc
    return schemas.CompanyTabView(**result)


@router.get("/alerts", response_model=schemas.AlertPrefView)
def get_alerts(
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    return schemas.AlertPrefView(enabled=service.alerts_enabled(db, user.id))


@router.put("/alerts", response_model=schemas.AlertPrefView)
def put_alerts(
    payload: schemas.AlertPrefWrite,
    user: CurrentUser = Depends(_flyers_module),
    db: Session = Depends(get_db),
):
    enabled = service.set_alerts_enabled(db, user.id, payload.enabled)
    return schemas.AlertPrefView(enabled=enabled)
