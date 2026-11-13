"""Claim numbers: the race backstop (hardening 2026-10-19).

Claim numbers are assigned read-max-then-insert in the claims
service. Sequential requests can never collide, but two creates
in flight at once (a double-submit that actually overlaps) could
read the same max and both try to commit the same
(owner_id, claim_year, number_seq) — duplicate numbers an owner
would quote to an adjuster. This adds the unique constraint the
borrowing module's one-active-lend index already models: the
service pre-assigns for a friendly flow, the database guarantees
the invariant, and the service retries the loser with the next
number.

Production's claims table was empty when this was written (0 rows,
verified 2026-10-19), so the constraint applies with no dedupe
step; on any database that somehow held duplicates, CREATE would
fail loudly rather than silently pick winners — the right failure.

Revision ID: 0024_claim_number_unique
Revises: 0023_checkout_seq
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_claim_number_unique"
down_revision: str | None = "0023_checkout_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "uq_claims_owner_year_seq"


def upgrade() -> None:
    # batch mode: SQLite can't ALTER a constraint in place (the
    # migration tests run there); on Postgres batch is a passthrough.
    with op.batch_alter_table("claims") as batch_op:
        batch_op.create_unique_constraint(
            _CONSTRAINT, ["owner_id", "claim_year", "number_seq"]
        )


def downgrade() -> None:
    with op.batch_alter_table("claims") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="unique")
