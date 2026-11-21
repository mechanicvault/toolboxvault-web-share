"""Warranty claims become AGENT-scoped (owner rulings, 2026-10-31).

The 2026-10-25 two-types build made the dealer COMPANY the second
seat on a warranty claim: any verified representative of the
company could see and work every claim for that company. The owner
corrected the model (files/claims-agent-scope-revision-2026-10-31.md):

- A warranty claim's viewers are the owner and ONE agent — the
  owner's dealer agent for the claim — or no agent at all (then
  only the owner can see it; the company gets no access at all).
- The claim takes the owner's agent ON RECORD for the dealer by
  default; the owner can change the claim's agent.
- These are manufacturer warranty claims: a claim/case number may
  exist, but there is NO insurance policy.

Schema changes, all additive:

- claims.agent_user_id / claims.private_agent_id — the claim's
  agent pointer, the PreferredAgent exactly-one shape (a platform
  user OR one of the owner's private agent records; both NULL =
  no agent). SET NULL on delete either side, so a claim never
  dangles off a removed record or account.
- claims.manufacturer_case_number — the manufacturer's claim /
  case number for warranty claims (their counterpart to the
  insurance policy number; warranty claims never carry one).

Backfill: every existing warranty claim with a dealer takes the
owner's CURRENT agent on record for that dealer — the owner's
earliest preferred-agent row for (owner, dealer), whose platform
or private pointer lands in the matching column — else no agent
(owner-only). Production holds test claims only.

Revision ID: 0066_claims_agent_scope
Revises: 0065_downloads_subscribers
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066_claims_agent_scope"
down_revision = "0065_downloads_subscribers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column(
            "agent_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_claims_agent_user_id", "claims", ["agent_user_id"])
    op.add_column(
        "claims",
        sa.Column(
            "private_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("private_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_claims_private_agent_id", "claims", ["private_agent_id"]
    )
    op.add_column(
        "claims",
        sa.Column(
            "manufacturer_case_number",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
    )
    # Backfill (see the docstring): per claim, the owner's earliest
    # preferred-agent row for the claim's dealer supplies the
    # pointer. A preferred row carries exactly one of the two
    # columns, so each scalar subquery picks its own side and the
    # other stays NULL.
    op.execute(
        """
        UPDATE claims AS c
        SET agent_user_id = (
                SELECT pa.agent_user_id
                FROM preferred_agents AS pa
                WHERE pa.user_id = c.owner_id
                  AND pa.company_id = c.dealer_company_id
                ORDER BY pa.created_at ASC, pa.id ASC
                LIMIT 1
            ),
            private_agent_id = (
                SELECT pa.private_agent_id
                FROM preferred_agents AS pa
                WHERE pa.user_id = c.owner_id
                  AND pa.company_id = c.dealer_company_id
                ORDER BY pa.created_at ASC, pa.id ASC
                LIMIT 1
            )
        WHERE c.kind = 'warranty_repair'
          AND c.dealer_company_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("claims", "manufacturer_case_number")
    op.drop_index("ix_claims_private_agent_id", table_name="claims")
    op.drop_column("claims", "private_agent_id")
    op.drop_index("ix_claims_agent_user_id", table_name="claims")
    op.drop_column("claims", "agent_user_id")
