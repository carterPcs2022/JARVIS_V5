"""
core/friday_fallback.py — Protocol 14: Friday Protocol.

When both Groq and Ollama are unreachable, JARVIS switches to a minimal
rule-based fallback. He can still handle monitoring, alerts, telemetry,
Mac control, and basic canned responses. JARVIS never goes fully dark.
"""
import re
from datetime import datetime

from config.settings import USER_TIMEZONE


def _now_local() -> datetime:
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(USER_TIMEZONE))
    except Exception:
        return datetime.now()


# ── Canned responses ──────────────────────────────────────────────────────────

_CANNED = {
    "greet":    ("Both LLM engines are currently offline. I'm running on Friday Protocol — "
                 "my emergency fallback mode. I can still handle system monitoring, "
                 "Mac control, and status checks."),
    "status":   None,   # filled dynamically
    "help":     ("In Friday Protocol mode I can: check system status, monitor threats, "
                 "control Mac apps, check Spotify, manage volume, take screenshots, "
                 "and run emergency diagnostics. LLM reasoning is unavailable until "
                 "Groq or Ollama comes back online."),
    "offline":  ("I'm operating on emergency fallback. My reasoning engines are offline "
                 "but core systems remain functional. I'll notify you when they're back."),
    "unknown":  ("I'm in Friday Protocol — minimal fallback mode. I understood your request "
                 "but cannot reason about it without an LLM. Try system commands or status checks."),
}

# ── Intent patterns ───────────────────────────────────────────────────────────

_PATTERNS = [
    # Greetings / status
    (r"\b(hello|hi|hey|howdy|yo)\b",              "greet"),
    (r"\b(status|health|how are you|online)\b",    "status"),
    (r"\b(help|what can you|what do you)\b",       "help"),

    # System telemetry
    (r"\b(cpu|ram|memory|disk|uptime|telemetry)\b","telemetry"),

    # Threats
    (r"\b(threat|security|sentinel|alert|attack)\b","threats"),

    # Mac control — delegated to mac_dispatcher directly
    (r"\b(open|launch|close|quit|spotify|volume|mute|screenshot|email)\b", "mac"),

    # Memory
    (r"\b(remember|recall|memory|history)\b",      "memory"),

    # LLM status
    (r"\b(groq|ollama|model|llm|engine|ai)\b",     "llm_status"),
]


def _dynamic_status() -> str:
    try:
        from core.tools.system import snapshot
        s = snapshot()
        from services.sentinel import summary as sentinel_summary
        threat = sentinel_summary()
        return (
            f"[FRIDAY PROTOCOL — DEGRADED MODE]\n"
            f"  CPU: {s['cpu_percent']}%  |  RAM: {s['ram_used_pct']}%  |  "
            f"Disk: {s['disk_used_pct']}%\n"
            f"  Uptime: {s['uptime_hours']:.1f}h  |  "
            f"Threats (24h): {threat.get('last_24h', 0)}\n"
            f"  LLM engines: OFFLINE\n"
            f"  Time: {_now_local().strftime('%H:%M:%S')}"
        )
    except Exception as e:
        return f"[FRIDAY PROTOCOL] Status check failed: {e}"


def _handle_telemetry() -> str:
    try:
        from core.tools.system import snapshot
        s = snapshot()
        return (
            f"System telemetry:\n"
            f"  CPU: {s['cpu_percent']}%\n"
            f"  RAM: {s['ram_used_pct']}% ({s['ram_total_gb']} GB total)\n"
            f"  Disk: {s['disk_used_pct']}% ({s['disk_total_gb']} GB total)\n"
            f"  Uptime: {s['uptime_hours']:.2f} hours"
        )
    except Exception as e:
        return f"Telemetry unavailable: {e}"


def _handle_threats() -> str:
    try:
        from services.sentinel import summary, threats
        s = summary()
        recent = threats(1)
        lines = [f"Threat summary (last 24h): {s['last_24h']} events"]
        for sev, count in s.get("by_severity", {}).items():
            lines.append(f"  {sev}: {count}")
        if recent:
            lines.append(f"Most recent: {recent[-1]['category']} — {recent[-1]['detail']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Threat data unavailable: {e}"


def _handle_mac(user_input: str) -> str:
    try:
        from core.mac_dispatcher import dispatch
        return dispatch(user_input)
    except Exception as e:
        return f"Mac control error: {e}"


def _handle_memory() -> str:
    try:
        from core.memory import memory_stats, get_short_term
        stats = memory_stats()
        recent = get_short_term(3)
        lines = [
            f"Memory: {stats['short_term_turns']} short-term turns, "
            f"{stats['long_term_memories']} long-term memories"
        ]
        if recent:
            lines.append("Last 3 exchanges:")
            for t in recent[-3:]:
                lines.append(f"  [{t['ts'][:10]}] You: {t['user'][:60]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Memory unavailable: {e}"


def _handle_llm_status() -> str:
    from config.settings import GROQ_BASE_URL, OLLAMA_BASE_URL, GROQ_MODEL, OLLAMA_MODEL
    return (
        f"LLM Status:\n"
        f"  Groq ({GROQ_MODEL}): OFFLINE\n"
        f"  Ollama ({OLLAMA_MODEL} @ {OLLAMA_BASE_URL}): OFFLINE\n"
        f"  Mode: Friday Protocol (emergency fallback)\n"
        f"  Reasoning: UNAVAILABLE"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def respond(user_input: str) -> dict:
    """
    Friday Protocol response. Returns same dict shape as Brain.process_dict.
    """
    low = user_input.lower()

    # Match intent
    intent_key = "unknown"
    for pattern, key in _PATTERNS:
        if re.search(pattern, low):
            intent_key = key
            break

    if intent_key == "status":
        response = _dynamic_status()
    elif intent_key == "telemetry":
        response = _handle_telemetry()
    elif intent_key == "threats":
        response = _handle_threats()
    elif intent_key == "mac":
        response = _handle_mac(user_input)
    elif intent_key == "memory":
        response = _handle_memory()
    elif intent_key == "llm_status":
        response = _handle_llm_status()
    elif intent_key == "greet":
        response = _CANNED["greet"]
    elif intent_key == "help":
        response = _CANNED["help"]
    else:
        response = _CANNED["unknown"]

    return {
        "response":   f"[FRIDAY PROTOCOL] {response}",
        "model":      "friday-fallback",
        "provider":   "local",
        "latency_ms": 0.0,
        "meta": {
            "action":        "friday_fallback",
            "complexity":    "simple",
            "mode":          "friday_fallback",
            "was_rewritten": False,
            "issues":        ["llm_offline"],
        },
    }
