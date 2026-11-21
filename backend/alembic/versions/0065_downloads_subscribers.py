"""Downloads subscriber list (lead magnet, 2026-10-29).

One row per email address that joined the Toolbox Vault updates
list on the /downloads page: address, source, the unsubscribe token
every update email carries, and the unsubscribe stamp. Not an
account table and not billing — see app/modules/downloads/models.py.
"""

import sqlalchemy as sa
from alembic import op

revision = "0065_downloads_subscribers"
down_revision = "0064_visitor_counter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "downloads_subscribers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="downloads"),
        sa.Column("unsubscribe_token", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_downloads_subscribers_email"),
        sa.UniqueConstraint(
            "unsubscribe_token", name="uq_downloads_subscribers_unsubscribe_token"
        ),
    )
    op.create_index(
        "ix_downloads_subscribers_email", "downloads_subscribers", ["email"]
    )
    op.create_index(
        "ix_downloads_subscribers_unsubscribe_token",
        "downloads_subscribers",
        ["unsubscribe_token"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_downloads_subscribers_unsubscribe_token",
        table_name="downloads_subscribers",
    )
    op.drop_index("ix_downloads_subscribers_email", table_name="downloads_subscribers")
    op.drop_table("downloads_subscribers")
