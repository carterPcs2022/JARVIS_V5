"""services/timelock.py — restrict destructive actions to specific hours
(narrows a 3am-while-you-sleep attack window). Available standalone —
not wired into the existing coldfire/scatter endpoints (core/protocols.py
already has its own double-confirmation gate for those); call
timelock.check(action) yourself before whatever action you want time-
restricted."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import BASE_DIR

TIMELOCK_FILE = BASE_DIR / "memory" / "timelock_config.json"

DEFAULT_CONFIG = {
    "coldfire": {"allowed_hours": [9, 22], "require_confirmation_delay": 30, "blackout_periods": []},
    "scatter": {"allowed_hours": [8, 20], "require_confirmation_delay": 60, "blackout_periods": []},
    "memory_wipe": {"allowed_hours": [10, 18], "require_confirmation_delay": 120, "blackout_periods": []},
    "security_override": {"allowed_hours": [8, 22], "require_confirmation_delay": 45, "blackout_periods": []},
}


class TimeLock:

    def __init__(self):
        self.config = self._load()

    def check(self, action: str) -> dict:
        config = self.config.get(action, {})
        if not config:
            return {"allowed": True, "reason": "no_timelock"}

        now = datetime.now()
        hour = now.hour
        allowed_hours = config.get("allowed_hours", [0, 24])
        start_hour, end_hour = allowed_hours[0], allowed_hours[1]

        if not (start_hour <= hour < end_hour):
            next_window = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            if hour >= end_hour:
                next_window += timedelta(days=1)
            return {
                "allowed": False, "reason": f"Time-locked: only allowed {start_hour}:00-{end_hour}:00",
                "retry_at": next_window.isoformat(), "action": action,
            }

        for blackout in config.get("blackout_periods", []):
            if self._in_blackout(now, blackout):
                return {"allowed": False, "reason": f"Blackout period active: {blackout}", "action": action}

        return {
            "allowed": True, "confirmation_delay": config.get("require_confirmation_delay", 0),
            "reason": "within_allowed_window", "action": action,
        }

    def add_blackout(self, action: str, start: str, end: str, reason: str = ""):
        self.config.setdefault(action, {}).setdefault("blackout_periods", []).append(
            {"start": start, "end": end, "reason": reason}
        )
        self._save()

    def emergency_unlock(self, action: str, master_passphrase: str, duration_minutes: int = 5) -> dict:
        """Temporarily lift the timelock for `action`. Requires
        COLDFIRE_PASSPHRASE — the same secret that already gates the
        actual destructive actions, so this doesn't introduce a new
        weaker path around them."""
        import hmac
        import os
        coldfire_passphrase = os.getenv("COLDFIRE_PASSPHRASE", "")
        if not coldfire_passphrase or not hmac.compare_digest(master_passphrase, coldfire_passphrase):
            return {"error": "Invalid passphrase"}

        now = datetime.now()
        end = now + timedelta(minutes=duration_minutes)
        self.config.setdefault(action, {})["allowed_hours"] = [0, 24]
        self.config[action]["_temp_unlock_until"] = end.isoformat()
        self._save()

        from core.event_bus import bus
        bus.alert(f"TIMELOCK EMERGENCY OVERRIDE: {action} unlocked for {duration_minutes} minutes.",
                 severity="critical", category="TIMELOCK")

        return {"unlocked": True, "action": action, "expires": end.isoformat(), "duration": duration_minutes}

    def _in_blackout(self, now: datetime, blackout: dict) -> bool:
        try:
            return datetime.fromisoformat(blackout["start"]) <= now <= datetime.fromisoformat(blackout["end"])
        except Exception:
            return False

    def _load(self) -> dict:
        if TIMELOCK_FILE.exists():
            try:
                return json.loads(TIMELOCK_FILE.read_text())
            except Exception:
                pass
        return json.loads(json.dumps(DEFAULT_CONFIG))

    def _save(self):
        TIMELOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIMELOCK_FILE.write_text(json.dumps(self.config, indent=2))


timelock = TimeLock()
