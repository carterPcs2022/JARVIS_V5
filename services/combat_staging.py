"""services/combat_staging.py — Phase 2 of combat mode: pre-staged actions.

V1 scope: "security"-category engages only. When combat mode engages for a
security threat, pre-run a network scan in the background so a likely
follow-up ("who's on my network", "check for intruders") gets an instant
answer from the cached result instead of a fresh multi-second scan.

"physical" and "emergency" categories deliberately stage nothing yet —
the two plausible targets for those (home automation arm/scene,
emergency-contact notification) both depend on env vars not confirmed
live in this deployment (HOME_ASSISTANT_URL/TOKEN and
EMERGENCY_CONTACT_EMAIL/NAME are unset locally, and combat_mode.py's
existing activate_scene("red_alert") call on every engage() already
covers home automation's real side effect — there's nothing further to
stage there). Expand this module once there's something real to point at.

Staging is read-only: the exact same network_intel.scan_network() call
/stark/network already performs on demand elsewhere in the app, just
triggered proactively. Nothing here ever executes a side-effecting
action — see services/combat_mode.py's engage()/disengage() for the
actual state-mutating actions (HA scene, voice alert), which this module
doesn't touch.
"""
import threading
import time

from config.settings import COMBAT_MODE_TIMEOUT_MINUTES

# Matches combat_mode's own auto-timeout — a scan from a threat window
# that's already closed shouldn't silently answer a much-later question.
_STAGE_TTL_SECONDS = COMBAT_MODE_TIMEOUT_MINUTES * 60

# Same convention as services/home_automation.py's _VOICE_TRIGGERS —
# plain substring matching, not an LLM call, so a fast-path hit costs
# no extra latency or API spend (the whole point of staging).
_NETWORK_SCAN_TRIGGERS = [
    "who's on my network", "whos on my network", "who is on my network",
    "check for intruders", "any intruders",
    "unknown device", "unknown devices",
    "who's connected", "whos connected", "who is connected",
    "scan the network", "scan my network",
    "network status", "check my network", "check the network",
]

# Single dict, not per-session-keyed — this process runs one uvicorn
# worker (see other modules' comments on the same point), and combat
# mode itself is already a single global state machine (services/
# combat_mode.py has no per-user session concept either), so there's
# nothing to key against beyond "the current engage."
_staged: dict = {}


def stage_for_category(category: str):
    """Called from combat_mode.engage() right after a real engage.
    Runs the scan in a background thread — never blocks engage() itself,
    which needs to stay fast since it's on the hot path of every
    classified message."""
    if category != "security":
        return  # V1 scope — see module docstring
    threading.Thread(target=_run_network_scan, daemon=True).start()


def _run_network_scan():
    try:
        from services.network_intel import network
        devices = network.scan_network()
        _staged["category"] = "security"
        _staged["devices"] = devices
        _staged["staged_at"] = time.time()
        print(f"[CombatStaging] Pre-staged network scan: {len(devices)} device(s)")
    except Exception as e:
        # Never surfaces to the user — a failed stage just means the next
        # matching question falls through to normal (slower) processing.
        print(f"[CombatStaging] Staging failed (non-fatal): {e}")


def clear():
    """Called from combat_mode.disengage() — a stale stage from a past
    engage shouldn't answer a question asked in an unrelated later
    session."""
    _staged.clear()


def try_fast_path(message: str) -> dict | None:
    """Returns a ready response dict if `message` matches a fresh staged
    action, else None — caller falls through to normal processing.
    Never raises: any failure here just means no fast path, not an error
    surfaced to the user."""
    try:
        if "devices" not in _staged:
            return None
        if time.time() - _staged.get("staged_at", 0) > _STAGE_TTL_SECONDS:
            return None

        msg_lower = message.lower()
        if not any(trigger in msg_lower for trigger in _NETWORK_SCAN_TRIGGERS):
            return None

        devices = _staged["devices"]
        unknown = [d for d in devices if not d.get("trusted")]
        if unknown:
            names = ", ".join(d.get("hostname") or d.get("ip", "unknown") for d in unknown)
            response = (f"I already checked, sir — {len(unknown)} unrecognized "
                        f"device(s) on the network: {names}.")
        elif devices:
            response = (f"I already checked, sir — all {len(devices)} device(s) "
                        f"on the network are recognized. Nothing out of place.")
        else:
            response = "I already checked, sir — no devices found on the network."

        return {
            "response":   response,
            "model":      "staged",
            "provider":   "combat_staging",
            "latency_ms": 0,
            "meta": {
                "action":        "combat_staged_network_scan",
                "complexity":    "simple",
                "mode":          "combat_fast_path",
                "was_rewritten": False,
                "issues":        [],
            },
        }
    except Exception as e:
        print(f"[CombatStaging] try_fast_path() failed (non-fatal): {e}")
        return None
