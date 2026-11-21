"""Used Parts module (2026-10-19, blueprint §18): the owner's
location tree + part records.

- part_locations — the owner's own tree (warehouse → aisle → bin):
  parent_id points up, NULL is a root. Levels are labels
  (warehouse|aisle|bin|shelf|other); the FK carries no cascade —
  deleting a node that still holds parts or children is a
  service-level reassign-or-detach decision, never a silent orphan.
- parts — minimal core by design (title, quantity, condition,
  notes, photos as storage keys): everything specific is a
  user-defined field through the shared custom-fields engine
  (field_definitions.item_type 'part' — an application-level axis
  value, so NO schema change to field_definitions), values in
  custom_data. converted_tool_id records the one-way "Add to Asset
  Inventory" copy (SET NULL if the tool is later deleted).

No module_access seed: the control service falls back to the
manifest's default_groups (mechanic + shop) when a module has no
rows — the same posture every post-0008 module shipped with.

Revision ID: 0026_parts
Revises: 0025_corporate_directory
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_parts"
down_revision: str | None = "0025_corporate_directory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "part_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "level", sa.String(length=20), nullable=False, server_default="other"
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
        sa.ForeignKeyConstraint(["parent_id"], ["part_locations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_part_locations_owner_id", "part_locations", ["owner_id"]
    )
    op.create_index(
        "ix_part_locations_parent_id", "part_locations", ["parent_id"]
    )

    op.create_table(
        "parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "condition", sa.String(length=50), nullable=False, server_default=""
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "custom_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "converted_tool_id", postgresql.UUID(as_uuid=True), nullable=True
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
        sa.CheckConstraint("quantity >= 1", name="ck_parts_quantity_min"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["location_id"], ["part_locations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["converted_tool_id"], ["tools.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parts_owner_id", "parts", ["owner_id"])
    op.create_index("ix_parts_location_id", "parts", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_parts_location_id", table_name="parts")
    op.drop_index("ix_parts_owner_id", table_name="parts")
    op.drop_table("parts")
    op.drop_index("ix_part_locations_parent_id", table_name="part_locations")
    op.drop_index("ix_part_locations_owner_id", table_name="part_locations")
    op.drop_table("part_locations")
