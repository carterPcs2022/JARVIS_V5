"""services/home_automation.py — full smart-home scene management.

Talks to Home Assistant's REST API (https://www.home-assistant.io/docs/rest_api/)
when HOME_ASSISTANT_URL/HOME_ASSISTANT_TOKEN are configured. Without them, each
subsystem degrades to a clearly-labeled no-op instead of pretending to control
hardware that isn't wired up — same pattern as services/calendar_intel.py
(empty list without a token) and services/finance.py ("connect an account").
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

HOME_ASSISTANT_URL   = os.getenv("HOME_ASSISTANT_URL", "")
HOME_ASSISTANT_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")

SCENES: dict[str, dict] = {
    "morning": {
        "lights":      {"brightness": 80, "color": "warm"},
        "temperature": 70,
        "music":       "happy",
        "blinds":      "open",
    },
    "movie": {
        "lights":      {"brightness": 10, "color": "blue"},
        "temperature": 68,
        "blinds":      "closed",
    },
    "focus": {
        "lights":      {"brightness": 90, "color": "cool"},
        "temperature": 69,
        "music":       "focus",
        "blinds":      "half",
    },
    "night": {
        "lights":      {"brightness": 0},
        "temperature": 66,
        "blinds":      "closed",
    },
    "away": {
        "lights":   {"brightness": 0},
        "temperature": 62,
        "security": "armed",
    },
    "red_alert": {
        "lights":      {"brightness": 100, "color": "red"},
        "security":    "armed",
    },
    "workout": {
        "lights":      {"brightness": 100, "color": "energizing"},
        "temperature": 65,
        "music":       "energy",
    },
    "reading": {
        "lights":      {"brightness": 70, "color": "warm"},
        "temperature": 70,
        "music":       "relax",
    },
}

# Phrases that trigger each scene from a chat/voice command — checked in
# order, first match wins.
_VOICE_TRIGGERS: list[tuple[str, str]] = [
    ("movie mode", "movie"),
    ("good morning", "morning"),
    ("good night", "night"),
    ("i'm leaving", "away"),
    ("im leaving", "away"),
    ("leaving now", "away"),
    ("focus mode", "focus"),
    ("workout mode", "workout"),
    ("reading mode", "reading"),
]


def _ha_configured() -> bool:
    return bool(HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN)


def _ha_call(domain: str, service: str, data: dict) -> dict:
    import httpx
    try:
        r = httpx.post(
            f"{HOME_ASSISTANT_URL.rstrip('/')}/api/services/{domain}/{service}",
            json=data,
            headers={"Authorization": f"Bearer {HOME_ASSISTANT_TOKEN}", "Content-Type": "application/json"},
            timeout=5,
        )
        return {"ok": r.status_code < 300, "status": r.status_code}
    except Exception as e:
        log.debug("Home Assistant call failed (%s.%s): %s", domain, service, e)
        return {"ok": False, "error": str(e)}


def list_devices() -> dict:
    """List entities Home Assistant currently knows about, via its
    /api/states endpoint. Read-only — same not_configured guard and httpx
    pattern as every other function in this module."""
    if not _ha_configured():
        return {"status": "not_configured"}
    import httpx
    try:
        r = httpx.get(
            f"{HOME_ASSISTANT_URL.rstrip('/')}/api/states",
            headers={"Authorization": f"Bearer {HOME_ASSISTANT_TOKEN}"},
            timeout=5,
        )
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code}
        states = r.json()
        return {
            "ok": True,
            "count": len(states),
            "devices": [
                {
                    "entity_id": s.get("entity_id"),
                    "state": s.get("state"),
                    "name": (s.get("attributes") or {}).get("friendly_name", s.get("entity_id")),
                }
                for s in states
            ],
        }
    except Exception as e:
        log.debug("Home Assistant list_devices failed: %s", e)
        return {"ok": False, "error": str(e)}


def set_lights(**config) -> dict:
    if not _ha_configured():
        return {"status": "not_configured", "requested": config}
    return _ha_call("light", "turn_on", {"entity_id": "all", **config})


def set_temperature(target: float) -> dict:
    if not _ha_configured():
        return {"status": "not_configured", "requested": target}
    return _ha_call("climate", "set_temperature", {"entity_id": "climate.home", "temperature": target})


def control_blinds(position: str) -> dict:
    if not _ha_configured():
        return {"status": "not_configured", "requested": position}
    service = {"open": "open_cover", "closed": "close_cover", "half": "set_cover_position"}.get(position, "open_cover")
    data = {"entity_id": "all"}
    if service == "set_cover_position":
        data["position"] = 50
    return _ha_call("cover", service, data)


def arm_security(mode: str) -> dict:
    if not _ha_configured():
        return {"status": "not_configured", "requested": mode}
    service = "alarm_arm_away" if mode == "armed" else "alarm_disarm"
    return _ha_call("alarm_control_panel", service, {"entity_id": "alarm_control_panel.home"})


def activate_scene(scene_name: str) -> dict:
    """Activate a full home scene — lights, temperature, music, blinds, security."""
    scene = SCENES.get(scene_name.lower())
    if not scene:
        return {"error": f"Unknown scene: {scene_name}. Available: {', '.join(SCENES)}"}

    results = {}
    for system, config in scene.items():
        try:
            if system == "lights":
                results["lights"] = set_lights(**config)
            elif system == "temperature":
                results["temperature"] = set_temperature(config)
            elif system == "music":
                from services.spotify import spotify
                results["music"] = spotify.play_mood(config) if spotify.is_connected() else {"status": "spotify_not_connected"}
            elif system == "blinds":
                results["blinds"] = control_blinds(config)
            elif system == "security":
                results["security"] = arm_security(config)
        except Exception as e:
            results[system] = {"error": str(e)}

    return {"scene": scene_name, "results": results}


def handle_scene_command(text: str) -> str | None:
    """Returns a JARVIS response string if `text` is a scene voice command, else None."""
    t = text.lower()
    for phrase, scene in _VOICE_TRIGGERS:
        if phrase in t:
            activate_scene(scene)
            return f"{scene.capitalize()} mode activated."
    return None
