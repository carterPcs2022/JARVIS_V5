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
