"""0087: the admin polish lane (owner corrections, 2026-11-07)
— one new table, created with SQLAlchemy DDL straight off the
owning module's model, the 0082/0085/0086 pattern:

- ai_usage (billing) — one row per METERED AI action: when it
  ran, which action consumed it, what it was for (the consumer's
  subject), provider + model, provider call count, token counts,
  and the wallet credits charged. The wallet ledger records
  spends only, so at the default price of 0 an AI call left no
  trace and token counts were discarded by the transports; the
  admin AI Usage report reads THIS table. History starts with
  this migration — no earlier usage was ever recorded.

ai_usage.user_id references users (core) by string FK, so
core's models are imported before the DDL compiles — the 0081
lesson (the test suite imports everything and masks a missing
import; the alembic boot process does not).
"""

from alembic import op

revision = "0087_ai_usage"
down_revision = "0086_onboarding"
branch_labels = None
depends_on = None


def _register_fk_targets() -> None:
    """ai_usage references users.id by string; SQLAlchemy
    resolves string FKs against the shared metadata at DDL
    compile time, so the owning module must be imported
    first."""
    from app.modules.core import models as _core_models  # noqa: F401


def upgrade() -> None:
    from app.modules.billing import models as billing_models

    _register_fk_targets()
    bind = op.get_bind()
    billing_models.AiUsage.__table__.create(bind, checkfirst=False)


def downgrade() -> None:
    from app.modules.billing import models as billing_models

    _register_fk_targets()
    bind = op.get_bind()
    billing_models.AiUsage.__table__.drop(bind, checkfirst=False)
