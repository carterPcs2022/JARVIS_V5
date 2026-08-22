"""core/interfaces/tool.py — the Tool protocol: every callable JARVIS can
invoke declares its own risk level and confirmation/permission
requirements, instead of each call site deciding safety ad hoc.

Phase 3 (docs/AUDIT.md §11) found there are three independent tool
dispatchers in this codebase, not one registry with gaps:

  1. core/executor.py (9 tools) — this module's original Phase 1 coverage.
  2. core/mac_dispatcher.py (27 tools: app/system control, Spotify, Gmail)
     — the one actually on the live default chat path
     (core.brain_v2.Executor._mac_control()); Phase 1 missed it entirely.
  3. core/tool_calling.py (7 tools) — used by exactly one side-door route.

These are kept as three SEPARATE registries (registry(), from
core.executor.TOOLS; mac_registry(), from core.mac_dispatcher.TOOLS;
tool_calling_registry(), from core.tool_calling.TOOLS), not flattened into
one dict — #1 and #3 used to both define a tool literally named
"web_search" (core.deep_search vs core.tools.search.SearchCascade,
genuinely different capabilities: deep synthesis with page-fetching vs.
a raw multi-provider search cascade with a mode parameter, not
duplicates of each other). core/tool_calling.py's has since been renamed
to "web_search_raw" to reconcile the collision; kept as separate
registries regardless, since a flat merge would still be the wrong
model for two dispatchers with genuinely different confirmation/context
semantics (see core/executor.py's execute_step() vs
core/mac_dispatcher.py's dispatch(), below).

Enforcement: Tool.execute() now takes `confirmed`. When
requires_confirmation=True and confirmed=False, it does NOT run the
handler — it registers a pending action (core.interfaces.permissions) and
returns it instead. What a caller does with that differs by dispatcher
context (see core/executor.py's execute_step() — fails closed, no
cross-turn confirm channel in an autonomous task — vs
core/mac_dispatcher.py's dispatch() — a real two-turn confirm/discard flow,
since it's called fresh per chat message).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

RISK_LEVELS = ("low", "medium", "high", "destructive")


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str = ""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]          # JSON-schema-shaped, same convention
                                         # as core/tool_calling.py's TOOLS_SCHEMA
    handler: Callable[[dict], Any]
    risk_level: str = "low"             # one of RISK_LEVELS
    requires_confirmation: bool = False
    reversible: bool = True
    permissions: list[str] = field(default_factory=list)   # e.g. ["read"], ["execute"]

    def execute(self, args: dict, confirmed: bool = False) -> ToolResult:
        """Runs the handler directly, unless this tool requires
        confirmation and `confirmed` isn't set — in which case nothing
        runs; a pending action is registered instead and returned as
        output (ok=False, error="confirmation_required") for the caller
        to surface or act on."""
        if self.requires_confirmation and not confirmed:
            from core.interfaces.permissions import propose
            pending = propose(self.name, args)
            return ToolResult(ok=False, output=pending, error="confirmation_required")
        try:
            return ToolResult(ok=True, output=self.handler(args))
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


_TOOLS: dict[str, Tool] | None = None
_MAC_TOOLS: dict[str, Tool] | None = None
_TOOL_CALLING_TOOLS: dict[str, Tool] | None = None


def registry() -> dict[str, Tool]:
    """core/executor.py's 9 tools."""
    global _TOOLS
    if _TOOLS is None:
        from core.executor import TOOLS
        _TOOLS = TOOLS
    return _TOOLS


def mac_registry() -> dict[str, Tool]:
    """core/mac_dispatcher.py's 27 tools — the live default-chat-path
    dispatcher for app/system control, Spotify, and Gmail. Named
    TOOL_REGISTRY there (not TOOLS) since that module already has a
    plain-dict TOOLS used to build its LLM tool-selection prompt."""
    global _MAC_TOOLS
    if _MAC_TOOLS is None:
        from core.mac_dispatcher import TOOL_REGISTRY
        _MAC_TOOLS = TOOL_REGISTRY
    return _MAC_TOOLS


def tool_calling_registry() -> dict[str, Tool]:
    """core/tool_calling.py's 7 tools — side-door only (POST /stark/tools/think)."""
    global _TOOL_CALLING_TOOLS
    if _TOOL_CALLING_TOOLS is None:
        from core.tool_calling import TOOL_OBJECTS
        _TOOL_CALLING_TOOLS = TOOL_OBJECTS
    return _TOOL_CALLING_TOOLS


def get_tool(name: str) -> Tool | None:
    """Looks up `name` in core/executor.py's registry only — the other two
    have their own name collision with this one (see module docstring),
    so callers that mean mac_dispatcher.py or tool_calling.py's tools must
    use mac_registry()/tool_calling_registry() explicitly instead."""
    return registry().get(name)
