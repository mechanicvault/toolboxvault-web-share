"""Migration 0074 (repairs ∪ claims merge) against a hand-built
pre-0074 database, in the test_claim_number_migration harness
pattern. Pins:

- claims gains repair_sent_to / repair_cost / repair_completed_at;
- warranty_service_requests.repair_record_id becomes claim_id;
- every repair record becomes a warranty claim: status mapped
  onto the ladder (awaiting_parts -> in_repair), problem ->
  description, cost / sent-to / dates carried verbatim, claim
  numbers continuing the owner's CL-<year>-<seq> ledger, one
  snapshot line per claim (piece records keep their set link);
- warranty requests re-point at the converted claims (requests
  whose records were already gone keep their dangling id);
- the journal's repair_record rows become non-restorable (other
  entities untouched);
- repair_records is dropped;
- a second upgrade() run is a no-op (idempotent).
"""

import importlib.util
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0074_claims_repairs_merge.py"
)

_OWNER_A = str(uuid.uuid4())
_OWNER_B = str(uuid.uuid4())
_EXISTING_CLAIM = str(uuid.uuid4())
_RECORD_DONE = str(uuid.uuid4())
_RECORD_PARTS = str(uuid.uuid4())
_RECORD_PIECE = str(uuid.uuid4())
_SET_ID = str(uuid.uuid4())
_DANGLING = str(uuid.uuid4())

_TS = datetime(2026, 10, 20, 13, 52, 53, tzinfo=timezone.utc)
_TS_DONE = datetime(2026, 10, 20, 13, 52, 54, tzinfo=timezone.utc)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0074", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0074_engine():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE claims ("
                " id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(36) NOT NULL,"
                " claim_number VARCHAR(20) NOT NULL DEFAULT '',"
                " claim_year INTEGER NOT NULL DEFAULT 0,"
                " number_seq INTEGER NOT NULL DEFAULT 0,"
                " kind VARCHAR(30) NOT NULL DEFAULT 'insurance_disaster',"
                " insurer_name VARCHAR(300) NOT NULL DEFAULT '',"
                " policy_number VARCHAR(200) NOT NULL DEFAULT '',"
                " dealer_company_id VARCHAR(36),"
                " dealer_name VARCHAR(300) NOT NULL DEFAULT '',"
                " agent_user_id VARCHAR(36), private_agent_id VARCHAR(36),"
                " manufacturer_case_number VARCHAR(200) NOT NULL DEFAULT '',"
                " reported_at DATETIME, report_method VARCHAR(20) NOT NULL DEFAULT '',"
                " agent_name VARCHAR(300) NOT NULL DEFAULT '',"
                " agent_phone VARCHAR(100) NOT NULL DEFAULT '',"
                " agent_email VARCHAR(300) NOT NULL DEFAULT '',"
                " incident_type VARCHAR(20) NOT NULL DEFAULT 'damage',"
                " incident_date DATE, description TEXT NOT NULL DEFAULT '',"
                " status VARCHAR(20) NOT NULL DEFAULT 'draft',"
                " police_report_number VARCHAR(100) NOT NULL DEFAULT '',"
                " police_department VARCHAR(200) NOT NULL DEFAULT '',"
                " police_report_date DATE, proof_of_loss_due DATE,"
                " proof_of_loss_sent_at DATE, depreciation_deadline DATE,"
                " filed_at DATETIME, closed_at DATETIME,"
                " archived BOOLEAN NOT NULL DEFAULT 0, archived_at DATETIME,"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE claim_lines ("
                " id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(36) NOT NULL,"
                " claim_id VARCHAR(36) NOT NULL,"
                " target_kind VARCHAR(10) NOT NULL, target_id VARCHAR(36) NOT NULL,"
                " set_id VARCHAR(36), target_name VARCHAR(300) NOT NULL DEFAULT '',"
                " set_name VARCHAR(300) NOT NULL DEFAULT '',"
                " target_part_number VARCHAR(200) NOT NULL DEFAULT '',"
                " set_model_number VARCHAR(200) NOT NULL DEFAULT '',"
                " include_addons BOOLEAN NOT NULL DEFAULT 0,"
                " value_basis VARCHAR(20) NOT NULL DEFAULT 'entered',"
                " amount NUMERIC(12, 2),"
                " include_in_package BOOLEAN NOT NULL DEFAULT 1,"
                " created_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE repair_records ("
                " id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(36) NOT NULL,"
                " item_kind VARCHAR(10) NOT NULL, item_id VARCHAR(36) NOT NULL,"
                " item_name VARCHAR(300) NOT NULL DEFAULT '',"
                " set_id VARCHAR(36), set_name VARCHAR(300) NOT NULL DEFAULT '',"
                " status VARCHAR(20) NOT NULL DEFAULT 'reported',"
                " problem TEXT NOT NULL DEFAULT '',"
                " sent_to VARCHAR(300) NOT NULL DEFAULT '',"
                " repair_cost NUMERIC(12, 2),"
                " was_checked_out BOOLEAN NOT NULL DEFAULT 0,"
                " notes TEXT NOT NULL DEFAULT '',"
                " reported_at DATETIME NOT NULL,"
                " completed_at DATETIME,"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE warranty_service_requests ("
                " id VARCHAR(36) PRIMARY KEY,"
                " repair_record_id VARCHAR(36),"
                " status VARCHAR(20) NOT NULL DEFAULT 'sent')"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE change_journal ("
                " id VARCHAR(36) PRIMARY KEY,"
                " entity_type VARCHAR(50) NOT NULL,"
                " restorable BOOLEAN NOT NULL DEFAULT 1)"
            )
        )
        # One pre-existing claim: the converted numbers continue
        # its owner's ledger (next seq = 8).
        conn.execute(
            sa.text(
                "INSERT INTO claims (id, owner_id, claim_number, claim_year,"
                " number_seq, kind, status, created_at, updated_at)"
                " VALUES (:id, :o, 'CL-2026-007', 2026, 7,"
                " 'insurance_disaster', 'filed', :ts, :ts)"
            ),
            {"id": _EXISTING_CLAIM, "o": _OWNER_A, "ts": _TS},
        )
        # Distinct created_ats per owner: the conversion numbers
        # claims in (created_at, id) order, and same-instant ties
        # would make the expected numbers depend on uuid order.
        later = datetime(2026, 10, 20, 14, 52, 53, tzinfo=timezone.utc)
        records = [
            # (id, owner, kind, item_id, set_id, status, problem,
            #  sent_to, cost, reported, completed, created)
            (_RECORD_DONE, _OWNER_A, "tool", str(uuid.uuid4()), None,
             "completed", "Smoke break", "Smoke Dealer",
             42.50, _TS, _TS_DONE, _TS),  # float: raw sqlite can't bind Decimal
            (_RECORD_PARTS, _OWNER_A, "tool", str(uuid.uuid4()), None,
             "awaiting_parts", "Waiting on a gear", "Gear Depot",
             None, later, None, later),
            (_RECORD_PIECE, _OWNER_B, "piece", str(uuid.uuid4()), _SET_ID,
             "reported", "test broken", "",
             None, _TS, None, _TS),
        ]
        for (rid, owner, kind, item_id, set_id, status, problem,
             sent_to, cost, reported, completed, created) in records:
            conn.execute(
                sa.text(
                    "INSERT INTO repair_records (id, owner_id, item_kind,"
                    " item_id, item_name, set_id, set_name, status, problem,"
                    " sent_to, repair_cost, reported_at, completed_at,"
                    " created_at, updated_at) VALUES (:id, :o, :k, :iid,"
                    " 'History Story Wrench', :sid, 'Big Set', :st, :pr,"
                    " :sent, :cost, :rep, :comp, :created, :created)"
                ),
                {
                    "id": rid, "o": owner, "k": kind, "iid": item_id,
                    "sid": set_id, "st": status, "pr": problem,
                    "sent": sent_to, "cost": cost,
                    "rep": reported, "comp": completed, "created": created,
                },
            )
        for rid, target in ((_RECORD_DONE, _RECORD_DONE), ("req-2", _DANGLING)):
            conn.execute(
                sa.text(
                    "INSERT INTO warranty_service_requests"
                    " (id, repair_record_id) VALUES (:id, :t)"
                ),
                {"id": f"req-{rid[:4]}" if rid != "req-2" else rid, "t": target},
            )
        conn.execute(
            sa.text(
                "INSERT INTO change_journal (id, entity_type, restorable)"
                " VALUES ('j1', 'repair_record', 1), ('j2', 'claim', 1)"
            )
        )
    return engine


def _run_upgrade(engine, migration):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.upgrade()
        conn.commit()


def test_upgrade_converts_records_to_claims():
    migration = _load_migration()
    assert migration.revision == "0074_claims_repairs_merge"
    assert migration.down_revision == "0073_agent_takeover"
    engine = _pre_0074_engine()
    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        assert not sa.inspect(conn).has_table("repair_records")
        claim_cols = {c["name"] for c in sa.inspect(conn).get_columns("claims")}
        assert {"repair_sent_to", "repair_cost", "repair_completed_at"} <= claim_cols
        request_cols = {
            c["name"] for c in sa.inspect(conn).get_columns("warranty_service_requests")
        }
        assert "claim_id" in request_cols
        assert "repair_record_id" not in request_cols

        claims = conn.execute(
            sa.text(
                "SELECT id, owner_id, claim_number, kind, status, description,"
                " repair_sent_to, repair_cost, repair_completed_at, reported_at"
                " FROM claims ORDER BY claim_number"
            )
        ).fetchall()
        assert len(claims) == 4  # the pre-existing one + 3 converted
        by_number = {row[2]: row for row in claims}

        done = by_number["CL-2026-008"]  # ledger continued from seq 7
        assert done[1] == _OWNER_A
        assert done[3] == "warranty_repair"
        assert done[4] == "completed"
        assert done[5] == "Smoke break"
        assert done[6] == "Smoke Dealer"
        assert Decimal(str(done[7])) == Decimal("42.50")
        assert done[8] is not None  # repair_completed_at carried

        parts = by_number["CL-2026-009"]
        assert parts[4] == "in_repair"  # awaiting_parts maps onto the ladder
        assert parts[6] == "Gear Depot"
        assert parts[7] is None

        piece = by_number["CL-2026-001"]  # owner B's own ledger starts at 1
        assert piece[1] == _OWNER_B
        assert piece[4] == "reported"  # faithfully NOT completed
        assert piece[5] == "test broken"

        lines = conn.execute(
            sa.text(
                "SELECT claim_id, target_kind, target_id, set_id, target_name"
                " FROM claim_lines"
            )
        ).fetchall()
        assert len(lines) == 3
        piece_line = next(r for r in lines if r[1] == "piece")
        assert piece_line[0] == piece[0]
        assert piece_line[3] == _SET_ID
        assert piece_line[4] == "History Story Wrench"

        requests = conn.execute(
            sa.text("SELECT id, claim_id FROM warranty_service_requests")
        ).fetchall()
        by_id = {r[0]: r[1] for r in requests}
        assert by_id["req-" + _RECORD_DONE[:4]] == done[0]
        assert by_id["req-2"] == _DANGLING  # untouched, as it dangled before

        journal = conn.execute(
            sa.text("SELECT id, restorable FROM change_journal ORDER BY id")
        ).fetchall()
        assert journal == [("j1", 0), ("j2", 1)]

    # Idempotent: a second run changes nothing.
    _run_upgrade(engine, migration)
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT COUNT(*) FROM claims")).scalar()
        assert count == 4


def test_downgrade_restores_shapes_not_data():
    migration = _load_migration()
    engine = _pre_0074_engine()
    _run_upgrade(engine, migration)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.downgrade()
        conn.commit()
        assert sa.inspect(conn).has_table("repair_records")
        rows = conn.execute(sa.text("SELECT COUNT(*) FROM repair_records")).scalar()
        assert rows == 0  # shapes return; the conversion is one-way
        claim_cols = {c["name"] for c in sa.inspect(conn).get_columns("claims")}
        assert "repair_cost" not in claim_cols
        count = conn.execute(sa.text("SELECT COUNT(*) FROM claims")).scalar()
        assert count == 4  # converted claims stay claims
