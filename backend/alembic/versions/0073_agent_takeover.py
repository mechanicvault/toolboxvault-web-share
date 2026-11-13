"""Agent codes + takeover requests (owner model, 2026-11-03).

Every user-entered private agent record gets an AGENT CODE — a
property of the record itself, so that everything the user does
with that record (claims, truck account, route facts, all of
which reference the record) transfers to a real agent in place
when the agent signs up, enters the code, and the owner accepts
the takeover.

- private_agents.agent_code — eight characters from an
  unambiguous alphabet (no 0/O/1/I/L), unique across the system,
  shown only to the record's owner. Existing rows are backfilled
  with fresh codes here (the generator is inlined so this
  migration stays frozen even if the app alphabet ever moves).
- private_agents.link_source — HOW linked_user_id came to be
  set: "takeover" (code + owner acceptance; the record stays the
  working record) or "switch" (the older account-number switch,
  which archives the record). Backfilled "switch" for rows the
  old flow already linked; NULL stays unlinked.
- agent_takeover_requests — one row per code entry: requester,
  record, status (pending/accepted/declined/superseded),
  decided_at. Both FKs CASCADE — a request is meaningless
  without its record, and a deleted account's asks die with it.

Revision ID: 0073_agent_takeover
Revises: 0072_forum_favorites
Create Date: 2026-11-03
"""

import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0073_agent_takeover"
down_revision = "0072_forum_favorites"
branch_labels = None
depends_on = None

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def upgrade() -> None:
    op.add_column(
        "private_agents",
        sa.Column("agent_code", sa.String(length=12), nullable=True),
    )
    op.add_column(
        "private_agents",
        sa.Column("link_source", sa.String(length=20), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id FROM private_agents WHERE agent_code IS NULL")
    ).fetchall()
    used: set[str] = set()
    for (row_id,) in rows:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        while code in used:
            code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        used.add(code)
        bind.execute(
            sa.text("UPDATE private_agents SET agent_code = :code WHERE id = :id"),
            {"code": code, "id": row_id},
        )
    # Rows the pre-existing account-number switch already linked
    # are switch links by construction (that flow archives).
    bind.execute(
        sa.text(
            "UPDATE private_agents SET link_source = 'switch' "
            "WHERE linked_user_id IS NOT NULL AND link_source IS NULL"
        )
    )
    op.alter_column("private_agents", "agent_code", nullable=False)
    op.create_index(
        "ix_private_agents_agent_code",
        "private_agents",
        ["agent_code"],
        unique=True,
    )

    op.create_table(
        "agent_takeover_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "private_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("private_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_takeover_requests_private_agent_id",
        "agent_takeover_requests",
        ["private_agent_id"],
    )
    op.create_index(
        "ix_agent_takeover_requests_requester_user_id",
        "agent_takeover_requests",
        ["requester_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_takeover_requests_requester_user_id",
        table_name="agent_takeover_requests",
    )
    op.drop_index(
        "ix_agent_takeover_requests_private_agent_id",
        table_name="agent_takeover_requests",
    )
    op.drop_table("agent_takeover_requests")
    op.drop_index("ix_private_agents_agent_code", table_name="private_agents")
    op.drop_column("private_agents", "link_source")
    op.drop_column("private_agents", "agent_code")
