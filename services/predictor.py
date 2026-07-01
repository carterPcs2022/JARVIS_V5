"""services/predictor.py — Predictive intelligence. JARVIS anticipates needs."""
from __future__ import annotations
import json, logging
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
_PATTERNS_FILE = Path("data/patterns.json")


def _load() -> dict:
    _PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _PATTERNS_FILE.exists():
        try:
            return json.loads(_PATTERNS_FILE.read_text())
        except Exception:
            pass
    return {"hourly": {}, "daily": {}, "sequences": [], "topics": {}}


def _save(data: dict):
    _PATTERNS_FILE.write_text(json.dumps(data, indent=2))


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
