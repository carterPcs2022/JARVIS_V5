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
from config.settings import BASE_DIR, API_TOKEN


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
    _log_protocol("P17_Ultron_Scatter", "scatter", "Protocol 17 activated — scattering identity")
    return get_engine().scatter(passphrase)


def reassemble_identity(passphrase: str) -> dict:
    """Protocol 17: reassemble JARVIS from scattered shards."""
    from core.scatter import get_engine
    _log_protocol("P17_Ultron_Scatter", "reassemble", "Protocol 17 — reassembling identity")
    return get_engine().reassemble(passphrase)


# ── Active protocol status report ─────────────────────────────────────────────

def protocol_status() -> dict:
    overrides = _load_json(_OVERRIDES_FILE, dict)
    integrity = _load_json(_BASELINE_FILE, dict)
    checkpoints = endgame_list()
    return {
        "active_protocols": {
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
        },
        "lockdown":          _lockdown_active,
        "friday_mode":       _friday_active,
        "override_counts":   {k: v.get("count", 0) for k, v in overrides.items()},
        "endgame_checkpoints": len(checkpoints),
        "integrity_baseline": bool(integrity),
        "protocol_log_entries": len(_load_json(_PROTOCOL_LOG, list)),
    }
