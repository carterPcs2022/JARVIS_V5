"""services/metrics.py — Prometheus metrics for JARVIS. prometheus_client is
an optional dependency; if it isn't installed, /metrics reports that
clearly instead of crashing the whole app at import time."""
try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():
        return b"# prometheus_client not installed (pip install prometheus-client)\n"


if _AVAILABLE:
    REQUESTS_TOTAL = Counter(
        "jarvis_requests_total", "Total requests to JARVIS", ["endpoint", "method", "status"]
    )
    RESPONSE_TIME = Histogram(
        "jarvis_response_seconds", "Response time in seconds", ["endpoint", "model"]
    )
    GROQ_CALLS = Counter(
        "jarvis_groq_calls_total", "Total Groq API calls", ["model", "status"]
    )
    MEMORY_SIZE = Gauge("jarvis_memory_conversations", "Number of conversations in memory")
    ACTIVE_WEBSOCKETS = Gauge("jarvis_websockets_active", "Active WebSocket connections")
    PROTOCOL_TRIGGERS = Counter(
        "jarvis_protocol_triggers_total", "Times each protocol was triggered", ["protocol", "severity"]
    )
    THREATS_DETECTED = Counter(
        "jarvis_threats_total", "Security threats detected", ["category", "severity"]
    )
    CPU_USAGE = Gauge("jarvis_cpu_percent", "CPU usage")
    RAM_USAGE = Gauge("jarvis_ram_percent", "RAM usage")
    DISK_USAGE = Gauge("jarvis_disk_percent", "Disk usage")

    # V6 migration (docs/AUDIT.md Phase 8) — observability for the
    # core/interfaces/ protocols. Wired at each interface's one real, live
    # call site (core/brain_v2.py's Executor._reasoning_engine() for
    # reasoning, core/executor.py's execute_step() and
    # core/mac_dispatcher.py's dispatch() for tools,
    # core/interfaces/verification.py's with_retry() for verification) —
    # not at every individual strategy/tool implementation, since most of
    # those are still side-door/inert (same reasoning Phase 1-2 already
    # documented for why the registries themselves don't force full
    # wiring). Agent metrics deliberately not added: the Agent registry has
    # no live call site yet (still fully inert, per Phase 1's own
    # docstring) — instrumenting it now would just be dead counters that
    # never increment on real traffic.
    REASONING_STRATEGY_CALLS = Counter(
        "jarvis_reasoning_strategy_total", "ReasoningStrategy.solve() calls", ["strategy", "outcome"]
    )
    TOOL_EXECUTIONS = Counter(
        "jarvis_tool_executions_total", "Tool executions", ["tool", "risk_level", "outcome"]
    )
    VERIFICATION_OUTCOMES = Counter(
        "jarvis_verification_total", "Verification outcomes", ["outcome"]
    )


def update_system_metrics():
    if not _AVAILABLE:
        return
    try:
        import psutil
        CPU_USAGE.set(psutil.cpu_percent())
        RAM_USAGE.set(psutil.virtual_memory().percent)
        DISK_USAGE.set(psutil.disk_usage("/").percent)
    except Exception:
        pass


def record_reasoning_strategy(strategy: str, success: bool):
    if not _AVAILABLE:
        return
    try:
        REASONING_STRATEGY_CALLS.labels(strategy=strategy, outcome="success" if success else "failure").inc()
    except Exception:
        pass


def record_tool_execution(tool: str, risk_level: str, success: bool):
    if not _AVAILABLE:
        return
    try:
        TOOL_EXECUTIONS.labels(tool=tool, risk_level=risk_level,
                               outcome="success" if success else "failure").inc()
    except Exception:
        pass


def record_verification(outcome: str):
    """outcome: "success" | "retry" | "failure"."""
    if not _AVAILABLE:
        return
    try:
        VERIFICATION_OUTCOMES.labels(outcome=outcome).inc()
    except Exception:
        pass
