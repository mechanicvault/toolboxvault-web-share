"""Migration 0096 (downloads tier cells + release-scoped
announcements) — bare-subprocess regression (standing rule,
owner 2026-11-06): pytest's conftest imports every model, so a
migration relying on shared-metadata imports stays green in the
suite while the real alembic boot crashes. This proof loads
ONLY the migration file — no `app.*` imports — and runs upgrade
+ downgrade against the parent schema the real chain has at
0095 for the two touched tables (module_tier_access as 0067
created it; feature_announcements as 0091 created it — column
names/types verified against the live production schema by
this lane), seeded with the four cell states production can
actually hold:

- prints: fully seeded, all keys on   -> gains ONLY a downloads
  row, ON (its seeded starting world), nothing else moves.
- support: no rows, no state row      -> materializes at the
  global fallback (on), downloads ON.
- forum: no rows, global switch OFF   -> materializes OFF,
  downloads OFF.
- inventory: one partial row (normal) -> missing keys
  materialize OFF (a present row set reads missing as off),
  downloads OFF, the existing row untouched.
- wishlist: a downloads row already present -> the upgrade is
  idempotent for it: row count and values unchanged.
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
        "mig0096", os.environ["MIG0096_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0096_URL"])
    ctx = MigrationContext.configure(engine.connect())
    mig.op = Operations(ctx)
    conn = ctx.connection

    # Parent schema at 0095 (0067's module_tier_access +
    # module_state; 0091's feature_announcements), exact
    # column names/types from the live production schema.
    conn.execute(sa.text(
        "CREATE TABLE module_state ("
        " module_id VARCHAR(64) PRIMARY KEY,"
        " globally_enabled BOOLEAN NOT NULL DEFAULT 1)"
    ))
    conn.execute(sa.text(
        "CREATE TABLE module_tier_access ("
        " id CHAR(32) PRIMARY KEY,"
        " module_id VARCHAR(64) NOT NULL,"
        " tier VARCHAR(32) NOT NULL,"
        " enabled BOOLEAN NOT NULL DEFAULT 0,"
        " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE (module_id, tier))"
    ))
    conn.execute(sa.text(
        "CREATE TABLE feature_announcements ("
        " id CHAR(32) PRIMARY KEY,"
        " title VARCHAR(200) NOT NULL DEFAULT '',"
        " body VARCHAR(1000) NOT NULL DEFAULT '',"
        " link VARCHAR(300),"
        " status VARCHAR(20) NOT NULL DEFAULT 'queued',"
        " recipient_count INTEGER,"
        " created_by_id CHAR(32),"
        " created_by_name VARCHAR(200) NOT NULL DEFAULT '',"
        " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " sent_at TIMESTAMP)"
    ))

    import uuid as _uuid
    def cell(module_id, tier, enabled):
        conn.execute(sa.text(
            "INSERT INTO module_tier_access (id, module_id, tier, enabled)"
            " VALUES (:id, :m, :t, :e)"
        ), {"id": _uuid.uuid4().hex, "m": module_id, "t": tier, "e": enabled})

    for key in ("normal", "moderator", "moderator_admin", "beta"):
        cell("prints", key, 1)
    cell("inventory", "normal", 1)
    cell("wishlist", "downloads", 0)
    conn.execute(sa.text(
        "INSERT INTO module_state (module_id, globally_enabled)"
        " VALUES ('forum', 0)"
    ))
    conn.commit()

    mig.upgrade()
    conn.commit()

    def cells(module_id):
        return {
            r[0]: bool(r[1])
            for r in conn.execute(sa.text(
                "SELECT tier, enabled FROM module_tier_access"
                " WHERE module_id = :m"
            ), {"m": module_id}).all()
        }

    prints = cells("prints")
    assert prints == {
        "normal": True, "moderator": True, "moderator_admin": True,
        "beta": True, "downloads": True,
    }, prints
    support = cells("support")
    assert support == {
        "normal": True, "moderator": True, "moderator_admin": True,
        "beta": True, "downloads": True,
    }, support
    forum = cells("forum")
    assert forum == {
        "normal": False, "moderator": False, "moderator_admin": False,
        "beta": False, "downloads": False,
    }, forum
    inventory = cells("inventory")
    assert inventory == {
        "normal": True, "moderator": False, "moderator_admin": False,
        "beta": False, "downloads": False,
    }, inventory
    wishlist = cells("wishlist")
    assert wishlist == {"downloads": False}, wishlist
    total_downloads = conn.execute(sa.text(
        "SELECT COUNT(*) FROM module_tier_access WHERE tier = 'downloads'"
    )).scalar()
    assert total_downloads == 21, total_downloads

    cols = {
        r[1] for r in conn.execute(sa.text(
            "PRAGMA table_info(feature_announcements)"
        )).all()
    }
    assert "release_module_id" in cols, cols
    assert "audience_user_ids" in cols, cols

    mig.downgrade()
    conn.commit()

    remaining = conn.execute(sa.text(
        "SELECT COUNT(*) FROM module_tier_access WHERE tier = 'downloads'"
    )).scalar()
    assert remaining == 0, remaining
    assert cells("prints") == {
        "normal": True, "moderator": True,
        "moderator_admin": True, "beta": True,
    }, cells("prints")
    cols = {
        r[1] for r in conn.execute(sa.text(
            "PRAGMA table_info(feature_announcements)"
        )).all()
    }
    assert "release_module_id" not in cols, cols
    assert "audience_user_ids" not in cols, cols

    print("BARE-0096-OK")
    """
)


def test_migration_0096_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0096.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0096_PATH"] = os.path.join(
        backend, "alembic", "versions", "0096_downloads_tier.py"
    )
    env["MIG0096_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0096-OK" in proc.stdout
