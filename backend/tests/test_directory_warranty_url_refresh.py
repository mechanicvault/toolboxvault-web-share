"""Migration 0043 (directory warranty-URL refresh, audit A12).

Runs the migration's real upgrade()/downgrade() against a sqlite
dealer_companies table holding the pre-pass platform values, and pins:

- the five flagged platform rows gain the verified official URLs;
- rows an operator/user owns (owner_id set) are NEVER touched, even
  with a matching name;
- unflagged platform rows keep their values;
- the upgrade is idempotent; the downgrade restores the old values.
"""

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0043_directory_warranty_urls.py"
)

_OLD = {
    "Snap-on Incorporated": "https://www.snapon.com/Terms-and-Conditions-of-Sale",
    "Amazon.com": "https://www.amazon.com/gp/help/customer/display.html?nodeId=201819200",
    "SUNEX Tools Inc.": "https://sunextools.com/pages/test-forms",
    "Wright Tool Company": "https://wrighttool.com/support",
    "Harbor Freight Tools": None,
}
_NEW = {
    "Snap-on Incorporated": "https://snapon.com/warranty-information",
    "Amazon.com": "https://www.amazon.com/gp/help/customer/display.html?nodeId=201809390",
    "SUNEX Tools Inc.": "https://sunextools.com/pages/warranty-information",
    "Wright Tool Company": "https://wrighttool.com/pages/warranty",
    "Harbor Freight Tools": "https://www.harborfreight.com/media/catalog/product/w/a/warranty-hand-tools.pdf",
}
_UNTOUCHED_URL = "https://www.matcotools.com"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0043_directory_warranty_urls", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE dealer_companies ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36),"
                " name VARCHAR(300) NOT NULL,"
                " warranty_url VARCHAR(500)"
                ")"
            )
        )
        rows = [(name, None, url) for name, url in _OLD.items()]
        rows.append(("Matco Tools", None, _UNTOUCHED_URL))
        # A user-owned private company that happens to share a name.
        rows.append(
            ("Snap-on Incorporated", str(uuid.uuid4()), "https://example.com/mine")
        )
        for name, owner_id, url in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO dealer_companies (id, owner_id, name, warranty_url)"
                    " VALUES (:i, :o, :n, :u)"
                ),
                {"i": str(uuid.uuid4()), "o": owner_id, "n": name, "u": url},
            )
    return engine


def _urls(conn):
    result = conn.execute(
        sa.text(
            "SELECT name, owner_id, warranty_url FROM dealer_companies"
        )
    )
    return {(r.name, r.owner_id): r.warranty_url for r in result}


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_upgrade_refresh_is_scoped_idempotent_and_reversible():
    migration = _load_migration()
    engine = _engine()
    with engine.connect() as conn:
        _run(conn, migration.upgrade)
        urls = _urls(conn)
        for name, new in _NEW.items():
            assert urls[(name, None)] == new, name
        assert urls[("Matco Tools", None)] == _UNTOUCHED_URL
        private = [u for (n, o), u in urls.items() if o is not None]
        assert private == ["https://example.com/mine"]
        _run(conn, migration.upgrade)  # idempotent
        assert _urls(conn) == urls
        _run(conn, migration.downgrade)
        down = _urls(conn)
        for name, old in _OLD.items():
            assert down[(name, None)] == old, name
        assert down[("Matco Tools", None)] == _UNTOUCHED_URL
