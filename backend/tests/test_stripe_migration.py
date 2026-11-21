"""Migration 0017 (Stripe wiring): against a hand-built PRE-0017
database, the upgrade adds users.stripe_customer_id, the
subscription mirror columns, and the stripe_events ledger; the
downgrade removes all of it. Existing rows survive untouched —
the columns are nullable and the ledger starts empty.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(
        filename[:-3], MIGRATIONS_DIR / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ops(engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            yield conn


def _columns(engine, table: str) -> set[str]:
    inspector = sa.inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def _tables(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def _pre_0017_engine(tmp_path: Path):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/pre_stripe.db")
    with engine.begin() as conn:
        # The pre-0017 shape the migration touches: users without
        # the customer id, subscriptions without the mirror facts.
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                " id CHAR(36) PRIMARY KEY,"
                " email VARCHAR(320) NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE subscriptions ("
                " user_id CHAR(36) PRIMARY KEY,"
                " plan_key VARCHAR(32) NOT NULL,"
                " status VARCHAR(20) NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email) VALUES "
                "('11111111-1111-1111-1111-111111111111', 'a@example.com')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_key, status) VALUES "
                "('11111111-1111-1111-1111-111111111111', 'pro', 'active')"
            )
        )
    return engine


def test_0017_is_chained_after_item_structure():
    migration = _load_migration("0017_stripe.py")
    assert migration.revision == "0017_stripe"
    assert migration.down_revision == "0016_item_structure"


def test_0017_upgrade_adds_columns_and_ledger_then_downgrade_removes(tmp_path):
    migration = _load_migration("0017_stripe.py")
    engine = _pre_0017_engine(tmp_path)

    assert "stripe_customer_id" not in _columns(engine, "users")
    assert "stripe_events" not in _tables(engine)

    for conn in _ops(engine):
        migration.upgrade()
        conn.commit()

    assert "stripe_customer_id" in _columns(engine, "users")
    subscription_cols = _columns(engine, "subscriptions")
    assert "stripe_subscription_id" in subscription_cols
    assert "stripe_status" in subscription_cols
    assert "bracket_key" in subscription_cols
    assert "stripe_events" in _tables(engine)

    with engine.connect() as conn:
        # Pre-existing data survived; the new facts start empty.
        row = conn.execute(
            sa.text(
                "SELECT plan_key, status, stripe_subscription_id"
                " FROM subscriptions"
            )
        ).one()
        assert row == ("pro", "active", None)
        count = conn.execute(sa.text("SELECT COUNT(*) FROM stripe_events")).scalar()
        assert count == 0

    for conn in _ops(engine):
        migration.downgrade()
        conn.commit()

    assert "stripe_customer_id" not in _columns(engine, "users")
    assert "stripe_subscription_id" not in _columns(engine, "subscriptions")
    assert "stripe_events" not in _tables(engine)
    engine.dispose()
