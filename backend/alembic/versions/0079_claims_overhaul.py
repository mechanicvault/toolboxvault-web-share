"""Claims overhaul (owner orders, 2026-11-05 #6–#8; built 2026-11-06).

Three record changes to the shared claims table, WARRANTY claims
only in effect (insurance/disaster rows are never rewritten —
the disaster module's statuses, filing and pages are untouched):

1. filed_with — Ryan's three filing routes become a column:
   "agent" (runs through the owner's agent), "self" (the owner
   handles it alone), "corporate" (filed straight with the dealer
   company; verified representatives of that company form the
   claim's second seat). Backfill is honest and provable
   claim-by-claim: a warranty claim that carries an agent pointer
   — or the name snapshot a deleted agent record left behind —
   was agent-seated, so it reads "agent"; every other warranty
   claim was the owner's alone and reads "self". No corporate
   claims can exist yet (the route is new), so none are minted
   by the backfill.

2. The status remap. Ryan's new ladder keeps four keys and adds
   four; the one value that disappears is warranty "closed":
   closing is now its own layer (the closed_at stamp, which the
   old ladder's close already stamped on every closed claim).
   A closed warranty claim's least-wrong home on the new ladder
   is "completed" (Repaired) WITH its closed_at preserved — the
   claim reads Repaired in Repair history, exactly the mapping
   the owner was told about. Insurance rows keep status "closed"
   untouched (their ladder still ends there).

3. The backorder clock: backorder_entered_at /
   backorder_last_reminded_at, the bookkeeping the monthly
   backorder reminder job runs on. Both start NULL — no claim is
   in the new Backordered status yet, so no clock is owed.

DDL goes through SQLAlchemy ops; the two data steps are plain
UPDATEs whose table/column names (claims: kind, status,
agent_user_id, private_agent_id, agent_name_snapshot, closed_at)
were verified against the live production schema
(information_schema, 2026-11-06) BEFORE this was written, per the
standing migration rule from the 2026-11-05 outage.

Revision ID: 0079_claims_overhaul
Revises: 0078_dealer_personal_edits
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0079_claims_overhaul"
down_revision = "0078_dealer_personal_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column(
            "filed_with",
            sa.String(length=20),
            nullable=False,
            server_default="self",
        ),
    )
    op.add_column(
        "claims",
        sa.Column(
            "backorder_entered_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "claims",
        sa.Column(
            "backorder_last_reminded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # The filed-with backfill (warranty claims only): an agent
    # pointer — or the snapshot a deleted agent record left —
    # means the claim was seated with an agent.
    op.execute(
        "UPDATE claims SET filed_with = 'agent' "
        "WHERE kind = 'warranty_repair' AND ("
        "agent_user_id IS NOT NULL "
        "OR private_agent_id IS NOT NULL "
        "OR agent_name_snapshot <> '')"
    )
    # The status remap (warranty claims only): closed becomes
    # Repaired under the preserved closed layer.
    op.execute(
        "UPDATE claims SET status = 'completed' "
        "WHERE kind = 'warranty_repair' AND status = 'closed'"
    )


def downgrade() -> None:
    # Best-effort reverse of the status remap: a warranty claim
    # that is Repaired AND carries the closed layer was, before
    # the overhaul, status "closed". (A claim completed and then
    # closed AFTER the upgrade reads the same and also returns —
    # its pre-overhaul equivalent was the same pair of facts.)
    op.execute(
        "UPDATE claims SET status = 'closed' "
        "WHERE kind = 'warranty_repair' AND status = 'completed' "
        "AND closed_at IS NOT NULL"
    )
    op.drop_column("claims", "backorder_last_reminded_at")
    op.drop_column("claims", "backorder_entered_at")
    op.drop_column("claims", "filed_with")
