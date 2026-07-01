"""services/fitness.py — Health & fitness coaching. Not medical advice —
rough, practical guidance grounded in whatever health data JARVIS has."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from config.settings import BASE_DIR

WORKOUTS_FILE = BASE_DIR / "memory" / "workouts.json"
NUTRITION_FILE = BASE_DIR / "memory" / "nutrition.json"


def _load(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return []
    return []


def _save(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class FitnessCoach:

    def workout_plan(self, goal: str = "general fitness", days_per_week: int = 3,
                      equipment: list[str] | None = None, duration_minutes: int = 45) -> dict:
        from core.llm.router import think
        equip = ", ".join(equipment) if equipment else "bodyweight only"
        prompt = (
            f"Build a {days_per_week}-day/week workout plan for the goal '{goal}', "
            f"{duration_minutes} minutes per session, using: {equip}. "
            f"Give a day-by-day breakdown with specific exercises, sets, and reps."
        )
        return {"goal": goal, "plan": think(prompt, max_tokens=700)}

    def log_workout(self, exercises: list[dict]) -> dict:
        workouts = _load(WORKOUTS_FILE)
        entry = {"ts": datetime.now().isoformat(), "exercises": exercises}
        workouts.append(entry)
        _save(WORKOUTS_FILE, workouts)

        streak = self._current_streak(workouts)
        return {"logged": True, "streak_days": streak}

    def _current_streak(self, workouts: list[dict]) -> int:
        dates = sorted({w["ts"][:10] for w in workouts}, reverse=True)
        if not dates:
            return 0
        streak = 1
        today = datetime.now().date()
        if dates[0] != str(today) and dates[0] != str(today - timedelta(days=1)):
            return 0
        for i in range(1, len(dates)):
            prev = datetime.fromisoformat(dates[i - 1]).date()
            cur = datetime.fromisoformat(dates[i]).date()
            if (prev - cur).days == 1:
                streak += 1
            else:
                break
        return streak

    def suggest_today(self) -> str:
        workouts = _load(WORKOUTS_FILE)
        last_workout = workouts[-1] if workouts else None

        health_note = ""
        try:
            from services.health import health_monitor
            latest = health_monitor.get_latest_health()
            hrv = latest.get("hrv")
            sleep = latest.get("sleep_hours")
            if hrv is not None:
                health_note += f"HRV: {hrv}ms. "
            if sleep is not None:
                health_note += f"Sleep last night: {sleep}h. "
        except Exception:
            pass

        try:
            from core.llm.router import think
            prompt = (
                f"Last workout: {last_workout}\n{health_note}\n"
                "Suggest what today's training focus should be (rest, light recovery, "
                "or intense session) and why, in 1-2 sentences."
            )
            return think(prompt, max_tokens=150)
        except Exception:
            return "No recent data to base a recommendation on — how are you feeling today?"

    def nutrition_log(self, meal: str) -> dict:
        try:
            from core.llm.router import think
            raw = think(
                f"Estimate rough macros/calories for this meal (not medical advice, "
                f"just a reasonable estimate): \"{meal}\". "
                f"Format: Calories: X | Protein: Xg | Carbs: Xg | Fat: Xg",
                max_tokens=80,
            )
        except Exception:
            raw = "Estimate unavailable."

        log = _load(NUTRITION_FILE)
        entry = {"ts": datetime.now().isoformat(), "meal": meal, "estimate": raw}
        log.append(entry)
        _save(NUTRITION_FILE, log)
        return entry

    def fitness_summary(self, period: str = "week") -> str:
        days = 7 if period == "week" else 30
        cutoff = datetime.now() - timedelta(days=days)

        workouts = [w for w in _load(WORKOUTS_FILE) if datetime.fromisoformat(w["ts"]) >= cutoff]

        steps_note = ""
        sleep_note = ""
        try:
            from services.health import health_monitor
            latest = health_monitor.get_latest_health()
            if latest.get("steps_today") is not None:
                steps_note = f"Latest step count: {latest['steps_today']}. "
            if latest.get("sleep_hours") is not None:
                sleep_note = f"Latest sleep: {latest['sleep_hours']}h. "
        except Exception:
            pass

        try:
            from core.llm.router import think
            prompt = (
                f"This {period}: {len(workouts)} workouts logged. {steps_note}{sleep_note}\n"
                "Write a brief, encouraging fitness summary (2-3 sentences)."
            )
            return think(prompt, max_tokens=150)
        except Exception:
            return f"This {period}: {len(workouts)} workouts logged. {steps_note}{sleep_note}"


fitness_coach = FitnessCoach()
