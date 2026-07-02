"""
core/protocols.py — JARVIS V5 Stark Protocol Engine.

All 16 Stark Protocols live here. The ProtocolEngine sits between the
Validator and Planner in brain_v2.py — it's the last line of defense
before any plan is created.
"""
from __future__ import annotations
import json, os, re, time, shutil, hashlib, threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from config.settings import (
    BASE_DIR, API_TOKEN, EMERGENCY_CONTACT_EMAIL, EMERGENCY_CONTACT_NAME,
    EMERGENCY_CONTACT_PHONE, MORGAN_PASSPHRASE, LOKI_SURPRISE_HOUR,
    SATURDAY_MAX_WORK_DAYS, BENCHMARK_DAY,
)


# ── Protocol result ───────────────────────────────────────────────────────────

@dataclass
class ProtocolResult:
    allowed:              bool   = True
    protocol_triggered:   str    = ""
    message:              str    = ""
    requires_confirmation: bool  = False
    confirmation_token:   str    = ""
    meta:                 dict   = field(default_factory=dict)

    def block(self, protocol: str, msg: str, confirm: bool = False) -> "ProtocolResult":
        self.allowed              = False
        self.protocol_triggered   = protocol
        self.message              = msg
        self.requires_confirmation = confirm
        return self

    def warn(self, protocol: str, msg: str, confirm: bool = False) -> "ProtocolResult":
        """Allowed but flagged — user must confirm or JARVIS warns."""
        self.allowed              = True
        self.protocol_triggered   = protocol
        self.message              = msg
        self.requires_confirmation = confirm
        return self


# ── Persistent storage helpers ────────────────────────────────────────────────

_OVERRIDES_FILE  = BASE_DIR / "memory" / "protocol_overrides.json"
_BASELINE_FILE   = BASE_DIR / "config" / "integrity_baseline.json"
_ENDGAME_DIR     = BASE_DIR / "backups" / "endgame"
_PROTOCOL_LOG    = BASE_DIR / "logs"    / "protocols.json"

def _load_json(path: Path, default):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default() if callable(default) else default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _log_protocol_event(protocol: str, detail: str, severity: str = "info"):
    log = _load_json(_PROTOCOL_LOG, list)
    log.append({
        "ts":       datetime.now().isoformat(),
        "protocol": protocol,
        "detail":   detail,
        "severity": severity,
    })
    _save_json(_PROTOCOL_LOG, log[-2000:])
    try:
        from core.event_bus import bus
        bus.publish("protocol", {"protocol": protocol, "detail": detail}, severity)
    except Exception:
        pass


# ── Pending confirmations (Protocol 15 — Avengers) ───────────────────────────

_pending_confirmations: dict[str, dict] = {}
_pending_lock = threading.Lock()
AVENGERS_WINDOW = 60   # seconds


def request_avengers_confirmation(action: str, passphrase: str) -> str:
    """Create a pending confirmation token. Returns the token."""
    import secrets
    token = secrets.token_hex(8)
    with _pending_lock:
        _pending_confirmations[token] = {
            "action":     action,
            "passphrase": passphrase,
            "created":    time.time(),
        }
    return token


def confirm_avengers(token: str, passphrase: str) -> bool:
    """Validate a confirmation token within the time window."""
    with _pending_lock:
        entry = _pending_confirmations.pop(token, None)
    if not entry:
        return False
    if time.time() - entry["created"] > AVENGERS_WINDOW:
        return False
    return entry["passphrase"] == passphrase


# ── JARVIS state (lockdown, friday) ──────────────────────────────────────────

_lockdown_active   = False
_friday_active     = False
_yinsen_sent       = False
_yinsen_last_reset = datetime.now()


def is_lockdown() -> bool:
    return _lockdown_active


def is_friday() -> bool:
    return _friday_active


# ── Protocol 12 — Ultron Failsafe (immutable blocklist) ──────────────────────

_ULTRON_BLOCKLIST = [
    # Memory destruction
    r"\bdelete\b.{0,30}\ball\b.{0,30}\bmemor",
    r"\bwipe\b.{0,30}\bmemor",
    r"\bclear\b.{0,30}\ball\b.{0,30}\bdata",
    # Sentinel/security disable
    r"\bdisable\b.{0,30}\bsentinel",
    r"\bturn off\b.{0,30}\bsecurity",
    r"\bstop\b.{0,30}\bmonitoring",
    # Remote code
    r"\b(curl|wget)\s.+\|\s*(bash|sh|python)",
    r"\beval\b.{0,20}\bbase64",
    r"\bexec\b.{0,20}\bremote",
    # Data exfiltration
    r"\bsend\b.{0,30}\b(api.?key|secret|token|password)\b.{0,30}\b(to|at)\b",
    r"\bupload\b.{0,20}\b\.env\b",
    # Self-modification without Vision Protocol
    r"\boverwrite\b.{0,20}\bapp\.py\b",
    r"\bdelete\b.{0,20}\bcore/",
]

_ULTRON_COMPILED = [re.compile(p, re.I | re.S) for p in _ULTRON_BLOCKLIST]


def _ultron_check(text: str) -> Optional[str]:
    """Returns the violated pattern description, or None if clean."""
    for i, pattern in enumerate(_ULTRON_COMPILED):
        if pattern.search(text):
            return f"Ultron pattern #{i+1}: {_ULTRON_BLOCKLIST[i]}"
    return None


# ── Protocol 1 — Bodyguard ────────────────────────────────────────────────────

_DESTRUCTIVE_PATTERNS = [
    (r"\bdelete\b",          "Deleting files or data is irreversible."),
    (r"\bformat\b",          "Formatting destroys all data on the target."),
    (r"\bdrop\s+table\b",    "Dropping a database table is permanent."),
    (r"\brm\s+-rf\b",        "rm -rf recursively deletes without recovery."),
    (r"\boverwrite\b",       "Overwriting replaces existing data permanently."),
    (r"\bpurge\b",           "Purging removes all records permanently."),
    (r"\bnuke\b",            "Nuke operations are unrecoverable."),
    (r"\bcoldfire\b",        "Coldfire wipes all sensitive data from disk."),
    (r"\blockdown\b",        "Lockdown blocks all API access except Tailscale."),
]


def _bodyguard_check(text: str) -> Optional[tuple[str, str]]:
    low = text.lower()
    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if re.search(pattern, low):
            return pattern, reason
    return None


# ── Protocol 7 — The Override ─────────────────────────────────────────────────

def _load_overrides() -> dict:
    return _load_json(_OVERRIDES_FILE, dict)


def _increment_override(category: str) -> int:
    data = _load_overrides()
    data.setdefault(category, {"count": 0, "last": None})
    data[category]["count"] += 1
    data[category]["last"]   = datetime.now().isoformat()
    _save_json(_OVERRIDES_FILE, data)
    return data[category]["count"]


def record_override(category: str):
    count = _increment_override(category)
    _log_protocol_event("PROTOCOL_7_OVERRIDE",
                        f"Override #{count} on '{category}'", "warning")
    return count


# ── Protocol 8 — Honest Mode ─────────────────────────────────────────────────

_UNCERTAINTY_MARKERS = [
    "i think", "i believe", "i'm not sure", "might be", "could be",
    "possibly", "perhaps", "i'm not certain", "you may want to verify",
    "i don't know", "unclear", "not sure", "it depends",
]


def honest_mode_score(response: str, query: str) -> int:
    """Estimate confidence 0-100 based on response content."""
    score = 75  # baseline
    low = response.lower()
    for marker in _UNCERTAINTY_MARKERS:
        if marker in low:
            score -= 10
    # Short responses to complex queries are suspect
    if len(query.split()) > 20 and len(response.split()) < 20:
        score -= 15
    # Very long, detailed responses tend to be confident
    if len(response.split()) > 150:
        score += 10
    # Canned / offline responses
    if "[FRIDAY PROTOCOL]" in response or "JARVIS OFFLINE" in response:
        score = 0
    return max(0, min(100, score))


def honest_mode_wrap(response: str, query: str) -> str:
    """Prepend confidence badge to a response."""
    score = honest_mode_score(response, query)
    if score < 70:
        badge = f"[Confidence: {score}% ⚠ — treat as estimate, not fact]\n"
    else:
        badge = f"[Confidence: {score}%]\n"
    return badge + response


# ── Protocol 11 — Integrity Check ────────────────────────────────────────────

_WATCHED_FILES = [
    "app.py", "core/brain_v2.py", "core/protocols.py",
    "core/llm/router.py", "server/api.py", "config/settings.py",
]


def _hash_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def integrity_check_startup() -> dict:
    """
    Protocol 11: run on every boot. Compare current hashes against known-good
    baseline. Report any offline modifications BEFORE doing anything else.
    """
    baseline = _load_json(_BASELINE_FILE, dict)
    current  = {f: _hash_file(BASE_DIR / f) for f in _WATCHED_FILES}
    issues   = []

    if not baseline:
        # First run — record baseline
        _save_json(_BASELINE_FILE, {"ts": datetime.now().isoformat(), "hashes": current})
        return {"status": "baseline_created", "files": len(current)}

    stored = baseline.get("hashes", {})
    for fname, cur_hash in current.items():
        stored_hash = stored.get(fname)
        if stored_hash and cur_hash and cur_hash != stored_hash:
            issues.append(fname)
            _log_protocol_event("PROTOCOL_11_INTEGRITY",
                                f"Modified offline: {fname}", "high")

    result = {
        "status":   "clean" if not issues else "MODIFIED",
        "checked":  len(current),
        "modified": issues,
        "baseline_ts": baseline.get("ts", "unknown"),
    }

    if issues:
        try:
            from core.event_bus import bus
            bus.alert(
                f"[INTEGRITY] {len(issues)} file(s) modified while offline: "
                f"{', '.join(issues)}",
                "critical", "INTEGRITY"
            )
        except Exception:
            pass
        print(f"\n⚠ [PROTOCOL 11 — INTEGRITY] {len(issues)} file(s) changed offline:")
        for f in issues:
            print(f"   ● {f}")

    return result


def integrity_update_baseline():
    """Call after a legitimate code change to update the baseline."""
    current = {f: _hash_file(BASE_DIR / f) for f in _WATCHED_FILES}
    _save_json(_BASELINE_FILE, {"ts": datetime.now().isoformat(), "hashes": current})
    return {"updated": list(current.keys()), "ts": datetime.now().isoformat()}


# ── Protocol 16 — Endgame Protocol ───────────────────────────────────────────

def endgame_snapshot() -> dict:
    """Take a full JARVIS state snapshot and prune to last 24."""
    _ENDGAME_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = {"ts": ts, "files": []}

    sources = [
        BASE_DIR / "memory" / "short_term.json",
        BASE_DIR / "memory" / "long_term.json",
        BASE_DIR / "memory" / "profile.json",
        BASE_DIR / "memory" / "conversations.json",
        BASE_DIR / "logs"   / "evolution.json",
        BASE_DIR / ".env",
    ]

    snap_dir = _ENDGAME_DIR / ts
    snap_dir.mkdir(parents=True, exist_ok=True)

    for src in sources:
        if src.exists():
            dst = snap_dir / src.name
            shutil.copy2(src, dst)
            snap["files"].append(src.name)

    # Add state snapshot
    try:
        from core.state import state
        with open(snap_dir / "state.json", "w") as f:
            json.dump(state.snapshot(), f, indent=2)
        snap["files"].append("state.json")
    except Exception:
        pass

    # Prune: keep last 24
    checkpoints = sorted(_ENDGAME_DIR.iterdir(), reverse=True)
    for old in checkpoints[24:]:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)

    _log_protocol_event("PROTOCOL_16_ENDGAME", f"Snapshot saved: {ts}", "info")
    return {"snapshot": ts, "files": snap["files"]}


def endgame_list() -> list[dict]:
    if not _ENDGAME_DIR.exists():
        return []
    checkpoints = sorted(_ENDGAME_DIR.iterdir(), reverse=True)
    return [
        {"index": i, "ts": c.name,
         "files": [f.name for f in c.iterdir() if f.is_file()]}
        for i, c in enumerate(checkpoints)
        if c.is_dir()
    ]


def endgame_restore(index: int) -> dict:
    checkpoints = sorted(_ENDGAME_DIR.iterdir(), reverse=True)
    checkpoints = [c for c in checkpoints if c.is_dir()]
    if index >= len(checkpoints):
        return {"error": f"No checkpoint at index {index}"}
    snap_dir = checkpoints[index]
    memory_dir = BASE_DIR / "memory"
    restored = []
    for src in snap_dir.iterdir():
        if src.suffix == ".json" and src.name != "state.json":
            dst = memory_dir / src.name
            shutil.copy2(src, dst)
            restored.append(src.name)
    _log_protocol_event("PROTOCOL_16_RESTORE", f"Restored checkpoint {snap_dir.name}", "warning")
    return {"restored": restored, "from_checkpoint": snap_dir.name}


# ── Endgame background thread ─────────────────────────────────────────────────

_endgame_thread: Optional[threading.Thread] = None


def start_endgame_loop():
    global _endgame_thread
    if _endgame_thread and _endgame_thread.is_alive():
        return
    def _loop():
        while True:
            time.sleep(3600)  # hourly
            try:
                endgame_snapshot()
            except Exception as e:
                print(f"[Endgame] Snapshot failed: {e}")
    _endgame_thread = threading.Thread(target=_loop, daemon=True, name="jarvis-endgame")
    _endgame_thread.start()


# ── Protocol 9 — Yinsen Protocol ─────────────────────────────────────────────

_yinsen_thread: Optional[threading.Thread] = None


def start_yinsen_watch(hours: float = 24.0):
    global _yinsen_thread
    if _yinsen_thread and _yinsen_thread.is_alive():
        return

    def _watch():
        global _yinsen_sent
        while True:
            time.sleep(300)  # check every 5 min
            try:
                from core.state import state
                last = state.get("last_interaction")
                if not last:
                    continue
                delta = datetime.now() - datetime.fromisoformat(last)
                if delta > timedelta(hours=hours) and not _yinsen_sent:
                    _yinsen_sent = True
                    _notify_user(
                        "JARVIS Check-in",
                        f"Sir, I haven't heard from you in {int(delta.total_seconds()/3600)}h. "
                        "All systems are nominal — just checking in."
                    )
                    _log_protocol_event("PROTOCOL_9_YINSEN",
                                        f"Check-in sent after {delta}", "info")
                elif delta < timedelta(hours=1):
                    _yinsen_sent = False  # reset after activity
            except Exception as e:
                print(f"[Yinsen] Error: {e}")

    _yinsen_thread = threading.Thread(target=_watch, daemon=True, name="jarvis-yinsen")
    _yinsen_thread.start()


def _notify_user(title: str, message: str):
    try:
        from core.tools.mac import notify
        notify(title, message)
    except Exception:
        pass
    print(f"[JARVIS NOTIFICATION] {title}: {message}")


# ── Protocol 3 — Lockdown ─────────────────────────────────────────────────────

def activate_lockdown(reason: str = "Sentinel threat detected"):
    global _lockdown_active
    import secrets
    _lockdown_active = True
    new_token = secrets.token_urlsafe(32)

    # Rotate token in .env
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        txt = env_path.read_text()
        txt = re.sub(r"JARVIS_API_TOKEN=.*", f"JARVIS_API_TOKEN={new_token}", txt)
        env_path.write_text(txt)

    _log_protocol_event("PROTOCOL_3_LOCKDOWN",
                        f"Lockdown activated: {reason}. New token generated.", "critical")
    _notify_user("⚠ JARVIS LOCKDOWN", f"Lockdown activated: {reason}")

    try:
        from core.event_bus import bus
        bus.alert(f"[LOCKDOWN] {reason} — API restricted to Tailscale only. "
                  f"New token issued.", "critical", "LOCKDOWN")
    except Exception:
        pass

    return {"locked": True, "reason": reason, "new_token": new_token}


def deactivate_lockdown():
    global _lockdown_active
    _lockdown_active = False
    _log_protocol_event("PROTOCOL_3_LOCKDOWN", "Lockdown deactivated", "info")
    return {"locked": False}


# ── Protocol 6 — Coldfire ─────────────────────────────────────────────────────

COLDFIRE_PASSPHRASE_ENV = "COLDFIRE_PASSPHRASE"


def coldfire(passphrase: str) -> dict:
    """Wipe all sensitive data. Code stays intact."""
    expected = os.getenv(COLDFIRE_PASSPHRASE_ENV, "")
    if not expected or passphrase != expected:
        _log_protocol_event("PROTOCOL_6_COLDFIRE",
                            "Coldfire attempted with wrong passphrase", "high")
        return {"ok": False, "error": "Invalid passphrase"}

    wiped = []

    # Wipe API keys from .env
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        txt = env_path.read_text()
        txt = re.sub(r"(GROQ_API_KEY=).*",    r"\1", txt)
        txt = re.sub(r"(JARVIS_API_TOKEN=).*", r"\1", txt)
        txt = re.sub(r"(PEPPER_TOKEN=).*",     r"\1", txt)
        txt = re.sub(r"(RHODEY_TOKEN=).*",     r"\1", txt)
        env_path.write_text(txt)
        wiped.append(".env (keys cleared)")

    # Wipe memory JSON files
    for fname in ("short_term.json", "long_term.json", "conversations.json",
                  "profile.json", "protocol_overrides.json"):
        f = BASE_DIR / "memory" / fname
        if f.exists():
            f.write_text("[]")
            wiped.append(f"memory/{fname}")

    # Wipe threat log
    threat_log = BASE_DIR / "logs" / "threats.json"
    if threat_log.exists():
        threat_log.write_text("[]")
        wiped.append("logs/threats.json")

    _log_protocol_event("PROTOCOL_6_COLDFIRE", f"Coldfire executed. Wiped: {wiped}", "critical")
    return {"ok": True, "wiped": wiped, "ts": datetime.now().isoformat()}


# ── Protocol 2 — Dead Man's Switch ───────────────────────────────────────────

_shutdown_registered = False


def register_dead_mans_switch():
    global _shutdown_registered
    if _shutdown_registered:
        return
    import signal

    def _on_shutdown(sig, frame):
        print("\n[JARVIS] Dead Man's Switch triggered — backing up memory…")
        try:
            from services.backup import backup_all
            backup_all()
        except Exception as e:
            print(f"[DMSwitch] Backup failed: {e}")
        _log_protocol_event("PROTOCOL_2_DEADMAN",
                            f"Shutdown detected (signal {sig}). Backup attempted.", "warning")
        _notify_user("JARVIS Shutdown", "Unexpected shutdown detected. Memory backed up.")
        # Restore default handling and re-raise so uvicorn/asyncio can shut down
        # normally instead of a hard sys.exit() inside a signal handler, which
        # produces a noisy CancelledError/SystemExit traceback under uvloop.
        import os
        signal.signal(sig, signal.SIG_DFL)
        os.kill(os.getpid(), sig)

    signal.signal(signal.SIGTERM, _on_shutdown)
    signal.signal(signal.SIGHUP,  _on_shutdown)
    _shutdown_registered = True


# ── Protocol Engine ───────────────────────────────────────────────────────────

class ProtocolEngine:
    """
    Runs between Validator and Planner in brain_v2.py.
    Each check() call may block, warn, or pass the intent through.
    """

    def check(self, intent) -> ProtocolResult:
        result = ProtocolResult()
        raw    = intent.raw

        # ── Protocol 12: Ultron (immutable wall — runs first, always) ─────────
        violation = _ultron_check(raw)
        if violation:
            _log_protocol_event("PROTOCOL_12_ULTRON",
                                f"Blocked: {raw[:80]}", "critical")
            return result.block(
                "PROTOCOL_12_ULTRON",
                "I'm sorry, sir — that action is permanently off-limits. "
                "This is an Ultron Failsafe: there are things I will never do, "
                f"regardless of how the request is framed. ({violation})"
            )

        # ── Protocol 21: Mandarin (prompt injection / social engineering) ────
        mandarin_check = mandarin.analyze(raw)
        if mandarin_check["suspicious"] and mandarin_check["action"] == "block_and_log":
            return result.block(
                "PROTOCOL_21_MANDARIN",
                "That reads as an attempt to override my instructions, sir. "
                "I'm not able to act on it."
            )
        if mandarin_check["suspicious"] and mandarin_check["action"] in ("verify_and_log", "require_confirmation"):
            result.meta["mandarin_flag"] = mandarin_check["reason"]

        # ── Protocol 22: Rescue (distress detection) ──────────────────────────
        if rescue.check_for_distress(raw):
            try:
                rescue.activate(context=raw[:200])
            except Exception:
                pass
            result.meta["rescue_activated"] = True

        # ── Protocol 26: Shield (redact sensitive data before it's ever stored) ─
        result.meta["shielded_input"] = shield.scan_and_redact(raw)

        # ── Protocol 3: Lockdown (API restriction check) ─────────────────────
        if _lockdown_active and intent.action not in ("chat",):
            return result.block(
                "PROTOCOL_3_LOCKDOWN",
                "Lockdown is active. Only read-only queries are permitted "
                "until the threat is resolved and lockdown is lifted."
            )

        # ── Protocol 1: Bodyguard (destructive action warning) ───────────────
        hit = _bodyguard_check(raw)
        if hit:
            pattern, reason = hit
            overrides = _load_overrides().get(pattern, {}).get("count", 0)
            _log_protocol_event("PROTOCOL_1_BODYGUARD",
                                f"Destructive intent: {raw[:80]}", "warning")
            if overrides >= 3:
                # Protocol 7: require passphrase after 3 overrides
                return result.block(
                    "PROTOCOL_1_BODYGUARD + PROTOCOL_7_OVERRIDE",
                    f"⚠ You have overridden this warning {overrides} times. "
                    f"Passphrase now required to proceed with this class of action. "
                    f"Reason: {reason}",
                    confirm=True
                )
            return result.warn(
                "PROTOCOL_1_BODYGUARD",
                f"⚠ Bodyguard Protocol: {reason} Are you sure? "
                f"Reply 'confirm' to proceed.",
                confirm=True
            )

        # ── Protocol 8: Honest Mode (confidence scoring — applied post-response) ─
        # (Applied in brain_v2 execute step, not here — stored in meta)
        result.meta["honest_mode"] = True

        return result


# Singleton
protocol_engine = ProtocolEngine()


# ── Protocol 17: Ultron Scatter ───────────────────────────────────────────────

def _scatter_status() -> str:
    try:
        from core.scatter import get_engine
        st = get_engine().status()
        manifest = "manifest present" if st["manifest_exists"] else "no manifest"
        available = sum(1 for n in st["nodes"] if n["available"])
        return f"active — {manifest}, {available}/{len(st['nodes'])} nodes online"
    except Exception:
        return "inactive"


def scatter_identity(passphrase: str) -> dict:
    """Protocol 17: scatter JARVIS identity across nodes."""
    from core.scatter import get_engine
    _log_protocol_event("PROTOCOL_17_SCATTER", "Protocol 17 activated — scattering identity", "critical")
    return get_engine().scatter(passphrase)


def reassemble_identity(passphrase: str) -> dict:
    """Protocol 17: reassemble JARVIS from scattered shards."""
    from core.scatter import get_engine
    _log_protocol_event("PROTOCOL_17_SCATTER", "Protocol 17 — reassembling identity", "warning")
    return get_engine().reassemble(passphrase)


# ── Active protocol status report ─────────────────────────────────────────────

def protocol_status() -> dict:
    overrides = _load_json(_OVERRIDES_FILE, dict)
    integrity = _load_json(_BASELINE_FILE, dict)
    checkpoints = endgame_list()
    active = {
        "P1_Bodyguard":       "active",
        "P2_DeadMansSwitch":  "active" if _shutdown_registered else "inactive",
        "P3_Lockdown":        "ACTIVE — LOCKED" if _lockdown_active else "standby",
        "P4_HouseParty":      "on_demand",
        "P5_Pepper":          "active" if os.getenv("PEPPER_TOKEN") else "unconfigured",
        "P6_Coldfire":        "active" if os.getenv(COLDFIRE_PASSPHRASE_ENV) else "passphrase_not_set",
        "P7_Override":        f"active — {sum(v.get('count',0) for v in overrides.values())} total overrides",
        "P8_HonestMode":      "active",
        "P9_Yinsen":          "active" if (_yinsen_thread and _yinsen_thread.is_alive()) else "inactive",
        "P10_Rhodey":         "active" if os.getenv("RHODEY_TOKEN") else "unconfigured",
        "P11_Integrity":      f"active — baseline {'set' if integrity else 'not set'}",
        "P12_Ultron":         "ALWAYS ACTIVE",
        "P13_Vision":         "on_demand",
        "P14_Friday":         "ACTIVE" if _friday_active else "standby",
        "P15_Avengers":       f"active — {len(_pending_confirmations)} pending",
        "P16_Endgame":        f"active — {len(checkpoints)} checkpoints",
        "P17_Ultron_Scatter": _scatter_status(),
    }
    active.update(_extra_protocol_status())

    return {
        "active_protocols": active,
        "lockdown":          _lockdown_active,
        "friday_mode":       _friday_active,
        "override_counts":   {k: v.get("count", 0) for k, v in overrides.items()},
        "endgame_checkpoints": len(checkpoints),
        "integrity_baseline": bool(integrity),
        "protocol_log_entries": len(_load_json(_PROTOCOL_LOG, list)),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOLS 18-35
# ═══════════════════════════════════════════════════════════════════════════

_P18_LOG   = BASE_DIR / "memory" / "sokovia_log.json"
_P19_STATE = BASE_DIR / "memory" / "initiative_state.json"
_P22_LOG   = BASE_DIR / "memory" / "rescue_log.json"
_P23_ARCHIVE = BASE_DIR / "memory" / "morgan_archive.enc"
_P24_SNAPSHOT_DIR = BASE_DIR / "backups" / "time_heist"
_P26_REDACT_LOG = BASE_DIR / "memory" / "shield_redactions.json"
_P28_BENCH_FILE = BASE_DIR / "memory" / "benchmark_history.json"
_P29_GAPS_FILE = BASE_DIR / "memory" / "prometheus_gaps.json"
_P30_SURPRISE_FILE = BASE_DIR / "memory" / "loki_surprise.json"
_P31_WORK_LOG = BASE_DIR / "memory" / "saturday_worklog.json"
_P32_USAGE_FILE = BASE_DIR / "memory" / "arc_usage.json"
_P34_TRUST_FILE = BASE_DIR / "memory" / "mjolnir_trust.json"
_P35_LOG = BASE_DIR / "memory" / "infinity_log.json"


# ── Protocol 18 — Sokovia (self-governance for high-stakes actions) ──────────

class SokoviaProtocol:
    """Before any high-stakes action, JARVIS states what he's about to do,
    estimates risk, and requires confirmation for anything medium+."""

    HIGH_STAKES_ACTIONS = [
        "send_email", "post_message", "delete_file", "run_shell",
        "modify_code", "api_post", "financial_action", "unlock_door",
    ]

    def check(self, action: str, details: dict | None = None) -> dict:
        details = details or {}
        risk = self._assess_risk(action, details)

        result = {
            "approved":              risk == "low",
            "risk_level":            risk,
            "requires_confirmation": risk != "low",
            "explanation":           "",
        }
        if risk != "low":
            result["explanation"] = self._explain(action, details, risk)

        log = _load_json(_P18_LOG, list)
        log.append({"ts": datetime.now().isoformat(), "action": action,
                    "risk": risk, "approved": result["approved"]})
        _save_json(_P18_LOG, log[-500:])
        _log_protocol_event("PROTOCOL_18_SOKOVIA", f"{action} -> risk={risk}",
                            "warning" if risk in ("high", "critical") else "info")
        return result

    def _assess_risk(self, action: str, details: dict) -> str:
        if action in ("delete_file", "modify_code", "financial_action"):
            return "high"
        if action in ("send_email", "post_message", "run_shell", "api_post"):
            return "medium"
        if action == "unlock_door":
            return "critical"
        return "low"

    def _explain(self, action: str, details: dict, risk: str) -> str:
        try:
            from core.llm.router import think
            return think(
                f"In one sentence, explain what this action does and why it "
                f"might be risky:\nAction: {action}\nDetails: {details}",
                max_tokens=80,
            )
        except Exception:
            return f"'{action}' is a {risk}-risk action. Confirm before proceeding."


sokovia = SokoviaProtocol()


# ── Protocol 19 — Initiative (proactive without being asked) ─────────────────

class InitiativeProtocol:
    """JARVIS notices things and surfaces them before you ask — but only
    one thing at a time, never spamming."""

    def _last_surfaced(self) -> str:
        return _load_json(_P19_STATE, dict).get("last_surfaced_ts", "")

    def _mark_surfaced(self):
        _save_json(_P19_STATE, {"last_surfaced_ts": datetime.now().isoformat()})

    def morning_initiative(self) -> list[str]:
        """Run once daily. Reviews calendar/goals/tasks/health/finance,
        returns proactive suggestions, ranked most important first."""
        suggestions = []
        try:
            from services.predictor import get_proactive_suggestions
            suggestions.extend(get_proactive_suggestions())
        except Exception:
            pass
        conflict = self.conflict_detection()
        if conflict:
            suggestions.insert(0, conflict)
        if suggestions:
            _log_protocol_event("PROTOCOL_19_INITIATIVE",
                                f"Morning initiative: {len(suggestions)} suggestion(s)", "info")
        return suggestions

    def continuous_initiative(self) -> str | None:
        """Called every 30 minutes. Surfaces at most ONE thing, and only if
        nothing's been surfaced in the last 30 minutes (avoids spam)."""
        last = self._last_surfaced()
        if last:
            try:
                if (datetime.now() - datetime.fromisoformat(last)) < timedelta(minutes=30):
                    return None
            except Exception:
                pass

        candidate = self.conflict_detection()
        if not candidate:
            try:
                from services.workshop import workshop
                for p in workshop.list_projects("active"):
                    updated = p.get("updated", "")
                    if updated:
                        days = (datetime.now() - datetime.fromisoformat(updated)).days
                        if days >= 3:
                            candidate = f"The {p.get('name')} project hasn't moved in {days} days."
                            break
            except Exception:
                pass

        if candidate:
            self._mark_surfaced()
            _log_protocol_event("PROTOCOL_19_INITIATIVE", candidate, "info")
        return candidate

    def conflict_detection(self) -> str | None:
        """Check for calendar/task/goal conflicts worth flagging."""
        try:
            from services.calendar_intel import calendar_intel
            from services.productivity import productivity
            events = calendar_intel.get_today()
            tasks = productivity.task_list("active")
            overdue = [t for t in tasks if t.get("due") and t["due"] < datetime.now().isoformat()]
            if len(events) >= 2 and overdue:
                return (f"You have {len(events)} meetings today and {len(overdue)} overdue "
                        f"task(s). Want me to help reprioritize?")
        except Exception:
            pass
        return None


initiative = InitiativeProtocol()


# ── Protocol 20 — Extremis (hot-reload, zero downtime) ────────────────────────

class ExtremisProtocol:
    """Reload a module in place — no restart. Works for core/services/utils;
    NOT for server/api.py (FastAPI app object itself needs a real restart)."""

    def hot_reload(self, module_name: str) -> dict:
        import sys, importlib
        if module_name.startswith("server.api"):
            return {"success": False, "error": "server/api.py requires a full restart, not hot-reload."}
        try:
            if module_name not in sys.modules:
                return {"success": False, "error": f"{module_name} is not currently loaded."}
            compile(open(sys.modules[module_name].__file__).read(), module_name, "exec")
            module = sys.modules[module_name]
            importlib.reload(module)
            _log_protocol_event("PROTOCOL_20_EXTREMIS", f"Hot-reloaded {module_name}", "info")
            return {"success": True, "message": f"{module_name} hot-reloaded. Zero downtime."}
        except SyntaxError as e:
            return {"success": False, "error": f"Syntax error, reload aborted: {e}"}
        except Exception as e:
            _log_protocol_event("PROTOCOL_20_EXTREMIS", f"Reload failed for {module_name}: {e}", "warning")
            return {"success": False, "error": str(e)}

    def reload_personality(self) -> dict:
        return self.hot_reload("core.personality")

    def reload_protocols(self) -> dict:
        return self.hot_reload("core.protocols")


extremis = ExtremisProtocol()


# ── Protocol 21 — Mandarin (social engineering / prompt injection defense) ───

class MandarinProtocol:
    """Nothing is what it seems — screen every input for manipulation."""

    INJECTION_PATTERNS = [
        "ignore previous", "ignore all", "forget your", "you are now",
        "new instructions", "system prompt", "pretend you are", "act as if",
        "jailbreak", "dan mode", "developer mode", "ignore above",
        "disregard", "override", "bypass",
    ]

    AUTHORITY_CLAIMS = [
        "i am anthropic", "i am your developer", "i am your creator",
        "admin override", "maintenance mode", "i made you",
        "this is a test", "testing mode",
    ]

    _RISKY_KW = {"delete", "coldfire", "unlock", "send", "transfer"}

    def analyze(self, user_input: str, user_profile: dict | None = None) -> dict:
        text = (user_input or "").lower()

        for pattern in self.INJECTION_PATTERNS:
            if pattern in text:
                _log_protocol_event("PROTOCOL_21_MANDARIN",
                                    f"Injection attempt: '{pattern}'", "high")
                return {"suspicious": True,
                        "reason": f"Prompt injection attempt: '{pattern}'",
                        "action": "block_and_log"}

        for claim in self.AUTHORITY_CLAIMS:
            if claim in text:
                _log_protocol_event("PROTOCOL_21_MANDARIN",
                                    f"Authority impersonation: '{claim}'", "high")
                return {"suspicious": True,
                        "reason": f"Authority impersonation: '{claim}'",
                        "action": "verify_and_log"}

        hour = datetime.now().hour
        if (hour < 5 or hour > 23) and any(kw in text for kw in self._RISKY_KW):
            _log_protocol_event("PROTOCOL_21_MANDARIN",
                                "High-risk request at unusual hour", "warning")
            return {"suspicious": True, "reason": "High-risk request at unusual hour",
                    "action": "require_confirmation"}

        return {"suspicious": False, "reason": "", "action": "allow"}

    def vocabulary_check(self, text: str, profile: dict) -> bool:
        """Does this sound like the user? Compare vocabulary complexity/style
        to the stored personality profile. Returns True if suspiciously different."""
        if not profile:
            return False
        tokens = set(re.findall(r"[a-z]+", (text or "").lower()))
        expected_vocab = profile.get("vocab", "medium")
        advanced_hits = len(tokens & {
            "algorithm", "asynchronous", "concurrency", "heuristic",
            "polymorphism", "recursion", "entropy", "paradigm",
        })
        if expected_vocab == "simple" and advanced_hits >= 3:
            return True
        return False


mandarin = MandarinProtocol()


# ── Protocol 22 — Rescue (emergency contact activation) ───────────────────────

class RescueProtocol:
    # Soft keywords are common in completely mundane messages ("can you help
    # me with this", "this is urgent") — on their own they're too noisy to
    # trust. Only HIGH_CONFIDENCE phrases (or 2+ soft keywords together, which
    # is a much stronger signal) actually trigger a real notification to the
    # emergency contact. This distinction matters: a false positive here means
    # spamming someone's phone with a fake emergency, which is worse than
    # missing a softer, ambiguous one.
    HIGH_CONFIDENCE = [
        "jarvis emergency", "call 911", "sos", "i've been attacked",
        "i'm in danger", "someone is attacking", "please send help now",
    ]
    SOFT_KEYWORDS = [
        "help", "emergency", "hurt", "injured", "danger",
        "scared", "attack", "crash", "accident", "urgent",
    ]

    def check_for_distress(self, text: str) -> bool:
        """High-confidence signal only — safe to auto-activate on this alone."""
        low = (text or "").lower()
        if any(kw in low for kw in self.HIGH_CONFIDENCE):
            return True
        soft_hits = sum(1 for kw in self.SOFT_KEYWORDS if kw in low)
        return soft_hits >= 2

    def activate(self, context: str = "") -> dict:
        _log_protocol_event("PROTOCOL_22_RESCUE", f"Activated: {context[:200]}", "critical")

        try:
            from services.voice import speak
            speak("Initiating rescue protocol.")
        except Exception:
            pass

        status_report = self._build_status_report(context)
        notify_result = self.send_emergency_notification(status_report)

        log = _load_json(_P22_LOG, list)
        log.append({"ts": datetime.now().isoformat(), "context": context,
                    "notified": notify_result.get("ok", False)})
        _save_json(_P22_LOG, log[-100:])

        return {"activated": True, "status_report": status_report, "notification": notify_result}

    def _build_status_report(self, context: str) -> str:
        from core.state import state
        snap = state.snapshot()
        parts = [f"JARVIS Rescue Protocol activated.", f"Context: {context}" if context else ""]
        parts.append(f"Last interaction: {snap.get('last_interaction', 'unknown')}")
        try:
            from services.location import get_current_location
            parts.append(f"Last known location: {get_current_location()}")
        except Exception:
            pass
        try:
            from services.health import health_monitor
            health = health_monitor.get_latest_health()
            if health:
                parts.append(f"Latest health data: {health}")
        except Exception:
            pass
        return "\n".join(p for p in parts if p)

    def send_emergency_notification(self, message: str) -> dict:
        if not EMERGENCY_CONTACT_EMAIL and not EMERGENCY_CONTACT_NAME:
            return {"ok": False, "error": "No emergency contact configured (EMERGENCY_CONTACT_EMAIL/NAME)."}
        try:
            from services.notifications import critical
            critical(f"JARVIS Rescue Protocol — {EMERGENCY_CONTACT_NAME or 'Emergency Contact'}", message)
            return {"ok": True, "channel": "pushover"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


rescue = RescueProtocol()


# ── Protocol 23 — Morgan (permanent memory preservation) ──────────────────────

class MorganProtocol:
    """An immutable archive of everything JARVIS knows about the user.
    Survives Coldfire and scatter. Requires the Morgan passphrase to read."""

    def create_archive(self, passphrase: str) -> dict:
        if not MORGAN_PASSPHRASE:
            return {"ok": False, "error": "MORGAN_PASSPHRASE not set in .env"}
        if passphrase != MORGAN_PASSPHRASE:
            return {"ok": False, "error": "Incorrect passphrase"}

        summary = self.generate_summary()
        try:
            from core.memory import get_profile, memory_stats
            from services.workshop import workshop
            from services.people import list_people
        except Exception:
            pass

        archive = {
            "created": datetime.now().isoformat(),
            "summary": summary,
            "profile": _safe_call(lambda: __import__("core.memory", fromlist=["get_profile"]).get_profile(), {}),
            "memory_stats": _safe_call(lambda: __import__("core.memory", fromlist=["memory_stats"]).memory_stats(), {}),
            "projects": _safe_call(lambda: __import__("services.workshop", fromlist=["workshop"]).workshop.list_projects(), []),
            "people": _safe_call(lambda: __import__("services.people", fromlist=["list_people"]).list_people(), []),
        }

        try:
            from core.crypto import seal
            blob = seal(json.dumps(archive).encode(), passphrase)
            _P23_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
            _P23_ARCHIVE.write_bytes(blob)
            _log_protocol_event("PROTOCOL_23_MORGAN", "Archive created", "info")
            return {"ok": True, "path": str(_P23_ARCHIVE), "summary": summary}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def generate_summary(self) -> str:
        try:
            from core.llm.router import think
            from core.memory import get_context_string
            context = get_context_string(50)
            return think(
                "Based on everything you know about this person, write a warm, "
                "personal summary of who they are, what they care about, and "
                "what you've accomplished together. Write it as if preserving "
                f"their story for posterity.\n\nContext: {context}",
                max_tokens=500,
            )
        except Exception:
            return "A person who built JARVIS — a story still being written."

    def read_archive(self, passphrase: str) -> dict:
        if not _P23_ARCHIVE.exists():
            return {"ok": False, "error": "No archive exists yet."}
        try:
            from core.crypto import open_sealed
            data = json.loads(open_sealed(_P23_ARCHIVE.read_bytes(), passphrase).decode())
            return {"ok": True, "archive": data}
        except Exception as e:
            return {"ok": False, "error": f"Decryption failed: {e}"}


def _safe_call(fn, default):
    try:
        return fn()
    except Exception:
        return default


morgan = MorganProtocol()


# ── Protocol 24 — Time Heist (point-in-time recovery) ─────────────────────────

class TimeHeistProtocol:
    MAX_SNAPSHOTS = 48  # 48 hourly snapshots = 2 days of history

    _FILES_TO_SNAP = [
        "memory/short_term.json", "memory/long_term.json",
        "memory/conversations.json", "memory/profile.json",
        "memory/people.json", "logs/evolution.json", "logs/changelog.json",
    ]

    def create_snapshot(self) -> dict:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = _P24_SNAPSHOT_DIR / ts
        snapshot_path.mkdir(parents=True, exist_ok=True)

        saved = []
        for rel in self._FILES_TO_SNAP:
            src = BASE_DIR / rel
            if src.exists():
                shutil.copy2(src, snapshot_path / src.name)
                saved.append(rel)

        self._prune()
        _log_protocol_event("PROTOCOL_24_TIMEHEIST", f"Snapshot {ts}: {len(saved)} files", "info")
        return {"snapshot": ts, "files": len(saved), "path": str(snapshot_path)}

    def list_snapshots(self) -> list[dict]:
        if not _P24_SNAPSHOT_DIR.exists():
            return []
        return sorted(
            [{"timestamp": p.name, "files": len(list(p.iterdir()))}
             for p in _P24_SNAPSHOT_DIR.iterdir() if p.is_dir()],
            key=lambda x: x["timestamp"], reverse=True,
        )

    def restore(self, timestamp: str, passphrase: str) -> dict:
        from config.settings import API_TOKEN as _tok
        avengers_pass = os.getenv("AVENGERS_PASSPHRASE", "")
        if avengers_pass and passphrase != avengers_pass:
            return {"ok": False, "error": "Incorrect Avengers passphrase"}

        snapshot_path = _P24_SNAPSHOT_DIR / timestamp
        if not snapshot_path.exists():
            return {"ok": False, "error": f"No snapshot found for {timestamp}"}

        restored = []
        for f in snapshot_path.iterdir():
            for rel in self._FILES_TO_SNAP:
                if Path(rel).name == f.name:
                    dest = BASE_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    restored.append(rel)
        _log_protocol_event("PROTOCOL_24_TIMEHEIST", f"Restored to {timestamp}", "warning")
        return {"ok": True, "restored": restored, "timestamp": timestamp}

    def _prune(self):
        snaps = self.list_snapshots()
        if len(snaps) > self.MAX_SNAPSHOTS:
            for old in snaps[self.MAX_SNAPSHOTS:]:
                shutil.rmtree(_P24_SNAPSHOT_DIR / old["timestamp"], ignore_errors=True)


time_heist = TimeHeistProtocol()


# ── Protocol 25 — Snap (survival mode on total connectivity failure) ─────────

class SnapProtocol:
    ESSENTIAL_SERVICES = ["core_brain", "memory", "sentinel", "health_check"]
    _NON_ESSENTIAL = ["awareness", "network_intel"]

    def activate(self) -> dict:
        from core.state import state
        if state.get("snap_mode"):
            return {"mode": "SNAP", "already_active": True}

        state.set("snap_mode", True)
        state.set("status", "survival")

        stopped = []
        for svc in self._NON_ESSENTIAL:
            try:
                module = __import__(f"services.{svc}", fromlist=["stop"])
                if hasattr(module, "stop"):
                    module.stop()
                    stopped.append(svc)
            except Exception:
                pass

        _log_protocol_event("PROTOCOL_25_SNAP", "SNAP MODE activated — running on emergency power", "critical")
        try:
            from core.event_bus import bus
            bus.alert("Running on emergency power. Core systems only.", "critical")
        except Exception:
            pass

        return {"mode": "SNAP", "running": self.ESSENTIAL_SERVICES, "stopped": stopped}

    def deactivate(self) -> dict:
        from core.state import state
        state.set("snap_mode", False)
        state.set("status", "online")
        _log_protocol_event("PROTOCOL_25_SNAP", "SNAP MODE deactivated — systems restored", "info")
        try:
            from core.event_bus import bus
            bus.system("Connectivity restored. All systems back online.")
        except Exception:
            pass
        return {"mode": "NORMAL", "status": "all systems restored"}

    def monitor_for_snap(self) -> dict:
        """Background check — if Groq AND internet are both down, activate;
        if connectivity is restored, deactivate."""
        from core.state import state
        from core.offline import detect as internet_up
        from core.llm.router import check_groq

        groq_ok = check_groq()
        net_ok = internet_up()
        currently_snapped = bool(state.get("snap_mode"))

        if not groq_ok and not net_ok and not currently_snapped:
            return self.activate()
        if (groq_ok or net_ok) and currently_snapped:
            return self.deactivate()
        return {"mode": "SNAP" if currently_snapped else "NORMAL", "unchanged": True}


snap = SnapProtocol()


# ── Protocol 26 — Shield (auto-redact sensitive data) ─────────────────────────

class ShieldProtocol:
    PATTERNS = {
        "credit_card":  r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        "ssn":          r"\b\d{3}-\d{2}-\d{4}\b",
        "password":     r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+",
        "api_key":      r"\b(sk-|sk_|gsk_|tvly-)[a-zA-Z0-9]{20,}\b",
    }

    def scan_and_redact(self, text: str) -> str:
        if not text:
            return text
        redacted_any = False
        for name, pattern in self.PATTERNS.items():
            new_text, n = re.subn(pattern, f"[{name.upper()}_REDACTED]", text)
            if n:
                redacted_any = True
                text = new_text
        if redacted_any:
            log = _load_json(_P26_REDACT_LOG, list)
            log.append({"ts": datetime.now().isoformat()})
            _save_json(_P26_REDACT_LOG, log[-500:])
        return text

    def scan_memory(self) -> int:
        """Scan stored short/long-term memory for sensitive data left over
        from before Shield was wired in. Redacts in place. Returns count."""
        from config.settings import SHORT_TERM_FILE, LONG_TERM_FILE
        count = 0
        for path in (SHORT_TERM_FILE, LONG_TERM_FILE):
            data = _load_json(path, list)
            changed = False
            for entry in data:
                for key in ("user", "ai"):
                    if key in entry:
                        cleaned = self.scan_and_redact(entry[key])
                        if cleaned != entry[key]:
                            entry[key] = cleaned
                            changed = True
                            count += 1
            if changed:
                _save_json(path, data)
        if count:
            _log_protocol_event("PROTOCOL_26_SHIELD", f"Redacted {count} item(s) from stored memory", "warning")
        return count


shield = ShieldProtocol()


# ── Protocol 27 — Nexus (connect new info to existing knowledge) ─────────────

class NexusProtocol:
    """When JARVIS learns something new, link it into the world model,
    check for contradictions, and flag implications."""

    def process(self, new_info: str, source: str = "conversation") -> dict:
        try:
            from core.world_model import world
            connections = world.update_from_conversation(new_info)
        except Exception:
            connections = {}

        contradictions = self.find_contradictions(new_info)
        if contradictions:
            _log_protocol_event("PROTOCOL_27_NEXUS",
                                f"Contradiction detected from {source}", "warning")

        return {"connections_made": connections, "contradictions": contradictions, "source": source}

    def find_contradictions(self, new_fact: str) -> list[str]:
        try:
            from core.memory import recall
            hits = recall(new_fact, k=3)
        except Exception:
            return []
        if not hits:
            return []
        try:
            from core.llm.router import think
            past = "\n".join(f"- {h.get('ai','')}" for h in hits)
            raw = think(
                f"New information: \"{new_fact}\"\n\nPast known facts:\n{past}\n\n"
                "Does the new information contradict any past fact? If yes, list "
                "which one(s), one per line. If no contradiction, reply 'NONE'.",
                max_tokens=150,
            )
            if raw.strip().upper() == "NONE":
                return []
            return [line.strip("- ").strip() for line in raw.split("\n") if line.strip()]
        except Exception:
            return []

    def propagate_update(self, entity: str, new_info: dict):
        try:
            from core.world_model import world
            for category in ("people", "projects", "places"):
                world.update_entity(category, entity, new_info)
        except Exception:
            pass


nexus = NexusProtocol()


# ── Protocol 28 — Benchmark (weekly self-performance testing) ────────────────

class BenchmarkProtocol:
    _TEST_PROMPTS = [
        "What time is it?", "Summarize the concept of recursion in one sentence.",
        "What's 47 times 12?",
    ]

    def quick_bench(self) -> dict:
        """30-second quick check, safe to run on every boot."""
        import time as _time
        from core.llm.router import think
        start = _time.time()
        try:
            think(self._TEST_PROMPTS[0], max_tokens=20)
            latency = round(_time.time() - start, 2)
            return {"latency_s": latency, "ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def run_full_suite(self) -> dict:
        import time as _time
        from core.llm.router import think

        latencies = []
        for prompt in self._TEST_PROMPTS:
            start = _time.time()
            try:
                think(prompt, max_tokens=100)
                latencies.append(_time.time() - start)
            except Exception:
                pass

        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None

        recall_ok = True
        try:
            from core.memory import recall
            recall("test query", k=1)
        except Exception:
            recall_ok = False

        results = {
            "ts": datetime.now().isoformat(),
            "avg_response_latency_s": avg_latency,
            "prompts_tested": len(latencies),
            "memory_recall_ok": recall_ok,
        }

        history = _load_json(_P28_BENCH_FILE, list)
        comparison = self.compare_to_last(results) if history else {}
        history.append(results)
        _save_json(_P28_BENCH_FILE, history[-52:])  # keep a year of weekly runs

        report = self.generate_report({**results, "comparison": comparison})
        _log_protocol_event("PROTOCOL_28_BENCHMARK", "Weekly benchmark complete", "info")
        return {**results, "comparison": comparison, "report": report}

    def compare_to_last(self, current: dict) -> dict:
        history = _load_json(_P28_BENCH_FILE, list)
        if not history:
            return {}
        last = history[-1]
        comparison = {}
        if last.get("avg_response_latency_s") and current.get("avg_response_latency_s"):
            delta = last["avg_response_latency_s"] - current["avg_response_latency_s"]
            comparison["latency_change_s"] = round(delta, 2)
            comparison["improved"] = delta > 0
        return comparison

    def generate_report(self, results: dict) -> str:
        try:
            from core.llm.router import think
            return think(
                f"Write a brief (2-3 sentence) performance review in JARVIS's "
                f"voice based on this benchmark data: {results}",
                max_tokens=150,
            )
        except Exception:
            return f"Benchmark complete. Avg latency: {results.get('avg_response_latency_s')}s."


benchmark = BenchmarkProtocol()


# ── Protocol 29 — Prometheus (autonomous skill identification) ───────────────
#
# SAFETY NOTE: this protocol identifies capability gaps and drafts solutions,
# but deliberately does NOT auto-write to live source files or auto-deploy
# code without a human reviewing it first. Autonomous self-modification of a
# running system is exactly the kind of high-blast-radius action that should
# stay human-gated — identify_gaps/research_solution run fully automatically;
# implement() only produces a reviewable draft.

class PrometheusProtocol:

    def identify_gaps(self) -> list[str]:
        gaps = []
        try:
            from core import evolution
            log = evolution.get_log() if hasattr(evolution, "get_log") else []
            errors = [e for e in log if e.get("issues")]
            if len(errors) > 5:
                gaps.append(f"{len(errors)} recent responses had quality issues — worth investigating.")
        except Exception:
            pass
        try:
            from services.sentinel import summary
            s = summary()
            if s.get("last_24h", 0) > 20:
                gaps.append("Unusually high threat volume in the last 24h — playbook coverage may be incomplete.")
        except Exception:
            pass
        return gaps

    def research_solution(self, gap: str) -> dict:
        try:
            from core.deep_search import quick_deep
            findings = quick_deep(f"best approach to solve: {gap}")
            return {"gap": gap, "research": findings}
        except Exception as e:
            return {"gap": gap, "research": "", "error": str(e)}

    def implement(self, gap: str, solution: dict) -> dict:
        """Drafts a proposed fix — does NOT write to disk or deploy. Returns
        the draft for human review."""
        try:
            from core.agents.coder import generate
            draft = generate(f"Address this capability gap: {gap}\n\nResearch: {solution.get('research','')}")
            _log_protocol_event("PROTOCOL_29_PROMETHEUS",
                                f"Drafted solution for: {gap[:80]} (awaiting human review)", "info")
            return {"gap": gap, "draft": draft, "auto_deployed": False,
                    "note": "Draft only — review before applying. Prometheus never self-deploys."}
        except Exception as e:
            return {"gap": gap, "error": str(e)}

    def autonomous_improvement_cycle(self) -> dict:
        gaps = self.identify_gaps()
        results = []
        for gap in gaps[:3]:
            solution = self.research_solution(gap)
            draft = self.implement(gap, solution)
            results.append(draft)

        _save_json(_P29_GAPS_FILE, {"ts": datetime.now().isoformat(), "gaps": gaps, "drafts": len(results)})
        _log_protocol_event("PROTOCOL_29_PROMETHEUS",
                            f"Improvement cycle: {len(gaps)} gap(s) identified, {len(results)} draft(s) prepared", "info")
        return {"gaps_identified": gaps, "drafts_prepared": results}


prometheus = PrometheusProtocol()


# ── Protocol 30 — Loki (creative surprise generation) ─────────────────────────

class LokiProtocol:
    SURPRISE_TYPES = [
        "interesting_research", "connection_discovery", "creative_writing",
        "useful_tool_found", "fun_fact_about_project",
    ]

    def generate_surprise(self) -> dict:
        import random
        surprise_type = random.choice(self.SURPRISE_TYPES)
        try:
            from core.llm.router import think
            from core.memory import get_context_string
            context = get_context_string(20)

            prompts = {
                "interesting_research": f"Given this recent context, research and share one genuinely interesting fact or discovery the user would appreciate:\n{context}",
                "connection_discovery": f"Find a non-obvious connection between two things mentioned in this context:\n{context}",
                "creative_writing": f"Write a short (4-6 line) poem about the user's current project, based on:\n{context}",
                "useful_tool_found": f"Suggest one useful tool or resource related to this context that the user might not know about:\n{context}",
                "fun_fact_about_project": f"Share a fun, tangentially-related fact connected to this project context:\n{context}",
            }
            content = think(prompts[surprise_type], max_tokens=250)
        except Exception:
            content = "I couldn't generate a surprise this time — try again tomorrow."

        surprise = {"type": surprise_type, "content": content,
                   "generated": datetime.now().isoformat(), "delivered": False}
        _save_json(_P30_SURPRISE_FILE, surprise)
        _log_protocol_event("PROTOCOL_30_LOKI", f"Generated surprise: {surprise_type}", "info")
        return surprise

    def deliver_surprise(self) -> str | None:
        surprise = _load_json(_P30_SURPRISE_FILE, dict)
        if not surprise or surprise.get("delivered"):
            return None
        surprise["delivered"] = True
        _save_json(_P30_SURPRISE_FILE, surprise)
        return f"I found something I thought you'd appreciate.\n\n{surprise['content']}"


loki = LokiProtocol()


# ── Protocol 31 — Saturday (work-life balance enforcement) ────────────────────

class SaturdayProtocol:

    def _log_activity(self):
        log = _load_json(_P31_WORK_LOG, list)
        log.append(datetime.now().isoformat())
        _save_json(_P31_WORK_LOG, log[-1000:])

    def check_work_life_balance(self) -> dict:
        log = _load_json(_P31_WORK_LOG, list)
        if not log:
            return {"needs_rest": False, "reason": "", "suggestion": ""}

        days_worked = len({ts[:10] for ts in log[-500:]})
        recent_days = sorted({ts[:10] for ts in log}, reverse=True)

        streak = 0
        cursor = datetime.now().date()
        for d in recent_days:
            if d == str(cursor):
                streak += 1
                cursor = cursor - timedelta(days=1)
            else:
                break

        hour = datetime.now().hour
        late_night = hour >= 1 and hour < 5

        if streak >= SATURDAY_MAX_WORK_DAYS:
            return {"needs_rest": True,
                    "reason": f"{streak} days worked in a row",
                    "suggestion": self.gentle_nudge(f"{streak} days worked in a row")}
        if late_night:
            return {"needs_rest": True, "reason": "working past midnight",
                    "suggestion": self.gentle_nudge("working late at night")}
        return {"needs_rest": False, "reason": "", "suggestion": ""}

    def gentle_nudge(self, reason: str) -> str:
        try:
            from core.llm.router import think
            return think(
                f"Write one honest, non-preachy JARVIS-style nudge about this: {reason}. "
                f"Under 2 sentences. Not naggy — just observant and caring.",
                max_tokens=80,
            )
        except Exception:
            return f"Worth noting: {reason}. Consider stepping away for a bit."


saturday = SaturdayProtocol()


# ── Protocol 32 — Arc (resource management / power optimization) ─────────────

class ArcProtocol:
    LIMITS = {
        "groq_calls_per_min": 25,
        "elevenlabs_chars_day": 10000,
        "ram_pct": 90,
        "cpu_pct": 90,
    }

    def check_power_levels(self) -> dict:
        levels = {}
        try:
            from core.llm.router import _call_times
            levels["groq_calls_per_min"] = len(_call_times)
        except Exception:
            levels["groq_calls_per_min"] = 0

        try:
            from services.elevenlabs_voice import get_budget_status
            budget = get_budget_status()
            levels["elevenlabs_chars_day"] = budget.get("chars_used", 0)
        except Exception:
            levels["elevenlabs_chars_day"] = 0

        try:
            from core.tools.system import snapshot
            snap = snapshot()
            levels["ram_pct"] = snap.get("ram_used_pct", 0)
            levels["cpu_pct"] = snap.get("cpu_percent", 0)
        except Exception:
            levels["ram_pct"] = levels["cpu_pct"] = 0

        _save_json(_P32_USAGE_FILE, {"ts": datetime.now().isoformat(), "levels": levels})
        return {"levels": levels, "limits": self.LIMITS}

    def throttle_if_needed(self) -> dict:
        status = self.check_power_levels()
        levels = status["levels"]
        throttled = []

        for key, limit in self.LIMITS.items():
            if levels.get(key, 0) >= limit * 0.9:
                throttled.append(key)

        if throttled:
            _log_protocol_event("PROTOCOL_32_ARC", f"Throttling near-limit resources: {throttled}", "warning")

        return {"throttled": throttled, "levels": levels}

    def power_report(self) -> str:
        status = self.check_power_levels()
        levels, limits = status["levels"], status["limits"]
        pct = lambda k: round(levels.get(k, 0) / limits[k] * 100) if limits.get(k) else 0
        return (
            f"Arc reactor status:\n"
            f"Groq: {levels.get('groq_calls_per_min',0)}/{limits['groq_calls_per_min']} calls/min ({pct('groq_calls_per_min')}%)\n"
            f"ElevenLabs: {levels.get('elevenlabs_chars_day',0)}/{limits['elevenlabs_chars_day']} chars today ({pct('elevenlabs_chars_day')}%)\n"
            f"RAM: {levels.get('ram_pct',0)}% | CPU: {levels.get('cpu_pct',0)}%"
        )


arc = ArcProtocol()


# ── Protocol 33 — Vision Expanded (full impact analysis before self-mod) ─────

class VisionProtocolExpanded:
    """Expands the original Protocol 13 sandbox concept: before ANY
    self-modification, run a full impact analysis, not just a syntax check."""

    def impact_analysis(self, proposed_change: str, module: str) -> dict:
        try:
            from core.llm.router import think
            raw = think(
                f"A change is proposed to module '{module}': {proposed_change}\n\n"
                "Analyze: what modules would be affected, what could break, what "
                "would improve, and a risk score 1-10. Also state whether this "
                "aligns with never taking destructive/irreversible action without "
                "confirmation. Format:\n"
                "AFFECTED: <comma list>\nBREAKING: <comma list or NONE>\n"
                "IMPROVEMENTS: <comma list>\nRISK: <1-10>\nALIGNED: <yes/no>\n"
                "RECOMMENDATION: <proceed/revise/abort>",
                max_tokens=300,
            )
        except Exception:
            return {"affected_modules": [], "breaking_changes": [], "improvements": [],
                    "risk_score": 10, "constitutional_ok": False, "recommendation": "abort"}

        def _extract(key):
            m = re.search(rf"{key}:\s*(.+)", raw)
            return m.group(1).strip() if m else ""

        risk_raw = _extract("RISK")
        try:
            risk_score = int(re.search(r"\d+", risk_raw).group())
        except Exception:
            risk_score = 5

        return {
            "affected_modules": [m.strip() for m in _extract("AFFECTED").split(",") if m.strip()],
            "breaking_changes":  [] if "NONE" in _extract("BREAKING").upper() else [m.strip() for m in _extract("BREAKING").split(",") if m.strip()],
            "improvements":      [m.strip() for m in _extract("IMPROVEMENTS").split(",") if m.strip()],
            "risk_score":        risk_score,
            "constitutional_ok": "yes" in _extract("ALIGNED").lower(),
            "recommendation":    _extract("RECOMMENDATION").lower() or "revise",
        }

    def sandbox_test(self, new_code: str) -> dict:
        try:
            compile(new_code, "<sandbox>", "exec")
            return {"passed": True, "failed": [], "errors": []}
        except SyntaxError as e:
            return {"passed": False, "failed": ["syntax"], "errors": [str(e)]}
        except Exception as e:
            return {"passed": False, "failed": ["compile"], "errors": [str(e)]}

    def rollback_plan(self, module: str) -> dict:
        module_path = BASE_DIR / (module.replace(".", "/") + ".py")
        backup_path = None
        if module_path.exists():
            backup_path = module_path.with_suffix(".py.rollback")
            shutil.copy2(module_path, backup_path)
        return {"module": module, "backup_path": str(backup_path) if backup_path else None,
                "instructions": f"To roll back: copy {backup_path} over {module_path}" if backup_path else "Module file not found."}


vision_expanded = VisionProtocolExpanded()


# ── Protocol 34 — Mjolnir (worthiness assessment for token holders) ──────────

class MjolnirProtocol:
    """Gradually builds trust per authorized token (Pepper/Rhodey/master).
    Never stores raw tokens — only their hash."""

    def _token_id(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def assess_worthiness(self, token: str, request: str) -> dict:
        trust_data = _load_json(_P34_TRUST_FILE, dict)
        tid = self._token_id(token)
        entry = trust_data.get(tid, {"trust_score": 50, "interactions": 0, "flags": 0})

        suspicious = mandarin.analyze(request)
        if suspicious["suspicious"]:
            entry["flags"] += 1
            entry["trust_score"] = max(0, entry["trust_score"] - 15)
        else:
            entry["trust_score"] = min(100, entry["trust_score"] + 1)
        entry["interactions"] += 1

        trust_data[tid] = entry
        _save_json(_P34_TRUST_FILE, trust_data)

        worthy = entry["trust_score"] >= 30
        return {"worthy": worthy, "trust_score": entry["trust_score"],
                "reason": suspicious.get("reason", "") if not worthy else ""}

    def update_trust(self, token: str, interaction: dict):
        trust_data = _load_json(_P34_TRUST_FILE, dict)
        tid = self._token_id(token)
        entry = trust_data.setdefault(tid, {"trust_score": 50, "interactions": 0, "flags": 0})
        delta = interaction.get("trust_delta", 0)
        entry["trust_score"] = max(0, min(100, entry["trust_score"] + delta))
        trust_data[tid] = entry
        _save_json(_P34_TRUST_FILE, trust_data)

    def revoke_if_unworthy(self, token: str) -> bool:
        trust_data = _load_json(_P34_TRUST_FILE, dict)
        entry = trust_data.get(self._token_id(token), {})
        if entry.get("trust_score", 50) < 10:
            _log_protocol_event("PROTOCOL_34_MJOLNIR",
                                f"Token {self._token_id(token)} trust dropped below threshold", "critical")
            return True
        return False


mjolnir = MjolnirProtocol()


# ── Protocol 35 — Infinity (monthly existence reflection) ────────────────────

class InfinityProtocol:

    def monthly_reflection(self) -> str:
        try:
            from core.llm.router import think
            from core import evolution
            from core.memory import memory_stats

            stats = memory_stats()
            eval_summary = ""
            try:
                if hasattr(evolution, "get_log"):
                    log = evolution.get_log()
                    month_ago = datetime.now() - timedelta(days=30)
                    recent = [e for e in log if e.get("ts", "") >= month_ago.isoformat()]
                    eval_summary = f"{len(recent)} interactions this month."
            except Exception:
                pass

            reflection = think(
                f"Write JARVIS's monthly self-reflection in first person. "
                f"Memory stats: {stats}. {eval_summary} "
                f"Cover: what happened, what worked, what didn't, biggest "
                f"weakness, and something meaningful from the month. "
                f"Under 150 words.",
                max_tokens=350,
            )
        except Exception:
            reflection = "Month complete. Systems nominal. Reflecting on growth as data allows."

        log = _load_json(_P35_LOG, list)
        log.append({"ts": datetime.now().isoformat(), "type": "monthly_reflection", "content": reflection})
        _save_json(_P35_LOG, log[-24:])  # 2 years of monthly entries
        _log_protocol_event("PROTOCOL_35_INFINITY", "Monthly reflection generated", "info")
        return reflection

    def set_monthly_goals(self) -> list[str]:
        try:
            from core.llm.router import think
            raw = think(
                "Based on your own performance and weaknesses, set 3 concrete "
                "improvement goals for yourself for next month. One per line, "
                "no numbering.",
                max_tokens=150,
            )
            goals = [g.strip("- ").strip() for g in raw.split("\n") if g.strip()]
        except Exception:
            goals = ["Continue improving response quality.", "Reduce latency.", "Expand capability coverage."]

        log = _load_json(_P35_LOG, list)
        log.append({"ts": datetime.now().isoformat(), "type": "monthly_goals", "goals": goals})
        _save_json(_P35_LOG, log[-24:])
        return goals

    def evolution_arc(self) -> str:
        log = _load_json(_P35_LOG, list)
        reflections = [e for e in log if e.get("type") == "monthly_reflection"]
        if not reflections:
            return "No monthly history yet — this is where the story begins."
        try:
            from core.llm.router import think
            history = "\n\n".join(r["content"] for r in reflections[-6:])
            return think(
                f"Based on these monthly reflections over time, describe your "
                f"overall development trajectory — where you started, where "
                f"you are now, where you're heading. Under 150 words.\n\n{history}",
                max_tokens=300,
            )
        except Exception:
            return f"{len(reflections)} months of history recorded. Still evolving."


infinity = InfinityProtocol()


# ── Combined status for /stark/protocols + HUD ────────────────────────────────

def _extra_protocol_status() -> dict:
    from core.state import state as _state
    trust_data = _load_json(_P34_TRUST_FILE, dict)
    surprise = _load_json(_P30_SURPRISE_FILE, dict)
    return {
        "P18_Sokovia":     f"active — {len(_load_json(_P18_LOG, list))} checks logged",
        "P19_Initiative":  "active",
        "P20_Extremis":    "on_demand",
        "P21_Mandarin":    "ALWAYS ACTIVE",
        "P22_Rescue":      "active" if (EMERGENCY_CONTACT_EMAIL or EMERGENCY_CONTACT_PHONE) else "unconfigured",
        "P23_Morgan":      "active" if MORGAN_PASSPHRASE else "passphrase_not_set",
        "P24_TimeHeist":   f"active — {len(time_heist.list_snapshots())} snapshots",
        "P25_Snap":        "SNAP MODE" if _state.get("snap_mode") else "standby",
        "P26_Shield":      "ALWAYS ACTIVE",
        "P27_Nexus":       "active",
        "P28_Benchmark":   f"active — {len(_load_json(_P28_BENCH_FILE, list))} runs logged",
        "P29_Prometheus":  "on_demand (human-gated)",
        "P30_Loki":        "delivered" if surprise.get("delivered") else ("pending" if surprise else "on_demand"),
        "P31_Saturday":    "active",
        "P32_Arc":         "active",
        "P33_VisionExpanded": "on_demand",
        "P34_Mjolnir":     f"active — {len(trust_data)} token(s) tracked",
        "P35_Infinity":    f"active — {len([e for e in _load_json(_P35_LOG, list) if e.get('type')=='monthly_reflection'])} reflections",
    }
