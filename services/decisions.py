"""services/decisions.py — Systematic decision support, like Tony never
deciding anything important without running the numbers."""
import json
from datetime import datetime
from pathlib import Path
from config.settings import BASE_DIR

DECISIONS_LOG = BASE_DIR / "memory" / "decisions.json"


def _load_log() -> list[dict]:
    if DECISIONS_LOG.exists():
        try:
            return json.loads(DECISIONS_LOG.read_text())
        except Exception:
            return []
    return []


def _save_log(log: list[dict]):
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS_LOG.write_text(json.dumps(log, indent=2))


class DecisionSupport:

    def analyze(self, decision: str, options: list[str] | None = None,
                criteria: list[str] | None = None) -> dict:
        from core.llm.router import think

        options_str = ", ".join(options) if options else "(identify likely options yourself)"
        criteria_str = ", ".join(criteria) if criteria else "(identify the most relevant criteria yourself)"

        prompt = (
            f"Decision to analyze: \"{decision}\"\n"
            f"Options: {options_str}\n"
            f"Criteria: {criteria_str}\n\n"
            "Do a full decision analysis:\n"
            "1. List the real options\n"
            "2. List the key criteria and weight each by importance (1-5)\n"
            "3. Score each option against each criterion (1-10)\n"
            "4. Calculate a weighted recommendation\n"
            "5. Note the top risks of the recommended option\n"
            "Present as a structured decision matrix, then a one-paragraph recommendation."
        )
        analysis = think(prompt, max_tokens=800)
        return {"decision": decision, "analysis": analysis, "ts": datetime.now().isoformat()}

    def pros_cons(self, topic: str) -> dict:
        from core.llm.router import think
        raw = think(
            f"Give a pros/cons analysis of: \"{topic}\". "
            "Format as 'PROS:' then bullet list, then 'CONS:' then bullet list.",
            max_tokens=400,
        )
        pros, cons = [], []
        section = None
        for line in raw.split("\n"):
            if "PROS" in line.upper():
                section = "pros"; continue
            if "CONS" in line.upper():
                section = "cons"; continue
            item = line.strip("-• ").strip()
            if item and section == "pros":
                pros.append(item)
            elif item and section == "cons":
                cons.append(item)
        return {"topic": topic, "pros": pros, "cons": cons}

    def devil_advocate(self, decision: str, chosen_option: str) -> str:
        from core.llm.router import think
        prompt = (
            f"The decision is: \"{decision}\". The chosen option is: \"{chosen_option}\".\n\n"
            "Argue AGAINST this choice as strongly and fairly as possible — steelman the "
            "opposing view. Don't be contrarian for its own sake; make the strongest honest case."
        )
        return think(prompt, max_tokens=400)

    def risk_analysis(self, plan: str) -> dict:
        from core.llm.router import think
        raw = think(
            f"Analyze risks in this plan: \"{plan}\"\n\n"
            "For each risk give: description, likelihood (low/medium/high), "
            "impact (low/medium/high), and mitigation. Format as a numbered list.",
            max_tokens=500,
        )
        return {"plan": plan, "risk_analysis": raw}

    def swot(self, subject: str) -> dict:
        from core.llm.router import think
        raw = think(
            f"Do a SWOT analysis of: \"{subject}\". "
            "Sections: STRENGTHS, WEAKNESSES, OPPORTUNITIES, THREATS. Bullet points under each.",
            max_tokens=500,
        )
        sections = {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}
        current = None
        for line in raw.split("\n"):
            up = line.upper()
            if "STRENGTH" in up: current = "strengths"; continue
            if "WEAKNESS" in up: current = "weaknesses"; continue
            if "OPPORTUNIT" in up: current = "opportunities"; continue
            if "THREAT" in up: current = "threats"; continue
            item = line.strip("-• ").strip()
            if item and current:
                sections[current].append(item)
        return {"subject": subject, **sections}

    def log_decision(self, decision: str, chosen_option: str = "", notes: str = "") -> dict:
        log = _load_log()
        entry = {
            "id": len(log) + 1, "decision": decision, "chosen_option": chosen_option,
            "notes": notes, "ts": datetime.now().isoformat(), "outcome": None,
        }
        log.append(entry)
        _save_log(log)
        return entry

    def record_outcome(self, decision_id: int, outcome: str) -> dict:
        log = _load_log()
        for entry in log:
            if entry["id"] == decision_id:
                entry["outcome"] = outcome
                entry["outcome_ts"] = datetime.now().isoformat()
                _save_log(log)
                return entry
        return {"error": "decision not found"}

    def decision_log(self) -> list[dict]:
        return list(reversed(_load_log()))

    def pending_followups(self, days: int = 30) -> list[dict]:
        """Decisions logged 30+ days ago with no recorded outcome — worth checking in on."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        return [
            e for e in _load_log()
            if e.get("outcome") is None and datetime.fromisoformat(e["ts"]) <= cutoff
        ]


decisions = DecisionSupport()
