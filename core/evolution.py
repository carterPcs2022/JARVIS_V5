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
    default = {"sessions": [], "model_scores": {}, "version": 5}
    if EVOLUTION_LOG.exists():
        try:
            with open(EVOLUTION_LOG) as f:
                return json.load(f)
        except Exception:
            return default
    return default


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


# ── Fable 5 usage/cost tracking ────────────────────────────────────────────────
from config.settings import BASE_DIR
FABLE_STATS_FILE = BASE_DIR / "memory" / "fable_stats.json"

# Anthropic's published per-million-token pricing for their top-end model
# class (same bracket as Opus) — an estimate, not a billing source of
# truth. Check the Anthropic Console for actual spend.
_FABLE_INPUT_COST_PER_M = 15.0
_FABLE_OUTPUT_COST_PER_M = 75.0


def _load_fable_stats() -> dict:
    if FABLE_STATS_FILE.exists():
        try:
            return json.loads(FABLE_STATS_FILE.read_text())
        except Exception:
            pass
    return {"total_calls": 0, "total_think_tokens": 0, "total_out_tokens": 0, "queries": []}


def _save_fable_stats(stats: dict):
    FABLE_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FABLE_STATS_FILE.write_text(json.dumps(stats, indent=2))


def record_fable_response(query: str, response: str, thinking_tokens: int, response_tokens: int):
    """Track Fable 5 usage — called from core/llm/router.py after every
    successful Fable call."""
    stats = _load_fable_stats()
    stats["total_calls"] = stats.get("total_calls", 0) + 1
    stats["total_think_tokens"] = stats.get("total_think_tokens", 0) + thinking_tokens
    stats["total_out_tokens"] = stats.get("total_out_tokens", 0) + response_tokens
    stats.setdefault("queries", []).append({
        "query": (query or "")[:100], "think_t": thinking_tokens, "out_t": response_tokens,
        "ts": datetime.now().isoformat(),
    })
    stats["queries"] = stats["queries"][-200:]
    _save_fable_stats(stats)


def fable_usage_report() -> dict:
    """How much Fable have we used, and roughly what has it cost?"""
    stats = _load_fable_stats()
    calls = stats.get("total_calls", 0)
    think_tok = stats.get("total_think_tokens", 0)
    out_tok = stats.get("total_out_tokens", 0)

    input_cost = (think_tok / 1_000_000) * _FABLE_INPUT_COST_PER_M
    output_cost = (out_tok / 1_000_000) * _FABLE_OUTPUT_COST_PER_M
    total_cost = round(input_cost + output_cost, 4)

    return {
        "total_fable_calls": calls,
        "thinking_tokens_used": think_tok,
        "output_tokens_used": out_tok,
        "estimated_cost_usd": total_cost,
        "avg_think_per_call": think_tok // max(calls, 1),
        "note": "Estimate based on published per-token pricing, not actual billing — check the Anthropic Console for real spend.",
    }
