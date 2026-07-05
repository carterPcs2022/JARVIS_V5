"""core/epistemic.py — tracks JARVIS's own real accuracy by domain
(recorded via record_correction() when the user actually corrects him,
e.g. from core/active_learning.py), and blends that history with the
model's own stated confidence. Free — no LLM call — safe to call
anywhere; not auto-wired into the default pipeline since nothing
currently calls record_correction() with a domain label."""
import json

from config.settings import BASE_DIR

ACCURACY_FILE = BASE_DIR / "memory" / "epistemic_accuracy.json"

DOMAIN_BASELINES = {
    "python": 0.92, "javascript": 0.90, "math": 0.85, "science": 0.80,
    "history": 0.75, "medicine": 0.55, "law": 0.50, "finance": 0.65,
    "predictions": 0.45, "general": 0.70,
}

_DOMAIN_KEYWORDS = {
    "python": ("python", "def ", "import "),
    "math": ("calculate", "equation", "formula"),
    "medicine": ("medical", "symptom", "disease"),
    "law": ("legal", "contract", "court"),
    "finance": ("stock", "invest", "money"),
}


class EpistemicCalibrator:

    def get_domain(self, query: str) -> str:
        q = query.lower()
        for domain, kws in _DOMAIN_KEYWORDS.items():
            if any(k in q for k in kws):
                return domain
        return "general"

    def get_accuracy(self, domain: str) -> float:
        if ACCURACY_FILE.exists():
            try:
                data = json.loads(ACCURACY_FILE.read_text())
                if domain in data and data[domain].get("total", 0) >= 10:
                    d = data[domain]
                    return d["correct"] / d["total"]
            except Exception:
                pass
        return DOMAIN_BASELINES.get(domain, 0.70)

    def record_correction(self, domain: str, correct: bool):
        data = {}
        if ACCURACY_FILE.exists():
            try:
                data = json.loads(ACCURACY_FILE.read_text())
            except Exception:
                data = {}
        if domain not in data:
            data[domain] = {"correct": 0, "total": 0}
        data[domain]["total"] += 1
        if correct:
            data[domain]["correct"] += 1
        ACCURACY_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACCURACY_FILE.write_text(json.dumps(data, indent=2))

    def calibrate(self, query: str, base_confidence: int) -> dict:
        domain = self.get_domain(query)
        accuracy = self.get_accuracy(domain)
        adjusted = int(base_confidence * 0.6 + accuracy * 100 * 0.4)
        return {"domain": domain, "accuracy": round(accuracy * 100), "adjusted": adjusted}


epistemic = EpistemicCalibrator()
