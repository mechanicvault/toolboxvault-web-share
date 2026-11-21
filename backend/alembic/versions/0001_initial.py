"""Initial schema: users, tools, field_definitions, account_number_seq,
refresh_tokens, email_verification_tokens.

Also creates the tools search-vector trigger (full-text search) and its GIN
index. Reviewed by eye against the SQLAlchemy models; needs a live
`alembic upgrade head` on the Hetzner box before it is trusted.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEARCH_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION tools_search_vector_update() RETURNS trigger AS $$
DECLARE
    custom_text text := '';
    r record;
BEGIN
    -- Searchable custom-field values (plus their labels) join the vector.
    -- Definitions marked searchable=false are excluded; orphan keys
    -- (definition deleted without scrub) are still searchable by value.
    FOR r IN
        SELECT COALESCE(fd.label, '') AS label, v.value AS value
        FROM jsonb_each_text(COALESCE(NEW.custom_data, '{}'::jsonb)) AS v(key, value)
        LEFT JOIN field_definitions fd ON fd.id::text = v.key
        WHERE fd.id IS NULL OR fd.searchable
    LOOP
        custom_text := custom_text || ' ' || r.label || ' ' || r.value;
    END LOOP;

    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.brand, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.model, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.serial_number, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.notes, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.condition, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.location, '')), 'D') ||
        setweight(to_tsvector('english', custom_text), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

SEARCH_TRIGGER_SQL = """
CREATE TRIGGER tools_search_vector_trigger
BEFORE INSERT OR UPDATE ON tools
FOR EACH ROW EXECUTE FUNCTION tools_search_vector_update();
"""


def upgrade() -> None:
    # Collision-free account numbers: nextval() is atomic under concurrency.
    op.execute("CREATE SEQUENCE IF NOT EXISTS account_number_seq START WITH 1")

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_number", sa.String(16), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "password_hash", sa.String(255), nullable=False, server_default=""
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "tools",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("brand", sa.String(200), nullable=False, server_default=""),
        sa.Column("model", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "serial_number", sa.String(200), nullable=False, server_default=""
        ),
        sa.Column("condition", sa.String(50), nullable=False, server_default=""),
        sa.Column("category", sa.String(200), nullable=False, server_default=""),
        sa.Column("location", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("purchase_price", sa.Numeric(12, 2)),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("replacement_cost", sa.Numeric(12, 2)),
        sa.Column("msrp", sa.Numeric(12, 2)),
        sa.Column(
            "custom_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Maintained by the trigger below; never written by the app.
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "field_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Definitions are per-user (owner-scoped): see models.FieldDefinition.
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "item_type", sa.String(50), nullable=False, server_default="tool"
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column(
            "field_type", sa.String(20), nullable=False, server_default="text"
        ),
        sa.Column(
            "required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "searchable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "owner_id", "item_type", "name", name="uq_field_definitions_type_name"
        ),
    )
    op.create_index(
        "ix_field_definitions_owner_id", "field_definitions", ["owner_id"]
    )
    # Every tools query filters by owner — without this index each one is a
    # sequential scan over all users' tools (blueprint §12 budget).
    op.create_index("ix_tools_owner_id", "tools", ["owner_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        # SHA-256 hex of the token; the plain token is never stored.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "email_verification_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id",
        "email_verification_tokens",
        ["user_id"],
    )

    op.execute(sa.text(SEARCH_FUNCTION_SQL))
    op.execute(sa.text(SEARCH_TRIGGER_SQL))
    op.execute(
        "CREATE INDEX ix_tools_search_vector ON tools USING gin (search_vector)"
    )
    # Fire the trigger once for any pre-existing rows (no-op on a fresh DB).
    op.execute("UPDATE tools SET updated_at = updated_at")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tools_search_vector_trigger ON tools")
    op.execute("DROP FUNCTION IF EXISTS tools_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS ix_tools_search_vector")
    op.drop_table("email_verification_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("field_definitions")
    op.drop_table("tools")
    op.drop_table("users")
    op.execute("DROP SEQUENCE IF EXISTS account_number_seq")
