"""Downloads page visitor counter (owner order, 2026-11-08).

The Downloads page gets the teaser page's quiet unique-visitor
counter as its own: the same one-row-per-page table
(visitor_counter, migration 0064) gains the Downloads row,
id 2. The counting rules (its own counted cookie, the same
automation + operator IP exclusions) live in core/teaser.py;
this migration only seeds the row, exactly as 0064 seeded id 1.
The downgrade removes only this row — the table and the teaser
row are 0064's and stay untouched.
"""

from alembic import op

revision = "0094_downloads_visitor_counter"
down_revision = "0093_print_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO visitor_counter (id, count) "
        "SELECT 2, 0 WHERE NOT EXISTS (SELECT 1 FROM visitor_counter WHERE id = 2)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM visitor_counter WHERE id = 2")
