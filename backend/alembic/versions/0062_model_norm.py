"""Normalized model columns (scale fix, 2026-10-26).

Audit finding B9 (scale-proof code sweep): tools.model /
batteries.model are plain unindexed strings and there is NO
normalized-model column anywhere, so every consumer that narrows
by model number pays a per-row lower() scan (the catalog does
exactly that) and no SQL-side matching can use an index at all.

This migration adds `model_norm` to both tables — the comparison
form of the primary model (trim, collapse internal whitespace,
casefold: the importer's merge-dedupe rule, canonical copy in
tool_expansion.service.norm_model) — backfills it for existing
rows, and indexes it. Going forward the column is maintained by
mapper listeners in inventory/models.py on every ORM write, so
no write path can forget it.

It also indexes the Tool Expansion reports pair
(anchor_model, suggested_model): the kill-threshold read groups
by exactly that pair on every expansion read (F-11.6).

The backfill runs in Python with a frozen copy of the
normalization (migrations never import live app code — the rule
of the day the app changes must not rewrite history), so the
values are byte-identical to what the app computes.

Revision ID: 0062_model_norm
Revises: 0061_tool_expansion
Create Date: 2026-10-26
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "0062_model_norm"
down_revision = "0061_tool_expansion"
branch_labels = None
depends_on = None

_WHITESPACE = re.compile(r"\s+")


def _norm_model(value) -> str:
    """Frozen copy of the model-number comparison form."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", str(value).strip()).casefold()


def _backfill(table_name: str) -> None:
    bind = op.get_bind()
    table = sa.table(
        table_name,
        sa.column("id"),
        sa.column("model"),
        sa.column("model_norm"),
    )
    rows = bind.execute(sa.select(table.c.id, table.c.model)).all()
    for row_id, model in rows:
        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(model_norm=_norm_model(model))
        )


def upgrade() -> None:
    for table_name in ("tools", "batteries"):
        op.add_column(
            table_name,
            sa.Column(
                "model_norm",
                sa.String(200),
                nullable=False,
                server_default="",
            ),
        )
        _backfill(table_name)
        op.create_index(
            f"ix_{table_name}_model_norm", table_name, ["model_norm"]
        )
    op.create_index(
        "ix_tool_expansion_reports_pair",
        "tool_expansion_reports",
        ["anchor_model", "suggested_model"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_expansion_reports_pair",
        table_name="tool_expansion_reports",
    )
    for table_name in ("batteries", "tools"):
        op.drop_index(f"ix_{table_name}_model_norm", table_name=table_name)
        op.drop_column(table_name, "model_norm")
