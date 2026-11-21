"""Migration 0009 (admin grant consolidation, owner 2026-10-18).

0008 granted users.is_operator to the owner's account AND the QA
smoke-test account; the owner directed that god access belongs to
mechanicltz@gmail.com singly. These tests run the migration's real
upgrade()/downgrade() against the fixture database and pin:

- the owner's email ends up operator (even starting from False);
- the QA smoke-test email is revoked (even starting from True);
- unrelated users are untouched, in both polarities;
- upgrade is idempotent (plain UPDATEs, safe to re-run);
- downgrade restores exactly the 0008 end state.
"""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.core import models as core_models

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0009_admin_grant.py"
)

OWNER_EMAIL = "mechanicltz@gmail.com"
QA_EMAIL = "smoke-test@toolboxvault.com"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0009_admin_grant", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(db, fn) -> None:
    """Execute a migration function with the alembic op proxy bound
    to the fixture session's own connection."""
    ctx = MigrationContext.configure(db.connection())
    with Operations.context(ctx):
        fn()


def _make_user(db, account_number, email, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Grant User",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _flag(db, email) -> bool:
    # expire_all: the migration wrote through raw SQL on the shared
    # connection, so the session's identity map holds stale rows.
    db.expire_all()
    user = db.query(core_models.User).filter_by(email=email).one()
    return bool(user.is_operator)


def test_migration_chains_off_module_control():
    migration = _load_migration()
    assert migration.revision == "0009_admin_grant"
    assert migration.down_revision == "0008_module_control"


def test_owner_email_ends_up_operator(db):
    _make_user(db, "TV-M-000301", OWNER_EMAIL, operator=False)
    _run(db, _load_migration().upgrade)
    assert _flag(db, OWNER_EMAIL) is True


def test_qa_email_is_revoked(db):
    _make_user(db, "TV-M-000302", QA_EMAIL, operator=True)
    _run(db, _load_migration().upgrade)
    assert _flag(db, QA_EMAIL) is False


def test_upgrade_is_idempotent(db):
    _make_user(db, "TV-M-000303", OWNER_EMAIL, operator=False)
    _make_user(db, "TV-M-000304", QA_EMAIL, operator=True)
    migration = _load_migration()
    _run(db, migration.upgrade)
    _run(db, migration.upgrade)
    assert _flag(db, OWNER_EMAIL) is True
    assert _flag(db, QA_EMAIL) is False


def test_unrelated_users_are_untouched(db):
    _make_user(db, "TV-M-000305", "other-op@example.com", operator=True)
    _make_user(db, "TV-M-000306", "plain@example.com", operator=False)
    _run(db, _load_migration().upgrade)
    # An unrelated operator keeps the flag; an unrelated non-operator
    # does not gain it. The migration names two emails, no others.
    assert _flag(db, "other-op@example.com") is True
    assert _flag(db, "plain@example.com") is False


def test_downgrade_restores_the_0008_state(db):
    _make_user(db, "TV-M-000307", OWNER_EMAIL, operator=True)
    _make_user(db, "TV-M-000308", QA_EMAIL, operator=True)
    migration = _load_migration()
    _run(db, migration.upgrade)
    assert _flag(db, QA_EMAIL) is False
    _run(db, migration.downgrade)
    assert _flag(db, QA_EMAIL) is True
    # The owner's grant predates 0009 — downgrade must not strip it.
    assert _flag(db, OWNER_EMAIL) is True
