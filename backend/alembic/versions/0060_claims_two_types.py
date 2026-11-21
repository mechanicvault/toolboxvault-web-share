"""Claims split into two kinds (owner model, confirmed 2026-10-25).

Ryan's correction: the system handles TWO kinds of claims — the
everyday WARRANTY / REPAIR claim (a tool breaks, the dealer fixes
or replaces it; auto-created from the broken-item flow, reported
to the dealer, driven by both sides when the dealer is on the
platform) and the rare INSURANCE DISASTER claim (theft/loss/fire
at scale — the incident flow that already exists). Spec:
goals/toolbox-vault-website/files/claims-two-types-model-2026-10-25.md.

Schema changes, all additive:

- claims.kind — warranty_repair | insurance_disaster. Every
  existing row is an insurance claim (the incident list is loss
  events), so the column lands with that server default and no
  data rewrite is needed.
- claims.dealer_company_id / dealer_name — a warranty claim's
  dealer: the item's dealer tag at creation (id, SET NULL if the
  company is later deleted) plus a name snapshot so the record
  stays readable. NULL/empty on insurance claims.
- claims.reported_at / report_method — when the dealer was told
  about a warranty claim, and how ("system" = Toolbox Vault
  reported it, "user" = the owner told them).
- claim_communications.author_id / author_role / author_name —
  a warranty claim's comm log is a two-party record; entries now
  say who wrote them. Existing rows are the owner's (NULL id,
  empty role/name).
- claim_lines.target_part_number / set_model_number — a piece
  claim carries the piece's own part/model number AND the parent
  set's model number (Ryan 2026-10-25), so a dealer can find the
  piece by either number.

Revision ID: 0060_claims_two_types
Revises: 0059_set_piece_core_price
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060_claims_two_types"
down_revision = "0059_set_piece_core_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column(
            "kind",
            sa.String(20),
            nullable=False,
            server_default="insurance_disaster",
        ),
    )
    op.add_column(
        "claims",
        sa.Column(
            "dealer_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_claims_dealer_company_id", "claims", ["dealer_company_id"]
    )
    op.add_column(
        "claims",
        sa.Column(
            "dealer_name", sa.String(300), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "claims",
        sa.Column(
            "reported_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "claims",
        sa.Column(
            "report_method", sa.String(20), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "claim_communications",
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "claim_communications",
        sa.Column(
            "author_role", sa.String(10), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "claim_communications",
        sa.Column(
            "author_name", sa.String(300), nullable=False, server_default=""
        ),
    )
    # Piece-claim number snapshots (Ryan 2026-10-25): the piece's own
    # part/model number and the parent set's model number ride the
    # claim line, so the record shows both wherever it appears.
    op.add_column(
        "claim_lines",
        sa.Column(
            "target_part_number",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "claim_lines",
        sa.Column(
            "set_model_number",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("claim_lines", "set_model_number")
    op.drop_column("claim_lines", "target_part_number")
    op.drop_column("claim_communications", "author_name")
    op.drop_column("claim_communications", "author_role")
    op.drop_column("claim_communications", "author_id")
    op.drop_column("claims", "report_method")
    op.drop_column("claims", "reported_at")
    op.drop_column("claims", "dealer_name")
    op.drop_index("ix_claims_dealer_company_id", table_name="claims")
    op.drop_column("claims", "dealer_company_id")
    op.drop_column("claims", "kind")
