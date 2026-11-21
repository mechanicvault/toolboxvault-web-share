"""0096: the downloads tier + release-scoped announcements
(open signup, owner order 2026-11-09).

Two changes, both data/column additions — no table is created,
no existing column changes shape:

1. module_tier_access gains the "downloads" switchboard cells.
   The downloads rung (core/tiers.py) is the limited level a
   no-code signup lands on while the teaser gate is up; the tier
   layer reaches it only through an explicit cell — the service
   reads NO fallback for this key. This seed writes the level's
   starting world: downloads ON for prints (the 3D Print Files
   member abilities) and support (Help & Support — tickets are
   an essential, not a feature), OFF for every other feature
   module.

   Seeding follows the switchboard's own first-write rule
   (module_control.set_tier_assignment): a module whose cells
   are only partly written would read its missing cells as OFF,
   so any module missing cells gets ALL of them materialized at
   their current effective values (rows present ⇒ stored value,
   missing ⇒ off; no rows at all ⇒ the module's global state,
   the 0067 fallback) with only the downloads cell taking the
   seed value above. A fully-seeded module gains exactly one
   row. Idempotent: a cell that already exists is never touched.

2. feature_announcements gains two nullable columns for the
   module release events (module_routes' tier flip):
   release_module_id (the feature the announcement releases;
   the fan-out renders its copy per recipient, in their
   language) and audience_user_ids (a JSON list of the accounts
   that gained the module — the fan-out honors it when set).
   NULL on both = an operator-composed announcement to every
   active account, exactly as the table has always behaved.

Explicit DDL + table-level inserts only — no model __table__
objects, no hand-written SQL (the 0084/0089/0090 posture). Every
column name and type was verified against the live production
schema immediately before shipping (production at 0095:
module_tier_access = id/module_id/tier/enabled/updated_at with
uq_module_tier_access_cell; feature_announcements as created by
0091, no release columns present).
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0096_downloads_tier"
down_revision = "0095_print_media"
branch_labels = None
depends_on = None

# The feature modules registered at this migration (registry.py's
# FEATURE_MODULES — the same hardcoded-list posture as 0067's
# seed; a module registered later gets its downloads cell from
# the admin's first write, and reads OFF until then by design).
_FEATURE_MODULES = (
    "inventory",
    "shared_tools",
    "ai_assistant",
    "borrowing",
    "dealers",
    "reports",
    "maintenance",
    "claims",
    "disaster_claims",
    "parts",
    "messaging",
    "marketplace",
    "forum",
    "wishlist",
    "truck_accounts",
    "feedback",
    "catalog",
    "support",
    "tool_expansion",
    "flyers",
    "prints",
)

# The keys that predate this migration (0067's vocabulary).
_EXISTING_KEYS = ("normal", "moderator", "moderator_admin", "beta")

# The downloads level's starting world: the two modules its
# accounts may reach from day one.
_DOWNLOADS_ON = frozenset({"prints", "support"})


def upgrade() -> None:
    op.add_column(
        "feature_announcements",
        sa.Column("release_module_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "feature_announcements",
        sa.Column("audience_user_ids", sa.JSON(), nullable=True),
    )

    tier_access = sa.table(
        "module_tier_access",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("module_id", sa.String(64)),
        sa.column("tier", sa.String(32)),
        sa.column("enabled", sa.Boolean()),
    )
    module_state = sa.table(
        "module_state",
        sa.column("module_id", sa.String(64)),
        sa.column("globally_enabled", sa.Boolean()),
    )
    bind = op.get_bind()
    globals_ = {
        row.module_id: bool(row.globally_enabled)
        for row in bind.execute(sa.select(module_state)).fetchall()
    }
    existing: dict[str, dict[str, bool]] = {}
    for row in bind.execute(sa.select(tier_access)).fetchall():
        existing.setdefault(row.module_id, {})[row.tier] = bool(row.enabled)

    rows = []
    for module_id in _FEATURE_MODULES:
        stored = existing.get(module_id)
        if stored is not None and "downloads" in stored:
            continue  # already seeded — never touch an existing cell
        if stored:
            # Rows present: a missing cell currently reads OFF.
            current = {key: stored.get(key, False) for key in _EXISTING_KEYS}
        else:
            # No rows at all: every key currently reads the
            # module's global state (missing row = enabled).
            enabled = globals_.get(module_id, True)
            current = {key: enabled for key in _EXISTING_KEYS}
        for key in _EXISTING_KEYS:
            if stored is None or key not in stored:
                rows.append(
                    {
                        "id": uuid.uuid4(),
                        "module_id": module_id,
                        "tier": key,
                        "enabled": current[key],
                    }
                )
        rows.append(
            {
                "id": uuid.uuid4(),
                "module_id": module_id,
                "tier": "downloads",
                "enabled": module_id in _DOWNLOADS_ON,
            }
        )
    if rows:
        op.bulk_insert(tier_access, rows)


def downgrade() -> None:
    # The downloads cells go; any companion cells the upgrade
    # materialized stay — they spell out exactly the values the
    # pre-migration fallback already read, so behavior is
    # identical with or without them.
    tier_access = sa.table(
        "module_tier_access",
        sa.column("module_id", sa.String(64)),
        sa.column("tier", sa.String(32)),
    )
    op.execute(
        tier_access.delete().where(tier_access.c.tier == "downloads")
    )
    op.drop_column("feature_announcements", "audience_user_ids")
    op.drop_column("feature_announcements", "release_module_id")
