"""Set pieces: core pieces may carry their own price (owner 2026-10-25).

Migration 0016 enforced "core pieces carry NO price, ever" with
the CHECK `ck_set_pieces_core_has_no_price` on `set_pieces` (the
price lives on the set). Ryan superseded that rule on 2026-10-25:
every set piece — core included — gets an OPTIONAL price of its
own. His reasons: replacing one lost piece costs money (one socket
out of a 10-socket set), and people build sets one piece at a
time, each piece costing its own amount.

The `price` column itself already exists (addons used it). This
migration only drops the CHECK. The piece price is the piece's own
cost/replacement figure: the service never rolls it into the set's
own price or totals (only addon prices join a set's totals, as
before), so existing money math is untouched.

Downgrade re-creates the CHECK — it will fail if any core piece
has recorded a price in the meantime, which is the honest outcome:
those prices would have nowhere to live under the old rule.

Revision ID: 0059_set_piece_core_price
Revises: 0058_user_wizard_defaults
Create Date: 2026-10-25
"""

from alembic import op

revision = "0059_set_piece_core_price"
down_revision = "0058_user_wizard_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_set_pieces_core_has_no_price", "set_pieces", type_="check"
    )


def downgrade() -> None:
    op.create_check_constraint(
        "ck_set_pieces_core_has_no_price",
        "set_pieces",
        "kind = 'addon' OR price IS NULL",
    )
