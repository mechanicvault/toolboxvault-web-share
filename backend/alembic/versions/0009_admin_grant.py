"""Admin grant consolidation (owner, 2026-10-18).

Migration 0008 granted users.is_operator to two accounts: the
owner's (mechanicltz@gmail.com) and the QA smoke-test account
(smoke-test@toolboxvault.com), which needed it so the admin surface
could be exercised end-to-end before launch. The owner has since
directed that the main admin — god access — belongs to his email
singly. This migration therefore:

- asserts is_operator = true for mechanicltz@gmail.com (a no-op if
  0008 already set it; the end state is what matters), and
- revokes is_operator from smoke-test@toolboxvault.com — a throwaway
  QA account must not hold god access. The account itself is
  untouched: it still signs in and keeps its mechanic features.

Both statements are plain UPDATEs matched by email: safe to run
repeatedly, and a no-op where an account doesn't exist (e.g. a fresh
dev database) — same contract as the 0008 grant.

Downgrade restores exactly the 0008 end state (smoke-test regains
the grant; the owner's grant predates this migration and stays).

Revision ID: 0009_admin_grant
Revises: 0008_module_control
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_admin_grant"
down_revision: str | Sequence[str] | None = "0008_module_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The addresses are fixed constants from the owner's direction —
# inlined on purpose, same rationale as 0008: bound params render as
# NULL in offline --sql dumps, which would silently change nobody if
# such a dump were ever applied by hand. These are not user input.
_OWNER_EMAIL = "mechanicltz@gmail.com"
_QA_EMAIL = "smoke-test@toolboxvault.com"


def upgrade() -> None:
    op.execute(
        f"UPDATE users SET is_operator = true WHERE email = '{_OWNER_EMAIL}'"
    )
    op.execute(
        f"UPDATE users SET is_operator = false WHERE email = '{_QA_EMAIL}'"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE users SET is_operator = true WHERE email = '{_QA_EMAIL}'"
    )
