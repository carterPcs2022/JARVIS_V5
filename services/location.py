"""services/location.py — Location awareness. JARVIS behaves differently by location."""
from __future__ import annotations
import os, socket, logging
from pathlib import Path

log = logging.getLogger(__name__)

# User-defined location → IP prefix mapping (set in .env)
# HOME_NETWORK=192.168.1, WORK_NETWORK=10.0.0
_HOME_NET = os.getenv("HOME_NETWORK", "192.168.1")
_WORK_NET = os.getenv("WORK_NETWORK", "10.0.0")

_OVERRIDE: str | None = None  # manual override


def set_location(location: str):
    """Manual override — 'home', 'work', or 'unknown'."""
    global _OVERRIDE
    _OVERRIDE = location
    log.info("Location manually set to: %s", location)


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def get_current_location() -> str:
    if _OVERRIDE:
        return _OVERRIDE

    ip = _local_ip()
    if ip:
        if _HOME_NET and ip.startswith(_HOME_NET):
            return "home"
        if _WORK_NET and ip.startswith(_WORK_NET):
            return "work"

    # Tailscale device name fallback
    tailscale_ip = os.getenv("TAILSCALE_IP", "")
    if tailscale_ip and ip == tailscale_ip:
        return "remote"

    return "unknown"


def get_location_context() -> str:
    loc = get_current_location()
    if loc == "home":
        return "User is at home. Use a casual, relaxed tone. Home automation and personal tools are available."
    if loc == "work":
        return "User is at work. Use a professional tone. Prioritize work tools and productivity."
    if loc == "remote":
        return "User is accessing remotely via Tailscale. They may be mobile or traveling."
    return ""


def location_affects_notifications(priority: str) -> bool:
    """At work, suppress low-priority personal notifications."""
    loc = get_current_location()
    if loc == "work" and priority in ("info",):
        return False
    return True
