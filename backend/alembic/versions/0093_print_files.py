"""0093: the 3D print files shelf (owner order 2026-11-08,
Downloads Part 2).

Six new tables for the community shelf of free print files:

- print_files — one showcased file: publisher, the prints
  module's OWN category key, the removal tombstone, the
  current-version pointer, and the public counters (print
  downloads across all versions, STEP downloads, the rating
  sum/count the average reads from).
- print_file_versions — one uploaded version (print file
  required, STEP optional); versions only rise, old ones stay
  downloadable. Unique per (file, version number).
- print_ratings — one member's stars for one file, unique per
  (file, member).
- print_comments — forum posture: live / removed_author /
  removed_mod plus the author_gone tombstone.
- print_reports — the flags feeding the shared moderation
  queue (the forum_reports shape), file_id denormalized onto
  comment reports.
- print_maker_links — a member's outside maker-profile links.

Plus the module-control seed, the migration-0081 pattern:
prints globally enabled, all four groups enabled
(mechanic_technician / shop_company / tool_dealer /
insurance), every tier enabled (god bypasses tier rows by
design).

Plain table creation from explicit definitions — no model
__table__ DDL and no hand-written SQL beyond the seed inserts
(the 0084/0091/0092 posture). The module-control column names
match the live production schema — module_state(module_id,
globally_enabled), module_access(id, module_id, account_group,
enabled), module_tier_access(id, module_id, tier, enabled) —
verified against production immediately before shipping (the
standing migration rule); the live tables' updated_at columns
are NOT NULL with a now() default, so the seed inserts omit
them on purpose and let the default fire.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0093_print_files"
down_revision = "0092_download_files"
branch_labels = None
depends_on = None

MODULE_ID = "prints"
DEFAULT_GROUPS = (
    "mechanic_technician",
    "shop_company",
    "tool_dealer",
    "insurance",
)
TIERS = ("normal", "moderator", "moderator_admin", "beta")


def _control_tables():
    meta = sa.MetaData()
    module_state = sa.Table(
        "module_state",
        meta,
        sa.Column("module_id", sa.String(64), primary_key=True),
        sa.Column("globally_enabled", sa.Boolean(), nullable=False),
    )
    module_access = sa.Table(
        "module_access",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("account_group", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    module_tier_access = sa.Table(
        "module_tier_access",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    return module_state, module_access, module_tier_access


def _timestamps():
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "print_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("publisher_gone", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("category_key", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="live", nullable=False),
        sa.Column("removed_by_id", sa.UUID(), nullable=True),
        sa.Column("removed_reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("download_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_download_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rating_sum", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rating_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("preview_key", sa.String(length=300), nullable=True),
        sa.Column("preview_content_type", sa.String(length=100), server_default="", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["publisher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_print_files_publisher_id", "print_files", ["publisher_id"])
    op.create_index("ix_print_files_category_key", "print_files", ["category_key"])
    op.create_index("ix_print_files_status", "print_files", ["status"])

    op.create_table(
        "print_file_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("print_key", sa.String(length=300), nullable=False),
        sa.Column("print_filename", sa.String(length=200), nullable=False),
        sa.Column("print_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_key", sa.String(length=300), nullable=True),
        sa.Column("step_filename", sa.String(length=200), server_default="", nullable=False),
        sa.Column("step_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("note", sa.String(length=500), server_default="", nullable=False),
        sa.Column("downloads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_downloads", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["file_id"], ["print_files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "version_number", name="uq_print_version_file_number"),
    )
    op.create_index("ix_print_file_versions_file_id", "print_file_versions", ["file_id"])

    op.create_table(
        "print_ratings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["file_id"], ["print_files.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "user_id", name="uq_print_rating_file_user"),
    )
    op.create_index("ix_print_ratings_file_id", "print_ratings", ["file_id"])
    op.create_index("ix_print_ratings_user_id", "print_ratings", ["user_id"])

    op.create_table(
        "print_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="live", nullable=False),
        sa.Column("removed_reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("author_gone", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["print_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_print_comments_file_id", "print_comments", ["file_id"])
    op.create_index("ix_print_comments_author_id", "print_comments", ["author_id"])

    op.create_table(
        "print_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("comment_id", sa.UUID(), nullable=True),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(length=500), server_default="", nullable=False),
        sa.Column("resolved_by_id", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["file_id"], ["print_files.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_print_reports_file_id", "print_reports", ["file_id"])
    op.create_index("ix_print_reports_reporter_id", "print_reports", ["reporter_id"])

    op.create_table(
        "print_maker_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_print_maker_links_user_id", "print_maker_links", ["user_id"])

    import uuid

    module_state, module_access, module_tier_access = _control_tables()
    op.bulk_insert(
        module_state,
        [{"module_id": MODULE_ID, "globally_enabled": True}],
    )
    op.bulk_insert(
        module_access,
        [
            {
                "id": uuid.uuid4(),
                "module_id": MODULE_ID,
                "account_group": group,
                "enabled": True,
            }
            for group in DEFAULT_GROUPS
        ],
    )
    op.bulk_insert(
        module_tier_access,
        [
            {
                "id": uuid.uuid4(),
                "module_id": MODULE_ID,
                "tier": tier,
                "enabled": True,
            }
            for tier in TIERS
        ],
    )


def downgrade() -> None:
    module_state, module_access, module_tier_access = _control_tables()
    op.execute(
        module_tier_access.delete().where(
            module_tier_access.c.module_id == MODULE_ID
        )
    )
    op.execute(
        module_access.delete().where(module_access.c.module_id == MODULE_ID)
    )
    op.execute(
        module_state.delete().where(module_state.c.module_id == MODULE_ID)
    )
    op.drop_index("ix_print_maker_links_user_id", table_name="print_maker_links")
    op.drop_table("print_maker_links")
    op.drop_index("ix_print_reports_reporter_id", table_name="print_reports")
    op.drop_index("ix_print_reports_file_id", table_name="print_reports")
    op.drop_table("print_reports")
    op.drop_index("ix_print_comments_author_id", table_name="print_comments")
    op.drop_index("ix_print_comments_file_id", table_name="print_comments")
    op.drop_table("print_comments")
    op.drop_index("ix_print_ratings_user_id", table_name="print_ratings")
    op.drop_index("ix_print_ratings_file_id", table_name="print_ratings")
    op.drop_table("print_ratings")
    op.drop_index("ix_print_file_versions_file_id", table_name="print_file_versions")
    op.drop_table("print_file_versions")
    op.drop_index("ix_print_files_status", table_name="print_files")
    op.drop_index("ix_print_files_category_key", table_name="print_files")
    op.drop_index("ix_print_files_publisher_id", table_name="print_files")
    op.drop_table("print_files")
