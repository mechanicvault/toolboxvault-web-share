"""Dealers routes: the directory, MY private companies/agents, and
MY preferred agents. Everything is gated on the dealers module
being effective for the caller — when the module is off, this whole
tree answers 403 module_unavailable and item dealer tags hide, while
the stored data stays untouched (module removability).
"""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core import vcard
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.core.rate_limit import agent_code_rate_limiter
from app.modules.core import models as core_models
from app.modules.dealers import areas, portal, schemas, service, takeover, warranty
from app.modules.dealers import models as dealer_models

router = APIRouter(dependencies=[Depends(require_module("dealers"))])


def _account(db: Session, user: CurrentUser) -> core_models.User:
    account = db.get(core_models.User, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return account


def _as_422(exc: service.DealerError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _as_http(exc: service.DealerError) -> HTTPException:
    """DealerError with its own status (404 for not-yours cases,
    422 default for rule refusals)."""
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _not_found(what: str = "Company") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _company_views(
    db: Session, user_id: uuid.UUID, companies
) -> list[dict]:
    """Serialize companies FOR this viewer: his personal edits
    (2026-11-05) ride over the directory values, batch-loaded
    in one query. Own companies never carry an edit (their
    direct edit is the path), so they serialize raw."""
    edits = service.personal_edits_for(
        db, user_id, [c.id for c in companies if c.is_directory]
    )
    return [
        service.serialize_company(c, edit=edits.get(c.id)) for c in companies
    ]


@router.get("/companies", response_model=list[schemas.CompanyView])
def list_companies(
    q: str | None = Query(default=None, max_length=200),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    views = _company_views(db, user.id, service.list_companies(db, user.id, q))
    # Directory first, then by the name the VIEWER sees — a
    # dealer he renamed for himself sorts under his name in
    # his own list (the service order is the raw directory's).
    views.sort(key=lambda v: (not v["is_directory"], v["name"].casefold()))
    return views


@router.post(
    "/companies", response_model=schemas.CompanyView, status_code=status.HTTP_201_CREATED
)
def create_private_company(
    payload: schemas.CompanyWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        company = service.create_company(
            db, owner_id=user.id, data=payload.model_dump()
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return service.serialize_company(company)


@router.get("/companies/{company_id}", response_model=schemas.CompanyView)
def get_company(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    return service.serialize_company_for_viewer(db, company, user.id)


@router.put("/companies/{company_id}", response_model=schemas.CompanyView)
def update_private_company(
    company_id: uuid.UUID,
    payload: schemas.CompanyWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.get_own_private_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    try:
        company = service.update_company(db, company, payload.model_dump())
    except service.DealerError as exc:
        raise _as_422(exc)
    return service.serialize_company(company)


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_private_company(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.get_own_private_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    service.delete_company(db, company)


# ---------------------------------------------------------------------
# Personal edits (owner, 2026-11-05): the viewer's OWN details
# for a DIRECTORY dealer. Saving never touches the directory
# row — it writes his personal layer; clearing it (Reset) drops
# the layer and the directory details show again. His own
# private companies refuse here: their PUT above is the edit.
# ---------------------------------------------------------------------


@router.put(
    "/companies/{company_id}/personal-edit",
    response_model=schemas.CompanyView,
)
def save_personal_edit(
    company_id: uuid.UUID,
    payload: schemas.PersonalCompanyWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    try:
        service.save_personal_edit(db, user.id, company, payload.model_dump())
    except service.DealerError as exc:
        raise _as_http(exc)
    return service.serialize_company_for_viewer(db, company, user.id)


@router.delete(
    "/companies/{company_id}/personal-edit",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_personal_edit(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    service.clear_personal_edit(db, user.id, company_id)


# ---------------------------------------------------------------------
# My dealer list (owner directive, 2026-10-31): the caller's own
# customization of the prefilled pick list. Reads/writes here are
# list state only — dealer records live under /companies and are
# never touched by these routes beyond minting one when an entry
# is picked.
# ---------------------------------------------------------------------


def _list_settings_view(db: Session, user_id: uuid.UUID) -> schemas.DealerListSettingsView:
    settings = service.dealer_list_settings(db, user_id)
    edits = service.personal_edits_for(
        db, user_id, [row["company"].id for row in settings["directory"]]
    )
    return schemas.DealerListSettingsView(
        directory=[
            schemas.DirectoryListState(
                company=schemas.CompanyView(
                    **service.serialize_company(
                        row["company"], edit=edits.get(row["company"].id)
                    )
                ),
                hidden=row["hidden"],
            )
            for row in settings["directory"]
        ],
        entries=[
            schemas.DealerListEntryView(**service.serialize_list_entry(db, entry))
            for entry in settings["entries"]
        ],
    )


@router.get("/pick-list", response_model=schemas.DealerPickListView)
def get_pick_list(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.pick_list(db, user.id)
    return schemas.DealerPickListView(
        companies=[
            schemas.CompanyView(**view)
            for view in _company_views(db, user.id, result["companies"])
        ],
        entries=[
            schemas.DealerListEntryView(**service.serialize_list_entry(db, entry))
            for entry in result["entries"]
        ],
    )


@router.get("/list-settings", response_model=schemas.DealerListSettingsView)
def get_list_settings(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _list_settings_view(db, user.id)


@router.post("/directory-hidden", response_model=schemas.DealerListSettingsView)
def hide_directory_company(
    payload: schemas.DirectoryHideRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        service.hide_directory_company(db, user.id, payload.company_id)
    except service.DealerError as exc:
        raise _as_http(exc)
    return _list_settings_view(db, user.id)


@router.delete(
    "/directory-hidden/{company_id}", response_model=schemas.DealerListSettingsView
)
def unhide_directory_company(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.unhide_directory_company(db, user.id, company_id)
    return _list_settings_view(db, user.id)


@router.post(
    "/list-entries",
    response_model=schemas.DealerListEntryView,
    status_code=status.HTTP_201_CREATED,
)
def create_list_entry(
    payload: schemas.DealerListEntryWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry = service.create_list_entry(db, user.id, payload.model_dump())
    except service.DealerError as exc:
        raise _as_422(exc)
    return schemas.DealerListEntryView(**service.serialize_list_entry(db, entry))


@router.put("/list-entries/{entry_id}", response_model=schemas.DealerListEntryView)
def update_list_entry(
    entry_id: uuid.UUID,
    payload: schemas.DealerListEntryWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = service.get_own_list_entry(db, user.id, entry_id)
    if entry is None:
        raise _not_found("List entry")
    try:
        entry = service.update_list_entry(db, entry, payload.model_dump())
    except service.DealerError as exc:
        raise _as_422(exc)
    return schemas.DealerListEntryView(**service.serialize_list_entry(db, entry))


@router.delete("/list-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list_entry(
    entry_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = service.get_own_list_entry(db, user.id, entry_id)
    if entry is None:
        raise _not_found("List entry")
    service.delete_list_entry(db, entry)


@router.post("/list-entries/{entry_id}/use", response_model=schemas.CompanyView)
def use_list_entry(
    entry_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = service.get_own_list_entry(db, user.id, entry_id)
    if entry is None:
        raise _not_found("List entry")
    try:
        company = service.use_list_entry(db, user.id, entry)
    except service.DealerError as exc:
        raise _as_422(exc)
    return service.serialize_company(company)


@router.post("/list-restore", response_model=schemas.DealerListRestoreResult)
def restore_dealer_list(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    counts = service.restore_dealer_list(db, user.id)
    return schemas.DealerListRestoreResult(
        hidden_removed=counts["hidden_removed"],
        entries_removed=counts["entries_removed"],
        settings=_list_settings_view(db, user.id),
    )


# ---------------------------------------------------------------------
# Private agents
# ---------------------------------------------------------------------


@router.get("/agents/private", response_model=list[schemas.PrivateAgentView])
def list_private_agents(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        portal.serialize_private_agent_linked(db, a)
        for a in service.list_private_agents(db, user.id)
    ]


@router.post(
    "/agents/private",
    response_model=schemas.PrivateAgentView,
    status_code=status.HTTP_201_CREATED,
)
def create_private_agent(
    payload: schemas.PrivateAgentCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        agent = service.create_private_agent(db, user.id, payload.model_dump())
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_private_agent_linked(db, agent)


@router.put("/agents/private/{agent_id}", response_model=schemas.PrivateAgentView)
def update_private_agent(
    agent_id: uuid.UUID,
    payload: schemas.PrivateAgentUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent = service.get_own_private_agent(db, user.id, agent_id)
    if agent is None:
        raise _not_found("Agent")
    try:
        agent = service.update_private_agent(
            db, user.id, agent, payload.model_dump(exclude_unset=True)
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_private_agent_linked(db, agent)


@router.delete("/agents/private/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_private_agent(
    agent_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent = service.get_own_private_agent(db, user.id, agent_id)
    if agent is None:
        raise _not_found("Agent")
    try:
        service.delete_private_agent(db, agent)
    except service.DealerError as exc:
        # The linked-record refusal (stage 1): a record a real
        # agent works from can't be deleted — the reason is the
        # answer, in plain words.
        raise _as_http(exc)


# ---------------------------------------------------------------------
# Contact cards: vCard import into PRIVATE agents (agent card
# import lane, 2026-11-07). Import creates the caller's own
# private records only — a registered agent is never created,
# claimed, or touched here.
# ---------------------------------------------------------------------


@router.post("/agents/import/preview", response_model=schemas.AgentImportPreview)
async def preview_agent_import(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Parse an uploaded .vcf and show what WOULD land: one row
    per readable card with the dealer its organization line
    suggests and its likely duplicates flagged, unreadable
    cards as soft errors. Creates nothing."""
    data = await file.read(vcard.MAX_FILE_BYTES + 1)
    if len(data) > vcard.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file is too large for a contact import (2 MB max).",
        )
    cards, total = vcard.parse_vcf(data)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file doesn't contain any contact cards.",
        )
    preview = service.preview_agent_import(db, user.id, cards)
    preview["total_cards"] = total
    return preview


@router.post(
    "/agents/import",
    response_model=schemas.AgentImportResult,
    status_code=status.HTTP_201_CREATED,
)
def import_agents(
    payload: schemas.AgentImportRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create exactly the rows the owner confirmed in the
    preview — each a PRIVATE record through the ordinary
    create path, nothing more, nothing merged."""
    created = service.import_agents(
        db, user.id, [row.model_dump() for row in payload.agents]
    )
    return {
        "created": [
            portal.serialize_private_agent_linked(db, agent) for agent in created
        ],
        "count": len(created),
    }


# ---------------------------------------------------------------------
# Agent-code takeover (2026-11-03): an agent enters a record's
# code and asks to take it over; the owner accepts or declines.
# ---------------------------------------------------------------------


@router.post(
    "/agents/takeover/enter-code", response_model=schemas.TakeoverEnterResult
)
def enter_agent_code(
    payload: schemas.TakeoverEnterCode,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Wrong codes answer generically and count against a
    per-IP + per-account failure budget on the login limiter's
    shape — a code is a capability and guessing must stay
    impractical. Known-code states (pending / already claimed /
    your own record) resolve without a failure: possession of
    the code is what names the record."""
    client_ip = request.client.host if request.client else "unknown"
    limit_key = f"agent-code:{client_ip}:{user.id}"
    retry_after = agent_code_rate_limiter.retry_after(limit_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many code attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    account = _account(db, user)
    try:
        result = takeover.enter_code(db, account, payload.code)
    except service.DealerError as exc:
        agent_code_rate_limiter.record_failure(limit_key)
        raise _as_422(exc)
    agent_code_rate_limiter.record_success(limit_key)
    return result


@router.get("/agents/takeover/mine", response_model=schemas.TakeoverMineView)
def my_takeover_state(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        takeover.require_agent_side(account)
    except service.DealerError as exc:
        raise _as_422(exc)
    return {
        "requests": takeover.my_requests(db, account),
        "claimed": takeover.claimed_records(db, account),
    }


@router.get(
    "/agents/private/{agent_id}/takeover-requests",
    response_model=list[schemas.TakeoverRequestView],
)
def list_takeover_requests(
    agent_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent = service.get_own_private_agent(db, user.id, agent_id)
    if agent is None:
        raise _not_found("Agent")
    account = _account(db, user)
    try:
        return takeover.pending_requests_for_record(db, account, agent)
    except service.DealerError as exc:
        raise _as_http(exc)


@router.post(
    "/agents/takeover/{request_id}/accept",
    response_model=schemas.PrivateAgentView,
)
def accept_takeover_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        agent = takeover.accept_request(db, account, request_id)
    except service.DealerError as exc:
        raise _as_http(exc)
    return portal.serialize_private_agent_linked(db, agent)


@router.post(
    "/agents/takeover/{request_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
)
def decline_takeover_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        takeover.decline_request(db, account, request_id)
    except service.DealerError as exc:
        raise _as_http(exc)


# ---------------------------------------------------------------------
# Preferred agents
# ---------------------------------------------------------------------


@router.get("/preferred", response_model=list[schemas.PreferredAgentView])
def list_preferred(
    company_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        service.serialize_preferred(db, row)
        for row in service.list_preferred(db, user.id, company_id)
    ]


@router.get(
    "/preferred/on-record",
    response_model=schemas.PreferredSummaryView,
)
def preferred_on_record(
    company_id: uuid.UUID = Query(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's preferred-agent SUMMARY for one company
    (owner ruling 2026-11-06): "one" with the agent when
    exactly one preferred agent is flagged — displays name
    him; "many" with no agent when more than one is flagged —
    displays show "Multiple Agents" instead of specifics;
    "none" when the caller has no agent for the company.
    Connections with none flagged resolve the earliest row
    as "one", as before. The item pages' agent line and the
    Warranty tab's current-agent row read it. (A claim's
    FUNCTIONAL default agent is a different read — the
    claims module's own agent_on_record.)"""
    return service.preferred_summary_view(db, user.id, company_id)


@router.post(
    "/preferred",
    response_model=schemas.PreferredAgentView,
    status_code=status.HTTP_201_CREATED,
)
def add_preferred(
    payload: schemas.PreferredAgentCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = service.add_preferred(
            db,
            user.id,
            company_id=payload.company_id,
            private_agent_id=payload.private_agent_id,
            agent_account_number=payload.agent_account_number,
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return service.serialize_preferred(db, row)


@router.delete("/preferred/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_preferred(
    row_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not service.remove_preferred(db, user.id, row_id):
        raise _not_found("Preferred agent")


# ---------------------------------------------------------------------
# The roster + agent record (stage 1, 2026-11-04;
# multi-preferred, 2026-11-05): the dealer Agents tab's data.
# The roster lists the caller's own records + his connected
# platform agents for one company, preferred agents (every
# starred row) first; the record view carries one agent's
# claims and truck slot; the flag endpoint stars/unstars one
# agent at a time — no switch exists anymore.
# ---------------------------------------------------------------------


@router.get(
    "/companies/{company_id}/roster",
    response_model=list[schemas.RosterEntryView],
)
def get_company_roster(
    company_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    if as_visitor:
        # The modeled member's roster for this company: the
        # same roster read keyed on the visitor stand-in's id —
        # no entered records, no connections, so it reads empty
        # exactly as a member with no agents here sees it.
        _require_visitor_manager(db, user, company)
        from app.modules.core import visitor_preview

        return service.company_roster(db, visitor_preview.VISITOR_ID, company)
    return service.company_roster(db, user.id, company)


@router.get(
    "/companies/{company_id}/roster/agent",
    response_model=schemas.RosterAgentDetailView,
)
def get_roster_agent(
    company_id: uuid.UUID,
    kind: str = Query(...),
    ref_id: uuid.UUID = Query(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    if kind not in ("private", "platform"):
        raise _not_found("Agent")
    account = _account(db, user)
    try:
        return service.roster_agent_detail(
            db, account, company, kind=kind, ref_id=ref_id
        )
    except service.DealerError as exc:
        raise _as_http(exc)


@router.get("/companies/{company_id}/roster/agent/export.vcf")
def export_roster_agent_vcf(
    company_id: uuid.UUID,
    kind: str = Query(...),
    ref_id: uuid.UUID = Query(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One roster agent's contact card (.vcf) — the same
    roster authorization as the record view: the company must
    be visible to the caller and the agent on his roster."""
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    if kind not in ("private", "platform"):
        raise _not_found("Agent")
    facts = service.agent_card_facts(
        db, user.id, company, kind=kind, ref_id=ref_id
    )
    if facts is None:
        raise _not_found("Agent")
    body = vcard.build_vcard(
        name=facts["name"],
        phones=facts["phones"],
        emails=facts["emails"],
        org=facts["org"],
        note=facts["note"],
    )
    return Response(
        content=body,
        media_type="text/vcard; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{vcard.download_filename(facts["name"])}"'
            )
        },
    )


@router.post(
    "/preferred/flag",
    response_model=schemas.PreferredAgentView,
    status_code=status.HTTP_201_CREATED,
)
def set_agent_preferred(
    payload: schemas.SetAgentPreferredRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Star or unstar ONE roster agent (multi-preferred,
    2026-11-05): the flag is per agent and independent — no
    switch, no prompt, no claims ever move, no tenure stamps."""
    account = _account(db, user)
    try:
        row = service.set_agent_preferred(
            db,
            account,
            company_id=payload.company_id,
            private_agent_id=payload.private_agent_id,
            agent_user_id=payload.agent_user_id,
            is_preferred=payload.is_preferred,
        )
    except service.DealerError as exc:
        raise _as_http(exc)
    return service.serialize_preferred(db, row)


def _require_visitor_manager(db: Session, user: CurrentUser, company) -> None:
    """"View as visitor" gate (Sweep D5): the preview fetches
    belong to the company's representatives — the dealer-seat
    members who manage this directory record's presence (a
    CompanyRepresentation is that seat). Directory companies
    only: a private company answers 404 to every other member,
    so it has no visitor view to preview. Anyone else already
    reads the plain member view, so their preview request is
    a 403, never a silent swap."""
    rep = (
        db.query(dealer_models.CompanyRepresentation)
        .filter(
            dealer_models.CompanyRepresentation.agent_user_id == user.id,
            dealer_models.CompanyRepresentation.company_id == company.id,
        )
        .first()
        if company.is_directory
        else None
    )
    if rep is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a representative of this company can preview its page as a visitor.",
        )


# ---------------------------------------------------------------------
# Company detail (directory page: facts + listed agents + my
# preferred agents for the company) — dealer portal, 2026-10-19.
# ---------------------------------------------------------------------


# No response_model here on purpose: the public agent cards are
# KEY-DISCIPLINED dicts (a contact key exists only when the agent
# filled it in), and a response model would re-fill the omitted
# keys with nulls. The portal service owns the exact shape
# (schemas.CompanyDetailView documents it).
@router.get("/companies/{company_id}/detail")
def get_company_detail(
    company_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    if as_visitor:
        # "View as visitor" (Sweep D5): the representative's
        # preview fetch — the same detail payload, shaped for
        # a member with no relationship to the company.
        _require_visitor_manager(db, user, company)
        return portal.company_detail_as_visitor(db, company)
    return portal.company_detail(db, _account(db, user), company)


# ---------------------------------------------------------------------
# Dealer intermingling (2026-10-25): the viewer's OWN records for
# this company — their items from it, honest stats, their claims
# touching it. Owner-scoped: the company must be visible to the
# viewer (directory or their own), and every record read is the
# viewer's. The claims block rides when EITHER the claims or the
# dealers module is effective for the viewer (the two-seat gate
# the claims pages use since 66bb8ea); when neither is, the
# payload carries claims=None and the page shows no claims
# areas at all.
# ---------------------------------------------------------------------


@router.get(
    "/companies/{company_id}/my-records",
    response_model=schemas.CompanyMyRecordsView,
)
def get_company_my_records(
    company_id: uuid.UUID,
    as_visitor: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = service.visible_company(db, user.id, company_id)
    if company is None:
        raise _not_found()
    if as_visitor:
        _require_visitor_manager(db, user, company)
    from app.modules.core import module_control

    # Two-seat gate (C-13, Deep Audit Round 2 — mirroring the claim
    # pages' rule from 66bb8ea): the claims block rides when EITHER
    # the claims module OR the dealers module is effective for the
    # viewer, so a dealer-seat representative sees the claims block
    # on their own company's page instead of a silent null. The
    # block's contents stay owner-scoped inside company_my_records
    # (the viewer's own claims touching this company), so opening
    # the gate leaks nothing about anyone else's records.
    claims_on = module_control.effective_for_user(
        db, "claims", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
    ) or module_control.effective_for_user(
        db, "dealers", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
    )
    if as_visitor:
        # The modeled member's own records with this company:
        # none — the same records read, keyed on the visitor
        # stand-in's id, so the stats/items/claims it returns
        # are the empty set a member with no history here sees.
        # The claims-block gate above is computed for the
        # caller as usual: module reach is the page's frame,
        # not part of the personal layer being previewed away.
        from app.modules.core import visitor_preview

        return service.company_my_records(
            db, visitor_preview.VISITOR_ID, company, claims_on=claims_on
        )
    return service.company_my_records(db, user.id, company, claims_on=claims_on)


# ---------------------------------------------------------------------
# Agent profile + photo + representations (the portal proper)
# ---------------------------------------------------------------------


@router.get("/profile/me", response_model=schemas.AgentProfileView)
def get_my_profile(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    return portal.serialize_profile(account, portal.get_profile(db, user.id))


@router.put("/profile/me", response_model=schemas.AgentProfileView)
def update_my_profile(
    payload: schemas.AgentProfileWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        profile = portal.update_profile(
            db, account, payload.model_dump(exclude_unset=True)
        )
    except service.DealerError as exc:
        raise _as_http(exc)
    return portal.serialize_profile(account, profile)


@router.post(
    "/profile/me/photo/upload-url", response_model=schemas.PhotoUploadUrlResponse
)
def profile_photo_upload_url(
    payload: schemas.PhotoUploadUrlRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        return portal.issue_profile_photo_url(account, payload.model_dump())
    except service.DealerError as exc:
        raise _as_422(exc)


@router.post("/profile/me/photo", response_model=schemas.AgentProfileView)
def attach_profile_photo(
    payload: schemas.PhotoAttachRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        profile = portal.attach_profile_photo(db, account, payload.key)
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_profile(account, profile)


@router.delete("/profile/me/photo", response_model=schemas.AgentProfileView)
def remove_profile_photo(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    profile = portal.remove_profile_photo(db, account)
    return portal.serialize_profile(account, profile)


@router.get(
    "/profile/me/representations", response_model=list[schemas.RepresentationView]
)
def list_my_representations(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        portal.serialize_representation(db, row)
        for row in portal.list_representations(db, user.id)
    ]


@router.post(
    "/profile/me/representations",
    response_model=schemas.RepresentationView,
    status_code=status.HTTP_201_CREATED,
)
def add_my_representation(
    payload: schemas.RepresentationCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        row = portal.add_representation(db, account, payload.company_id)
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_representation(db, row)


@router.delete(
    "/profile/me/representations/{rep_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_my_representation(
    rep_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not portal.remove_representation(db, user.id, rep_id):
        raise _not_found("Representation")


# ---------------------------------------------------------------------
# One-tap preferred from a public agent card
# ---------------------------------------------------------------------


@router.post(
    "/preferred/by-agent",
    response_model=schemas.PreferredAddResult,
    status_code=status.HTTP_201_CREATED,
)
def add_preferred_by_agent(
    payload: schemas.PreferredByAgentCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row, created = portal.add_preferred_by_agent(
            db,
            user.id,
            company_id=payload.company_id,
            agent_user_id=payload.agent_user_id,
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return {
        "created": created,
        "preferred": service.serialize_preferred(db, row),
    }


# ---------------------------------------------------------------------
# Private -> platform switch
# ---------------------------------------------------------------------


@router.post(
    "/agents/private/{agent_id}/link", response_model=schemas.PrivateAgentView
)
def link_private_agent(
    agent_id: uuid.UUID,
    payload: schemas.PrivateAgentLink,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ownership checked at the door: another user's record is a
    # 404, never a 422 (its existence must not leak).
    if service.get_own_private_agent(db, user.id, agent_id) is None:
        raise _not_found("Agent")
    try:
        agent = portal.link_private_agent(
            db, user.id, agent_id, payload.agent_account_number
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_private_agent_linked(db, agent)


@router.post(
    "/agents/private/{agent_id}/unlink", response_model=schemas.PrivateAgentView
)
def unlink_private_agent(
    agent_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if service.get_own_private_agent(db, user.id, agent_id) is None:
        raise _not_found("Agent")
    try:
        agent = portal.unlink_private_agent(db, user.id, agent_id)
    except service.DealerError as exc:
        raise _as_422(exc)
    return portal.serialize_private_agent_linked(db, agent)


# ---------------------------------------------------------------------
# Dealer home stats (aggregate counts only — see portal.portal_stats)
# ---------------------------------------------------------------------


@router.get("/stats", response_model=schemas.DealerPortalStats)
def dealer_stats(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return portal.portal_stats(db, user.id)


# ---------------------------------------------------------------------
# Find an Agent (dealer build, 2026-10-20): ZIP / city / address ->
# every publicly listed agent whose territory covers the point.
# No response_model on purpose: the cards are KEY-DISCIPLINED
# dicts (contact keys only when published; the anonymous card
# never carries them), exactly like the company detail cards.
# ---------------------------------------------------------------------

public_router = APIRouter()
"""The anonymous window onto Find-an-Agent: read-only (no contact
actions, no preferred adds — those need an account), the same
posture as the marketplace board's /public twin. The directory
itself is signed-in today; this surface is search-only by design
and leaks nothing the agent didn't publish."""


def _find(db: Session, q: str, company_id, *, public: bool):
    result = areas.find_agents(db, q, company_id=company_id, public=public)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="We couldn't find that place — try a ZIP code, city, or street address.",
        )
    return result


@router.get("/find-agent")
def find_agent(
    q: str = Query(min_length=1, max_length=300),
    company_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _find(db, q, company_id, public=False)


@public_router.get("/find-agent")
def find_agent_public(
    q: str = Query(min_length=1, max_length=300),
    company_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _find(db, q, company_id, public=True)


@router.get("/geocode", response_model=schemas.GeocodeResult)
def geocode_place(
    q: str = Query(min_length=1, max_length=300),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resolve a place for the profile area editor (ZIP + radius
    preview, drawn-map centering). Same cache as Find-an-Agent."""
    point = areas.geocode(db, q)
    if point is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="We couldn't find that place — try a ZIP code, city, or street address.",
        )
    return point


# ---------------------------------------------------------------------
# Find local Agent (stage 3, 2026-11-05): the owner-ruled member
# search — ZIP + radius over the same service-area machinery, the
# reusable seam the dealer Agents tab mounts scoped and the Find
# an Agent page mounts unscoped. No response_model, same
# key-disciplined dicts as find-agent. ZIPs resolve from the
# bundled centroid dataset only — a ZIP the dataset doesn't know
# is an honest 422, never a network guess.
# ---------------------------------------------------------------------


@router.get("/find-local-agent")
def find_local_agent(
    zip_code: str = Query(min_length=5, max_length=10),
    radius_miles: float = Query(
        default=25.0, ge=areas.MIN_RADIUS_MILES, le=areas.MAX_RADIUS_MILES
    ),
    company_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = areas.search_local_agents(
        db,
        user.id,
        zip_code=zip_code,
        radius_miles=radius_miles,
        company_id=company_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="We couldn't find that ZIP code — check it and try again.",
        )
    return result


@router.get("/near-you")
def near_you(
    radius_miles: float = Query(
        default=50.0, ge=areas.MIN_RADIUS_MILES, le=areas.MAX_RADIUS_MILES
    ),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dealers near you (dashboard widget, widget wave 2,
    2026-11-10): the viewer's own ZIP — from the postal address
    on their profile — run through the Find local Agent search.
    Always 200: a missing/unknown ZIP is a STATE in the payload,
    not an error, so the widget can say so plainly and door to
    the profile instead of failing. No response_model, same
    key-disciplined dicts as find-local-agent. The router's
    dealers-module gate is the reach: a seat without dealers
    (the downloads level included) gets 403 module_unavailable
    and is never offered the widget."""
    return areas.near_you(db, _account(db, user), radius_miles=radius_miles)


@router.post(
    "/find-local-agent/connect",
    response_model=schemas.PreferredAddResult,
    status_code=status.HTTP_201_CREATED,
)
def connect_local_agent(
    payload: schemas.PreferredByAgentCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Connect with an agent found by the local search: creates
    the connection row (flagged preferred only when the user
    has no preferred agent for the company yet), idempotently."""
    try:
        row, created = portal.connect_local_agent(
            db,
            user.id,
            company_id=payload.company_id,
            agent_user_id=payload.agent_user_id,
        )
    except service.DealerError as exc:
        raise _as_422(exc)
    return {
        "created": created,
        "preferred": service.serialize_preferred(db, row),
    }


# ---------------------------------------------------------------------
# Warranty service requests (dealer build, 2026-10-20)
# ---------------------------------------------------------------------


@router.get(
    "/warranty-requests/eligibility/{claim_id}",
    response_model=schemas.WarrantyEligibility,
)
def warranty_eligibility(
    claim_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        return warranty.eligibility(db, account, claim_id)
    except service.DealerError as exc:
        raise _as_http(exc)


@router.post(
    "/warranty-requests",
    response_model=schemas.WarrantyRequestView,
    status_code=status.HTTP_201_CREATED,
)
def send_warranty_request(
    payload: schemas.WarrantyRequestCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        row = warranty.send_request(db, account, payload.claim_id)
    except service.DealerError as exc:
        raise _as_http(exc)
    return warranty.serialize_request(db, row, user.id)


@router.get(
    "/warranty-requests/mine", response_model=list[schemas.WarrantyRequestView]
)
def my_warranty_requests(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return warranty.list_for_requester(db, user.id)


@router.get(
    "/warranty-requests/incoming", response_model=list[schemas.WarrantyRequestView]
)
def incoming_warranty_requests(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return warranty.list_for_agent(db, user.id)


@router.get("/warranty-requests/counts", response_model=schemas.WarrantyCounts)
def warranty_counts(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return warranty.counts_for_agent(db, user.id)


@router.get(
    "/warranty-requests/{request_id}", response_model=schemas.WarrantyRequestView
)
def get_warranty_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = warranty.get_request(db, request_id)
    if row is None or not warranty.is_party(db, row, user.id):
        raise _not_found("Warranty request")
    return warranty.serialize_request(db, row, user.id)


@router.post(
    "/warranty-requests/{request_id}/claim",
    response_model=schemas.WarrantyRequestView,
)
def claim_warranty_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        row = warranty.claim(db, account, request_id)
    except service.DealerError as exc:
        raise _as_http(exc)
    return warranty.serialize_request(db, row, user.id)


@router.post(
    "/warranty-requests/{request_id}/status",
    response_model=schemas.WarrantyRequestView,
)
def set_warranty_status(
    request_id: uuid.UUID,
    payload: schemas.WarrantyStatusUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account(db, user)
    try:
        row = warranty.set_status(db, account, request_id, payload.status)
    except service.DealerError as exc:
        raise _as_http(exc)
    return warranty.serialize_request(db, row, user.id)
