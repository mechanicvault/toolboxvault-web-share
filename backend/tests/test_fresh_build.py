"""Fresh-build check (sheet row 116, 2026-11-18).

A brand-new database must build from an empty schema by
running the whole migration chain — a fresh install, a new
server, a disaster-recovery restore. The chain is
Postgres-only (0001 opens with tsvector triggers and
sequences), so this test runs where a Postgres server is
offered: set TBV_FRESH_BUILD_DSN to a maintenance-database
URL (e.g. postgresql+psycopg://user:pass@host:5432/postgres)
on a server the test may create and drop ONE throwaway
database on. Without it the test skips, the same posture as
the backup tests' binary checks.

The upgrade runs in a BARE subprocess (only alembic + the
migration files, like the migration gates) so nothing the
suite imported can mask a missing import or a live-model
shortcut — the exact failure this row fixed: 0081 created
flyer_sources from the live models (already carrying 0083's
columns), and 0083 died adding auto_hash a second time.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
DSN = os.environ.get("TBV_FRESH_BUILD_DSN", "")

requires_postgres = pytest.mark.skipif(
    not DSN,
    reason=(
        "TBV_FRESH_BUILD_DSN not set — the fresh-build check "
        "needs a Postgres server it may create a throwaway "
        "database on"
    ),
)


def _swap_db(url: str, name: str) -> str:
    head, _, _old = url.rpartition("/")
    return f"{head}/{name}"


@requires_postgres
def test_empty_database_builds_to_head():
    import psycopg
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    db_name = f"tbv_fresh_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(DSN.replace("+psycopg", ""), autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{db_name}"')
        try:
            env = dict(os.environ)
            env["DATABASE_URL"] = _swap_db(DSN, db_name)
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                env=env,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            assert proc.returncode == 0, (
                "fresh build failed:\n"
                + proc.stdout[-2000:]
                + proc.stderr[-2000:]
            )
            head = ScriptDirectory.from_config(
                Config(str(BACKEND / "alembic.ini"))
            ).get_current_head()
            check = psycopg.connect(
                _swap_db(DSN, db_name).replace("+psycopg", "")
            )
            try:
                version = check.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0]
                assert version == head
                # The row's original collision point: 0083's
                # columns exist exactly once on flyer_sources.
                cols = {
                    row[0]
                    for row in check.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'flyer_sources'"
                    )
                }
                assert {"auto_hash", "auto_checked_at"} <= cols
                # The tables the live-model shortcut used to
                # create (0081/0082/0085/0086/0087/0088) all
                # exist, built from their written definitions.
                tables = {
                    row[0]
                    for row in check.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                }
                assert {
                    "flyer_sources",
                    "flyers",
                    "flyer_alert_prefs",
                    "report_templates",
                    "generated_reports",
                    "report_template_seeds",
                    "site_stats_snapshots",
                    "community_blocks",
                    "onboarding_progress",
                    "ai_usage",
                    "subscription_status_changes",
                } <= tables
            finally:
                check.close()
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        admin.close()
