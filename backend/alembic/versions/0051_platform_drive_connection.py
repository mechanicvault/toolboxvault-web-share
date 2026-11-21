"""Platform Drive connection for Disaster Vault uploads (2026-10-24).

The Disaster Vault Drive leg moves from a service account (which
has no storage quota and 403s on every upload) to OAuth AS the
MechanicVault account. The operator connects once in Admin ->
Settings; the refresh token lives in this effectively-single-row
table, Fernet-encrypted at rest (app/modules/core/cloud_crypto.py).
`connected_by_id` is a PLAIN user id (no FK — the 0038 lesson).

Revision ID: 0051_platform_drive_connection
Revises: 0050_support_tickets
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0051_platform_drive_connection"
down_revision = "0050_support_tickets"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "platform_drive_connection",
        sa.Column("id", _UUID, primary_key=True),
        # The OAuth refresh token, Fernet-encrypted at rest (never
        # plaintext, never serialized out of the API).
        sa.Column(
            "refresh_token_encrypted", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column("drive_email", sa.String(320), nullable=False, server_default=""),
        sa.Column(
            "drive_folder_id", sa.String(200), nullable=False, server_default=""
        ),
        # PLAIN column on purpose — see the module docstring.
        sa.Column("connected_by_id", _UUID, nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_drive_connection")
