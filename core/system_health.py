"""Unified JARVIS runtime health model for the STARK HUD.

This module is intentionally observational: it reports live state and
configuration without making provider calls or mutating subsystems.
"""
from __future__ import annotations

import os
import time
from typing import Any


def _state(name: str, default: Any = None) -> Any:
    try:
        from core.state import state
        return state.get(name, default)
    except Exception:
        return default


def _component(name: str, status: str, *, reason: str = "", **extra: Any) -> dict:
    item = {"name": name, "status": status}
    if reason:
        item["reason"] = reason
    item.update(extra)
    return item


def _provider_status() -> list[dict]:
    try:
        from config.settings import (
            ANTHROPIC_API_KEY,
            CEREBRAS_API_KEY,
            GROQ_API_KEY,
        )
    except Exception:
        ANTHROPIC_API_KEY = CEREBRAS_API_KEY = GROQ_API_KEY = ""

    statuses = _state("model_status", {}) or {}
    try:
        from services.circuit_breaker import cb
        circuits = cb.dashboard()
    except Exception:
        circuits = {}


    def tracked(provider: str) -> bool:
        return any(k.startswith(provider + ":") for k in statuses)

    def provider_item(provider: str, configured: bool) -> dict:
        name = provider.upper()
        if not configured:
            return _component(name, "offline", reason="not configured")
        keys = [k for k in statuses if k.startswith(provider + ":")]
        circuit = circuits.get(provider, {})
        error = (circuit.get("last_error") or "").lower()
        if "402" in error or "payment required" in error or "billing" in error:
            return _component(name, "payment_required", reason="provider rejected a request for payment", circuit=circuit)
        if circuit.get("state") == "open":
            return _component(name, "rate_limited" if circuit.get("retry_after") else "degraded",
                              reason="circuit open; routing around provider", circuit=circuit)
        if keys and any(statuses[k] for k in keys):
            return _component(name, "online", reason="recent successful model call", circuit=circuit)
        if keys:
            return _component(name, "degraded", reason="configured but recent model attempts failed", circuit=circuit)
        return _component(name, "standby", reason="configured; no recent model result", circuit=circuit)

    return [
        provider_item("anthropic", bool(ANTHROPIC_API_KEY)),
        provider_item("groq", bool(GROQ_API_KEY)),
        provider_item("cerebras", bool(CEREBRAS_API_KEY)),
        provider_item("ollama", bool(_state("ollama_available", False))),
    ]


def snapshot() -> dict:
    """Return the single health contract consumed by HUD/diagnostics."""
    started = _state("boot_time")
    uptime = 0
    try:
        uptime = max(0, int(time.time() - __import__("server.api", fromlist=["BOOT_TIME"]).BOOT_TIME))
    except Exception:
        pass

    providers = _provider_status()

    warnings = list(_state("warnings", []) or [])
    sentinel = bool(_state("sentinel", False))
    voice = bool(_state("voice_active", False))

    try:
        from config.settings import FRIDAY_URL
        friday_configured = bool(FRIDAY_URL)
    except Exception:
        friday_configured = bool(os.getenv("FRIDAY_URL", "").strip())

    components = [
        _component("CORE", "online", model=_state("active_model", ""), provider=_state("active_provider", "")),
        _component("MEMORY", "online"),
        _component("VOICE", "speaking" if voice else "standby"),
        _component("SECURITY", "online" if sentinel else "degraded",
                    reason="Sentinel active" if sentinel else "Sentinel not active"),
        _component("FRIDAY", "standby" if friday_configured else "offline",
                    reason="configured; live probe reported separately" if friday_configured else "FRIDAY_URL not configured"),
        _component("ENGINEERING", "standby"),
    ]

    degraded = any(p["status"] in ("degraded", "offline", "rate_limited", "payment_required") for p in providers)
    if any(c["status"] == "degraded" for c in components):
        degraded = True

    overall = "degraded" if degraded else "online"

    return {
        "schema": "jarvis.health.v1",
        "overall": overall,
        "uptime_seconds": uptime,
        "boot_time": started,
        "components": components,
        "providers": providers,
        "warnings": warnings[-20:],
        "active": {
            "model": _state("active_model", ""),
            "provider": _state("active_provider", ""),
            "tier": _state("active_tier", ""),
        },
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
