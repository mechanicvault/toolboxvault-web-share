"""Migration 0095 (print showcase media) — bare-subprocess
regression (standing rule, owner 2026-11-06, after the third
migration incident): pytest's conftest imports every model,
so a migration that relies on shared-metadata imports (or
any app package import at all) stays green in the suite
while the real alembic boot crashes on it. This proof loads
ONLY the migration file — no `app.*` imports — upgrades and
downgrades it against the parent schema the real chain has
at 0094 (print_files as migration 0093 created it, verified
against the live production schema by this lane), holding
one listing WITH a preview and one without, and checks: the
preview becomes photo #1 of the new print_media set on the
same storage key, the preview-less listing gains nothing,
and the downgrade drops the table while leaving every
print_files row — previews included — exactly as it was.
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
        "mig0095", os.environ["MIG0095_PATH"]
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(os.environ["MIG0095_URL"])
    ctx = MigrationContext.configure(engine.connect())
    ops = Operations(ctx)
    mig.op = ops
    conn = ctx.connection
    # The parent schema the real chain has at 0094 for this
    # table: migration 0093's print_files create, with the
    # exact column names/types the live production schema
    # carries (fresh pg_dump, this lane's evidence).
    conn.execute(sa.text(
        "CREATE TABLE print_files ("
        " id UUID PRIMARY KEY,"
        " publisher_id UUID NOT NULL,"
        " publisher_gone BOOLEAN NOT NULL DEFAULT 0,"
        " title VARCHAR(160) NOT NULL,"
        " description TEXT NOT NULL DEFAULT '',"
        " category_key VARCHAR(48) NOT NULL,"
        " status VARCHAR(16) NOT NULL DEFAULT 'live',"
        " removed_by_id UUID,"
        " removed_reason VARCHAR(500) NOT NULL DEFAULT '',"
        " removed_at TIMESTAMP,"
        " current_version INTEGER NOT NULL DEFAULT 1,"
        " download_count INTEGER NOT NULL DEFAULT 0,"
        " step_download_count INTEGER NOT NULL DEFAULT 0,"
        " rating_sum INTEGER NOT NULL DEFAULT 0,"
        " rating_count INTEGER NOT NULL DEFAULT 0,"
        " preview_key VARCHAR(300),"
        " preview_content_type VARCHAR(100) NOT NULL DEFAULT '',"
        " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    ))
    with_photo = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    no_photo = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    pub = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    conn.execute(sa.text(
        "INSERT INTO print_files (id, publisher_id, title, category_key,"
        " preview_key, preview_content_type) VALUES"
        " (:id, :pub, 'Tray', 'parts-trays', :key, 'image/png')"
    ), {"id": with_photo, "pub": pub,
        "key": f"prints/{pub}/{with_photo}/preview-tray.png"})
    conn.execute(sa.text(
        "INSERT INTO print_files (id, publisher_id, title, category_key)"
        " VALUES (:id, :pub, 'Bare', 'other-shop')"
    ), {"id": no_photo, "pub": pub})
    conn.commit()

    mig.upgrade()
    conn.commit()

    tables = {r[0] for r in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )).all()}
    assert "print_media" in tables, tables
    rows = conn.execute(sa.text(
        "SELECT file_id, kind, storage_key, content_type, filename,"
        " sort_order, duration_seconds FROM print_media"
    )).all()
    assert len(rows) == 1, rows
    file_id, kind, key, ctype, filename, sort_order, duration = rows[0]
    # The UUID type stores dashless hex through a raw read;
    # the ORM restores the dashed form (the app's own reads).
    assert str(file_id).replace("-", "") == with_photo.replace("-", ""), rows
    assert kind == "photo", rows
    assert key == f"prints/{pub}/{with_photo}/preview-tray.png", rows
    assert ctype == "image/png", rows
    assert filename == "tray.png", rows
    assert sort_order == 0, rows
    assert duration is None, rows

    mig.downgrade()
    conn.commit()

    tables = {r[0] for r in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )).all()}
    assert "print_media" not in tables, tables
    kept = conn.execute(sa.text(
        "SELECT id, preview_key FROM print_files ORDER BY title"
    )).all()
    assert len(kept) == 2, kept
    assert {str(r[0]) for r in kept} == {with_photo, no_photo}, kept
    assert [r[1] for r in kept if str(r[0]) == with_photo] == [
        f"prints/{pub}/{with_photo}/preview-tray.png"
    ], kept

    print("BARE-0095-OK")
    """
)


def test_migration_0095_bare_subprocess(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = tmp_path / "bare_0095.py"
    child.write_text(CHILD)
    env = dict(os.environ)
    env["MIG0095_PATH"] = os.path.join(
        backend, "alembic", "versions", "0095_print_media.py"
    )
    env["MIG0095_URL"] = f"sqlite:///{tmp_path / 'bare.db'}"
    proc = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "BARE-0095-OK" in proc.stdout
