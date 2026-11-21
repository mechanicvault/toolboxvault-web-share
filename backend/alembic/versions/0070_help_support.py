"""Help & Support as a main tab layout page (owner approved
2026-11-02): three schema moves.

1. forum_categories.system_key — the built-in rooms the system
   seeds and finds by key. Three rows are seeded here:

   - "Using Toolbox Vault" (site_help): the dedicated room for
     questions about using the website and the app — the Help &
     Support page's Ask-the-community tab embeds it. An ordinary
     room in every other way (threads, the paid posting gate).
   - "Bug Reports" (bug_reports) and "Feature Requests"
     (feature_requests): the PERMANENT boards (owner directive
     2026-11-02). The boards are fixtures of the forum: the rows
     can never be deleted or edited by anyone — no delete route
     exists for categories, and the service refuses every
     update to a permanent row, operator path included. Their
     POSTS stay powered by the feedback module (statuses, votes,
     comments, the roadmap tie-in — the boards' approved
     mechanics, unchanged); the category rows are their home in
     the forum's board list and carry their live counts.
     Individual posts inside them stay ordinary posts —
     permanence belongs to the boards only.

2. help_videos — the How-to videos tab's operator-managed list:
   a title, one line about what it teaches, the YouTube video
   id (videos are hosted on the Toolbox Vault YouTube channel
   and played in place — no video files on this server), which
   side it belongs to (website | app), a display order, and a
   published flag. Unpublished rows are drafts only operators
   see. The table starts EMPTY: the tab's honest "coming soon"
   state is the empty state, no fake content.

Revision ID: 0070_help_support
Revises: 0069_dealer_list_customization
Create Date: 2026-11-02
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0070_help_support"
down_revision = "0069_dealer_list_customization"
branch_labels = None
depends_on = None

# Fixed ids (the 0034 starter-set pattern): the built-in rooms
# are seeded identically in every environment.
SYSTEM_CATEGORIES: tuple[tuple[str, str, str, str, int], ...] = (
    (
        "0f0e0d0c-0006-4000-8000-000000000006",
        "site_help",
        "Using Toolbox Vault",
        "Questions about the website and the app — accounts, "
        "tools, claims, and how things work. (For fixing "
        "vehicles, Repair Help is the room.)",
        60,
    ),
    (
        "0f0e0d0c-0007-4000-8000-000000000007",
        "bug_reports",
        "Bug Reports",
        "Something broken? Tell us what you did, what you "
        "expected, and what happened instead. Reports are "
        "public, with a status you can follow.",
        70,
    ),
    (
        "0f0e0d0c-0008-4000-8000-000000000008",
        "feature_requests",
        "Feature Requests",
        "Something missing? Describe the job you're trying to "
        "get done. Requests are public, with a status you can "
        "follow — committed ones land on the What's coming "
        "roadmap.",
        80,
    ),
)


def upgrade() -> None:
    op.add_column(
        "forum_categories",
        sa.Column("system_key", sa.String(length=40), nullable=True),
    )
    # Batch mode: SQLite can't ALTER a constraint in place (the
    # migration tests run there); on Postgres batch is a
    # passthrough (the 0024 pattern).
    with op.batch_alter_table("forum_categories") as batch_op:
        batch_op.create_unique_constraint(
            "uq_forum_categories_system_key", ["system_key"]
        )

    categories = sa.table(
        "forum_categories",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("system_key", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # Timestamps ride the seed rows explicitly (the 0034 rule:
    # the migration test harness runs the same upgrade on
    # SQLite, where now() can't be evaluated by the server).
    seeded_at = datetime.now(timezone.utc)
    op.bulk_insert(
        categories,
        [
            {
                "id": uuid.UUID(row_id),
                "system_key": system_key,
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_active": True,
                "created_at": seeded_at,
                "updated_at": seeded_at,
            }
            for row_id, system_key, name, description, sort_order in SYSTEM_CATEGORIES
        ],
    )

    op.create_table(
        "help_videos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "summary", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column("youtube_id", sa.String(length=32), nullable=False),
        # website | app
        sa.Column(
            "section",
            sa.String(length=10),
            nullable=False,
            server_default="website",
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
    )
    op.create_index(
        "ix_help_videos_section", "help_videos", ["section"]
    )


def downgrade() -> None:
    op.drop_index("ix_help_videos_section", table_name="help_videos")
    op.drop_table("help_videos")
    categories = sa.table(
        "forum_categories",
        sa.column("id", postgresql.UUID(as_uuid=True)),
    )
    for row_id, *_rest in SYSTEM_CATEGORIES:
        op.execute(
            categories.delete().where(
                categories.c.id == uuid.UUID(row_id)
            )
        )
    with op.batch_alter_table("forum_categories") as batch_op:
        batch_op.drop_constraint(
            "uq_forum_categories_system_key", type_="unique"
        )
    op.drop_column("forum_categories", "system_key")
