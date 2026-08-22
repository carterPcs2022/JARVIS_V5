# jarvis_mcp_server

Exposes JARVIS V5's existing capabilities as an [MCP](https://modelcontextprotocol.io)
server, over the **Streamable HTTP** transport, so any MCP client (Claude,
other LLM orchestrators) can call into JARVIS as tools.

This does **not** reimplement any JARVIS logic — every tool is a thin async
wrapper (`jarvis_client.py`) around functions that already exist in
`core/` and `services/`. See `server.py`'s module docstring for the full
scope statement.

## Tools (v1)

| Tool | Wraps | Read-only? |
|---|---|---|
| `jarvis_query` | `core.llm.router.chat()` | yes |
| `jarvis_memory_search` | `core.memory.{recall,recall_facts,recall_episodes,search_notes}` | yes |
| `jarvis_memory_write` | `core.memory.{store_note,store_fact,store_episode}` | no |
| `jarvis_home_assistant` | `services.home_automation.*` (incl. a new `list_devices()`) | no |
| `jarvis_habit_tracker` | `services.productivity.productivity.{habit_tracker,log_habit}` | no |
| `jarvis_system_status` | `core.tools.system.snapshot`, `core.llm.router.check_*`, `services.circuit_breaker.cb`, `core.memory.memory_stats` | yes |

Every tool accepts a `response_format` field (`"markdown"` default, or
`"json"`) and returns clear, actionable error text (e.g. `"Error: [JARVIS
OFFLINE] Ollama failed."`) instead of a bare exception if a JARVIS
subsystem is down or unconfigured — see each tool's docstring for its
exact success/error response shape.

### Phase 2 — explicitly out of scope

Not exposed here, and nothing in this directory imports from these
modules: **Suit Lockdown** (`core/protocols.py`), **Sentinel**
(`services/sentinel.py`), any passphrase-gated protocol
(`AVENGERS_PASSPHRASE`/`COLDFIRE_PASSPHRASE`/`MORGAN_PASSPHRASE` in
`core/protocols.py`), and **combat mode** (`services/combat_mode.py`).
These need their own auth/approval layer before any MCP exposure — treat
this as a deliberate boundary, not an oversight.

## How auth works

The server reuses `JARVIS_API_TOKEN` — the same env var and constant-time
comparison the main JARVIS API already uses in `utils/security.py` — as a
plain `Authorization: Bearer <token>` check in front of the whole MCP
endpoint (`jarvis_mcp_server/auth.py`). There is no second auth system.

Like the rest of this codebase, an **unset** `JARVIS_API_TOKEN` means open
access — convenient for local dev, but set it before this server is
reachable from the internet. The server logs a warning on startup if it's
unset.

## Running locally

This server imports `core/` and `services/` directly, so it needs the
**main repo's** `requirements.txt` installed too, not just its own:

```bash
cd JARVIS_V5
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r jarvis_mcp_server/requirements.txt

export JARVIS_API_TOKEN=some-local-dev-token   # or leave unset for open access locally
python3 -m jarvis_mcp_server.server            # starts on 0.0.0.0:8001 by default
```

Env vars this server reads directly: `JARVIS_API_TOKEN` (auth — shared
with the main app), `PORT` / `HOST` (bind address; `PORT` matches Render's
convention), `MCP_PORT` (fallback if `PORT` isn't set). Everything else
(`GROQ_API_KEY`, `HOME_ASSISTANT_URL`, etc.) is whatever the main JARVIS
app already reads — this server doesn't define new config, it just calls
into the same modules.

### Testing with MCP Inspector

```bash
# in one terminal
python3 -m jarvis_mcp_server.server

# in another
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8001/mcp \
  --transport http --header "Authorization: Bearer some-local-dev-token" \
  --method tools/list
```

Or run the Inspector's UI mode (`npx @modelcontextprotocol/inspector`,
no `--cli`) and point it at `http://127.0.0.1:8001/mcp` with the same
header to call tools interactively.

For quick manual testing without any real JARVIS credentials configured,
that's expected and fine: `jarvis_query` will return the honest
`"[JARVIS OFFLINE]"` error JARVIS's own router returns when no LLM
provider is reachable, `jarvis_home_assistant` reports
`"not_configured"`, etc. — every tool is designed to say so clearly
rather than pretend to succeed.

## Deploying as a second Render service

JARVIS V5 has no `render.yaml` today — the main API is deployed as a
single Render web service using the repo's `Dockerfile`
(`CMD ["python", "app.py"]`). Add this as a **second, independent** Render
web service pointed at the same repo/branch:

1. In the Render dashboard: **New → Web Service**, same GitHub repo, same
   branch as the main JARVIS service.
2. **Build**: reuse the existing `Dockerfile` (Render lets one repo back
   multiple services, each with its own start command) — or, simpler,
   leave Render's default Python build and set:
   - **Build Command**: `pip install -r requirements.txt -r jarvis_mcp_server/requirements.txt`
   - **Start Command**: `python -m jarvis_mcp_server.server`
3. **Environment variables**: copy over whatever the main service already
   has configured for the subsystems you want reachable —
   `JARVIS_API_TOKEN` (required for auth to mean anything in production),
   `GROQ_API_KEY`/`ANTHROPIC_API_KEY`/`OLLAMA_BASE_URL` (for
   `jarvis_query`), `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_TOKEN` (for
   `jarvis_home_assistant`), `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`/
   `VOYAGE_API_KEY` (for memory). Render sets `PORT` automatically — the
   server already reads it.
4. Deploy. Render's health check can hit `/mcp` — expect a `401` if
   `JARVIS_API_TOKEN` is set (that's a correct "server is up, auth is
   working" signal, not a failure) or a JSON-RPC method-not-allowed style
   response on a bare GET, since `/mcp` expects POST for JSON-RPC calls.

You'll end up with two independent Render URLs: the existing JARVIS API,
and this MCP server (e.g. `https://jarvis-mcp.onrender.com`). They share
the same repo/env vars where relevant but scale, restart, and deploy
independently — a crash in one doesn't take down the other.

## Connecting Claude.ai's custom connector

1. In Claude.ai (or Claude Desktop's remote-MCP settings), add a **custom
   connector** pointing at `https://<your-render-service>.onrender.com/mcp`.
2. Transport: **Streamable HTTP**.
3. Auth: set the connector's bearer token to the same value as this
   service's `JARVIS_API_TOKEN` env var on Render.
4. Save and enable it in a conversation — the six `jarvis_*` tools above
   should appear as available tools.

If the connector reports a `401`, double check the token matches exactly
what's set on the Render service (not the main JARVIS API's token, if
you rotated them independently — by design they're the same env var name,
so keep them in sync if you want one token to work for both).

## Files

- `server.py` — FastMCP server, tool definitions (Pydantic input models +
  docstrings + annotations), the bearer-auth-wrapped Streamable HTTP app,
  and the CLI entrypoint (`--stdio` for local testing, HTTP otherwise).
- `jarvis_client.py` — async wrappers around the real JARVIS functions;
  all JARVIS-calling logic and error formatting lives here, not in
  `server.py`.
- `auth.py` — the bearer-token ASGI middleware.
- `requirements.txt` — this service's one dependency (`mcp`) beyond the
  main repo's `requirements.txt`.
