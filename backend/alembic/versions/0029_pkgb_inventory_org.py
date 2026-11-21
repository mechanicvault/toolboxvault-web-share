"""Review Round 1 · Package B — inventory organization (2026-10-19).

- inventory_locations — the owner's TIERED location tree for
  inventory (top tier = the toolbox / place, drawers under it):
  parent_id points up, NULL is a root. The FK from items carries
  ON DELETE SET NULL; deleting a node that still holds items or
  children is a service-level reassign-or-detach decision, never a
  silent orphan (the parts-tree doctrine).
- tools.location_id / batteries.location_id — the item's node.
  The free-text `location` column REMAINS as the denormalized
  display string, kept in sync by the service as the node's PATH
  ("Shop Toolbox / Left Drawer 2").
- Data: each owner's distinct existing free-text locations become
  top-level nodes and their items link to them (path == the old
  text for a top-level node, so nothing visible changes).
- tools.standing / batteries.standing — the item's standing:
  in_service | broken | in_repair | lost | stolen. Backfilled from
  repair_state (the repair trio); standing becomes the authority
  and repair_state stays as a mirrored legacy column.
- maintenance_log_entries.attachments — a log entry can carry
  documents (calibration certificates): storage keys + metadata,
  the same stored shape as item attachments.

Revision ID: 0029_pkgb_inventory_org
Revises: 0028_messaging_pool
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_pkgb_inventory_org"
down_revision: str | None = "0028_messaging_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "inventory_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["inventory_locations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_locations_owner_id", "inventory_locations", ["owner_id"]
    )
    op.create_index(
        "ix_inventory_locations_parent_id", "inventory_locations", ["parent_id"]
    )

    for table in ("tools", "batteries"):
        op.add_column(
            table,
            sa.Column(
                "location_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
        )
        # Batch mode: SQLite (the migration-test dialect) cannot
        # ALTER a foreign key into an existing table; Postgres
        # renders the same operations as plain ALTERs (0016's rule).
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table}_location_id",
                "inventory_locations",
                ["location_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index(f"ix_{table}_location_id", table, ["location_id"])
        op.add_column(
            table,
            sa.Column(
                "standing",
                sa.String(length=20),
                nullable=False,
                server_default="in_service",
            ),
        )
        # Standing starts as the item's repair standing.
        op.execute(f"UPDATE {table} SET standing = repair_state")

    op.add_column(
        "maintenance_log_entries",
        sa.Column(
            "attachments",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )

    # -- data: free-text locations become top-level tree nodes --------
    if is_postgres:
        op.execute(
            """
            INSERT INTO inventory_locations (id, owner_id, parent_id, name, sort_order)
            SELECT gen_random_uuid(), owner_id, NULL, location, 0 FROM (
                SELECT DISTINCT owner_id, location FROM tools WHERE location <> ''
                UNION
                SELECT DISTINCT owner_id, location FROM batteries WHERE location <> ''
            ) AS distinct_locations
            """
        )
        for table in ("tools", "batteries"):
            op.execute(
                f"""
                UPDATE {table} AS item
                SET location_id = node.id
                FROM inventory_locations AS node
                WHERE node.owner_id = item.owner_id
                  AND node.name = item.location
                  AND item.location <> ''
                """
            )
    else:
        import uuid as _uuid

        from datetime import datetime, timezone

        locations = sa.table(
            "inventory_locations",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("owner_id", postgresql.UUID(as_uuid=True)),
            sa.column("parent_id", postgresql.UUID(as_uuid=True)),
            sa.column("name", sa.String(length=200)),
            sa.column("sort_order", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        stamp = datetime.now(timezone.utc)
        pairs: set[tuple[str, str]] = set()
        for table in ("tools", "batteries"):
            rows = bind.execute(
                sa.text(
                    f"SELECT DISTINCT owner_id, location FROM {table} "
                    "WHERE location <> ''"
                )
            ).fetchall()
            for owner_id, location in rows:
                pairs.add((str(owner_id), location))
        node_ids: dict[tuple[str, str], _uuid.UUID] = {}
        inserts = []
        for owner_id, location in sorted(pairs):
            node_id = _uuid.uuid4()
            node_ids[(owner_id, location)] = node_id
            inserts.append(
                {
                    "id": node_id,
                    "owner_id": _uuid.UUID(owner_id),
                    "parent_id": None,
                    "name": location,
                    "sort_order": 0,
                    # SQLite has no now() for the server default.
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            )
        if inserts:
            op.bulk_insert(locations, inserts)
        for (owner_id, location), node_id in node_ids.items():
            for table in ("tools", "batteries"):
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET location_id = :node_id "
                        "WHERE owner_id = :owner_id AND location = :location"
                    ),
                    {
                        "node_id": str(node_id),
                        "owner_id": owner_id,
                        "location": location,
                    },
                )


def downgrade() -> None:
    op.drop_column("maintenance_log_entries", "attachments")
    for table in ("tools", "batteries"):
        op.drop_index(f"ix_{table}_location_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_location_id", type_="foreignkey")
        op.drop_column(table, "location_id")
        op.drop_column(table, "standing")
    op.drop_index("ix_inventory_locations_parent_id", table_name="inventory_locations")
    op.drop_index("ix_inventory_locations_owner_id", table_name="inventory_locations")
    op.drop_table("inventory_locations")
