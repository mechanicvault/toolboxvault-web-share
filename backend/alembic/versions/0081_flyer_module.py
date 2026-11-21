"""0081: the flyers module (owner order, 2026-11-05 #10).

Three tables. Their definitions are WRITTEN INTO this script
(row 116 fix, 2026-11-18): the original version created them
straight off the module's live models, so a fresh build made
them with TODAY'S columns — and 0083 then failed adding
auto_hash a second time. A migration must carry the table
shape as of ITS OWN point in the chain; later migrations add
their pieces themselves. (The partial unique indexes and the
shape check below are that as-of shape, verbatim.)

- flyer_sources — one flyer spot per dealer company or per
  agent (platform seat or private record), with the source's
  visibility toggle, history setting, and standing flyer URL
  (+ the content hash the daily pull dedupes by).
- flyers — one posted flyer: stored PDF + rendered thumbnail,
  the date window it is current for, and its origin
  (link/upload/photos/standing).
- flyer_alert_prefs — the new-flyer notification's own
  per-user switch (a row exists only where flipped; absence
  means the default, ON).

Plus the module-control seed, the migration-0076 pattern:
flyers globally enabled, the three default groups
(mechanic_technician / shop_company / tool_dealer) enabled,
every tier enabled (god bypasses tier rows by design).

The module-control column names below match the live
production schema — module_state(module_id, globally_enabled),
module_access(id, module_id, account_group, enabled),
module_tier_access(id, module_id, tier, enabled) — verified
by \\d against production immediately before this migration
shipped (AGENTS.md migration rule, strengthened 2026-11-06:
the FINAL text is what gets verified). The live tables'
updated_at columns are NOT NULL with a now() default; the
seed inserts omit them on purpose so the default fires.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0081_flyer_module"
down_revision = "0080_truck_highest_balance"
branch_labels = None
depends_on = None

MODULE_ID = "flyers"
DEFAULT_GROUPS = ("mechanic_technician", "shop_company", "tool_dealer")
TIERS = ("normal", "moderator", "moderator_admin", "beta")


def _control_tables():
    meta = sa.MetaData()
    # NOTE: the live module-control tables also carry an
    # updated_at column (NOT NULL, default now()) — the mirrors
    # deliberately omit it so inserts let the database default
    # fire instead of writing a value.
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


def _create_flyer_tables() -> None:
    """The three flyer tables, defined as of 0081. NOTE:
    flyer_sources has NO auto_hash / auto_checked_at here —
    0083 adds those; that separation is the whole point of
    writing the definitions down (row 116)."""
    op.create_table(
        "flyer_sources",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "company_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "private_agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("private_agents.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "visible", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "history_visible",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "standing_url",
            sa.String(1000),
            nullable=False,
            server_default="",
        ),
        sa.Column("standing_hash", sa.String(64)),
        sa.Column("standing_checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        sa.CheckConstraint(
            "(kind = 'company' AND agent_user_id IS NULL"
            " AND private_agent_id IS NULL)"
            " OR (kind = 'agent' AND (agent_user_id IS NULL)"
            " <> (private_agent_id IS NULL))",
            name="ck_flyer_sources_shape",
        ),
    )
    op.create_index(
        "ix_flyer_sources_company_id", "flyer_sources", ["company_id"]
    )
    op.create_index(
        "uq_flyer_sources_company",
        "flyer_sources",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'company'"),
    )
    op.create_index(
        "uq_flyer_sources_platform_agent",
        "flyer_sources",
        ["company_id", "agent_user_id"],
        unique=True,
        postgresql_where=sa.text("agent_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_flyer_sources_private_agent",
        "flyer_sources",
        ["company_id", "private_agent_id"],
        unique=True,
        postgresql_where=sa.text("private_agent_id IS NOT NULL"),
    )
    op.create_table(
        "flyers",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("flyer_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "label", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column("pdf_key", sa.String(500), nullable=False),
        sa.Column("thumb_key", sa.String(500)),
        sa.Column(
            "page_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column(
            "origin_url",
            sa.String(1000),
            nullable=False,
            server_default="",
        ),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "posted_by_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
    op.create_index("ix_flyers_source_id", "flyers", ["source_id"])
    op.create_index("ix_flyers_content_hash", "flyers", ["content_hash"])
    op.create_index("ix_flyers_ends_on", "flyers", ["ends_on"])
    op.create_table(
        "flyer_alert_prefs",
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade() -> None:
    _create_flyer_tables()

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
    op.drop_table("flyer_alert_prefs")
    op.drop_table("flyers")
    op.drop_table("flyer_sources")
