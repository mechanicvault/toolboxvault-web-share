"""Community Forum (2026-10-20, community suite build 3).

Four new tables, all forum-owned:

- forum_categories — the operator's rooms, SEEDED here with the
  mechanic-first starter set (General Discussion, Tool Talk,
  Repair Help, Deals & Finds, Shop Talk). Operators rename /
  reorder / archive them from the forum's admin routes; archive
  is a flag, never a delete, so thread history is never
  orphaned.
- forum_threads — one discussion: title, the moderator levers
  (pinned / locked), the firewall hold flag (a held opener hides
  the whole thread until released), and the account-deletion
  tombstone flag. author_id is a PLAIN column (no FK) BY DESIGN:
  threads survive their author's deletion as "Former member"
  history (the marketplace two-party doctrine).
- forum_posts — the opener + flat replies (quote + link
  snapshots ride the row). status is the visibility state
  machine: visible | held | removed_author | removed_mod.
  author_id plain for the same reason as threads.
- forum_reports — one member's report of one post, feeding the
  moderation queue (the message_reports shape). reporter_id
  keeps its FK: a report is the reporter's own record and goes
  with their account.

No module_access seed for forum: the control service falls back
to the manifest's default_groups (all four) when a module has no
rows — the same posture every post-0008 module shipped with. No
system-setting seed: the kill switch (`community.forum_enabled`)
reads its code default (ON) until an operator edits it.

Revision ID: 0034_forum
Revises: 0033_marketplace
Create Date: 2026-10-20
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_forum"
down_revision: str | None = "0033_marketplace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The starter set (seeded with fixed ids so the seed is stable
# across environments; operators rename/archive from there).
STARTER_CATEGORIES: tuple[tuple[str, str, str, int], ...] = (
    (
        "0f0e0d0c-0001-4000-8000-000000000001",
        "General Discussion",
        "Anything that doesn't fit the other rooms — introductions, "
        "shop life, and community news.",
        10,
    ),
    (
        "0f0e0d0c-0002-4000-8000-000000000002",
        "Tool Talk",
        "Tools themselves: reviews, comparisons, new arrivals, and "
        "what's worth the money.",
        20,
    ),
    (
        "0f0e0d0c-0003-4000-8000-000000000003",
        "Repair Help",
        "Stuck on a job? Ask the room — symptoms, diagnostics, and "
        "the fixes that worked.",
        30,
    ),
    (
        "0f0e0d0c-0004-4000-8000-000000000004",
        "Deals & Finds",
        "Sales, truck deals, and the bargains worth driving for. "
        "Link your Tools For Sale listings and Community Parts.",
        40,
    ),
    (
        "0f0e0d0c-0005-4000-8000-000000000005",
        "Shop Talk",
        "Running a shop or a crew: hiring, pricing, customers, and "
        "the business side of the trade.",
        50,
    ),
)


def upgrade() -> None:
    op.create_table(
        "forum_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "forum_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Plain (no FK) by design — see the module docstring.
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "locked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "held", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "author_gone", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "last_post_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_post_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["category_id"], ["forum_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forum_threads_category_id", "forum_threads", ["category_id"])
    op.create_index("ix_forum_threads_author_id", "forum_threads", ["author_id"])
    op.create_index("ix_forum_threads_held", "forum_threads", ["held"])
    op.create_table(
        "forum_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Plain (no FK) by design — see the module docstring.
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="visible"
        ),
        sa.Column(
            "removed_reason", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column("flags", sa.Text(), nullable=False, server_default=""),
        sa.Column("quote_post_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "quote_author_name",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "quote_excerpt", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "link_type", sa.String(length=20), nullable=False, server_default=""
        ),
        sa.Column("link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "link_title", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "author_gone", sa.Boolean(), nullable=False, server_default=sa.false()
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
        sa.ForeignKeyConstraint(["thread_id"], ["forum_threads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forum_posts_thread_id", "forum_posts", ["thread_id"])
    op.create_index("ix_forum_posts_author_id", "forum_posts", ["author_id"])
    op.create_index("ix_forum_posts_status", "forum_posts", ["status"])
    op.create_table(
        "forum_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reason", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="open"
        ),
        sa.Column(
            "resolution", sa.String(length=500), nullable=False, server_default=""
        ),
        sa.Column("resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["forum_posts.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["forum_threads.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forum_reports_post_id", "forum_reports", ["post_id"])
    op.create_index("ix_forum_reports_thread_id", "forum_reports", ["thread_id"])
    op.create_index("ix_forum_reports_reporter_id", "forum_reports", ["reporter_id"])

    categories = sa.table(
        "forum_categories",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # Timestamps ride the seed rows explicitly: the server default
    # is now(), which only Postgres can evaluate (the migration
    # test harness runs the same upgrade on SQLite).
    seeded_at = datetime.now(timezone.utc)
    op.bulk_insert(
        categories,
        [
            {
                "id": uuid.UUID(row_id),
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_active": True,
                "created_at": seeded_at,
                "updated_at": seeded_at,
            }
            for row_id, name, description, sort_order in STARTER_CATEGORIES
        ],
    )


def downgrade() -> None:
    op.drop_table("forum_reports")
    op.drop_table("forum_posts")
    op.drop_table("forum_threads")
    op.drop_table("forum_categories")
