"""Schema/index guarantees + storage credentials (audits I5, I6).

These assert on the model metadata and the migration source, so a future
edit that quietly drops an index or a table fails here instead of in
production. Migration *rendering* is gated separately by
`alembic upgrade head --sql`.
"""

from pathlib import Path

from app.core.db import Base
from app.modules.core import schemas as core_schemas
from app.core.deps import CurrentUser

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0001_initial.py"
)


def _indexed_columns(table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {col.name for index in table.indexes for col in index.columns}


def test_tools_owner_id_is_indexed():
    # Every inventory query filters by owner_id (blueprint §12 budget).
    assert "owner_id" in _indexed_columns("tools")


def test_token_tables_exist_with_user_indexes():
    assert "refresh_tokens" in Base.metadata.tables
    assert "email_verification_tokens" in Base.metadata.tables
    assert "user_id" in _indexed_columns("refresh_tokens")
    assert "user_id" in _indexed_columns("email_verification_tokens")


def test_migration_creates_what_the_models_declare():
    source = MIGRATION.read_text()
    assert '"refresh_tokens"' in source
    assert '"email_verification_tokens"' in source
    assert '"ix_tools_owner_id"' in source
    assert '"ix_refresh_tokens_user_id"' in source


def test_user_public_serializes_from_the_principal():
    """The /me route returns CurrentUser through UserPublic — prove the
    DTO carries every field the public shape needs (audit I10)."""
    import uuid
    from datetime import datetime, timezone

    principal = CurrentUser(
        id=uuid.uuid4(),
        account_number="TV-000001",
        email="a@example.com",
        name="A",
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    public = core_schemas.UserPublic.model_validate(principal)
    assert public.account_number == "TV-000001"
    assert public.email_verified is True
