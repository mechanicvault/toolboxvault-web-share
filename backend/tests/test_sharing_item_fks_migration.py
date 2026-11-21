"""Migration 0111 (sharing item FKs) upgrades a 0110-shaped
database cleanly: the seven item FKs on the four sharing tables
are dropped (the columns and indexes stay), and the downgrade
restores them with CASCADE.
"""

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0111_sharing_item_fks.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0111_fk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TABLES = {
    "shared_items": ("tool_id", "battery_id"),
    "peer_share_exclusions": ("tool_id", "battery_id"),
    "peer_set_choices": ("set_tool_id",),
    "share_exclusions": ("tool_id", "battery_id"),
}
_REFS = {"tool_id": "tools", "set_tool_id": "tools", "battery_id": "batteries"}


def _fk_name(table, column):
    # The names production carries (verified 2026-11-18): the
    # battery FKs on the two tables that existed when migration
    # 0014 added battery columns carry its fk_ names; everything
    # else (share_exclusions was born later, in 0031) carries
    # PostgreSQL's auto-names.
    if column == "battery_id" and table in (
        "shared_items",
        "peer_share_exclusions",
    ):
        return f"fk_{table}_battery_id"
    return f"{table}_{column}_fkey"


def _pre_state(engine):
    meta = MetaData()
    Table("tools", meta, Column("id", String(36), primary_key=True))
    Table("batteries", meta, Column("id", String(36), primary_key=True))
    for table, cols in _TABLES.items():
        Table(
            table,
            meta,
            Column("id", String(36), primary_key=True),
            *[
                Column(
                    c,
                    String(36),
                    ForeignKey(
                        f"{_REFS[c]}.id",
                        name=_fk_name(table, c),
                        ondelete="CASCADE",
                    ),
                )
                for c in cols
            ],
        )
    meta.create_all(engine)


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


def _fk_columns(engine, table):
    return {
        fk["constrained_columns"][0]
        for fk in inspect(engine).get_foreign_keys(table)
    }


def test_0111_drops_item_fks_and_downgrade_restores(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/mig.db")
    _pre_state(engine)
    migration = _load_migration()
    for table, cols in _TABLES.items():
        assert set(cols) <= _fk_columns(engine, table)

    _run(migration, engine, "up")
    for table in _TABLES:
        assert _fk_columns(engine, table) == set(), table

    _run(migration, engine, "down")
    for table, cols in _TABLES.items():
        assert set(cols) <= _fk_columns(engine, table)
