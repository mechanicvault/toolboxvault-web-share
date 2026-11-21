"""Migration 0112 (usernames) upgrades a 0111-shaped database
cleanly: the three columns and the unique key index appear,
god-tier accounts are backfilled with the reserved name
"Toolbox Vault", everyone else stays unpicked (NULL), and the
downgrade removes exactly what the upgrade added.
"""

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import (
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0112_usernames.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0112", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    meta = MetaData()
    Table(
        "users",
        meta,
        Column("id", String(36), primary_key=True),
        Column("tier", String(32), nullable=False),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, tier) VALUES (:i, :t)"
            ),
            [
                {"i": str(uuid.uuid4()), "t": "god"},
                {"i": str(uuid.uuid4()), "t": "normal"},
            ],
        )


def _run(migration, engine, direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            if direction == "up":
                migration.upgrade()
            else:
                migration.downgrade()


def test_0112_upgrade_backfills_god_and_downgrade_reverts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/mig.db")
    _pre_state(engine)
    migration = _load_migration()

    _run(migration, engine, "up")
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert {"username", "username_key", "username_changed_at"} <= columns
    indexes = inspect(engine).get_indexes("users")
    assert any(
        idx["name"] == "uq_users_username_key" and idx["unique"]
        for idx in indexes
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tier, username, username_key FROM users ORDER BY tier")
        ).all()
    by_tier = {tier: (username, key) for tier, username, key in rows}
    assert by_tier["god"] == ("Toolbox Vault", "toolboxvault")
    assert by_tier["normal"] == (None, None)

    _run(migration, engine, "down")
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "username" not in columns
    assert "username_key" not in columns
    assert "username_changed_at" not in columns
