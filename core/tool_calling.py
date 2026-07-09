"""
core/tool_calling.py — Structured function calling via Groq.

Instead of guessing which JARVIS capability to invoke from prose (the
existing keyword-based Reasoner), this lets the model pick a tool with
typed, validated parameters. One extra round-trip when a tool is actually
needed (two calls total: decide -> call tool -> synthesize), zero extra
cost when it isn't (finishes in one call).
"""
import json
import httpx
from config.settings import GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type":  {"type": "string", "enum": ["web", "news", "video", "scholar"]},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Get current system vitals (CPU, RAM, disk, uptime)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_recall",
            "description": "Search JARVIS's long-term memory for relevant past context",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_task",
            "description": "Execute a multi-step autonomous task",
            "parameters": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mac_control",
            "description": "Control the Mac — open/quit apps, media control, volume, screenshots, Gmail, Spotify",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_check",
            "description": "Check the calendar for events",
            "parameters": {
                "type": "object",
                "properties": {"period": {"type": "string", "enum": ["today", "tomorrow", "week"]}},
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_code",
            "description": "Write code for a specific task",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "language":    {"type": "string"},
                },
                "required": ["description"],
            },
        },
    },
]


def _handle_web_search(args: dict):
    from core.tools.search import SearchCascade
    mode = args.get("type", "web")
    return SearchCascade.search(args["query"], mode=mode if mode != "web" else "auto")


def _handle_system_status(args: dict):
    from core.tools.system import snapshot
    return snapshot()


def _handle_memory_recall(args: dict):
    from core.memory import recall_as_context
    return recall_as_context(args["query"])


def _handle_run_task(args: dict):
    from core.agents.planner_agent import run
    return run(args["task"])


def _handle_mac_control(args: dict):
    from core.mac_dispatcher import dispatch
    return dispatch(args["command"])


def _handle_calendar_check(args: dict):
    from services.calendar_intel import calendar_intel
    if not calendar_intel.is_connected():
        # An empty list here is ambiguous ("no events" vs. "never checked a
        # real calendar") — say so explicitly instead of letting the model
        # guess or invent events.
        return {
            "connected": False,
            "message": "Calendar isn't connected yet, sir. Set CALDAV_URL (and credentials, if needed) to connect one.",
        }
    period = args.get("period", "today")
    if period == "today":
        return calendar_intel.get_today()
    return calendar_intel.get_upcoming(24 if period == "tomorrow" else 168)


def _handle_generate_code(args: dict):
    from core.agents.coder import generate
    return generate(args["description"], args.get("language", "python"))


TOOL_HANDLERS = {
    "web_search":        _handle_web_search,
    "get_system_status": _handle_system_status,
    "memory_recall":     _handle_memory_recall,
    "run_task":          _handle_run_task,
    "mac_control":       _handle_mac_control,
    "calendar_check":    _handle_calendar_check,
    "generate_code":     _handle_generate_code,
}


def think_with_tools(user_input: str, context: str = "", system: str | None = None) -> dict:
    """
    Full tool-use pipeline: JARVIS decides which tool(s) to call (if any),
    calls them, and synthesizes a final response incorporating the results.

    Returns {"content": str, "tools_used": list[str]}
    """
    if not GROQ_API_KEY:
        from core.llm.router import think
        return {"content": think(user_input, context, system), "tools_used": []}

    from core.context import build_system
    sys_prompt = system or build_system()
    messages = [{"role": "system", "content": sys_prompt}]
    if context:
        messages.append({"role": "system", "content": f"Context:\n{context}"})
    messages.append({"role": "user", "content": user_input})

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{GROQ_BASE_URL}/chat/completions", headers=headers, json={
                "model": GROQ_MODEL, "messages": messages,
                "tools": TOOLS_SCHEMA, "tool_choice": "auto", "max_tokens": 1024,
            })
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            message = choice["message"]
    except Exception as e:
        from core.llm.router import think
        print(f"[ToolCalling] Groq function-call request failed, falling back: {e}")
        return {"content": think(user_input, context, system), "tools_used": []}

    if choice.get("finish_reason") != "tool_calls" or not message.get("tool_calls"):
        return {"content": message.get("content", ""), "tools_used": []}

    tools_used = []
    messages.append(message)

    for tool_call in message["tool_calls"]:
        fn_name = tool_call["function"]["name"]
        try:
            fn_args = json.loads(tool_call["function"]["arguments"])
        except Exception:
            fn_args = {}

        print(f"[ToolCalling] Calling {fn_name} with {fn_args}")
        handler = TOOL_HANDLERS.get(fn_name)
        if handler:
            try:
                result = handler(fn_args)
                result_str = json.dumps(result, default=str) if not isinstance(result, str) else result
            except Exception as e:
                result_str = f"Tool error: {e}"
        else:
            result_str = f"Unknown tool: {fn_name}"

        tools_used.append(fn_name)
        messages.append({
            "role": "tool", "tool_call_id": tool_call["id"], "content": result_str[:2000],
        })

    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{GROQ_BASE_URL}/chat/completions", headers=headers, json={
                "model": GROQ_MODEL, "messages": messages, "max_tokens": 1024,
            })
            r.raise_for_status()
            final = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        final = f"I ran {', '.join(tools_used)} but couldn't synthesize a final response: {e}"

    return {"content": final, "tools_used": tools_used}
