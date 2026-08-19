"""
core/executor.py — JARVIS step executor.
Runs individual planned steps, dispatching to the right tool.
"""
import json
from core.llm.router import think


def execute_step(step: dict) -> str:
    """Execute a single planned step. Returns string result."""
    tool = step.get("tool", "think")
    args = step.get("args", {})

    dispatch = {
        "think":          _think,
        "web_search":     _web_search,
        "get_weather":    _get_weather,
        "system_info":    _system_info,
        "run_shell":      _run_shell,
        "read_file":      _read_file,
        "write_file":     _write_file,
        "browser_open":   _browser_open,
        "vision_analyze": _vision_analyze,
    }

    # ── Confirmation gate (core/interfaces/tool.py) ────────────────────────────
    # execute_step() runs inside autonomous, multi-step task execution
    # (core/react.py, core/agentic_loop.py, core/agents/planner_agent.py) —
    # unlike core/mac_dispatcher.py's dispatch() (called fresh per chat
    # message, so there's a next turn to confirm on), there's no point in
    # this call chain to pause and wait for a confirmation that can't
    # arrive. A tool marked requires_confirmation=True (run_shell,
    # write_file) fails closed here instead — refuses cleanly rather than
    # either silently proceeding or hanging. A caller with a real
    # confirmation channel can pass step["confirmed"]=True to bypass this;
    # none of the current callers do.
    spec = TOOLS.get(tool)
    if spec and spec.requires_confirmation and not step.get("confirmed", False):
        return json.dumps({
            "error": f"'{tool}' requires explicit confirmation and can't run "
                     f"unattended in this context.",
            "tool": tool, "confirmation_required": True,
        })

    handler = dispatch.get(tool, _unknown_tool)

    def _run() -> str:
        try:
            return handler(args)
        except Exception as e:
            return json.dumps({"error": str(e), "tool": tool})

    # ── Verification + bounded retry (core/interfaces/verification.py) ─────────
    # A Python-level "no exception" isn't the same as "this actually
    # worked" — every core/tools/*.py handler that fails already reports it
    # via {"error": ...} or a "[Xxx error: ...]" string (see that module's
    # docstring); verify_tool_result() detects that convention. Retried,
    # with a hard cap and backoff, ONLY for errors that look transient
    # (timeout/connection/rate-limit) on tools marked reversible — a
    # permanent failure (e.g. run_shell's allowlist rejection) or a
    # non-reversible tool never auto-retries; it fails once and reports the
    # real reason, same as before this existed.
    from core.interfaces.verification import with_retry, verify_tool_result
    reversible = spec.reversible if spec else True
    result, _verdict = with_retry(
        _run, verify=lambda r: verify_tool_result(r, reversible=reversible), max_attempts=3,
    )
    return result


# ── Tool handlers ─────────────────────────────────────────────────────────────

def _think(args: dict) -> str:
    return think(args.get("prompt", str(args)))


def _web_search(args: dict) -> str:
    from core.deep_search import deep_search
    r = deep_search(args.get("query", ""), fetch_pages=True)
    return r.answer if r.answer else json.dumps({"error": "No results"})


def _get_weather(args: dict) -> str:
    from core.tools.web import get_weather
    return json.dumps(get_weather(args.get("city", "New York")))


def _system_info(args: dict) -> str:
    from core.tools.system import snapshot
    return json.dumps(snapshot())


def _run_shell(args: dict) -> str:
    from core.tools.system import run_shell
    return json.dumps(run_shell(args.get("command", "")))


def _read_file(args: dict) -> str:
    from core.tools.files import read_file
    return read_file(args.get("path", ""))


def _write_file(args: dict) -> str:
    from core.tools.files import write_file
    return json.dumps(write_file(args.get("path", ""), args.get("content", "")))


def _browser_open(args: dict) -> str:
    from core.tools.browser import fetch
    return fetch(args.get("url", ""))


def _vision_analyze(args: dict) -> str:
    from core.tools.vision import analyze
    return analyze(args.get("path", ""), args.get("prompt", "Describe this image"))


def _unknown_tool(args: dict) -> str:
    return json.dumps({"error": f"Unknown tool", "args": args})


# ── Tool registry (core/interfaces/tool.py) ────────────────────────────────────
# Declares risk/confirmation/permission metadata for the nine tools above.
# execute_step() and its dispatch table above are untouched and remain the
# real, live code path (called from core/agents/planner_agent.py,
# core/react.py, core/executor.py's own callers) — nothing here enforces
# requires_confirmation or checks permissions yet; see core/interfaces/tool.py's
# module docstring for why that's Phase 3, not this.
#
# risk_level / requires_confirmation follow docs/AUDIT.md's own findings:
# run_shell is the tool the audit flagged for a real shell-injection bug
# (fixed in core/tools/system.py, but running an arbitrary allowlisted shell
# command is inherently higher-risk than the rest of this list regardless),
# and write_file/read_file are sandboxed to home/tmp with an extension
# allowlist (core/tools/files.py) but still touch the real filesystem.

from core.interfaces.tool import Tool

# (name, handler, description, risk_level, requires_confirmation, reversible,
#  permissions, parameters)
_TOOL_SPECS = [
    ("think", _think, "Ask the LLM to reason about a prompt.",
     "low", False, True, ["read"],
     {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}),
    ("web_search", _web_search, "Search the web and synthesize an answer.",
     "low", False, True, ["read", "network"],
     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ("get_weather", _get_weather, "Get current weather for a city.",
     "low", False, True, ["read", "network"],
     {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}),
    ("system_info", _system_info, "Read live CPU/RAM/disk/uptime.",
     "low", False, True, ["read"],
     {"type": "object", "properties": {}}),
    ("run_shell", _run_shell, "Run an allowlisted shell command.",
     "high", True, False, ["execute"],
     {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}),
    ("read_file", _read_file, "Read a file (sandboxed to home/tmp, extension-allowlisted).",
     "medium", False, True, ["read"],
     {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
    ("write_file", _write_file, "Write a file (sandboxed to home/tmp, extension-allowlisted).",
     "medium", True, False, ["write"],
     {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
      "required": ["path", "content"]}),
    ("browser_open", _browser_open, "Fetch and extract text from a URL.",
     "low", False, True, ["read", "network"],
     {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
    ("vision_analyze", _vision_analyze, "Analyze an image with a vision model.",
     "low", False, True, ["read"],
     {"type": "object", "properties": {"path": {"type": "string"}, "prompt": {"type": "string"}},
      "required": ["path"]}),
]

TOOLS: dict[str, Tool] = {
    name: Tool(
        name=name, description=desc, parameters=params, handler=handler,
        risk_level=risk, requires_confirmation=confirm, reversible=reversible,
        permissions=perms,
    )
    for name, handler, desc, risk, confirm, reversible, perms, params in _TOOL_SPECS
}
