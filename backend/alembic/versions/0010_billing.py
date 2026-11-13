"""Billing: plans, subscriptions, grants, codes, AI wallet + core
columns for referrals and session devices (Phase A1, owner
decisions 2026-10-18).

What lands:

1. plans + business_brackets — the plan CATALOG as config. Plans:
   free (20 active items), pro (unlimited), business (unlimited;
   shop price = base + bracket fee, so the bracket STRUCTURE is
   modeled now — the fees themselves are money and live in Stripe
   later; prices are deliberately NOT in this migration or any
   code). ai_monthly_credits is 0 on every plan until the owner
   prices the AI module.
2. subscriptions + entitlement_grants — the entitlement sources
   the resolver folds into one answer (Stripe facts arrive in
   Phase C; codes/admin/tests write them until then).
3. system_settings — operator config; seeded with
   entitlements.enforcement_enabled = false (owner: build the
   limits now, enforce from launch — flipping this row is the
   launch-day change).
4. redeem_codes + redemptions — admin-issued codes and their
   per-user-once ledger.
5. ai_wallets + ai_ledger — the two-bucket AI credit wallet.
6. users.referred_by_id (referral capture) and
   refresh_tokens.user_agent (the Settings sessions list).
7. The AI Assistant feature module registers in module control the
   same way 0008 seeded the first modules: globally on, assigned
   to NO group (a purchasable add-on; default_groups is empty).

Downgrade drops it all in reverse.

Revision ID: 0010_billing
Revises: 0009_admin_grant
Create Date: 2026-10-18
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_billing"
down_revision: str | Sequence[str] | None = "0009_admin_grant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACCOUNT_GROUPS = [
    "mechanic_technician",
    "shop_company",
    "tool_dealer",
    "insurance",
]


def upgrade() -> None:
    # -- core columns -------------------------------------------------
    op.add_column(
        "users",
        sa.Column("referred_by_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_referred_by_id", "users", "users", ["referred_by_id"], ["id"]
    )
    op.create_index("ix_users_referred_by_id", "users", ["referred_by_id"])
    op.add_column(
        "refresh_tokens",
        sa.Column("user_agent", sa.String(length=500), nullable=True),
    )

    # -- plan catalog ---------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("plan_key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("item_limit", sa.Integer(), nullable=True),
        sa.Column(
            "ai_monthly_credits",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("plan_key"),
    )
    op.create_table(
        "business_brackets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_key", sa.String(length=32), nullable=False),
        sa.Column("up_to_employees", sa.Integer(), nullable=True),
        sa.Column("bracket_key", sa.String(length=32), nullable=False),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.ForeignKeyConstraint(["plan_key"], ["plans.plan_key"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bracket_key", name="uq_business_bracket_key"),
    )

    plans = sa.table(
        "plans",
        sa.column("plan_key", sa.String),
        sa.column("name", sa.String),
        sa.column("item_limit", sa.Integer),
        sa.column("ai_monthly_credits", sa.Integer),
        sa.column("is_paid", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        plans,
        [
            {
                "plan_key": "free",
                "name": "Free",
                "item_limit": 20,
                "ai_monthly_credits": 0,
                "is_paid": False,
                "sort_order": 0,
            },
            {
                "plan_key": "pro",
                "name": "Pro",
                "item_limit": None,
                "ai_monthly_credits": 0,
                "is_paid": True,
                "sort_order": 1,
            },
            {
                "plan_key": "business",
                "name": "Business",
                "item_limit": None,
                "ai_monthly_credits": 0,
                "is_paid": True,
                "sort_order": 2,
            },
        ],
    )
    brackets = sa.table(
        "business_brackets",
        sa.column("id", sa.UUID),
        sa.column("plan_key", sa.String),
        sa.column("up_to_employees", sa.Integer),
        sa.column("bracket_key", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        brackets,
        [
            {
                "id": uuid.uuid4(),
                "plan_key": "business",
                "up_to_employees": limit,
                "bracket_key": key,
                "sort_order": order,
            }
            for order, (limit, key) in enumerate(
                [
                    (5, "up_to_5"),
                    (10, "up_to_10"),
                    (25, "up_to_25"),
                    (None, "unlimited"),
                ]
            )
        ],
    )

    # -- entitlement sources ---------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "plan_key", sa.String(length=32), nullable=False, server_default="free"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="none"
        ),
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default=""
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_subscription_user"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_table(
        "entitlement_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "plan_key", sa.String(length=32), nullable=False, server_default="pro"
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default=""
        ),
        sa.Column(
            "source_ref", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_entitlement_grants_user_id", "entitlement_grants", ["user_id"]
    )

    # -- system settings ---------------------------------------------------
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String),
        sa.column("value", postgresql.JSONB),
    )
    op.bulk_insert(
        settings_table,
        [{"key": "entitlements.enforcement_enabled", "value": False}],
    )

    # -- redeem codes ---------------------------------------------------------
    op.create_table(
        "redeem_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "amount", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "plan_key", sa.String(length=32), nullable=False, server_default="pro"
        ),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_redeem_code"),
    )
    op.create_table(
        "redemptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["code_id"], ["redeem_codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grant_id"], ["entitlement_grants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_id", "user_id", name="uq_redemption_code_user"),
    )
    op.create_index("ix_redemptions_code_id", "redemptions", ["code_id"])
    op.create_index("ix_redemptions_user_id", "redemptions", ["user_id"])

    # -- AI wallet ----------------------------------------------------------
    op.create_table(
        "ai_wallets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "allowance_balance",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "banked_balance", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_refill_period", sa.String(length=7), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_ai_wallet_user"),
    )
    op.create_index("ix_ai_wallets_user_id", "ai_wallets", ["user_id"])
    op.create_table(
        "ai_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "ref", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column("bucket_balance_after", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_ledger_user_id", "ai_ledger", ["user_id"])

    # -- AI Assistant in module control (0008's seeding pattern) -----------
    module_state = sa.table(
        "module_state",
        sa.column("module_id", sa.String),
        sa.column("globally_enabled", sa.Boolean),
    )
    module_access = sa.table(
        "module_access",
        sa.column("id", sa.UUID),
        sa.column("module_id", sa.String),
        sa.column("account_group", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        module_state,
        [{"module_id": "ai_assistant", "globally_enabled": True}],
    )
    op.bulk_insert(
        module_access,
        [
            {
                "id": uuid.uuid4(),
                "module_id": "ai_assistant",
                "account_group": group,
                "enabled": False,
            }
            for group in _ACCOUNT_GROUPS
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM module_access WHERE module_id = 'ai_assistant'"
    )
    op.execute("DELETE FROM module_state WHERE module_id = 'ai_assistant'")
    op.drop_index("ix_ai_ledger_user_id", table_name="ai_ledger")
    op.drop_table("ai_ledger")
    op.drop_index("ix_ai_wallets_user_id", table_name="ai_wallets")
    op.drop_table("ai_wallets")
    op.drop_index("ix_redemptions_user_id", table_name="redemptions")
    op.drop_index("ix_redemptions_code_id", table_name="redemptions")
    op.drop_table("redemptions")
    op.drop_table("redeem_codes")
    op.drop_table("system_settings")
    op.drop_index("ix_entitlement_grants_user_id", table_name="entitlement_grants")
    op.drop_table("entitlement_grants")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("business_brackets")
    op.drop_table("plans")
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_index("ix_users_referred_by_id", table_name="users")
    op.drop_constraint("fk_users_referred_by_id", "users", type_="foreignkey")
    op.drop_column("users", "referred_by_id")
