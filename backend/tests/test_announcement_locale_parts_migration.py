"""Migration 0102 (member email single-language lane,
2026-11-10) adds the per-language email parts to
feature_announcements — title_es / body_en / body_es, all
nullable — onto the table's 0101 shape (0091's columns +
0096's release columns), and the downgrade removes exactly
those three columns. Explicit add-column DDL only; no data
moves; a pre-existing announcement row must survive the
round-trip untouched.
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
        / "0102_announcement_locale_parts.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0102", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """The 0101-shaped feature_announcements: 0091's table plus
    0096's two release columns, with `users` reduced to its key
    (the created_by_id FK target)."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
    )
    announcements = sa.Table(
        "feature_announcements",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column("link", sa.String(300)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("recipient_count", sa.Integer),
        sa.Column(
            "created_by_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
        ),
        sa.Column("created_by_name", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("release_module_id", sa.String(64)),
        sa.Column("audience_user_ids", sa.JSON),
    )
    meta.create_all(engine)
    return announcements


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0102_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0102_announcement_locale_parts"
    assert migration.down_revision == "0101_conversion_requests"
    engine = sa.create_engine("sqlite://")
    table = _pre_state(engine)
    import uuid

    row_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            table.insert().values(
                id=row_id,
                title="Existing",
                body="Already queued before 0102.",
                status="queued",
                created_by_name="Toolbox Vault",
            )
        )
        cols = {
            c["name"]: c
            for c in sa.inspect(conn).get_columns("feature_announcements")
        }
        assert "title_es" not in cols
        _run(conn, migration.upgrade)
        cols = {
            c["name"]: c
            for c in sa.inspect(conn).get_columns("feature_announcements")
        }
        for name in ("title_es", "body_en", "body_es"):
            assert name in cols, name
            assert cols[name]["nullable"] is True, name
        assert str(cols["title_es"]["type"]) == "VARCHAR(200)"
        assert str(cols["body_en"]["type"]) == "VARCHAR(1000)"
        assert str(cols["body_es"]["type"]) == "VARCHAR(1000)"
        # The pre-existing row survives, parts NULL.
        stored = conn.execute(
            sa.select(table.c.title, table.c.body).where(table.c.id == row_id)
        ).one()
        assert stored == ("Existing", "Already queued before 0102.")

        _run(conn, migration.downgrade)
        cols = {
            c["name"]
            for c in sa.inspect(conn).get_columns("feature_announcements")
        }
        assert "title_es" not in cols
        assert "body_en" not in cols
        assert "body_es" not in cols
        assert "release_module_id" in cols  # 0096's columns stay
        stored = conn.execute(
            sa.select(table.c.title).where(table.c.id == row_id)
        ).one()
        assert stored[0] == "Existing"


def test_migration_0102_runs_in_a_bare_process(tmp_path):
    """Regression posture (deploy crash-loop, 2026-11-06,
    migration 0081): the suite's conftest imports every model,
    which masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else. This
    runs 0102 in a fresh interpreter that imports ONLY the
    migration file."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0102.py"
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
                "mig_0102",
                backend / "alembic" / "versions"
                / "0102_announcement_locale_parts.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table(
                "feature_announcements",
                meta,
                sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                sa.Column("title", sa.String(200), nullable=False),
                sa.Column("body", sa.String(1000), nullable=False),
            )
            meta.create_all(engine)

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            with engine.begin() as conn:
                run(conn, migration.upgrade)
                cols = {
                    c["name"]
                    for c in sa.inspect(conn).get_columns(
                        "feature_announcements"
                    )
                }
                assert {"title_es", "body_en", "body_es"} <= cols
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                cols = {
                    c["name"]
                    for c in sa.inspect(conn).get_columns(
                        "feature_announcements"
                    )
                }
                assert not ({"title_es", "body_en", "body_es"} & cols)
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
