"""Gap-closer wave 1 (2026-10-20): rating moderation, structured
warranty details, category registry, lost/stolen report records,
borrower address book.

Schema changes, by feature:

- ratings gains removed_at / removed_by_id (moderator removal of
  abusive ratings — the row stays, aggregates exclude it), and a
  new rating_reports table feeds the moderation queue's Ratings
  section (the message_reports shape).
- tools + batteries gain warranty_provider / warranty_contact /
  warranty_terms / warranty_type (structured warranty details;
  warranty_type NULL = legacy, months logic unchanged).
- inventory_categories: the category manager's registry —
  owner-scoped names unique on their normalized key, so a
  category can exist with zero items and renames/merges have an
  anchor. Items keep their free-text category string.
- item_loss_reports: one ACTIVE lost/stolen report per item
  (partial unique index), closed with a recovered_date and kept
  as history.
- borrower_contacts: the owner's reusable borrower address book;
  checkouts gains borrower_contact_id (plain column — the
  snapshot link, no FK, so deleting a contact never touches the
  ledger).

Revision ID: 0036_gap_wave1
Revises: 0035_job_runs
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_gap_wave1"
down_revision: str | None = "0035_job_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _warranty_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "warranty_provider", sa.String(length=200),
            nullable=False, server_default="",
        ),
        sa.Column(
            "warranty_contact", sa.String(length=300),
            nullable=False, server_default="",
        ),
        sa.Column(
            "warranty_terms", sa.String(length=500),
            nullable=False, server_default="",
        ),
        sa.Column("warranty_type", sa.String(length=20), nullable=True),
    ]


def upgrade() -> None:
    # -- rating moderation -------------------------------------------------
    op.add_column(
        "ratings", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ratings",
        sa.Column(
            "removed_by_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_table(
        "rating_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rating_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "reporter_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "reason", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="open"
        ),
        sa.Column(
            "resolution", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column(
            "resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rating_id"], ["ratings.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rating_reports_rating_id", "rating_reports", ["rating_id"])
    op.create_index(
        "ix_rating_reports_reporter_id", "rating_reports", ["reporter_id"]
    )

    # -- structured warranty details ---------------------------------------
    for table in ("tools", "batteries"):
        for column in _warranty_columns():
            op.add_column(table, column)

    # -- category registry ---------------------------------------------------
    op.create_table(
        "inventory_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized", sa.String(length=500), nullable=False),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "normalized",
            name="uq_inventory_categories_owner_normalized",
        ),
    )
    op.create_index(
        "ix_inventory_categories_owner_id", "inventory_categories", ["owner_id"]
    )

    # -- lost/stolen report records ------------------------------------------
    op.create_table(
        "item_loss_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_kind", sa.String(length=10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column(
            "standing", sa.String(length=20), nullable=False, server_default="lost"
        ),
        sa.Column("reported_date", sa.Date(), nullable=True),
        sa.Column(
            "police_report_number", sa.String(length=100),
            nullable=False, server_default="",
        ),
        sa.Column(
            "police_department", sa.String(length=200),
            nullable=False, server_default="",
        ),
        sa.Column(
            "insurer_name", sa.String(length=200),
            nullable=False, server_default="",
        ),
        sa.Column(
            "claim_number", sa.String(length=100),
            nullable=False, server_default="",
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("recovered_date", sa.Date(), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_loss_reports_owner_id", "item_loss_reports", ["owner_id"])
    op.create_index("ix_item_loss_reports_item_id", "item_loss_reports", ["item_id"])
    op.create_index(
        "uq_loss_reports_one_active_per_item",
        "item_loss_reports",
        ["item_kind", "item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # -- borrower address book -------------------------------------------------
    op.create_table(
        "borrower_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column(
            "contact", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        # Optional link to a platform user account (powers the
        # Nudge's in-app delivery; history never depends on it).
        sa.Column("linked_user_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_borrower_contacts_owner_id", "borrower_contacts", ["owner_id"]
    )
    op.add_column(
        "checkouts",
        sa.Column(
            "borrower_contact_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_index(
        "ix_checkouts_borrower_contact_id", "checkouts", ["borrower_contact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_checkouts_borrower_contact_id", table_name="checkouts")
    op.drop_column("checkouts", "borrower_contact_id")
    op.drop_index("ix_borrower_contacts_owner_id", table_name="borrower_contacts")
    op.drop_table("borrower_contacts")

    op.drop_index("uq_loss_reports_one_active_per_item", table_name="item_loss_reports")
    op.drop_index("ix_item_loss_reports_item_id", table_name="item_loss_reports")
    op.drop_index("ix_item_loss_reports_owner_id", table_name="item_loss_reports")
    op.drop_table("item_loss_reports")

    op.drop_index("ix_inventory_categories_owner_id", table_name="inventory_categories")
    op.drop_table("inventory_categories")

    for table in ("tools", "batteries"):
        for name in (
            "warranty_type",
            "warranty_terms",
            "warranty_contact",
            "warranty_provider",
        ):
            op.drop_column(table, name)

    op.drop_index("ix_rating_reports_reporter_id", table_name="rating_reports")
    op.drop_index("ix_rating_reports_rating_id", table_name="rating_reports")
    op.drop_table("rating_reports")
    op.drop_column("ratings", "removed_by_id")
    op.drop_column("ratings", "removed_at")
