"""Migration 0085 (admin lane) upgrades a 0084-shaped database
cleanly: it creates site_stats_snapshots (the daily Site Stats
snapshot) and community_blocks (per-feature community blocks,
with the partial unique index that keeps one ACTIVE block per
member + feature), and the downgrade drops exactly those two
tables. Both tables are created straight off the owning
modules' models (the 0082 pattern), so the pre-state only
needs the users table the foreign key points at."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0085_admin_lane.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0085", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0085 shape: the users table (the FK target)
    and nothing else the migration touches."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0085_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0085_admin_lane"
    assert migration.down_revision == "0084_boards_urgency"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert "site_stats_snapshots" in tables
        assert "community_blocks" in tables
        snap_cols = {
            c["name"] for c in inspector.get_columns("site_stats_snapshots")
        }
        assert {"id", "day", "payload", "created_at", "updated_at"} <= snap_cols
        block_cols = {
            c["name"] for c in inspector.get_columns("community_blocks")
        }
        assert {
            "id",
            "user_id",
            "feature",
            "reason",
            "blocked_by_id",
            "lifted_by_id",
            "lifted_at",
            "created_at",
            "updated_at",
        } <= block_cols
        index_names = {
            ix["name"] for ix in inspector.get_indexes("community_blocks")
        }
        assert "uq_community_block_active" in index_names
        # day is unique on the snapshot table.
        uniques = inspector.get_unique_constraints("site_stats_snapshots")
        assert any(
            set(u["column_names"]) == {"day"} for u in uniques
        ) or any(
            ix["unique"] and set(ix["column_names"]) == {"day"}
            for ix in inspector.get_indexes("site_stats_snapshots")
        )

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert "site_stats_snapshots" not in tables
        assert "community_blocks" not in tables
        assert "users" in tables


def test_migration_0085_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0085 in a fresh interpreter that imports ONLY
    the migration file — its own imports (the owning modules,
    for the model __table__ DDL and the FK-target registration)
    must be enough."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0085.py"
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
                "mig_0085",
                backend / "alembic" / "versions" / "0085_admin_lane.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("users", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True))
            meta.create_all(engine)

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            with engine.begin() as conn:
                run(conn, migration.upgrade)
                inspector = sa.inspect(conn)
                tables = set(inspector.get_table_names())
                assert "site_stats_snapshots" in tables, tables
                assert "community_blocks" in tables, tables
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                inspector = sa.inspect(conn)
                tables = set(inspector.get_table_names())
                assert "site_stats_snapshots" not in tables
                assert "community_blocks" not in tables
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
