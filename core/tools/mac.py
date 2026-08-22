"""core/tools/mac.py — macOS system control via subprocess + AppleScript."""
import subprocess, os, re
from pathlib import Path


# ── AppleScript runner ────────────────────────────────────────────────────────

def run_applescript(script: str) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"[AppleScript error: {e}]"


# ── App control ───────────────────────────────────────────────────────────────

def open_app(name: str) -> dict:
    """Open any macOS application by name."""
    try:
        r = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            return {"ok": True, "message": f"Opened {name}"}
        return {"ok": False, "message": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def quit_app(name: str) -> dict:
    """Quit an application."""
    safe = name.replace('"', '\\"')
    result = run_applescript(f'tell application "{safe}" to quit')
    return {"ok": True, "message": f"Quit {name}", "detail": result}


def focus_app(name: str) -> dict:
    """Bring an application to the foreground."""
    safe = name.replace('"', '\\"')
    result = run_applescript(f'tell application "{safe}" to activate')
    return {"ok": True, "message": f"Focused {name}", "detail": result}


def list_running_apps() -> list[str]:
    """Return names of all currently running user applications."""
    script = 'tell application "System Events" to get name of every process whose background only is false'
    raw = run_applescript(script)
    return [a.strip() for a in raw.split(",") if a.strip()]


def is_app_running(name: str) -> bool:
    safe = name.replace('"', '\\"')
    script = f'tell application "System Events" to (name of every process) contains "{safe}"'
    return run_applescript(script).lower() == "true"


# ── System controls ────────────────────────────────────────────────────────────

def get_volume() -> int:
    raw = run_applescript("output volume of (get volume settings)")
    try:
        return int(raw)
    except Exception:
        return -1


def set_volume(level: int) -> dict:
    level = max(0, min(100, int(level)))
    run_applescript(f"set volume output volume {level}")
    return {"ok": True, "message": f"Volume set to {level}%"}


def mute() -> dict:
    run_applescript("set volume with output muted")
    return {"ok": True, "message": "Muted"}


def unmute() -> dict:
    run_applescript("set volume without output muted")
    return {"ok": True, "message": "Unmuted"}


def take_screenshot(path: str = "/tmp/jarvis_screenshot.png") -> dict:
    try:
        subprocess.run(["screencapture", "-x", path], timeout=5)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def lock_screen() -> dict:
    run_applescript('tell application "System Events" to keystroke "q" using {command down, control down}')
    return {"ok": True, "message": "Screen locked"}


def empty_trash() -> dict:
    run_applescript('tell application "Finder" to empty trash')
    return {"ok": True, "message": "Trash emptied"}


# ── Clipboard ─────────────────────────────────────────────────────────────────

def get_clipboard() -> str:
    return run_applescript("the clipboard")


def set_clipboard(text: str) -> dict:
    safe = text.replace('"', '\\"')
    run_applescript(f'set the clipboard to "{safe}"')
    return {"ok": True, "message": "Clipboard updated"}


# ── Notifications ─────────────────────────────────────────────────────────────

def notify(title: str, message: str, subtitle: str = "JARVIS") -> dict:
    safe_t = title.replace('"', '\\"')
    safe_m = message.replace('"', '\\"')
    safe_s = subtitle.replace('"', '\\"')
    run_applescript(
        f'display notification "{safe_m}" with title "{safe_t}" subtitle "{safe_s}"'
    )
    return {"ok": True, "message": f"Notification sent: {title}"}


# ── Finder ────────────────────────────────────────────────────────────────────

def open_url(url: str) -> dict:
    try:
        subprocess.run(["open", url], timeout=5)
        return {"ok": True, "message": f"Opened {url}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def reveal_in_finder(path: str) -> dict:
    safe = path.replace('"', '\\"')
    run_applescript(f'tell application "Finder" to reveal POSIX file "{safe}"')
    run_applescript('tell application "Finder" to activate')
    return {"ok": True, "message": f"Revealed {path} in Finder"}


# ── Safari / Chrome ───────────────────────────────────────────────────────────

def open_url_in_browser(url: str, browser: str = "Safari") -> dict:
    safe = url.replace('"', '\\"')
    script = f'''
        tell application "{browser}"
            activate
            open location "{safe}"
        end tell
    '''
    run_applescript(script)
    return {"ok": True, "message": f"Opened {url} in {browser}"}


def get_browser_url(browser: str = "Safari") -> str:
    if browser == "Safari":
        return run_applescript('tell application "Safari" to get URL of current tab of window 1')
    elif browser in ("Google Chrome", "Chrome"):
        return run_applescript('tell application "Google Chrome" to get URL of active tab of window 1')
    return ""


# ── Calendar ─────────────────────────────────────────────────────────────────

def get_todays_events() -> list[dict]:
    script = '''
        tell application "Calendar"
            set todayStart to current date
            set time of todayStart to 0
            set todayEnd to todayStart + (24 * 60 * 60) - 1
            set result to {}
            repeat with c in calendars
                repeat with e in (every event of c whose start date is greater than or equal to todayStart and start date is less than or equal to todayEnd)
                    set end of result to (summary of e & " at " & ((start date of e) as string))
                end repeat
            end repeat
            return result
        end tell
    '''
    raw = run_applescript(script)
    if not raw or raw.startswith("["):
        return []
    return [{"event": e.strip()} for e in raw.split(",") if e.strip()]


def create_reminder(title: str, due_in_minutes: int = 60) -> dict:
    from datetime import datetime, timedelta
    due = datetime.now() + timedelta(minutes=due_in_minutes)
    safe_title = title.replace('"', '\\"')
    script = f'''
        tell application "Reminders"
            set newReminder to make new reminder with properties {{name:"{safe_title}", due date:date "{due.strftime('%B %d, %Y %H:%M:%S')}"}}
        end tell
    '''
    run_applescript(script)
    return {"ok": True, "message": f"Reminder set: '{title}' in {due_in_minutes} min"}
