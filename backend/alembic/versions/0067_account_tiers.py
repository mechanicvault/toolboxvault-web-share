"""Account tiers + module rollout by tier (owner design, 2026-10-31).

Spec: files/account-tiers-and-module-rollout-2026-10-31.md. Three
pieces, all additive:

1. users.tier — the account's primary rung: normal | moderator |
   moderator_admin | god (core/tiers.py owns the vocabulary and
   the derivation). Backfilled from the pre-tier facts, in
   precedence order: is_operator ⇒ god; role='community_admin' ⇒
   moderator_admin; role='moderator' ⇒ moderator; else normal.
   Production mapping (verified by census before this build):
   mechanicvault (operator) → god; mechanicltz + smoke-test
   (moderator role) → moderator; howto-videos → normal. No
   moderator_admin accounts exist yet — the rung is god's to grant.

2. users.beta_tester — the stackable Beta Tester upgrade flag.
   Defaults False for every existing account; granted by hand
   through the admin panel, never backfilled on.

3. module_tier_access — the module switchboard's per-tier cells
   (module_id, tier) for tier in normal | moderator |
   moderator_admin | beta. Seeded for every feature module from
   its CURRENT global state: globally on ⇒ all four tiers on;
   globally off ⇒ all four off (the parked five: parts, wishlist,
   marketplace, messaging stay dark for every tier; god bypasses
   the layer entirely). The service also falls back to the global
   state when a module has no tier rows, so a module registered
   later behaves exactly as seeded here until god sets its cells.

Downgrade drops the table and both columns; the role/operator
facts the backfill read are untouched, so a downgrade loses
nothing the pre-tier system knew.

Revision ID: 0067_account_tiers
Revises: 0066_claims_agent_scope
Create Date: 2026-10-31
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0067_account_tiers"
down_revision = "0066_claims_agent_scope"
branch_labels = None
depends_on = None

# The feature-module registry at this revision (mirrors
# app.modules.registry.FEATURE_MODULES), with each module's
# production global state at seed time: the four parked modules
# are globally OFF; everything else is on (a module with no
# module_state row reads as enabled, which is the same answer).
_FEATURE_MODULES: list[tuple[str, bool]] = [
    ("inventory", True),
    ("shared_tools", True),
    ("ai_assistant", True),
    ("borrowing", True),
    ("dealers", True),
    ("reports", True),
    ("maintenance", True),
    ("claims", True),
    ("parts", False),
    ("messaging", False),
    ("marketplace", False),
    ("forum", True),
    ("wishlist", False),
    ("truck_accounts", True),
    ("feedback", True),
    ("catalog", True),
    ("support", True),
    ("tool_expansion", True),
]

_TIER_KEYS = ("normal", "moderator", "moderator_admin", "beta")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "tier",
            sa.String(32),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "beta_tester",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill the rung from the pre-tier facts (precedence:
    # operator ⇒ god; community_admin ⇒ moderator_admin;
    # moderator ⇒ moderator; the server default already left
    # everyone else at normal).
    op.execute(
        "UPDATE users SET tier = 'god' WHERE is_operator IS TRUE"
    )
    op.execute(
        "UPDATE users SET tier = 'moderator_admin' "
        "WHERE is_operator IS NOT TRUE AND role = 'community_admin'"
    )
    op.execute(
        "UPDATE users SET tier = 'moderator' "
        "WHERE is_operator IS NOT TRUE AND role = 'moderator'"
    )

    op.create_table(
        "module_tier_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "module_id", "tier", name="uq_module_tier_access_cell"
        ),
    )
    op.create_index(
        "ix_module_tier_access_module_id", "module_tier_access", ["module_id"]
    )

    # Seed the tier cells from each module's global state — but
    # read the LIVE global switch where a module_state row exists,
    # so the seed follows the operator's actual kill switches even
    # if they drift from the snapshot above (the dict supplies the
    # module list and the no-row fallback, True).
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
    stored = {
        row.module_id: bool(row.globally_enabled)
        for row in bind.execute(sa.select(module_state)).fetchall()
    }
    rows = []
    for module_id, snapshot_enabled in _FEATURE_MODULES:
        enabled = stored.get(module_id, snapshot_enabled)
        for tier in _TIER_KEYS:
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "module_id": module_id,
                    "tier": tier,
                    "enabled": enabled,
                }
            )
    op.bulk_insert(tier_access, rows)


def downgrade() -> None:
    op.drop_index("ix_module_tier_access_module_id", table_name="module_tier_access")
    op.drop_table("module_tier_access")
    op.drop_column("users", "beta_tester")
    op.drop_column("users", "tier")
