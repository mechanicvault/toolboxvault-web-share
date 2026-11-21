"""Dealer portal core (2026-10-19): agent profiles, company
representations, and the private -> platform agent switch.

Builds on the dealers module (0016). Three pieces:

- dealer_agent_profiles — 1:1 with the user: the agent's own
  display name, public contact fields (never a fallback to account
  data), service area, bio, profile photo (a storage KEY only), and
  publicly_listed — the owner's visibility switch, DEFAULT OFF.
- dealer_company_representations — an agent's self-asserted link
  to a DIRECTORY company, unverified until an operator verifies
  it. Unique per (agent, company).
- The private -> platform switch: private_agents gains archived +
  linked_user_id + link_snapshot (the preference rows it fed, for
  a lossless unlink), and preferred_agents gains
  switched_from_private_agent_id — the provenance that lets an
  unlink flip exactly the re-pointed rows back.

Revision ID: 0022_dealer_portal
Revises: 0021_claims
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_dealer_portal"
down_revision: str | None = "0021_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dealer_agent_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "display_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("phone", sa.String(length=100), nullable=False, server_default=""),
        sa.Column(
            "contact_email", sa.String(length=320), nullable=False, server_default=""
        ),
        sa.Column(
            "service_area", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("photo_key", sa.String(length=500), nullable=True),
        sa.Column(
            "publicly_listed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dealer_agent_profiles_user_id"),
        "dealer_agent_profiles",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "dealer_company_representations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("verified_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["agent_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["company_id"], ["dealer_companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["verified_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_user_id", "company_id", name="uq_representations_agent_company"
        ),
    )
    op.create_index(
        op.f("ix_dealer_company_representations_agent_user_id"),
        "dealer_company_representations",
        ["agent_user_id"],
    )
    op.create_index(
        op.f("ix_dealer_company_representations_company_id"),
        "dealer_company_representations",
        ["company_id"],
    )

    op.add_column(
        "private_agents",
        sa.Column(
            "archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "private_agents",
        sa.Column("linked_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "private_agents",
        sa.Column(
            "link_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            # Plain literal, not an '[]'::jsonb cast: the cast is
            # Postgres-only syntax and the migration must also run
            # on SQLite (migration tests). Postgres casts the
            # literal to jsonb implicitly.
            server_default=sa.text("'[]'"),
        ),
    )
    # batch_alter_table for the FK adds: plain create_foreign_key
    # can't ALTER on SQLite (the migration tests run there);
    # batch mode is the house pattern (0016) and is a no-op
    # passthrough on Postgres.
    with op.batch_alter_table("private_agents") as batch_op:
        batch_op.create_foreign_key(
            "fk_private_agents_linked_user_id", "users", ["linked_user_id"], ["id"]
        )

    op.add_column(
        "preferred_agents",
        sa.Column(
            "switched_from_private_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    with op.batch_alter_table("preferred_agents") as batch_op:
        batch_op.create_foreign_key(
            "fk_preferred_agents_switched_from",
            "private_agents",
            ["switched_from_private_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("preferred_agents") as batch_op:
        batch_op.drop_constraint(
            "fk_preferred_agents_switched_from", type_="foreignkey"
        )
    op.drop_column("preferred_agents", "switched_from_private_agent_id")
    with op.batch_alter_table("private_agents") as batch_op:
        batch_op.drop_constraint(
            "fk_private_agents_linked_user_id", type_="foreignkey"
        )
    op.drop_column("private_agents", "link_snapshot")
    op.drop_column("private_agents", "linked_user_id")
    op.drop_column("private_agents", "archived")
    op.drop_table("dealer_company_representations")
    op.drop_table("dealer_agent_profiles")
