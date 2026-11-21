"""Catalog library — the system's own tool database
(sheet rows 219 + 221).

Ryan's direction (2026-11-20): every successful grounded
import is stored in a system-level product library keyed by
brand + part number (and UPC where known), with pieces,
prices, photos, specs and warranty; the quick lookup checks
the library first and answers from it in about a second; the
web walk runs only on a library miss, and its result then
feeds the library. Dealer catalogs seed it (row 221).

Two brand-new tables; there is nothing to verify against the
live schema beyond their absence (checked 2026-11-20):
- catalog_products — one row per product, unique on the
  normalized (brand_key, model_key).
- catalog_pieces — one row per set piece, FK to its product,
  its own part number keyed for the reverse lookup (row 217).

Revision ID: 0113_catalog_library
Revises: 0112_usernames
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0113_catalog_library"
down_revision = "0112_usernames"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=False),
        sa.Column("brand_key", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("upc", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=400), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("size", sa.String(length=120), nullable=True),
        sa.Column("msrp", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("photos", sa.JSON(), nullable=True),
        sa.Column("specs", sa.JSON(), nullable=True),
        sa.Column("warranty_type", sa.String(length=40), nullable=True),
        sa.Column("warranty_months", sa.Integer(), nullable=True),
        sa.Column("warranty_terms", sa.Text(), nullable=True),
        sa.Column("is_set", sa.Boolean(), nullable=False),
        sa.Column("piece_count", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "brand_key", "model_key", name="uq_catalog_product_brand_model"
        ),
    )
    op.create_index(
        "ix_catalog_products_brand_key", "catalog_products", ["brand_key"]
    )
    op.create_index(
        "ix_catalog_products_model_key", "catalog_products", ["model_key"]
    )
    op.create_index("ix_catalog_products_upc", "catalog_products", ["upc"])
    op.create_table(
        "catalog_pieces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=400), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("model_key", sa.String(length=120), nullable=True),
        sa.Column("msrp", sa.Float(), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalog_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_pieces_product_id", "catalog_pieces", ["product_id"]
    )
    op.create_index(
        "ix_catalog_pieces_model_key", "catalog_pieces", ["model_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_pieces_model_key", table_name="catalog_pieces")
    op.drop_index("ix_catalog_pieces_product_id", table_name="catalog_pieces")
    op.drop_table("catalog_pieces")
    op.drop_index("ix_catalog_products_upc", table_name="catalog_products")
    op.drop_index(
        "ix_catalog_products_model_key", table_name="catalog_products"
    )
    op.drop_index(
        "ix_catalog_products_brand_key", table_name="catalog_products"
    )
    op.drop_table("catalog_products")
