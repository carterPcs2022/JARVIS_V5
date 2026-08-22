# JARVIS as an MCP Server — Claude Desktop Setup

This lets Claude Desktop use JARVIS directly as a tool inside any conversation —
his memory, home control, network intelligence, file access, and brain.

## 1. Install the MCP package (already done in this project)

```bash
pip3 install mcp
```

## 2. Find your Claude Desktop config file

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

If it doesn't exist yet, create it.

## 3. Add the JARVIS server entry

Copy the contents of [`mcp_config.json`](../mcp_config.json) in this project
into that file's `mcpServers` object (merge with any other servers already
listed — don't overwrite them), then fill in your own values:

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "python3",
      "args": ["/absolute/path/to/JARVIS_V5/services/mcp_server.py"],
      "env": {
        "JARVIS_API_TOKEN": "<your JARVIS_API_TOKEN, same value as in .env>"
      }
    }
  }
}
```

Set `args` to the actual absolute path of your local JARVIS_V5 checkout, and
`JARVIS_API_TOKEN` to the same value configured in your `.env` — this is the
same token that gates every other JARVIS endpoint, so treat it as a secret:
don't commit a filled-in copy of this config anywhere.

## 4. Restart Claude Desktop

Fully quit and reopen the app. You should see a small tools/plug icon in the
chat input indicating MCP servers are connected.

## 5. Test it

In a Claude Desktop conversation, try:

> "Ask JARVIS what's on my calendar today"

> "Use JARVIS to search the web for the latest news on X"

> "Ask JARVIS what he remembers about our conversation on Tuesday"

Claude will call into the `jarvis_chat`, `jarvis_calendar_today`,
`jarvis_memory_recall`, etc. tools automatically based on what you ask.

## Available tools

| Tool | What it does |
|---|---|
| `jarvis_chat` | Full brain pipeline — general conversation |
| `jarvis_memory_recall` | Search long-term memory |
| `jarvis_home_control` | Mac/home automation control |
| `jarvis_system_status` | Live CPU/RAM/disk/uptime |
| `jarvis_run_task` | Autonomous multi-step task execution |
| `jarvis_goals_list` | Active workshop projects/goals |
| `jarvis_add_note` | Save a note to JARVIS's second brain |
| `jarvis_web_search` | Deep web search via the search cascade |
| `jarvis_calendar_today` | Today's calendar events |
| `jarvis_network_scan` | Scan the local network for devices |
| `jarvis_file_read` | Read a file from the JARVIS project (sandboxed) |
| `jarvis_code_generate` | Generate code from a description |

## Available resources

| URI | Content |
|---|---|
| `jarvis://memory/recent` | Last 20 conversation turns |
| `jarvis://goals/active` | Active goals/projects |
| `jarvis://system/status` | Live system status |
| `jarvis://knowledge_graph` | World model entity relationships |
| `jarvis://workshop/projects` | All workshop projects |

## Important notes

- The MCP server runs as a **separate standalone process** (spawned by Claude
  Desktop via stdio), completely independent from the FastAPI server
  (`server/api.py`). You do **not** need `python3 app.py` running for MCP to
  work — the MCP process imports JARVIS's Python modules directly.
- Both processes read/write the same `memory/` files, so anything Claude does
  through MCP shows up in the regular JARVIS HUD too, and vice versa.
- If a tool call fails, check Claude Desktop's MCP logs (Settings → Developer)
  for the Python traceback.
