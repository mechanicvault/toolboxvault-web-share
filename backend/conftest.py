"""Repo-root pytest setup.

Runs before any test module imports the app: puts backend/ on sys.path and
provides a throwaway JWT_SECRET so importing app.main exercises the real
startup path (the fail-closed guard is tested separately, in a subprocess
WITHOUT this variable — see tests/test_jwt_secret_guard.py).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "pytest-only-secret-not-for-production")
