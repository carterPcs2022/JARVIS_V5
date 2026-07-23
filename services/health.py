"""
JARVIS V5 - Health Monitor Service
Tracks biometric data from Apple Health / Apple Shortcuts webhooks.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

HEALTH_DATA_FILE = BASE_DIR / "memory" / "health_data.json"


class HealthMonitor:
    """Monitors and analyzes personal health metrics."""

    def _load_data(self) -> list:
        """Load health data — Turso-mirrored via core.memory._load(), same
        as every other memory category. Previously a plain JSON file with
        no durability path at all: not Turso-backed like core/memory.py's
        conversation/note stores, and not covered by the manual
        /stark/backup snapshot either — a Render redeploy (ephemeral disk,
        no persistent volume on this service) could silently wipe the
        entire health history a multi-day trend check depends on."""
        from core.memory import _load
        data = _load(HEALTH_DATA_FILE)
        return data if isinstance(data, list) else []

    def _save_data(self, data: list) -> None:
        """Save health data — see _load_data()'s note on why this goes
        through core.memory._save() instead of a plain json.dump()."""
        from core.memory import _save
        _save(HEALTH_DATA_FILE, data)

    def get_latest_health(self) -> dict:
        """Return the most recent health snapshot."""
        data = self._load_data()
        if not data:
            return {
                "message": "No health data available. Send data via the /health/data endpoint from Apple Shortcuts.",
                "heart_rate": None,
                "steps_today": None,
                "sleep_hours": None,
                "hrv": None,
                "resting_hr": None,
                "weight_kg": None,
            }
        latest = data[-1]
        return latest

    def receive_health_data(self, data: dict) -> dict:
        """
        Validate and store incoming health data from Apple Shortcuts webhook.
        Appends a timestamped snapshot to memory/health_data.json.
        """
        if not isinstance(data, dict):
            return {"status": "error", "message": "Data must be a JSON object."}

        # Add timestamp if not present
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()

        # Basic validation: at least one known health field required
        known_fields = {
            "heart_rate", "steps_today", "sleep_hours", "hrv",
            "resting_hr", "weight_kg", "calories_burned", "active_minutes",
            "blood_oxygen", "body_temp_c", "diastolic_bp", "systolic_bp",
        }
        present = known_fields.intersection(data.keys())
        if not present:
            return {
                "status": "error",
                "message": f"No recognized health fields found. Expected one of: {', '.join(sorted(known_fields))}",
            }

        existing = self._load_data()
        existing.append(data)
        self._save_data(existing)

        # Background anomaly check (non-blocking)
        try:
            self.watch_for_anomaly(snapshot=data)
        except Exception as e:
            logger.warning(f"Anomaly check failed: {e}")

        return {
            "status": "ok",
            "message": f"Health snapshot recorded with {len(present)} field(s).",
            "fields_stored": sorted(present),
            "timestamp": data["timestamp"],
            "total_snapshots": len(existing),
        }

    def health_brief(self) -> str:
        """Generate a JARVIS-style health summary using the LLM."""
        from core.llm.router import think

        latest = self.get_latest_health()
        data = self._load_data()

        if not data:
            return "No health data on file, sir. Sync your Apple Health via Apple Shortcuts to get started."

        # Provide last 7 snapshots for context
        recent = data[-7:]
        context = json.dumps(recent, indent=2, default=str)

        prompt = (
            f"You are JARVIS, an AI assistant. Generate a concise, intelligent health briefing "
            f"in JARVIS's calm, professional style. Focus on notable trends, any concerns, and "
            f"positive achievements. Keep it under 150 words.\n\nHealth data (most recent snapshots):\n{context}"
        )
        return think(prompt)

    def stress_check(self) -> str:
        """
        Assess stress level based on HRV and resting heart rate.
        Returns a descriptive string assessment.
        """
        latest = self.get_latest_health()

        hrv = latest.get("hrv")
        resting_hr = latest.get("resting_hr")

        if hrv is None and resting_hr is None:
            return "Insufficient data for stress assessment. HRV and resting heart rate values are needed."

        indicators = []
        stressed = False

        if hrv is not None:
            try:
                hrv = float(hrv)
                if hrv < 30:
                    stressed = True
                    indicators.append(f"HRV is low at {hrv:.1f}ms (threshold: 30ms)")
                else:
                    indicators.append(f"HRV is healthy at {hrv:.1f}ms")
            except (ValueError, TypeError):
                pass

        if resting_hr is not None:
            try:
                rhr = float(resting_hr)
                if rhr > 90:
                    stressed = True
                    indicators.append(f"Resting HR is elevated at {rhr:.0f}bpm (threshold: 90bpm)")
                else:
                    indicators.append(f"Resting HR is normal at {rhr:.0f}bpm")
            except (ValueError, TypeError):
                pass

        timestamp = latest.get("timestamp", "unknown time")
        summary = " | ".join(indicators) if indicators else "No usable stress indicators in latest snapshot."

        if stressed:
            return (
                f"STRESS DETECTED — {summary}. "
                f"Recommendation: Consider a short breathing exercise or rest period. "
                f"(Data from: {timestamp})"
            )
        return (
            f"Stress levels appear normal — {summary}. "
            f"(Data from: {timestamp})"
        )

    def sleep_analysis(self) -> dict:
        """
        Analyze the last 30 days of sleep data.
        Returns trends dict with avg_sleep, trend, best_day, worst_day.
        """
        data = self._load_data()
        cutoff = datetime.now() - timedelta(days=30)

        sleep_entries = []
        for snap in data:
            if "sleep_hours" not in snap or snap["sleep_hours"] is None:
                continue
            ts_str = snap.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            if ts >= cutoff:
                try:
                    sleep_entries.append((ts, float(snap["sleep_hours"])))
                except (ValueError, TypeError):
                    continue

        if not sleep_entries:
            return {
                "avg_sleep": None,
                "trend": "No sleep data available for the last 30 days.",
                "best_day": None,
                "worst_day": None,
                "data_points": 0,
            }

        sleep_entries.sort(key=lambda x: x[0])
        hours_list = [h for _, h in sleep_entries]
        avg_sleep = sum(hours_list) / len(hours_list)

        best_entry = max(sleep_entries, key=lambda x: x[1])
        worst_entry = min(sleep_entries, key=lambda x: x[1])

        # Simple trend: compare first half vs second half
        mid = len(hours_list) // 2
        if mid > 0:
            first_half_avg = sum(hours_list[:mid]) / mid
            second_half_avg = sum(hours_list[mid:]) / (len(hours_list) - mid)
            diff = second_half_avg - first_half_avg
            if diff > 0.3:
                trend = f"Improving — sleep has increased by ~{diff:.1f}h over the past 30 days."
            elif diff < -0.3:
                trend = f"Declining — sleep has decreased by ~{abs(diff):.1f}h over the past 30 days."
            else:
                trend = f"Stable — sleep averaging {avg_sleep:.1f}h with minimal variation."
        else:
            trend = f"Insufficient data for trend analysis. Average: {avg_sleep:.1f}h."

        return {
            "avg_sleep": round(avg_sleep, 2),
            "trend": trend,
            "best_day": best_entry[0].strftime("%Y-%m-%d") + f" ({best_entry[1]:.1f}h)",
            "worst_day": worst_entry[0].strftime("%Y-%m-%d") + f" ({worst_entry[1]:.1f}h)",
            "data_points": len(sleep_entries),
        }

    def watch_for_anomaly(self, snapshot: dict = None) -> None:
        """
        Background check: fires bus.alert() if HR > 120 or sleep < 5h.
        Can be called with a specific snapshot or uses the latest stored data.
        """
        from core.event_bus import bus

        if snapshot is None:
            snapshot = self.get_latest_health()

        if not snapshot:
            return

        heart_rate = snapshot.get("heart_rate")
        sleep_hours = snapshot.get("sleep_hours")
        timestamp = snapshot.get("timestamp", "recent reading")

        if heart_rate is not None:
            try:
                hr = float(heart_rate)
                if hr > 150:
                    # core.event_bus.bus.alert() only routes to Pushover/
                    # voice/Telegram at severity in ("critical", "high") —
                    # every health anomaly used to fire at "warning", so a
                    # genuinely dangerous reading was HUD-only, invisible
                    # unless a browser tab happened to be open. 120-150bpm
                    # stays "warning" (routine exercise range); above that
                    # is worth an actual notification.
                    bus.alert(
                        f"HEALTH ANOMALY: Heart rate is {hr:.0f}bpm — significantly elevated. "
                        f"Recorded at {timestamp}.",
                        severity="high"
                    )
                elif hr > 120:
                    bus.alert(
                        f"HEALTH ANOMALY: Heart rate is {hr:.0f}bpm — elevated. "
                        f"Recorded at {timestamp}.",
                        severity="warning"
                    )
            except (ValueError, TypeError):
                pass

        if sleep_hours is not None:
            try:
                sl = float(sleep_hours)
                if sl < 5:
                    bus.alert(
                        f"HEALTH ANOMALY: Only {sl:.1f} hours of sleep recorded. "
                        f"Cognitive performance may be impaired today. "
                        f"Recorded at {timestamp}.",
                        severity="warning"
                    )
            except (ValueError, TypeError):
                pass

    def detect_trends(self) -> list[str]:
        """Multi-day pattern detection over accumulated health_data.json
        history — distinct from watch_for_anomaly()'s single-reading
        thresholds, which can't see a pattern that only shows up across
        several days (e.g. a short-sleep streak where no single night
        crosses an acute threshold by much, but four in a row do)."""
        data = self._load_data()
        if not data:
            return []

        findings = []

        # Sleep: collapse to one reading per calendar day (last snapshot
        # wins if the Shortcut synced more than once that day), then look
        # for a run of consecutive under-5h nights.
        by_day: dict[str, float] = {}
        for snap in data:
            sl = snap.get("sleep_hours")
            ts_str = snap.get("timestamp", "")
            if sl is None or not ts_str:
                continue
            try:
                day = datetime.fromisoformat(ts_str).date().isoformat()
                by_day[day] = float(sl)
            except (ValueError, TypeError):
                continue

        days_sorted = sorted(by_day.keys())
        if len(days_sorted) >= 4:
            last_4 = days_sorted[-4:]
            if all(by_day[d] < 5 for d in last_4):
                avg = sum(by_day[d] for d in last_4) / len(last_4)
                findings.append(
                    f"Sleep has been under 5 hours for {len(last_4)} nights running "
                    f"({last_4[0]} to {last_4[-1]}, averaging {avg:.1f}h)."
                )

        # Resting HR: compare this week's daily average to the prior week's.
        by_day_rhr: dict[str, float] = {}
        for snap in data:
            rhr = snap.get("resting_hr")
            ts_str = snap.get("timestamp", "")
            if rhr is None or not ts_str:
                continue
            try:
                day = datetime.fromisoformat(ts_str).date().isoformat()
                by_day_rhr[day] = float(rhr)
            except (ValueError, TypeError):
                continue

        rhr_days = sorted(by_day_rhr.keys())
        if len(rhr_days) >= 10:
            recent_week = rhr_days[-7:]
            prior_week = rhr_days[-14:-7] if len(rhr_days) >= 14 else rhr_days[:-7]
            if prior_week:
                recent_avg = sum(by_day_rhr[d] for d in recent_week) / len(recent_week)
                prior_avg = sum(by_day_rhr[d] for d in prior_week) / len(prior_week)
                if recent_avg - prior_avg >= 5:
                    findings.append(
                        f"Resting heart rate has risen from an average of {prior_avg:.0f}bpm "
                        f"to {recent_avg:.0f}bpm over the last week."
                    )

        return findings

    def watch_for_trends(self) -> None:
        """Scheduler-driven (unlike watch_for_anomaly, which is webhook-
        driven per reading). Multi-day patterns aren't acute events, so
        findings are queued for the daily digest rather than firing
        bus.alert() immediately per finding — see services/notifications.py
        queue_digest()/flush_digest()."""
        findings = self.detect_trends()
        if not findings:
            return
        from services.notifications import queue_digest
        for finding in findings:
            queue_digest("HEALTH_TREND", finding)


health_monitor = HealthMonitor()
