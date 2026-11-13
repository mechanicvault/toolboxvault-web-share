"""0081: the flyers module (owner order, 2026-11-05 #10).

Three tables, created with SQLAlchemy DDL straight off the
module's models (so the partial unique indexes and the shape
check ride along verbatim):

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


def _register_fk_targets() -> None:
    """The flyer tables' foreign keys name tables owned by
    other modules (users, dealer_companies, private_agents).
    SQLAlchemy resolves those string references against the
    shared metadata at DDL compile time, so the owning model
    modules must be imported before the flyer tables are
    created or dropped — the test suite imports everything and
    masks this; the alembic boot process does not. (Deploy
    crash-loop on first ship, 2026-11-06: NoReferencedTableError
    for dealer_companies.)"""
    from app.modules.core import models as _core_models  # noqa: F401
    from app.modules.dealers import models as _dealer_models  # noqa: F401


def upgrade() -> None:
    from app.modules.flyers import models as flyer_models

    _register_fk_targets()
    bind = op.get_bind()
    flyer_models.FlyerSource.__table__.create(bind, checkfirst=False)
    flyer_models.Flyer.__table__.create(bind, checkfirst=False)
    flyer_models.FlyerAlertPref.__table__.create(bind, checkfirst=False)

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
    from app.modules.flyers import models as flyer_models

    _register_fk_targets()
    bind = op.get_bind()
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
    flyer_models.FlyerAlertPref.__table__.drop(bind, checkfirst=False)
    flyer_models.Flyer.__table__.drop(bind, checkfirst=False)
    flyer_models.FlyerSource.__table__.drop(bind, checkfirst=False)
