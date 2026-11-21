"""0101: conversion requests (downloads level → full access,
owner order 2026-11-10).

One new table:

- conversion_requests — a downloads-level account's ONE request
  for full access, the no-code path beside the gate code. One
  row per account, EVER: the unique user_id is the owner's
  anti-spam rule at the schema level (a denial does not free
  the slot — the code door stays the route after a no; an
  approval consumes it — the conversion ends the account's
  life on the rung). status pending → approved | denied,
  decided by a god-tier account alone; the decider is
  snapshotted (id + email) so the record stays readable.

Plain table creation from explicit definitions — no model
__table__ DDL (the 0084/0091/0092/0093 posture). Bare-safe:
this file imports alembic + sqlalchemy only, and names its
table and columns literally. Column definitions mirror
core/models.py ConversionRequest, written against the users
table's known shape (id uuid PK — migration 0001's table,
verified across every later migration that references it).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0101_conversion_requests"
down_revision = "0100_home_stats_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversion_requests",
        sa.Column("id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_by_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "decided_by_email",
            sa.String(length=320),
            server_default="",
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_conversion_requests_user_id",
        "conversion_requests",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversion_requests_user_id", table_name="conversion_requests"
    )
    op.drop_table("conversion_requests")
