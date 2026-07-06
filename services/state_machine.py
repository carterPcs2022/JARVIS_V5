"""services/state_machine.py — cryptographic state machine.

JARVIS can only move through explicitly defined state transitions, and
some transitions require an authorization token. This is a governance/
audit layer available for callers who want a formal state model with
built-in authorization gates — it is intentionally NOT wired to actually
execute Coldfire/Lockdown itself. core/protocols.py already has its own
tested double-confirmation gates for those (Protocol 3 Lockdown, Protocol
6 Coldfire); routing them through this machine as well would mean two
independent systems could each believe they're the source of truth for
"is JARVIS in lockdown," which is exactly the kind of desync a security
system shouldn't have. Use transition() to track/gate your own custom
state needs; call the existing protocol functions directly for the real
lockdown/coldfire actions.
"""
import hmac
import json
import os
from datetime import datetime
from enum import Enum

from config.settings import BASE_DIR


class JarvisState(Enum):
    STANDBY     = "standby"
    ONLINE      = "online"
    ALERT       = "alert"
    LOCKDOWN    = "lockdown"
    COLDFIRE    = "coldfire"
    MAINTENANCE = "maintenance"


VALID_TRANSITIONS = {
    JarvisState.STANDBY:     [JarvisState.ONLINE],
    JarvisState.ONLINE:      [JarvisState.ALERT, JarvisState.MAINTENANCE, JarvisState.STANDBY],
    JarvisState.ALERT:       [JarvisState.ONLINE, JarvisState.LOCKDOWN],
    JarvisState.LOCKDOWN:    [JarvisState.ONLINE, JarvisState.COLDFIRE],
    JarvisState.COLDFIRE:    [],  # terminal
    JarvisState.MAINTENANCE: [JarvisState.ONLINE],
}

TRANSITION_AUTH = {
    (JarvisState.LOCKDOWN, JarvisState.ONLINE):   "avengers",
    (JarvisState.ALERT,    JarvisState.LOCKDOWN): "api_token",
    (JarvisState.LOCKDOWN, JarvisState.COLDFIRE): "coldfire",
}

STATE_FILE = BASE_DIR / "memory" / "jarvis_state_machine.json"


class CryptoStateMachine:

    def __init__(self):
        self._state = JarvisState.STANDBY
        self._history: list[dict] = []
        self._load()

    def transition(self, target: JarvisState, auth_token: str = "") -> dict:
        current = self._state

        valid_targets = VALID_TRANSITIONS.get(current, [])
        if target not in valid_targets:
            return {"success": False, "reason": f"Cannot transition from {current.value} to {target.value}",
                    "current": current.value}

        auth_key = (current, target)
        if auth_key in TRANSITION_AUTH:
            required_type = TRANSITION_AUTH[auth_key]
            if not self._verify_auth(auth_token, required_type):
                return {"success": False, "reason": f"Authorization required: {required_type}",
                        "current": current.value}

        self._state = target
        record = {"from": current.value, "to": target.value,
                   "ts": datetime.now().isoformat(), "auth": bool(auth_token)}
        self._history.append(record)
        self._save()

        try:
            from services.audit_log import audit_log
            audit_log.record(f"state_transition_{current.value}_to_{target.value}", "jarvis", record, "success")
        except Exception:
            pass

        try:
            from core.event_bus import bus
            bus.system(f"State transition: {current.value} -> {target.value}")
        except Exception:
            pass

        return {"success": True, "from": current.value, "to": target.value, "ts": record["ts"]}

    def _verify_auth(self, token: str, auth_type: str) -> bool:
        required = {
            "api_token": os.getenv("JARVIS_API_TOKEN", ""),
            "avengers":  os.getenv("AVENGERS_PASSPHRASE", ""),
            "coldfire":  os.getenv("COLDFIRE_PASSPHRASE", ""),
        }.get(auth_type, "")
        if not required:
            return False
        return hmac.compare_digest(token, required)

    def get_state(self) -> str:
        return self._state.value

    def get_history(self) -> list:
        return self._history[-20:]

    def _load(self):
        if not STATE_FILE.exists():
            return
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            self._state = JarvisState(data.get("state", "standby"))
            self._history = data.get("history", [])
        except Exception:
            self._state = JarvisState.STANDBY

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "state": self._state.value,
                "history": self._history[-100:],
                "saved": datetime.now().isoformat(),
            }, f, indent=2)


state_machine = CryptoStateMachine()
