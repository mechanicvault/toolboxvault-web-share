"""Migration 0082 (reports library) upgrades a 0081-shaped
database cleanly: the three reports-library tables appear with
their columns, and the downgrade removes exactly what the
upgrade added. The migration touches no existing table and
seeds no data — the defaults live behind the service's
seed-once marker, not in the migration.
"""

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0082_reports_library.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0082", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0082 shape: the one FK target the new tables
    reference outside their own module (users)."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(300), nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0082_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0082_reports_library"
    assert migration.down_revision == "0081_flyer_module"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, 'a@x.io')"),
            {"id": str(user_id)},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        assert {
            "report_templates",
            "generated_reports",
            "report_template_seeds",
        } <= set(tables)

        template_cols = {
            c["name"] for c in inspector.get_columns("report_templates")
        }
        assert {
            "id", "owner_id", "report_type", "name", "description",
            "area", "settings", "is_default", "created_at", "updated_at",
        } <= template_cols
        history_cols = {
            c["name"] for c in inspector.get_columns("generated_reports")
        }
        assert {
            "id", "owner_id", "template_id", "name", "report_type",
            "format", "storage_key", "content_type", "size_bytes",
            "settings", "created_at",
        } <= history_cols
        seed_cols = {
            c["name"] for c in inspector.get_columns("report_template_seeds")
        }
        assert {"user_id", "seeded_at"} <= seed_cols

        # A template + a history row referencing it store fine.
        template_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO report_templates"
                " (id, owner_id, report_type, name, description, area,"
                "  settings, is_default)"
                " VALUES (:id, :u, 'inventory', 'Full inventory report',"
                "         '', 'quick', '{}', 1)"
            ),
            {"id": template_id, "u": str(user_id)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO generated_reports"
                " (id, owner_id, template_id, name, report_type, format,"
                "  storage_key, content_type, size_bytes, settings)"
                " VALUES (:id, :u, :t, 'Full inventory report',"
                "         'inventory', 'pdf', 'k', 'application/pdf', 10, '{}')"
            ),
            {"id": str(uuid.uuid4()), "u": str(user_id), "t": template_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO report_template_seeds (user_id) VALUES (:u)"
            ),
            {"u": str(user_id)},
        )

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        assert "report_templates" not in tables
        assert "generated_reports" not in tables
        assert "report_template_seeds" not in tables
        # The pre-state table is untouched by the round-trip.
        assert "users" in tables


def test_migration_0082_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks FK-resolution failures that only appear when alembic
    runs the migration in a process that has imported nothing
    else. This runs 0082 in a fresh interpreter that imports
    ONLY the migration file — its users FK must resolve through
    the migration's own imports."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0082.py"
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
                "mig_0082", backend / "alembic" / "versions" / "0082_reports_library.py"
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("users", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("email", sa.String(300), nullable=False))
            meta.create_all(engine)

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            with engine.begin() as conn:
                run(conn, migration.upgrade)
                tables = set(sa.inspect(conn).get_table_names())
                assert {"report_templates", "generated_reports",
                        "report_template_seeds"} <= tables
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                tables = set(sa.inspect(conn).get_table_names())
                assert not ({"report_templates", "generated_reports",
                             "report_template_seeds"} & tables)
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
