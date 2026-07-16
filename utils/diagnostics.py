"""utils/diagnostics.py — System diagnostic utilities."""
import json
from core.tools.system import snapshot
from core.llm.router import check_groq, check_ollama, check_anthropic
from core.state import state
from config.settings import GROQ_MODEL, OLLAMA_MODEL


def _check_mac_bridge() -> dict:
    """Live reachability check, not just "is a URL configured" — Mac Bridge
    runs on the user's own machine (typically tunneled via ngrok), so the
    URL being set says nothing about whether the tunnel is actually up
    right now. Short timeout: this runs inline in the diagnostics request
    path, and services/scheduler.py's _mac_bridge_check() is the one that
    actually alerts on sustained outages — this is just a point-in-time read."""
    import os
    url = os.getenv("MAC_BRIDGE_URL", "")
    if not url:
        return {"configured": False, "reachable": False}
    try:
        import httpx
        r = httpx.get(f"{url}/health", timeout=3)
        return {"configured": True, "reachable": r.status_code < 500}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)}


def _check_memory_files() -> dict:
    """Confirms every memory JSON file this repo relies on (short/long-term
    memory, conversation log, user profile) actually parses — a truncated
    write (e.g. a crash mid-save) leaves a file present but unreadable,
    which core.memory's loaders would otherwise only surface later as a
    confusing failure deep in an unrelated request."""
    from config.settings import SHORT_TERM_FILE, LONG_TERM_FILE, CONVERSATIONS_FILE, PROFILE_FILE
    files = {
        "short_term":    SHORT_TERM_FILE,
        "long_term":     LONG_TERM_FILE,
        "conversations": CONVERSATIONS_FILE,
        "profile":       PROFILE_FILE,
    }
    result = {}
    for name, path in files.items():
        if not path.exists():
            result[name] = {"exists": False, "valid_json": None}
            continue
        try:
            with open(path, "r") as f:
                json.load(f)
            result[name] = {"exists": True, "valid_json": True}
        except Exception as e:
            result[name] = {"exists": True, "valid_json": False, "error": str(e)}
    return result

def full_diagnostic() -> dict:
    # check_groq() already treats a 429 as "up" (just rate-limited, not
    # down) — see its docstring. Anthropic is a config check, not a live
    # ping (see check_anthropic docstring), so it's cheap to include here.
    groq_ok      = check_groq()
    ollama_ok    = check_ollama()
    anthropic_ok = check_anthropic()
    sys       = snapshot()
    warnings  = []

    if sys["cpu_percent"] > 90:   warnings.append("⚠️ CPU critical")
    if sys["ram_used_pct"] > 90:  warnings.append("⚠️ RAM critical")
    if sys["disk_used_pct"] > 85: warnings.append("⚠️ Disk critical")
    # Ollama/Anthropic are fallbacks — their absence isn't a problem on its
    # own as long as Groq is up. Only call it out when nothing is left.
    if not groq_ok and not anthropic_ok and not ollama_ok:
        warnings.append("⚠️ Groq unavailable")
        warnings.append("⚠️ Anthropic unavailable")
        warnings.append("⚠️ Ollama unavailable")
    elif not groq_ok:
        warnings.append("⚠️ Groq unavailable (fallback active)")

    # active_model is set live by core/llm/router.py after every real chat
    # call (it reflects whichever tier/model actually served the last
    # response — Groq or an Anthropic tier). Previously this function
    # overwrote it with a static guess based only on which provider is
    # reachable, clobbering the real value on every ~30s HUD poll — the
    # HUD's model display would flicker back to a guess a few seconds
    # after showing the real model. Only fall back to a guess if nothing
    # real has been recorded yet.
    active_model = state.get("active_model") or (
        GROQ_MODEL if groq_ok else OLLAMA_MODEL if ollama_ok else "none"
    )
    brain_status = ("GROQ ONLINE" if groq_ok else
                    "OLLAMA FALLBACK" if ollama_ok else "ALL ENGINES OFFLINE")

    state.update({"groq_available": groq_ok, "ollama_available": ollama_ok,
                  "status": "online" if (groq_ok or ollama_ok) else "degraded"})

    # Protocol status
    lockdown_active = friday_active = False
    try:
        from core.protocols import protocol_status, is_lockdown, is_friday
        proto = protocol_status()
        lockdown_active = is_lockdown()
        friday_active   = is_friday()
        if lockdown_active: warnings.append("⚠️ LOCKDOWN ACTIVE")
        if friday_active:   warnings.append("⚠️ Friday Protocol — LLMs offline")
    except Exception:
        proto = {}

    # "DEGRADED" only means every LLM provider is down (Groq counts as up
    # even at 429 — that's rate limiting, not an outage), or lockdown/Friday
    # protocol is active. A CPU spike or a fallback simply not being
    # configured shouldn't flip the whole HUD to DEGRADED — those still
    # show up in `warnings` for detail, they just don't drive the headline.
    # Config validity, Mac Bridge reachability, memory-file integrity — all
    # folded into this one combined status rather than a second endpoint,
    # so /stark/diagnostics stays the single "check everything" call.
    try:
        from core.config_validator import validate_config
        config_result = validate_config()
    except Exception as e:
        config_result = {"ok": False, "issues": [f"config_validator crashed: {e}"]}
    if not config_result.get("ok"):
        warnings.append("⚠️ Config validation failed — see config_check.issues")

    mac_bridge_result = _check_mac_bridge()
    if mac_bridge_result.get("configured") and not mac_bridge_result.get("reachable"):
        warnings.append("⚠️ Mac Bridge unreachable")

    memory_files_result = _check_memory_files()
    if any(v.get("valid_json") is False for v in memory_files_result.values()):
        warnings.append("⚠️ Memory file corrupted — see memory_files")
    missing_memory_files = [name for name, v in memory_files_result.items() if not v.get("exists")]
    if missing_memory_files:
        warnings.append(f"⚠️ Memory file(s) missing: {', '.join(missing_memory_files)} — see memory_files")

    all_llms_down = not groq_ok and not anthropic_ok and not ollama_ok
    status = "DEGRADED" if (all_llms_down or lockdown_active or friday_active) else "NOMINAL"

    return {"status": status,
            "brain": brain_status, "active_model": active_model,
            "groq_available": groq_ok, "ollama_available": ollama_ok,
            "anthropic_available": anthropic_ok,
            "system": sys, "warnings": warnings,
            "jarvis_state": state.snapshot(),
            "protocols": proto,
            "config_check": config_result,
            "mac_bridge": mac_bridge_result,
            "memory_files": memory_files_result}
