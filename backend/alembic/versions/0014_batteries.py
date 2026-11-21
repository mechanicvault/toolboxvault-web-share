"""Batteries: first-class asset records in Asset Inventory (owner
spec 2026-10-18 15:35, shape decided 18:01).

Batteries are their OWN records — own serials, photos, receipts,
custom fields and warranty clocks — with an optional "currently in"
link to a tool. The link lives on the battery
(batteries.currently_in_tool_id → tools.id, ON DELETE SET NULL):
batteries migrate between tools and outlive them.

Changes:
  - New `batteries` table mirroring `tools` (identity, money,
    custom_data, attachments, search vector + the same style of
    trigger) plus the battery-specific columns (platform, voltage,
    capacity_ah, chemistry, warranty_months).
  - `shared_items` gains item_kind ('tool' default — every existing
    row is a tool) + battery_id; tool_id becomes nullable. Same
    field rules share batteries with shops/insurers.
  - `peer_share_exclusions` gains the same discriminator so a
    battery can be withheld from peer viewers like a tool.

Downgrade drops the battery rows from the sharing tables (they
cannot be represented in the old shape), restores the original
constraints, and drops `batteries`.

Revision ID: 0014_batteries
Revises: 0013_backup_runs
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_batteries"
down_revision: str | Sequence[str] | None = "0013_backup_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEARCH_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION batteries_search_vector_update() RETURNS trigger AS $$
DECLARE
    custom_text text := '';
    r record;
BEGIN
    -- Same contract as tools: searchable custom-field values (plus
    -- their labels) join the vector.
    FOR r IN
        SELECT COALESCE(fd.label, '') AS label, v.value AS value
        FROM jsonb_each_text(COALESCE(NEW.custom_data, '{}'::jsonb)) AS v(key, value)
        LEFT JOIN field_definitions fd ON fd.id::text = v.key
        WHERE fd.id IS NULL OR fd.searchable
    LOOP
        custom_text := custom_text || ' ' || r.label || ' ' || r.value;
    END LOOP;

    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.brand, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.model, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.serial_number, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.platform, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.notes, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.condition, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.location, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.chemistry, '')), 'D') ||
        setweight(to_tsvector('english', custom_text), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

SEARCH_TRIGGER_SQL = """
CREATE TRIGGER batteries_search_vector_trigger
BEFORE INSERT OR UPDATE ON batteries
FOR EACH ROW EXECUTE FUNCTION batteries_search_vector_update();
"""


def upgrade() -> None:
    op.create_table(
        "batteries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("brand", sa.String(200), nullable=False, server_default=""),
        sa.Column("model", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "serial_number", sa.String(200), nullable=False, server_default=""
        ),
        sa.Column("condition", sa.String(50), nullable=False, server_default=""),
        sa.Column(
            "category", sa.String(200), nullable=False, server_default="Battery"
        ),
        sa.Column("location", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("purchase_price", sa.Numeric(12, 2)),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("replacement_cost", sa.Numeric(12, 2)),
        sa.Column("msrp", sa.Numeric(12, 2)),
        sa.Column("platform", sa.String(100), nullable=False, server_default=""),
        sa.Column("voltage", sa.Numeric(6, 2)),
        sa.Column("capacity_ah", sa.Numeric(6, 2)),
        sa.Column("chemistry", sa.String(100), nullable=False, server_default=""),
        sa.Column("warranty_months", sa.Integer()),
        sa.Column(
            "currently_in_tool_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "custom_data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["currently_in_tool_id"], ["tools.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_batteries_owner_id", "batteries", ["owner_id"])
    op.create_index(
        "ix_batteries_currently_in_tool_id", "batteries", ["currently_in_tool_id"]
    )
    op.create_index(
        "ix_batteries_search_vector",
        "batteries",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.execute(SEARCH_FUNCTION_SQL)
    op.execute(SEARCH_TRIGGER_SQL)

    # -- sharing tables learn the second item kind -------------------
    for table, old_uq, new_uq in (
        (
            "shared_items",
            "uq_shared_item_owner_tool_group",
            "uq_shared_item_owner_item_group",
        ),
        (
            "peer_share_exclusions",
            "uq_peer_exclusion_owner_tool",
            "uq_peer_exclusion_owner_item",
        ),
    ):
        op.add_column(
            table,
            sa.Column(
                "item_kind",
                sa.String(20),
                nullable=False,
                server_default="tool",
            ),
        )
        op.add_column(
            table, sa.Column("battery_id", sa.UUID(), nullable=True)
        )
        op.create_foreign_key(
            f"fk_{table}_battery_id",
            table,
            "batteries",
            ["battery_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_battery_id", table, ["battery_id"])
        op.alter_column(table, "tool_id", nullable=True)
        op.drop_constraint(old_uq, table, type_="unique")
        new_columns = ["owner_id", "item_kind", "tool_id", "battery_id"]
        if table == "shared_items":
            new_columns.append("recipient_group")
        op.create_unique_constraint(new_uq, table, new_columns)


def downgrade() -> None:
    for table, old_uq, new_uq in (
        (
            "shared_items",
            "uq_shared_item_owner_tool_group",
            "uq_shared_item_owner_item_group",
        ),
        (
            "peer_share_exclusions",
            "uq_peer_exclusion_owner_tool",
            "uq_peer_exclusion_owner_item",
        ),
    ):
        # Battery rows have no old-shape representation: drop them.
        op.execute(f"DELETE FROM {table} WHERE item_kind <> 'tool'")
        op.drop_constraint(new_uq, table, type_="unique")
        op.create_unique_constraint(
            old_uq,
            table,
            ["owner_id", "tool_id"]
            + (["recipient_group"] if table == "shared_items" else []),
        )
        op.alter_column(table, "tool_id", nullable=False)
        op.drop_index(f"ix_{table}_battery_id", table_name=table)
        op.drop_constraint(f"fk_{table}_battery_id", table, type_="foreignkey")
        op.drop_column(table, "battery_id")
        op.drop_column(table, "item_kind")

    op.execute("DROP TRIGGER IF EXISTS batteries_search_vector_trigger ON batteries")
    op.execute("DROP FUNCTION IF EXISTS batteries_search_vector_update()")
    op.drop_index("ix_batteries_search_vector", table_name="batteries")
    op.drop_index("ix_batteries_currently_in_tool_id", table_name="batteries")
    op.drop_index("ix_batteries_owner_id", table_name="batteries")
    op.drop_table("batteries")
