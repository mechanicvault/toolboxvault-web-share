"""Dealer build (2026-10-20): service-area geometry, the geocode
cache, and warranty service requests.

- dealer_agent_profiles gains the service-area geometry: area_type
  (polygon|radius), area_polygon (GeoJSON), area_center_lat/lng +
  area_radius_km, area_zip. The text service_area label is
  unchanged; publicly_listed gains a service rule (an area must
  exist) enforced in the portal service, not the schema.
- geocode_cache: normalized query -> point, platform data (the
  Find-an-Agent geocoder's memory: bundled ZIP centroids first,
  Nominatim second, each place resolved once).
- warranty_service_requests: the broken-item -> dealer workflow's
  record (snapshots of item + requester, routing list, claim and
  status flow). Item and repair links are plain columns by design
  (the ledger pattern), so the table carries no cross-module FKs
  beyond users + the (SET NULL) company tag.

Revision ID: 0037_dealer_build
Revises: 0036_gap_wave1
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_dealer_build"
down_revision: str | None = "0036_gap_wave1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- service-area geometry --------------------------------------------
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("area_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column(
            "area_polygon",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("area_center_lat", sa.Float(), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("area_center_lng", sa.Float(), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column("area_radius_km", sa.Float(), nullable=True),
    )
    op.add_column(
        "dealer_agent_profiles",
        sa.Column(
            "area_zip", sa.String(length=10), nullable=False, server_default=""
        ),
    )

    # -- geocode cache ------------------------------------------------------
    op.create_table(
        "geocode_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_key", sa.String(length=300), nullable=False),
        sa.Column("query_text", sa.String(length=300), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_key"),
    )
    op.create_index(
        "ix_geocode_cache_query_key", "geocode_cache", ["query_key"]
    )

    # -- warranty service requests -------------------------------------------
    op.create_table(
        "warranty_service_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "requester_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_name", sa.String(length=300), nullable=False),
        sa.Column(
            "repair_record_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("item_kind", sa.String(length=10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_name", sa.String(length=300), nullable=False),
        sa.Column("brand", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "serials",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_status", sa.String(length=20), nullable=False),
        sa.Column("requester_name", sa.String(length=300), nullable=False),
        sa.Column("requester_email", sa.String(length=320), nullable=False),
        sa.Column("requester_phone", sa.String(length=100), nullable=False),
        sa.Column("requester_area", sa.String(length=300), nullable=False),
        sa.Column(
            "routed_agent_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "claimed_by_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "requester_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["claimed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["dealer_companies.id"], ondelete="SET NULL"
        ),
        # requester_id deliberately carries NO foreign key: the
        # request tombstones when its requester deletes their
        # account (forum doctrine), which an FK would forbid.
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_warranty_service_requests_requester_id",
        "warranty_service_requests",
        ["requester_id"],
    )
    op.create_index(
        "ix_warranty_service_requests_company_id",
        "warranty_service_requests",
        ["company_id"],
    )
    op.create_index(
        "ix_warranty_service_requests_repair_record_id",
        "warranty_service_requests",
        ["repair_record_id"],
    )
    op.create_index(
        "ix_warranty_service_requests_claimed_by_id",
        "warranty_service_requests",
        ["claimed_by_id"],
    )
    op.create_index(
        "ix_warranty_service_requests_status",
        "warranty_service_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("warranty_service_requests")
    op.drop_table("geocode_cache")
    for column in (
        "area_zip",
        "area_radius_km",
        "area_center_lng",
        "area_center_lat",
        "area_polygon",
        "area_type",
    ):
        op.drop_column("dealer_agent_profiles", column)
