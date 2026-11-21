"""Item structure package: fields, sets, tags, dealers module.

Owner specs, 2026-10-18 (app video audit + sets model + dealer
model + module doctrine):

TOOLS/BATTERIES — quantity (money is PER UNIT: the app's "Price
Each" — every total multiplies by quantity; existing rows default
to 1 so their values are unchanged), size (tools), multi-value
model/serial lists (the single columns stay as the synced PRIMARY;
existing values backfill into the lists), consumable (tools),
dealer tag FKs.

SETS — a set IS a tool (is_set) + set_pieces (core pieces have NO
price, ever — a CHECK constraint enforces it; addons carry prices);
standalone tools attach into a set via tools.attached_to_set_id
(SET NULL: the tool survives the set). Set pieces are not assets:
no count, no top-level list presence.

TAGS — per-user vocabulary (tags) + item links (item_tags).

DEALERS MODULE — dealer_companies (directory rows owner_id NULL +
private rows), private_agents, preferred_agents (exactly one of
platform agent / private record, CHECK-enforced). The directory is
SEEDED with the four majors using ONLY contact data published on
their official websites (verified 2026-10-18; each fact's source is
in the company notes where it matters — anything not publicly
listed, e.g. Snap-on US billing, is simply absent, never invented).

CROSS-MODULE — checkouts.group_id (set lend bundles: sibling rows
share one group), shared_items.include_addons (tier sharing's
stored set choice), peer_set_choices (peer sharing's stored set
choice; absence = include, peer's default).

SEARCH — the tools trigger function learns size + ALL model/serial
list values (weight B like the primaries); existing rows re-fire
the trigger to backfill vectors.

Revision ID: 0016_item_structure
Revises: 0015_borrowing
Create Date: 2026-10-18
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_item_structure"
down_revision: str | None = "0015_borrowing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TOOLS_SEARCH_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION tools_search_vector_update() RETURNS trigger AS $$
DECLARE
    custom_text text := '';
    list_text text := '';
    r record;
BEGIN
    -- Searchable custom-field values (plus their labels) join the vector.
    FOR r IN
        SELECT COALESCE(fd.label, '') AS label, v.value AS value
        FROM jsonb_each_text(COALESCE(NEW.custom_data, '{}'::jsonb)) AS v(key, value)
        LEFT JOIN field_definitions fd ON fd.id::text = v.key
        WHERE fd.id IS NULL OR fd.searchable
    LOOP
        custom_text := custom_text || ' ' || r.label || ' ' || r.value;
    END LOOP;

    -- Multi-value model/serial numbers: EVERY value is searchable,
    -- not just the primary column.
    SELECT coalesce(string_agg(value, ' '), '')
      INTO list_text
      FROM (
          SELECT jsonb_array_elements_text(COALESCE(NEW.model_numbers, '[]'::jsonb)) AS value
          UNION ALL
          SELECT jsonb_array_elements_text(COALESCE(NEW.serial_numbers, '[]'::jsonb)) AS value
      ) AS entries;

    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.brand, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.model, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.serial_number, '')), 'B') ||
        setweight(to_tsvector('english', list_text), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.size, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.notes, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.condition, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'D') ||
        setweight(to_tsvector('english', coalesce(NEW.location, '')), 'D') ||
        setweight(to_tsvector('english', custom_text), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# The 0001 original, restored on downgrade.
TOOLS_SEARCH_FUNCTION_SQL_ORIGINAL = """
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


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    # -- dealers module (first: item FKs reference dealer_companies) --------
    op.create_table(
        "dealer_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("website", sa.String(500), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "phones", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_directory", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
    )
    op.create_index("ix_dealer_companies_owner_id", "dealer_companies", ["owner_id"])

    op.create_table(
        "private_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("phone", sa.String(100), nullable=False, server_default=""),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        *_timestamps(),
    )
    op.create_index("ix_private_agents_owner_id", "private_agents", ["owner_id"])
    op.create_index("ix_private_agents_company_id", "private_agents", ["company_id"])

    op.create_table(
        "preferred_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dealer_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.Column(
            "private_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("private_agents.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(agent_user_id IS NULL) <> (private_agent_id IS NULL)",
            name="ck_preferred_agents_exactly_one_agent",
        ),
        sa.UniqueConstraint(
            "user_id", "company_id", "agent_user_id",
            name="uq_preferred_agents_platform_agent",
        ),
        sa.UniqueConstraint(
            "user_id", "company_id", "private_agent_id",
            name="uq_preferred_agents_private_agent",
        ),
    )
    op.create_index("ix_preferred_agents_user_id", "preferred_agents", ["user_id"])
    op.create_index("ix_preferred_agents_company_id", "preferred_agents", ["company_id"])

    # Directory seed — ONLY data published on the companies' official
    # websites (verified 2026-10-18). Department numbers that are not
    # publicly listed are absent by design.
    companies = sa.table(
        "dealer_companies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("owner_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
        sa.column("website", sa.String),
        sa.column("address", sa.Text),
        sa.column("phones", postgresql.JSONB),
        sa.column("notes", sa.Text),
        sa.column("is_directory", sa.Boolean),
    )
    op.bulk_insert(
        companies,
        [
            {
                "id": uuid.uuid4(),
                "owner_id": None,
                "name": "Snap-on Incorporated",
                "email": "",
                "website": "https://www.snapon.com",
                "address": "2801 80th Street, Kenosha, Wisconsin 53143",
                "phones": [
                    {"label": "Corporate Office", "number": "877-762-7664"},
                    {"label": "Diagnostics Support", "number": "1-800-424-7226"},
                ],
                "notes": (
                    "Corporate contacts from snapon.com (Contact Us page). "
                    "Diagnostics support email: diagnostics_support@snapon.com. "
                    "US billing/credit phone is not publicly listed on snapon.com."
                ),
                "is_directory": True,
            },
            {
                "id": uuid.uuid4(),
                "owner_id": None,
                "name": "Matco Tools",
                "email": "customerservice@matcotools.com",
                "website": "https://www.matcotools.com",
                "address": "4403 Allen Road, Stow, OH 44224",
                "phones": [
                    {"label": "Customer Service", "number": "866-289-8665"},
                ],
                "notes": (
                    "Customer service (866-BUY-TOOLS) hours Mon-Fri 8:00AM-6:30PM EST, "
                    "per matcotools.com. Billing/financial services phone is not "
                    "publicly listed."
                ),
                "is_directory": True,
            },
            {
                "id": uuid.uuid4(),
                "owner_id": None,
                "name": "Mac Tools",
                "email": "MTCS@sbdinc.com",
                "website": "https://www.mactools.com",
                "address": "5195 Blazer Parkway, Dublin, OH 43017",
                "phones": [
                    {"label": "Customer Service", "number": "1-800-622-8665"},
                ],
                "notes": (
                    "US & Canada contact from mactools.com/pages/contact-us "
                    "(1-800-MAC-TOOLS). Separate technical service / billing "
                    "numbers are not publicly listed."
                ),
                "is_directory": True,
            },
            {
                "id": uuid.uuid4(),
                "owner_id": None,
                "name": "Cornwell Quality Tools",
                "email": "custserv@cornwelltools.com",
                "website": "https://www.cornwelltools.com",
                "address": "667 Seville Road, Wadsworth, OH 44281",
                "phones": [
                    {"label": "General", "number": "1-800-321-8356"},
                ],
                "notes": (
                    "Contacts from cornwelltools.com/contact-us: warranty inquiries "
                    "custserv@cornwelltools.com, credit inquiries "
                    "techcredit@cornwelltools.com, other inquiries "
                    "salesadmin@cornwelltools.com. Customer service by text/SMS: "
                    "(330) 665-0274. The 1-800 number appears unlabeled in "
                    "Cornwell's official catalog; no department-labeled phone is "
                    "published on their site."
                ),
                "is_directory": True,
            },
        ],
    )

    # -- tools: new fields -----------------------------------------------------
    op.add_column(
        "tools",
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "tools", sa.Column("size", sa.String(200), nullable=False, server_default="")
    )
    op.add_column(
        "tools",
        sa.Column(
            "model_numbers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "tools",
        sa.Column(
            "serial_numbers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "tools",
        sa.Column("consumable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tools",
        sa.Column("is_set", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tools", sa.Column("attached_to_set_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column(
        "tools", sa.Column("dealer_company_id", postgresql.UUID(as_uuid=True))
    )
    # Batch mode: SQLite (the migration-test dialect) cannot ALTER a
    # foreign key into an existing table; Postgres renders the same
    # operations as plain ALTERs.
    with op.batch_alter_table("tools") as batch_op:
        batch_op.create_foreign_key(
            "fk_tools_attached_to_set_id", "tools", ["attached_to_set_id"], ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_tools_dealer_company_id", "dealer_companies",
            ["dealer_company_id"], ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_tools_attached_to_set_id", "tools", ["attached_to_set_id"])
    op.create_index("ix_tools_dealer_company_id", "tools", ["dealer_company_id"])
    # Backfill the multi-value lists from the primary columns
    # (jsonb helpers are Postgres-only; the SQLite migration test
    # exercises the DDL, production runs Postgres).
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "UPDATE tools SET model_numbers = jsonb_build_array(model) "
            "WHERE model <> ''"
        )
        op.execute(
            "UPDATE tools SET serial_numbers = jsonb_build_array(serial_number) "
            "WHERE serial_number <> ''"
        )

    # -- batteries: quantity + dealer tag ---------------------------------------
    op.add_column(
        "batteries",
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "batteries", sa.Column("dealer_company_id", postgresql.UUID(as_uuid=True))
    )
    with op.batch_alter_table("batteries") as batch_op:
        batch_op.create_foreign_key(
            "fk_batteries_dealer_company_id", "dealer_companies",
            ["dealer_company_id"], ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_batteries_dealer_company_id", "batteries", ["dealer_company_id"])

    # -- set pieces ---------------------------------------------------------------
    op.create_table(
        "set_pieces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(10), nullable=False, server_default="core"),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("part_number", sa.String(200), nullable=False, server_default=""),
        sa.Column("serial_number", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="present"),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "kind = 'addon' OR price IS NULL", name="ck_set_pieces_core_has_no_price"
        ),
    )
    op.create_index("ix_set_pieces_set_id", "set_pieces", ["set_id"])
    op.create_index("ix_set_pieces_owner_id", "set_pieces", ["owner_id"])

    # -- tags -----------------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(30), nullable=False, server_default="amber"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_id", "name", name="uq_tags_owner_name"),
    )
    op.create_index("ix_tags_owner_id", "tags", ["owner_id"])

    op.create_table(
        "item_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("item_kind", sa.String(10), nullable=False, server_default="tool"),
        sa.Column(
            "tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "battery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batteries.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_item_tags_owner_id", "item_tags", ["owner_id"])
    op.create_index("ix_item_tags_tool_id", "item_tags", ["tool_id"])
    op.create_index("ix_item_tags_battery_id", "item_tags", ["battery_id"])
    op.create_index("ix_item_tags_tag_id", "item_tags", ["tag_id"])

    # -- cross-module columns ---------------------------------------------------------
    op.add_column("checkouts", sa.Column("group_id", postgresql.UUID(as_uuid=True)))
    op.create_index("ix_checkouts_group_id", "checkouts", ["group_id"])

    op.add_column(
        "shared_items",
        sa.Column(
            "include_addons", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    op.create_table(
        "peer_set_choices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "set_tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "include_addons", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamps(),
        sa.UniqueConstraint("owner_id", "set_tool_id", name="uq_peer_set_choice"),
    )
    op.create_index("ix_peer_set_choices_owner_id", "peer_set_choices", ["owner_id"])
    op.create_index(
        "ix_peer_set_choices_set_tool_id", "peer_set_choices", ["set_tool_id"]
    )

    # -- search: size + all list values join the tools vector --------------------------
    if op.get_bind().dialect.name == "postgresql":
        op.execute(TOOLS_SEARCH_FUNCTION_SQL)
        # Re-fire the trigger on existing rows so vectors backfill.
        op.execute("UPDATE tools SET name = name")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(TOOLS_SEARCH_FUNCTION_SQL_ORIGINAL)
        op.execute("UPDATE tools SET name = name")

    op.drop_index("ix_peer_set_choices_set_tool_id", table_name="peer_set_choices")
    op.drop_index("ix_peer_set_choices_owner_id", table_name="peer_set_choices")
    op.drop_table("peer_set_choices")

    op.drop_column("shared_items", "include_addons")

    op.drop_index("ix_checkouts_group_id", table_name="checkouts")
    op.drop_column("checkouts", "group_id")

    op.drop_table("item_tags")
    op.drop_table("tags")
    op.drop_table("set_pieces")

    op.drop_index("ix_batteries_dealer_company_id", table_name="batteries")
    with op.batch_alter_table("batteries") as batch_op:
        batch_op.drop_constraint(
            "fk_batteries_dealer_company_id", type_="foreignkey"
        )
    op.drop_column("batteries", "dealer_company_id")
    op.drop_column("batteries", "quantity")

    op.drop_index("ix_tools_dealer_company_id", table_name="tools")
    op.drop_index("ix_tools_attached_to_set_id", table_name="tools")
    with op.batch_alter_table("tools") as batch_op:
        batch_op.drop_constraint("fk_tools_dealer_company_id", type_="foreignkey")
        batch_op.drop_constraint("fk_tools_attached_to_set_id", type_="foreignkey")
    op.drop_column("tools", "dealer_company_id")
    op.drop_column("tools", "attached_to_set_id")
    op.drop_column("tools", "is_set")
    op.drop_column("tools", "consumable")
    op.drop_column("tools", "serial_numbers")
    op.drop_column("tools", "model_numbers")
    op.drop_column("tools", "size")
    op.drop_column("tools", "quantity")

    op.drop_table("preferred_agents")
    op.drop_table("private_agents")
    op.drop_table("dealer_companies")
