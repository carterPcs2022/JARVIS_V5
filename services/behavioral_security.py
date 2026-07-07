"""services/behavioral_security.py — learns normal request patterns per IP
and flags deviations (rapid-fire, endpoint scanning, body-size spikes,
user-agent switching, off-hours sensitive-endpoint access).

NOT wired as auto-blocking middleware. This is a single-user personal
assistant behind a single Render URL — the owner's own normal usage
(bursty polling from the HUD, occasional heavy sessions) can easily look
like the "anomalies" this module detects, especially before 10+ requests
establish a baseline. Auto-blocking on a behavioral score risk-locks the
owner out of his own assistant on a false positive, which is a worse
outcome than letting a real scanner poke around a personal API for a few
extra requests. Exposed as read-only risk-score/summary endpoints instead
— genuinely useful signal, without the self-lockout risk of enforcement."""
import hashlib
import time
from collections import defaultdict, deque
from datetime import datetime


class BehavioralSecurity:

    def __init__(self):
        self._ip_profiles: dict = {}
        self._anomaly_log: list = []

    def record_request(self, ip: str, endpoint: str, method: str,
                       user_agent: str = "", body_size: int = 0):
        from utils.security import is_trusted_ip
        if is_trusted_ip(ip):
            return

        key = self._ip_key(ip)

        if key not in self._ip_profiles:
            self._ip_profiles[key] = {
                "ip": ip, "first_seen": datetime.now().isoformat(), "request_count": 0,
                "endpoints": defaultdict(int), "methods": defaultdict(int),
                "avg_body_size": 0, "user_agents": set(),
                "request_times": deque(maxlen=100), "anomaly_score": 0,
            }

        profile = self._ip_profiles[key]
        profile["request_count"] += 1
        profile["endpoints"][endpoint] += 1
        profile["methods"][method] += 1
        profile["user_agents"].add(user_agent[:100])
        profile["request_times"].append(time.time())

        n = profile["request_count"]
        profile["avg_body_size"] = (profile["avg_body_size"] * (n - 1) + body_size) / n

        if n >= 10:
            anomalies = self.detect_anomalies(ip, endpoint, method, body_size)
            if anomalies:
                profile["anomaly_score"] += len(anomalies)
                self._log_anomaly(ip, anomalies)

    def detect_anomalies(self, ip: str, endpoint: str, method: str, body_size: int) -> list[str]:
        anomalies = []
        key = self._ip_key(ip)
        profile = self._ip_profiles.get(key, {})
        if not profile:
            return anomalies

        times = list(profile.get("request_times", []))

        if len(times) >= 10:
            recent_10 = times[-10:]
            if recent_10[-1] - recent_10[0] < 5:
                anomalies.append("RAPID_FIRE: 10+ requests in 5 seconds")

        endpoints_tried = len(profile.get("endpoints", {}))
        if endpoints_tried > 15 and profile["request_count"] < 50:
            anomalies.append(f"ENDPOINT_SCAN: {endpoints_tried} unique endpoints tried")

        avg_body = profile.get("avg_body_size", 0)
        if avg_body > 0 and body_size > avg_body * 10:
            anomalies.append(f"BODY_SPIKE: request body {body_size}B vs avg {avg_body:.0f}B")

        agents = profile.get("user_agents", set())
        if len(agents) > 5:
            anomalies.append(f"AGENT_SWITCHING: {len(agents)} different user agents")

        hour = datetime.now().hour
        HIGH_RISK_ENDPOINTS = ("/stark/coldfire", "/stark/baseline", "/stark/protocols",
                              "/stark/security", "/stark/memory")
        if hour < 5 and any(h in endpoint for h in HIGH_RISK_ENDPOINTS):
            anomalies.append(f"OFF_HOURS_SENSITIVE: {endpoint} at {hour}:00")

        return anomalies

    def _log_anomaly(self, ip: str, anomalies: list[str]):
        entry = {"ip": ip, "anomalies": anomalies, "ts": datetime.now().isoformat(),
                 "severity": "HIGH" if len(anomalies) > 2 else "MEDIUM"}
        self._anomaly_log.append(entry)
        self._anomaly_log = self._anomaly_log[-500:]

        from core.event_bus import bus
        severity = "high" if len(anomalies) > 2 else "warning"
        bus.alert(f"Behavioral anomaly detected from {ip}: {', '.join(anomalies[:2])}",
                 severity=severity, category="BEHAVIORAL_SECURITY")
        try:
            from services.siem import siem
            siem.log_event("ANOMALY", ip=ip, details={"anomalies": anomalies}, severity=entry["severity"])
        except Exception:
            pass

    def get_risk_score(self, ip: str) -> dict:
        key = self._ip_key(ip)
        profile = self._ip_profiles.get(key, {})
        if not profile:
            return {"ip": ip, "score": 0, "risk": "unknown", "trusted": False}

        score = profile.get("anomaly_score", 0)
        anomalies = [a for a in self._anomaly_log if a["ip"] == ip]

        risk = "low"
        if score >= 10:
            risk = "critical"
        elif score >= 5:
            risk = "high"
        elif score >= 2:
            risk = "medium"

        return {
            "ip": ip, "score": score, "risk": risk,
            "requests": profile.get("request_count", 0), "anomalies": len(anomalies),
            "trusted": score == 0 and profile.get("request_count", 0) > 20,
        }

    def _ip_key(self, ip: str) -> str:
        return hashlib.md5(ip.encode()).hexdigest()[:8]

    def get_anomaly_log(self, limit: int = 50) -> list[dict]:
        """Recent anomaly entries — {ip, anomalies, ts, severity} each.
        In-memory only (not persisted to disk), same as the rest of this
        module's state."""
        return self._anomaly_log[-limit:]

    def threat_summary(self) -> dict:
        high_risk_ips = [ip for ip, profile in self._ip_profiles.items()
                        if profile.get("anomaly_score", 0) >= 5]
        return {
            "monitored_ips": len(self._ip_profiles), "high_risk_ips": len(high_risk_ips),
            "total_anomalies": len(self._anomaly_log), "recent_anomalies": self._anomaly_log[-5:],
        }


behavioral = BehavioralSecurity()
