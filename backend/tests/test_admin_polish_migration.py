"""Admin polish migration 0087 (AI usage metering table):
bare-subprocess proof (the 0081 gate).

The migration must run in a process that imports ONLY the
migration file — no app conftest, whose full model imports
mask a missing FK-target registration — and the table it
creates must be exactly the model's table.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0087_ai_usage.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0087_ai_usage", MIGRATION
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_metadata():
    module = _load_migration()
    assert module.revision == "0087_ai_usage"
    assert module.down_revision == "0086_onboarding"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_migration_upgrade_downgrade_sqlite(tmp_path):
    module = _load_migration()
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'migration.db'}"
    )
    with engine.begin() as conn:
        # The FK target, built by hand in the same minimal
        # spirit as the onboarding migration's proof: the
        # ai_usage table references users.id.
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                "id CHAR(36) PRIMARY KEY, "
                "email VARCHAR(320), "
                "name VARCHAR(200))"
            )
        )
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
        inspector = sa.inspect(conn)
        assert "ai_usage" in inspector.get_table_names()
        columns = {
            col["name"] for col in inspector.get_columns("ai_usage")
        }
        assert columns == {
            "id", "user_id", "action", "subject", "provider",
            "model", "calls", "tokens_in", "tokens_out",
            "credits_charged", "created_at",
        }
        fks = inspector.get_foreign_keys("ai_usage")
        assert any(
            fk["referred_table"] == "users" for fk in fks
        )
        with Operations.context(ctx):
            module.downgrade()
        inspector = sa.inspect(conn)
        assert "ai_usage" not in inspector.get_table_names()
    engine.dispose()


def test_migration_loads_in_a_bare_subprocess():
    """The 0081 regression gate verbatim: a subprocess whose
    only import is the migration file itself must be able to
    load it (its model imports register the FK target)."""
    code = (
        "import importlib.util, sys;"
        "spec = importlib.util.spec_from_file_location("
        f"'m', r'{MIGRATION}');"
        "module = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(module);"
        "print(module.revision)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0087_ai_usage"
