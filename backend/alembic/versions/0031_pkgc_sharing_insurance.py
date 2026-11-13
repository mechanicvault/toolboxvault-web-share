"""Package C (2026-10-19) — sharing rules + My Insurance.

Ryan's review round 1, items 15–17: sharing should follow RULES,
not one-by-one picking, and a claim should know the owner's agent.

- share_rules — per (owner, recipient group) scope rules for tier
  sharing: category | location (subtree) | tag | all, with the
  per-rule include-addons answer for matched sets. Resolved
  dynamically at read time; stores no item ids.
- share_exclusions — per (owner, group) item withholdings that
  beat both picks and rules at resolution.
- peer_share_exclusion_rules — the same scope model in peer
  sharing's withholding direction (peer is default-include):
  category | location | tag scopes whose items never reach the
  crew list.
- insurance_profiles — one row per user: insurer company, agent
  name/phone/email, policy number, notes (Settings → My
  Insurance).
- claims.agent_name / agent_phone / agent_email — the agent block
  snapshotted onto each claim at creation; existing claims get
  empty strings (they predate profiles — no backfill is honest).

Revision ID: 0031_pkgc_sharing_insurance
Revises: 0030_import_value_matching
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_pkgc_sharing_insurance"
down_revision: str | None = "0030_import_value_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "share_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_group", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_value", sa.String(length=500), nullable=False),
        sa.Column("scope_ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "include_addons",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "recipient_group",
            "scope",
            "scope_value",
            "scope_ref_id",
            name="uq_share_rule_owner_group_scope",
        ),
    )
    op.create_index("ix_share_rules_owner_id", "share_rules", ["owner_id"])

    op.create_table(
        "share_exclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_kind", sa.String(length=20), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("battery_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_group", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["battery_id"], ["batteries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "item_kind",
            "tool_id",
            "battery_id",
            "recipient_group",
            name="uq_share_exclusion_owner_item_group",
        ),
    )
    op.create_index(
        "ix_share_exclusions_owner_id", "share_exclusions", ["owner_id"]
    )
    op.create_index(
        "ix_share_exclusions_tool_id", "share_exclusions", ["tool_id"]
    )
    op.create_index(
        "ix_share_exclusions_battery_id", "share_exclusions", ["battery_id"]
    )

    op.create_table(
        "peer_share_exclusion_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_value", sa.String(length=500), nullable=False),
        sa.Column("scope_ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "scope",
            "scope_value",
            "scope_ref_id",
            name="uq_peer_exclusion_rule_owner_scope",
        ),
    )
    op.create_index(
        "ix_peer_share_exclusion_rules_owner_id",
        "peer_share_exclusion_rules",
        ["owner_id"],
    )

    op.create_table(
        "insurance_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("insurer_company", sa.String(length=300), nullable=False),
        sa.Column("agent_name", sa.String(length=300), nullable=False),
        sa.Column("agent_phone", sa.String(length=60), nullable=False),
        sa.Column("agent_email", sa.String(length=320), nullable=False),
        sa.Column("policy_number", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_insurance_profiles_user"),
    )
    op.create_index(
        "ix_insurance_profiles_user_id", "insurance_profiles", ["user_id"]
    )

    for column, length in (
        ("agent_name", 300),
        ("agent_phone", 60),
        ("agent_email", 320),
    ):
        op.add_column(
            "claims",
            sa.Column(
                column,
                sa.String(length=length),
                server_default="",
                nullable=False,
            ),
        )


def downgrade() -> None:
    for column in ("agent_email", "agent_phone", "agent_name"):
        op.drop_column("claims", column)
    op.drop_index("ix_insurance_profiles_user_id", table_name="insurance_profiles")
    op.drop_table("insurance_profiles")
    op.drop_index(
        "ix_peer_share_exclusion_rules_owner_id",
        table_name="peer_share_exclusion_rules",
    )
    op.drop_table("peer_share_exclusion_rules")
    op.drop_index("ix_share_exclusions_battery_id", table_name="share_exclusions")
    op.drop_index("ix_share_exclusions_tool_id", table_name="share_exclusions")
    op.drop_index("ix_share_exclusions_owner_id", table_name="share_exclusions")
    op.drop_table("share_exclusions")
    op.drop_index("ix_share_rules_owner_id", table_name="share_rules")
    op.drop_table("share_rules")
