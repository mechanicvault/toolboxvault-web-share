"""Migration 0091 (release machinery) creates the
feature_announcements history table cleanly from a 0090-shaped
database, and the downgrade removes exactly what the upgrade
added. Plain table creation from explicit column definitions —
no data moves; the only pre-state the table needs is `users`
(its created_by_id FK target), reduced to its key column.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0091_feature_announcements.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0091", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0091 shape: users reduced to its key (the
    announcements table's only FK target)."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0091_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0091_feature_announcements"
    assert migration.down_revision == "0090_appearance_accent_light"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        assert "feature_announcements" not in sa.inspect(conn).get_table_names()
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert "feature_announcements" in inspector.get_table_names()
        cols = {c["name"]: c for c in inspector.get_columns("feature_announcements")}
        assert set(cols) == {
            "id",
            "title",
            "body",
            "link",
            "status",
            "recipient_count",
            "created_by_id",
            "created_by_name",
            "created_at",
            "sent_at",
        }
        assert cols["title"]["nullable"] is False
        assert cols["link"]["nullable"] is True
        assert cols["sent_at"]["nullable"] is True
        fks = inspector.get_foreign_keys("feature_announcements")
        assert len(fks) == 1
        assert fks[0]["referred_table"] == "users"

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        assert "feature_announcements" not in inspector.get_table_names()
        # The pre-state survives the round-trip.
        assert "users" in inspector.get_table_names()


def test_migration_0091_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0091 in a fresh interpreter that imports ONLY
    the migration file — plain op.create_table DDL must
    compile with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0091.py"
    script.write_text(
        textwrap.dedent(
            """
            import importlib.util
            import sys
            from pathlib import Path

            import sqlalchemy as sa
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            backend = Path(sys.argv[1])
            sys.path.insert(0, str(backend))
            spec = importlib.util.spec_from_file_location(
                "mig_0091",
                backend / "alembic" / "versions" / "0091_feature_announcements.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("users", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("email", sa.String(320), nullable=False))
            meta.create_all(engine)

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            with engine.begin() as conn:
                run(conn, migration.upgrade)
                names = sa.inspect(conn).get_table_names()
                assert "feature_announcements" in names
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                names = sa.inspect(conn).get_table_names()
                assert "feature_announcements" not in names
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
