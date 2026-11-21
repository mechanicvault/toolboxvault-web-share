"""Support tickets (support module, 2026-10-24).

The Help & Support page's ticket system: a member opens a ticket
and trades messages with the support team (operators).

- support_tickets — one conversation: owner (user_id FK,
  CASCADE — a ticket is private two-party mail and dies with the
  account), subject, lifecycle status (open | answered | closed).
- support_messages — the messages inside a ticket: ticket_id FK
  CASCADE, author_id FK CASCADE, author_kind ("user" |
  "operator"), body.

Revision ID: 0050_support_tickets
Revises: 0049_acquisition_ledger
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_support_tickets"
down_revision = "0049_acquisition_ledger"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="open"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_support_tickets_user_id", "support_tickets", ["user_id"]
    )
    op.create_index(
        "ix_support_tickets_status", "support_tickets", ["status"]
    )
    op.create_table(
        "support_messages",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "ticket_id",
            _UUID,
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_kind", sa.String(10), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_support_messages_ticket_id", "support_messages", ["ticket_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_tickets_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_user_id", table_name="support_tickets")
    op.drop_table("support_tickets")
