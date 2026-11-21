"""Migration 0092 (downloads-documents lane) creates the
download_files catalog table and seeds the nine-file shelf,
and the downgrade removes exactly what the upgrade added.
Plain table creation + seed from explicit definitions — the
table needs no pre-state (it references nothing).
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0092_download_files.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0092", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0092_upgrade_seeds_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0092_download_files"
    assert migration.down_revision == "0091_feature_announcements"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        assert "download_files" not in sa.inspect(conn).get_table_names()
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert "download_files" in inspector.get_table_names()
        cols = {c["name"]: c for c in inspector.get_columns("download_files")}
        assert set(cols) == {
            "id",
            "key",
            "file_format",
            "filename",
            "storage_key",
            "sort_order",
            "is_active",
            "download_count",
            "created_at",
            "updated_at",
        }
        rows = conn.execute(
            sa.text("SELECT key, download_count FROM download_files ORDER BY sort_order")
        ).all()
        assert [r[0] for r in rows] == [
            "tool-inventory",
            "paycheck-calculator",
            "flat-rate-tracker",
            "inspection-checklist",
            "pre-purchase-form",
            "diagnostic-worksheet",
            "electrical-worksheet",
            "intake-form",
            "torque-chart",
        ]
        assert all(r[1] == 0 for r in rows)

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        assert "download_files" not in inspector.get_table_names()


def test_migration_0092_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0092 in a fresh interpreter that imports ONLY
    the migration file — plain op.create_table DDL plus the
    seed inserts must compile with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0092.py"
    script.write_text(
        textwrap.dedent(
            """
            import importlib.util
            import sys
            from pathlib import Path

            import sqlalchemy as sa

            backend = Path(sys.argv[1])
            sys.path.insert(0, str(backend))
            spec = importlib.util.spec_from_file_location(
                "mig_0092",
                backend / "alembic" / "versions" / "0092_download_files.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            with engine.begin() as conn:
                run(conn, migration.upgrade)
                names = sa.inspect(conn).get_table_names()
                assert "download_files" in names
                count = conn.execute(
                    sa.text("SELECT count(*) FROM download_files")
                ).scalar()
                assert count == 9, count
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                names = sa.inspect(conn).get_table_names()
                assert "download_files" not in names
            print("bare ok")
            """
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), str(backend)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "bare ok" in result.stdout
