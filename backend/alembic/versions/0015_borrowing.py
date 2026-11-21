"""Borrowing: the check-out ledger (feature map row 28, converted).

The app kept lending embedded in tool records (`current_checkout` +
`checkout_history` inside each tool document; its `checkouts`
collection was empty). The website builds it as proper records:
one `checkouts` table, one row per lend, rows never deleted — the
table IS the history, state transitions only.

One ACTIVE lend (requested | checked_out) per item at a time is
enforced by a partial unique index on (item_kind, item_id); the
service pre-checks for a friendly error and the index is the
race-proof backstop.

item_id is deliberately NOT a foreign key: the ledger outlives the
item (item_name is snapshotted on the row), so history stays
readable after a rename or delete. owner_id / borrower_user_id are
real FKs — if an account is deleted its lends go with it, matching
the account-deletion cascade everywhere else.

No module-control seeding: the control service falls back to the
manifest's default_groups (mechanic + shop) for modules without
assignment rows, exactly as it did for ai_assistant.

Revision ID: 0015_borrowing
Revises: 0014_batteries
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_borrowing"
down_revision: str | Sequence[str] | None = "0014_batteries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checkouts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("item_kind", sa.String(10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_name", sa.String(300), nullable=False, server_default=""),
        sa.Column(
            "borrower_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "borrower_name", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column(
            "borrower_contact", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column(
            "state", sa.String(20), nullable=False, server_default="requested"
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("checked_out_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("returned_by", sa.String(20)),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_checkouts_owner_id", "checkouts", ["owner_id"])
    op.create_index("ix_checkouts_item_id", "checkouts", ["item_id"])
    op.create_index(
        "ix_checkouts_borrower_user_id", "checkouts", ["borrower_user_id"]
    )
    op.create_index("ix_checkouts_state", "checkouts", ["state"])
    op.create_index(
        "uq_checkouts_one_active_per_item",
        "checkouts",
        ["item_kind", "item_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'checked_out')"),
    )


def downgrade() -> None:
    op.drop_index("uq_checkouts_one_active_per_item", table_name="checkouts")
    op.drop_table("checkouts")
