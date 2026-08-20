"""tests/test_app_boot.py — the app must actually boot. Every one of the
36 router modules in server/api.py's _safe_import() calls is caught and
logged, not raised, so a broken import wouldn't otherwise fail loudly."""
from fastapi.routing import APIRoute


def test_app_imports_and_registers_routes():
    import server.api as api
    routes = [r for r in api.app.routes if isinstance(r, APIRoute)]
    assert len(routes) > 0, "no routes registered at all — something is badly broken"


def test_no_router_import_failures(capsys):
    """server/api.py's _safe_import() prints "[JARVIS] Failed to import
    ..." (via print(), not logging) for any router module that failed to
    load rather than raising — that failure would otherwise be silent."""
    import importlib
    import server.api as api
    importlib.reload(api)
    captured = capsys.readouterr()
    assert "Failed to import" not in captured.out, captured.out
