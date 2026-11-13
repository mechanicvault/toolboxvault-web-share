"""Migration 0089 (agent invite reminder) upgrades a
0088-shaped database cleanly: private_agents gains
invite_reminded_at (nullable, no default — every pre-existing
record lands NULL = never reminded, which is simply true), and
the downgrade removes exactly what the upgrade added. Plain
column add — no new tables, no data moves.
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
        / "0089_agent_invite_reminder.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0089", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0089 shape: private_agents reduced to its
    key columns (no invite_reminded_at)."""
    meta = sa.MetaData()
    sa.Table(
        "private_agents",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0089_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0089_agent_invite_reminder"
    assert migration.down_revision == "0088_subscription_status_changes"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        # A pre-existing record, written before the column exists.
        import uuid

        row_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO private_agents (id, owner_id, name, created_at)"
                " VALUES (:id, :owner, 'Austin', '2026-11-05 01:54:16+00:00')"
            ),
            {"id": row_id, "owner": str(uuid.uuid4())},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        cols = {c["name"]: c for c in inspector.get_columns("private_agents")}
        assert "invite_reminded_at" in cols
        assert cols["invite_reminded_at"]["nullable"] is True
        # The pre-existing row lands NULL — never reminded.
        got = conn.execute(
            sa.text(
                "SELECT invite_reminded_at FROM private_agents WHERE id = :id"
            ),
            {"id": row_id},
        ).scalar_one()
        assert got is None

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        col_names = {c["name"] for c in inspector.get_columns("private_agents")}
        assert "invite_reminded_at" not in col_names
        # The pre-state columns (and the row) survive the round-trip.
        assert {"id", "owner_id", "name", "created_at"} <= col_names
        kept = conn.execute(
            sa.text("SELECT name FROM private_agents WHERE id = :id"),
            {"id": row_id},
        ).scalar_one()
        assert kept == "Austin"


def test_migration_0089_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0089 in a fresh interpreter that imports ONLY
    the migration file — plain op.add_column DDL must compile
    with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0089.py"
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
                "mig_0089",
                backend / "alembic" / "versions" / "0089_agent_invite_reminder.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("private_agents", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("owner_id", PG_UUID(as_uuid=True), nullable=False),
                     sa.Column("name", sa.String(300), nullable=False))
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
                cols = {c["name"] for c in inspector.get_columns("private_agents")}
                assert "invite_reminded_at" in cols
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                inspector = sa.inspect(conn)
                cols = {c["name"] for c in inspector.get_columns("private_agents")}
                assert "invite_reminded_at" not in cols
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
