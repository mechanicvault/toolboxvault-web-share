"""Module control (module doctrine, owner 2026-10-18).

Three pieces:

1. users.is_operator — the operator flag gating /api/admin/*.
   Granted here to the owner's own account and the QA smoke-test
   account (matched by email; a no-op where the account doesn't
   exist, e.g. a fresh dev database).
2. module_state — one row per feature module: the global switch.
3. module_access — one row per (feature module, account group):
   the operator's assignment matrix.

Both control tables are seeded from the feature manifests'
default_groups so the day-one matrix reproduces the access rules
that were hard-coded before this migration: inventory serves
mechanic_technician only; shared_tools serves mechanic_technician
+ shop_company; both modules globally on.

Revision ID: 0008_module_control
Revises: 0007_notifications
Create Date: 2026-10-18
"""

import uuid
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_module_control"
down_revision: str | Sequence[str] | None = "0007_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (module_id, [assigned groups]) — mirrors the manifests'
# default_groups (inventory, shared_tools). The service also falls
# back to the manifests when rows are absent, so the two can never
# disagree in effect.
_FEATURE_MODULES: list[tuple[str, list[str]]] = [
    ("inventory", ["mechanic_technician"]),
    ("shared_tools", ["mechanic_technician", "shop_company"]),
]

_ACCOUNT_GROUPS = [
    "mechanic_technician",
    "shop_company",
    "tool_dealer",
    "insurance",
]

# Operators granted at migration time (owner + QA smoke account).
_OPERATOR_EMAILS = ["mechanicltz@gmail.com", "smoke-test@toolboxvault.com"]


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_operator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # The two addresses are fixed constants from the build spec —
    # inlined on purpose: bound params render as NULL in offline
    # --sql dumps, which would silently grant nobody if such a dump
    # were ever applied by hand. These are not user input.
    for email in _OPERATOR_EMAILS:
        op.execute(
            f"UPDATE users SET is_operator = true WHERE email = '{email}'"
        )

    op.create_table(
        "module_state",
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column(
            "globally_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("module_id"),
    )
    op.create_table(
        "module_access",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("account_group", sa.String(length=50), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "module_id", "account_group", name="uq_module_access_cell"
        ),
    )
    op.create_index("ix_module_access_module_id", "module_access", ["module_id"])

    module_state = sa.table(
        "module_state",
        sa.column("module_id", sa.String),
        sa.column("globally_enabled", sa.Boolean),
    )
    module_access = sa.table(
        "module_access",
        sa.column("id", sa.UUID),
        sa.column("module_id", sa.String),
        sa.column("account_group", sa.String),
        sa.column("enabled", sa.Boolean),
    )

    op.bulk_insert(
        module_state,
        [
            {"module_id": module_id, "globally_enabled": True}
            for module_id, _ in _FEATURE_MODULES
        ],
    )
    op.bulk_insert(
        module_access,
        [
            {
                "id": uuid.uuid4(),
                "module_id": module_id,
                "account_group": group,
                "enabled": group in assigned,
            }
            for module_id, assigned in _FEATURE_MODULES
            for group in _ACCOUNT_GROUPS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_module_access_module_id", table_name="module_access")
    op.drop_table("module_access")
    op.drop_table("module_state")
    op.drop_column("users", "is_operator")
