"""services/automation.py — Scheduled tasks, dream mode, and FRIDAY coordination."""
import os, json
from datetime import datetime
from pathlib import Path
from config.settings import DREAM_LOG
from core.llm.router import think
from config.settings import JARVIS_PERSONALITY

FRIDAY_URL = os.environ.get("FRIDAY_URL", "http://localhost:8080")


def check_friday_alive() -> bool:
    """Is FRIDAY standing by?"""
    try:
        import httpx
        r = httpx.get(f"{FRIDAY_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def notify_friday_of_shutdown(reason: str = "JARVIS shutdown"):
    """Called by Protocol 2 (Dead Man's Switch) before JARVIS shuts down."""
    try:
        import httpx
        httpx.post(
            f"{FRIDAY_URL}/takeover",
            json={"reason": reason, "ts": datetime.now().isoformat()},
            timeout=3,
        )
    except Exception:
        pass


def morning_briefing() -> str:
    parts = []
    try:
        from core.tools.system import snapshot
        sys = snapshot()
        parts.append(f"System: CPU {sys['cpu_percent']}% | RAM {sys['ram_used_pct']}% | Disk {sys['disk_used_pct']}% | Uptime {sys['uptime_hours']}h")
    except Exception:
        pass
    try:
        from services.sentinel import summary
        s = summary()
        parts.append(f"Security: {s['last_24h']} events in 24h")
    except Exception:
        pass
    try:
        friday_status = "online" if check_friday_alive() else "offline"
        parts.append(f"FRIDAY: {friday_status}")
    except Exception:
        pass
    try:
        from core.memory import get_context_string
        ctx = get_context_string(5)
        if ctx:
            parts.append(f"Recent activity:\n{ctx}")
    except Exception:
        pass

    prompt = (f"{JARVIS_PERSONALITY}\n\nGenerate a concise morning briefing.\n\n"
              + "\n".join(parts))
    briefing = think(prompt)

    DREAM_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if DREAM_LOG.exists():
        with open(DREAM_LOG) as f:
            try:
                log = json.load(f)
            except Exception:
                log = []
    log.append({"ts": datetime.now().isoformat(), "briefing": briefing[:500]})
    with open(DREAM_LOG, "w") as f:
        json.dump(log[-30:], f, indent=2)
    return briefing


def run_dream_cycle() -> dict:
    briefing = morning_briefing()
    brief_file = Path("jarvis_morning_briefing.txt")
    with open(brief_file, "w") as f:
        f.write(f"=== JARVIS Briefing — {datetime.now().strftime('%A %B %d %Y')} ===\n\n{briefing}")
    return {"briefing": briefing, "file": str(brief_file)}


def last_backup_age_hours() -> float | None:
    """Return hours since last backup, or None if no backup exists."""
    try:
        backup_dir = Path("backups")
        if not backup_dir.exists():
            return None
        files = sorted(backup_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        import time
        return (time.time() - files[-1].stat().st_mtime) / 3600
    except Exception:
        return None
