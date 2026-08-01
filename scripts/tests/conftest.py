"""Shared pytest setup for the scripts test suite."""

import sys
from pathlib import Path

# Put the repo root on sys.path so `backend.*` and `scripts.*` absolute
# imports resolve when pytest is invoked from anywhere. conftest.py lives at
# scripts/tests/, so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
