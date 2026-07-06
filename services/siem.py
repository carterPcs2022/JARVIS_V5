"""services/siem.py — correlates security events across honeypot/canary/
behavioral/auth systems and derives an overall threat level. Pure
in-memory event correlation + bus.alert() on rule match — no blocking
side effects of its own, safe to wire in everywhere."""
import time
from datetime import datetime


def _rule_brute_force(events):
    return sum(1 for e in events if e.get("type") == "AUTH_FAILURE") >= 5


def _rule_coordinated_scan(events):
    return len({e.get("ip") for e in events if e.get("type") == "HONEYPOT"}) >= 3


def _rule_after_hours(events):
    return (datetime.now().hour < 6 or datetime.now().hour > 22) and sum(
        1 for e in events if e.get("type") in ("HONEYPOT", "AUTH_FAILURE")) >= 2


def _rule_canary_and_honeypot(events):
    return (any(e.get("type") == "CANARY" for e in events)
            and any(e.get("type") == "HONEYPOT" for e in events))


THREAT_RULES = [
    {"name": "BRUTE_FORCE", "description": "Multiple auth failures from same IP",
     "condition": _rule_brute_force, "severity": "HIGH", "window": 300},
    {"name": "COORDINATED_SCAN", "description": "Multiple IPs hitting honeypots",
     "condition": _rule_coordinated_scan, "severity": "CRITICAL", "window": 600},
    {"name": "AFTER_HOURS_ATTACK", "description": "High-risk requests outside business hours",
     "condition": _rule_after_hours, "severity": "HIGH", "window": 300},
    {"name": "CANARY_AND_HONEYPOT", "description": "Both canary and honeypot triggered",
     "condition": _rule_canary_and_honeypot, "severity": "CRITICAL", "window": 3600},
]


class SIEM:

    def __init__(self):
        self._events: list = []

    def log_event(self, event_type: str, ip: str = "", details: dict | None = None, severity: str = "INFO"):
        event = {
            "type": event_type, "ip": ip, "details": details or {}, "severity": severity,
            "ts": time.time(), "timestamp": datetime.now().isoformat(),
        }
        self._events.append(event)
        self._events = self._events[-10000:]
        self._check_rules()

    def _check_rules(self):
        now = time.time()
        for rule in THREAT_RULES:
            window = rule.get("window", 300)
            recent = [e for e in self._events if now - e.get("ts", 0) <= window]
            try:
                if rule["condition"](recent):
                    self._trigger_alert(rule)
            except Exception:
                pass

    def _trigger_alert(self, rule: dict):
        from core.event_bus import bus
        bus.alert(f"SIEM ALERT: {rule['name']} — {rule['description']}",
                 severity=rule["severity"].lower(), category="SIEM")

    def get_threat_level(self) -> str:
        recent = self._events[-100:]
        recent_critical = sum(1 for e in recent if e.get("severity") == "CRITICAL")
        recent_high = sum(1 for e in recent if e.get("severity") == "HIGH")
        if recent_critical >= 3:
            return "RED"
        if recent_critical >= 1:
            return "ORANGE"
        if recent_high >= 5:
            return "YELLOW"
        return "GREEN"

    def security_dashboard(self) -> dict:
        from services.honeypot import honeypot

        now = time.time()
        last_hour = [e for e in self._events if now - e.get("ts", 0) <= 3600]
        return {
            "threat_level": self.get_threat_level(),
            "events_1h": len(last_hour),
            "critical_1h": sum(1 for e in last_hour if e.get("severity") == "CRITICAL"),
            "honeypot_hits": sum(1 for e in self._events if e.get("type") == "HONEYPOT"),
            "blocked_ips": len(honeypot.get_blocklist()),
            "canary_triggers": sum(1 for e in self._events if e.get("type") == "CANARY"),
        }


siem = SIEM()
