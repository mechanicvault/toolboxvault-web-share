"""Agent-code takeover (owner model, 2026-11-03).

The flow, in the owner's words: the user enters their agent as
a private record; the record carries an agent code; the user
hands the code to the real agent; the agent signs up, enters
the code, and asks to take over the record; the user accepts;
the agent's account links onto THE RECORD — and because claims,
truck accounts and route facts all reference the record, the
agent inherits the record's whole working life in place.

Security posture (the claims H-1 register): a takeover link is
one of the two verified-link bases for an agent seat — the
requester had to possess the owner's secret code AND the owner
had to accept that named account. Nobody can self-serve a
link: an unknown code answers generically, entries are
rate-limited at the route, and a code is used up by a
successful claim.

Audience (owner, 2026-11-04): the agent side of this flow —
entering a code, and the asks/claimed state that rides with it —
belongs to DEALER-group accounts only. A mechanic never sees
the panel, and the endpoints refuse him too, so the hidden
panel is not the only lock; a multi-group account that
includes tool_dealer passes (access is a union, as everywhere).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.dealers import models
from app.modules.dealers.agent_codes import normalize_agent_code
from app.modules.dealers.service import DealerError

GENERIC_CODE_REFUSAL = (
    "That code doesn't match an agent record. Check the code "
    "and try again."
)


def _is_dealer_group(user: core_models.User) -> bool:
    from app.modules.dealers.portal import DEALER_GROUP

    return DEALER_GROUP in (user.account_types or [])


def require_agent_side(user: core_models.User) -> None:
    """Dealer-group gate for the agent side's state reads (the
    panel's asks + claimed records). The refusal is plain here —
    no code is being probed, so there is nothing to protect by
    being vague."""
    if not _is_dealer_group(user):
        raise DealerError(
            "Agent codes are for dealer accounts — add the Tool "
            "Dealer group to your account first."
        )


def _user_label(db: Session, user: core_models.User) -> str:
    profile = db.scalar(
        select(models.AgentProfile).where(models.AgentProfile.user_id == user.id)
    )
    if profile is not None and profile.display_name:
        return profile.display_name
    return user.name


def _company_name(db: Session, record: models.PrivateAgent) -> str:
    if record.company_id is None:
        return ""
    company = db.get(models.DealerCompany, record.company_id)
    return company.name if company is not None else ""


def _notify(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str,
    record: models.PrivateAgent,
    request_id: uuid.UUID,
) -> None:
    inbox.create_notification(
        db,
        user_id,
        kind=kind,
        title=title,
        body=body,
        data={
            "company_id": str(record.company_id) if record.company_id else "",
            "private_agent_id": str(record.id),
            "takeover_request_id": str(request_id),
        },
        commit=False,
    )


# ---------------------------------------------------------------------
# Agent side: enter a code
# ---------------------------------------------------------------------


def enter_code(db: Session, requester: core_models.User, raw_code: str) -> dict:
    """Resolve a code entry. An unknown code raises the GENERIC
    refusal (the route counts it against the rate limiter);
    every known-code state returns an outcome dict — the code
    itself is the capability, so naming the record it belongs to
    is safe, and the owner still decides."""
    if not _is_dealer_group(requester):
        # Outside the panel's audience (owner, 2026-11-04): the
        # SAME generic refusal a wrong code gets — the endpoint
        # never explains itself to a non-dealer caller, and no
        # request or notification is created.
        raise DealerError(GENERIC_CODE_REFUSAL)
    code = normalize_agent_code(raw_code)
    record = None
    if code:
        record = db.scalar(
            select(models.PrivateAgent).where(models.PrivateAgent.agent_code == code)
        )
    if record is None:
        raise DealerError(GENERIC_CODE_REFUSAL)
    base = {
        "company_name": _company_name(db, record),
        "agent_name": record.name,
        "private_agent_id": str(record.id),
        "company_id": str(record.company_id) if record.company_id else None,
    }
    if record.owner_id == requester.id:
        return {**base, "status": "own_record", "request_id": None}
    if record.linked_user_id is not None or record.archived:
        return {**base, "status": "already_claimed", "request_id": None}
    existing = db.scalar(
        select(models.AgentTakeoverRequest).where(
            models.AgentTakeoverRequest.private_agent_id == record.id,
            models.AgentTakeoverRequest.requester_user_id == requester.id,
            models.AgentTakeoverRequest.status == "pending",
        )
    )
    if existing is not None:
        return {**base, "status": "pending", "request_id": str(existing.id)}
    req = models.AgentTakeoverRequest(
        private_agent_id=record.id, requester_user_id=requester.id
    )
    db.add(req)
    db.flush()
    owner = db.get(core_models.User, record.owner_id)
    if owner is not None:
        company = base["company_name"]
        _notify(
            db,
            owner.id,
            kind=inbox.KIND_AGENT_TAKEOVER_REQUESTED,
            title="An agent is asking to take over your agent record",
            body=(
                f"{_user_label(db, requester)} ({requester.account_number}) "
                f"entered the agent code for your record “{record.name}”"
                + (f" at {company}" if company else "")
                + " and is asking to step into it. Nothing changes "
                "unless you accept."
            ),
            record=record,
            request_id=req.id,
        )
    db.commit()
    db.refresh(req)
    return {**base, "status": "pending", "request_id": str(req.id)}


# ---------------------------------------------------------------------
# Owner side: see and answer requests
# ---------------------------------------------------------------------


def pending_requests_for_record(
    db: Session, owner: core_models.User, record: models.PrivateAgent
) -> list[dict]:
    if record.owner_id != owner.id:
        raise DealerError("Agent record not found.", status_code=404)
    rows = db.scalars(
        select(models.AgentTakeoverRequest)
        .where(
            models.AgentTakeoverRequest.private_agent_id == record.id,
            models.AgentTakeoverRequest.status == "pending",
        )
        .order_by(models.AgentTakeoverRequest.created_at.asc())
    ).all()
    out = []
    for req in rows:
        requester = db.get(core_models.User, req.requester_user_id)
        if requester is None:
            continue
        out.append(
            {
                "id": req.id,
                "requester_name": _user_label(db, requester),
                "requester_account_number": requester.account_number,
                "created_at": req.created_at,
            }
        )
    return out


def _owned_request(
    db: Session, owner: core_models.User, request_id: uuid.UUID
) -> tuple[models.AgentTakeoverRequest, models.PrivateAgent]:
    req = db.get(models.AgentTakeoverRequest, request_id)
    if req is None:
        raise DealerError("That request is no longer there.", status_code=404)
    record = db.get(models.PrivateAgent, req.private_agent_id)
    if record is None or record.owner_id != owner.id:
        raise DealerError("That request is no longer there.", status_code=404)
    return req, record


def accept_request(
    db: Session, owner: core_models.User, request_id: uuid.UUID
) -> models.PrivateAgent:
    """Link the record to the requesting agent's account. The
    record stays the working record — preferences keep pointing
    at it, claims and truck accounts keep referencing it — the
    agent simply steps into it, history and all."""
    req, record = _owned_request(db, owner, request_id)
    if req.status != "pending":
        raise DealerError("That request was already answered.")
    requester = db.get(core_models.User, req.requester_user_id)
    if requester is None or not requester.is_active:
        req.status = "declined"
        req.decided_at = datetime.now(timezone.utc)
        db.commit()
        raise DealerError("That account is no longer available.")
    if record.linked_user_id is not None or record.archived:
        req.status = "superseded"
        req.decided_at = datetime.now(timezone.utc)
        db.commit()
        raise DealerError("This agent record has already been claimed.")
    now = datetime.now(timezone.utc)
    record.linked_user_id = requester.id
    record.link_source = "takeover"
    req.status = "accepted"
    req.decided_at = now
    company = _company_name(db, record)
    _notify(
        db,
        requester.id,
        kind=inbox.KIND_AGENT_TAKEOVER_ACCEPTED,
        title="You're now the agent on record",
        body=(
            f"{_user_label(db, owner)} accepted your request. You are "
            f"now the agent on their record “{record.name}”"
            + (f" at {company}" if company else "")
            + " — its claims, truck account and history are yours "
            "to work from here."
        ),
        record=record,
        request_id=req.id,
    )
    # Any other open asks for this record are closed by the
    # claim — their requesters hear the record went to another
    # agent (nothing about the customer beyond what the code
    # already told them).
    others = db.scalars(
        select(models.AgentTakeoverRequest).where(
            models.AgentTakeoverRequest.private_agent_id == record.id,
            models.AgentTakeoverRequest.status == "pending",
            models.AgentTakeoverRequest.id != req.id,
        )
    ).all()
    for other in others:
        other.status = "superseded"
        other.decided_at = now
        _notify(
            db,
            other.requester_user_id,
            kind=inbox.KIND_AGENT_TAKEOVER_DECLINED,
            title="That agent record was claimed by another agent",
            body=(
                f"The record “{record.name}”"
                + (f" at {company}" if company else "")
                + " was claimed by a different agent, so your request "
                "is closed. If that seems wrong, ask the customer for "
                "a fresh code."
            ),
            record=record,
            request_id=other.id,
        )
    db.commit()
    db.refresh(record)
    return record


def decline_request(
    db: Session, owner: core_models.User, request_id: uuid.UUID
) -> None:
    """Nothing changes: the record stays private and unclaimed,
    the code stays live for the agent the owner actually means
    to hand it to, and the requester hears the no."""
    req, record = _owned_request(db, owner, request_id)
    if req.status != "pending":
        raise DealerError("That request was already answered.")
    req.status = "declined"
    req.decided_at = datetime.now(timezone.utc)
    company = _company_name(db, record)
    _notify(
        db,
        req.requester_user_id,
        kind=inbox.KIND_AGENT_TAKEOVER_DECLINED,
        title="Your agent-record request was declined",
        body=(
            f"The customer declined your request to take over the "
            f"record “{record.name}”"
            + (f" at {company}" if company else "")
            + ". Nothing was linked. If you work with this customer, "
            "ask them to check the code they gave you."
        ),
        record=record,
        request_id=req.id,
    )
    db.commit()


# ---------------------------------------------------------------------
# Agent side: my asks and my claimed records
# ---------------------------------------------------------------------


def my_requests(db: Session, user: core_models.User) -> list[dict]:
    rows = db.scalars(
        select(models.AgentTakeoverRequest)
        .where(models.AgentTakeoverRequest.requester_user_id == user.id)
        .order_by(models.AgentTakeoverRequest.created_at.desc())
    ).all()
    out = []
    for req in rows:
        record = db.get(models.PrivateAgent, req.private_agent_id)
        if record is None:
            continue
        owner = db.get(core_models.User, record.owner_id)
        out.append(
            {
                "id": req.id,
                "status": req.status,
                "agent_name": record.name,
                "company_name": _company_name(db, record),
                "company_id": record.company_id,
                "owner_name": owner.name if owner is not None else "",
                "created_at": req.created_at,
                "decided_at": req.decided_at,
            }
        )
    return out


def claimed_records(db: Session, user: core_models.User) -> list[dict]:
    """The customer agent records this account has taken over —
    each one an independent seat, walled in its owner's context
    exactly as the claims/truck resolvers enforce."""
    records = db.scalars(
        select(models.PrivateAgent)
        .where(
            models.PrivateAgent.linked_user_id == user.id,
            models.PrivateAgent.link_source == "takeover",
        )
        .order_by(models.PrivateAgent.updated_at.desc())
    ).all()
    out = []
    for record in records:
        owner = db.get(core_models.User, record.owner_id)
        accepted = db.scalar(
            select(models.AgentTakeoverRequest)
            .where(
                models.AgentTakeoverRequest.private_agent_id == record.id,
                models.AgentTakeoverRequest.requester_user_id == user.id,
                models.AgentTakeoverRequest.status == "accepted",
            )
            .order_by(models.AgentTakeoverRequest.decided_at.desc())
        )
        out.append(
            {
                "private_agent_id": record.id,
                "agent_name": record.name,
                "company_id": record.company_id,
                "company_name": _company_name(db, record),
                "owner_name": owner.name if owner is not None else "",
                "claimed_at": (
                    accepted.decided_at if accepted is not None else record.updated_at
                ),
            }
        )
    return out
