"""Sharing rows keep no FK to items (found by the PG suite, row 117).

The four sharing-consent tables (shared_items,
peer_share_exclusions, peer_set_choices, share_exclusions)
pointed at tools/batteries with ON DELETE CASCADE — written in
2026-10 (migrations 0005/0006/0016/0031) so a tool delete would
never be blocked by share rows. The audit-trail build
(2026-10-19) then settled the opposite need: a deleted item's
share rows LINGER (resolution drops refs whose item is gone),
and a journal restore brings the item back to its shares.

SQLite never enforced the cascades, so the suite saw the
designed behavior; PostgreSQL enforces them, so on production
a delete silently destroyed the picks/exclusions/choices and
a restore brought the item back unshared. This migration
drops the seven item FKs. The columns stay (indexed,
polymorphic by item_kind — they never could be honest FKs for
both kinds at once); the owner FKs stay CASCADE (an account
deletion still takes its sharing setup with it).

Names verified against the production schema 2026-11-18:
five carry PostgreSQL's auto-names (<table>_<column>_fkey);
the two battery FKs were named fk_<table>_battery_id by
migration 0014. SQLite keeps FKs anonymous, so there the drop
goes through a batch recreate matched by name in the test
pre-state.

Revision ID: 0111_sharing_item_fks
Revises: 0110_rate_limit_events
Create Date: 2026-11-18
"""

from alembic import op

revision = "0111_sharing_item_fks"
down_revision = "0110_rate_limit_events"
branch_labels = None
depends_on = None

# (table, pg constraint name, column, referenced table)
_ITEM_FKS = [
    ("shared_items", "shared_items_tool_id_fkey", "tool_id", "tools"),
    ("shared_items", "fk_shared_items_battery_id", "battery_id", "batteries"),
    (
        "peer_share_exclusions",
        "peer_share_exclusions_tool_id_fkey",
        "tool_id",
        "tools",
    ),
    (
        "peer_share_exclusions",
        "fk_peer_share_exclusions_battery_id",
        "battery_id",
        "batteries",
    ),
    (
        "peer_set_choices",
        "peer_set_choices_set_tool_id_fkey",
        "set_tool_id",
        "tools",
    ),
    ("share_exclusions", "share_exclusions_tool_id_fkey", "tool_id", "tools"),
    (
        "share_exclusions",
        "share_exclusions_battery_id_fkey",
        "battery_id",
        "batteries",
    ),
]


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table, constraint, _column, _ref in _ITEM_FKS:
            op.drop_constraint(constraint, table, type_="foreignkey")
    else:
        # SQLite cannot drop a constraint in place; the batch
        # recreate matches it by name (the test pre-state names
        # them the way PostgreSQL auto-names them).
        for table, constraint, _column, _ref in _ITEM_FKS:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(constraint, type_="foreignkey")


def downgrade() -> None:
    for table, constraint, column, ref in _ITEM_FKS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                constraint, ref, [column], ["id"], ondelete="CASCADE"
            )
