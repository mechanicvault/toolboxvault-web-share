"""Wave 3 (2026-10-20): shop crews, insurer directory, currency, feedback.

Five features, one migration:

- shop_memberships — the shop crew ledger (core). BOTH user
  columns are PLAIN ids (no FK — the 0038 lesson: a two-party
  table whose user columns are FKs blocks Postgres account
  deletion; the core cascade sweeps these rows explicitly).
- insurer_companies + insurer_affiliations — the platform
  insurer directory (starts EMPTY — no seed data is invented)
  and insurance-group users' operator-verified affiliations (the
  dealer CompanyRepresentation shape). insurance_profiles gains
  insurer_company_id (SET NULL: picking fills the free-text name;
  the name survives a directory delete, the link goes).
- users.country + users.currency — the currency chooser: ISO
  3166 alpha-2 (optional) + ISO 4217 (default USD, defaults from
  country). V1 semantics: an account's amounts are IN its
  currency; stored amounts never convert.
- fx_rates — the daily ECB rate cache (EUR base, via
  frankfurter.app) feeding DISPLAY-ONLY approximate hints.
- claims.archived (+archived_at) and claim_lines.
  include_in_package — the claim extras: archive shelving and
  per-line package toggles (defaults keep today's behavior:
  unarchived, every line in the package).
- feedback_* — the public feedback boards (posts, votes, flat
  comments, moderation reports). author/reporter ids are PLAIN
  columns (the forum doctrine): posts tombstone as "Former
  member" on account deletion.

Revision ID: 0041_wave3
Revises: 0040_wave2
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_wave3"
down_revision: str | None = "0040_wave2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
_UUID = postgresql.UUID(as_uuid=True)

_NOW = sa.func.now()


def upgrade() -> None:
    # -- users: country + currency -------------------------------------
    op.add_column(
        "users",
        sa.Column("country", sa.String(2), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    )

    # -- shop crews ------------------------------------------------------
    op.create_table(
        "shop_memberships",
        sa.Column("id", _UUID, primary_key=True),
        # PLAIN columns on purpose — see the module docstring.
        sa.Column("shop_user_id", _UUID, nullable=False),
        sa.Column("employee_user_id", _UUID, nullable=True),
        sa.Column("invite_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("invite_token", sa.String(64), nullable=False),
        sa.Column("role_label", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_notices", _JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_shop_memberships_shop_user_id", "shop_memberships", ["shop_user_id"])
    op.create_index("ix_shop_memberships_employee_user_id", "shop_memberships", ["employee_user_id"])
    op.create_index("ix_shop_memberships_invite_token", "shop_memberships", ["invite_token"], unique=True)

    # -- insurer directory + affiliations --------------------------------
    op.create_table(
        "insurer_companies",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("website", sa.String(500), nullable=False, server_default=""),
        sa.Column("phones", _JSONB, nullable=False, server_default="[]"),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "insurer_affiliations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id", _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "company_id", _UUID,
            sa.ForeignKey("insurer_companies.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("role_at_company", sa.String(200), nullable=False, server_default=""),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_by_id", _UUID, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "user_id", "company_id", name="uq_insurer_affiliation_user_company"
        ),
    )
    op.create_index("ix_insurer_affiliations_user_id", "insurer_affiliations", ["user_id"])
    op.create_index("ix_insurer_affiliations_company_id", "insurer_affiliations", ["company_id"])

    # batch mode: the column carries a ForeignKey, which SQLite
    # cannot ALTER in directly (Postgres takes either path).
    with op.batch_alter_table("insurance_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "insurer_company_id", _UUID,
                sa.ForeignKey(
                    "insurer_companies.id",
                    ondelete="SET NULL",
                    name="fk_insurance_profiles_insurer_company",
                ),
                nullable=True,
            )
        )
    op.create_index(
        "ix_insurance_profiles_insurer_company_id",
        "insurance_profiles",
        ["insurer_company_id"],
    )

    # -- FX rate cache -----------------------------------------------------
    op.create_table(
        "fx_rates",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("currency", "rate_date", name="uq_fx_rate_currency_date"),
    )
    op.create_index("ix_fx_rates_currency", "fx_rates", ["currency"])
    op.create_index("ix_fx_rates_rate_date", "fx_rates", ["rate_date"])

    # -- claim extras -------------------------------------------------------
    op.add_column(
        "claims",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "claims",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "claim_lines",
        sa.Column(
            "include_in_package", sa.Boolean(),
            nullable=False, server_default="true",
        ),
    )

    # -- feedback boards ------------------------------------------------------
    op.create_table(
        "feedback_posts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("board", sa.String(10), nullable=False),
        # PLAIN column (tombstone doctrine) — no FK.
        sa.Column("author_id", _UUID, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("status_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="visible"),
        sa.Column("removed_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("flags", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_gone", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_feedback_posts_board", "feedback_posts", ["board"])
    op.create_index("ix_feedback_posts_author_id", "feedback_posts", ["author_id"])
    op.create_index("ix_feedback_posts_status", "feedback_posts", ["status"])
    op.create_index("ix_feedback_posts_visibility", "feedback_posts", ["visibility"])

    op.create_table(
        "feedback_votes",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "post_id", _UUID,
            sa.ForeignKey("feedback_posts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("post_id", "user_id", name="uq_feedback_vote_post_user"),
    )
    op.create_index("ix_feedback_votes_post_id", "feedback_votes", ["post_id"])
    op.create_index("ix_feedback_votes_user_id", "feedback_votes", ["user_id"])

    op.create_table(
        "feedback_comments",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "post_id", _UUID,
            sa.ForeignKey("feedback_posts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("author_id", _UUID, nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="visible"),
        sa.Column("removed_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("flags", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_gone", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_feedback_comments_post_id", "feedback_comments", ["post_id"])
    op.create_index("ix_feedback_comments_author_id", "feedback_comments", ["author_id"])
    op.create_index("ix_feedback_comments_visibility", "feedback_comments", ["visibility"])

    op.create_table(
        "feedback_reports",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("target_kind", sa.String(10), nullable=False),
        sa.Column("target_id", _UUID, nullable=False),
        sa.Column("reporter_id", _UUID, nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_feedback_reports_target_id", "feedback_reports", ["target_id"])
    op.create_index("ix_feedback_reports_reporter_id", "feedback_reports", ["reporter_id"])
    op.create_index("ix_feedback_reports_status", "feedback_reports", ["status"])


def downgrade() -> None:
    op.drop_table("feedback_reports")
    op.drop_table("feedback_comments")
    op.drop_table("feedback_votes")
    op.drop_table("feedback_posts")
    op.drop_column("claim_lines", "include_in_package")
    op.drop_column("claims", "archived_at")
    op.drop_column("claims", "archived")
    op.drop_table("fx_rates")
    op.drop_index("ix_insurance_profiles_insurer_company_id", table_name="insurance_profiles")
    with op.batch_alter_table("insurance_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_insurance_profiles_insurer_company", type_="foreignkey"
        )
        batch_op.drop_column("insurer_company_id")
    op.drop_table("insurer_affiliations")
    op.drop_table("insurer_companies")
    op.drop_table("shop_memberships")
    op.drop_column("users", "currency")
    op.drop_column("users", "country")
