"""Support ticket statuses: "answered" becomes "under_review" (2026-10-24).

Owner steer: ticket statuses are exactly three — Open · Under
Review · Closed. The shipped middle status "answered" is
renamed "under_review" (an operator reply now lands a ticket
there instead). Data-only migration: rewrite the stored value;
the column is a plain string with no CHECK constraint to move.

Production holds exactly one real ticket (open, unaffected);
the rewrite matters for correctness everywhere else.

Revision ID: 0053_support_status_under_review
Revises: 0052_user_module_prefs
Create Date: 2026-10-24
"""

from alembic import op

revision = "0053_support_status_under_review"
down_revision = "0052_user_module_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE support_tickets SET status = 'under_review' "
        "WHERE status = 'answered'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE support_tickets SET status = 'answered' "
        "WHERE status = 'under_review'"
    )
