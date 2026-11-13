"""Home stats-only reset (new Home dashboard, owner design 2026-11-10).

The new Home system (design doc §3.10) starts EVERY account from
the one stats widget — predefined, preloaded, and removable like
any other widget afterwards. This migration performs that
one-time reset on the stored layouts: for every row of
user_page_layouts with page_key 'home', the blocks list becomes
exactly the stats widget's entry, [{"key": "overview",
"visible": true}] — the same stored key the Overview block has
always used, so the downloads level (whose assembly seats its
own downloads-flavored stats body under the same key) resets to
its own stats widget with no special case here.

Two protections, by the owner's order:

- The GOD account is never touched: rows whose owner holds
  tier 'god' keep their layout exactly as stored.
- The Home side panel's pseudo-entry ({"key": "panel", ...})
  rides in the same blocks list but is NOT a box — it is
  preserved verbatim, in place, after the stats entry. Only the
  box list is replaced.

The transform is naturally idempotent (resetting an
already-reset row produces the same row), so a re-run can never
compound. The downgrade is a deliberate no-op: a reset cannot
un-happen — the arrangements it replaced are gone, and inventing
a "restore" would fabricate layouts nobody chose.

Bare-safe by construction (the standing migration gate): this
file imports alembic + sqlalchemy only, names its tables and
columns literally, and builds no scratch state from ORM models.
Columns verified against the models that own them:
user_page_layouts(id, user_id, page_key, blocks) —
core/models.py UserPageLayout; users(id, tier) — core/models.py
User (tier added by migration 0067).
"""

import sqlalchemy as sa
from alembic import op

revision = "0100_home_stats_reset"
down_revision = "0099_prints_visitor_counter"
branch_labels = None
depends_on = None

_STATS_ENTRY = {"key": "overview", "visible": True}
_PANEL_KEY = "panel"


def _reset_blocks(blocks: object) -> list:
    """One row's blocks after the reset: the stats entry first,
    then the panel pseudo-entry verbatim when one exists."""
    panels = []
    if isinstance(blocks, list):
        for entry in blocks:
            if isinstance(entry, dict) and entry.get("key") == _PANEL_KEY:
                panels.append(entry)
    return [dict(_STATS_ENTRY), *panels]


def _norm_id(value: object) -> str:
    """UUIDs arrive as uuid objects on Postgres and as undashed
    hex text on SQLite — compare them in one canonical shape."""
    return str(value).replace("-", "").lower()


def upgrade() -> None:
    bind = op.get_bind()
    layouts = sa.table(
        "user_page_layouts",
        sa.column("id"),
        sa.column("user_id"),
        sa.column("page_key"),
        sa.column("blocks", sa.JSON),
    )
    users = sa.table(
        "users",
        sa.column("id"),
        sa.column("tier"),
    )
    god_ids = {
        _norm_id(row[0])
        for row in bind.execute(
            sa.select(users.c.id).where(users.c.tier == "god")
        )
    }
    rows = bind.execute(
        sa.select(layouts.c.id, layouts.c.user_id, layouts.c.blocks).where(
            layouts.c.page_key == "home"
        )
    ).fetchall()
    for row_id, user_id, blocks in rows:
        if _norm_id(user_id) in god_ids:
            continue
        new_blocks = _reset_blocks(blocks)
        if new_blocks != blocks:
            bind.execute(
                layouts.update()
                .where(layouts.c.id == row_id)
                .values(blocks=new_blocks)
            )


def downgrade() -> None:
    # A one-time reset cannot be reversed: the layouts it
    # replaced no longer exist anywhere to restore from.
    pass
