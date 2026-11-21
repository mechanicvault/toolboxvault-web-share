"""Migration 0094 (Downloads visitor counter) — bare-subprocess
regression (standing rule, owner 2026-11-06, after the third
migration incident): pytest's conftest imports every model, so
a migration that relies on shared-metadata imports (or any app
package import at all) stays green in the suite while the real
alembic boot crashes on it. This proof loads ONLY the migration
file — no `app.*` imports — upgrades and downgrades it against
the parent schema the real chain has at 0093 (visitor_counter
as migration 0064 created it, holding the teaser's live row),
and checks the Downloads row arrives at 0, the teaser row is
untouched either way, and the downgrade removes only id 2.
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
        "mig0094", os.environ["MIG0094_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0094_URL"])
    ctx = MigrationContext.configure(engine.connect())
    ops = Operations(ctx)
    mig.op = ops
    conn = ctx.connection
    # The parent schema the real chain has at 0093 for this
    # table: migration 0064's create (verified against the live
    # production schema before shipping: id integer PK, count
    # bigint NOT NULL DEFAULT 0), with the teaser's row holding
    # a live count the migration must never disturb.
    conn.execute(sa.text(
        "CREATE TABLE visitor_counter ("
        " id INTEGER PRIMARY KEY,"
        " count BIGINT NOT NULL DEFAULT 0)"
    ))
    conn.execute(sa.text(
        "INSERT INTO visitor_counter (id, count) VALUES (1, 48)"
    ))
    conn.commit()

    mig.upgrade()
    conn.commit()

    rows = conn.execute(sa.text(
        "SELECT id, count FROM visitor_counter ORDER BY id"
    )).all()
    assert rows == [(1, 48), (2, 0)], rows

    # A second upgrade is a no-op (the NOT EXISTS guard).
    mig.upgrade()
    conn.commit()
    rows = conn.execute(sa.text(
        "SELECT id, count FROM visitor_counter ORDER BY id"
    )).all()
    assert rows == [(1, 48), (2, 0)], rows

    mig.downgrade()
    conn.commit()

    rows = conn.execute(sa.text(
        "SELECT id, count FROM visitor_counter ORDER BY id"
    )).all()
    assert rows == [(1, 48)], rows

    print("BARE-0094-OK")
    """
)


def test_migration_0094_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0094.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0094_PATH"] = os.path.join(
        backend, "alembic", "versions", "0094_downloads_visitor_counter.py"
    )
    env["MIG0094_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0094-OK" in proc.stdout
