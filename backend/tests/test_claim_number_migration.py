"""Migration 0024 (claim-number unique constraint) against a
hand-built pre-0024 schema: the constraint lands, duplicate
(owner, year, seq) inserts are refused afterwards, the same seq
under a different owner/year stays legal, and downgrade removes
the constraint cleanly. Same hand-rolled harness pattern as the
checkout-seq migration test."""

import uuid

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_OWNER_A = str(uuid.uuid4())
_OWNER_B = str(uuid.uuid4())


def _load_migration():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0024_claim_number_unique.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0024", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0024_engine():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE claims ("
                "id VARCHAR(36) PRIMARY KEY, "
                "owner_id VARCHAR(36) NOT NULL, "
                "claim_number VARCHAR(20) NOT NULL, "
                "claim_year INTEGER NOT NULL, "
                "number_seq INTEGER NOT NULL)"
            )
        )
        for owner, seq in ((_OWNER_A, 1), (_OWNER_A, 2), (_OWNER_B, 1)):
            conn.execute(
                sa.text(
                    "INSERT INTO claims (id, owner_id, claim_number,"
                    " claim_year, number_seq) VALUES (:id, :o, :n, 2026, :s)"
                ),
                {"id": str(uuid.uuid4()), "o": owner, "n": f"CL-2026-{seq:03d}", "s": seq},
            )
    return engine


def _insert(conn, owner, seq):
    conn.execute(
        sa.text(
            "INSERT INTO claims (id, owner_id, claim_number,"
            " claim_year, number_seq) VALUES (:id, :o, :n, 2026, :s)"
        ),
        {"id": str(uuid.uuid4()), "o": owner, "n": f"CL-2026-{seq:03d}", "s": seq},
    )


def test_upgrade_adds_constraint_and_downgrade_removes_it():
    migration = _load_migration()
    engine = _pre_0024_engine()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.upgrade()
        conn.commit()

        # Duplicate (owner, year, seq) is now refused...
        try:
            with conn.begin():
                _insert(conn, _OWNER_A, 2)
            raise AssertionError("duplicate claim number insert was allowed")
        except sa.exc.IntegrityError:
            pass
        # ...while the same seq for another owner or year stays legal.
        with conn.begin():
            _insert(conn, _OWNER_B, 2)
            conn.execute(
                sa.text(
                    "INSERT INTO claims (id, owner_id, claim_number,"
                    " claim_year, number_seq) VALUES (:id, :o, 'CL-2027-002', 2027, 2)"
                ),
                {"id": str(uuid.uuid4()), "o": _OWNER_A},
            )

        with Operations.context(ctx):
            migration.downgrade()
        conn.commit()
        # Constraint gone: the duplicate insert succeeds again.
        with conn.begin():
            _insert(conn, _OWNER_A, 2)
