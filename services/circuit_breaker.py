"""services/circuit_breaker.py — Circuit Breaker pattern for external calls.

If a service fails too many times in a row, "open" the circuit so further
calls fail fast (no retry storm against a dead service) instead of hanging;
after a cooldown, try a limited number of test calls ("half-open") and
close again once they succeed.

States: CLOSED (normal) -> OPEN (failing, bypass) -> HALF (testing recovery) -> CLOSED
"""
import time
from datetime import datetime


class CircuitBreaker:

    FAILURE_THRESHOLD = 5    # failures before opening
    RECOVERY_TIMEOUT  = 60   # seconds before trying again
    SUCCESS_THRESHOLD = 2    # successes to close from half-open

    def __init__(self):
        self._circuits: dict = {}

    def _get_circuit(self, service: str) -> dict:
        if service not in self._circuits:
            self._circuits[service] = {
                "state": "closed", "failures": 0, "successes": 0,
                "last_failure": None, "opened_at": None, "total_opens": 0,
            }
        return self._circuits[service]

    def call(self, service: str, fn, *args, **kwargs):
        """Execute fn(*args, **kwargs) through the circuit breaker.
        Usage: result = cb.call("groq", groq_function, messages)"""
        circuit = self._get_circuit(service)

        if circuit["state"] == "open":
            elapsed = time.time() - (circuit["opened_at"] or 0)
            if elapsed < self.RECOVERY_TIMEOUT:
                raise CircuitOpenError(
                    f"{service} circuit is open. Retry in {self.RECOVERY_TIMEOUT - elapsed:.0f}s"
                )
            circuit["state"] = "half"
            print(f"[CircuitBreaker] {service}: open -> half-open")

        try:
            result = fn(*args, **kwargs)
            self._on_success(service)
            return result
        except Exception as e:
            self._on_failure(service, str(e))
            raise

    def _on_success(self, service: str):
        circuit = self._get_circuit(service)
        if circuit["state"] == "half":
            circuit["successes"] += 1
            if circuit["successes"] >= self.SUCCESS_THRESHOLD:
                circuit["state"] = "closed"
                circuit["failures"] = 0
                circuit["successes"] = 0
                print(f"[CircuitBreaker] {service}: half -> CLOSED")
        else:
            circuit["failures"] = max(0, circuit["failures"] - 1)

    def _on_failure(self, service: str, error: str):
        circuit = self._get_circuit(service)
        circuit["failures"] += 1
        circuit["last_failure"] = datetime.now().isoformat()

        if circuit["failures"] >= self.FAILURE_THRESHOLD and circuit["state"] != "open":
            circuit["state"] = "open"
            circuit["opened_at"] = time.time()
            circuit["total_opens"] += 1
            print(f"[CircuitBreaker] {service}: OPEN ({error[:50]})")
            try:
                from core.event_bus import bus
                bus.alert(
                    f"Circuit breaker opened for {service}. Routing around it. "
                    f"Will retry in {self.RECOVERY_TIMEOUT}s.",
                    severity="medium", category="CIRCUIT_BREAKER",
                )
            except Exception:
                pass

    def get_state(self, service: str) -> str:
        return self._get_circuit(service)["state"]

    def is_available(self, service: str) -> bool:
        return self.get_state(service) != "open"

    def force_close(self, service: str):
        if service in self._circuits:
            self._circuits[service]["state"] = "closed"
            self._circuits[service]["failures"] = 0

    def dashboard(self) -> dict:
        return {
            service: {"state": c["state"], "failures": c["failures"], "total_opens": c["total_opens"]}
            for service, c in self._circuits.items()
        }


class CircuitOpenError(Exception):
    pass


cb = CircuitBreaker()
