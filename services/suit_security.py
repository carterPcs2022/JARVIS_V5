"""services/suit_security.py — biometric/behavioral security foundation for
future suit hardware integration.

Distinct from services/suit_assembly.py (HUD boot-sequence animation) and
services/suit_diagnostics.py (status reporting) — this tracks biometric
baselines and interaction patterns now so that, by the time real sensor
hardware exists, there's already a meaningful behavioral signature to
verify against.
"""
import hashlib
import time
from datetime import datetime

from config.settings import BASE_DIR

BIOMETRIC_FILE = BASE_DIR / "memory" / "biometric_baseline.json"
NEURAL_FILE    = BASE_DIR / "memory" / "neural_handshake.json"


class SuitSecuritySystem:

    # ── Biometric baseline ────────────────────────────────────────────────

    def update_biometric_baseline(self, heart_rate: float = 0, hrv: float = 0,
                                   blood_oxygen: float = 0, voice_pattern: str = "") -> dict:
        """Record a biometric reading and roll it into the baseline. Once
        sensor hardware exists, verify_biometrics() compares live readings
        against this baseline in real time."""
        baseline = self._load_biometric()
        ts = datetime.now().isoformat()

        baseline.setdefault("readings", [])
        reading = {
            "ts": ts, "heart_rate": heart_rate, "hrv": hrv, "blood_oxygen": blood_oxygen,
            "hour": datetime.now().hour, "day_of_week": datetime.now().strftime("%A"),
        }
        baseline["readings"].append(reading)
        baseline["readings"] = baseline["readings"][-10000:]

        readings = baseline["readings"]
        valid_hr = [r["heart_rate"] for r in readings[-100:] if r["heart_rate"] > 0]
        if len(readings) >= 10 and valid_hr:
            baseline["avg_hr"] = sum(valid_hr) / len(valid_hr)

        self._save_biometric(baseline)
        return reading

    def verify_biometrics(self, heart_rate: float, hrv: float) -> dict:
        """Compare a live reading against the baseline. Significant
        deviation is a signal (not proof) of possible impersonation."""
        baseline = self._load_biometric()
        avg_hr = baseline.get("avg_hr", 0)

        if not avg_hr:
            return {"verified": True, "note": "No baseline yet"}

        hr_deviation = abs(heart_rate - avg_hr) / avg_hr
        if hr_deviation > 0.4:
            return {
                "verified": False,
                "reason": f"Heart rate deviation {hr_deviation:.0%} — possible impersonation",
                "expected": avg_hr, "received": heart_rate,
            }
        return {"verified": True, "deviation": hr_deviation, "baseline": avg_hr}

    # ── Neural handshake (interaction fingerprint) ────────────────────────

    def record_interaction_pattern(self, query: str, response_time_ms: float):
        """Record how the user specifically interacts with JARVIS — query
        length/style, response timing, vocabulary. Enough history builds a
        hard-to-forge behavioral signature."""
        data = self._load_neural()
        data.setdefault("patterns", [])

        pattern = {
            "query_length": len(query), "query_words": len(query.split()),
            "response_time": response_time_ms, "hour": datetime.now().hour,
            "ts": datetime.now().isoformat(),
            "vocabulary_hash": hashlib.md5(" ".join(sorted(query.lower().split())).encode()).hexdigest()[:8],
        }
        data["patterns"].append(pattern)
        data["patterns"] = data["patterns"][-50000:]

        if len(data["patterns"]) >= 100:
            self._compute_neural_profile(data)

        self._save_neural(data)

    def _compute_neural_profile(self, data: dict):
        patterns = data["patterns"][-1000:]
        data["profile"] = {
            "avg_query_length": sum(p["query_length"] for p in patterns) / len(patterns),
            "avg_response_time": sum(p["response_time"] for p in patterns) / len(patterns),
            "peak_hours": self._find_peak_hours(patterns),
            "interaction_count": len(data["patterns"]),
        }

    def _find_peak_hours(self, patterns: list) -> list:
        from collections import Counter
        hours = Counter(p["hour"] for p in patterns)
        return [h for h, _ in hours.most_common(3)]

    def get_neural_profile(self) -> dict:
        return self._load_neural().get("profile", {})

    # ── Proximity check ────────────────────────────────────────────────────

    def check_proximity(self, device_id: str, required_distance_m: float = 10) -> dict:
        """Future suit feature: certain commands only work when a paired
        device is within range. Simulated via last-seen heartbeat now —
        real distance measurement needs hardware."""
        from core.state import state
        last_seen = state.get(f"device_{device_id}_last_seen", 0)
        if not last_seen:
            return {"in_range": False, "reason": "Device not registered"}
        seconds_ago = time.time() - last_seen
        return {"in_range": seconds_ago < 30, "seconds_ago": seconds_ago, "device": device_id}

    # ── File helpers ───────────────────────────────────────────────────────

    def _load_biometric(self) -> dict:
        return self._load_json(BIOMETRIC_FILE)

    def _save_biometric(self, data: dict):
        self._save_json(BIOMETRIC_FILE, data)

    def _load_neural(self) -> dict:
        return self._load_json(NEURAL_FILE)

    def _save_neural(self, data: dict):
        self._save_json(NEURAL_FILE, data)

    def _load_json(self, path) -> dict:
        if path.exists():
            import json
            try:
                return json.loads(path.read_text())
            except Exception:
                return {}
        return {}

    def _save_json(self, path, data: dict):
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


suit_security = SuitSecuritySystem()
