"""services/sleep_intel.py — sleep debt tracking and optimal bedtime.

Builds on services/health.py's existing health_data.json store (which already
carries sleep_hours per snapshot) rather than keeping a second, divergent
sleep log — log_sleep() just adds quality/bedtime/wake_time fields onto the
same snapshot record.
"""
from __future__ import annotations

from datetime import datetime

from services.health import health_monitor

_TARGET_HOURS = 8.0


class SleepIntelligence:

    def log_sleep(self, hours: float, quality: int, bedtime: str = "", wake_time: str = "") -> dict:
        return health_monitor.receive_health_data({
            "sleep_hours": hours,
            "quality":     quality,
            "bedtime":     bedtime,
            "wake_time":   wake_time,
        })

    def _sleep_entries(self) -> list[dict]:
        return [e for e in health_monitor._load_data() if e.get("sleep_hours") is not None]

    def sleep_debt(self) -> dict:
        """Calculate accumulated sleep debt against an 8h/night target."""
        entries = self._sleep_entries()[-7:]
        if len(entries) < 3:
            return {"debt_hours": 0, "status": "insufficient_data"}

        avg  = sum(float(e["sleep_hours"]) for e in entries) / len(entries)
        debt = max(0.0, (_TARGET_HOURS - avg) * len(entries))
        status = "ok" if debt < 2 else "warning" if debt < 5 else "critical"

        return {
            "avg_sleep":   round(avg, 1),
            "target":      _TARGET_HOURS,
            "weekly_debt": round(debt, 1),
            "status":      status,
            "recommendation": (
                "Sleep debt is nominal." if status == "ok" else
                f"You're {debt:.1f}h short this week. Consider an earlier bedtime."
            ),
        }

    def optimal_bedtime(self) -> str:
        """Find the bedtime associated with the best-quality nights, so far."""
        good_nights = [e for e in self._sleep_entries() if e.get("quality", 0) and int(e["quality"]) >= 8 and e.get("bedtime")]
        if not good_nights:
            return "10:30 PM"
        return good_nights[-1]["bedtime"]


sleep_intel = SleepIntelligence()
