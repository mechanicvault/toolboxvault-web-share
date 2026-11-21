"""Tool Expansion module (owner spec 2026-10-25).

A new module: known addons for the tools and sets a user already
owns, learned across the whole user base by model-number matching.
Suggestions themselves are DERIVED from live inventory at read
time (the community catalog's precedent) — nothing about a
suggestion is stored. The only schema is the two user-control
ledgers Ryan specified:

- tool_expansion_dismissals — "remove this for me": (user, their
  item kind+id, suggested model number) — the suggestion never
  shows for that user on that item again.
- tool_expansion_reports — "not relevant / inaccurate": (user,
  anchor model, suggested model) — one row per user per match;
  when the distinct-reporter count reaches the kill-threshold
  setting, the match stops generating for everyone.

Both key to users.id with the plain FK the module tables use;
core's delete_account sweeps a user's rows with the account (the
marketplace-reports rule: paperwork I filed goes with me).

Revision ID: 0061_tool_expansion
Revises: 0060_claims_two_types
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_tool_expansion"
down_revision = "0060_claims_two_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_expansion_dismissals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("anchor_kind", sa.String(10), nullable=False),
        sa.Column(
            "anchor_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("suggested_model", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "anchor_kind",
            "anchor_id",
            "suggested_model",
            name="uq_expansion_dismissal",
        ),
    )
    op.create_index(
        "ix_tool_expansion_dismissals_user_id",
        "tool_expansion_dismissals",
        ["user_id"],
    )
    op.create_index(
        "ix_tool_expansion_dismissals_anchor_id",
        "tool_expansion_dismissals",
        ["anchor_id"],
    )

    op.create_table(
        "tool_expansion_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("anchor_model", sa.String(200), nullable=False),
        sa.Column("suggested_model", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "anchor_model",
            "suggested_model",
            name="uq_expansion_report",
        ),
    )
    op.create_index(
        "ix_tool_expansion_reports_user_id",
        "tool_expansion_reports",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_expansion_reports_user_id",
        table_name="tool_expansion_reports",
    )
    op.drop_table("tool_expansion_reports")
    op.drop_index(
        "ix_tool_expansion_dismissals_anchor_id",
        table_name="tool_expansion_dismissals",
    )
    op.drop_index(
        "ix_tool_expansion_dismissals_user_id",
        table_name="tool_expansion_dismissals",
    )
    op.drop_table("tool_expansion_dismissals")
