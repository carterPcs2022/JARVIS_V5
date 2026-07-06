"""services/canary.py — digital tripwires planted in memory files. If a
canary value ever appears in an incoming request, someone read a file they
should never have had reason to read verbatim (a legitimate client never
echoes memory file contents back in a request body)."""
import json
import uuid
from pathlib import Path
from datetime import datetime

from config.settings import BASE_DIR

CANARY_FILE = BASE_DIR / "memory" / "canaries.json"

_MEMORY_FILES_TO_WATCH = [
    ("memory/short_term.json", "Short-term memory accessed"),
    ("memory/long_term.json", "Long-term memory accessed"),
    ("memory/people.json", "People database accessed"),
    ("memory/profile.json", "User profile accessed"),
]


class CanaryTokens:

    def __init__(self):
        self._local_canaries = self._load()

    def plant_local_canary(self, location: str, description: str = "") -> dict:
        canary_value = f"CANARY_{uuid.uuid4().hex.upper()}"
        canary = {
            "id": uuid.uuid4().hex[:8], "value": canary_value, "location": location,
            "description": description, "planted": datetime.now().isoformat(),
            "triggered": False, "trigger_count": 0,
        }
        self._local_canaries[canary_value] = canary
        self._save()
        return canary

    def check_canary(self, content: str) -> list[dict]:
        """Cheap substring check — zero false positives, since a canary
        value is a random UUID that would never legitimately appear."""
        triggered = []
        for value, canary in self._local_canaries.items():
            if value in content:
                canary["triggered"] = True
                canary["trigger_count"] += 1
                canary["last_triggered"] = datetime.now().isoformat()
                triggered.append(canary)

                from core.event_bus import bus
                bus.alert(
                    f"CANARY TRIGGERED: {canary['description']} at {canary['location']}. "
                    f"Someone accessed protected content.",
                    severity="critical", category="CANARY",
                )
                try:
                    from services.siem import siem
                    siem.log_event("CANARY", details={"location": canary["location"]}, severity="CRITICAL")
                except Exception:
                    pass

        if triggered:
            self._save()
        return triggered

    def plant_in_memory_files(self) -> list[dict]:
        """Plant a fresh canary UUID in each watched memory file's
        top-level dict, if the file exists and is a JSON object. Safe to
        call repeatedly (e.g. daily via scheduler) — it just replaces the
        _canary key's value each time."""
        planted = []
        for filepath, description in _MEMORY_FILES_TO_WATCH:
            canary = self.plant_local_canary(filepath, description)
            path = BASE_DIR / filepath
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    data["_canary"] = canary["value"]
                    path.write_text(json.dumps(data, indent=2))
                    planted.append(canary)
            except Exception:
                continue
        return planted

    def scan_requests(self, request_body: str) -> bool:
        return len(self.check_canary(request_body)) > 0

    def list_canaries(self) -> list[dict]:
        return list(self._local_canaries.values())

    def _load(self) -> dict:
        if CANARY_FILE.exists():
            try:
                return json.loads(CANARY_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        CANARY_FILE.parent.mkdir(parents=True, exist_ok=True)
        CANARY_FILE.write_text(json.dumps(self._local_canaries, indent=2))


canary = CanaryTokens()
