"""Per-user customization of the prefilled dealer pick list
(owner directive, 2026-10-31).

Ryan's words: "Users should be able to add or remove default
dealer lists as well. So if a user removes dealers that are
prefilled, when a user goes to enter a new dealer themselves,
they can either enter one manually or pick one from the list."

Two overlay tables on the dealers module — the customization is
computed against the LIVE directory, never copied from it:

- user_dealer_list_hidden — one row per (user, directory company)
  the user removed from their own pick list. Because removals are
  remembered per entry (not a frozen snapshot of the list), a
  brand the operator adds to the directory later appears for
  every user who hasn't hidden it. Hiding touches nothing else:
  the directory row, the user's items tagged with it, and every
  other user's list all stand.

- user_dealer_list_entries — the user's own additions: a name
  plus the Add Dealer wizard's basics (kind, email, website,
  address, phones, notes). An entry is a TEMPLATE, not a dealer
  record: picking it in an entry flow mints the user's private
  company from its fields and records the link in
  created_company_id (SET NULL — deleting that company makes the
  entry pickable again). Removing an entry never touches a
  company it created.

"Restore defaults" is application logic over these two tables
(clear the user's rows); no schema support needed.

Revision ID: 0069_dealer_list_customization
Revises: 0068_truck_account_agents
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0069_dealer_list_customization"
down_revision = "0068_truck_account_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_dealer_list_hidden",
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
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "company_id", name="uq_dealer_list_hidden_user_company"
        ),
    )
    op.create_index(
        "ix_user_dealer_list_hidden_user_id",
        "user_dealer_list_hidden",
        ["user_id"],
    )
    op.create_index(
        "ix_user_dealer_list_hidden_company_id",
        "user_dealer_list_hidden",
        ["company_id"],
    )
    op.create_table(
        "user_dealer_list_entries",
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
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column(
            "kind",
            sa.String(20),
            nullable=False,
            server_default="manufacturer",
        ),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("website", sa.String(500), nullable=False, server_default=""),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "phones",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="SET NULL"),
            nullable=True,
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
        "ix_user_dealer_list_entries_user_id",
        "user_dealer_list_entries",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_dealer_list_entries_user_id",
        table_name="user_dealer_list_entries",
    )
    op.drop_table("user_dealer_list_entries")
    op.drop_index(
        "ix_user_dealer_list_hidden_company_id",
        table_name="user_dealer_list_hidden",
    )
    op.drop_index(
        "ix_user_dealer_list_hidden_user_id",
        table_name="user_dealer_list_hidden",
    )
    op.drop_table("user_dealer_list_hidden")
