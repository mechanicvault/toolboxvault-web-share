"""Maintenance module (2026-10-19): repairs, schedules, tool warranty.

Conversion of the app's broken/warranty/maintenance cluster (feature
map rows 30/32/34) WITHOUT its traps: the app embedded repair info
inside tool records and WIPED it when the item was marked fixed
(copying the cost into an auto-created claim first — the broken<=>
claim mirror, Risk #3). Here repair history is its own ledger and
marking fixed CLOSES a record; nothing is ever wiped, and nothing
claim-like is created (claims is a later module and will CONSUME
these records through the maintenance service).

SCHEMA:
- tools.warranty_months — tools gain the warranty term batteries
  already carry; status stays COMPUTED (one shared function in the
  inventory service reads purchase_date + warranty_months for both
  kinds — the app had TWO warranty-expiry values and only the nested
  one worked, Risk #7; here there is exactly one source).
- repair_state / repair_problem on tools, batteries, set_pieces:
  the item's CURRENT standing (in_service | broken | in_repair) and
  the current problem text. The standing lives on the item record —
  like the dealer tag — while the HISTORY lives in repair_records.
  A set PIECE carries its own standing, distinct from its presence
  status (present/missing/sold/removed): one socket of a set can be
  broken while the set works.
- repair_records — one row per break->fix cycle, never deleted by
  state transitions (state flow lives in `status`: reported ->
  in_repair / awaiting_parts -> completed). item_id is deliberately
  NOT a foreign key (the borrowing ledger's doctrine: the record
  outlives the item; item_name is snapshotted).
- maintenance_schedules + maintenance_log_entries — per-item
  schedules (calibration/service/inspection/other) with an interval
  and/or a fixed due date; the log is each schedule's service
  history (date, cost, technician — the app's embedded shape, as
  rows). Logging an entry advances the schedule's last_done_at.

Revision ID: 0020_maintenance
Revises: 0019_import_sessions
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_maintenance"
down_revision: str | None = "0019_import_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _repair_columns(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "repair_state",
            sa.String(length=20),
            nullable=False,
            server_default="in_service",
        ),
    )
    op.add_column(
        table,
        sa.Column(
            "repair_problem", sa.Text(), nullable=False, server_default=""
        ),
    )


def upgrade() -> None:
    # Tool warranty term (batteries already carry theirs).
    op.add_column(
        "tools", sa.Column("warranty_months", sa.Integer(), nullable=True)
    )
    # Current repair standing on every repairable record kind.
    _repair_columns("tools")
    _repair_columns("batteries")
    _repair_columns("set_pieces")

    op.create_table(
        "repair_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_kind", sa.String(length=10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "item_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "set_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "set_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="reported",
        ),
        sa.Column(
            "problem", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "sent_to", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("repair_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "was_checked_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_repair_records_owner_id"), "repair_records", ["owner_id"]
    )
    op.create_index(
        op.f("ix_repair_records_item_id"), "repair_records", ["item_id"]
    )

    op.create_table(
        "maintenance_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_kind", sa.String(length=10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "item_name", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
            server_default="service",
        ),
        sa.Column(
            "label", sa.String(length=300), nullable=False, server_default=""
        ),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("last_done_at", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_schedules_owner_id"),
        "maintenance_schedules",
        ["owner_id"],
    )
    op.create_index(
        op.f("ix_maintenance_schedules_item_id"),
        "maintenance_schedules",
        ["item_id"],
    )

    op.create_table(
        "maintenance_log_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("done_date", sa.Date(), nullable=False),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "technician",
            sa.String(length=300),
            nullable=False,
            server_default="",
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["maintenance_schedules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_log_entries_owner_id"),
        "maintenance_log_entries",
        ["owner_id"],
    )
    op.create_index(
        op.f("ix_maintenance_log_entries_schedule_id"),
        "maintenance_log_entries",
        ["schedule_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_maintenance_log_entries_schedule_id"),
        table_name="maintenance_log_entries",
    )
    op.drop_index(
        op.f("ix_maintenance_log_entries_owner_id"),
        table_name="maintenance_log_entries",
    )
    op.drop_table("maintenance_log_entries")
    op.drop_index(
        op.f("ix_maintenance_schedules_item_id"),
        table_name="maintenance_schedules",
    )
    op.drop_index(
        op.f("ix_maintenance_schedules_owner_id"),
        table_name="maintenance_schedules",
    )
    op.drop_table("maintenance_schedules")
    op.drop_index(op.f("ix_repair_records_item_id"), table_name="repair_records")
    op.drop_index(op.f("ix_repair_records_owner_id"), table_name="repair_records")
    op.drop_table("repair_records")
    for table in ("set_pieces", "batteries", "tools"):
        op.drop_column(table, "repair_problem")
        op.drop_column(table, "repair_state")
    op.drop_column("tools", "warranty_months")
