"""core/offline.py — Graceful degradation when there's no internet.

JARVIS should stay fully useful offline: local LLM, local memory, local TTS,
local system/security monitoring all keep working. Only genuinely
internet-dependent features (cloud search, cloud TTS, email, calendar,
finance, messaging) go dark.
"""
from core.state import state

OFFLINE_CAPABLE = [
    "brain", "memory", "voice_stt", "voice_tts_local", "system",
    "sentinel", "home", "notes", "tasks", "world_model",
]

ONLINE_ONLY = [
    "groq", "elevenlabs", "web_search", "email", "calendar",
    "finance", "telegram", "sms", "discord",
]


def detect() -> bool:
    """Check if internet is available."""
    try:
        import httpx
        httpx.get("https://1.1.1.1", timeout=2)
        return True
    except Exception:
        return False


def status() -> dict:
    online = detect()
    return {
        "online": online,
        "offline_capable": {f: True for f in OFFLINE_CAPABLE},
        "online_only": {f: online for f in ONLINE_ONLY},
    }


def switch_to_offline():
    from core.event_bus import bus
    state.set("internet_online", False)
    state.set("groq_available", False)
    bus.system("Internet connectivity lost. Switching to local systems. Core functionality maintained.")


def switch_to_online():
    from core.event_bus import bus
    state.set("internet_online", True)
    bus.system("Connectivity restored. All systems online.")


_was_online = True


def check_and_notify():
    """Call periodically (e.g. from a background loop) to detect transitions."""
    global _was_online
    online = detect()
    if _was_online and not online:
        switch_to_offline()
    elif not _was_online and online:
        switch_to_online()
    _was_online = online
    return online
