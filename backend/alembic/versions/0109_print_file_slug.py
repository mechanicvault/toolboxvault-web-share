"""Print files — the public URL slug (sheet row 99).

Every public print file page lived at /3dprints/<uuid> — a
bare identifier, not a slug. The SEO plan's rule: public URLs
are short plain words with hyphens, and any URL that changes
keeps working through a redirect. Print files gain `slug`:
the title in slug form ("impact-swivel-mount"), unique across
the shelf, assigned once and never rewritten by later title
edits, so a link shared anywhere keeps landing on the file.
The old id URLs keep resolving (the API resolves both keys
and the page canonicalizes to the slug URL), which is the
redirect half of the rule.

Existing rows are backfilled oldest-first in (created_at, id)
order; collisions take -2, -3, ... suffixes in that order.
The slugify here is a self-contained copy of the service's —
migrations never import app code. The column lands NULLABLE
with a unique index: a slug names exactly one file, and NULL
marks a not-yet-backfilled row, which every read path treats
as "use the id".

DDL names (print_files: id, title, created_at) were verified
against the live production schema before this was written,
per the standing migration rule.

Revision ID: 0109_print_file_slug
Revises: 0108_truck_account_number
Create Date: 2026-11-18
"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0109_print_file_slug"
down_revision = "0108_truck_account_number"
branch_labels = None
depends_on = None


def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > 80:
        text = text[:80].rstrip("-")
    return text or "print-file"


def upgrade() -> None:
    op.add_column(
        "print_files",
        sa.Column("slug", sa.String(length=180), nullable=True),
    )
    op.create_index(
        "ix_print_files_slug", "print_files", ["slug"], unique=True
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, title FROM print_files "
            "WHERE slug IS NULL ORDER BY created_at, id"
        )
    ).fetchall()
    taken: set[str] = set()
    for row_id, title in rows:
        base = _slugify(title)
        slug = base
        n = 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1
        taken.add(slug)
        bind.execute(
            sa.text("UPDATE print_files SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row_id},
        )


def downgrade() -> None:
    op.drop_index("ix_print_files_slug", table_name="print_files")
    op.drop_column("print_files", "slug")
