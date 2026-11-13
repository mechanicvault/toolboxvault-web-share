"""0097: the feedback boards join the downloads level's
standing definition (boards + tickets for every registered
user, owner order 2026-11-09).

ONE cell moves: module_tier_access (feedback, downloads) goes
ON, next to prints + support from 0096. Ryan's ruling is that
posting on the Bug Reports / Feature Requests boards, commenting
and flagging there, and submitting support tickets are part of
what being registered IS — every registered seat already had
the boards except the downloads level 0096 seeded, whose
feedback cell it left dark.

Why a migration and not an admin's tier flip: the flip is a
RELEASE EVENT by design — module_routes' tier handler fires
module_release (the nav NEW badge, the scoped announcement,
the onboarding "notified" rows). This change is baseline
plumbing for the level, like support in 0096, not a release,
so it lands as data and the release machinery never runs:
no badge, no announcement, no wizard rows. Nothing else in
the switchboard moves — every other cell keeps exactly the
value 0096 (or a later operator write) gave it.

The write is an upsert, not a bare update: for the downloads
rung a missing cell reads OFF (the rung reads NO fallback,
0096's doctrine), so an update-only migration could silently
leave the boards dark on a database whose feedback cell was
never seeded. The upgrade flips the cell where it sits, writes
it where it is absent, and leaves an already-lit cell exactly
as it found it — idempotent on every shape.

Downgrade restores the 0096 state: the cell reads OFF again
(set False where present; a cell the upgrade had to insert
stays behind as an explicit OFF, which is the same read —
0096's own downgrade leaves its materialized cells the same
way).

Table-level ops only — no model __table__ objects, no
hand-written SQL (the 0084/0089/0090/0096 posture). The one
touched table's shape was verified against a fresh production
schema dump taken for this lane (production at 0096:
module_tier_access = id uuid / module_id varchar(64) / tier
varchar(32) / enabled boolean / updated_at timestamptz, with
uq_module_tier_access_cell on (module_id, tier)).
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0097_feedback_for_downloads"
down_revision = "0096_downloads_tier"
branch_labels = None
depends_on = None

_MODULE_ID = "feedback"
_TIER = "downloads"


def _tier_access_table() -> sa.Table:
    return sa.table(
        "module_tier_access",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("module_id", sa.String(64)),
        sa.column("tier", sa.String(32)),
        sa.column("enabled", sa.Boolean()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _cell(bind, tier_access) -> bool | None:
    """The stored value of the (feedback, downloads) cell, or
    None where the row is absent."""
    row = bind.execute(
        sa.select(tier_access.c.enabled).where(
            tier_access.c.module_id == _MODULE_ID,
            tier_access.c.tier == _TIER,
        )
    ).first()
    return None if row is None else bool(row.enabled)


def upgrade() -> None:
    tier_access = _tier_access_table()
    bind = op.get_bind()
    current = _cell(bind, tier_access)
    if current is True:
        return  # already lit — never rewrite an existing cell
    if current is False:
        op.execute(
            tier_access.update()
            .where(
                tier_access.c.module_id == _MODULE_ID,
                tier_access.c.tier == _TIER,
            )
            .values(enabled=True, updated_at=sa.func.now())
        )
        return
    op.bulk_insert(
        tier_access,
        [
            {
                "id": uuid.uuid4(),
                "module_id": _MODULE_ID,
                "tier": _TIER,
                "enabled": True,
            }
        ],
    )


def downgrade() -> None:
    tier_access = _tier_access_table()
    bind = op.get_bind()
    if _cell(bind, tier_access) is None:
        return  # nothing seeded — the 0096 read is already OFF
    op.execute(
        tier_access.update()
        .where(
            tier_access.c.module_id == _MODULE_ID,
            tier_access.c.tier == _TIER,
        )
        .values(enabled=False, updated_at=sa.func.now())
    )
