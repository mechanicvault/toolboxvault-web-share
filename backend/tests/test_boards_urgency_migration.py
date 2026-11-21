"""Migration 0084 (boards urgency) upgrades a 0083-shaped
database cleanly: feedback_posts gains urgency (NOT NULL,
server default 'medium' — the picker's own default, landing
on every pre-existing post), and the downgrade removes
exactly what the upgrade added. Plain column add — no new
tables, no data moves.
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
        / "0084_boards_urgency.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0084", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0084 shape: feedback_posts reduced to its
    key columns (no urgency)."""
    meta = sa.MetaData()
    sa.Table(
        "feedback_posts",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("board", sa.String(10), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0084_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0084_boards_urgency"
    assert migration.down_revision == "0083_flyer_official_links"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        # A pre-existing post, written before the column exists.
        import uuid

        row_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO feedback_posts (id, board, title)"
                " VALUES (:id, 'bug', 'Old report')"
            ),
            {"id": row_id},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        cols = {c["name"]: c for c in inspector.get_columns("feedback_posts")}
        assert "urgency" in cols
        assert cols["urgency"]["nullable"] is False
        # The server default lands on the pre-existing row.
        got = conn.execute(
            sa.text("SELECT urgency FROM feedback_posts WHERE id = :id"),
            {"id": row_id},
        ).scalar_one()
        assert got == "medium"

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        col_names = {c["name"] for c in inspector.get_columns("feedback_posts")}
        assert "urgency" not in col_names
        # The pre-state columns (and the row) survive the round-trip.
        assert {"id", "board", "title"} <= col_names
        kept = conn.execute(
            sa.text("SELECT title FROM feedback_posts WHERE id = :id"),
            {"id": row_id},
        ).scalar_one()
        assert kept == "Old report"


def test_migration_0084_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0084 in a fresh interpreter that imports ONLY
    the migration file — plain op.add_column DDL must compile
    with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0084.py"
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
                "mig_0084",
                backend / "alembic" / "versions" / "0084_boards_urgency.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("feedback_posts", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("board", sa.String(10), nullable=False),
                     sa.Column("title", sa.String(300), nullable=False))
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
                cols = {c["name"] for c in inspector.get_columns("feedback_posts")}
                assert "urgency" in cols
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                inspector = sa.inspect(conn)
                cols = {c["name"] for c in inspector.get_columns("feedback_posts")}
                assert "urgency" not in cols
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
