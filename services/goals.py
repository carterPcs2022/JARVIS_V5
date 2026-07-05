"""services/goals.py — goal and mission-objective tracking.
Shares memory/goals.json with services/awareness.py's check_goals(), which
alerts on approaching deadlines; this module is the writer side."""
import json
import uuid
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

GOALS_FILE = BASE_DIR / "memory" / "goals.json"


def _load() -> list[dict]:
    if GOALS_FILE.exists():
        try:
            data = json.loads(GOALS_FILE.read_text())
            if isinstance(data, dict):
                return data.get("goals", [])
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save(goals: list[dict]):
    GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOALS_FILE.write_text(json.dumps(goals, indent=2))


def add_goal(title: str, description: str = "", target_date: str = "", priority: str = "medium") -> dict:
    goal = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "description": description,
        "deadline": target_date,
        "priority": priority,
        "created": datetime.now().isoformat(),
        "done": False,
    }
    goals = _load()
    goals.append(goal)
    _save(goals)
    return goal


def add_mission(title: str, deadline: str, priority: str = "high") -> dict:
    """Add a time-critical mission objective. JARVIS counts down and can
    alert at intervals (1 week, 3 days, 24 hours, 1 hour) via
    services.awareness.check_goals()."""
    deadline_dt = datetime.fromisoformat(deadline)
    now = datetime.now()
    hours_left = (deadline_dt - now).total_seconds() / 3600

    mission = add_goal(
        title=title,
        description=f"MISSION DEADLINE: {deadline}",
        target_date=deadline,
        priority=priority,
    )
    mission["mission_mode"] = True
    mission["hours_left"] = round(hours_left, 1)
    mission["status_phrase"] = _mission_status(hours_left)
    return mission


def _mission_status(hours: float) -> str:
    if hours < 0:   return "MISSION OVERDUE"
    if hours < 1:   return f"CRITICAL — {int(hours * 60)} MINUTES"
    if hours < 24:  return f"URGENT — {int(hours)} HOURS"
    if hours < 72:  return f"APPROACHING — {int(hours / 24)} DAYS"
    if hours < 168: return f"ACTIVE — {int(hours / 24)} DAYS"
    return f"SCHEDULED — {int(hours / 24)} DAYS"


def get_goals(status: str = "active") -> list[dict]:
    """status: 'active' (not done), 'done', or 'all'."""
    goals = _load()
    if status == "active":
        return [g for g in goals if not g.get("done")]
    if status == "done":
        return [g for g in goals if g.get("done")]
    return goals


def list_missions() -> list[dict]:
    """All goals with mission_mode/deadline set, with live hours_left/status."""
    missions = []
    for g in _load():
        if not g.get("deadline"):
            continue
        try:
            hours_left = (datetime.fromisoformat(g["deadline"]) - datetime.now()).total_seconds() / 3600
        except Exception:
            continue
        m = dict(g)
        m["hours_left"] = round(hours_left, 1)
        m["status_phrase"] = _mission_status(hours_left)
        missions.append(m)
    return sorted(missions, key=lambda m: m["hours_left"])
