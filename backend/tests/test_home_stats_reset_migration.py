"""Migration 0100 (Home stats-only reset) against a pre-0100
shaped database:

- every user's home layout becomes exactly the stats widget
  entry, [{"key": "overview", "visible": true}];
- the panel pseudo-entry (key "panel") is preserved verbatim;
- the GOD tier's rows are never touched;
- other pages' layout rows are never touched;
- the transform is idempotent, and the downgrade is a no-op
  (a reset cannot un-happen).

The pre-state tables are the migration's own minimal shape
(users id/tier; user_page_layouts id/user_id/page_key/blocks) —
the same columns core/models.py declares for the real tables.
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
        / "0100_home_stats_reset.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0100", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("tier", sa.String(32), nullable=False),
    )
    sa.Table(
        "user_page_layouts",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("page_key", sa.String(64), nullable=False),
        sa.Column("blocks", sa.JSON, nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


GOD = str(uuid.uuid4())
NORM = str(uuid.uuid4())
RUNG = str(uuid.uuid4())

PANEL = {
    "key": "panel",
    "visible": True,
    "panel_hidden": ["stats"],
    "panel_stat_order": ["inventory.total_items"],
}
GOD_BLOCKS = [
    {"key": "overview", "visible": True, "hidden_stats": ["claims.open_claims"]},
    {"key": "widget:inventory", "visible": True, "size": "half"},
    dict(PANEL),
]
NORM_BLOCKS = [
    {"key": "widget:inventory", "visible": True, "size": "half"},
    {"key": "overview", "visible": True, "hidden_stats": ["parts.used_parts"]},
    {"key": "notifications", "visible": False},
    dict(PANEL),
]
RUNG_BLOCKS = [
    {"key": "widget:downloads", "visible": True},
    {"key": "widget:prints", "visible": True},
    {"key": "widget:converter", "visible": True},
]
INV_BLOCKS = [{"key": "search", "visible": True}]


def _seed(conn):
    users = sa.table(
        "users", sa.column("id"), sa.column("tier")
    )
    layouts = sa.table(
        "user_page_layouts",
        sa.column("id", PG_UUID(as_uuid=True)),
        sa.column("user_id", PG_UUID(as_uuid=True)),
        sa.column("page_key", sa.String(64)),
        sa.column("blocks", sa.JSON),
    )
    conn.execute(
        users.insert(),
        [
            {"id": GOD, "tier": "god"},
            {"id": NORM, "tier": "normal"},
            {"id": RUNG, "tier": "downloads"},
        ],
    )
    conn.execute(
        layouts.insert(),
        [
            {"id": uuid.uuid4(), "user_id": uuid.UUID(GOD), "page_key": "home", "blocks": GOD_BLOCKS},
            {"id": uuid.uuid4(), "user_id": uuid.UUID(NORM), "page_key": "home", "blocks": NORM_BLOCKS},
            {"id": uuid.uuid4(), "user_id": uuid.UUID(RUNG), "page_key": "home", "blocks": RUNG_BLOCKS},
            {"id": uuid.uuid4(), "user_id": uuid.UUID(NORM), "page_key": "inventory", "blocks": INV_BLOCKS},
        ],
    )


def _blocks(conn, user_id, page_key="home"):
    import json

    raw = conn.execute(
        sa.text(
            "SELECT blocks FROM user_page_layouts "
            "WHERE user_id = :u AND page_key = :p"
        ),
        # PG_UUID stores undashed hex on SQLite.
        {"u": user_id.replace("-", ""), "p": page_key},
    ).scalar_one()
    # sa.text reads the JSON column as raw text on SQLite.
    return json.loads(raw) if isinstance(raw, str) else raw


def test_migration_0100_resets_home_to_stats_only():
    migration = _load_migration()
    assert migration.revision == "0100_home_stats_reset"
    assert migration.down_revision == "0099_prints_visitor_counter"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    with engine.begin() as conn:
        _seed(conn)
        _run(conn, migration.upgrade)

        # The normal user's boxes are gone — stats alone, with
        # the panel pseudo-entry preserved verbatim behind it.
        assert _blocks(conn, NORM) == [
            {"key": "overview", "visible": True},
            PANEL,
        ]
        # The downloads rung resets to the same stored shape —
        # its assembly seats the rung stats flavor under the
        # same key.
        assert _blocks(conn, RUNG) == [{"key": "overview", "visible": True}]
        # God is never touched, byte for byte.
        assert _blocks(conn, GOD) == GOD_BLOCKS
        # Other pages are never touched.
        assert _blocks(conn, NORM, "inventory") == INV_BLOCKS

        # Idempotent: a second run changes nothing further.
        _run(conn, migration.upgrade)
        assert _blocks(conn, NORM) == [
            {"key": "overview", "visible": True},
            PANEL,
        ]
        assert _blocks(conn, GOD) == GOD_BLOCKS

        # The downgrade is a documented no-op.
        _run(conn, migration.downgrade)
        assert _blocks(conn, NORM) == [
            {"key": "overview", "visible": True},
            PANEL,
        ]


def test_migration_0100_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06, migration
    0081): the suite's conftest imports every model, which
    masks failures that only appear when alembic runs the
    migration in a process that has imported nothing else.
    This runs 0100 in a fresh interpreter that imports ONLY
    the migration file."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0100.py"
    script.write_text(
        textwrap.dedent(
            """
            import importlib.util
            import json
            import sys
            import uuid
            from pathlib import Path

            import sqlalchemy as sa
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            backend = Path(sys.argv[1])
            spec = importlib.util.spec_from_file_location(
                "mig_0100",
                backend / "alembic" / "versions" / "0100_home_stats_reset.py",
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("users", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("tier", sa.String(32), nullable=False))
            sa.Table("user_page_layouts", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
                     sa.Column("page_key", sa.String(64), nullable=False),
                     sa.Column("blocks", sa.JSON, nullable=False))
            meta.create_all(engine)

            def run(conn, fn):
                from alembic.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    fn()

            uid = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO users (id, tier) VALUES (:id, 'normal')"
                ), {"id": uid})
                conn.execute(sa.text(
                    "INSERT INTO user_page_layouts (id, user_id, page_key, blocks)"
                    " VALUES (:id, :u, 'home', :b)"
                ), {"id": str(uuid.uuid4()), "u": uid,
                    "b": json.dumps([{"key": "widget:inventory", "visible": True}])})
                run(conn, migration.upgrade)
                got = conn.execute(sa.text(
                    "SELECT blocks FROM user_page_layouts"
                )).scalar_one()
                assert json.loads(got) == [{"key": "overview", "visible": True}], got
                run(conn, migration.downgrade)
            print("bare-ok")
            """
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), str(backend)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "bare-ok" in result.stdout
