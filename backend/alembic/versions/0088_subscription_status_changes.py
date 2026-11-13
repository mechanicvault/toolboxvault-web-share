"""0088: the cancellation counts lane (owner 2026-11-07) —
one new table, created with SQLAlchemy DDL straight off the
owning module's model, the 0082/0085/0086/0087 pattern:

- subscription_status_changes (billing) — one row per RECORDED
  subscription status transition: the subscription, the status
  it left, the status it entered, when, and the change's
  source. The Subscription row stores only its current status,
  so before this lane no cancellation date existed anywhere
  and the admin Accounting report printed that gap instead of
  a count. Writers append transitions only (a same-status
  re-save records nothing); the report counts a cancellation
  as a live state (active | trialing | past_due) reaching a
  terminal state (canceled | ended), once. History starts
  with this migration — no earlier change was ever recorded,
  and no row pretends otherwise.

subscription_status_changes references users (core) and
subscriptions (billing) by string FK, so core's models are
imported before the DDL compiles — the 0081 lesson (the test
suite imports everything and masks a missing import; the
alembic boot process does not).
"""

from alembic import op

revision = "0088_subscription_status_changes"
down_revision = "0087_ai_usage"
branch_labels = None
depends_on = None


def _register_fk_targets() -> None:
    """subscription_status_changes references users.id and
    subscriptions.id by string; SQLAlchemy resolves string FKs
    against the shared metadata at DDL compile time, so the
    owning modules must be imported first."""
    from app.modules.core import models as _core_models  # noqa: F401


def upgrade() -> None:
    from app.modules.billing import models as billing_models

    _register_fk_targets()
    bind = op.get_bind()
    billing_models.SubscriptionStatusChange.__table__.create(
        bind, checkfirst=False
    )


def downgrade() -> None:
    from app.modules.billing import models as billing_models

    _register_fk_targets()
    bind = op.get_bind()
    billing_models.SubscriptionStatusChange.__table__.drop(
        bind, checkfirst=False
    )
