"""Truck accounts become AGENT-issued, under a dealer company
(owner revision, 2026-10-31).

Spec: files/truck-accounts-agent-revision-2026-10-31.md. The
wave-2 build keyed a truck account to a dealer USER alone — no
company, no agent record, no credit line. The owner's model:

- The issuer is a specific dealer AGENT, acting under a dealer
  COMPANY: the account nests under that company's dealer page
  ("open balance with agent Matt — $1,000" on the Matco page).
- Route changes do NOT move truck accounts (the deliberate
  opposite of warranty claims, which follow the new agent): an
  account stays with its original agent until the CUSTOMER
  transfers it to a new agent of the same dealer — a deliberate
  act, recorded in the account's history.

Schema changes:

- truck_accounts.dealer_company_id — the company the account is
  under (FK, SET NULL like the claims dealer link: the dealer is
  factual context; a deleted company leaves the tab standing).
- truck_accounts.dealer_company_name — the company NAME SNAPSHOT,
  so the record still reads correctly after the company is gone.
- truck_accounts.private_agent_id — set when the account's agent
  holder is one of the CUSTOMER's private agent records (no
  platform account): the claims exactly-one shape beside
  dealer_user_id. While it is set, dealer_user_id is NULL and
  the customer maintains the tab himself.
- truck_accounts.dealer_user_id becomes NULLABLE (it is the
  platform holder of the dealer side; NULL exactly while a
  private agent holds the account). truck_entries.dealer_user_id
  becomes NULLABLE to match (entries recorded while a private
  agent holds the account attribute to no platform dealer; the
  journal reads the column as-is).
- truck_accounts.agent_name_snapshot — who the agent was, as the
  customer saw the name at issue / last transfer.
- truck_accounts.credit_limit — the credit line the agent
  extended (NULL = no line recorded; the balance rule is
  unchanged: SUM of the ledger, never stored).
- truck_account_transfers — the transfer history: one row per
  customer-initiated transfer with from/to pointers AND name
  snapshots (plain columns, the parent table's own doctrine —
  a history row must survive either side deleting their
  account; the snapshots carry the meaning).

Backfill for existing accounts (production holds at most test
rows): dealer_user_id already IS the issuing platform agent, so
agent_name_snapshot takes that user's current name. The company
is set only when it is UNAMBIGUOUS: the dealer user's single
verified representation, else the single company for which the
customer prefers this dealer user. Anything else stays NULL —
the account remains valid, it simply is not nested under a
company page until an agent link gives it one.

Revision ID: 0068_truck_account_agents
Revises: 0067_account_tiers
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0068_truck_account_agents"
down_revision = "0067_account_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "truck_accounts",
        sa.Column(
            "dealer_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_truck_accounts_dealer_company_id",
        "truck_accounts",
        ["dealer_company_id"],
    )
    op.add_column(
        "truck_accounts",
        sa.Column(
            "dealer_company_name",
            sa.String(300),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "truck_accounts",
        sa.Column(
            "private_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("private_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_truck_accounts_private_agent_id",
        "truck_accounts",
        ["private_agent_id"],
    )
    op.add_column(
        "truck_accounts",
        sa.Column(
            "agent_name_snapshot",
            sa.String(300),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "truck_accounts",
        sa.Column(
            "credit_limit",
            sa.Numeric(12, 2),
            nullable=True,
        ),
    )
    op.alter_column(
        "truck_accounts", "dealer_user_id", nullable=True
    )
    op.alter_column("truck_entries", "dealer_user_id", nullable=True)

    op.create_table(
        "truck_account_transfers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("truck_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # PLAIN columns on purpose (the parent table's doctrine):
        # a history row outlives either side's account deletion;
        # the name snapshots carry who was who.
        sa.Column(
            "from_agent_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "from_private_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "from_agent_name", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column(
            "to_agent_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "to_private_agent_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "to_agent_name", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column(
            "transferred_by", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_truck_account_transfers_account_id",
        "truck_account_transfers",
        ["account_id"],
    )

    # -- backfill -------------------------------------------------
    op.execute(
        """
        UPDATE truck_accounts AS ta
        SET agent_name_snapshot = COALESCE(u.name, '')
        FROM users AS u
        WHERE u.id = ta.dealer_user_id
          AND ta.dealer_user_id IS NOT NULL
        """
    )
    # Company, route 1: the dealer user's ONE verified
    # representation.
    op.execute(
        """
        UPDATE truck_accounts AS ta
        SET dealer_company_id = (
                SELECT r.company_id
                FROM dealer_company_representations AS r
                WHERE r.agent_user_id = ta.dealer_user_id
                  AND r.verified = true
                ORDER BY r.created_at ASC, r.id ASC
                LIMIT 1
            )
        WHERE ta.dealer_user_id IS NOT NULL
          AND (
                SELECT count(*)
                FROM dealer_company_representations AS r2
                WHERE r2.agent_user_id = ta.dealer_user_id
                  AND r2.verified = true
              ) = 1
        """
    )
    # Company, route 2: the customer's preference names this
    # dealer user for exactly ONE company.
    op.execute(
        """
        UPDATE truck_accounts AS ta
        SET dealer_company_id = (
                SELECT pa.company_id
                FROM preferred_agents AS pa
                WHERE pa.user_id = ta.customer_user_id
                  AND pa.agent_user_id = ta.dealer_user_id
                ORDER BY pa.created_at ASC, pa.id ASC
                LIMIT 1
            )
        WHERE ta.dealer_company_id IS NULL
          AND ta.customer_user_id IS NOT NULL
          AND ta.dealer_user_id IS NOT NULL
          AND (
                SELECT count(DISTINCT pa2.company_id)
                FROM preferred_agents AS pa2
                WHERE pa2.user_id = ta.customer_user_id
                  AND pa2.agent_user_id = ta.dealer_user_id
              ) = 1
        """
    )
    op.execute(
        """
        UPDATE truck_accounts AS ta
        SET dealer_company_name = c.name
        FROM dealer_companies AS c
        WHERE c.id = ta.dealer_company_id
          AND ta.dealer_company_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # NOTE: restoring NOT NULL on the dealer_user_id columns
    # requires no private-held accounts / entries to exist.
    op.drop_index(
        "ix_truck_account_transfers_account_id",
        table_name="truck_account_transfers",
    )
    op.drop_table("truck_account_transfers")
    op.alter_column("truck_entries", "dealer_user_id", nullable=False)
    op.alter_column("truck_accounts", "dealer_user_id", nullable=False)
    op.drop_column("truck_accounts", "credit_limit")
    op.drop_column("truck_accounts", "agent_name_snapshot")
    op.drop_index(
        "ix_truck_accounts_private_agent_id", table_name="truck_accounts"
    )
    op.drop_column("truck_accounts", "private_agent_id")
    op.drop_column("truck_accounts", "dealer_company_name")
    op.drop_index(
        "ix_truck_accounts_dealer_company_id", table_name="truck_accounts"
    )
    op.drop_column("truck_accounts", "dealer_company_id")
