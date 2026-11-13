"""Importer routes (inventory module): upload → suggest → dry-run
→ confirm, plus session discard.

Mounted into the inventory router by routes.py BEFORE the /{tool_id}
routes: the literal "import" segment must win over a UUID path
parameter ("import" is not a UUID, so a late registration would 422
instead of routing). Every route is gated by the same
require_module("inventory") dependency as the rest of the module.

HTTP layer only — parsing, mapping validation, transformation and
creation all live in importer.py.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.inventory import importer, matching, schemas

router = APIRouter()

_inventory_module = require_module("inventory")


def _session_or_404(db: Session, user: CurrentUser, session_id: uuid.UUID):
    """Owner-scoped session lookup: foreign ids and missing ids are
    the same 404; an expired session deletes itself and says so."""
    try:
        session = importer.get_owned_session(db, user.id, session_id)
    except importer.SessionExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail=str(exc)
        ) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    return session


@router.post(
    "/import/upload",
    response_model=schemas.ImportSessionPublic,
    status_code=201,
)
async def upload_import_file(
    file: UploadFile = File(...),
    kind: str = Form(default="tool"),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Accept a .csv/.xlsx, parse it, and keep its bytes against a
    24h import session. Returns the preview (headers + sample rows),
    the field catalog for the kind, and suggested mappings."""
    data = await file.read()
    try:
        session = importer.create_session(
            db, user.id, filename=file.filename or "", kind=kind, data=data
        )
    except importer.ImportFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    rows = importer.session_rows(session)
    fields = importer.field_catalog(db, user.id, session.kind)
    return {
        "session_id": session.id,
        "filename": session.filename,
        "file_format": session.file_format,
        "kind": session.kind,
        "headers": list(session.headers),
        "sample_rows": rows[: importer.SAMPLE_ROWS],
        "row_count": session.row_count,
        "expires_at": session.expires_at,
        "fields": fields,
        "suggested_mapping": {
            str(index): key
            for index, key in importer.suggest_mapping(
                list(session.headers), fields
            ).items()
        },
    }


@router.post(
    "/import/{session_id}/suggest",
    response_model=schemas.ImportSuggestResponse,
)
def suggest_import_mapping(
    session_id: uuid.UUID,
    payload: schemas.ImportSuggestRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Field catalog + auto-suggested mapping for a (possibly
    changed) kind — the mapping UI calls this when the user flips
    between Tools and Batteries."""
    session = _session_or_404(db, user, session_id)
    fields = importer.field_catalog(db, user.id, payload.kind)
    return {
        "kind": payload.kind,
        "fields": fields,
        "suggested_mapping": {
            str(index): key
            for index, key in importer.suggest_mapping(
                list(session.headers), fields
            ).items()
        },
    }


@router.post(
    "/import/{session_id}/resolve",
    response_model=schemas.ImportResolveResponse,
)
def resolve_import_values(
    session_id: uuid.UUID,
    payload: schemas.ImportResolveRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The Resolve matches step (smart matching, 2026-10-19): for
    the file's distinct dealer / brand / category / tag / location
    values, what's already known (normalized-exact matches and
    remembered answers — automatic, but listed) and what still
    needs the user's answer (fuzzy candidates — never auto-merged).
    Read-only: answers travel with the dry run / confirm."""
    session = _session_or_404(db, user, session_id)
    try:
        mapping = importer.validate_mapping(
            db, user.id, payload.mapping, payload.kind, len(session.headers)
        )
    except importer.ImportMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    rows = importer.session_rows(session)
    return matching.build_plan(db, user.id, rows, mapping)


@router.post(
    "/import/{session_id}/dry-run",
    response_model=schemas.ImportDryRunPublic,
)
def dry_run_import(
    session_id: uuid.UUID,
    payload: schemas.ImportRunRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    session = _session_or_404(db, user, session_id)
    try:
        return importer.dry_run(
            db,
            user.id,
            session,
            payload.kind,
            payload.mapping,
            payload.skip_duplicates,
            payload.resolutions,
        )
    except importer.ImportMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/import/{session_id}/confirm",
    response_model=schemas.ImportSummaryPublic,
)
def confirm_import(
    session_id: uuid.UUID,
    payload: schemas.ImportRunRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    session = _session_or_404(db, user, session_id)
    try:
        return importer.confirm_import(
            db,
            user.id,
            session,
            payload.kind,
            payload.mapping,
            payload.skip_duplicates,
            payload.resolutions,
        )
    except importer.ImportMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/import/learned",
    response_model=list[schemas.LearnedMappingPublic],
)
def list_learned_mappings(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Settings → Import matching: the answers the importer
    remembers for this user."""
    return matching.list_learned(db, user.id)


@router.delete("/import/learned/{mapping_id}", status_code=204)
def delete_learned_mapping(
    mapping_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Forget one remembered answer — the next import carrying
    that value asks again. A foreign id is the same 404 as a
    missing one."""
    if not matching.delete_learned(db, user.id, mapping_id):
        raise HTTPException(status_code=404, detail="Mapping not found")


@router.delete("/import/{session_id}", status_code=204)
def discard_import_session(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    session = _session_or_404(db, user, session_id)
    importer.delete_session(db, session)
