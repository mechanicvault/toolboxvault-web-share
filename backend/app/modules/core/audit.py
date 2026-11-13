"""The audit log (admin panel, owner 2026-10-18: the admin must be
able to "see all audit data" — and every God-privilege action must
leave a trail).

One write path: `record`. Every mutating /api/admin/* endpoint
calls it AFTER its change commits, with the acting operator, a
dotted action name, the target (user id / email / module id / code
/ setting key), and a small JSON detail. Rows are never edited or
deleted by any endpoint; the actor's email is snapshotted onto the
row so the trail stays readable even if the account later changes.

Actions vocabulary:
  module.global_toggle, module.group_assignment,
  module.tier_assignment                               (module control)
  code.create, code.deactivate, grant.create,
  ai_grant.create                                      (billing admin)
  user.operator_grant, user.operator_revoke, user.role_set,
  user.tier_set, user.beta_set,
  user.trial_start, user.free_period, user.ai_credits,
  user.deactivate, user.reactivate                     (users admin)
  ban.create, ban.remove                               (bans admin)
  setting.update                                       (settings admin)
  user.email_change                                    (self-serve email
    change — actor is the user themselves; recorded here because
    an identity move deserves the same trail as an operator act)
  user.tier_converted, user.conversion_request_denied  (tier
    conversion, 2026-11-10 — a downloads-level account's move to
    normal: by its own gate code, actor = the user; by god's
    approval of its one request, actor = the deciding god
    account; a denial is recorded with the decider as actor)

SERVICE INTERFACE (stable):
  - record(db, actor, action=..., target=..., detail=...) -> row
  - list_entries(db, *, actor=None, action=None, since=None,
                 until=None, limit=50, offset=0) -> (rows, total)
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import models


def record(
    db: Session,
    actor,
    *,
    action: str,
    target: str = "",
    detail: dict | None = None,
) -> models.AuditLog:
    """Append one audit row for `actor` (a CurrentUser or a User —
    anything carrying id + email; None records an anonymous/system
    actor). Commits immediately: the trail must survive even if the
    caller's request later fails."""
    row = models.AuditLog(
        actor_user_id=uuid.UUID(str(actor.id)) if actor is not None else None,
        actor_email=(actor.email if actor is not None else "") or "",
        action=action,
        target=str(target)[:200],
        detail=detail or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_entries(
    db: Session,
    *,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[models.AuditLog], int]:
    """The Admin → Audit read: newest first, filterable by actor
    (email substring or exact actor id), action (exact), and a
    created-at window. Returns (page, total)."""
    stmt = select(models.AuditLog)
    count_stmt = select(func.count(models.AuditLog.id))
    if actor:
        needle = actor.strip()
        condition = models.AuditLog.actor_email.ilike(f"%{needle}%")
        try:
            actor_id = uuid.UUID(needle)
        except ValueError:
            actor_id = None
        if actor_id is not None:
            condition = condition | (models.AuditLog.actor_user_id == actor_id)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if action:
        stmt = stmt.where(models.AuditLog.action == action.strip())
        count_stmt = count_stmt.where(models.AuditLog.action == action.strip())
    if since is not None:
        stmt = stmt.where(models.AuditLog.created_at >= since)
        count_stmt = count_stmt.where(models.AuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(models.AuditLog.created_at <= until)
        count_stmt = count_stmt.where(models.AuditLog.created_at <= until)
    total = db.scalar(count_stmt) or 0
    rows = list(
        db.scalars(
            stmt.order_by(models.AuditLog.created_at.desc(), models.AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total
