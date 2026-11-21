"""Migration 0021 (claims module).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0021 database (its own engine — the shared fixture
schema already carries the post-0021 shape) and pins:

- claims, claim_lines, claim_evidence and claim_communications
  are created with the columns the models declare;
- the claim -> children cascade FK is in place;
- downgrade removes exactly the four tables upgrade added.
"""

import importlib.util
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
    / "0021_claims.py"
)

_CLAIMS_TABLES = {"claims", "claim_lines", "claim_evidence", "claim_communications"}


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0021_claims", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0021_engine():
    """A database as of 0020: a users table (the claims tables
    reference it) and none of the claims tables."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                " id VARCHAR(36) PRIMARY KEY,"
                " email VARCHAR(320) NOT NULL DEFAULT ''"
                ")"
            )
        )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def test_0021_upgrade_creates_the_four_claims_tables():
    migration = _load_migration()
    assert migration.revision == "0021_claims"
    assert migration.down_revision == "0020_maintenance"
    engine = _pre_0021_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        inspector = sa.inspect(conn)
        assert _CLAIMS_TABLES <= set(inspector.get_table_names())
        claim_columns = {c["name"] for c in inspector.get_columns("claims")}
        assert {
            "claim_number", "claim_year", "number_seq", "insurer_name",
            "incident_type", "incident_date", "status",
            "police_report_number", "proof_of_loss_due",
            "proof_of_loss_sent_at", "depreciation_deadline",
            "filed_at", "closed_at",
        } <= claim_columns
        line_columns = {c["name"] for c in inspector.get_columns("claim_lines")}
        assert {
            "target_kind", "target_id", "set_id", "target_name",
            "set_name", "include_addons", "value_basis", "amount",
        } <= line_columns
        evidence_columns = {
            c["name"] for c in inspector.get_columns("claim_evidence")
        }
        assert {
            "source", "item_kind", "item_id", "attachment_key",
            "filename", "kind", "attachment",
        } <= evidence_columns
        fks = inspector.get_foreign_keys("claim_lines")
        assert any(
            fk["referred_table"] == "claims"
            and fk["options"].get("ondelete") == "CASCADE"
            for fk in fks
        )


def test_0021_downgrade_removes_exactly_what_upgrade_added():
    migration = _load_migration()
    engine = _pre_0021_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert not (_CLAIMS_TABLES & tables)
        assert "users" in tables  # pre-existing data untouched
