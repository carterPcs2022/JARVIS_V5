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


def start():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(_email_check,  "interval", minutes=15, id="email_check")
        _scheduler.add_job(_system_check, "interval", minutes=5,  id="system_check")
        _scheduler.add_job(_llm_health_refresh, "interval", minutes=2, id="llm_health_refresh")
        _scheduler.start()
        log.info("Scheduler started — email every 15m, system every 5m, LLM health every 2m")
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
