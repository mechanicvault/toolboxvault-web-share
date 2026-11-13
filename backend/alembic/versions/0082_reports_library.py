"""0082: the reports library (Reports page redesign, owner
2026-11-06).

Three tables, created with SQLAlchemy DDL straight off the
reports module's models:

- report_templates — the redesigned page's saved reports: a
  catalog report type + its settings + the area it lists in
  (quick | accounting).
- generated_reports — the History: one row per generated file,
  the bytes in object storage under the owner's namespace.
- report_template_seeds — the seed-once marker for the seven
  default templates (a deleted default never resurrects).

No data is seeded here and no existing table is touched: the
defaults are seeded lazily by the service at each user's first
templates read (that's what makes seed-once semantics work for
accounts that already exist). The only foreign keys point at
users (core) and at report_templates (this same module), so the
FK registration below needs core's models imported before the
DDL compiles — the 0081 lesson.
"""

from alembic import op

revision = "0082_reports_library"
down_revision = "0081_flyer_module"
branch_labels = None
depends_on = None


def _register_fk_targets() -> None:
    """generated_reports and report_templates reference
    users.id by string; SQLAlchemy resolves string FKs against
    the shared metadata at DDL compile time, so the owning
    module must be imported first — the test suite imports
    everything and masks this; the alembic boot process does
    not (0081's crash-loop lesson)."""
    from app.modules.core import models as _core_models  # noqa: F401


def upgrade() -> None:
    from app.modules.reports import models as report_models

    _register_fk_targets()
    bind = op.get_bind()
    report_models.ReportTemplate.__table__.create(bind, checkfirst=False)
    report_models.GeneratedReport.__table__.create(bind, checkfirst=False)
    report_models.ReportTemplateSeed.__table__.create(bind, checkfirst=False)


def downgrade() -> None:
    from app.modules.reports import models as report_models

    _register_fk_targets()
    bind = op.get_bind()
    report_models.ReportTemplateSeed.__table__.drop(bind, checkfirst=False)
    report_models.GeneratedReport.__table__.drop(bind, checkfirst=False)
    report_models.ReportTemplate.__table__.drop(bind, checkfirst=False)
