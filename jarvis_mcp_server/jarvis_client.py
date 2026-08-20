"""jarvis_mcp_server/jarvis_client.py — thin async wrappers around JARVIS
V5's existing (sync) core/services functions.

No business logic lives here beyond dispatch and error formatting — every
wrapped call is an existing JARVIS capability. Imports are deferred into
each function (matching this repo's own convention, see
services/mcp_server.py) so this module stays cheap to import even if a
given subsystem's own dependencies aren't installed, and so one missing
subsystem can't break the others.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class JarvisUnavailableError(Exception):
    """Raised when a JARVIS subsystem can't be reached or fails outright —
    carries an actionable message instead of a bare traceback."""


async def _call(fn, *args, **kwargs) -> Any:
    """Run a sync JARVIS function off the event loop thread."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# ── jarvis_query ─────────────────────────────────────────────────────────

async def query(message: str, max_tokens: int, model_tier: str | None) -> dict[str, Any]:
    try:
        from core.llm.router import chat
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's LLM router is unavailable: {e}") from e

    messages = [{"role": "user", "content": message}]
    try:
        result = await _call(chat, messages, max_tokens=max_tokens, force_model=model_tier, query=message)
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's LLM router failed to respond: {e}") from e

    content = result.get("content", "")
    if isinstance(content, str) and content.startswith("[JARVIS OFFLINE]"):
        raise JarvisUnavailableError(content)

    return {
        "response": content,
        "model": result.get("model"),
        "provider": result.get("provider"),
    }


# ── jarvis_memory_search ─────────────────────────────────────────────────

async def memory_search(query_text: str, limit: int, scope: str) -> list[dict]:
    try:
        from core import memory as mem
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's memory system is unavailable: {e}") from e

    dispatch = {
        "conversations": lambda: mem.recall(query_text, k=limit),
        "facts":         lambda: mem.recall_facts(query_text, k=limit),
        "episodes":      lambda: mem.recall_episodes(query_text, k=limit),
        "notes":         lambda: mem.search_notes(query_text, k=limit),
    }

    try:
        if scope == "all":
            results: list[dict] = []
            for kind, fn in dispatch.items():
                hits = await _call(fn)
                results.extend({"type": kind, **h} for h in hits)
            return results

        fn = dispatch.get(scope)
        if fn is None:
            raise JarvisUnavailableError(f"Unknown memory scope: {scope!r}")
        hits = await _call(fn)
        return [{"type": scope, **h} for h in hits]
    except JarvisUnavailableError:
        raise
    except Exception as e:
        raise JarvisUnavailableError(f"Memory search failed: {e}") from e


# ── jarvis_memory_write ──────────────────────────────────────────────────

async def memory_write(
    content: str,
    category: str,
    title: str | None,
    confidence: float | None,
    importance: int | None,
    tags: list[str] | None,
) -> dict:
    try:
        from core import memory as mem
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's memory system is unavailable: {e}") from e

    try:
        if category == "note":
            return await _call(mem.store_note, content, title or "")
        if category == "fact":
            return await _call(mem.store_fact, content, confidence if confidence is not None else 0.9)
        if category == "episode":
            return await _call(
                mem.store_episode, content, importance if importance is not None else 5, None, None, tags
            )
        raise JarvisUnavailableError(f"Unknown memory category: {category!r}")
    except JarvisUnavailableError:
        raise
    except Exception as e:
        raise JarvisUnavailableError(f"Memory write failed: {e}") from e


# ── jarvis_home_assistant ────────────────────────────────────────────────

async def home_assistant(action: str, params: dict[str, Any]) -> dict:
    try:
        from services import home_automation as ha
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's Home Assistant integration is unavailable: {e}") from e

    try:
        if action == "list_devices":
            return await _call(ha.list_devices)

        if action == "set_lights":
            kwargs = {k: v for k, v in params.items() if k in ("brightness", "color") and v is not None}
            if not kwargs:
                raise JarvisUnavailableError("action='set_lights' requires at least 'brightness' or 'color'")
            return await _call(lambda: ha.set_lights(**kwargs))

        if action == "set_temperature":
            if params.get("temperature") is None:
                raise JarvisUnavailableError("action='set_temperature' requires 'temperature'")
            return await _call(ha.set_temperature, params["temperature"])

        if action == "control_blinds":
            if not params.get("blinds_position"):
                raise JarvisUnavailableError("action='control_blinds' requires 'blinds_position'")
            return await _call(ha.control_blinds, params["blinds_position"])

        if action == "arm_security":
            if not params.get("security_mode"):
                raise JarvisUnavailableError("action='arm_security' requires 'security_mode'")
            return await _call(ha.arm_security, params["security_mode"])

        if action == "activate_scene":
            if not params.get("scene_name"):
                raise JarvisUnavailableError("action='activate_scene' requires 'scene_name'")
            return await _call(ha.activate_scene, params["scene_name"])

        raise JarvisUnavailableError(f"Unknown Home Assistant action: {action!r}")
    except JarvisUnavailableError:
        raise
    except Exception as e:
        raise JarvisUnavailableError(f"Home Assistant call failed: {e}") from e


# ── jarvis_habit_tracker ─────────────────────────────────────────────────

async def habit_tracker(action: str, habit_name: str | None) -> dict:
    try:
        from services.productivity import productivity
    except Exception as e:
        raise JarvisUnavailableError(f"JARVIS's productivity/habit tracker is unavailable: {e}") from e

    try:
        if action == "list":
            return await _call(productivity.habit_tracker)
        if action == "log":
            if not habit_name:
                raise JarvisUnavailableError("action='log' requires 'habit_name'")
            return await _call(productivity.log_habit, habit_name)
        raise JarvisUnavailableError(f"Unknown habit tracker action: {action!r}")
    except JarvisUnavailableError:
        raise
    except Exception as e:
        raise JarvisUnavailableError(f"Habit tracker call failed: {e}") from e


# ── jarvis_system_status ─────────────────────────────────────────────────

async def system_status() -> dict:
    status: dict[str, Any] = {}
    errors: list[str] = []

    try:
        from core.tools.system import snapshot
        status["system"] = await _call(snapshot)
    except Exception as e:
        errors.append(f"system snapshot unavailable: {e}")

    try:
        from core.llm.router import check_anthropic, check_groq, check_ollama
        status["llm_providers"] = {
            "groq":      await _call(check_groq),
            "ollama":    await _call(check_ollama),
            "anthropic": await _call(check_anthropic),
        }
    except Exception as e:
        errors.append(f"LLM provider status unavailable: {e}")

    try:
        from services.circuit_breaker import cb
        status["circuit_breakers"] = await _call(cb.dashboard)
    except Exception as e:
        errors.append(f"circuit breaker status unavailable: {e}")

    try:
        from core.memory import memory_stats
        status["memory"] = await _call(memory_stats)
    except Exception as e:
        errors.append(f"memory stats unavailable: {e}")

    if errors:
        status["partial_errors"] = errors

    if not status or set(status) <= {"partial_errors"}:
        raise JarvisUnavailableError(
            "All JARVIS status subsystems are unavailable: " + "; ".join(errors)
        )

    return status
