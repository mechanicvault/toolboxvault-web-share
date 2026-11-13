"""Dealer agent records, stage 1 (owner model, 2026-11-04).

Ryan's settled agent model (see goals/toolbox-vault-website/files/
dealer-agent-records-model-2026-11-04.md): an agent is a RECORD
with a route and a tenure, the dealer page carries a ROSTER of the
agents a user is connected with, and exactly ONE of them is the
preferred (the app's "current agent").

- private_agents gains the record fields the app carries plus
  the site's route schedule (mirroring dealer_agent_profiles'
  triple, computed by the same route_days module):
  location (the route area, free text), route_frequency /
  route_day_of_week / route_anchor_date, and tenure
  started_at / ended_at (dates — tenure is day-granular).
  Backfill: every existing record's started_at is its created_at
  date (the day the owner entered him is the day he started in
  their records).
- preferred_agents rows become CONNECTION rows: a row says "this
  user is connected with this agent for this company" (it already
  encoded every connection path: typed account number, one-tap
  card add, the private -> platform switch). The PREFERRED is now
  a flag on the row: is_preferred, exactly one true per
  (user, company). Backfill: the EARLIEST row per (user, company)
  — today's agent-on-record resolution — takes the flag; every
  other row stays as a plain connection, so no connection is lost
  in the move from several-preferred to exactly-one.
  Platform tenure lives on the row (tenure_started_at /
  tenure_ended_at): a platform agent's tenure is per-customer,
  so it cannot live on the agent's own account.
- claims gains agent_name_snapshot: when a private agent record
  is deleted, his claims keep his NAME (the dealer_name snapshot
  doctrine) after the FK SET NULLs the pointer. Empty everywhere
  else — the live pointer still resolves the name while it lives.

Idempotent: every step is guarded on the current shape, so a
re-run is a no-op.

Revision ID: 0075_agent_records_stage1
Revises: 0074_claims_repairs_merge
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0075_agent_records_stage1"
down_revision = "0074_claims_repairs_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    agent_columns = {c["name"] for c in inspector.get_columns("private_agents")}
    if "location" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column(
                "location",
                sa.String(length=300),
                nullable=False,
                server_default="",
            ),
        )
    if "route_frequency" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column("route_frequency", sa.String(length=20), nullable=True),
        )
    if "route_day_of_week" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column("route_day_of_week", sa.Integer(), nullable=True),
        )
    if "route_anchor_date" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column("route_anchor_date", sa.Date(), nullable=True),
        )
    if "started_at" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column("started_at", sa.Date(), nullable=True),
        )
    if "ended_at" not in agent_columns:
        op.add_column(
            "private_agents",
            sa.Column("ended_at", sa.Date(), nullable=True),
        )
    # Backfill: the day the owner entered the record is the day
    # the agent started in their records. The WHERE clause is the
    # guard — a re-run finds nothing left to fill.
    bind.execute(
        sa.text(
            "UPDATE private_agents SET started_at = DATE(created_at)"
            " WHERE started_at IS NULL"
        )
    )

    pref_columns = {c["name"] for c in inspector.get_columns("preferred_agents")}
    if "is_preferred" not in pref_columns:
        op.add_column(
            "preferred_agents",
            sa.Column(
                "is_preferred",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "tenure_started_at" not in pref_columns:
        op.add_column(
            "preferred_agents",
            sa.Column("tenure_started_at", sa.Date(), nullable=True),
        )
    if "tenure_ended_at" not in pref_columns:
        op.add_column(
            "preferred_agents",
            sa.Column("tenure_ended_at", sa.Date(), nullable=True),
        )
    # The earliest connection per (user, company) — today's
    # agent-on-record resolution — takes the flag. Guarded to
    # pairs with no flag yet, so a re-run changes nothing and a
    # pair whose preferred was SINCE switched keeps its flag.
    pairs = bind.execute(
        sa.text(
            "SELECT user_id, company_id FROM preferred_agents"
            " GROUP BY user_id, company_id"
            " HAVING SUM(CASE WHEN is_preferred THEN 1 ELSE 0 END) = 0"
        )
    ).fetchall()
    for user_id, company_id in pairs:
        first = bind.execute(
            sa.text(
                "SELECT id FROM preferred_agents"
                " WHERE user_id = :u AND company_id = :c"
                " ORDER BY created_at ASC, id ASC LIMIT 1"
            ),
            {"u": user_id, "c": company_id},
        ).first()
        if first is not None:
            bind.execute(
                sa.text(
                    "UPDATE preferred_agents SET is_preferred = :yes"
                    " WHERE id = :id"
                ),
                {"yes": True, "id": first[0]},
            )

    claim_columns = {c["name"] for c in inspector.get_columns("claims")}
    if "agent_name_snapshot" not in claim_columns:
        op.add_column(
            "claims",
            sa.Column(
                "agent_name_snapshot",
                sa.String(length=300),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    op.drop_column("claims", "agent_name_snapshot")
    op.drop_column("preferred_agents", "tenure_ended_at")
    op.drop_column("preferred_agents", "tenure_started_at")
    op.drop_column("preferred_agents", "is_preferred")
    op.drop_column("private_agents", "ended_at")
    op.drop_column("private_agents", "started_at")
    op.drop_column("private_agents", "route_anchor_date")
    op.drop_column("private_agents", "route_day_of_week")
    op.drop_column("private_agents", "route_frequency")
    op.drop_column("private_agents", "location")
