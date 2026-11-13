"""3D Print Files page visitor counter (owner order, 2026-11-10).

The 3D Print Files page gets the teaser/Downloads pages' quiet
unique-visitor counter as its own: the same one-row-per-page
table (visitor_counter, migration 0064) gains the prints row,
id 3. The counting rules (its own counted cookie, the same
automation + operator IP exclusions) live in core/teaser.py;
this migration only seeds the row, exactly as 0094 seeded id 2.
The downgrade removes only this row — the table and the other
rows stay untouched.
"""

from alembic import op

revision = "0099_prints_visitor_counter"
down_revision = "0098_download_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO visitor_counter (id, count) "
        "SELECT 3, 0 WHERE NOT EXISTS (SELECT 1 FROM visitor_counter WHERE id = 3)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM visitor_counter WHERE id = 3")
