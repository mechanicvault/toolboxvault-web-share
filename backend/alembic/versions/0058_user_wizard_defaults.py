"""Account-held Add wizard defaults (Wizard Phase 1, 2026-10-25).

Adds `wizard_defaults` to `users`: ONE nullable JSON document
holding the user's Add-tool / Add-battery wizard setup — the
optional sections the wizard pre-checks on its "What do you want
to include?" step, plus the user's usual storage location and
usual dealer (bought-from company) that the wizard pre-fills.

Why a new column, and not one of the existing per-user stores:
`user_page_layouts` is contractually a page's ordered block
list (a JSON list of {key, visible} for a named page) and
`user_module_prefs` / `notification_channel_prefs` are row-per-
choice tables for their own fixed vocabularies. Wizard defaults
are a single small document that matches none of those shapes;
stuffing it into the layouts table would break that table's one
documented invariant. This column follows the appearance
precedent instead (0057): account data on the user row itself.

NULL means "this account has never saved wizard defaults" and
the client uses the shipped behaviour (nothing pre-checked, no
usual location or dealer). A saved JSON object — including one
with an empty sections list — is the user's explicit setup and
wins on every device, exactly like the appearance triple.

Revision ID: 0058_user_wizard_defaults
Revises: 0057_user_appearance
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0058_user_wizard_defaults"
down_revision = "0057_user_appearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("wizard_defaults", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "wizard_defaults")
