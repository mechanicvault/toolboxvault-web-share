"""Tools For Sale + reputation (2026-10-19, community suite
build 2).

Four new tables, all marketplace-owned:

- sale_listings — the board's listings. Snapshot rows (title /
  brand / model copied at creation; photos copied into the
  marketplace storage namespace), so the only FK is the owner's.
  status starts "active"; sold/removed rows persist (a sold
  listing anchors its reputation interaction).
- deal_interactions — completed deals between two people, the
  only rateable thing. Party ids are PLAIN columns (no FK) with
  name snapshots BY DESIGN: the record is two-party history and
  must survive either account's deletion so the other side's
  completed-deals count and published ratings stay honest.
  dedupe_key is unique — one interaction per deal.
- ratings — one per side per interaction (unique pair),
  1–5 stars (check), published_at NULL while double-blind-held.
  rater/ratee are plain columns too: a deleted rater's stars
  keep counting, displayed as "Former member".
- thread_completions — one row per (anchored thread,
  participant) who closed it as a completed deal; the second
  row creates the interaction.

No module_access seed for marketplace: the control service falls
back to the manifest's default_groups (all four) when a module
has no rows — the same posture every post-0008 module shipped
with. No system-setting seed: the kill switch
(`community.marketplace_enabled`) reads its code default (ON)
until an operator edits it.

Revision ID: 0033_marketplace
Revises: 0032_reports_alignment
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_marketplace"
down_revision: str | None = "0032_reports_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sale_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "listing_type",
            sa.String(length=20),
            nullable=False,
            server_default="for_sale",
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "condition", sa.String(length=120), nullable=False, server_default=""
        ),
        sa.Column("brand", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "delivery_local_pickup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "delivery_ships",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("public_area_label", sa.String(length=120), nullable=True),
        sa.Column("show_phone_override", sa.Boolean(), nullable=True),
        sa.Column(
            "source_kind", sa.String(length=20), nullable=False, server_default=""
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_sale_listings_owner_id", "sale_listings", ["owner_id"])
    op.create_index("ix_sale_listings_status", "sale_listings", ["status"])

    op.create_table(
        "deal_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_low_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_high_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "party_low_name", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "party_high_name",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "source", sa.String(length=20), nullable=False, server_default="listing"
        ),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "context_title", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("dedupe_key", sa.String(length=80), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_interaction_dedupe"),
    )
    op.create_index(
        "ix_deal_interactions_party_low_id", "deal_interactions", ["party_low_id"]
    )
    op.create_index(
        "ix_deal_interactions_party_high_id", "deal_interactions", ["party_high_id"]
    )

    op.create_table(
        "ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rater_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ratee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("stars >= 1 AND stars <= 5", name="ck_ratings_stars"),
        sa.ForeignKeyConstraint(["interaction_id"], ["deal_interactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "interaction_id", "rater_id", name="uq_rating_interaction_rater"
        ),
    )
    op.create_index("ix_ratings_interaction_id", "ratings", ["interaction_id"])
    op.create_index("ix_ratings_rater_id", "ratings", ["rater_id"])
    op.create_index("ix_ratings_ratee_id", "ratings", ["ratee_id"])

    op.create_table(
        "thread_completions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "user_id", name="uq_thread_completion_user"),
    )
    op.create_index("ix_thread_completions_thread_id", "thread_completions", ["thread_id"])
    op.create_index("ix_thread_completions_user_id", "thread_completions", ["user_id"])


def downgrade() -> None:
    op.drop_table("thread_completions")
    op.drop_table("ratings")
    op.drop_table("deal_interactions")
    op.drop_table("sale_listings")
