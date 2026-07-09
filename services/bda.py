"""services/bda.py — Battle Damage Assessment. Post-incident summary: what
was affected, what to rebuild, remediation steps. Deliberately NOT
auto-wired to fire on every SIEM critical alert — that would mean an
unattended Opus-tier call (the most expensive available) firing every time
a noisy detector trips, with no human in the loop to judge whether it's
warranted. Call assess() explicitly (voice command or endpoint) instead."""
import json
from pathlib import Path
from datetime import datetime

from core.llm.router import think

BDA_LOG = Path("logs/bda.json")


class BattleDamageAssessment:

    def assess(self, incident: str, threat_type: str = "", affected: list | None = None,
               tier: str = "standard") -> dict:
        affected = affected or []
        analysis = think(
            f"Battle Damage Assessment:\n"
            f"Incident: {incident}\n"
            f"Threat type: {threat_type}\n"
            f"Potentially affected: {affected}\n\n"
            f"Assess:\n"
            f"1. What was compromised (if anything)?\n"
            f"2. What data was exposed?\n"
            f"3. What systems need rebuilding?\n"
            f"4. Immediate remediation steps\n"
            f"5. Long-term hardening required\n\n"
            f"Military BDA format. Specific. Actionable.",
            force_model=tier,
        )

        bda = {
            "incident": incident, "threat_type": threat_type, "affected": affected,
            "assessment": analysis, "ts": datetime.now().isoformat(), "remediated": False,
        }
        self._save(bda)

        try:
            from services.voice import speak
            speak("Battle damage assessment complete. Remediation steps ready.")
        except Exception:
            pass

        return bda

    def mark_remediated(self, ts: str):
        log = self._load()
        for entry in log:
            if entry.get("ts") == ts:
                entry["remediated"] = True
        self._save_all(log)

    def pending_remediation(self) -> list:
        return [e for e in self._load() if not e.get("remediated")]

    def _load(self) -> list:
        if BDA_LOG.exists():
            try:
                return json.loads(BDA_LOG.read_text())
            except Exception:
                return []
        return []

    def _save(self, entry: dict):
        log = self._load()
        log.append(entry)
        self._save_all(log[-100:])

    def _save_all(self, log: list):
        BDA_LOG.parent.mkdir(parents=True, exist_ok=True)
        BDA_LOG.write_text(json.dumps(log, indent=2))


bda = BattleDamageAssessment()
