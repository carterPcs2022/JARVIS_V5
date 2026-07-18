"""services/predictor.py — Predictive intelligence. JARVIS anticipates needs."""
from __future__ import annotations
import json, logging
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
_PATTERNS_FILE = Path("data/patterns.json")


_DEFAULT = {"hourly": {}, "daily": {}, "sequences": [], "topics": {}}
_TURSO_KEY = "data/patterns.json"


def _load() -> dict:
    _PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Turso first — same durable-copy pattern as core/memory.py, since this
    # file used to be plain local JSON and silently wiped on every Render
    # redeploy along with the rest of the ephemeral disk.
    from core.turso_store import get as turso_get
    remote = turso_get(_TURSO_KEY)
    if remote is not None:
        return remote

    if _PATTERNS_FILE.exists():
        try:
            return json.loads(_PATTERNS_FILE.read_text())
        except Exception:
            pass
    return dict(_DEFAULT)


def _save(data: dict):
    _PATTERNS_FILE.write_text(json.dumps(data, indent=2))

    from core.turso_store import put as turso_put
    turso_put(_TURSO_KEY, data)


def record_query(query: str):
    """Call after every user message to build pattern history."""
    data = _load()
    now  = datetime.now()
    hour = str(now.hour)
    day  = now.strftime("%A")

    # Hourly patterns
    data["hourly"].setdefault(hour, []).append(query[:80])
    data["hourly"][hour] = data["hourly"][hour][-50:]

    # Daily patterns
    data["daily"].setdefault(day, []).append(query[:80])
    data["daily"][day] = data["daily"][day][-50:]

    # Topic frequency
    for word in set(query.lower().split()):
        if len(word) > 4:
            data["topics"][word] = data["topics"].get(word, 0) + 1

    # Sequences (last query → this query)
    data["sequences"].append(query[:80])
    data["sequences"] = data["sequences"][-200:]

    _save(data)


def analyze_patterns() -> dict:
    data  = _load()
    now   = datetime.now()
    hour  = str(now.hour)
    day   = now.strftime("%A")

    hourly_common  = Counter(data["hourly"].get(hour, [])).most_common(3)
    daily_common   = Counter(data["daily"].get(day, [])).most_common(3)
    top_topics     = sorted(data["topics"].items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "hour":          hour,
        "day":           day,
        "common_this_hour": [q for q, _ in hourly_common],
        "common_today":     [q for q, _ in daily_common],
        "top_topics":       [t for t, _ in top_topics],
    }


def get_proactive_suggestions() -> list[str]:
    suggestions = []
    now = datetime.now()

    try:
        from core.tools.system import snapshot
        sys = snapshot()
        if sys.get("disk_used_pct", 0) > 75:
            suggestions.append(f"Disk is at {sys['disk_used_pct']:.0f}% — want me to find large files?")
        if sys.get("cpu_percent", 0) > 85:
            suggestions.append(f"CPU running hot at {sys['cpu_percent']:.0f}%.")
    except Exception:
        pass

    try:
        from services.backup import last_backup_age_hours
        age = last_backup_age_hours()
        if age and age > 72:
            suggestions.append(f"It's been {int(age//24)} days since your last backup.")
    except Exception:
        pass

    patterns = analyze_patterns()
    if patterns["common_this_hour"]:
        suggestions.append(f"You usually ask about '{patterns['common_this_hour'][0]}' around this time.")

    if now.weekday() == 0 and now.hour == 9:
        suggestions.append("Monday morning — want your weekly briefing?")

    if now.hour == 18:
        suggestions.append("Winding down time — any tasks to close out today?")

    return suggestions[:2]


def predict_next_query(last_query: str) -> str | None:
    low = last_query.lower()
    if "weather" in low:
        return "traffic conditions"
    if "email" in low or "inbox" in low:
        return "any urgent items to reply to"
    if "spotify" in low or "music" in low or "playing" in low:
        return "adjust the volume"
    if "backup" in low:
        return "check disk space"
    if "news" in low:
        return "today's headlines summary"
    return None


# ── Predictive pre-loading — pre-generate likely responses ────────────────────
#
# SAFETY NOTE: preload_likely_response() runs the FULL brain pipeline (a real
# LLM call) for a guessed query. start_background_prediction() would run this
# every 60 seconds, forever, regardless of whether you're even at your
# computer — a permanent background LLM-call generator. Given this session's
# repeated fight against Groq rate limits, that loop is built but NOT started
# automatically. Call predictor_engine.start_background_prediction() explicitly
# if you want it, or trigger preload_likely_response() on-demand instead (e.g.
# right when a physical button like the iPhone Action Button is pressed, so
# it's at most one extra guess per deliberate action, not a standing loop).

import threading
import time as _time
from collections import defaultdict as _defaultdict


class PredictiveEngine:

    def __init__(self):
        self._prediction_cache: dict = {}
        self._running = False

    def preload_likely_response(self):
        """Predict the most likely next query and pre-generate its response
        into the cache. One real LLM call — call this deliberately, not on a loop."""
        patterns = analyze_patterns()
        candidates = patterns.get("common_this_hour", [])
        if not candidates:
            return
        predicted = candidates[0]
        if predicted in self._prediction_cache:
            return

        print(f"[Predictor] Pre-loading: {predicted[:50]}")
        try:
            from core.brain_v2 import brain
            result = brain.process_dict(predicted)
            self._prediction_cache[predicted] = {
                "response": result["response"], "cached_at": _time.time(), "prediction": True,
            }
        except Exception as e:
            print(f"[Predictor] Pre-load failed: {e}")

    def get_cached_response(self, query: str) -> dict | None:
        """Cache expires after 5 minutes."""
        cached = self._prediction_cache.get(query)
        if not cached:
            return None
        if _time.time() - cached["cached_at"] > 300:
            del self._prediction_cache[query]
            return None
        print("[Predictor] Cache hit! Instant response.")
        return cached

    def start_background_prediction(self):
        """Opt-in continuous prediction loop — NOT started by default (see
        module-level safety note above). One real Groq call per minute,
        forever, once started."""
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.preload_likely_response()
                except Exception:
                    pass
                _time.sleep(60)

        threading.Thread(target=_loop, daemon=True, name="jarvis-predictor").start()

    def stop_background_prediction(self):
        self._running = False


predictor_engine = PredictiveEngine()


def run_simulation(scenario: str, variables: dict | None = None, time_horizon: str = "1 week") -> dict:
    """
    Run a predictive simulation.
    "JARVIS if I keep spending at this rate..." / "how long until disk is full?"
    """
    from core.llm.router import think
    result = think(
        f"Run a predictive simulation:\nScenario: {scenario}\n"
        f"Variables: {json.dumps(variables or {})}\nTime horizon: {time_horizon}\n\n"
        f"Provide: most likely outcome, best case, worst case, key risk factors, "
        f"recommendation. Be specific with numbers.",
        force_model="reasoning",
    )
    return {"scenario": scenario, "time_horizon": time_horizon, "simulation": result}
