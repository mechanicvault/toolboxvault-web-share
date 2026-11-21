"""Migration 0093 (3D print files) — bare-subprocess
regression (standing rule, owner 2026-11-06, after the third
migration incident): pytest's conftest imports every model, so
a migration that relies on shared-metadata imports (or any
app package import at all) stays green in the suite while the
real alembic boot crashes on it. This proof loads ONLY the
migration file — no `app.*` imports — upgrades and downgrades
it against a minimal parent schema (users + the three
module-control tables, shaped by the migrations that own
them), and checks the print tables, the module-control seed
and its exact removal on the way down.
"""

import importlib.util
import os
import subprocess
import sys
import textwrap

CHILD = textwrap.dedent(
    """
    import importlib.util
    import os
    import sys

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "mig0093", os.environ["MIG0093_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0093_URL"])
    ctx = MigrationContext.configure(engine.connect())
    ops = Operations(ctx)
    mig.op = ops
    # One connection throughout (the 0092 proof's shape): the
    # parent schema, the migration's own writes and the checks
    # all read the same committed state.
    conn = ctx.connection
    # The parent schema the real chain has at 0092: users
    # (0001) + the module control tables (0025's create,
    # 0068's trim: NO updated_at on module_access /
    # module_tier_access; module_state's updated_at is
    # nullable — the live shape verified against production
    # before shipping).
    conn.execute(sa.text(
        "CREATE TABLE users (id UUID PRIMARY KEY)"
    ))
    conn.execute(sa.text(
        "CREATE TABLE module_state ("
        " module_id VARCHAR(64) PRIMARY KEY,"
        " globally_enabled BOOLEAN NOT NULL,"
        " updated_at TIMESTAMP WITH TIME ZONE)"
    ))
    conn.execute(sa.text(
        "CREATE TABLE module_access ("
        " id UUID PRIMARY KEY,"
        " module_id VARCHAR(64) NOT NULL,"
        " account_group VARCHAR(64) NOT NULL,"
        " enabled BOOLEAN NOT NULL)"
    ))
    conn.execute(sa.text(
        "CREATE TABLE module_tier_access ("
        " id UUID PRIMARY KEY,"
        " module_id VARCHAR(64) NOT NULL,"
        " tier VARCHAR(32) NOT NULL,"
        " enabled BOOLEAN NOT NULL)"
    ))
    conn.commit()

    mig.upgrade()
    conn.commit()

    insp = sa.inspect(engine)
    tables = set(insp.get_table_names())
    for expected in (
        "print_files",
        "print_file_versions",
        "print_ratings",
        "print_comments",
        "print_reports",
        "print_maker_links",
    ):
        assert expected in tables, f"missing table {expected}"

    file_cols = {c["name"] for c in insp.get_columns("print_files")}
    for expected in (
        "publisher_id", "publisher_gone", "title", "description",
        "category_key", "status", "removed_by_id", "removed_reason",
        "removed_at", "current_version", "download_count",
        "step_download_count", "rating_sum", "rating_count",
        "preview_key", "preview_content_type", "created_at",
        "updated_at",
    ):
        assert expected in file_cols, f"missing print_files.{expected}"

    version_uniques = {
        tuple(sorted(u["column_names"]))
        for u in insp.get_unique_constraints("print_file_versions")
    }
    assert ("file_id", "version_number") in version_uniques, version_uniques
    rating_uniques = {
        tuple(sorted(u["column_names"]))
        for u in insp.get_unique_constraints("print_ratings")
    }
    assert ("file_id", "user_id") in rating_uniques, rating_uniques

    report_cols = {c["name"] for c in insp.get_columns("print_reports")}
    for expected in (
        "target_kind", "file_id", "comment_id", "reporter_id",
        "reason", "status", "resolution", "resolved_by_id",
        "resolved_at", "created_at",
    ):
        assert expected in report_cols, f"missing print_reports.{expected}"

    state = conn.execute(sa.text(
        "SELECT globally_enabled FROM module_state"
        " WHERE module_id = 'prints'"
    )).scalar()
    assert state in (True, 1), state
    groups = conn.execute(sa.text(
        "SELECT account_group, enabled FROM module_access"
        " WHERE module_id = 'prints' ORDER BY account_group"
    )).all()
    assert [g for g, _ in groups] == [
        "insurance", "mechanic_technician", "shop_company",
        "tool_dealer",
    ], groups
    assert all(enabled for _, enabled in groups), groups
    tiers = conn.execute(sa.text(
        "SELECT tier, enabled FROM module_tier_access"
        " WHERE module_id = 'prints' ORDER BY tier"
    )).all()
    assert [t for t, _ in tiers] == [
        "beta", "moderator", "moderator_admin", "normal",
    ], tiers
    assert all(enabled for _, enabled in tiers), tiers

    mig.downgrade()
    conn.commit()

    insp = sa.inspect(engine)
    tables = set(insp.get_table_names())
    for gone in (
        "print_files",
        "print_file_versions",
        "print_ratings",
        "print_comments",
        "print_reports",
        "print_maker_links",
    ):
        assert gone not in tables, f"table survived downgrade: {gone}"
    for table in ("module_state", "module_access", "module_tier_access"):
        count = conn.execute(sa.text(
            f"SELECT count(*) FROM {table} WHERE module_id = 'prints'"
        )).scalar()
        assert count == 0, (table, count)

    print("BARE-0093-OK")
    """
)


def test_migration_0093_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0093.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0093_PATH"] = os.path.join(
        backend, "alembic", "versions", "0093_print_files.py"
    )
    env["MIG0093_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0093-OK" in proc.stdout
