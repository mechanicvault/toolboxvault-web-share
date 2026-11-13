"""Importer smart value matching (2026-10-19) — learned mappings.

Ryan's rule: an import must MATCH values interactively — his
dealer column may say "matco" while the site holds "Matco
Incorporated"; the importer asks once, applies the answer across
the whole file, and REMEMBERS it. This migration adds the memory:

- import_value_mappings — the owner's learned answers, one row per
  (owner, field, normalized raw value): map (to a company / tree
  node id, or a canonical brand/category/tag string), create (as a
  new value), or unset (drop it). Deleting a row in Settings makes
  the importer ask again.

No data movement: the table starts empty and fills as users answer.

Revision ID: 0030_import_value_matching
Revises: 0029_pkgb_inventory_org
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_import_value_matching"
down_revision: str | None = "0029_pkgb_inventory_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_value_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("raw_value", sa.String(length=500), nullable=False),
        sa.Column("normalized", sa.String(length=500), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_value", sa.String(length=500), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "field",
            "normalized",
            name="uq_import_value_mappings_owner_field_normalized",
        ),
    )
    op.create_index(
        "ix_import_value_mappings_owner_id", "import_value_mappings", ["owner_id"]
    )
    op.create_index(
        "ix_import_value_mappings_normalized",
        "import_value_mappings",
        ["normalized"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_import_value_mappings_normalized", table_name="import_value_mappings"
    )
    op.drop_index(
        "ix_import_value_mappings_owner_id", table_name="import_value_mappings"
    )
    op.drop_table("import_value_mappings")
