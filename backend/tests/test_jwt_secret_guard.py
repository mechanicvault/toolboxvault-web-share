"""Fail-closed startup guard (audit I4): with JWT_SECRET unset the app
must REFUSE to boot (the shipped default is public knowledge); with a
real secret it must boot. Runs in subprocesses so the environment is
exactly what a fresh server start sees.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BOOT_SNIPPET = "from app.main import create_app; create_app(); print('booted')"


def _boot(env_overrides: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("JWT_SECRET", None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", BOOT_SNIPPET],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_app_refuses_to_boot_with_default_jwt_secret():
    result = _boot({})
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr


def test_app_boots_with_a_real_jwt_secret():
    result = _boot({"JWT_SECRET": "subprocess-test-secret"})
    assert result.returncode == 0, result.stderr
    assert "booted" in result.stdout
