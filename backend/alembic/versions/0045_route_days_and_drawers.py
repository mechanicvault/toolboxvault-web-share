"""Route-day schedules + drawer-grid positions (audit A2 + A3).

A2 — dealer_agent_profiles gains the route schedule the app
carried: route_frequency ("weekly" | "biweekly" | "monthly"),
route_day_of_week (0 = Monday .. 6 = Sunday), route_anchor_date
(the known route day the biweekly/monthly cycles count from).
All NULL = the agent runs no fixed route.

A3 — inventory_locations gains the app's drawer-grid fields
verbatim: parent_layout_id (the toolbox/layout a node is a drawer
of) and drawer_index (its position in that layout). NULL on every
existing row — no structure is invented for locations that never
had it; the fields exist so migrated drawer structure lands
intact.

Revision ID: 0045_route_days_and_drawers
Revises: 0044_consumable_rebuy
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_route_days_and_drawers"
down_revision: str | None = "0044_consumable_rebuy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("route_frequency", sa.String(20), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("route_day_of_week", sa.Integer(), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("route_anchor_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "inventory_locations",
        sa.Column(
            "parent_layout_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_locations.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "inventory_locations",
        sa.Column("drawer_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inventory_locations", "drawer_index")
    op.drop_column("inventory_locations", "parent_layout_id")
    op.drop_column("dealer_agent_profiles", "route_anchor_date")
    op.drop_column("dealer_agent_profiles", "route_day_of_week")
    op.drop_column("dealer_agent_profiles", "route_frequency")
