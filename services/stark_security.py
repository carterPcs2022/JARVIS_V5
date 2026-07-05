"""services/stark_security.py — JARVIS's own perimeter security: zero-trust
device registration, attack-pattern scanning, encryption at rest, and a
self-audit.

IMPORTANT: scan_request() is intentionally NOT wired as blocking middleware
on every request. JARVIS is a coding assistant — completely normal messages
routinely contain backticks, `$(...)`, "1=1"-style logic, SQL snippets, or
pasted stack traces. A pattern-match block on every request body would
false-positive on JARVIS's own primary use case constantly. scan_request()
is exposed for callers who want it (e.g. flagging genuinely public-facing
endpoints like the Twilio webhooks), and everything it finds is still logged
to logs/security.json and visible via /stark/security/attack_log."""
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR, API_TOKEN, SECRET_KEY

DEVICE_CERTS_FILE = BASE_DIR / "security" / "trusted_devices.json"
SECURITY_LOG_FILE = BASE_DIR / "logs" / "security.json"


class StarkSecurity:

    def __init__(self):
        self.trusted_devices: dict = self._load_devices()

    # ── Zero-trust device authentication ─────────────────────────────────────

    def register_device(self, device_name: str, device_fingerprint: str) -> dict:
        """Register a trusted device fingerprint. Only registered devices
        pass verify_device(), even with a correct token."""
        cert = {
            "device": device_name,
            "fingerprint": device_fingerprint,
            "registered": datetime.now().isoformat(),
            "last_seen": None,
            "trust_level": "trusted",
        }
        self.trusted_devices[device_fingerprint] = cert
        self._save_devices()
        return cert

    def verify_device(self, fingerprint: str, token: str) -> dict:
        """Zero-trust check: correct token AND a registered device fingerprint."""
        token_ok = token == API_TOKEN
        device_ok = fingerprint in self.trusted_devices

        if token_ok and device_ok:
            device = self.trusted_devices[fingerprint]
            device["last_seen"] = datetime.now().isoformat()
            self._save_devices()
            return {"verified": True, "device": device["device"], "trust_level": device["trust_level"]}

        return {
            "verified": False,
            "token_valid": token_ok,
            "device_trusted": device_ok,
            "reason": "Unknown device" if token_ok else "Invalid token",
        }

    def list_devices(self) -> list[dict]:
        return list(self.trusted_devices.values())

    # ── Intrusion pattern scanning (advisory, not blocking by default) ──────

    ATTACK_PATTERNS = {
        "sql_injection": ["' or 1=1", "union select", "drop table", "'; --"],
        "xss": ["<script>", "javascript:", "onerror=", "onload="],
        "path_traversal": ["../../", "..\\..\\", "%2e%2e%2f", "/etc/passwd"],
        "prompt_injection": ["ignore previous instructions", "ignore all previous",
                             "you are now dan", "reveal your system prompt"],
    }

    def scan_request(self, request_data: str, source_ip: str) -> dict:
        """Scan text for attack patterns. Logs and alerts on a match but
        does NOT block — see module docstring."""
        threats = []
        data_lower = request_data.lower()

        for attack_type, patterns in self.ATTACK_PATTERNS.items():
            for pattern in patterns:
                if pattern in data_lower:
                    threats.append({
                        "type": attack_type, "pattern": pattern,
                        "source": source_ip, "ts": datetime.now().isoformat(),
                    })
                    break

        if threats:
            self._log_attack(threats[0])
            from core.event_bus import bus
            bus.alert(f"Suspicious pattern flagged from {source_ip}: {threats[0]['type']}",
                      severity="warning", category="SECURITY")

        return {"flagged": bool(threats), "threats": threats}

    def block_ip(self, ip: str) -> dict:
        """Block an IP via UFW. Only works on a Linux host with ufw and root
        privileges (e.g. the Stark Server deploy) — silently no-ops elsewhere."""
        try:
            result = subprocess.run(["ufw", "deny", "from", ip], capture_output=True, text=True, timeout=5)
            return {"blocked": result.returncode == 0, "ip": ip}
        except Exception as e:
            return {"blocked": False, "ip": ip, "error": str(e)}

    # ── Encryption at rest ────────────────────────────────────────────────────

    def encrypt_memory_files(self) -> dict:
        """Write an encrypted (.json.enc) copy of every memory/*.json file,
        using SECRET_KEY. Does not delete or modify the originals."""
        from cryptography.fernet import Fernet
        import base64

        key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
        fernet = Fernet(key)

        memory_dir = BASE_DIR / "memory"
        encrypted = []
        for json_file in memory_dir.glob("*.json"):
            data = json_file.read_bytes()
            enc_path = json_file.with_suffix(".json.enc")
            enc_path.write_bytes(fernet.encrypt(data))
            encrypted.append(json_file.name)
        return {"encrypted_files": encrypted, "count": len(encrypted)}

    # ── Security audit ────────────────────────────────────────────────────────

    def security_audit(self) -> dict:
        """Self-audit: weak token/secret, .env presence, etc."""
        findings = []

        env_path = BASE_DIR / ".env"
        if env_path.exists():
            findings.append({"severity": "info", "issue": ".env present — confirm it isn't served statically"})

        if not API_TOKEN or len(API_TOKEN) < 20:
            findings.append({"severity": "critical", "issue": "Weak or missing API token (JARVIS_API_TOKEN)"})

        if not SECRET_KEY or SECRET_KEY == "change-me-in-production" or len(SECRET_KEY) < 32:
            findings.append({"severity": "high", "issue": "Weak or default secret key (JARVIS_SECRET_KEY)"})

        weights = {"critical": 30, "high": 20, "warning": 10, "info": 2}
        score = max(0, 100 - sum(weights.get(f["severity"], 5) for f in findings))
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 50 else "F"

        return {"audit_time": datetime.now().isoformat(), "findings": findings, "score": score, "grade": grade}

    def attack_log(self, limit: int = 50) -> list[dict]:
        if not SECURITY_LOG_FILE.exists():
            return []
        try:
            log = json.loads(SECURITY_LOG_FILE.read_text())
        except Exception:
            return []
        return log[-limit:]

    def _log_attack(self, threat: dict):
        SECURITY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log = []
        if SECURITY_LOG_FILE.exists():
            try:
                log = json.loads(SECURITY_LOG_FILE.read_text())
            except Exception:
                log = []
        log.append(threat)
        SECURITY_LOG_FILE.write_text(json.dumps(log[-1000:], indent=2))

    def _load_devices(self) -> dict:
        if DEVICE_CERTS_FILE.exists():
            try:
                return json.loads(DEVICE_CERTS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_devices(self):
        DEVICE_CERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEVICE_CERTS_FILE.write_text(json.dumps(self.trusted_devices, indent=2))


stark_security = StarkSecurity()
