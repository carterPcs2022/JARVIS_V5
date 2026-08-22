"""tests/conftest.py — shared pytest setup.

Sets JARVIS_API_TOKEN/ENVIRONMENT before any project module imports, since
config/settings.py and utils/security.py read them at import time —
without this, importing server.api (or anything that transitively imports
it) fails before a test even runs.
"""
import os

os.environ.setdefault("JARVIS_API_TOKEN", "test-token-for-pytest")
os.environ.setdefault("ENVIRONMENT", "local")

import pytest


@pytest.fixture(autouse=True)
def _clear_working_memory():
    """core/working_memory.py's working_mem is a module-level singleton
    (see Phase 5) — reset it before and after every test so one test's
    writes can't leak into another's assertions."""
    from core.working_memory import working_mem
    working_mem.clear()
    yield
    working_mem.clear()
