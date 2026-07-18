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
                "retry_after": None,
            }
        return self._circuits[service]

    def _maybe_recover(self, service: str) -> dict:
        """If open and the recovery window (retry_after, or the fixed
        cooldown) has elapsed, flip to half-open so the next attempt can
        actually test recovery. Centralized here so is_available() and
        call() never drift out of sync — previously is_available() only
        read the stored "open"/"closed" state and never re-checked elapsed
        time, so router.py's `if not cb.is_available(...): continue` gate
        skipped straight past Groq forever without ever reaching call()
        (the only place the elapsed-time check lived), leaving a circuit
        permanently open until process restart even long after Groq itself
        had recovered."""
        circuit = self._get_circuit(service)
        if circuit["state"] == "open":
            effective_timeout = circuit["retry_after"] or self.RECOVERY_TIMEOUT
            elapsed = time.time() - (circuit["opened_at"] or 0)
            if elapsed >= effective_timeout:
                circuit["state"] = "half"
                print(f"[CircuitBreaker] {service}: open -> half-open")
        return circuit

    def call(self, service: str, fn, *args, **kwargs):
        """Execute fn(*args, **kwargs) through the circuit breaker.
        Usage: result = cb.call("groq", groq_function, messages)"""
        circuit = self._maybe_recover(service)

        if circuit["state"] == "open":
            # retry_after (from e.g. GroqRateLimitError, set in
            # _on_failure) overrides the fixed cooldown when the failing
            # call told us exactly how long to wait — a tokens-per-day
            # exhaustion (40+ minutes) shouldn't be probed every
            # RECOVERY_TIMEOUT like a tokens-per-minute one (seconds) would
            # be; without this, every RECOVERY_TIMEOUT window between now
            # and the real reset burns a guaranteed-to-fail probe request.
            effective_timeout = circuit["retry_after"] or self.RECOVERY_TIMEOUT
            elapsed = time.time() - (circuit["opened_at"] or 0)
            raise CircuitOpenError(
                f"{service} circuit is open. Retry in {effective_timeout - elapsed:.0f}s"
            )

        try:
            result = fn(*args, **kwargs)
            self._on_success(service)
            return result
        except Exception as e:
            self._on_failure(service, str(e), retry_after=getattr(e, "retry_after", None))
            raise

    def _on_success(self, service: str):
        circuit = self._get_circuit(service)
        if circuit["state"] == "half":
            circuit["successes"] += 1
            if circuit["successes"] >= self.SUCCESS_THRESHOLD:
                circuit["state"] = "closed"
                circuit["failures"] = 0
                circuit["successes"] = 0
                circuit["retry_after"] = None
                print(f"[CircuitBreaker] {service}: half -> CLOSED")
        else:
            circuit["failures"] = max(0, circuit["failures"] - 1)

    def _on_failure(self, service: str, error: str, retry_after: float | None = None):
        circuit = self._get_circuit(service)
        circuit["failures"] += 1
        circuit["last_failure"] = datetime.now().isoformat()
        # Always overwrite, including with None — a failure that doesn't
        # carry a retry_after (e.g. a plain network error) means the
        # PREVIOUS failure's retry_after (which could be a 40+ minute TPD
        # wait) is no longer the relevant one. Without this, a single
        # unrelated blip during half-open testing would reopen the circuit
        # for another full TPD-length wait instead of falling back to the
        # default RECOVERY_TIMEOUT.
        circuit["retry_after"] = retry_after

        if circuit["failures"] >= self.FAILURE_THRESHOLD and circuit["state"] != "open":
            circuit["state"] = "open"
            circuit["opened_at"] = time.time()
            circuit["total_opens"] += 1
            wait = circuit["retry_after"] or self.RECOVERY_TIMEOUT
            print(f"[CircuitBreaker] {service}: OPEN ({error[:50]}) — retry in {wait:.0f}s")
            try:
                from core.event_bus import bus
                bus.alert(
                    f"Circuit breaker opened for {service}. Routing around it. "
                    f"Will retry in {wait:.0f}s.",
                    severity="medium", category="CIRCUIT_BREAKER",
                )
            except Exception:
                pass

    def get_state(self, service: str) -> str:
        return self._get_circuit(service)["state"]

    def is_available(self, service: str) -> bool:
        return self._maybe_recover(service)["state"] != "open"

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
