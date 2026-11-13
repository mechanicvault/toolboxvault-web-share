"""Community blocks (admin lane, owner ruling 2026-11-06):
per-feature blocks from community life, imposed and lifted by
god + moderator_admin seats only.

A block is surgical, never the platform ban: the member keeps
their account, their inventory, and every other feature —
they simply cannot post or reply in the ONE blocked feature,
enforced here at the write doors of the forum and the boards
(the parts surfaces adopt the same check when Community Parts
unparks; its reserved feature key already exists). The member
is told, in their inbox, which feature is blocked and that a
support ticket can ask for reinstatement.

Every write is audit-logged (the forum audit pattern) and the
block row is lifted, never deleted — the history of who
blocked whom, when, and why stays readable in the queue.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.core import tiers
from app.modules.forum import models

FEATURES = models.COMMUNITY_FEATURES
FEATURE_LABELS = models.FEATURE_LABELS

# Features whose write doors exist today. community_parts is
# carried in the vocabulary (and blockable in advance) but has
# no live door while the module is parked. print_files joined
# with the Downloads Part 2 lane (2026-11-08): its upload and
# comment doors run require_not_blocked like the forums'.
ENFORCED_FEATURES = ("forums", "feedback_boards", "print_files")


class BlockError(Exception):
    """A block action (or a blocked member's write) is refused."""


class BlockNotFound(BlockError):
    """The named block (or member) isn't available."""


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


def _can_block(actor) -> bool:
    """The block gate: god + moderator_admin rungs (the tier
    ladder's reading, operator flag included). Moderators work
    the flag queue but never block — the owner's ruling names
    the two admin rungs."""
    if getattr(actor, "is_operator", False):
        return True
    return tiers.resolved_tier(actor) in ("god", "moderator_admin")


def require_block_admin(actor) -> None:
    if not _can_block(actor):
        raise BlockError(
            "Blocking a member from a community feature is "
            "reserved to the site admins."
        )


# -- the read side -------------------------------------------------------


def active_block(
    db: Session, user_id: uuid.UUID, feature: str
) -> models.CommunityBlock | None:
    return db.scalars(
        select(models.CommunityBlock)
        .where(
            models.CommunityBlock.user_id == user_id,
            models.CommunityBlock.feature == feature,
            models.CommunityBlock.lifted_at.is_(None),
        )
        .order_by(models.CommunityBlock.created_at.desc())
        .limit(1)
    ).first()


def is_blocked(db: Session, user_id: uuid.UUID, feature: str) -> bool:
    return active_block(db, user_id, feature) is not None


def refusal_message(feature: str) -> str:
    """The plain-words refusal a blocked member gets at the
    write door (and the inbox notice's core): what is blocked
    and the road back — a support ticket asking for
    reinstatement."""
    label = FEATURE_LABELS.get(feature, "that part of the community")
    return (
        f"You're blocked from {label} right now, so this "
        "couldn't be posted. If you think that's wrong, open a "
        "support ticket and ask for your access back — the "
        "team can review it there."
    )


def require_not_blocked(db: Session, user_id: uuid.UUID, feature: str) -> None:
    """The write doors' check (forum threads/replies, board
    posts/comments). Raises BlockError with the refusal copy."""
    if is_blocked(db, user_id, feature):
        raise BlockError(refusal_message(feature))


def block_view(db: Session, row: models.CommunityBlock) -> dict:
    member = core_service.get_user_by_id(db, row.user_id)
    blocker = core_service.get_user_by_id(db, row.blocked_by_id)
    lifter = (
        core_service.get_user_by_id(db, row.lifted_by_id)
        if row.lifted_by_id
        else None
    )
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": member.name if member is not None else "",
        "account_number": member.account_number if member is not None else "",
        "feature": row.feature,
        "feature_label": FEATURE_LABELS.get(row.feature, row.feature),
        "reason": row.reason,
        "blocked_by_id": row.blocked_by_id,
        "blocked_by_name": blocker.name if blocker is not None else "",
        "lifted_by_id": row.lifted_by_id,
        "lifted_by_name": lifter.name if lifter is not None else "",
        "lifted_at": row.lifted_at,
        "active": row.lifted_at is None,
        "created_at": row.created_at,
    }


def list_blocks(db: Session, *, active_only: bool = True) -> list[dict]:
    stmt = select(models.CommunityBlock).order_by(
        models.CommunityBlock.created_at.desc()
    )
    if active_only:
        stmt = stmt.where(models.CommunityBlock.lifted_at.is_(None))
    return [block_view(db, row) for row in db.scalars(stmt).all()]


def my_blocks(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(models.CommunityBlock)
        .where(
            models.CommunityBlock.user_id == user_id,
            models.CommunityBlock.lifted_at.is_(None),
        )
        .order_by(models.CommunityBlock.created_at.desc())
    ).all()
    return [block_view(db, row) for row in rows]


# -- the writes ------------------------------------------------------------


def block_user(
    db: Session,
    actor,
    *,
    user_id: uuid.UUID | None = None,
    account_number: str = "",
    feature: str,
    reason: str = "",
) -> dict:
    """Impose one block. The target resolves by id or by EXACT
    account number (the platform's no-enumeration pattern — a
    wrong number is simply "not available"). God-rung accounts
    can't be blocked (the god-account protection, mirrored from
    the admin panel's edit guards), and nobody blocks
    themselves."""
    require_block_admin(actor)
    if feature not in FEATURES:
        raise BlockError("That isn't a community feature.")
    target: core_models.User | None = None
    if user_id is not None:
        target = core_service.get_user_by_id(db, user_id)
    elif (account_number or "").strip():
        target = core_service.get_user_by_account_number(
            db, account_number.strip()
        )
    if target is None or not target.is_active:
        raise BlockNotFound("That member isn't available.")
    if target.id == actor.id:
        raise BlockError("You can't block yourself.")
    if tiers.resolved_tier(target) == "god":
        raise BlockError("The site owner's account can't be blocked.")
    existing = active_block(db, target.id, feature)
    if existing is not None:
        raise BlockError(
            f"That member is already blocked from "
            f"{FEATURE_LABELS[feature]}."
        )
    row = models.CommunityBlock(
        user_id=target.id,
        feature=feature,
        reason=(reason or "").strip()[:500],
        blocked_by_id=actor.id,
    )
    db.add(row)
    db.flush()
    inbox.create_notification(
        db,
        target.id,
        kind=inbox.KIND_COMMUNITY_BLOCKED,
        title=f"You're blocked from {FEATURE_LABELS[feature]}",
        body=(
            f"A site admin has blocked your account from "
            f"{FEATURE_LABELS[feature]}"
            + (f" — {row.reason}" if row.reason else "")
            + ". Everything else on your account works as "
            "usual. If you think that's wrong, open a support "
            "ticket and ask for your access back — the team "
            "can review it there."
        ),
        data={"feature": feature, "block_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    _audit(
        db,
        actor,
        "community.block",
        target.id,
        {"feature": feature, "block_id": str(row.id), "reason": row.reason},
    )
    return block_view(db, row)


def lift_block(db: Session, actor, block_id: uuid.UUID) -> dict:
    """Lift one block (the row stays — lifted, never deleted)
    and tell the member their access is back."""
    require_block_admin(actor)
    row = db.get(models.CommunityBlock, block_id)
    if row is None or row.lifted_at is not None:
        raise BlockNotFound("That block isn't active.")
    row.lifted_by_id = actor.id
    row.lifted_at = _now()
    inbox.create_notification(
        db,
        row.user_id,
        kind=inbox.KIND_COMMUNITY_UNBLOCKED,
        title=f"Your access to {FEATURE_LABELS[row.feature]} is back",
        body=(
            f"A site admin has lifted your block from "
            f"{FEATURE_LABELS[row.feature]} — you can post "
            "there again. Thanks for working it out with the "
            "team."
        ),
        data={"feature": row.feature, "block_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    _audit(
        db,
        actor,
        "community.unblock",
        row.user_id,
        {"feature": row.feature, "block_id": str(row.id)},
    )
    return block_view(db, row)
