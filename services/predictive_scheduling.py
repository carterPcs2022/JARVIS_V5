"""services/predictive_scheduling.py — energy-based day optimization.
Matches task types to the time-of-day energy profile and factors in
today's calendar load and current stress level."""
from __future__ import annotations

from datetime import datetime

from config.settings import USER_TIMEZONE

_ENERGY_PROFILE: list[tuple[tuple[int, int], str]] = [
    ((6, 10),  "peak — best for deep work"),
    ((10, 13), "high — good for meetings"),
    ((13, 15), "low — admin tasks only"),
    ((15, 18), "medium — creative work"),
    ((18, 21), "declining — review and planning"),
]


def _now_local() -> datetime:
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(USER_TIMEZONE))
    except Exception:
        return datetime.now()


class PredictiveScheduler:

    def optimize_day(self) -> dict:
        """Recommend how to spend the rest of the day based on current
        energy window, today's calendar load, and stress level."""
        now  = _now_local()
        hour = now.hour

        energy = "moderate"
        for (start, end), level in _ENERGY_PROFILE:
            if start <= hour < end:
                energy = level
                break

        try:
            from services.calendar_intel import calendar_intel
            today = calendar_intel.get_today()
        except Exception:
            today = []

        try:
            from services.health import health_monitor
            stress = health_monitor.stress_check()
        except Exception:
            stress = "unknown"

        from core.llm.router import think
        try:
            recommendation = think(
                f"Current time: {now.strftime('%I:%M %p')}\n"
                f"Energy level: {energy}\n"
                f"Stress: {stress}\n"
                f"Today's events: {len(today)}\n"
                f"Events: " + ", ".join(e.get('title', '') for e in today[:3]) +
                f"\n\nRecommend an optimal schedule for the rest of the day. "
                f"Match task types to energy levels. Keep it under 120 words.",
                force_model="standard",
            )
        except Exception as e:
            recommendation = f"[Recommendation unavailable: {e}]"

        return {"current_energy": energy, "recommendation": recommendation, "hour": hour}


scheduler_intel = PredictiveScheduler()
