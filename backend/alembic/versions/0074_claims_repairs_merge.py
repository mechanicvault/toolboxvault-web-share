"""Repairs ∪ claims merge (owner model, 2026-11-03; built 2026-11-04).

Ryan's ruling: "The thought process behind a repair is the same
thing as a warranty claim. Even if it's outside of warranty and
the user has to pay to get it repaired, it still goes through a
warranty claim. So these 2 aspects need to be merged under the
claim tab." The warranty claim absorbs the repair record's
working end, so the separate repair_records ledger retires:

- claims gains the repair working end: repair_sent_to (where the
  item was sent), repair_cost (what the repair cost — a paid,
  out-of-warranty repair is the same claim with a cost on it),
  repair_completed_at (when the work finished; closing the claim
  later keeps all three).
- Every repair_records row becomes a warranty claim: status maps
  onto the claim ladder (reported -> reported, in_repair /
  awaiting_parts -> in_repair, completed -> completed), the
  problem becomes the claim's description, cost/dates/sent-to
  carry over verbatim, and one claim line snapshots the target
  (the ledger doctrine: the line outlives the item — several
  production records already point at deleted items and stay
  readable exactly that way). Claim numbers join the owner's
  CL-<year>-<seq> ledger in the record's own creation year.
- warranty_service_requests.repair_record_id is renamed to
  claim_id and re-pointed at the converted claims for the
  records that still exist (requests whose records were already
  deleted keep dangling ids, exactly as they dangled before —
  their snapshots keep them readable).
- repair_records is dropped. The conversion is one-way: the
  downgrade restores the empty table + column shapes but does
  not un-convert claims.

Idempotent: the conversion runs only while repair_records
exists and holds rows; a re-run after success finds no table.

Revision ID: 0074_claims_repairs_merge
Revises: 0073_agent_takeover
Create Date: 2026-11-04
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0074_claims_repairs_merge"
down_revision = "0073_agent_takeover"
branch_labels = None
depends_on = None


def _as_datetime(value):
    """Postgres hands back datetimes; SQLite hands back strings.
    The conversion reads either."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))

_STATUS_MAP = {
    "reported": "reported",
    "in_repair": "in_repair",
    "awaiting_parts": "in_repair",
    "completed": "completed",
}


def upgrade() -> None:
    bind = op.get_bind()
    # Every DDL step is guarded, so the upgrade is safe to re-run
    # against a database that already carries the merged shape
    # (the conversion below is likewise gated on the retired
    # table still existing).
    inspector = sa.inspect(bind)
    claim_columns = {c["name"] for c in inspector.get_columns("claims")}
    if "repair_sent_to" not in claim_columns:
        op.add_column(
            "claims",
            sa.Column(
                "repair_sent_to",
                sa.String(length=300),
                nullable=False,
                server_default="",
            ),
        )
    if "repair_cost" not in claim_columns:
        op.add_column(
            "claims",
            sa.Column(
                "repair_cost", sa.Numeric(precision=12, scale=2), nullable=True
            ),
        )
    if "repair_completed_at" not in claim_columns:
        op.add_column(
            "claims",
            sa.Column(
                "repair_completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    request_columns = {
        c["name"] for c in inspector.get_columns("warranty_service_requests")
    }
    if "repair_record_id" in request_columns:
        op.alter_column(
            "warranty_service_requests",
            "repair_record_id",
            new_column_name="claim_id",
        )
    # The journal's repair_record entries stay as the visible
    # trail, but the entity is retired: a restore can no longer
    # invert them (the records live on as claims now), so they
    # become visibility-only like the other two-party history.
    bind.execute(
        sa.text(
            "UPDATE change_journal SET restorable = :no"
            " WHERE entity_type = 'repair_record'"
        ),
        {"no": False},
    )
    inspector = sa.inspect(bind)
    if not inspector.has_table("repair_records"):
        return
    records = bind.execute(
        sa.text(
            "SELECT id, owner_id, item_kind, item_id, item_name, set_id,"
            " set_name, status, problem, sent_to, repair_cost,"
            " reported_at, completed_at, created_at, updated_at"
            " FROM repair_records ORDER BY created_at, id"
        )
    ).fetchall()
    if not records:
        op.drop_table("repair_records")
        return

    # The running claim-number ledger per (owner, year), seeded
    # from the claims that already exist so converted numbers
    # never collide with the (owner, year, seq) unique backstop.
    seqs: dict[tuple[str, int], int] = {}
    for owner_id, claim_year, number_seq in bind.execute(
        sa.text("SELECT owner_id, claim_year, number_seq FROM claims")
    ).fetchall():
        key = (str(owner_id), int(claim_year))
        seqs[key] = max(seqs.get(key, 0), int(number_seq or 0))

    converted: dict[str, str] = {}
    for row in records:
        (
            record_id,
            owner_id,
            item_kind,
            item_id,
            item_name,
            set_id,
            set_name,
            status,
            problem,
            sent_to,
            repair_cost,
            reported_at,
            completed_at,
            created_at,
            updated_at,
        ) = row
        created_at = _as_datetime(created_at)
        reported_at = _as_datetime(reported_at)
        completed_at = _as_datetime(completed_at)
        updated_at = _as_datetime(updated_at)
        year = int(created_at.year) if created_at is not None else 2026
        key = (str(owner_id), year)
        seqs[key] = seqs.get(key, 0) + 1
        claim_id = uuid.uuid4()
        converted[str(record_id)] = str(claim_id)
        bind.execute(
            sa.text(
                "INSERT INTO claims ("
                " id, owner_id, claim_number, claim_year, number_seq,"
                " kind, insurer_name, policy_number, dealer_company_id,"
                " dealer_name, agent_user_id, private_agent_id,"
                " manufacturer_case_number, reported_at, report_method,"
                " repair_sent_to, repair_cost, repair_completed_at,"
                " agent_name, agent_phone, agent_email, incident_type,"
                " incident_date, description, status,"
                " police_report_number, police_department,"
                " police_report_date, proof_of_loss_due,"
                " proof_of_loss_sent_at, depreciation_deadline,"
                " filed_at, closed_at, archived, archived_at,"
                " created_at, updated_at)"
                " VALUES ("
                " :id, :owner_id, :claim_number, :claim_year, :number_seq,"
                " 'warranty_repair', '', '', NULL,"
                " '', NULL, NULL,"
                " '', :reported_at, '',"
                " :repair_sent_to, :repair_cost, :repair_completed_at,"
                " '', '', '', 'damage',"
                " :incident_date, :description, :status,"
                " '', '',"
                " NULL, NULL,"
                " NULL, NULL,"
                " NULL, NULL, :archived, NULL,"
                " :created_at, :updated_at)"
            ),
            {
                # str ids: psycopg casts them to the UUID columns
                # on Postgres, and SQLite (the migration tests'
                # hand-built schemas) binds them natively.
                "id": str(claim_id),
                "owner_id": str(owner_id),
                "claim_number": f"CL-{year}-{seqs[key]:03d}",
                "claim_year": year,
                "number_seq": seqs[key],
                "reported_at": reported_at,
                "repair_sent_to": sent_to or "",
                "repair_cost": repair_cost,
                "repair_completed_at": completed_at,
                "incident_date": reported_at.date() if reported_at else None,
                "description": problem or "",
                "status": _STATUS_MAP.get(status, "reported"),
                "archived": False,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO claim_lines ("
                " id, owner_id, claim_id, target_kind, target_id,"
                " set_id, target_name, set_name, target_part_number,"
                " set_model_number, include_addons, value_basis,"
                " amount, include_in_package, created_at)"
                " VALUES ("
                " :id, :owner_id, :claim_id, :target_kind, :target_id,"
                " :set_id, :target_name, :set_name, '',"
                " '', :include_addons, 'entered',"
                " NULL, :include_in_package, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "owner_id": str(owner_id),
                "claim_id": str(claim_id),
                "target_kind": item_kind,
                "target_id": str(item_id),
                "set_id": str(set_id) if set_id is not None else None,
                "target_name": item_name or "",
                "set_name": set_name or "",
                "include_addons": False,
                "include_in_package": True,
                "created_at": created_at,
            },
        )

    # Re-point the dealer warranty requests whose repair records
    # were converted; the rest keep their (already dangling) ids.
    for old_id, new_id in converted.items():
        bind.execute(
            sa.text(
                "UPDATE warranty_service_requests SET claim_id = :new"
                " WHERE claim_id = :old"
            ),
            {"new": new_id, "old": old_id},
        )

    op.drop_table("repair_records")


def downgrade() -> None:
    # The table + column shapes return; converted claims stay
    # claims (the conversion is one-way, like every data move in
    # this chain — the repair facts remain readable on them).
    op.create_table(
        "repair_records",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("item_kind", sa.String(length=10), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "item_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("set_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "set_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="reported",
        ),
        sa.Column("problem", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "sent_to", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("repair_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "was_checked_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.alter_column(
        "warranty_service_requests",
        "claim_id",
        new_column_name="repair_record_id",
    )
    op.drop_column("claims", "repair_completed_at")
    op.drop_column("claims", "repair_cost")
    op.drop_column("claims", "repair_sent_to")
