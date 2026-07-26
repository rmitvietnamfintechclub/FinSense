"""Shared pytest setup for the pipeline test suite."""

import sys
from pathlib import Path

# Put the repo root on sys.path so `backend.*` absolute imports resolve
# when pytest is invoked from anywhere. conftest.py lives at
# backend/pipeline/tests/, so parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
