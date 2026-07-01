"""services/mcp_server.py — JARVIS as an MCP (Model Context Protocol) server.

Lets Claude Desktop (or any MCP client) use JARVIS's brain, memory, home
control, network intelligence, and file access as tools within a chat.

Run standalone:
    python3 services/mcp_server.py

Configure in Claude Desktop's mcp config (see deploy/MCP_SETUP.md).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure the project root is importable when run as a standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("jarvis")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="jarvis_chat",
            description="Send a message to JARVIS and get a response from his full brain pipeline.",
            inputSchema={
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Message to send to JARVIS"}},
                "required": ["message"],
            },
        ),
        Tool(
            name="jarvis_memory_recall",
            description="Search JARVIS's long-term memory for relevant past conversations.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="jarvis_home_control",
            description="Send a command to JARVIS's home automation (Home Assistant) integration.",
            inputSchema={
                "type": "object",
                "properties": {"command": {"type": "string", "description": "e.g. 'turn on living room lights'"}},
                "required": ["command"],
            },
        ),
        Tool(
            name="jarvis_system_status",
            description="Get JARVIS's live system vitals (CPU, RAM, disk, uptime, active model).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jarvis_run_task",
            description="Give JARVIS an autonomous multi-step task to execute.",
            inputSchema={
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        ),
        Tool(
            name="jarvis_goals_list",
            description="Get JARVIS's active goals/workshop projects.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jarvis_add_note",
            description="Save a note into JARVIS's second brain (knowledge base).",
            inputSchema={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        ),
        Tool(
            name="jarvis_web_search",
            description="Search the web using JARVIS's search cascade (Serper/Tavily/SerpApi/DuckDuckGo).",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="jarvis_calendar_today",
            description="Get today's calendar events from JARVIS.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jarvis_network_scan",
            description="Scan the local network for devices via JARVIS's network intelligence.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jarvis_file_read",
            description="Read a file from the JARVIS project directory (sandboxed to the project root).",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="jarvis_code_generate",
            description="Ask JARVIS to generate code from a description.",
            inputSchema={
                "type": "object",
                "properties": {"description": {"type": "string"}},
                "required": ["description"],
            },
        ),
    ]


def _text(s: str) -> list[TextContent]:
    return [TextContent(type="text", text=s)]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "jarvis_chat":
            from core.brain_v2 import brain
            result = brain.process_dict(arguments["message"])
            return _text(result["response"])

        if name == "jarvis_memory_recall":
            from core.memory import recall
            hits = recall(arguments["query"])
            if not hits:
                return _text("No relevant memories found.")
            lines = [f"[{h['ts'][:10]}] User: {h['user']}\nJARVIS: {h['ai']}" for h in hits]
            return _text("\n\n".join(lines))

        if name == "jarvis_home_control":
            from core.mac_dispatcher import dispatch
            return _text(dispatch(arguments["command"]))

        if name == "jarvis_system_status":
            from core.tools.system import snapshot
            return _text(json.dumps(snapshot(), indent=2))

        if name == "jarvis_run_task":
            from core.agents.planner_agent import run
            result = run(arguments["task"])
            return _text(result.get("final", str(result)))

        if name == "jarvis_goals_list":
            from services.workshop import workshop
            return _text(json.dumps(workshop.list_projects(), indent=2))

        if name == "jarvis_add_note":
            from services.second_brain import second_brain
            note = second_brain.capture(arguments["content"], source="mcp")
            return _text(f"Saved note: {note['title']}")

        if name == "jarvis_web_search":
            from core.deep_search import quick_deep
            return _text(quick_deep(arguments["query"]))

        if name == "jarvis_calendar_today":
            from services.calendar_intel import calendar_intel
            return _text(json.dumps(calendar_intel.get_today(), indent=2))

        if name == "jarvis_network_scan":
            from services.network_intel import network
            return _text(json.dumps(network.scan_network(), indent=2))

        if name == "jarvis_file_read":
            root = Path(__file__).parent.parent.resolve()
            target = (root / arguments["path"]).resolve()
            if not str(target).startswith(str(root)):
                return _text("Access denied: path is outside the JARVIS project directory.")
            if not target.exists():
                return _text(f"File not found: {arguments['path']}")
            return _text(target.read_text(errors="ignore")[:8000])

        if name == "jarvis_code_generate":
            from core.agents.coder import generate
            result = generate(arguments["description"])
            return _text(f"```{result['language']}\n{result['code']}\n```")

        return _text(f"Unknown tool: {name}")

    except Exception as e:
        return _text(f"JARVIS tool error: {e}")


@server.list_resources()
async def list_resources():
    from mcp.types import Resource
    return [
        Resource(uri="jarvis://memory/recent", name="Recent conversations", mimeType="application/json"),
        Resource(uri="jarvis://goals/active", name="Active goals", mimeType="application/json"),
        Resource(uri="jarvis://system/status", name="Live system status", mimeType="application/json"),
        Resource(uri="jarvis://knowledge_graph", name="Entity relationships", mimeType="application/json"),
        Resource(uri="jarvis://workshop/projects", name="Active projects", mimeType="application/json"),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "jarvis://memory/recent":
        from core.memory import get_short_term
        return json.dumps(get_short_term(20), indent=2)
    if uri == "jarvis://goals/active":
        from services.workshop import workshop
        return json.dumps(workshop.list_projects("active"), indent=2)
    if uri == "jarvis://system/status":
        from core.tools.system import snapshot
        return json.dumps(snapshot(), indent=2)
    if uri == "jarvis://knowledge_graph":
        from core.world_model import world
        return json.dumps(world.get_model(), indent=2)
    if uri == "jarvis://workshop/projects":
        from services.workshop import workshop
        return json.dumps(workshop.list_projects(), indent=2)
    return json.dumps({"error": f"Unknown resource: {uri}"})


async def main():
    os.environ.setdefault("JARVIS_API_TOKEN", os.environ.get("JARVIS_API_TOKEN", ""))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
