"""Per-category data removal (audit A11, 2026-10-22).

Settings -> Your data gains a scoped eraser next to the
whole-account delete: pick ONE category, type its name to
confirm, and just that category is removed — through the owning
module's own delete/close functions, so every guard those
modules enforce for single items applies here too.

Rules:
  - All-or-nothing per category: a pre-flight pass runs the
    guards BEFORE anything is deleted; one refusal stops the
    whole category with the guard's own reason.
  - Filed claims and financial ledgers follow their integrity
    rules: claims drafts are removable, filed claims are NOT
    (they close, never delete); truck accounts CLOSE — the
    ledger is the financial record and stays.
  - Forum posts follow the forum's own removal semantics (the
    author's tombstone — threads keep their shape for repliers).
  - Every removal is audit-logged (core.audit) with the counts.
  - The change journal treats these like the ordinary per-item
    erasers (restore rides the journal); only whole-account
    deletion runs in permanent mode.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import audit, models


class RemovalRefused(Exception):
    """A guard or integrity rule refuses this category right
    now; the message is the user-facing reason."""


CATEGORY_ORDER = (
    "inventory",
    "parts",
    "claim-drafts",
    "marketplace",
    "forum",
    "wishlist",
    "truck-accounts",
)

LABELS = {
    "inventory": "Inventory items",
    "parts": "My Parts listings",
    "claim-drafts": "Claim drafts",
    "marketplace": "Tools For Sale listings",
    "forum": "Forum posts",
    "wishlist": "Wishlist items",
    "truck-accounts": "Truck accounts",
}

NOTES = {
    "inventory": "Every tool and battery you own. Locations, categories, and tags stay.",
    "parts": "Every part in My Parts, including pool listings.",
    "claim-drafts": "Draft claims only — filed claims are the insurer-facing record and are closed, never deleted.",
    "marketplace": "Every listing you posted, sold or not.",
    "forum": "Your posts are removed the forum's way — threads keep their shape for the people who replied.",
    "wishlist": "Every item on your wishlist.",
    "truck-accounts": "Closes every open truck account you're part of. The charge/payment ledger stays as the financial record — closing is not erasing.",
}

# Each category belongs to the module that owns its data.
CATEGORY_MODULE = {
    "inventory": "inventory",
    "parts": "parts",
    "claim-drafts": "claims",
    "marketplace": "marketplace",
    "forum": "forum",
    "wishlist": "wishlist",
    "truck-accounts": "truck_accounts",
}


def _visible_categories(db: Session, user: models.User) -> tuple[str, ...]:
    """The categories THIS account's picker may name.

    Chrome reach audit (2026-11-09): the picker rides inside
    Export & delete, a core section every account keeps — but
    the static category list enumerated the whole site (every
    category is a module the downloads level cannot reach, all
    at count 0). For a group-waived account the list follows
    entitlement: a category exists only while its owning
    module is effective for the account (operator/group/tier
    layers; the per-user switch layer deliberately does NOT
    apply — an eraser must not vanish because its owner
    switched the module off). Full accounts get the complete
    list exactly as before.
    """
    from app.modules.core import module_control, tiers

    tier = tiers.resolved_tier(user)
    if not tiers.group_layer_waived(tier):
        return CATEGORY_ORDER
    return tuple(
        category
        for category in CATEGORY_ORDER
        if module_control.effective_for_user(
            db,
            CATEGORY_MODULE[category],
            user.account_types,
            tier=tier,
            beta_tester=bool(getattr(user, "beta_tester", False)),
        )
    )


def _inventory_items(db: Session, user_id: uuid.UUID):
    from app.modules.inventory import service as inventory_service

    tools = inventory_service.list_tools(db, user_id)
    batteries = inventory_service.list_batteries(db, user_id)
    return tools, batteries


def _inventory_block_reason(db: Session, user_id: uuid.UUID) -> str | None:
    """Pre-flight the delete guards over every item; the first
    refusal is the category's reason."""
    from app.modules.inventory import service as inventory_service

    tools, batteries = _inventory_items(db, user_id)
    for tool in tools:
        try:
            inventory_service._run_delete_guards(db, user_id, "tool", tool.id)
        except inventory_service.ToolValidationError as exc:
            return str(exc)
    for battery in batteries:
        try:
            inventory_service._run_delete_guards(db, user_id, "battery", battery.id)
        except inventory_service.ToolValidationError as exc:
            return str(exc)
    return None


def _draft_claims(db: Session, user_id: uuid.UUID):
    from app.modules.claims import models as claim_models

    return list(
        db.scalars(
            select(claim_models.Claim).where(
                claim_models.Claim.owner_id == user_id,
                claim_models.Claim.status == claim_models.STATUS_DRAFT,
            )
        )
    )


def _filed_claim_count(db: Session, user_id: uuid.UUID) -> int:
    from app.modules.claims import models as claim_models

    return len(
        list(
            db.scalars(
                select(claim_models.Claim.id).where(
                    claim_models.Claim.owner_id == user_id,
                    claim_models.Claim.status != claim_models.STATUS_DRAFT,
                )
            )
        )
    )


def _live_forum_posts(db: Session, user_id: uuid.UUID):
    from app.modules.forum import models as forum_models

    return list(
        db.scalars(
            select(forum_models.ForumPost).where(
                forum_models.ForumPost.author_id == user_id,
                forum_models.ForumPost.status.notin_(
                    ("removed_author", "removed_mod")
                ),
            )
        )
    )


def _open_truck_accounts(db: Session, user_id: uuid.UUID):
    from app.modules.truck_accounts import models as truck_models

    return list(
        db.scalars(
            select(truck_models.TruckAccount).where(
                truck_models.TruckAccount.status != "closed",
                (
                    (truck_models.TruckAccount.customer_user_id == user_id)
                    | (truck_models.TruckAccount.dealer_user_id == user_id)
                ),
            )
        )
    )


def _count(db: Session, user: models.User, category: str) -> int:
    uid = user.id
    if category == "inventory":
        tools, batteries = _inventory_items(db, uid)
        return len(tools) + len(batteries)
    if category == "parts":
        from app.modules.parts import service as parts_service

        return len(parts_service.list_parts(db, uid, limit=100000))
    if category == "claim-drafts":
        return len(_draft_claims(db, uid))
    if category == "marketplace":
        from app.modules.marketplace import models as market_models

        return len(
            list(
                db.scalars(
                    select(market_models.SaleListing.id).where(
                        market_models.SaleListing.owner_id == uid
                    )
                )
            )
        )
    if category == "forum":
        return len(_live_forum_posts(db, uid))
    if category == "wishlist":
        from app.modules.wishlist import service as wishlist_service

        return len(wishlist_service.list_items(db, uid))
    if category == "truck-accounts":
        return len(_open_truck_accounts(db, uid))
    return 0


def summaries(db: Session, user: models.User) -> list[dict]:
    """The settings page's picker data: every category with its
    live count, its standing note, and — when a guard already
    refuses — the reason (so the refusal is visible BEFORE the
    user types anything)."""
    out = []
    for category in _visible_categories(db, user):
        note = NOTES[category]
        blocked = None
        if category == "inventory":
            blocked = _inventory_block_reason(db, user.id)
        if category == "claim-drafts":
            filed = _filed_claim_count(db, user.id)
            if filed:
                note += f" ({filed} filed claim{'s' if filed != 1 else ''} stay untouched.)"
        out.append(
            {
                "key": category,
                "label": LABELS[category],
                "count": _count(db, user, category),
                "note": note,
                "blocked_reason": blocked,
            }
        )
    return out


def remove_category(
    db: Session, user: models.User, category: str, confirmation: str
) -> dict:
    """Remove one category. Raises RemovalRefused (409-worthy)
    or ValueError (422-worthy: unknown category / bad
    confirmation)."""
    # A category outside the caller's reach reads as unknown —
    # the same refusal as a category that doesn't exist.
    if category not in CATEGORY_ORDER or category not in _visible_categories(
        db, user
    ):
        raise ValueError("Unknown data category.")
    if (confirmation or "").strip() != category:
        raise ValueError(
            f"Type the category name — {category} — to confirm the removal."
        )
    uid = user.id
    removed: dict[str, int] = {}

    if category == "inventory":
        reason = _inventory_block_reason(db, uid)
        if reason:
            raise RemovalRefused(reason)
        from app.modules.inventory import service as inventory_service

        tools, batteries = _inventory_items(db, uid)
        for tool in tools:
            inventory_service.delete_tool(db, uid, tool.id)
        for battery in batteries:
            inventory_service.delete_battery(db, uid, battery.id)
        removed = {"tools": len(tools), "batteries": len(batteries)}
    elif category == "parts":
        from app.modules.parts import service as parts_service

        parts = parts_service.list_parts(db, uid, limit=100000)
        for part in parts:
            parts_service.delete_part(db, uid, part.id)
        removed = {"parts": len(parts)}
    elif category == "claim-drafts":
        from app.modules.claims import service as claims_service

        drafts = _draft_claims(db, uid)
        for claim in drafts:
            claims_service.delete_claim(db, user, claim.id)
        removed = {"claim_drafts": len(drafts)}
    elif category == "marketplace":
        from app.modules.marketplace import models as market_models
        from app.modules.marketplace import service as market_service

        listings = list(
            db.scalars(
                select(market_models.SaleListing).where(
                    market_models.SaleListing.owner_id == uid
                )
            )
        )
        for listing in listings:
            market_service.delete_listing(db, uid, listing.id)
        removed = {"listings": len(listings)}
    elif category == "forum":
        from app.modules.forum import service as forum_service

        posts = _live_forum_posts(db, uid)
        for post in posts:
            forum_service.delete_post(db, user, post_id=post.id)
        removed = {"posts": len(posts)}
    elif category == "wishlist":
        from app.modules.wishlist import service as wishlist_service

        items = wishlist_service.list_items(db, uid)
        for item in items:
            wishlist_service.delete_item(db, uid, item.id)
        removed = {"wishlist_items": len(items)}
    elif category == "truck-accounts":
        from app.modules.truck_accounts import service as truck_service

        accounts = _open_truck_accounts(db, uid)
        for account in accounts:
            truck_service.close_account(db, user, account)
        removed = {"truck_accounts_closed": len(accounts)}

    audit.record(
        db,
        user,
        action="data_removal",
        target=category,
        detail={"removed": removed},
    )
    return {"category": category, "removed": removed}
