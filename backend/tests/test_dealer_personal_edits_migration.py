"""Migration 0078 (personal dealer edits) upgrades a
0077-shaped database cleanly: the user_dealer_company_edits
table appears with the overlay columns, the (user, company)
unique constraint, and both FK targets wired; the downgrade
removes exactly what the upgrade added.
"""

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0078_dealer_personal_edits.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0078", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_state(engine):
    """Minimal pre-0078 shape: the two FK targets with the
    columns the new table references."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(300), nullable=False),
    )
    sa.Table(
        "dealer_companies",
        meta,
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
    )
    meta.create_all(engine)


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_migration_0078_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.revision == "0078_dealer_personal_edits"
    assert migration.down_revision == "0077_truck_accounts_stage2"
    engine = sa.create_engine("sqlite://")
    _pre_state(engine)
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, 'a@x.io')"),
            {"id": str(user_id)},
        )
        conn.execute(
            sa.text("INSERT INTO dealer_companies (id, name) VALUES (:id, 'Acme')"),
            {"id": str(company_id)},
        )
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert "user_dealer_company_edits" in inspector.get_table_names()
        columns = {
            c["name"] for c in inspector.get_columns("user_dealer_company_edits")
        }
        assert {
            "id", "user_id", "company_id", "name", "email", "website",
            "address", "phones", "notes", "logo_key", "logo_tile",
            "created_at", "updated_at",
        } <= columns
        uniques = inspector.get_unique_constraints("user_dealer_company_edits")
        assert any(
            set(u["column_names"]) == {"user_id", "company_id"} for u in uniques
        )
        fks = inspector.get_foreign_keys("user_dealer_company_edits")
        targets = {fk["referred_table"] for fk in fks}
        assert targets == {"users", "dealer_companies"}

        # A sparse overlay row stores fine (name only).
        conn.execute(
            sa.text(
                "INSERT INTO user_dealer_company_edits"
                " (id, user_id, company_id, name)"
                " VALUES (:id, :u, :c, 'My Acme')"
            ),
            {"id": str(uuid.uuid4()), "u": str(user_id), "c": str(company_id)},
        )

        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        assert "user_dealer_company_edits" not in inspector.get_table_names()
        # The pre-state tables are untouched by the round-trip.
        assert {"users", "dealer_companies"} <= set(inspector.get_table_names())
