"""utils/diagnostics.py — System diagnostic utilities."""
from core.tools.system import snapshot
from core.llm.router import check_groq, check_ollama
from core.state import state
from config.settings import GROQ_MODEL, OLLAMA_MODEL

def full_diagnostic() -> dict:
    groq_ok   = check_groq()
    ollama_ok = check_ollama()
    sys       = snapshot()
    warnings  = []

    if sys["cpu_percent"] > 90:   warnings.append("⚠️ CPU critical")
    if sys["ram_used_pct"] > 90:  warnings.append("⚠️ RAM critical")
    if sys["disk_used_pct"] > 85: warnings.append("⚠️ Disk critical")
    if not groq_ok:   warnings.append("⚠️ Groq unavailable")
    if not ollama_ok: warnings.append("⚠️ Ollama unavailable")

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
    try:
        from core.protocols import protocol_status, is_lockdown, is_friday
        proto = protocol_status()
        if is_lockdown(): warnings.append("⚠️ LOCKDOWN ACTIVE")
        if is_friday():   warnings.append("⚠️ Friday Protocol — LLMs offline")
    except Exception:
        proto = {}

    return {"status": "NOMINAL" if not warnings else "DEGRADED",
            "brain": brain_status, "active_model": active_model,
            "groq_available": groq_ok, "ollama_available": ollama_ok,
            "system": sys, "warnings": warnings,
            "jarvis_state": state.snapshot(),
            "protocols": proto}
