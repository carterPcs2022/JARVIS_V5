"""services/sentinel.py — Security threat monitoring (JARVIS's immune system)."""
import os, json, time, threading, hashlib
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import psutil
from config.settings import SENTINEL_SCAN_INTERVAL, THREAT_LOG, ALERT_CPU, ALERT_RAM, ALERT_DISK

WATCHED = ["core/brain.py","core/llm/router.py","server/api.py","config/settings.py","app.py"]
# 10000 is Render's default web service port — expected there, not a threat.
EXPECTED_PORTS = {8000, 11434, 22, 80, 443, 10000}
_running = False
_baseline: dict = {}
_failed_logins: dict = defaultdict(list)

# ── Failed-auth rate limiting / IP blocking ──────────────────────────────────
# Proposed and scoped earlier this session, built now: 5 failed auths in a
# 5-minute window (matches the existing BRUTE_FORCE threshold below) blocks
# that IP for 15 minutes. Trusted IPs (is_trusted_ip — loopback, Render's
# internal network, health checks) are exempt, same as the existing
# BRUTE_FORCE logging, so this can never affect legitimate infra traffic.
# The block is purely in-memory (resets on redeploy) and time-boxed — never
# permanent, never something that needs manual unblocking if it's wrong.
FAILURE_THRESHOLD = 5
FAILURE_WINDOW     = 300   # seconds — 5 minutes
BLOCK_DURATION      = 900  # seconds — 15 minutes
_blocked_ips: dict = {}    # ip -> unblock timestamp

# ── Permanent firewall escalation for repeat offenders ───────────────────────
# The temporary block above is deliberately soft (in-memory, time-boxed,
# never needs manual unblocking) — right for a one-off. An IP that keeps
# coming back and re-triggering it isn't a one-off. This adds one further,
# separate tier: after ESCALATION_THRESHOLD distinct temporary-block
# transitions, actually call services.stark_security.block_ip() — a real,
# permanent `ufw deny` rule. This is the first place in this codebase that
# automatically executes a live firewall command; kept narrow and separate
# from services/playbook.py's "brute_force" playbook (which also rotates
# JARVIS_API_TOKEN) specifically so this can't auto-rotate a live credential
# with no human in the loop — only the firewall rule escalates automatically.
ESCALATION_THRESHOLD = 3
_escalation_counts: dict = defaultdict(int)
_escalated_ips: set = set()

def _hash(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except: return None

def _baseline_path(base_dir: str = ".") -> str:
    return os.path.join(base_dir, "memory", "baseline.json")

def build_baseline(base_dir: str = ".") -> dict:
    """Rebuild the integrity baseline and persist it to disk. Call this after
    intentional code changes (e.g. POST /stark/baseline) so Protocol 11 stops
    flagging your own edits as tampering on the next restart."""
    global _baseline
    _baseline = {
        "ts": datetime.now().isoformat(),
        "files": {f: _hash(os.path.join(base_dir, f)) for f in WATCHED},
        "ports": _listening_ports(),
        "note": "Baseline rebuilt by user",
    }
    try:
        path = _baseline_path(base_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(_baseline, f, indent=2)
    except Exception as e:
        print(f"[Sentinel] Failed to persist baseline: {e}")
    return _baseline

def _load_baseline(base_dir: str = ".") -> dict | None:
    path = _baseline_path(base_dir)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"[Sentinel] Failed to load saved baseline: {e}")
    return None

def _listening_ports() -> list:
    try:
        return sorted({c.laddr.port for c in psutil.net_connections("inet")
                       if c.status == "LISTEN" and c.laddr})
    except: return []

def _log_threat(category: str, detail: str, severity: str = "medium"):
    entry = {"ts": datetime.now().isoformat(), "category": category,
             "detail": detail, "severity": severity}
    THREAT_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if THREAT_LOG.exists():
        with open(THREAT_LOG) as f:
            try: log = json.load(f)
            except: log = []
    log.append(entry)
    with open(THREAT_LOG, "w") as f:
        json.dump(log[-1000:], f, indent=2)

    # FILE_TAMPERED fires on every legitimate dev edit (this sentinel's own
    # integrity baseline vs. Protocol 11's — same symptom, same fix: it was
    # reaching the WebSocket chat via bus.alert() and drowning it in "a file
    # changed" noise every time code gets edited. Still logged to disk and
    # printed to the terminal either way. Real threats (CPU/RAM/disk spikes,
    # brute-force attempts, unexpected ports) still alert normally.
    if category != "FILE_TAMPERED":
        try:
            from core.event_bus import bus
            bus.alert(f"[SECURITY] {detail}", severity, category)
        except Exception:
            pass
    print(f"[SENTINEL][{severity.upper()}] {category}: {detail}")

_cooldowns: dict = {}
def _check_cooldown(key: str, secs: int = 300) -> bool:
    now = time.time()
    if now - _cooldowns.get(key, 0) > secs:
        _cooldowns[key] = now
        return True
    return False

def _scan(base_dir: str = "."):
    # File integrity
    try:
        for fname, known in _baseline.get("files", {}).items():
            cur = _hash(os.path.join(base_dir, fname))
            if cur and cur != known and _check_cooldown(f"file_{fname}"):
                _log_threat("FILE_TAMPERED", f"{fname} modified since baseline", "high")
    except Exception as e:
        print(f"[Sentinel] File integrity check failed: {e}")

    # New ports
    try:
        for port in set(_listening_ports()) - set(_baseline.get("ports", [])) - EXPECTED_PORTS:
            if _check_cooldown(f"port_{port}"):
                _log_threat("NEW_PORT", f"Unexpected port: {port}", "medium")
    except Exception as e:
        print(f"[Sentinel] Port scan failed: {e}")

    # System thresholds — each metric independent so a flaky psutil syscall
    # (macOS host_statistics64 intermittently fails under load) doesn't skip the rest.
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > ALERT_CPU and _check_cooldown("cpu"):
            _log_threat("HIGH_CPU", f"CPU at {cpu}%", "warning")
    except Exception as e:
        print(f"[Sentinel] CPU check failed: {e}")

    try:
        ram = psutil.virtual_memory().percent
        if ram > ALERT_RAM and _check_cooldown("ram"):
            _log_threat("HIGH_RAM", f"RAM at {ram}%", "warning")
    except Exception as e:
        print(f"[Sentinel] RAM check failed: {e}")

    try:
        disk = psutil.disk_usage("/").percent
        if disk > ALERT_DISK and _check_cooldown("disk"):
            _log_threat("HIGH_DISK", f"Disk at {disk}%", "warning")
    except Exception as e:
        print(f"[Sentinel] Disk check failed: {e}")

def _loop():
    while _running:
        try: _scan()
        except Exception as e: print(f"[Sentinel] Error: {e}")
        time.sleep(SENTINEL_SCAN_INTERVAL)

_thread = None
def start(base_dir: str = "."):
    global _running, _thread, _baseline
    if _running: return {"status": "already running"}

    # Prefer a saved baseline from disk (i.e. one you explicitly rebuilt after
    # legitimate changes) over building a fresh one — otherwise every restart
    # re-baselines against whatever's on disk *right now*, which defeats the
    # point of detecting tampering between restarts. A missing saved baseline
    # (first run) still falls back to building fresh.
    saved = _load_baseline(base_dir)
    if saved:
        _baseline = saved
        print("[Sentinel] Loaded saved baseline from disk")
    else:
        build_baseline(base_dir)

    _running = True
    _thread  = threading.Thread(target=_loop, daemon=True, name="jarvis-sentinel")
    _thread.start()
    return {"status": "sentinel started", "interval_s": SENTINEL_SCAN_INTERVAL}

def stop():
    global _running; _running = False
    return {"status": "sentinel stopped"}

def record_failed_auth(ip: str):
    from utils.security import is_trusted_ip
    if is_trusted_ip(ip):
        return
    now = time.time()
    _failed_logins[ip] = [t for t in _failed_logins[ip] if now - t < FAILURE_WINDOW]
    _failed_logins[ip].append(now)
    if len(_failed_logins[ip]) >= FAILURE_THRESHOLD:
        _log_threat("BRUTE_FORCE", f"{FAILURE_THRESHOLD}+ failed auth from {ip}", "high")
        already_blocked = ip in _blocked_ips and _blocked_ips[ip] > now
        _blocked_ips[ip] = now + BLOCK_DURATION
        if not already_blocked:
            # Only alert on the transition into a block, not on every
            # subsequent rejected request while already blocked — that
            # would spam a real Pushover critical() on every retry.
            try:
                from services.notifications import alert
                alert("Brute-force block triggered",
                      f"{ip} hit {FAILURE_THRESHOLD}+ failed auth attempts in "
                      f"{FAILURE_WINDOW // 60} minutes — blocked for "
                      f"{BLOCK_DURATION // 60} minutes.")
            except Exception:
                pass

            _escalation_counts[ip] += 1
            if _escalation_counts[ip] >= ESCALATION_THRESHOLD and ip not in _escalated_ips:
                _escalated_ips.add(ip)
                try:
                    from services.stark_security import stark_security
                    result = stark_security.block_ip(ip)
                    from services.notifications import critical
                    if result.get("blocked"):
                        critical("Permanent firewall block",
                                  f"{ip} re-triggered the temporary brute-force block "
                                  f"{_escalation_counts[ip]} times — added a permanent "
                                  f"ufw rule.")
                    else:
                        # ufw not available on this host (e.g. not Linux, or
                        # not root) — the temporary block above still holds;
                        # this just couldn't add the permanent layer on top.
                        critical("Firewall escalation failed",
                                  f"{ip} hit the escalation threshold but the permanent "
                                  f"ufw block failed: {result.get('error', 'unknown')}. "
                                  f"Temporary block still active.")
                except Exception as e:
                    print(f"[Sentinel] Firewall escalation failed for {ip}: {e}")


def is_blocked(ip: str) -> bool:
    """Cheap check called before token comparison on every auth path (REST,
    WebSocket, and the protocol Pepper/Rhodey/master tiers) — a blocked IP
    gets rejected without ever reaching hmac.compare_digest, so continued
    guessing during the block window can't even attempt a comparison."""
    from utils.security import is_trusted_ip
    if is_trusted_ip(ip):
        return False
    expiry = _blocked_ips.get(ip)
    if expiry is None:
        return False
    if time.time() >= expiry:
        del _blocked_ips[ip]
        return False
    return True

def summary() -> dict:
    log = []
    if THREAT_LOG.exists():
        with open(THREAT_LOG) as f:
            try: log = json.load(f)
            except: log = []
    from collections import Counter
    recent = [t for t in log if (datetime.now().timestamp() -
              datetime.fromisoformat(t["ts"]).timestamp()) < 86400]
    by_sev = Counter(t["severity"] for t in recent)
    return {"last_24h": len(recent), "by_severity": dict(by_sev),
            "baseline_set": bool(_baseline)}

def threats(hours: int = 24) -> list:
    if not THREAT_LOG.exists(): return []
    with open(THREAT_LOG) as f:
        try: log = json.load(f)
        except: return []
    cutoff = datetime.now().timestamp() - hours * 3600
    return [t for t in log if datetime.fromisoformat(t["ts"]).timestamp() > cutoff]

def analyze_threat(threat_data: dict) -> dict:
    """JARVIS-style threat analysis — classifies, scores, and recommends a
    response. Auto-triggers a critical alert if severe."""
    from core.llm.router import think
    analysis = think(
        f"Analyze this security threat and recommend response:\n"
        f"{json.dumps(threat_data, indent=2)}\n\n"
        f'Reply as JSON: {{"threat_level": 1-10, "classification": str, '
        f'"recommended_protocol": str, "immediate_action": str}}',
        force_model="instant",
    )
    try:
        result = json.loads(analysis.strip())
        if result.get("threat_level", 0) >= 8:
            from core.event_bus import bus
            bus.alert(f"Severe threat detected. {result.get('immediate_action', '')}",
                     severity="critical", category="THREAT")
        return result
    except Exception:
        return {"threat_level": 5, "classification": "unknown", "recommended_protocol": "monitor"}
