"""Migration 0086 (onboarding) upgrades a 0085-shaped database
cleanly: the onboarding_progress table appears with its columns
and the (user_id, step_key) uniqueness; the downgrade removes
exactly what the upgrade added. The migration builds the table
from the core model's DDL (the 0082/0085 pattern), so the
pre-state is an EMPTY database — there is no earlier shape of
this table to preserve.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0086_onboarding.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0086", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0086_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0086_onboarding"
    assert migration.down_revision == "0085_admin_lane"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert "onboarding_progress" in inspector.get_table_names()
        columns = {
            c["name"] for c in inspector.get_columns("onboarding_progress")
        }
        assert columns == {
            "id",
            "user_id",
            "step_key",
            "status",
            "detail",
            "created_at",
            "updated_at",
        }
        uniques = inspector.get_unique_constraints("onboarding_progress")
        assert any(
            set(u["column_names"]) == {"user_id", "step_key"} for u in uniques
        )
        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        assert "onboarding_progress" not in inspector.get_table_names()
