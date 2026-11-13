"""Module release events (owner order, 2026-11-09): opening a
module to a level that didn't have it must FEEL like a release.

The event hangs off the ONE flip door — the admin tier
assignment (module_routes.admin_set_tier). When a tier cell
flips off → on, the route snapshots the flipped key's audience
BEFORE the flip; this service then works out who actually
GAINED the module (effective after, not effective before —
operator layers only; a user's own switch is their business,
not a release) and, only when somebody gained it, fires the
three release acts:

  (a) NEW badge — the module's menu key is merged into the
      nav.new_badges registry with today's date (merge, never
      replace: other items' badges survive). Freshness stays
      the client's first-week computation (nav_badges.py); a
      stale entry is inert.
  (b) Announcement — one scoped feature_announcements row
      (announcements.queue_announcement with release_module_id
      + the gained accounts as audience_user_ids). The
      announcements job fans it out with per-recipient
      localized release copy.
  (c) Wizard pending state — one onboarding_progress row
      (module:<id>, status "notified") per gained account: the
      exact row the plan's baseline branch would mint lazily,
      written eagerly so the plan surfaces the module as a NEW
      step and its own inbox notification does NOT also fire
      (the announcement above is the notification). The wizard
      itself is untouched: the account-type step still leads
      for a typeless account, and the server-deep refusal (no
      module progress before the type pick) still stands.

A flip that gains nobody — the module still globally off,
unassigned to every group the audience holds, or already
effective for the whole audience through another key — fires
nothing: announcing a door nobody can open would be a lie.
Flips to OFF fire nothing (a module going dark is not a
release; the nav simply loses it, as always).
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import announcements, models, module_control, nav_badges, tiers

# Module id -> the frontend registry name whose nav item carries
# the module's NEW badge (the keys nav_badges stores — frontend
# src/modules/registry.ts `name`). Most are the module's own nav
# item; three modules have no nav item of their own, so their
# badge rides the door users actually take: prints opens from
# the Downloads item, and catalog + the AI assistant live inside
# Inventory's pages. Support's door (the Help page) is not a
# rail item, so its badge key names its registry entry and is
# inert in the rail — the announcement and wizard acts still
# fire for it.
NAV_KEY_BY_MODULE: dict[str, str] = {
    "inventory": "inventory",
    "shared_tools": "peer-shared-tools",
    "ai_assistant": "inventory",
    "borrowing": "borrowing",
    "dealers": "dealers",
    "reports": "reports",
    "maintenance": "repairs",
    "claims": "repairs",
    "disaster_claims": "disaster-claims",
    "parts": "parts",
    "messaging": "messaging",
    "marketplace": "marketplace",
    "forum": "forum",
    "wishlist": "wishlist",
    "truck_accounts": "truck-accounts",
    "feedback": "feedback",
    "catalog": "inventory",
    "support": "support-help",
    "tool_expansion": "tool-expansion",
    "flyers": "flyers",
    "prints": "core-downloads",
}


def audience_for(db: Session, tier_key: str) -> list[models.User]:
    """The accounts a tier cell speaks for: every ACTIVE account
    whose applicable tier keys include the flipped key (god
    resolves through the bypass — always effective, so it can
    never be in a gained set and never receives release noise)."""
    users = list(
        db.scalars(
            select(models.User).where(models.User.is_active.is_(True))
        ).all()
    )
    return [
        user
        for user in users
        if tier_key
        in tiers.applicable_tier_keys(
            tiers.resolved_tier(user), bool(user.beta_tester)
        )
    ]


def effectiveness_snapshot(
    db: Session, module_id: str, audience: list[models.User]
) -> dict[uuid.UUID, bool]:
    """Each audience account's OPERATOR-layer effectiveness for
    the module, right now (no per-user layer: a release is about
    entitlement, not about a switch the user set themselves)."""
    return {
        user.id: module_control.effective_for_user(
            db,
            module_id,
            user.account_types,
            tier=tiers.resolved_tier(user),
            beta_tester=bool(user.beta_tester),
        )
        for user in audience
    }


def on_tier_opened(
    db: Session,
    *,
    module_id: str,
    tier_key: str,
    actor_id: uuid.UUID,
    actor_name: str,
    before: dict[uuid.UUID, bool],
) -> dict | None:
    """Fire the release event for one off→on tier flip. `before`
    is the effectiveness snapshot the route took BEFORE the flip
    (effectiveness_snapshot over audience_for). Returns a small
    summary dict, or None when nobody gained the module (no
    event — see the module docstring)."""
    audience = audience_for(db, tier_key)
    after = effectiveness_snapshot(db, module_id, audience)
    gained = [
        user
        for user in audience
        if after.get(user.id) and not before.get(user.id)
    ]
    if not gained:
        return None

    from app.modules.registry import FEATURE_MODULES

    manifest = FEATURE_MODULES[module_id]

    # (a) The NEW badge — merged into the registry as it stands.
    nav_key = NAV_KEY_BY_MODULE.get(module_id, module_id)
    badges = nav_badges.get_nav_badges(db)
    badges[nav_key] = date.today().isoformat()
    nav_badges.set_nav_badges(db, badges)

    # (b) The scoped announcement. The stored copy is the
    # English rendering (the Admin history's record); the
    # fan-out re-renders per recipient (announcements.py).
    title, body = announcements.release_copy(module_id, "en")
    announcements.queue_announcement(
        db,
        author_id=actor_id,
        author_name=actor_name,
        title=title,
        body=body,
        link=manifest.nav_path,
        release_module_id=module_id,
        audience_user_ids=[str(user.id) for user in gained],
    )

    # (c) The wizard pending rows — one writer, one commit. A
    # row the account already resolved (done/skipped) is left
    # exactly as it stands: resolved steps never re-prompt.
    step_key = f"module:{module_id}"
    existing = {
        row.user_id
        for row in db.query(models.OnboardingProgress)
        .filter(models.OnboardingProgress.step_key == step_key)
        .all()
    }
    for user in gained:
        if user.id in existing:
            continue
        db.add(
            models.OnboardingProgress(
                user_id=user.id,
                step_key=step_key,
                status="notified",
                detail="",
            )
        )
    db.commit()

    return {
        "module": module_id,
        "tier": tier_key,
        "nav_key": nav_key,
        "recipients": len(gained),
    }
