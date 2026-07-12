"""services/system_doctor.py — a single "how's everything actually doing"
check, mirroring FRIDAY's services/system_doctor.py structure/shape so
hitting either assistant's doctor endpoint gives a consistent answer.
Deliberately thin: every check here delegates to real logic that already
exists elsewhere in this repo (core/config_validator.py, the Mac Bridge/
memory-file checks in utils/diagnostics.py, core.tools.system.snapshot())
rather than re-implementing any of it a second time.
"""
def _check_apis() -> dict:
    """Live reachability, not just "is a key present" — this repo already
    has real health checks for both providers (core/llm/router.py's
    check_groq()/check_anthropic(), the same ones utils/diagnostics.py's
    full_diagnostic() calls), so use those instead of a second, weaker
    key-presence-only check."""
    from core.llm.router import check_groq, check_anthropic
    checks = {"groq": check_groq(), "anthropic": check_anthropic()}
    return {"ok": any(checks.values()), "keys": checks}


def _check_mac_bridge() -> dict:
    from utils.diagnostics import _check_mac_bridge as _live_check
    result = _live_check()
    if not result.get("configured"):
        return {"ok": None, "reason": "not configured"}
    return {"ok": result.get("reachable", False), "detail": result}


def _check_disk() -> dict:
    """core.tools.system.snapshot() already computes disk usage for
    /stark/diagnostics — reuse that number instead of a second
    shutil.disk_usage() call against the same filesystem."""
    from core.tools.system import snapshot
    try:
        sys = snapshot()
        pct_used = sys["disk_used_pct"]
        return {"ok": pct_used < 90, "pct_used": pct_used}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_memory_files() -> dict:
    from utils.diagnostics import _check_memory_files as _live_check
    result = _live_check()
    missing = [name for name, v in result.items() if not v.get("exists")]
    corrupt = [name for name, v in result.items() if v.get("exists") and v.get("valid_json") is False]
    return {"ok": not corrupt, "missing": missing, "corrupt": corrupt}


def _check_config() -> dict:
    from core.config_validator import validate_config
    return validate_config()


def full_check() -> dict:
    """Never raises — a doctor that crashes when asked how the patient's
    doing is worse than useless."""
    checks = {
        "apis": _check_apis(),
        "mac_bridge": _check_mac_bridge(),
        "disk": _check_disk(),
        "memory_files": _check_memory_files(),
        "config": _check_config(),
    }
    # mac_bridge's ok=None (not configured) shouldn't count as unhealthy —
    # only an explicit False across any check should.
    healthy = all(c.get("ok") is not False for c in checks.values())
    return {"healthy": healthy, "checks": checks}
