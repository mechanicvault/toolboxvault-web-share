"""Migration 0083 (flyer official links) upgrades a 0082-shaped
database cleanly: dealer_companies gains official_flyer_url
(NOT NULL, default ''), flyer_sources gains the system pull's
dedupe pair (auto_hash, auto_checked_at), and the downgrade
removes exactly what the upgrade added. Plain column adds —
no new tables, no data moves.
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
        / "0083_flyer_official_links.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0083", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0083 shape: the two tables the migration
    adds columns to, each reduced to its key column."""
    meta = sa.MetaData()
    sa.Table(
        "dealer_companies",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
    )
    sa.Table(
        "flyer_sources",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0083_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0083_flyer_official_links"
    assert migration.down_revision == "0082_reports_library"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        company_cols = {
            c["name"]: c for c in inspector.get_columns("dealer_companies")
        }
        assert "official_flyer_url" in company_cols
        assert company_cols["official_flyer_url"]["nullable"] is False
        source_cols = {c["name"] for c in inspector.get_columns("flyer_sources")}
        assert {"auto_hash", "auto_checked_at"} <= source_cols

        # The server default lands on pre-existing rows.
        import uuid

        row_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO dealer_companies (id, name) VALUES (:id, 'Acme')"
            ),
            {"id": row_id},
        )
        got = conn.execute(
            sa.text(
                "SELECT official_flyer_url FROM dealer_companies"
                " WHERE id = :id"
            ),
            {"id": row_id},
        ).scalar_one()
        assert got == ""

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        company_cols = {
            c["name"] for c in inspector.get_columns("dealer_companies")
        }
        assert "official_flyer_url" not in company_cols
        source_cols = {c["name"] for c in inspector.get_columns("flyer_sources")}
        assert "auto_hash" not in source_cols
        assert "auto_checked_at" not in source_cols
        # The pre-state columns survive the round-trip.
        assert {"id", "name"} <= set(company_cols)


def test_migration_0083_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0083 in a fresh interpreter that imports ONLY
    the migration file — plain op.add_column DDL must compile
    with no model imports at all."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0083.py"
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
                "mig_0083",
                backend / "alembic" / "versions" / "0083_flyer_official_links.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("dealer_companies", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("name", sa.String(300), nullable=False))
            sa.Table("flyer_sources", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("kind", sa.String(20), nullable=False))
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
                cols = {c["name"] for c in inspector.get_columns("dealer_companies")}
                assert "official_flyer_url" in cols
                cols = {c["name"] for c in inspector.get_columns("flyer_sources")}
                assert {"auto_hash", "auto_checked_at"} <= cols
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                inspector = sa.inspect(conn)
                cols = {c["name"] for c in inspector.get_columns("dealer_companies")}
                assert "official_flyer_url" not in cols
                cols = {c["name"] for c in inspector.get_columns("flyer_sources")}
                assert not ({"auto_hash", "auto_checked_at"} & cols)
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
