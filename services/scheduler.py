"""Background scheduler — APScheduler jobs for JARVIS automation."""
from __future__ import annotations
import logging, os
from datetime import datetime, timedelta
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


def _cleanup_old_files():
    """Log rotation + audio cache cleanup — Render's disk is small and
    ephemeral, but logs/*.json and static/*.mp3 (voice responses) still
    grow unbounded between restarts otherwise."""
    import glob, time
    from config.settings import BASE_DIR
    try:
        for f in glob.glob(str(BASE_DIR / "logs" / "*.json")):
            if os.path.getmtime(f) < time.time() - 604800:  # 7 days
                os.remove(f)
        for f in glob.glob(str(BASE_DIR / "static" / "*.mp3")):
            if os.path.getmtime(f) < time.time() - 86400:  # 24 hours
                os.remove(f)
    except Exception as e:
        log.debug("Cleanup failed: %s", e)


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


def _weekly_active_learning_cycle():
    """Fine-tune the personal model on the week's conversations + corrections.
    Scheduled after Benchmark (3am) and Prometheus (4am) to avoid overlap."""
    try:
        from core.active_learning import learner
        learner.weekly_learning_cycle()
    except Exception as e:
        log.debug("Weekly active learning cycle failed: %s", e)


def _weekly_neuro_reanalysis():
    try:
        from core.neuro_mirror import neuro
        from core.memory import _load
        from config.settings import CONVERSATIONS_FILE
        convs = _load(CONVERSATIONS_FILE) or []
        if len(convs) >= 20:
            neuro.analyze_thinking_style(convs)
    except Exception as e:
        log.debug("Weekly neuro reanalysis failed: %s", e)


def _morning_routine():
    try:
        from services.morning_routine import morning
        morning.run()
    except Exception as e:
        log.debug("Morning routine failed: %s", e)


def _evening_routine():
    try:
        from services.evening_routine import evening
        evening.run()
    except Exception as e:
        log.debug("Evening routine failed: %s", e)


def _price_check():
    try:
        from services.price_tracker import price_tracker
        price_tracker.check_all()
    except Exception as e:
        log.debug("Price check failed: %s", e)


def _package_check():
    try:
        from services.packages import packages
        packages.check_all()
    except Exception as e:
        log.debug("Package check failed: %s", e)


def _daily_secret_scan():
    """Cheap (regex-only, no LLM calls) — safe to run automatically,
    unlike services.self_audit.full_audit() (LLM-based, ~9 paid calls),
    which stays manual-only."""
    try:
        from services.self_audit import audit
        findings = audit.scan_for_secrets()
        if findings:
            from core.event_bus import bus
            bus.alert(f"Daily secret scan found {len(findings)} potential exposed secret(s) in code.",
                     severity="critical", category="SECRET_SCAN")
    except Exception as e:
        log.debug("Daily secret scan failed: %s", e)


def _dead_mans_switch_monitor():
    """No-op unless services.dead_mans_switch.dms was explicitly
    configured (config["enabled"] defaults False) — safe to schedule
    unconditionally."""
    try:
        from services.dead_mans_switch import dms
        dms.monitor()
    except Exception as e:
        log.debug("Dead man's switch monitor failed: %s", e)


def _daily_canary_replant():
    try:
        from services.canary import canary
        canary.plant_in_memory_files()
    except Exception as e:
        log.debug("Daily canary replant failed: %s", e)


def _proactive_screen_check():
    """Local Mac only — services.screen_monitor already no-ops everywhere
    else, but skipping the job registration entirely on Render/Railway
    avoids a pointless 5-minute LLM-call timer with nothing to capture."""
    try:
        from services.screen_monitor import screen_monitor
        screen_monitor.proactive_monitor()
    except Exception as e:
        log.debug("Proactive screen check failed: %s", e)


def _proactive_research():
    try:
        from services.awareness import awareness
        awareness.proactive_research()
    except Exception as e:
        log.debug("Proactive research failed: %s", e)


def _stark_proactive_thinking():
    try:
        from core.stark_intelligence import stark_intel
        stark_intel.proactive_think()
    except Exception as e:
        log.debug("Stark proactive thinking failed: %s", e)


def _stark_anticipate_needs():
    try:
        from core.stark_intelligence import stark_intel
        stark_intel.anticipate_needs()
    except Exception as e:
        log.debug("Stark anticipate needs failed: %s", e)


def start():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from config.settings import LOKI_SURPRISE_HOUR, BENCHMARK_DAY

        # "interval" jobs fire immediately once the scheduler starts (their
        # next_run_time defaults to now), so every Groq-calling job here
        # would otherwise hit the API in the same instant scheduler_start()
        # runs — piling straight onto whatever warm_cache()/the LLM probe
        # just did. Stagger those specific jobs' first run 60s apart;
        # non-LLM jobs (email/system checks, cleanup, etc.) still fire
        # immediately since they don't touch Groq.
        now = datetime.now()

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(_email_check,  "interval", minutes=15, id="email_check")
        _scheduler.add_job(_system_check, "interval", minutes=5,  id="system_check")
        _scheduler.add_job(_llm_health_refresh, "interval", minutes=2, id="llm_health_refresh",
                            next_run_time=now + timedelta(seconds=60))

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

        # 10/10 upgrade: weekly fine-tuning + neuro reanalysis (Sunday, after
        # Benchmark at 3am and Prometheus at 4am)
        _scheduler.add_job(_weekly_active_learning_cycle, "cron", day_of_week="sun", hour=5, id="weekly_learning")
        _scheduler.add_job(_weekly_neuro_reanalysis, "cron", day_of_week="sun", hour=6, id="weekly_neuro")

        # Absolute final batch: morning/evening routines, price/package tracking
        _scheduler.add_job(_morning_routine, "cron", hour=7, minute=30, id="morning_routine", replace_existing=True)
        _scheduler.add_job(_evening_routine, "cron", hour=22, minute=0, id="evening_routine", replace_existing=True)
        _scheduler.add_job(_price_check, "interval", minutes=30, id="price_check")
        _scheduler.add_job(_package_check, "interval", hours=1, id="package_check")

        # Security batch — only the cheap/self-gated jobs are auto-scheduled.
        # services.self_audit.full_audit() (~9 paid LLM calls) and
        # services.red_team.run_exercise() (2x fable + 1x opus) stay
        # manual-only (POST /stark/security/audit, /stark/security/redteam)
        # rather than running unattended every night/week.
        _scheduler.add_job(_daily_secret_scan, "cron", hour=2, id="daily_secret_scan")
        _scheduler.add_job(_dead_mans_switch_monitor, "interval", hours=1, id="dead_mans_switch_monitor")
        _scheduler.add_job(_daily_canary_replant, "cron", hour=0, minute=0, id="daily_canary_replant")
        _scheduler.add_job(_cleanup_old_files, "cron", hour=3, minute=30, id="cleanup_old_files")

        # Final batch: proactive screen monitoring (local Mac only — screen
        # capture is a no-op everywhere else) + proactive project research
        from config.settings import ENVIRONMENT
        if ENVIRONMENT == "local":
            _scheduler.add_job(_proactive_screen_check, "interval", minutes=5, id="proactive_screen_check")
        _scheduler.add_job(_proactive_research, "interval", hours=2, id="proactive_research",
                            next_run_time=now + timedelta(seconds=120))

        # Stark Intelligence — background proactive thinking + anticipatory
        # pre-caching of the user's likely next question
        _scheduler.add_job(_stark_proactive_thinking, "interval", minutes=30, id="stark_proactive_thinking",
                            next_run_time=now + timedelta(seconds=180))
        _scheduler.add_job(_stark_anticipate_needs, "interval", minutes=5, id="stark_anticipate_needs",
                            next_run_time=now + timedelta(seconds=240))

        _scheduler.start()
        log.info("Scheduler started — email/15m, system/5m, LLM health/2m, "
                 "+ Protocols 19/24/25/28/29/30/31/32/35, weekly learning/neuro, "
                 "morning/evening routines, price/package tracking, "
                 "secret scan/dead man's switch/canary replant, log/audio cleanup, "
                 "proactive screen check (local), proactive research/2h, "
                 "stark proactive thinking/30m, stark anticipate needs/5m")
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
