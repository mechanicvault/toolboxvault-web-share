"""Warranty service requests (dealer build, 2026-10-20 — owner
design 07:43): when a user marks a tool or battery broken and the
item's dealer company has REGISTERED agents on the platform, the
repair flow offers "Send to my dealer". The send shows the exact
payload first (the requester's name/contact per their profile,
the item's identity, the problem, purchase date, computed
warranty status) and only sends on confirm.

Since the repairs ∪ claims merge (2026-11-04) the request rides
the item's warranty CLAIM (it used to ride the retired repair
record): eligibility/send take the claim's id, the problem is
the claim's description, and the request row's claim_id points
at the claim.

No registered agents (or no company tag) means nothing sends —
the existing private-dealer flow stands, and the eligibility
answer says why, honestly, instead of pretending.

Routing: the requester's PREFERRED agent(s) for the company get
it first and exclusively — they chose those people. Without a
preferred agent, every registered agent representing the company
whose service area covers the requester is offered it (the
requester's area from their public area label / postal ZIP); if
coverage can't be determined, ALL representing agents are routed
— a request must never die because a point couldn't be plotted.
First agent to CLAIM owns it; the rest see it as taken.

Private companies (not directory/platform) never route: there is
no registered agent OF a private company — representations only
exist for directory companies — so the check is simply "does any
active user represent this company".
"""

import re
import uuid

from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.dealers import areas, models, portal, service

KIND_REQUEST_RECEIVED = "warranty_request_received"
KIND_REQUEST_CLAIMED = "warranty_request_claimed"
KIND_REQUEST_STATUS = "warranty_request_status"

_STATUS_LABELS = {
    models.WR_UNCLAIMED: "Waiting for an agent",
    models.WR_RECEIVED: "Received",
    models.WR_IN_PROCESS: "In process",
    models.WR_RESOLVED: "Resolved",
}


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


# -- loading -----------------------------------------------------------------


def _load_claim(db: Session, owner_id: uuid.UUID, claim_id: uuid.UUID):
    """The owner's warranty claim + a small context for its first
    line (the item identity the request snapshots). Returns
    (claim, ctx) or None — a foreign or non-warranty claim is
    indistinguishable from a missing one. ctx.item_kind is the
    ITEM-resolution kind ("set" claims resolve to their tool
    record, so they read "tool" here)."""
    from types import SimpleNamespace

    from app.modules.claims import models as claim_models

    claim = db.get(claim_models.Claim, claim_id)
    if (
        claim is None
        or claim.owner_id != owner_id
        or claim.kind != claim_models.KIND_WARRANTY
    ):
        return None
    line = (
        db.query(claim_models.ClaimLine)
        .filter(claim_models.ClaimLine.claim_id == claim.id)
        .order_by(claim_models.ClaimLine.created_at)
        .first()
    )
    if line is None:
        return None
    ctx = SimpleNamespace(
        claim=claim,
        item_kind=(
            "tool" if line.target_kind == "set" else line.target_kind
        ),
        target_kind=line.target_kind,
        item_id=line.target_id,
        item_name=line.target_name,
        problem=claim.description or "",
    )
    return claim, ctx


def _load_item(db: Session, owner_id: uuid.UUID, ctx):
    from app.modules.inventory import models as inventory_models

    if ctx.item_kind == "tool":
        item = db.get(inventory_models.Tool, ctx.item_id)
    elif ctx.item_kind == "battery":
        item = db.get(inventory_models.Battery, ctx.item_id)
    else:
        item = db.get(inventory_models.SetPiece, ctx.item_id)
    if item is None or item.owner_id != owner_id:
        return None
    return item


def _company_for(db: Session, claim, ctx, item) -> models.DealerCompany | None:
    from app.modules.inventory import models as inventory_models

    # The claim carries its dealer (merge, 2026-11-04): the
    # company the claim was filed under is the company the
    # request goes to. The item's live tag is the fallback.
    company_id = claim.dealer_company_id
    if company_id is None:
        company_id = getattr(item, "dealer_company_id", None)
    if company_id is None and ctx.item_kind == "piece":
        parent = db.get(inventory_models.Tool, item.set_id)
        if parent is not None:
            company_id = parent.dealer_company_id
    if company_id is None:
        return None
    return db.get(models.DealerCompany, company_id)


def registered_agents(db: Session, company_id: uuid.UUID) -> list[core_models.User]:
    """Active users representing this company (the 'registered
    agents' of the design; verification is a trust badge, not a
    routing gate)."""
    rows = (
        db.query(models.CompanyRepresentation)
        .filter(models.CompanyRepresentation.company_id == company_id)
        .all()
    )
    agents = []
    for rep in rows:
        user = db.get(core_models.User, rep.agent_user_id)
        if user is not None and user.is_active:
            agents.append(user)
    agents.sort(key=lambda u: u.name.lower())
    return agents


def _display_name(db: Session, user: core_models.User) -> str:
    profile = portal.get_profile(db, user.id)
    if profile is not None and profile.display_name:
        return profile.display_name
    return user.name


# -- the payload ---------------------------------------------------------------


def build_payload(db: Session, requester: core_models.User, ctx, item) -> dict:
    """The EXACT snapshot a send would carry — the eligibility
    answer renders it as the preview, and send() stores it."""
    from app.modules.inventory import service as inventory_service

    serials: list[str] = []
    if ctx.item_kind == "tool":
        serials = [s for s in (item.serial_numbers or []) if s] or (
            [item.serial_number] if item.serial_number else []
        )
        brand, model = item.brand, item.model
        purchase_date, status = item.purchase_date, inventory_service.warranty_status_of(item)
    elif ctx.item_kind == "battery":
        serials = [item.serial_number] if item.serial_number else []
        brand, model = item.brand, item.model
        purchase_date, status = item.purchase_date, inventory_service.warranty_status_of(item)
    else:  # piece: identity rides the piece; brand the parent set's
        from app.modules.inventory import models as inventory_models

        parent = db.get(inventory_models.Tool, item.set_id)
        serials = [item.serial_number] if item.serial_number else []
        brand = parent.brand if parent is not None else ""
        model = item.part_number or ""
        purchase_date, status = item.purchase_date, "unknown"
    return {
        "requester_name": requester.name,
        "requester_email": requester.email,
        "requester_phone": requester.contact_phone or requester.phone or "",
        "requester_area": requester.public_area_label or "",
        "item_name": item.name or ctx.item_name,
        "brand": brand or "",
        "model": model or "",
        "serials": serials,
        "problem": ctx.problem or "",
        "purchase_date": purchase_date.isoformat() if purchase_date else None,
        "warranty_status": status,
    }


def existing_open_request(db: Session, claim_id: uuid.UUID):
    return (
        db.query(models.WarrantyServiceRequest)
        .filter(
            models.WarrantyServiceRequest.claim_id == claim_id,
            models.WarrantyServiceRequest.status.in_(models.WR_OPEN_STATUSES),
        )
        .order_by(models.WarrantyServiceRequest.created_at.desc())
        .first()
    )


def latest_request_for_claim(db: Session, claim_id: uuid.UUID):
    return (
        db.query(models.WarrantyServiceRequest)
        .filter(
            models.WarrantyServiceRequest.claim_id == claim_id
        )
        .order_by(models.WarrantyServiceRequest.created_at.desc())
        .first()
    )


def eligibility(db: Session, requester: core_models.User, claim_id: uuid.UUID) -> dict:
    """The claim page's dealer box: can this claim be sent to the
    dealer, to whom, and with exactly what payload? Always
    answers honestly — `available` False carries the reason,
    never a dead end."""
    loaded = _load_claim(db, requester.id, claim_id)
    if loaded is None:
        raise service.DealerError("That claim isn't yours.", status_code=404)
    claim, ctx = loaded
    base: dict = {"available": False, "reason": "", "company_name": ""}
    existing = latest_request_for_claim(db, claim_id)
    if existing is not None:
        base["existing_request"] = serialize_request(db, existing, requester.id)
        if existing.status in models.WR_OPEN_STATUSES:
            base["reason"] = "already_sent"
            return base
    from app.modules.claims import models as claim_models

    if (
        claim.status not in claim_models.WARRANTY_OPEN_STATUSES
        or claim.closed_at is not None
    ):
        base["reason"] = "claim_closed"
        return base
    item = _load_item(db, requester.id, ctx)
    if item is None:
        base["reason"] = "That item couldn't be found."
        return base
    company = _company_for(db, claim, ctx, item)
    if company is None:
        base["reason"] = "no_company"
        return base
    # The requester's own name for the dealer (personal edits,
    # 2026-11-05): the eligibility answer speaks to HIM. The
    # request SNAPSHOT further down keeps the directory name —
    # it is the record both parties share.
    base["company_name"] = service.personal_company_name(db, requester.id, company)
    agents = registered_agents(db, company.id)
    if not agents:
        base["reason"] = "no_agents"
        return base
    preferred = [
        row.agent_user_id
        for row in service.list_preferred(db, requester.id)
        if row.company_id == company.id and row.agent_user_id is not None
    ]
    base.update(
        {
            "available": True,
            "reason": "",
            "has_preferred_agent": bool(preferred),
            "preferred_agent_names": [
                _display_name(db, db.get(core_models.User, uid))
                for uid in preferred
                if db.get(core_models.User, uid) is not None
            ],
            "registered_agent_count": len(agents),
            "payload": build_payload(db, requester, ctx, item),
        }
    )
    return base


# -- routing ---------------------------------------------------------------------

_ZIP_IN_TEXT = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def _requester_point(db: Session, requester: core_models.User):
    """Best-effort point for the requester: their public area
    label geocoded, else a ZIP pulled from their postal address,
    else None (coverage unknown → route to all)."""
    if requester.public_area_label:
        point = areas.geocode(db, requester.public_area_label)
        if point is not None:
            return point
    match = _ZIP_IN_TEXT.search(requester.postal_address or "")
    if match:
        hit = areas.zip_centroid(match.group(1))
        if hit is not None:
            _place, _state, lat, lng = hit
            return {"lat": lat, "lng": lng}
    return None


def route_agents(
    db: Session, requester: core_models.User, company: models.DealerCompany
) -> list[core_models.User]:
    """Preferred first (exclusively); else area-covering
    representatives; else — coverage undeterminable — everyone."""
    preferred_ids = [
        row.agent_user_id
        for row in service.list_preferred(db, requester.id)
        if row.company_id == company.id and row.agent_user_id is not None
    ]
    agents = registered_agents(db, company.id)
    by_id = {agent.id: agent for agent in agents}
    preferred = [by_id[uid] for uid in preferred_ids if uid in by_id]
    if preferred:
        return preferred
    point = _requester_point(db, requester)
    if point is not None:
        covering = []
        for agent in agents:
            profile = portal.get_profile(db, agent.id)
            if profile is not None and areas.profile_covers_point(
                profile, point["lat"], point["lng"]
            ):
                covering.append(agent)
        if covering:
            return covering
    return agents


# -- send / claim / status ---------------------------------------------------------


def send_request(
    db: Session, requester: core_models.User, claim_id: uuid.UUID
) -> models.WarrantyServiceRequest:
    loaded = _load_claim(db, requester.id, claim_id)
    if loaded is None:
        raise service.DealerError("That claim isn't yours.", status_code=404)
    claim, ctx = loaded
    if existing_open_request(db, claim_id) is not None:
        raise service.DealerError(
            "This claim already has a warranty request in flight — "
            "one at a time, so the dealer isn't spammed twice for the same break."
        )
    from app.modules.claims import models as claim_models

    if (
        claim.status not in claim_models.WARRANTY_OPEN_STATUSES
        or claim.closed_at is not None
    ):
        raise service.DealerError(
            "That claim is finished — there's no open repair to send."
        )
    item = _load_item(db, requester.id, ctx)
    if item is None:
        raise service.DealerError("That item couldn't be found.", status_code=404)
    company = _company_for(db, claim, ctx, item)
    if company is None:
        raise service.DealerError(
            "This item isn't tagged with a dealer company, so there's "
            "no dealer to send it to."
        )
    agents = registered_agents(db, company.id)
    if not agents:
        raise service.DealerError(
            f"No registered agents for {company.name} yet — the request "
            "can't be sent. Your private dealer details on the item still work."
        )
    payload = build_payload(db, requester, ctx, item)
    routed = route_agents(db, requester, company)
    row = models.WarrantyServiceRequest(
        requester_id=requester.id,
        company_id=company.id,
        company_name=company.name,
        claim_id=claim.id,
        item_kind=ctx.item_kind,
        item_id=ctx.item_id,
        item_name=payload["item_name"],
        brand=payload["brand"],
        model=payload["model"],
        serials=payload["serials"],
        problem=payload["problem"],
        purchase_date=record_purchase_date(payload),
        warranty_status=payload["warranty_status"],
        requester_name=payload["requester_name"],
        requester_email=payload["requester_email"],
        requester_phone=payload["requester_phone"],
        requester_area=payload["requester_area"],
        routed_agent_ids=[str(agent.id) for agent in routed],
        status=models.WR_UNCLAIMED,
    )
    db.add(row)
    db.flush()
    for agent in routed:
        inbox.create_notification(
            db,
            agent.id,
            kind=KIND_REQUEST_RECEIVED,
            title=f"Warranty request: {payload['item_name']}",
            body=(
                f"{payload['requester_name']} sent a {company.name} item "
                "in for warranty service. First agent to claim it owns it."
            ),
            data={"request_id": str(row.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def record_purchase_date(payload: dict):
    from datetime import date as _date

    raw = payload.get("purchase_date")
    return _date.fromisoformat(raw) if raw else None


def get_request(db: Session, request_id: uuid.UUID):
    return db.get(models.WarrantyServiceRequest, request_id)


def is_party(db: Session, row: models.WarrantyServiceRequest, user_id: uuid.UUID) -> bool:
    if row.requester_id == user_id or row.claimed_by_id == user_id:
        return True
    return str(user_id) in (row.routed_agent_ids or [])


def serialize_request(
    db: Session, row: models.WarrantyServiceRequest, viewer_id: uuid.UUID
) -> dict:
    routed = []
    for raw_id in row.routed_agent_ids or []:
        try:
            agent_id = uuid.UUID(str(raw_id))
        except ValueError:
            continue
        user = db.get(core_models.User, agent_id)
        if user is not None:
            routed.append(
                {"user_id": agent_id, "display_name": _display_name(db, user)}
            )
    claimed_by = None
    if row.claimed_by_id is not None:
        claimer = db.get(core_models.User, row.claimed_by_id)
        if claimer is not None:
            claimed_by = {
                "user_id": claimer.id,
                "display_name": _display_name(db, claimer),
            }
    return {
        "id": row.id,
        "status": row.status,
        "status_label": status_label(row.status),
        "company_id": row.company_id,
        "company_name": row.company_name,
        "claim_id": row.claim_id,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "item_name": row.item_name,
        "brand": row.brand,
        "model": row.model,
        "serials": list(row.serials or []),
        "problem": row.problem,
        "purchase_date": row.purchase_date.isoformat() if row.purchase_date else None,
        "warranty_status": row.warranty_status,
        "requester_id": row.requester_id,
        "requester_name": (
            "Former member" if row.requester_deleted else row.requester_name
        ),
        "requester_email": row.requester_email,
        "requester_phone": row.requester_phone,
        "requester_area": row.requester_area,
        "requester_deleted": row.requester_deleted,
        "routed_agents": routed,
        "claimed_by": claimed_by,
        "claimed_by_me": row.claimed_by_id == viewer_id,
        "mine": row.requester_id == viewer_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "resolved_at": row.resolved_at,
    }


def list_for_requester(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = (
        db.query(models.WarrantyServiceRequest)
        .filter(models.WarrantyServiceRequest.requester_id == user_id)
        .order_by(models.WarrantyServiceRequest.created_at.desc())
        .all()
    )
    return [serialize_request(db, row, user_id) for row in rows]


def list_for_agent(db: Session, user_id: uuid.UUID) -> list[dict]:
    """The dealer queue: everything routed to me plus everything
    I've claimed, newest first."""
    rows = (
        db.query(models.WarrantyServiceRequest)
        .order_by(models.WarrantyServiceRequest.created_at.desc())
        .all()
    )
    mine = [
        row
        for row in rows
        if row.claimed_by_id == user_id
        or str(user_id) in (row.routed_agent_ids or [])
    ]
    return [serialize_request(db, row, user_id) for row in mine]


def counts_for_agent(db: Session, user_id: uuid.UUID) -> dict:
    rows = list_for_agent(db, user_id)
    return {
        "incoming_unclaimed": sum(
            1
            for r in rows
            if r["status"] == models.WR_UNCLAIMED and not r["claimed_by"]
        ),
        "claimed_open": sum(
            1
            for r in rows
            if r["claimed_by_me"] and r["status"] in (models.WR_RECEIVED, models.WR_IN_PROCESS)
        ),
        "resolved": sum(1 for r in rows if r["status"] == models.WR_RESOLVED),
    }


def claim(db: Session, agent: core_models.User, request_id: uuid.UUID):
    row = get_request(db, request_id)
    if row is None or str(agent.id) not in (row.routed_agent_ids or []):
        raise service.DealerError("That request isn't in your queue.", status_code=404)
    if row.status != models.WR_UNCLAIMED or row.claimed_by_id is not None:
        raise service.DealerError(
            "Another agent already claimed this one — first come, first served."
        )
    row.claimed_by_id = agent.id
    row.status = models.WR_RECEIVED
    inbox.create_notification(
        db,
        row.requester_id,
        kind=KIND_REQUEST_CLAIMED,
        title=f"{row.company_name} warranty: claimed",
        body=(
            f"{_display_name(db, agent)} claimed your warranty request "
            f"for the {row.item_name}."
        ),
        data={"request_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


# The dealer-driven flow: received -> in_process -> resolved
# (received == claimed; a claimer may also resolve directly).
_ALLOWED_TRANSITIONS = {
    models.WR_RECEIVED: {models.WR_IN_PROCESS, models.WR_RESOLVED},
    models.WR_IN_PROCESS: {models.WR_RESOLVED},
}


def set_status(
    db: Session, agent: core_models.User, request_id: uuid.UUID, new_status: str
):
    from datetime import datetime, timezone

    row = get_request(db, request_id)
    if row is None or row.claimed_by_id != agent.id:
        raise service.DealerError("That request isn't yours to update.", status_code=404)
    if new_status not in _ALLOWED_TRANSITIONS.get(row.status, set()):
        raise service.DealerError(
            f"A request that's {status_label(row.status).lower()} can't move "
            f"to {status_label(new_status).lower()}."
        )
    row.status = new_status
    if new_status == models.WR_RESOLVED:
        row.resolved_at = datetime.now(timezone.utc)
    inbox.create_notification(
        db,
        row.requester_id,
        kind=KIND_REQUEST_STATUS,
        title=f"{row.company_name} warranty: {status_label(new_status).lower()}",
        body=(
            f"Your warranty request for the {row.item_name} is now "
            f"{status_label(new_status).lower()}."
        ),
        data={"request_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


# -- export ----------------------------------------------------------------------


def export_rows(db: Session, user_id: uuid.UUID) -> dict:
    """Export summaries (data export → dealers.json): requests I
    sent, and requests routed to / claimed by me as an agent.
    Snapshots only — the same fields the parties see."""
    sent = list_for_requester(db, user_id)
    received = list_for_agent(db, user_id)
    keys = (
        "id", "status", "company_name", "item_name", "brand", "model",
        "serials", "problem", "purchase_date", "warranty_status",
        "requester_name", "created_at",
    )
    return {
        "warranty_requests_sent": [
            {k: r[k] for k in keys if k in r} for r in sent
        ],
        "warranty_requests_received": [
            {k: r[k] for k in keys if k in r} for r in received
        ],
    }


# -- asset history provider (registered into inventory's feed) -----------------


def _status_events_from_journal(
    db: Session, requester_id: uuid.UUID, row: models.WarrantyServiceRequest
) -> list:
    """Claimed / in-process / resolved transitions with their
    real timestamps, read from the request's change-journal
    entries (the request rows carry no transition log)."""
    from app.modules.core import models as core_models
    from app.modules.inventory import history as inventory_history

    entries = db.query(core_models.ChangeJournal).filter(
        core_models.ChangeJournal.user_id == requester_id,
        core_models.ChangeJournal.entity_type == "warranty_request",
        core_models.ChangeJournal.entity_id == row.id,
        core_models.ChangeJournal.action == "update",
    )
    events = []
    claimer = ""
    if row.claimed_by_id is not None:
        user = db.get(core_models.User, row.claimed_by_id)
        if user is not None:
            claimer = _display_name(db, user)
    for entry in entries:
        before_status = (entry.before or {}).get("status")
        after_status = (entry.after or {}).get("status")
        if after_status == before_status:
            continue
        if after_status == models.WR_RECEIVED:
            title = f"Claimed by {claimer}" if claimer else "Claimed by an agent"
        elif after_status == models.WR_IN_PROCESS:
            title = "In process"
        elif after_status == models.WR_RESOLVED:
            title = "Resolved"
        else:
            continue
        events.append(
            inventory_history.HistoryEvent(
                ts=(
                    row.resolved_at
                    if after_status == models.WR_RESOLVED and row.resolved_at
                    else entry.occurred_at
                ),
                kind="warranty",
                title=title,
                detail=row.company_name,
            )
        )
    return events


def history_events(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list:
    """Asset-history provider: warranty service requests the
    owner sent for this item — sent, claimed, in process,
    resolved. A request about one PIECE of a set lands on the
    set's page (the set is the asset the owner is reading)."""
    from app.modules.inventory import history as inventory_history
    from app.modules.inventory import models as inventory_models

    stmt = db.query(models.WarrantyServiceRequest).filter(
        models.WarrantyServiceRequest.requester_id == owner_id
    )
    if item_kind == "tool":
        from sqlalchemy import or_

        piece_ids = [
            piece.id
            for piece in db.query(inventory_models.SetPiece)
            .filter(inventory_models.SetPiece.set_id == item_id)
            .all()
        ]
        conditions = [
            (models.WarrantyServiceRequest.item_kind == "tool")
            & (models.WarrantyServiceRequest.item_id == item_id)
        ]
        if piece_ids:
            conditions.append(
                (models.WarrantyServiceRequest.item_kind == "piece")
                & (models.WarrantyServiceRequest.item_id.in_(piece_ids))
            )
        stmt = stmt.filter(or_(*conditions))
    else:
        stmt = stmt.filter(
            (models.WarrantyServiceRequest.item_kind == item_kind)
            & (models.WarrantyServiceRequest.item_id == item_id)
        )
    rows = stmt.order_by(models.WarrantyServiceRequest.created_at).all()
    events: list = []
    for row in rows:
        link = f"/dealers/{row.company_id}" if row.company_id else None
        detail = row.company_name
        if row.item_kind == "piece":
            detail = f"{row.company_name} · Piece: {row.item_name}"
        events.append(
            inventory_history.HistoryEvent(
                ts=row.created_at,
                kind="warranty",
                title=f"Sent to {row.company_name} for warranty",
                detail=detail,
                link=link,
            )
        )
        transitions = _status_events_from_journal(db, owner_id, row)
        if transitions:
            events.extend(transitions)
        else:
            # No journaled transitions (legacy request): derive
            # the reached states from the row itself.
            if row.claimed_by_id is not None:
                claimer = ""
                user = db.get(core_models.User, row.claimed_by_id)
                if user is not None:
                    claimer = _display_name(db, user)
                events.append(
                    inventory_history.HistoryEvent(
                        ts=row.updated_at,
                        kind="warranty",
                        title=(
                            f"Claimed by {claimer}"
                            if claimer
                            else "Claimed by an agent"
                        ),
                        detail=row.company_name,
                    )
                )
            if row.status == models.WR_IN_PROCESS:
                events.append(
                    inventory_history.HistoryEvent(
                        ts=row.updated_at,
                        kind="warranty",
                        title="In process",
                        detail=row.company_name,
                    )
                )
            if row.status == models.WR_RESOLVED:
                events.append(
                    inventory_history.HistoryEvent(
                        ts=row.resolved_at or row.updated_at,
                        kind="warranty",
                        title="Resolved",
                        detail=row.company_name,
                    )
                )
    return events


from app.modules.inventory import history as _inventory_history  # noqa: E402

_inventory_history.register_history_provider("dealers", history_events)
