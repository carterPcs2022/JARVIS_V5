"""services/red_team.py — JARVIS attacks himself: three-phase red team
exercise (recon -> attack vectors -> defenses) using the top reasoning
tiers. Manual/on-demand (POST /stark/security/redteam) — not auto-
scheduled weekly by default; 2x fable calls + 1 opus call per run is real
spend to put on autopilot without the owner asking each time."""
import json
from pathlib import Path
from datetime import datetime

from config.settings import BASE_DIR

REPORT_FILE = BASE_DIR / "logs" / "red_team.json"


class RedTeam:

    def run_exercise(self) -> dict:
        from core.llm.router import think

        print("[RedTeam] Starting red team exercise...")

        recon = think(
            f"Red team phase 1: Reconnaissance.\n"
            f"Target: JARVIS V5 personal AI on Render\n\n"
            f"What information can be gathered from:\n"
            f"1. Public HTTP headers\n2. Error messages\n3. API response structure\n"
            f"4. Timing patterns\n5. The /docs endpoint (FastAPI)\n\n"
            f"What does this reveal about the system?",
            force_model="fable",
        )

        vectors = think(
            f"Red team phase 2: Attack vectors.\n\n"
            f"Based on reconnaissance:\n{recon[:500]}\n\n"
            f"Identify the top 5 attack vectors ranked by:\n"
            f"1. Ease of exploitation\n2. Potential impact\n3. Likelihood of success\n\n"
            f"For each vector: what would the attacker do, what would they gain, how to detect it.",
            force_model="fable",
        )

        defenses = think(
            f"Red team phase 3: Defense recommendations.\n\n"
            f"Attack vectors identified:\n{vectors[:500]}\n\n"
            f"For each attack vector, provide:\n"
            f"1. Immediate mitigation (do now)\n2. Short-term hardening (this week)\n"
            f"3. Long-term architecture change\n\nPrioritize by risk. Be specific.",
            force_model="opus",
        )

        report = {
            "ts": datetime.now().isoformat(), "recon": recon,
            "attack_vectors": vectors, "defenses": defenses, "status": "complete",
        }

        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, indent=2))

        from core.event_bus import bus
        bus.system("Red team exercise complete. Report available at GET /stark/security/redteam/last")

        return report

    def last_report(self) -> dict | None:
        if REPORT_FILE.exists():
            try:
                return json.loads(REPORT_FILE.read_text())
            except Exception:
                return None
        return None


red_team = RedTeam()
