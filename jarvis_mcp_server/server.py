#!/usr/bin/env python3
"""jarvis_mcp_server/server.py — JARVIS V5 exposed as an MCP server.

Wraps EXISTING JARVIS capabilities (core.llm.router, core.memory,
services.home_automation, services.productivity, core.tools.system, ...)
as MCP tools over the Streamable HTTP transport. No JARVIS business logic
is reimplemented here — see jarvis_client.py for the thin async wrappers
that call into the real modules.

Deliberately out of scope (Phase 2 — needs its own auth/approval layer):
Suit Lockdown (core/protocols.py), Sentinel (services/sentinel.py), any
ENDGAME/AVENGERS/COLDFIRE/MORGAN passphrase-gated protocol, and combat
mode (services/combat_mode.py). Nothing in this file imports from those
modules.

Run from the repo root (this is a package — always invoke with -m so its
relative imports resolve):

    Local stdio testing (MCP Inspector, Claude Desktop):
        python3 -m jarvis_mcp_server.server --stdio

    HTTP service (what Render/production uses):
        python3 -m jarvis_mcp_server.server

See README.md for full run/deploy/connect instructions.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcp.server.fastmcp import FastMCP

from . import jarvis_client as jc

log = logging.getLogger("jarvis_mcp_server")

mcp = FastMCP(
    "jarvis_mcp",
    instructions=(
        "Tools for interacting with a running JARVIS V5 assistant: ask it a "
        "question, search or add to its memory, control its connected Home "
        "Assistant devices, read or log its habit tracker, and check its "
        "live system status. Security-critical JARVIS protocols (lockdown, "
        "sentinel, combat mode) are intentionally not exposed here."
    ),
)


# ── shared helpers ───────────────────────────────────────────────────────

class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _error_text(e: Exception) -> str:
    """Consistent, actionable error formatting across all tools. Never
    exposes a bare traceback — jc.JarvisUnavailableError messages are
    already written to be specific and actionable; anything else gets a
    generic-but-clear wrapper."""
    if isinstance(e, jc.JarvisUnavailableError):
        return f"Error: {e}"
    return f"Error: unexpected failure calling JARVIS ({type(e).__name__}): {e}"


MODEL_TIERS = {"instant", "standard", "reasoning", "research", "coder", "sonnet", "opus", "fable"}


# ── jarvis_query ─────────────────────────────────────────────────────────

class QueryInput(BaseModel):
    """Input model for sending a message to JARVIS's LLM router."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    message: str = Field(..., description="The question or message to send to JARVIS.", min_length=1, max_length=8000)
    max_tokens: int = Field(default=1024, description="Maximum tokens in the response.", ge=1, le=4096)
    model_tier: Optional[str] = Field(
        default=None,
        description=(
            "Optional model tier to pin, instead of JARVIS's automatic routing. "
            "Free tiers: 'instant', 'standard', 'reasoning', 'research', 'coder'. "
            "Paid tiers (only if the server has them configured/enabled): "
            "'sonnet', 'opus', 'fable'."
        ),
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")

    @field_validator("model_tier")
    @classmethod
    def validate_model_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in MODEL_TIERS:
            raise ValueError(f"model_tier must be one of {sorted(MODEL_TIERS)} or omitted")
        return v


@mcp.tool(
    name="jarvis_query",
    annotations={
        "title": "Ask JARVIS a Question",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def jarvis_query(params: QueryInput) -> str:
    """Send a message to JARVIS's LLM router and get a text response.

    This calls JARVIS's core LLM routing layer directly (core.llm.router.chat) —
    a stateless one-shot completion. It does NOT go through JARVIS's full
    assistant pipeline, so it does not read or write conversational memory,
    and it will not trigger JARVIS's protocol/personality behaviors.

    Args:
        params (QueryInput): message, optional max_tokens/model_tier, and
            response_format.

    Returns:
        str: On success, the response text (markdown) or a JSON object
            {"response": str, "model": str, "provider": str} (json format).
        On failure: "Error: <specific reason>" — e.g. every configured LLM
            provider is unreachable, or the router module itself failed to import.

    Examples:
        - Use when: "What's a good name for a Go microservice?" -> params.message = that text
        - Don't use when: you want JARVIS's memory-aware, personality-driven
          reply — that pipeline isn't exposed here (by design, see module docstring).
    """
    try:
        result = await jc.query(params.message, params.max_tokens, params.model_tier)
    except Exception as e:
        return _error_text(e)

    if params.response_format == ResponseFormat.JSON:
        return _json(result)

    lines = [result["response"]]
    meta = [f"model: {result.get('model')}", f"provider: {result.get('provider')}"]
    lines.append("\n_(" + ", ".join(m for m in meta if not m.endswith("None")) + ")_")
    return "\n".join(lines)


# ── jarvis_memory_search ─────────────────────────────────────────────────

MemoryScope = Literal["all", "conversations", "facts", "episodes", "notes"]


class MemorySearchInput(BaseModel):
    """Input model for searching JARVIS's memory."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    query: str = Field(..., description="Search text to match against stored memories.", min_length=1, max_length=2000)
    limit: int = Field(default=5, description="Maximum results per memory type.", ge=1, le=50)
    scope: MemoryScope = Field(
        default="all",
        description=(
            "Which memory store to search: 'conversations' (long-term chat "
            "history), 'facts' (extracted semantic facts), 'episodes' "
            "(notable events), 'notes' (freeform notes), or 'all' (every "
            "type, each capped at 'limit')."
        ),
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")


@mcp.tool(
    name="jarvis_memory_search",
    annotations={
        "title": "Search JARVIS Memory",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jarvis_memory_search(params: MemorySearchInput) -> str:
    """Search JARVIS's memory (TF-IDF, blended with embedding similarity
    when JARVIS has Voyage embeddings configured) across conversations,
    facts, episodes, and notes. Backed by JSON files mirrored to Turso when
    JARVIS has that configured — there is no separate vector database to
    query.

    Args:
        params (MemorySearchInput): query, limit, scope, response_format.

    Returns:
        str: On success, a markdown list or a JSON array of
            {"type": str, ...memory-type-specific fields...} objects (e.g.
            conversations have "user"/"ai"/"ts"; facts have "fact"/
            "confidence"; episodes have "event"/"importance"; notes have
            "title"/"text").
        "No memories found matching '<query>'" if scope-appropriate stores
            returned nothing.
        "Error: <reason>" on failure (e.g. the memory module failed to import).

    Examples:
        - Use when: "What did we discuss about the Q3 roadmap?" -> scope="conversations"
        - Use when: "What do you know about my dietary preferences?" -> scope="facts"
        - Don't use when: you want to ADD a memory — use jarvis_memory_write instead.
    """
    try:
        hits = await jc.memory_search(params.query, params.limit, params.scope)
    except Exception as e:
        return _error_text(e)

    if not hits:
        return f"No memories found matching '{params.query}'"

    if params.response_format == ResponseFormat.JSON:
        return _json(hits)

    lines = [f"# Memory search: '{params.query}'", ""]
    for h in hits:
        kind = h.get("type", "?")
        if kind == "conversations":
            lines.append(f"- **[{h.get('ts', '')[:10]}]** You: {h.get('user','')}\n  JARVIS: {h.get('ai','')}")
        elif kind == "facts":
            lines.append(f"- **Fact** ({h.get('confidence',0):.2f}): {h.get('fact','')}")
        elif kind == "episodes":
            lines.append(f"- **Episode** (importance {h.get('importance','?')}): {h.get('event','')}")
        elif kind == "notes":
            title = h.get("title") or "(untitled)"
            lines.append(f"- **Note** — {title}: {h.get('text','')}")
        else:
            lines.append(f"- {h}")
    return "\n".join(lines)


# ── jarvis_memory_write ──────────────────────────────────────────────────

MemoryCategory = Literal["note", "fact", "episode"]


class MemoryWriteInput(BaseModel):
    """Input model for adding a new entry to JARVIS's memory."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    content: str = Field(..., description="The text to remember.", min_length=1, max_length=8000)
    category: MemoryCategory = Field(
        default="note",
        description="'note' (freeform), 'fact' (a durable fact about something/someone), or 'episode' (a notable event).",
    )
    title: Optional[str] = Field(default=None, description="Title, used only when category='note'.", max_length=200)
    confidence: Optional[float] = Field(
        default=None, description="Confidence 0-1, used only when category='fact' (default 0.9).", ge=0.0, le=1.0
    )
    importance: Optional[int] = Field(
        default=None, description="Importance 1-10, used only when category='episode' (default 5).", ge=1, le=10
    )
    tags: Optional[list[str]] = Field(
        default=None, description="Tags, used only when category='episode'.", max_length=20
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")


@mcp.tool(
    name="jarvis_memory_write",
    annotations={
        "title": "Add a JARVIS Memory",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def jarvis_memory_write(params: MemoryWriteInput) -> str:
    """Add a new note, fact, or episode to JARVIS's memory.

    Args:
        params (MemoryWriteInput): content, category, and category-specific
            optional fields (title / confidence / importance+tags).

    Returns:
        str: On success, a markdown confirmation or the raw JSON object
            JARVIS's storage function returned (fields vary by category —
            e.g. notes include "id"/"title"/"durable"; facts include
            "fact"/"confidence"; episodes include "id"/"importance").
        "Error: <reason>" on failure.

    Examples:
        - Use when: "Remember that I prefer TypeScript over JavaScript" -> category="fact"
        - Use when: "Save this idea for later: ..." -> category="note"
        - Don't use when: searching existing memory — use jarvis_memory_search instead.
    """
    try:
        result = await jc.memory_write(
            params.content, params.category, params.title, params.confidence, params.importance, params.tags
        )
    except Exception as e:
        return _error_text(e)

    if params.response_format == ResponseFormat.JSON:
        return _json(result)

    if params.category == "note":
        return f"Saved note: {result.get('title') or '(untitled)'}"
    if params.category == "fact":
        return f"Saved fact: {result.get('fact', params.content)}"
    return f"Saved episode: {result.get('event', params.content)}"


# ── jarvis_home_assistant ────────────────────────────────────────────────

HomeAction = Literal[
    "list_devices", "set_lights", "set_temperature", "control_blinds", "arm_security", "activate_scene"
]


class HomeAssistantInput(BaseModel):
    """Input model for controlling JARVIS's connected Home Assistant devices."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    action: HomeAction = Field(
        ...,
        description=(
            "'list_devices' (see what's currently wired up in Home Assistant), "
            "'set_lights', 'set_temperature', 'control_blinds', 'arm_security', "
            "or 'activate_scene' (a full preset: lights+temp+music+blinds+security)."
        ),
    )
    brightness: Optional[int] = Field(default=None, description="0-100, for action='set_lights'.", ge=0, le=100)
    color: Optional[str] = Field(default=None, description="e.g. 'warm'/'cool'/'red', for action='set_lights'.", max_length=50)
    temperature: Optional[float] = Field(default=None, description="Target degrees, for action='set_temperature'.")
    blinds_position: Optional[Literal["open", "closed", "half"]] = Field(
        default=None, description="For action='control_blinds'."
    )
    security_mode: Optional[Literal["armed", "disarmed"]] = Field(default=None, description="For action='arm_security'.")
    scene_name: Optional[str] = Field(
        default=None,
        description="e.g. 'morning'/'movie'/'focus'/'night'/'away'/'workout'/'reading', for action='activate_scene'.",
        max_length=50,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")


@mcp.tool(
    name="jarvis_home_assistant",
    annotations={
        "title": "Control Home Assistant Devices",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def jarvis_home_assistant(params: HomeAssistantInput) -> str:
    """Control or inspect JARVIS's connected Home Assistant devices.

    Calls services/home_automation.py directly. If HOME_ASSISTANT_URL /
    HOME_ASSISTANT_TOKEN aren't configured on the JARVIS server, every
    action returns a clearly-labeled "not_configured" result rather than
    silently doing nothing.

    Args:
        params (HomeAssistantInput): action, plus the fields relevant to
            that action (see field descriptions).

    Returns:
        str: On success, a markdown summary or the raw JSON result from
            Home Assistant's REST API (fields vary by action — list_devices
            returns {"ok","count","devices":[{"entity_id","state","name"}]};
            others return {"ok","status"} or {"status":"not_configured"}).
        "Error: <reason>" on failure or a missing required field for the
            chosen action (e.g. action='set_temperature' without 'temperature').

    Examples:
        - Use when: "What smart home devices do I have?" -> action="list_devices"
        - Use when: "Turn on movie mode" -> action="activate_scene", scene_name="movie"
        - Don't use when: the device/entity isn't one of lights/climate/
          blinds/security/scenes — this tool only covers what
          services/home_automation.py implements.
    """
    try:
        result = await jc.home_assistant(params.action, params.model_dump(exclude={"action", "response_format"}))
    except Exception as e:
        return _error_text(e)

    if params.response_format == ResponseFormat.JSON:
        return _json(result)

    if result.get("status") == "not_configured":
        return "Home Assistant isn't configured on the JARVIS server (HOME_ASSISTANT_URL/HOME_ASSISTANT_TOKEN unset)."

    if params.action == "list_devices" and result.get("ok"):
        devices = result.get("devices", [])
        if not devices:
            return "No devices found in Home Assistant."
        lines = [f"# Home Assistant devices ({result.get('count', len(devices))})", ""]
        lines += [f"- **{d.get('name')}** (`{d.get('entity_id')}`): {d.get('state')}" for d in devices]
        return "\n".join(lines)

    return _json(result)


# ── jarvis_habit_tracker ─────────────────────────────────────────────────

HabitAction = Literal["list", "log"]


class HabitTrackerInput(BaseModel):
    """Input model for reading or logging JARVIS's habit tracker."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    action: HabitAction = Field(..., description="'list' to read current habits/streaks, 'log' to mark one done today.")
    habit_name: Optional[str] = Field(default=None, description="Required when action='log'.", max_length=200)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")

    @model_validator(mode="after")
    def _require_habit_name_for_log(self) -> "HabitTrackerInput":
        if self.action == "log" and not self.habit_name:
            raise ValueError("habit_name is required when action='log'")
        return self


@mcp.tool(
    name="jarvis_habit_tracker",
    annotations={
        "title": "Read or Log JARVIS Habits",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def jarvis_habit_tracker(params: HabitTrackerInput) -> str:
    """Read JARVIS's habit tracker (habits, today's completions, streaks)
    or log a habit as done for today.

    Logging is idempotent per day: logging the same habit twice on the
    same date does not double-count it (services/productivity.py dedupes
    by date). A never-seen habit_name is auto-registered on first log.

    Args:
        params (HabitTrackerInput): action, and habit_name (required for
            action='log').

    Returns:
        str: On success, a markdown summary or the raw JSON
            {"habits": [...], "today_completed": [...], "streaks": {...}}.
        "Error: <reason>" on failure, e.g. action='log' without habit_name.

    Examples:
        - Use when: "What are my current habit streaks?" -> action="list"
        - Use when: "Mark meditation as done today" -> action="log", habit_name="meditation"
    """
    try:
        result = await jc.habit_tracker(params.action, params.habit_name)
    except Exception as e:
        return _error_text(e)

    if params.response_format == ResponseFormat.JSON:
        return _json(result)

    habits = result.get("habits", [])
    completed = set(result.get("today_completed", []))
    streaks = result.get("streaks", {})
    lines = ["# Habit Tracker", ""]
    if not habits:
        lines.append("No habits tracked yet.")
    for h in habits:
        name = h if isinstance(h, str) else h.get("name", "")
        mark = "✅" if name in completed else "⬜"
        lines.append(f"- {mark} **{name}** — streak: {streaks.get(name, 0)}")
    if params.action == "log":
        lines.append(f"\n_Logged '{params.habit_name}' for today._")
    return "\n".join(lines)


# ── jarvis_system_status ─────────────────────────────────────────────────

class SystemStatusInput(BaseModel):
    """Input model for JARVIS's system status check (no required fields)."""
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format.")


@mcp.tool(
    name="jarvis_system_status",
    annotations={
        "title": "JARVIS System Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jarvis_system_status(params: SystemStatusInput) -> str:
    """Get JARVIS's live system status: CPU/RAM/disk/uptime, which LLM
    providers (Groq/Ollama/Anthropic) are currently reachable, circuit
    breaker states, and memory-store counts.

    Individual subsystems degrade independently — if e.g. the circuit
    breaker module fails to import, that section is omitted and reported
    under "partial_errors" rather than failing the whole call.

    Args:
        params (SystemStatusInput): response_format only.

    Returns:
        str: On success, a markdown summary or the raw JSON
            {"system": {...}, "llm_providers": {"groq": bool, "ollama": bool,
            "anthropic": bool}, "circuit_breakers": {...}, "memory": {...},
            "partial_errors": [str, ...] (only present if something degraded)}.
        "Error: <reason>" only if EVERY subsystem is unavailable.

    Examples:
        - Use when: "Is JARVIS healthy right now?" or "Which LLM provider is it using?"
    """
    try:
        result = await jc.system_status()
    except Exception as e:
        return _error_text(e)

    if params.response_format == ResponseFormat.JSON:
        return _json(result)

    lines = ["# JARVIS System Status", ""]
    sysinfo = result.get("system", {})
    if sysinfo:
        lines.append(
            f"- CPU: {sysinfo.get('cpu_percent')}% | RAM: {sysinfo.get('ram_used_pct')}% | "
            f"Disk: {sysinfo.get('disk_used_pct')}% | Uptime: {sysinfo.get('uptime_hours')}h"
        )
    providers = result.get("llm_providers", {})
    if providers:
        lines.append("- LLM providers: " + ", ".join(f"{k}={'up' if v else 'down'}" for k, v in providers.items()))
    breakers = result.get("circuit_breakers", {})
    if breakers:
        lines.append("- Circuit breakers: " + ", ".join(f"{k}={v.get('state')}" for k, v in breakers.items()))
    mem = result.get("memory", {})
    if mem:
        lines.append(
            f"- Memory: {mem.get('short_term_turns')} short-term turns, "
            f"{mem.get('long_term_memories')} long-term entries"
        )
    if result.get("partial_errors"):
        lines.append("\n**Partial degradation:**")
        lines += [f"- {e}" for e in result["partial_errors"]]
    return "\n".join(lines)


# ── entrypoint ───────────────────────────────────────────────────────────

def _build_http_app():
    """Wrap the FastMCP Streamable HTTP app with bearer-token auth."""
    from .auth import BearerAuthMiddleware

    app = mcp.streamable_http_app()
    return BearerAuthMiddleware(app)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    if "--stdio" in sys.argv:
        # Local testing (MCP Inspector, Claude Desktop) — no HTTP, no auth
        # layer needed since stdio is already a private, local channel.
        mcp.run(transport="stdio")
        return

    if not os.getenv("JARVIS_API_TOKEN"):
        log.warning(
            "JARVIS_API_TOKEN is not set — this MCP server will accept requests "
            "from anyone who can reach it. Set JARVIS_API_TOKEN before exposing "
            "this to the internet."
        )

    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8001")))
    app = _build_http_app()
    log.info("jarvis_mcp_server listening on %s:%s (Streamable HTTP, path /mcp)", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
