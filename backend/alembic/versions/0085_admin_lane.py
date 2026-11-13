"""0085: the admin lane (owner program, 2026-11-06 23:14 +
23:45) — two tables, created with SQLAlchemy DDL straight off
the owning modules' models, the 0082 pattern:

- site_stats_snapshots (core) — one row per day of site state
  (users by tier, free vs paying, MRR) that the admin Site
  Stats widget's day-over-day deltas read. Timestamps can't
  reconstruct what tier or plan a day ended in, so the jobs
  service snapshots it daily.

- community_blocks (forum) — one member's block from ONE
  community feature (forums | feedback_boards |
  community_parts), imposed/lifted by god + moderator_admin
  seats only. Per-feature and surgical — NOT the platform ban:
  the account, its inventory and every other feature stay
  untouched. Lifted, never deleted; one ACTIVE block per
  (member, feature) by partial unique index.

community_blocks.user_id references users (core) by string FK,
so core's models are imported before the DDL compiles — the
0081 lesson (the test suite imports everything and masks a
missing import; the alembic boot process does not).
"""

from alembic import op

revision = "0085_admin_lane"
down_revision = "0084_boards_urgency"
branch_labels = None
depends_on = None


def _register_fk_targets() -> None:
    """community_blocks references users.id by string;
    SQLAlchemy resolves string FKs against the shared metadata
    at DDL compile time, so the owning module must be imported
    first."""
    from app.modules.core import models as _core_models  # noqa: F401


def upgrade() -> None:
    from app.modules.core import models as core_models
    from app.modules.forum import models as forum_models

    _register_fk_targets()
    bind = op.get_bind()
    core_models.SiteStatsSnapshot.__table__.create(bind, checkfirst=False)
    forum_models.CommunityBlock.__table__.create(bind, checkfirst=False)


def downgrade() -> None:
    from app.modules.core import models as core_models
    from app.modules.forum import models as forum_models

    _register_fk_targets()
    bind = op.get_bind()
    forum_models.CommunityBlock.__table__.drop(bind, checkfirst=False)
    core_models.SiteStatsSnapshot.__table__.drop(bind, checkfirst=False)
