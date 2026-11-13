"""0086: the onboarding wizard system (owner design 2026-10-31,
built 2026-11-07) — one new table, created with SQLAlchemy DDL
straight off the owning module's model, the 0082/0085 pattern:

- onboarding_progress (core) — one row per (account, setup step):
  the guided pass's progress (done | skipped | notified), the
  "__fresh__" marker every post-wizard account is born with, the
  "__baseline__" module snapshot the new-feature detection reads,
  and the "__dismissed__" waiver row. It stores NO settings — the
  wizard writes through the same machinery Settings uses.

user_id is a plain id, not a foreign key (the 0038 lesson), so
this migration references no other table and imports only core's
models for the DDL compile.
"""

from alembic import op

revision = "0086_onboarding"
down_revision = "0085_admin_lane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.modules.core import models as core_models

    bind = op.get_bind()
    core_models.OnboardingProgress.__table__.create(bind, checkfirst=False)


def downgrade() -> None:
    from app.modules.core import models as core_models

    bind = op.get_bind()
    core_models.OnboardingProgress.__table__.drop(bind, checkfirst=False)
