"""Claims separation: Disaster Claims module seed + per-kind
claim numbers (owner order, 2026-11-04; build, 2026-11-05).

The insurance side of claims becomes its own module,
disaster_claims, with its own section, switch and numbering:

- The module-control rows for 'disaster_claims' MIRROR whatever
  'claims' carries today — global state, group access, tier
  access, and every user's personal toggle — so nobody loses or
  gains access in the split: disaster claims reach exactly the
  users insurance claims reached as part of claims. (Where
  claims has no row, the service fallback applies identically to
  both modules.)
- The claims table's number sequence goes per-KIND: the unique
  constraint on (owner, year, seq) becomes (owner, year, kind,
  seq), so a new disaster claim mints DC-<year>-001 without
  colliding with the same owner's warranty CL-<year>-001.
  Existing rows keep their stored numbers untouched — history
  never renumbers.

Reversible: the downgrade drops the module rows and restores
the three-column constraint (safe when no owner holds the same
seq in both kinds for the same year — the pre-separation state
this migration started from).

Revision ID: 0076_claims_separation
Revises: 0075_agent_records_stage1
Create Date: 2026-11-05
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0076_claims_separation"
down_revision = "0075_agent_records_stage1"
branch_labels = None
depends_on = None

_CLAIMS = "claims"
_DISASTER = "disaster_claims"


def _mirror_module_rows() -> None:
    bind = op.get_bind()

    state = bind.execute(
        sa.text(
            "SELECT globally_enabled FROM module_state WHERE module_id = :m"
        ),
        {"m": _CLAIMS},
    ).first()
    if state is not None:
        bind.execute(
            sa.text(
                "INSERT INTO module_state (module_id, globally_enabled) "
                "VALUES (:m, :enabled)"
            ),
            {"m": _DISASTER, "enabled": state[0]},
        )

    access = bind.execute(
        sa.text(
            "SELECT account_group, enabled FROM module_access "
            "WHERE module_id = :m"
        ),
        {"m": _CLAIMS},
    ).all()
    if access:
        op.bulk_insert(
            sa.table(
                "module_access",
                sa.column("id", sa.Uuid),
                sa.column("module_id", sa.String),
                sa.column("account_group", sa.String),
                sa.column("enabled", sa.Boolean),
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "module_id": _DISASTER,
                    "account_group": account_group,
                    "enabled": enabled,
                }
                for account_group, enabled in access
            ],
        )

    tiers = bind.execute(
        sa.text(
            "SELECT tier, enabled FROM module_tier_access "
            "WHERE module_id = :m"
        ),
        {"m": _CLAIMS},
    ).all()
    if tiers:
        op.bulk_insert(
            sa.table(
                "module_tier_access",
                sa.column("id", sa.Uuid),
                sa.column("module_id", sa.String),
                sa.column("tier", sa.String),
                sa.column("enabled", sa.Boolean),
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "module_id": _DISASTER,
                    "tier": tier,
                    "enabled": enabled,
                }
                for tier, enabled in tiers
            ],
        )

    prefs = bind.execute(
        sa.text(
            "SELECT user_id, enabled FROM user_module_prefs "
            "WHERE module_id = :m"
        ),
        {"m": _CLAIMS},
    ).all()
    if prefs:
        op.bulk_insert(
            sa.table(
                "user_module_prefs",
                sa.column("id", sa.Uuid),
                sa.column("user_id", sa.Uuid),
                sa.column("module_id", sa.String),
                sa.column("enabled", sa.Boolean),
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "module_id": _DISASTER,
                    "enabled": enabled,
                }
                for user_id, enabled in prefs
            ],
        )


def upgrade() -> None:
    with op.batch_alter_table("claims") as batch:
        batch.drop_constraint("uq_claims_owner_year_seq", type_="unique")
        batch.create_unique_constraint(
            "uq_claims_owner_year_kind_seq",
            ["owner_id", "claim_year", "kind", "number_seq"],
        )
    _mirror_module_rows()


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "user_module_prefs",
        "module_tier_access",
        "module_access",
        "module_state",
    ):
        bind.execute(
            sa.text(f"DELETE FROM {table_name} WHERE module_id = :m"),
            {"m": _DISASTER},
        )
    with op.batch_alter_table("claims") as batch:
        batch.drop_constraint("uq_claims_owner_year_kind_seq", type_="unique")
        batch.create_unique_constraint(
            "uq_claims_owner_year_seq",
            ["owner_id", "claim_year", "number_seq"],
        )
