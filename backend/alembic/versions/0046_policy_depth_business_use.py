"""0046 — policy-profile depth + business-use flags + nudge silence (audit A8+A9)

A9: insurance_profiles gains the depth the claims guidance needs —
policy_type (homeowners/renters/commercial/dedicated_tool/other),
deductible + coverage limit + business-use sub-limit (cents, NULL =
not declared), valuation basis (acv/rcv), and how-to-file notes.
Everything defaults to unset: a profile that never fills these in
behaves exactly as before.

A9: tools + batteries gain business_use (the flag the sub-limit
guidance keys off). Default false — nothing existing is reclassified.

A8: users gains silence_claim_readiness_nudges (the per-user opt-out
for the claim-readiness inbox nudges). Default false.

Revision ID: 0046_policy_depth_business_use
Revises: 0045_route_days_and_drawers
"""

from alembic import op
import sqlalchemy as sa

revision = "0046_policy_depth_business_use"
down_revision = "0045_route_days_and_drawers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "insurance_profiles",
        sa.Column("policy_type", sa.String(40), nullable=False, server_default=""),
    )
    op.add_column(
        "insurance_profiles",
        sa.Column("deductible_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "insurance_profiles",
        sa.Column("coverage_limit_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "insurance_profiles",
        sa.Column("valuation_basis", sa.String(10), nullable=False, server_default=""),
    )
    op.add_column(
        "insurance_profiles",
        sa.Column("business_sub_limit_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "insurance_profiles",
        sa.Column("how_to_file", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column(
            "silence_claim_readiness_nudges",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "tools",
        sa.Column("business_use", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "batteries",
        sa.Column("business_use", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("batteries", "business_use")
    op.drop_column("tools", "business_use")
    op.drop_column("users", "silence_claim_readiness_nudges")
    op.drop_column("insurance_profiles", "how_to_file")
    op.drop_column("insurance_profiles", "business_sub_limit_cents")
    op.drop_column("insurance_profiles", "valuation_basis")
    op.drop_column("insurance_profiles", "coverage_limit_cents")
    op.drop_column("insurance_profiles", "deductible_cents")
    op.drop_column("insurance_profiles", "policy_type")
