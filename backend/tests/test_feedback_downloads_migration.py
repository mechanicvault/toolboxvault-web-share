"""Migration 0097 (the feedback boards join the downloads
level) — bare-subprocess regression (standing rule, owner
2026-11-06): pytest's conftest imports every model, so a
migration relying on shared-metadata imports stays green in
the suite while the real alembic boot crashes. This proof
loads ONLY the migration file — no `app.*` imports — and runs
upgrade + downgrade against the parent schema the real chain
has at 0096 for the one touched table (module_tier_access as
0067 created it — column names/types verified against the
live production schema by this lane), seeded with the cell
states production can actually hold:

- feedback: the exact 0096 shape — the four pre-existing keys
  ON (their production values), downloads OFF -> upgrade flips
  ONLY the downloads cell; running upgrade twice changes
  nothing more (idempotent).
- prints + support: downloads ON (0096's lit cells) and forum:
  downloads OFF -> all three untouched (the write is scoped
  to the one cell).
- downgrade -> the table is the 0096 state again, byte for
  byte on (module_id, tier, enabled).
- feedback's downloads cell then DELETED (a drifted database
  where the cell was never seeded — for this rung a missing
  cell reads OFF) -> upgrade writes it ON; downgrade reads it
  OFF again.
- feedback's downloads cell already ON before upgrade -> the
  row is left exactly as found.
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
        "mig0097", os.environ["MIG0097_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0097_URL"])
    ctx = MigrationContext.configure(engine.connect())
    mig.op = Operations(ctx)
    conn = ctx.connection

    # Parent schema at 0096 (0067's module_tier_access), exact
    # column names/types from the live production schema.
    conn.execute(sa.text(
        "CREATE TABLE module_tier_access ("
        " id CHAR(32) PRIMARY KEY,"
        " module_id VARCHAR(64) NOT NULL,"
        " tier VARCHAR(32) NOT NULL,"
        " enabled BOOLEAN NOT NULL DEFAULT 0,"
        " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE (module_id, tier))"
    ))

    import uuid as _uuid
    def cell(module_id, tier, enabled):
        conn.execute(sa.text(
            "INSERT INTO module_tier_access (id, module_id, tier, enabled)"
            " VALUES (:id, :m, :t, :e)"
        ), {"id": _uuid.uuid4().hex, "m": module_id, "t": tier, "e": enabled})

    # The 0096 world for the modules this proof watches.
    for key in ("normal", "moderator", "moderator_admin", "beta"):
        cell("feedback", key, 1)
    cell("feedback", "downloads", 0)
    cell("prints", "downloads", 1)
    cell("support", "downloads", 1)
    cell("forum", "downloads", 0)
    conn.commit()

    def cells(module_id):
        return {
            r[0]: bool(r[1])
            for r in conn.execute(sa.text(
                "SELECT tier, enabled FROM module_tier_access"
                " WHERE module_id = :m"
            ), {"m": module_id}).all()
        }

    def whole_table():
        return sorted(
            (r[0], r[1], bool(r[2]))
            for r in conn.execute(sa.text(
                "SELECT module_id, tier, enabled FROM module_tier_access"
            )).all()
        )

    before = whole_table()

    mig.upgrade()
    conn.commit()

    feedback = cells("feedback")
    assert feedback == {
        "normal": True, "moderator": True, "moderator_admin": True,
        "beta": True, "downloads": True,
    }, feedback
    assert cells("prints") == {"downloads": True}, cells("prints")
    assert cells("support") == {"downloads": True}, cells("support")
    assert cells("forum") == {"downloads": False}, cells("forum")
    after_first = whole_table()
    assert len(after_first) == len(before), (before, after_first)
    flipped = [
        row for row in after_first if row not in before
    ]
    assert flipped == [("feedback", "downloads", True)], flipped

    # Idempotent: a second upgrade moves nothing at all.
    mig.upgrade()
    conn.commit()
    assert whole_table() == after_first, whole_table()

    mig.downgrade()
    conn.commit()
    assert whole_table() == before, (before, whole_table())

    # The drifted shape: the cell was never seeded. A missing
    # cell reads OFF for this rung, so the upgrade must WRITE
    # it, and the downgrade must read OFF again.
    conn.execute(sa.text(
        "DELETE FROM module_tier_access"
        " WHERE module_id = 'feedback' AND tier = 'downloads'"
    ))
    conn.commit()
    mig.upgrade()
    conn.commit()
    assert cells("feedback")["downloads"] is True, cells("feedback")
    mig.downgrade()
    conn.commit()
    assert cells("feedback")["downloads"] is False, cells("feedback")

    # Already lit before the upgrade: left exactly as found.
    conn.execute(sa.text(
        "UPDATE module_tier_access SET enabled = 1"
        " WHERE module_id = 'feedback' AND tier = 'downloads'"
    ))
    conn.commit()
    lit = whole_table()
    mig.upgrade()
    conn.commit()
    assert whole_table() == lit, (lit, whole_table())

    print("BARE-0097-OK")
    """
)


def test_migration_0097_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0097.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0097_PATH"] = os.path.join(
        backend, "alembic", "versions", "0097_feedback_for_downloads.py"
    )
    env["MIG0097_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0097-OK" in proc.stdout
