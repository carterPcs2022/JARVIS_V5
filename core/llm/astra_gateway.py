"""core/llm/astra_gateway.py — safe high-end Astra gateway.

Keeps GPT-6 Astra behind JARVIS's existing control plane. The gateway can
select Astra for explicitly high-value reasoning, but it never grants Astra
arbitrary local execution. Tool execution remains the responsibility of
JARVIS's authorization -> executor -> verification pipeline.

The gateway is opt-in with ASTRA_ENABLED=true. If Astra is unavailable or
fails, callers transparently fall back to the normal JARVIS router.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any


_HIGH_VALUE_TRIGGERS = (
    "maximum intelligence",
    "use astra",
    "use gpt-6 astra",
    "need your best",
    "pull out all the stops",
    "best you got",
    "hardest problem",
    "deepest analysis",
    "critical decision",
    "comprehensive analysis",
)


def astra_enabled() -> bool:
    """Return whether Astra may be selected automatically."""
    raw = os.getenv("ASTRA_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def should_use_astra(query: str) -> bool:
    """Cheap deterministic routing predicate; never makes an API call."""
    if not astra_enabled():
        return False
    low = (query or "").strip().lower()
    return any(trigger in low for trigger in _HIGH_VALUE_TRIGGERS)


def _sync_generate(messages: list[dict], max_tokens: int, system: str = "",
                   effort: str = "high") -> dict[str, Any]:
    """Run the async Astra provider from synchronous JARVIS code.

    This function is intentionally kept separate from the main async request
    handlers. Callers that are already async should use ``generate_async`` to
    avoid creating a nested event loop.
    """
    from core.interfaces.llm_provider import GenerateRequest
    from core.llm.astra import AstraProvider

    request = GenerateRequest(
        messages=messages,
        max_tokens=max_tokens,
        system=system,
        effort=effort,
    )
    response = asyncio.run(AstraProvider().generate(request))
    return {
        "content": response.content,
        "model": response.model,
        "provider": response.provider,
        "usage": response.usage,
    }


async def generate_async(messages: list[dict], max_tokens: int = 4096,
                         system: str = "", effort: str = "high") -> dict[str, Any]:
    """Generate through Astra without nested event-loop calls."""
    from core.interfaces.llm_provider import GenerateRequest
    from core.llm.astra import AstraProvider

    response = await AstraProvider().generate(GenerateRequest(
        messages=messages,
        max_tokens=max_tokens,
        system=system,
        effort=effort,
    ))
    return {
        "content": response.content,
        "model": response.model,
        "provider": response.provider,
        "usage": response.usage,
    }


def think(query: str, context: str = "", system: str = "",
          max_tokens: int = 4096, effort: str = "high") -> dict[str, Any]:
    """Try Astra first, then fall back to the normal JARVIS router.

    No fallback claim is hidden from the caller: the returned provider tells
    the truth about which engine actually answered.
    """
    if not should_use_astra(query):
        from core.llm.router import think as normal_think
        content = normal_think(query, context=context, system=system or None,
                               max_tokens=max_tokens)
        return {"content": content, "provider": "router", "model": ""}

    messages = [{"role": "user", "content": query}]
    if context:
        messages.insert(0, {"role": "system", "content": f"Context:\n{context}"})

    try:
        return _sync_generate(messages, max_tokens=max_tokens,
                              system=system, effort=effort)
    except Exception as exc:
        print(f"[Astra Gateway] Astra unavailable — falling back to JARVIS router: {exc}")
        from core.llm.router import think as normal_think
        content = normal_think(query, context=context, system=system or None,
                               max_tokens=max_tokens)
        return {"content": content, "provider": "router_fallback", "model": ""}
