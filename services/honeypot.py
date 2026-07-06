"""services/honeypot.py — fake endpoints nobody legitimate would ever hit.
Zero-false-positive attacker detection: since these paths do nothing real,
any request to them is definitionally a scanner or attacker."""
import json
from pathlib import Path
from datetime import datetime

from config.settings import BASE_DIR

HONEYPOT_FILE = BASE_DIR / "logs" / "honeypot.json"
BLOCKLIST_FILE = BASE_DIR / "memory" / "blocklist.json"

HONEYPOT_ENDPOINTS = [
    "/admin", "/admin/login", "/wp-admin", "/phpmyadmin", "/api/v1/admin",
    "/stark/config", "/stark/debug", "/config.json", "/backup",
    "/jarvis/root", "/api/keys", "/internal/api", "/server-status",
    "/.env", "/.git/config",
]


class Honeypot:

    def trigger(self, ip: str, endpoint: str, request_data: str = "") -> dict:
        entry = {
            "ip": ip, "endpoint": endpoint, "data": request_data[:200],
            "ts": datetime.now().isoformat(), "severity": "CRITICAL",
        }

        log = []
        if HONEYPOT_FILE.exists():
            try:
                log = json.loads(HONEYPOT_FILE.read_text())
            except Exception:
                log = []
        log.append(entry)
        HONEYPOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HONEYPOT_FILE.write_text(json.dumps(log[-500:], indent=2))

        from core.event_bus import bus
        bus.alert(f"HONEYPOT TRIGGERED: {ip} accessed {endpoint}. Adding to blocklist.",
                 severity="critical", category="HONEYPOT")

        try:
            from services.siem import siem
            siem.log_event("HONEYPOT", ip=ip, details={"endpoint": endpoint}, severity="CRITICAL")
        except Exception:
            pass

        self._block(ip)
        return entry

    def _block(self, ip: str):
        blocklist = self.get_blocklist()
        if ip not in blocklist:
            blocklist.append(ip)
            BLOCKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            BLOCKLIST_FILE.write_text(json.dumps(blocklist, indent=2))

    def unblock(self, ip: str) -> dict:
        blocklist = self.get_blocklist()
        if ip in blocklist:
            blocklist.remove(ip)
            BLOCKLIST_FILE.write_text(json.dumps(blocklist, indent=2))
            return {"unblocked": True, "ip": ip}
        return {"unblocked": False, "reason": "not in blocklist"}

    def get_blocklist(self) -> list[str]:
        if BLOCKLIST_FILE.exists():
            try:
                return json.loads(BLOCKLIST_FILE.read_text())
            except Exception:
                return []
        return []

    def is_blocked(self, ip: str) -> bool:
        return ip in self.get_blocklist()

    def log_summary(self) -> dict:
        if not HONEYPOT_FILE.exists():
            return {"triggers": 0, "unique_ips": 0}
        try:
            log = json.loads(HONEYPOT_FILE.read_text())
        except Exception:
            return {"triggers": 0, "unique_ips": 0}
        return {
            "triggers": len(log), "unique_ips": len({e["ip"] for e in log}),
            "recent": log[-3:],
        }


honeypot = Honeypot()
