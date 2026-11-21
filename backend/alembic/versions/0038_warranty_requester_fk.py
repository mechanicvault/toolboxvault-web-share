"""Dealer build fix (2026-10-20): drop the requester FK that
0037 shipped with.

warranty_service_requests.requester_id must be a PLAIN column
(the forum tombstone doctrine): the request survives its
requester's account deletion as a "Former member" record, and a
foreign key to users.id makes that user's row undeletable on
Postgres (the live smoke caught it: the requester's DELETE
/api/core/me 500'd on the constraint). 0037's source no longer
creates the FK; this migration removes it where 0037 already ran.

Revision ID: 0038_warranty_requester_fk
Revises: 0037_dealer_build
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_warranty_requester_fk"
down_revision: str | None = "0037_dealer_build"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _requester_fk_names(conn) -> list[str]:
    inspector = sa.inspect(conn)
    names = []
    for fk in inspector.get_foreign_keys("warranty_service_requests"):
        if fk.get("constrained_columns") == ["requester_id"]:
            if fk.get("name"):
                names.append(fk["name"])
    return names


def upgrade() -> None:
    conn = op.get_bind()
    names = _requester_fk_names(conn)
    if not names:
        return
    # batch mode: a plain DROP CONSTRAINT works on Postgres, and
    # SQLite (migration tests) rebuilds the table without it.
    with op.batch_alter_table("warranty_service_requests") as batch_op:
        for name in names:
            batch_op.drop_constraint(name, type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "warranty_service_requests_requester_id_fkey",
        "warranty_service_requests",
        "users",
        ["requester_id"],
        ["id"],
    )
