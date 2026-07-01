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

    handler = dispatch.get(tool, _unknown_tool)
    try:
        return handler(args)
    except Exception as e:
        return json.dumps({"error": str(e), "tool": tool})


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
