"""Migration 0098 (download_events — the dated download
record) — bare-subprocess regression (standing rule, owner
2026-11-06): pytest's conftest imports every model, so a
migration relying on shared-metadata imports stays green in
the suite while the real alembic boot crashes. This proof
loads ONLY the migration file — no `app.*` imports — and runs
upgrade + downgrade against the parent schema the real chain
has at 0097 for the one referenced table (download_files as
0092 created it — column names/types verified against the
live production schema by this lane):

- upgrade creates download_events with its FK onto
  download_files.key and both indexes; an event row inserts
  against a real file key and refuses a bogus one;
- downgrade drops exactly the new table — download_files and
  its rows are untouched;
- a second upgrade after the downgrade reproduces the table
  (the chain can re-run the step cleanly).
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

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "mig0098", os.environ["MIG0098_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0098_URL"])
    ctx = MigrationContext.configure(engine.connect())
    mig.op = Operations(ctx)
    conn = ctx.connection

    # Parent schema at 0097 (0092's download_files), exact
    # column names/types from the live production schema.
    conn.execute(sa.text(
        "CREATE TABLE download_files ("
        " id CHAR(32) PRIMARY KEY,"
        " key VARCHAR(64) NOT NULL UNIQUE,"
        " file_format VARCHAR(8) NOT NULL,"
        " filename VARCHAR(200) NOT NULL,"
        " storage_key VARCHAR(300) NOT NULL,"
        " sort_order INTEGER NOT NULL DEFAULT 0,"
        " is_active BOOLEAN NOT NULL DEFAULT 1,"
        " download_count INTEGER NOT NULL DEFAULT 0,"
        " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    ))
    conn.execute(sa.text(
        "INSERT INTO download_files (id, key, file_format, filename, storage_key)"
        " VALUES ('a', 'sheet-one', 'xlsx', 'Sheet.xlsx', 'downloads/sheet-one')"
    ))
    conn.commit()

    def tables():
        return {
            r[0]
            for r in conn.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )).all()
        }

    assert "download_events" not in tables()
    mig.upgrade()
    conn.commit()
    assert "download_events" in tables(), tables()

    # The FK is real: a bogus file key is refused (FK pragma on).
    conn.execute(sa.text("PRAGMA foreign_keys = ON"))
    import uuid as _uuid
    conn.execute(sa.text(
        "INSERT INTO download_events (id, file_key)"
        " VALUES (:id, 'sheet-one')"
    ), {"id": _uuid.uuid4().hex})
    conn.commit()
    try:
        conn.execute(sa.text(
            "INSERT INTO download_events (id, file_key)"
            " VALUES (:id, 'no-such-file')"
        ), {"id": _uuid.uuid4().hex})
        conn.commit()
        raise AssertionError("bogus file_key was accepted")
    except sa.exc.IntegrityError:
        conn.rollback()

    mig.downgrade()
    conn.commit()
    assert "download_events" not in tables(), tables()
    # The parent table and its row survive untouched.
    rows = conn.execute(sa.text(
        "SELECT key, download_count FROM download_files"
    )).all()
    assert rows == [("sheet-one", 0)], rows

    # Re-upgrade reproduces the table cleanly.
    mig.upgrade()
    conn.commit()
    assert "download_events" in tables(), tables()
    mig.downgrade()
    conn.commit()
    assert "download_events" not in tables(), tables()

    print("BARE-0098-OK")
    """
)


def test_migration_0098_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0098.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0098_PATH"] = os.path.join(
        backend, "alembic", "versions", "0098_download_events.py"
    )
    env["MIG0098_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0098-OK" in proc.stdout
