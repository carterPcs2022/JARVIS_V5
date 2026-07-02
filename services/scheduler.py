"""Background scheduler — APScheduler jobs for JARVIS automation."""
from __future__ import annotations
import logging, os
log = logging.getLogger(__name__)

_scheduler = None


def _email_check():
    try:
        from core.tools.gmail import is_configured, get_unread_count
        if not is_configured():
            return
        count = get_unread_count()
        if count > 0:
            from services.notifications import info
            info("Gmail", f"You have {count} unread emails")
            from core.event_bus import bus
            bus.publish("alert", {"title": "Gmail", "message": f"{count} unread emails"})
    except Exception as e:
        log.debug("Email check failed: %s", e)


def _system_check():
    try:
        from core.tools.system import snapshot
        from services.notifications import warning
        s = snapshot()
        if s.get("cpu_percent", 0) > float(os.getenv("ALERT_CPU", "90")):
            warning("High CPU", f"CPU at {s['cpu_percent']}%")
        if s.get("ram_used_pct", 0) > float(os.getenv("ALERT_RAM", "90")):
            warning("High RAM", f"RAM at {s['ram_used_pct']}%")
        if s.get("disk_used_pct", 0) > float(os.getenv("ALERT_DISK", "85")):
            warning("Low Disk", f"Disk at {s['disk_used_pct']}%")
    except Exception as e:
        log.debug("System check failed: %s", e)


def _llm_health_refresh():
    """core.state's groq_available/ollama_available otherwise only update
    when an actual chat request succeeds or fails — so a single transient
    429 or Ollama hiccup leaves /health reporting a stale, wrong status
    indefinitely (nothing else ever flips it back). Refresh it periodically
    from a real (rate-limit-cached) check instead."""
    try:
        from core.llm.router import check_groq, check_ollama
        from core.state import state
        state.update({
            "groq_available":   check_groq(),
            "ollama_available": check_ollama(),
        })
    except Exception as e:
        log.debug("LLM health refresh failed: %s", e)


# ── Stark Protocols 18-35 scheduled jobs ─────────────────────────────────────

def _p19_morning_initiative():
    try:
        from core.protocols import initiative
        suggestions = initiative.morning_initiative()
        if suggestions:
            from services.elevenlabs_voice import generate_for_network
            generate_for_network(suggestions[0])
    except Exception as e:
        log.debug("Morning initiative failed: %s", e)


def _p19_continuous_initiative():
    try:
        from core.protocols import initiative
        initiative.continuous_initiative()
    except Exception as e:
        log.debug("Continuous initiative failed: %s", e)


def _p24_hourly_snapshot():
    try:
        from core.protocols import time_heist
        time_heist.create_snapshot()
    except Exception as e:
        log.debug("Time Heist snapshot failed: %s", e)


def _p25_snap_monitor():
    try:
        from core.protocols import snap
        snap.monitor_for_snap()
    except Exception as e:
        log.debug("Snap monitor failed: %s", e)


def _p28_weekly_benchmark():
    try:
        from core.protocols import benchmark
        benchmark.run_full_suite()
    except Exception as e:
        log.debug("Weekly benchmark failed: %s", e)


def _p29_prometheus_cycle():
    try:
        from core.protocols import prometheus
        prometheus.autonomous_improvement_cycle()
    except Exception as e:
        log.debug("Prometheus cycle failed: %s", e)


def _p30_loki_surprise():
    try:
        from core.protocols import loki
        loki.generate_surprise()
    except Exception as e:
        log.debug("Loki surprise generation failed: %s", e)


def _p31_saturday_check():
    try:
        from core.protocols import saturday
        result = saturday.check_work_life_balance()
        if result.get("needs_rest") and result.get("suggestion"):
            from services.notifications import info
            info("JARVIS", result["suggestion"])
    except Exception as e:
        log.debug("Saturday balance check failed: %s", e)


def _p32_arc_check():
    try:
        from core.protocols import arc
        arc.throttle_if_needed()
    except Exception as e:
        log.debug("Arc power check failed: %s", e)


def _p35_infinity_reflection():
    try:
        from core.protocols import infinity
        infinity.monthly_reflection()
        infinity.set_monthly_goals()
    except Exception as e:
        log.debug("Infinity monthly reflection failed: %s", e)


def start():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from config.settings import LOKI_SURPRISE_HOUR, BENCHMARK_DAY

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(_email_check,  "interval", minutes=15, id="email_check")
        _scheduler.add_job(_system_check, "interval", minutes=5,  id="system_check")
        _scheduler.add_job(_llm_health_refresh, "interval", minutes=2, id="llm_health_refresh")

        # Protocol 19 — Initiative
        _scheduler.add_job(_p19_morning_initiative, "cron", hour=8, id="p19_morning_initiative")
        _scheduler.add_job(_p19_continuous_initiative, "interval", minutes=30, id="p19_continuous_initiative")

        # Protocol 24 — Time Heist (hourly snapshots)
        _scheduler.add_job(_p24_hourly_snapshot, "interval", hours=1, id="p24_time_heist")

        # Protocol 25 — Snap monitor
        _scheduler.add_job(_p25_snap_monitor, "interval", seconds=60, id="p25_snap_monitor")

        # Protocol 28 — Benchmark (weekly, configurable day)
        _scheduler.add_job(_p28_weekly_benchmark, "cron", day_of_week=BENCHMARK_DAY[:3], hour=3, id="p28_benchmark")

        # Protocol 29 — Prometheus (after benchmark, same day)
        _scheduler.add_job(_p29_prometheus_cycle, "cron", day_of_week=BENCHMARK_DAY[:3], hour=4, id="p29_prometheus")

        # Protocol 30 — Loki surprise generation (configurable hour)
        _scheduler.add_job(_p30_loki_surprise, "cron", hour=LOKI_SURPRISE_HOUR, id="p30_loki")

        # Protocol 31 — Saturday balance check (daily 9pm)
        _scheduler.add_job(_p31_saturday_check, "cron", hour=21, id="p31_saturday")

        # Protocol 32 — Arc power check (every 30 min)
        _scheduler.add_job(_p32_arc_check, "interval", minutes=30, id="p32_arc")

        # Protocol 35 — Infinity reflection (1st of month, 2am)
        _scheduler.add_job(_p35_infinity_reflection, "cron", day=1, hour=2, id="p35_infinity")

        _scheduler.start()
        log.info("Scheduler started — email/15m, system/5m, LLM health/2m, "
                 "+ Protocols 19/24/25/28/29/30/31/32/35")
        return True
    except ImportError:
        log.warning("APScheduler not installed — run: pip3 install APScheduler --break-system-packages")
        return False
    except Exception as e:
        log.warning("Scheduler failed to start: %s", e)
        return False


def stop():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


def add_job(func, trigger: str = "interval", **kwargs):
    if _scheduler:
        _scheduler.add_job(func, trigger, **kwargs)
