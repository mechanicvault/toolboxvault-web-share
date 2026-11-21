#!/bin/bash
# Run the backend test suite against a REAL PostgreSQL (sheet row 117).
#
# The default suite runs on SQLite; PostgreSQL-only behavior (search,
# date math, constraints, the migration chain itself) is invisible
# there — that gap is how the broken setup step 0083 shipped. This
# runner points the suite's PG mode (tests/conftest.py, TBV_TEST_PG_DSN)
# at a real server:
#
#   1. TBV_TEST_PG_DSN already set  -> use it as-is.
#   2. docker available             -> throwaway postgres:16 container.
#   3. local PostgreSQL installed   -> throwaway database + role on it
#                                      (installed via apt when missing
#                                      and running as root).
#
# Every test gets its own throwaway schema (see conftest._pg_db), so
# the database named here is only a landing pad — its own tables are
# never created or dropped. Extra args pass through to pytest.
#
# Usage:  backend/tests/run_pg_tests.sh [pytest args...]
# Results land in backend/tests/pg-results/ (JUnit XML + log).
set -u
cd "$(dirname "$0")/.."

RESULTS=tests/pg-results
mkdir -p "$RESULTS"
STAMP=$(date +%Y%m%d-%H%M%S)
# A caller running one chunk can name the results files itself.
XML="${PG_RESULTS_XML:-$RESULTS/pg-$STAMP.xml}"
LOG="${PG_RESULTS_LOG:-$RESULTS/pg-$STAMP.log}"

cleanup() {
  if [ -n "${DOCKER_CID:-}" ]; then
    docker rm -f "$DOCKER_CID" > /dev/null 2>&1
  fi
  if [ -n "${DROP_ROLE:-}" ]; then
    su postgres -c "psql -q -c \"DROP DATABASE IF EXISTS $PG_DBNAME;\" -c \"DROP ROLE IF EXISTS $PG_ROLE;\"" > /dev/null 2>&1
  fi
}
trap cleanup EXIT

if [ -n "${TBV_TEST_PG_DSN:-}" ]; then
  echo "Using TBV_TEST_PG_DSN from the environment."
elif command -v docker > /dev/null 2>&1; then
  DOCKER_CID=$(docker run -d -e POSTGRES_PASSWORD=tbvtest -e POSTGRES_DB=tbvtest -P postgres:16 2>/dev/null)
  if [ -z "$DOCKER_CID" ]; then
    echo "docker is present but the postgres:16 container did not start." >&2
    exit 2
  fi
  PORT=$(docker port "$DOCKER_CID" 5432/tcp | head -1 | sed 's/.*://')
  export TBV_TEST_PG_DSN="postgresql+psycopg://postgres:tbvtest@127.0.0.1:${PORT}/tbvtest"
  echo "Throwaway PostgreSQL container on port $PORT."
  for i in $(seq 1 30); do
    docker exec "$DOCKER_CID" pg_isready -q && break
    sleep 1
  done
else
  # Is PostgreSQL installed? Check a few times over a minute first —
  # a keeper relaunch can land while the machine is still settling
  # after a restart, and a momentarily missing binary must not be
  # mistaken for "not installed" (2026-11-18: exactly that sent a
  # relaunch into an apt install that raced a held dpkg lock).
  pg_present() {
    command -v pg_ctlcluster > /dev/null 2>&1 || ls /usr/lib/postgresql/*/bin/initdb > /dev/null 2>&1
  }
  for i in $(seq 1 12); do
    pg_present && break
    sleep 5
  done
  if ! pg_present; then
    if [ "$(id -u)" = "0" ] && command -v apt-get > /dev/null 2>&1; then
      echo "Installing PostgreSQL (one-time)..."
      # -o DPkg::Lock::Timeout: wait for a held dpkg lock instead of
      # failing on the spot.
      apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o DPkg::Lock::Timeout=300 postgresql || {
        echo "PostgreSQL install failed." >&2; exit 2; }
    else
      echo "No PostgreSQL available (no DSN, no docker, no local install)." >&2
      exit 2
    fi
  fi
  # Start the packaged cluster when it is down.
  if command -v pg_lsclusters > /dev/null 2>&1; then
    pg_lsclusters | awk '$4 != "online" {print $1, $2}' | while read -r ver name; do
      pg_ctlcluster "$ver" "$name" start > /dev/null 2>&1
    done
  fi
  PG_ROLE="tbvtest_$$"
  PG_DBNAME="tbvtest_$$"
  PG_PASS=$(head -c 18 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 24)
  su postgres -c "psql -q -c \"CREATE ROLE $PG_ROLE LOGIN PASSWORD '$PG_PASS';\" -c \"CREATE DATABASE $PG_DBNAME OWNER $PG_ROLE;\"" || {
    echo "Could not create the throwaway database/role." >&2; exit 2; }
  DROP_ROLE=1
  export TBV_TEST_PG_DSN="postgresql+psycopg://$PG_ROLE:$PG_PASS@127.0.0.1:5432/$PG_DBNAME"
  echo "Throwaway database $PG_DBNAME on the local PostgreSQL."
fi

# Code paths that open their own session (SessionLocal) should land on
# the same server rather than the app's default database.
export DATABASE_URL="$TBV_TEST_PG_DSN"

if [ -x ".venv/bin/python" ]; then
  PY=.venv/bin/python
elif [ -x "$HOME/workspace/toolbox-vault-web/backend/.venv/bin/python" ]; then
  PY="$HOME/workspace/toolbox-vault-web/backend/.venv/bin/python"
else
  PY=python3
fi

# Targets: any arguments REPLACE the default whole-suite target, so a
# caller can run one chunk of files against PostgreSQL (the chunked
# first run and any future split nightly both work this way).
if [ "$#" -gt 0 ]; then
  TARGETS=("$@")
else
  TARGETS=(tests/)
fi

"$PY" -m pytest "${TARGETS[@]}" -q --junitxml="$XML" 2>&1 | tee "$LOG"
exit "${PIPESTATUS[0]}"
