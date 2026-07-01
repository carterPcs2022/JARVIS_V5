"""
core/evolution.py — JARVIS evolution tracker.
Logs every interaction, tracks model performance, suggests improvements.
"""
import json
from datetime import datetime
from pathlib import Path
from config.settings import EVOLUTION_LOG


def _load() -> dict:
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    if EVOLUTION_LOG.exists():
        with open(EVOLUTION_LOG) as f:
            return json.load(f)
    return {"sessions": [], "model_scores": {}, "version": 5}


def _save(data: dict):
    with open(EVOLUTION_LOG, "w") as f:
        json.dump(data, f, indent=2)


def log(user_input: str, response: str, model: str,
        latency_ms: float, feedback: str = "neutral",
        was_rewritten: bool = False):
    data = _load()
    data["sessions"].append({
        "ts":           datetime.now().isoformat(),
        "model":        model,
        "latency_ms":   round(latency_ms, 2),
        "input_len":    len(user_input),
        "response_len": len(response),
        "feedback":     feedback,
        "rewritten":    was_rewritten,
    })
    data["sessions"] = data["sessions"][-1000:]

    scores = data.setdefault("model_scores", {})
    if model not in scores:
        scores[model] = {"positive": 0, "negative": 0, "neutral": 0, "total": 0}
    scores[model][feedback] = scores[model].get(feedback, 0) + 1
    scores[model]["total"] += 1
    _save(data)


def report() -> dict:
    data = _load()
    sessions = data.get("sessions", [])
    if not sessions:
        return {"status": "No data yet", "sessions": 0}

    avg_lat = sum(s["latency_ms"] for s in sessions) / len(sessions)
    pos_rate = sum(1 for s in sessions if s["feedback"] == "positive") / len(sessions) * 100
    rewrite_rate = sum(1 for s in sessions if s.get("rewritten")) / len(sessions) * 100

    return {
        "total_interactions":  len(sessions),
        "avg_latency_ms":      round(avg_lat, 2),
        "positive_rate":       f"{pos_rate:.1f}%",
        "rewrite_rate":        f"{rewrite_rate:.1f}%",
        "model_scores":        data.get("model_scores", {}),
        "last_interaction":    sessions[-1]["ts"] if sessions else None,
    }


def feedback(session_index: int, value: str) -> bool:
    """Update feedback for a session. value: positive/negative/neutral"""
    data = _load()
    sessions = data.get("sessions", [])
    if 0 <= session_index < len(sessions):
        sessions[session_index]["feedback"] = value
        _save(data)
        return True
    return False
