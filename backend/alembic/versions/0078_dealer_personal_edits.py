"""Personal dealer edits (owner, 2026-11-05).

The owner reported "there is no way to edit a dealer":
Edit company existed only for a viewer's OWN private
companies, and directory (shared) dealers offered no edit at
all. His chosen fix — PERSONAL EDITS: every dealer page gains
Edit for the signed-in viewer; for a shared directory company
what he saves is a personal layer over the directory record.

New table user_dealer_company_edits: one row per (user,
directory company) holding field-level overrides for the
company's identity/contact fields (name, email, website,
address, phones, notes, logo_key, logo_tile). Every override
column is nullable — NULL means "no override", so the read
seam starts from the live directory row and the operator's
directory updates keep flowing through untouched fields. The
corporate warranty block is researched platform data and is
not overlayable.

The user FK carries no cascade (the user_dealer_list_hidden
posture from 0069): the account-deletion cascade clears these
rows explicitly. The company FK cascades — an operator
deleting a directory company takes its personal layers with
it.

All DDL goes through SQLAlchemy ops (no hand-written SQL);
the table/column names were verified against the creating
models and migrations 0069 (the overlay family) before this
was written.

Revision ID: 0078_dealer_personal_edits
Revises: 0077_truck_accounts_stage2
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0078_dealer_personal_edits"
down_revision = "0077_truck_accounts_stage2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_dealer_company_edits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phones", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("logo_key", sa.String(length=500), nullable=True),
        sa.Column("logo_tile", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["dealer_companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "company_id", name="uq_dealer_company_edits_user_company"
        ),
    )
    op.create_index(
        "ix_user_dealer_company_edits_user_id",
        "user_dealer_company_edits",
        ["user_id"],
    )
    op.create_index(
        "ix_user_dealer_company_edits_company_id",
        "user_dealer_company_edits",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_dealer_company_edits_company_id",
        table_name="user_dealer_company_edits",
    )
    op.drop_index(
        "ix_user_dealer_company_edits_user_id",
        table_name="user_dealer_company_edits",
    )
    op.drop_table("user_dealer_company_edits")
