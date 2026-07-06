"""services/adaptive_ratelimit.py — rate limits that adjust based on an
IP's behavioral risk score instead of one static number for everyone.

NOT wired as blocking middleware, for the same reason
services/behavioral_security.py isn't: the risk score it reads from
behavioral.get_risk_score() can rise on the owner's own legitimate bursty
usage before a real baseline is established, and this module's "critical"
tier only allows 1 request/minute — that's severe enough to make the
assistant unusable for its own owner on a false positive. Exposed via
GET /stark/security/ratelimit-check for visibility/testing; the existing
flat utils.security.rate_limit() (60 req/min for everyone) remains the
enforced limit."""
import time
from collections import defaultdict, deque

_LIMITS = {
    "low": {"requests": 60, "burst": 10},
    "medium": {"requests": 20, "burst": 3},
    "high": {"requests": 5, "burst": 1},
    "critical": {"requests": 1, "burst": 0},
    "unknown": {"requests": 30, "burst": 5},
}


class AdaptiveRateLimit:

    def __init__(self):
        self._windows: dict = defaultdict(deque)
        self._penalties: dict = {}

    def check(self, ip: str, endpoint: str, cost: float = 1.0) -> dict:
        now = time.time()
        key = f"{ip}:{endpoint}"

        window = self._windows[key]
        while window and now - window[0] > 60:
            window.popleft()

        from services.behavioral_security import behavioral
        risk = behavioral.get_risk_score(ip)
        limit_config = _LIMITS.get(risk.get("risk", "unknown"), _LIMITS["unknown"])

        penalty_until = self._penalties.get(f"{ip}_until", 0)
        if now < penalty_until:
            return {"allowed": False, "retry_after": round(penalty_until - now, 1),
                    "reason": "Penalty period active"}

        request_count = len(window)
        if request_count >= limit_config["requests"]:
            self._penalties[ip] = self._penalties.get(ip, 1) * 2
            self._penalties[f"{ip}_until"] = now + self._penalties[ip]
            return {
                "allowed": False, "retry_after": self._penalties[ip], "reason": "Rate limit exceeded",
                "limit": limit_config["requests"], "current": request_count,
            }

        window.append(now)
        return {"allowed": True, "remaining": limit_config["requests"] - request_count - 1,
                "limit": limit_config["requests"]}

    def reset(self, ip: str):
        keys_to_delete = [k for k in self._windows if k.startswith(f"{ip}:")]
        for k in keys_to_delete:
            del self._windows[k]
        self._penalties.pop(ip, None)
        self._penalties.pop(f"{ip}_until", None)


rate_limiter = AdaptiveRateLimit()
