"""Claims module (2026-10-19): insurance claims over the vault.

Blueprint §15 + owner rules: a claim is a header (insurer,
incident, police-report block, deadlines) plus LINES that target an
asset, a whole set, or a single set piece — every line SNAPSHOTS
its target (names, the include-addons choice for sets, the value
basis and the amount) at filing time, so a filed claim never
drifts when items later change. target_id is deliberately NOT a
foreign key (the ledger doctrine: lines outlive items).

- claims — the header. claim_number is the owner-visible
  CL-<year>-<seq>, sequential per owner per year (claim_year +
  number_seq carry the sequence portably).
- claim_lines — one row per targeted item (tool | battery | set |
  piece), priced at add time.
- claim_evidence — by REFERENCE to an item's existing attachment
  (item_kind/item_id/attachment_key + filename snapshot; the file
  is never copied) or a claim-specific UPLOAD (attachment JSONB in
  the item-attachment shape, keys {owner}/claims/{claim_id}/...).
- claim_communications — the timestamped log of calls/letters.

Children cascade from their claim; the claim cascades from the
user. Account deletion ALSO enumerates these tables explicitly in
core's delete_account (it must run before the inventory loop —
open claims guard their items against deletion).

Revision ID: 0021_claims
Revises: 0020_maintenance
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_claims"
down_revision: str | None = "0020_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "claim_number", sa.String(length=20), nullable=False, server_default=""
        ),
        sa.Column("claim_year", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("number_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "insurer_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "policy_number", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "incident_type",
            sa.String(length=20),
            nullable=False,
            server_default="other",
        ),
        sa.Column("incident_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="draft"
        ),
        sa.Column(
            "police_report_number",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "police_department",
            sa.String(length=300),
            nullable=False,
            server_default="",
        ),
        sa.Column("police_report_date", sa.Date(), nullable=True),
        sa.Column("proof_of_loss_due", sa.Date(), nullable=True),
        sa.Column("proof_of_loss_sent_at", sa.Date(), nullable=True),
        sa.Column("depreciation_deadline", sa.Date(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(op.f("ix_claims_owner_id"), "claims", ["owner_id"])

    op.create_table(
        "claim_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_kind", sa.String(length=10), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "target_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "set_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "include_addons",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "value_basis",
            sa.String(length=20),
            nullable=False,
            server_default="replacement",
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claim_lines_owner_id"), "claim_lines", ["owner_id"])
    op.create_index(op.f("ix_claim_lines_claim_id"), "claim_lines", ["claim_id"])
    op.create_index(
        op.f("ix_claim_lines_target_id"), "claim_lines", ["target_id"]
    )
    op.create_index(op.f("ix_claim_lines_set_id"), "claim_lines", ["set_id"])

    op.create_table(
        "claim_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source",
            sa.String(length=10),
            nullable=False,
            server_default="reference",
        ),
        sa.Column("item_kind", sa.String(length=10), nullable=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attachment_key",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "filename", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="document"
        ),
        sa.Column("attachment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_evidence_owner_id"), "claim_evidence", ["owner_id"]
    )
    op.create_index(
        op.f("ix_claim_evidence_claim_id"), "claim_evidence", ["claim_id"]
    )

    op.create_table(
        "claim_communications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "channel", sa.String(length=20), nullable=False, server_default="phone"
        ),
        sa.Column(
            "contact", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_communications_owner_id"),
        "claim_communications",
        ["owner_id"],
    )
    op.create_index(
        op.f("ix_claim_communications_claim_id"),
        "claim_communications",
        ["claim_id"],
    )


def downgrade() -> None:
    op.drop_table("claim_communications")
    op.drop_table("claim_evidence")
    op.drop_table("claim_lines")
    op.drop_table("claims")
