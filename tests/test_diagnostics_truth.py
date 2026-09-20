"""Regression tests for truthful provider/status reporting."""


def test_status_is_a_real_self_check_trigger():
    from core.brain_v2 import SELF_CHECK_TRIGGERS

    assert "status" in SELF_CHECK_TRIGGERS
    assert "system status" in SELF_CHECK_TRIGGERS
    assert "jarvis status" in SELF_CHECK_TRIGGERS


def test_rate_limited_groq_is_reported_as_rate_limited(monkeypatch):
    import utils.diagnostics as diagnostics
    from services.circuit_breaker import cb

    monkeypatch.setattr(diagnostics, "check_groq", lambda: True)
    monkeypatch.setattr(diagnostics, "check_ollama", lambda: False)
    monkeypatch.setattr(diagnostics, "check_anthropic", lambda: True)
    monkeypatch.setattr(
        diagnostics,
        "snapshot",
        lambda: {
            "cpu_percent": 10,
            "ram_used_pct": 20,
            "disk_used_pct": 30,
        },
    )
    monkeypatch.setattr(
        diagnostics,
        "_check_mac_bridge",
        lambda: {"configured": False, "reachable": False},
    )
    monkeypatch.setattr(
        diagnostics,
        "_check_memory_files",
        lambda: {},
    )

    cb._circuits["groq"] = {
        "state": "open",
        "failures": 1,
        "successes": 0,
        "last_failure": None,
        "opened_at": 0,
        "total_opens": 1,
        "retry_after": 60,
    }

    result = diagnostics.full_diagnostic()

    assert result["brain"] == "GROQ RATE LIMITED"
    assert any("Groq rate-limited" in warning for warning in result["warnings"])
    assert result["reasoning_available"] is True

    cb._circuits.pop("groq", None)
