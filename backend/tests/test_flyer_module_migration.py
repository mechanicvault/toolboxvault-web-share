"""Migration 0081 (flyer module) upgrades a 0080-shaped
database cleanly: the three flyer tables appear with their
columns, checks and partial unique indexes, the module-control
seed lands (flyers on, three default groups, every tier), and
the downgrade removes exactly what the upgrade added.
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
        / "0081_flyer_module.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0081", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0081 shape: the FK targets the flyer tables
    reference + the module-control tables with the LIVE
    production columns (module_state / module_access /
    module_tier_access as \\d shows them)."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(300), nullable=False),
    )
    sa.Table(
        "dealer_companies",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
    )
    sa.Table(
        "private_agents",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    # The module-control mirrors carry the LIVE shape,
    # including updated_at NOT NULL with a now() default — a
    # seed insert that wrote an explicit NULL there would die
    # on production, and this pre-state must be able to catch
    # exactly that (it could not, in the lane's first draft).
    sa.Table(
        "module_state",
        meta,
        sa.Column("module_id", sa.String(64), primary_key=True),
        sa.Column("globally_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    sa.Table(
        "module_access",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("account_group", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    sa.Table(
        "module_tier_access",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0081_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0081_flyer_module"
    assert migration.down_revision == "0080_truck_highest_balance"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, 'a@x.io')"),
            {"id": str(user_id)},
        )
        conn.execute(
            sa.text("INSERT INTO dealer_companies (id, name) VALUES (:id, 'Acme')"),
            {"id": str(company_id)},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        assert {"flyer_sources", "flyers", "flyer_alert_prefs"} <= set(tables)

        source_cols = {c["name"] for c in inspector.get_columns("flyer_sources")}
        assert {
            "id", "kind", "company_id", "agent_user_id", "private_agent_id",
            "visible", "history_visible", "standing_url", "standing_hash",
            "standing_checked_at", "created_by_id", "created_at", "updated_at",
        } <= source_cols
        flyer_cols = {c["name"] for c in inspector.get_columns("flyers")}
        assert {
            "id", "source_id", "label", "pdf_key", "thumb_key", "page_count",
            "content_hash", "origin", "origin_url", "starts_on", "ends_on",
            "posted_by_id", "created_at", "updated_at",
        } <= flyer_cols
        pref_cols = {c["name"] for c in inspector.get_columns("flyer_alert_prefs")}
        assert {"user_id", "enabled", "updated_at"} <= pref_cols

        # A company source stores; a second one for the same
        # company is refused by the partial unique index.
        conn.execute(
            sa.text(
                "INSERT INTO flyer_sources (id, kind, company_id, created_by_id)"
                " VALUES (:id, 'company', :c, :u)"
            ),
            {"id": str(uuid.uuid4()), "c": str(company_id), "u": str(user_id)},
        )
        try:
            with conn.begin_nested():
                conn.execute(
                    sa.text(
                        "INSERT INTO flyer_sources"
                        " (id, kind, company_id, created_by_id)"
                        " VALUES (:id, 'company', :c, :u)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "c": str(company_id),
                        "u": str(user_id),
                    },
                )
            raise AssertionError("duplicate company source was accepted")
        except sa.exc.IntegrityError:
            pass

        # The module-control seed.
        state = conn.execute(
            sa.text(
                "SELECT globally_enabled FROM module_state"
                " WHERE module_id = 'flyers'"
            )
        ).scalar_one()
        assert state in (1, True)
        groups = conn.execute(
            sa.text(
                "SELECT account_group FROM module_access"
                " WHERE module_id = 'flyers' ORDER BY account_group"
            )
        ).scalars().all()
        assert groups == [
            "mechanic_technician",
            "shop_company",
            "tool_dealer",
        ]
        tiers = conn.execute(
            sa.text(
                "SELECT tier FROM module_tier_access"
                " WHERE module_id = 'flyers' ORDER BY tier"
            )
        ).scalars().all()
        assert tiers == ["beta", "moderator", "moderator_admin", "normal"]

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        assert "flyer_sources" not in tables
        assert "flyers" not in tables
        assert "flyer_alert_prefs" not in tables
        assert conn.execute(
            sa.text("SELECT COUNT(*) FROM module_state WHERE module_id = 'flyers'")
        ).scalar_one() == 0
        assert conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM module_access WHERE module_id = 'flyers'"
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM module_tier_access"
                " WHERE module_id = 'flyers'"
            )
        ).scalar_one() == 0
        # Pre-state tables untouched by the round-trip.
        assert {"users", "dealer_companies", "private_agents"} <= set(tables)


def test_migration_0081_runs_in_a_bare_process(tmp_path):
    """Regression (deploy crash-loop, 2026-11-06): the suite's
    conftest imports every model, which masks FK-resolution
    failures that only appear when alembic runs the migration
    in a process that has imported nothing else. The first
    shipped 0081 created its tables from the models' __table__
    objects without importing the modules that own the FK
    targets (users / dealer_companies / private_agents), and
    production died with NoReferencedTableError while every
    test stayed green. This test runs the migration in a fresh
    interpreter that imports ONLY the migration file."""
    import subprocess
    import sys
    import textwrap

    backend = Path(__file__).resolve().parents[1]
    script = tmp_path / "bare_0081.py"
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
                "mig_0081", backend / "alembic" / "versions" / "0081_flyer_module.py"
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            engine = sa.create_engine("sqlite://")
            meta = sa.MetaData()
            sa.Table("module_state", meta,
                     sa.Column("module_id", sa.String(64), primary_key=True),
                     sa.Column("globally_enabled", sa.Boolean(), nullable=False),
                     sa.Column("updated_at", sa.DateTime(timezone=True),
                               nullable=False, server_default=sa.func.now()))
            sa.Table("module_access", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("module_id", sa.String(64), nullable=False),
                     sa.Column("account_group", sa.String(64), nullable=False),
                     sa.Column("enabled", sa.Boolean(), nullable=False),
                     sa.Column("updated_at", sa.DateTime(timezone=True),
                               nullable=False, server_default=sa.func.now()))
            sa.Table("module_tier_access", meta,
                     sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
                     sa.Column("module_id", sa.String(64), nullable=False),
                     sa.Column("tier", sa.String(32), nullable=False),
                     sa.Column("enabled", sa.Boolean(), nullable=False),
                     sa.Column("updated_at", sa.DateTime(timezone=True),
                               nullable=False, server_default=sa.func.now()))
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
                assert {"flyer_sources", "flyers", "flyer_alert_prefs"} <= tables
            with engine.begin() as conn:
                run(conn, migration.downgrade)
                tables = set(sa.inspect(conn).get_table_names())
                assert not ({"flyer_sources", "flyers", "flyer_alert_prefs"} & tables)
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
