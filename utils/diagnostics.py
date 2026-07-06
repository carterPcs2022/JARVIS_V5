"""utils/diagnostics.py — System diagnostic utilities."""
from core.tools.system import snapshot
from core.llm.router import check_groq, check_ollama, check_anthropic
from core.state import state
from config.settings import GROQ_MODEL, OLLAMA_MODEL

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
    all_llms_down = not groq_ok and not anthropic_ok and not ollama_ok
    status = "DEGRADED" if (all_llms_down or lockdown_active or friday_active) else "NOMINAL"

    return {"status": status,
            "brain": brain_status, "active_model": active_model,
            "groq_available": groq_ok, "ollama_available": ollama_ok,
            "anthropic_available": anthropic_ok,
            "system": sys, "warnings": warnings,
            "jarvis_state": state.snapshot(),
            "protocols": proto}
