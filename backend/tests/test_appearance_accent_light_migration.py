"""Migration 0090 (per-mode accent) upgrades a 0089-shaped
database cleanly: users gains appearance_accent_light
(nullable, no default — every pre-existing account lands NULL
= no light-mode pick yet, which is simply true), and the
downgrade removes exactly what the upgrade added. Plain
column add on an existing table — no new tables, no data
moves; the pre-existing appearance_accent (the dark-mode
pick) is untouched by the round-trip.
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
        / "0090_appearance_accent_light.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0090", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0090 shape: users reduced to its key +
    appearance columns (no appearance_accent_light)."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("appearance_mode", sa.String(8), nullable=True),
        sa.Column("appearance_accent", sa.String(16), nullable=True),
        sa.Column("appearance_theme", sa.String(32), nullable=True),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0090_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0090_appearance_accent_light"
    assert migration.down_revision == "0089_agent_invite_reminder"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        # A pre-existing account, saved dark + orange before
        # the column exists (the production shape).
        import uuid

        row_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO users"
                " (id, email, appearance_mode, appearance_accent,"
                " appearance_theme)"
                " VALUES (:id, 'ryan@example.com', 'dark', '#f2760a',"
                " 'railsteel')"
            ),
            {"id": row_id},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        cols = {c["name"]: c for c in inspector.get_columns("users")}
        assert "appearance_accent_light" in cols
        assert cols["appearance_accent_light"]["nullable"] is True
        # The pre-existing row lands NULL — no light pick yet —
        # and its dark pick is untouched.
        got = conn.execute(
            sa.text(
                "SELECT appearance_accent_light, appearance_accent"
                " FROM users WHERE id = :id"
            ),
            {"id": row_id},
        ).one()
        assert got[0] is None
        assert got[1] == "#f2760a"

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        col_names = {c["name"] for c in inspector.get_columns("users")}
        assert "appearance_accent_light" not in col_names
        # The pre-state columns (and the row) survive the round-trip.
        assert {
            "id",
            "email",
            "appearance_mode",
            "appearance_accent",
            "appearance_theme",
        } <= col_names
        kept = conn.execute(
            sa.text("SELECT appearance_accent FROM users WHERE id = :id"),
            {"id": row_id},
        ).scalar_one()
        assert kept == "#f2760a"


def test_migration_0090_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0090 in a fresh interpreter that imports ONLY
    the migration file — plain op.add_column DDL must compile
    with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0090.py"
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
                "mig_0090",
                backend / "alembic" / "versions" / "0090_appearance_accent_light.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("users", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("email", sa.String(320), nullable=False),
                     sa.Column("appearance_accent", sa.String(16), nullable=True))
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
                cols = {c["name"] for c in inspector.get_columns("users")}
                assert "appearance_accent_light" in cols
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                inspector = sa.inspect(conn)
                cols = {c["name"] for c in inspector.get_columns("users")}
                assert "appearance_accent_light" not in cols
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
