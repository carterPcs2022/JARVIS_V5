"""server/api.py — JARVIS V5 FastAPI application."""
from fastapi import FastAPI, BackgroundTasks, Depends, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
import time

# Process-level uptime — distinct from the OS/container uptime that
# core.tools.system.snapshot()'s "uptime_hours" reports. On Render the
# container can persist across deploys in ways that make OS uptime
# misleading; this is uptime of the actual JARVIS process.
BOOT_TIME = time.time()

app = FastAPI(title="JARVIS", description="Just A Rather Very Intelligent System V5", version="5.0")

# /health must always come up — Render's container health check hits this
# path, and a non-200/unreachable response within its timeout kills the
# whole deploy, not just one feature. Previously every router (including
# health's own) was imported unguarded at module level: a single import
# error anywhere in that chain — a missing dependency, bad top-level code
# in any router file — meant `app` itself never finished constructing, so
# uvicorn couldn't even bind the port and every request 502'd, independent
# of anything the startup event handler does. If the real implementation
# (server/routes/health.py — richer: uptime, full state snapshot) fails to
# import, this minimal fallback keeps /health answering with a 200 instead
# of the entire app failing to come up.
try:
    from server.routes.health import router as health_router
    app.include_router(health_router)
except Exception as e:
    print(f"[JARVIS] health router failed to import, using minimal fallback: {e}")
    @app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
    def _health_fallback():
        return {"healthy": True}

from utils.security import add_cors, verify_token
add_cors(app)


def _safe_import(module_path: str, *attrs: str):
    """Import `attrs` from `module_path`, returning None for each on
    failure instead of letting one broken router take the entire app down
    with it. Failures are logged, not silent."""
    try:
        mod = __import__(module_path, fromlist=attrs)
        return tuple(getattr(mod, a) for a in attrs)
    except Exception as e:
        print(f"[JARVIS] Failed to import {module_path}: {e}")
        return tuple(None for _ in attrs)


def _include(*routers):
    for r in routers:
        if r is not None:
            app.include_router(r)


(ws_router,) = _safe_import("server.websocket", "router")
(chat_router,) = _safe_import("server.routes.chat", "router")
(telemetry_router,) = _safe_import("server.routes.telemetry", "router")
(diag_router,) = _safe_import("server.routes.diagnostics", "router")
(memory_router,) = _safe_import("server.routes.memory", "router")
(voice_router,) = _safe_import("server.routes.voice", "router")
(iris_router,) = _safe_import("server.routes.iris", "router")
(mac_router,) = _safe_import("server.routes.mac", "router")
(protocols_router,) = _safe_import("server.routes.protocols", "router")
(scatter_router,) = _safe_import("server.routes.scatter", "router")
(search_router,) = _safe_import("server.routes.search", "router")
(mark_router,) = _safe_import("server.routes.mark", "router")
(stark_extra_router,) = _safe_import("server.routes.stark_extra", "router")
(final_router, final_protected_router) = _safe_import("server.routes.final_features", "router", "protected")
(glasses_router,) = _safe_import("server.routes.glasses", "router")
(vision_identify_router,) = _safe_import("server.routes.vision_identify", "router")
(protocols_18_35_router,) = _safe_import("server.routes.protocols_18_35", "router")
(brain_enhancement_router,) = _safe_import("server.routes.brain_enhancement", "router")
(final_upgrade_router,) = _safe_import("server.routes.final_upgrade", "router")
(final_completion_router,) = _safe_import("server.routes.final_completion", "router")
(stark_infra_router, stark_phone_router) = _safe_import("server.routes.stark_infrastructure", "router", "phone_router")
(mythos_router,) = _safe_import("server.routes.mythos", "router")
(spotify_router, spotify_auth_router) = _safe_import("server.routes.spotify", "router", "auth_router")
(ultimate_brain_router,) = _safe_import("server.routes.ultimate_brain", "router")
(absolute_final_router,) = _safe_import("server.routes.absolute_final", "router")
(security_max_router,) = _safe_import("server.routes.security_max", "router")
(security_gov_router,) = _safe_import("server.routes.security_gov", "router")
(security_firewalls_router, suit_security_router) = _safe_import("server.routes.security_firewalls", "router", "suit_router")
(new_features_router,) = _safe_import("server.routes.new_features", "router")
(intel_router,) = _safe_import("server.routes.intel", "router")
(military_router,) = _safe_import("server.routes.military", "router")
(combat_mode_router,) = _safe_import("server.routes.combat_mode", "router")
(calendar_auth_router,) = _safe_import("server.routes.calendar_auth", "router")

# The two newest, least battle-tested subsystems also get an explicit
# opt-out on top of the same import guard as everything else above.
model_updater_router = None
if os.getenv("DISABLE_MODEL_UPDATER", "").lower() != "true":
    (model_updater_router,) = _safe_import("server.routes.model_updater", "router")

sandbox_router = None
if os.getenv("DISABLE_SANDBOX", "").lower() != "true":
    (sandbox_router,) = _safe_import("server.routes.sandbox", "router")

_include(
    ws_router, chat_router, telemetry_router, diag_router, memory_router,
    voice_router, iris_router, mac_router, protocols_router, scatter_router, search_router,
    mark_router, stark_extra_router, final_router, final_protected_router,
    glasses_router, vision_identify_router, protocols_18_35_router, brain_enhancement_router,
    final_upgrade_router, final_completion_router, stark_infra_router,
    stark_phone_router, mythos_router, spotify_router, spotify_auth_router,
    ultimate_brain_router, absolute_final_router, security_max_router,
    security_gov_router, security_firewalls_router, suit_security_router,
    new_features_router, intel_router, model_updater_router, sandbox_router,
    military_router, combat_mode_router, calendar_auth_router,
)


# ── Blocklist + canary check ──────────────────────────────────────────────────
# Deliberately minimal middleware — a dict lookup and a substring check,
# both effectively free and both zero-false-positive by construction: the
# blocklist can only ever be populated by literally hitting a fake
# honeypot path (see below), and a canary value is a random UUID that
# would never legitimately appear in a request body. This is NOT the
# behavioral/adaptive-rate-limit auto-blocking the source docs described —
# that's deliberately left unwired (see services/behavioral_security.py
# and services/adaptive_ratelimit.py docstrings) because false positives
# there are a real risk of locking the owner out of his own assistant.
@app.middleware("http")
async def security_gate_middleware(request: Request, call_next):
    from services.honeypot import honeypot

    ip = request.client.host if request.client else "unknown"
    if honeypot.is_blocked(ip):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Access denied"}, status_code=403)

    if request.method in ("POST", "PUT", "PATCH"):
        try:
            from services.canary import canary
            body = (await request.body()).decode(errors="ignore")
            if body and canary.scan_requests(body):
                from fastapi.responses import JSONResponse
                honeypot._block(ip)
                return JSONResponse({"error": "Access denied"}, status_code=403)
        except Exception:
            pass

    return await call_next(request)


# ── Honeypot fake endpoints ────────────────────────────────────────────────────
# Zero legitimate traffic ever reaches these — anyone who does is
# definitionally scanning/attacking. Registered directly on `app` (not
# behind verify_token) since the entire point is that they look real to
# someone who doesn't have a token.
from services.honeypot import honeypot as _honeypot, HONEYPOT_ENDPOINTS as _HONEYPOT_ENDPOINTS


def _make_honeypot_handler():
    async def _handler(request: Request):
        import asyncio
        ip = request.client.host if request.client else "unknown"
        path = str(request.url.path)
        try:
            body = (await request.body()).decode(errors="ignore")[:200]
        except Exception:
            body = ""
        _honeypot.trigger(ip, path, body)
        await asyncio.sleep(2)  # slow down a scanner
        return {"error": "Not found"}
    return _handler


for _endpoint in _HONEYPOT_ENDPOINTS:
    app.add_api_route(_endpoint, _make_honeypot_handler(), methods=["GET", "POST", "PUT", "DELETE"],
                      include_in_schema=False)


@app.get("/metrics")
def metrics():
    """Prometheus scrape target — intentionally unauthenticated, matching
    the standard Prometheus pattern (the metrics endpoint is usually only
    reachable from an internal scraper, not the public internet)."""
    from services.metrics import generate_latest, CONTENT_TYPE_LATEST, update_system_metrics
    update_system_metrics()
    from fastapi.responses import Response as _Response
    return _Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/system/doctor")
def system_doctor_endpoint():
    """Unnamespaced (not under /stark/) and unauthenticated to match
    FRIDAY's equivalent /friday/system/doctor — a quick "is everything
    okay" check meant to be hit casually, same tier as /health and
    /metrics above rather than the token-gated /stark/diagnostics."""
    from services.system_doctor import full_check
    return full_check()


HUD_DIR = Path(__file__).parent.parent / "hud_mobile"

# None of these HUD pages register hud_mobile/sw.js (only the mobile PWA
# entry point does), so its network-first fetch handler never applies to
# them — without an explicit no-cache header, FileResponse's default
# Last-Modified/ETag headers still leave heuristic browser caching free to
# serve a stale copy of the page itself (as opposed to the static assets
# under /hud/static/, which are fine to cache). Every HUD HTML route gets
# this explicitly rather than relying on the service worker to cover it.
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/hud")
async def hud_router(request: Request):
    """Detect device type from User-Agent and serve correct HUD.
    Respects ?view=desktop or ?view=mobile query param."""
    view = request.query_params.get("view", "auto")

    if view == "desktop":
        return FileResponse(HUD_DIR / "desktop.html", headers=_NO_CACHE_HEADERS)
    if view == "mobile":
        return FileResponse(HUD_DIR / "index.html", headers=_NO_CACHE_HEADERS)

    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(kw in ua for kw in ["iphone", "android", "mobile", "tablet", "ipad"])

    return FileResponse(HUD_DIR / ("index.html" if is_mobile else "desktop.html"), headers=_NO_CACHE_HEADERS)


@app.get("/hud/desktop")
async def hud_desktop():
    return FileResponse(HUD_DIR / "desktop.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/mobile")
async def hud_mobile_view():
    return FileResponse(HUD_DIR / "index.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/holographic")
async def holographic_hud():
    return FileResponse(HUD_DIR / "holographic.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/ironman")
async def ironman_hud():
    return FileResponse(HUD_DIR / "ironman_hud.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/ambient.js")
async def hud_ambient_js():
    from services.ambient import AMBIENT_HUD_SCRIPT
    from fastapi.responses import Response as _Response
    return _Response(AMBIENT_HUD_SCRIPT, media_type="application/javascript")


@app.get("/hud/intel")
async def intel_map():
    return FileResponse(HUD_DIR / "intelligence_map.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/helmet")
async def helmet_hud():
    return FileResponse(HUD_DIR / "helmet.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/helmet_mobile")
async def helmet_mobile():
    return FileResponse(HUD_DIR / "helmet_mobile.html", headers=_NO_CACHE_HEADERS)


@app.get("/hud/reactor")
async def arc_reactor():
    return FileResponse(HUD_DIR / "arc_reactor.html", headers=_NO_CACHE_HEADERS)


# ── Voice-reactive visuals ───────────────────────────────────────────────────
# core/state.py already has a "voice_active" field (declared, never toggled) —
# reused here instead of a fresh global dict, since it's already the
# established thread-safe state singleton every other module uses. This
# process runs a single uvicorn worker (see Procfile — no --workers flag),
# so in-memory state is safe here without needing cross-process sync.
#
# Toggled from the browser's real Audio element play/ended/pause events
# (hud_mobile/desktop.html), not from services/voice.py at TTS-generation
# time — generation happens on the server before the client ever starts
# playback, so a server-side hook there would have no idea of actual
# playback timing. The browser is the only thing that knows when audio is
# really playing.

@app.get("/hud/voice_state")
async def voice_state():
    """Is JARVIS currently speaking? Polled by hud_mobile/intelligence_map.html,
    which is a separate page/window and so can't just read desktop.html's
    in-page JS state directly."""
    from core.state import state
    return {"speaking": state.get("voice_active", False)}


@app.post("/hud/voice_start", dependencies=[Depends(verify_token)])
async def voice_start_endpoint():
    from core.state import state
    state.set("voice_active", True)
    return {"ok": True}


@app.post("/hud/voice_end", dependencies=[Depends(verify_token)])
async def voice_end_endpoint():
    from core.state import state
    state.set("voice_active", False)
    return {"ok": True}


@app.get("/hud/sw.js")
async def hud_service_worker():
    """Served at exactly the path app.js registers (navigator.serviceWorker.
    register('/hud/sw.js')) rather than under /hud/static/, so its default
    scope covers /hud/, /hud/desktop, and /hud/mobile. Also means browsers
    can actually re-fetch this file to detect updates — if it only existed
    under /hud/static/sw.js, the registration URL itself would 404 and the
    browser would never notice a new version, leaving old phones stuck on
    a stale cached HUD indefinitely."""
    return FileResponse(HUD_DIR / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/hud/", "Cache-Control": "no-cache"})


@app.get("/hud/status", dependencies=[Depends(verify_token)])
async def hud_status():
    """Single combined endpoint both HUDs poll every few seconds.

    Was public — confirmed live (unauthenticated GET returned a full 200
    with memory stats, conversation counts, security posture, model info)
    before this fix. The HUD already sends its token on every jarvisGet()
    call (see hud_mobile/desktop.html), so gating this needed no frontend
    change."""
    from core.tools.system import snapshot
    from utils.diagnostics import full_diagnostic
    from core.memory import memory_stats
    from services.sentinel import summary as threat_summary
    from core.event_bus import bus

    try:
        sys_snap = snapshot()
    except Exception:
        sys_snap = {}
    try:
        diag = full_diagnostic()
    except Exception:
        diag = {}
    try:
        mem = memory_stats()
    except Exception:
        mem = {}
    try:
        threat_sum = threat_summary()
    except Exception:
        threat_sum = {}
    try:
        from services.honeypot import honeypot
        honeypot_sum = honeypot.log_summary()
        blocked_ips = len(honeypot.get_blocklist())
    except Exception:
        honeypot_sum, blocked_ips = {}, 0
    try:
        from services.behavioral_security import behavioral
        anomaly_count = behavioral.threat_summary().get("total_anomalies", 0)
    except Exception:
        anomaly_count = 0
    try:
        # get_pending() drains every event type (chat, protocol, system...),
        # not just alerts — and each event nests its text under data.message,
        # not a top-level message/text field the way hud_mobile's pushAlert()
        # expects. Passing the raw events through rendered as a literal "[]"
        # for every non-alert event (undefined ts, undefined message).
        recent_alerts = [
            {"ts": e.get("timestamp", ""),
             "message": e.get("data", {}).get("message", "") if isinstance(e.get("data"), dict) else "",
             "severity": e.get("severity", "info")}
            for e in bus.get_pending() if e.get("type") == "alert"
        ]
    except Exception:
        recent_alerts = []
    try:
        from services.mark_system import mark_system, count_capabilities
        mark = mark_system.current_mark(real_capability_count=count_capabilities(app))
    except Exception:
        mark = {}
    try:
        from services.automation import check_friday_alive
        friday_online = check_friday_alive()
    except Exception:
        friday_online = False

    try:
        from core.state import state
        model = state.get("active_model", "") or ""
        provider = state.get("active_provider", "") or ""
        tier = state.get("active_tier", "") or ""
    except Exception:
        model = provider = tier = ""
    try:
        from services.model_updater import model_updater
        model_update_status = model_updater.get_status()
    except Exception:
        model_update_status = {}
    try:
        from services.combat_mode import combat_mode
        combat_status = combat_mode.status()
    except Exception:
        combat_status = {"state": "idle", "pending_confirm": False, "engaged_at": None}
    try:
        # Real, independently observable state — set by
        # core.self_improvement.run_improvement_cycle() itself while it's
        # actually running, not something inferred from a chat response.
        # A hallucinated "self-improvement cycle" (the streaming bug fixed
        # tonight) would show current_task: null here even while claiming
        # otherwise in the chat window — that mismatch is the whole point.
        from core.state import state
        from core.self_improvement import self_improvement
        sandbox_status = {
            "current_task":      state.get("current_task"),
            "pending_approvals": len(self_improvement.get_pending_approvals()),
        }
    except Exception:
        sandbox_status = {"current_task": None, "pending_approvals": 0}

    return {
        # Top-level, read directly from live state — see core/llm/router.py,
        # which sets these after every real chat call regardless of
        # provider (Groq or an Anthropic tier). diag.active_model below is
        # a same-value fallback for older HUD builds that read brain.model.
        "model":    model,
        "uptime_seconds": int(time.time() - BOOT_TIME),
        "provider": provider,
        "tier":     tier,
        "system": {
            "cpu":          sys_snap.get("cpu_percent", 0),
            "ram":          sys_snap.get("ram_used_pct", 0),
            "disk":         sys_snap.get("disk_used_pct", 0),
            "uptime_hours": sys_snap.get("uptime_hours", 0),
        },
        "brain": {
            "status":   diag.get("brain", "UNKNOWN"),
            "model":    model or diag.get("active_model", "—"),
            "provider": provider,
            "tier":     tier,
            "groq":     diag.get("groq_available", False),
            "ollama":   diag.get("ollama_available", False),
            "warnings": diag.get("warnings", []),
        },
        "memory": mem,
        "security": {
            "threats_24h":   threat_sum.get("last_24h", 0),
            "by_severity":   threat_sum.get("by_severity", {}),
            "baseline_set":  threat_sum.get("baseline_set", False),
            "honeypot_hits": honeypot_sum.get("triggers", 0),
            "blocked_ips":   blocked_ips,
            "anomaly_count": anomaly_count,
        },
        "mark":          mark,
        "combat_mode":   combat_status,
        "sandbox":       sandbox_status,
        "active_models":     model_update_status.get("current_models", {}),
        "last_model_check":  model_update_status.get("last_checked", "never"),
        "friday_online": friday_online,
        "alerts":        recent_alerts[:10],
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


# Static assets (CSS/JS/icons) still served from hud_mobile/
app.mount("/hud/static", StaticFiles(directory=str(HUD_DIR)), name="hud_static")


async def _early_background_start():
    """Protocol 11/2/16/9 + sentinel + canary — none of this is LLM-related
    or slow on its own, but it used to run synchronously inside the
    `startup` event handler, which Starlette blocks *all* request serving
    on (including /health) until it returns. A single unhandled exception
    anywhere in that block used to be able to crash startup entirely, and
    even without one, six sequential synchronous steps (each triggering
    module imports on first use) could plausibly outrun Render's health
    check timeout on a cold, CPU-throttled boot. Every step below is now
    both backgrounded (doesn't block request serving) and individually
    guarded (one failing step can't take the others down with it)."""
    from core.event_bus import bus
    from config.settings import ENVIRONMENT

    try:
        from core.protocols import integrity_check_startup
        integrity_result = integrity_check_startup()
        if integrity_result.get("modified"):
            print(f"[P11 INTEGRITY] ⚠ Modified files: {integrity_result['modified']}")
    except Exception as e:
        print(f"[JARVIS] Integrity check failed: {e}")

    try:
        from core.protocols import register_dead_mans_switch
        register_dead_mans_switch()
    except Exception as e:
        print(f"[JARVIS] Dead man's switch registration failed: {e}")

    try:
        from services.sentinel import start as sentinel_start
        base_dir = str(Path(__file__).parent.parent)
        sentinel_start(base_dir)  # loads a saved baseline from disk if one exists, else builds fresh
    except Exception as e:
        print(f"[JARVIS] Sentinel failed to start: {e}")

    # ── Wake word — local Mac only, no-op on Render/Railway (no mic) ─────────
    if ENVIRONMENT == "local":
        try:
            from services.wakeword import wakeword

            def _on_wakeword():
                bus.system(f"Wake word detected — listening.")

            wakeword.start(_on_wakeword)
        except Exception as e:
            print(f"[JARVIS] Wake word detector skipped: {e}")

    try:
        from core.protocols import start_endgame_loop
        start_endgame_loop()
    except Exception as e:
        print(f"[JARVIS] Endgame loop failed to start: {e}")

    try:
        from core.protocols import start_yinsen_watch
        start_yinsen_watch(hours=24)
    except Exception as e:
        print(f"[JARVIS] Yinsen watch failed to start: {e}")

    try:
        from services.canary import canary
        canary.plant_in_memory_files()
    except Exception as e:
        print(f"[JARVIS] Canary planting skipped: {e}")


@app.on_event("startup")
async def startup():
    import asyncio
    from core.state import state
    from core.event_bus import bus
    from core.llm.router import check_groq, check_ollama, check_anthropic
    from config.settings import ENVIRONMENT

    state.set("environment", ENVIRONMENT)
    print(f"[JARVIS] Environment: {ENVIRONMENT}")

    # Nothing above this line does I/O; everything that does is
    # backgrounded below so this handler returns immediately and
    # Starlette can start serving /health right away.
    asyncio.create_task(_early_background_start())

    # ── LLM probe ──────────────────────────────────────────────────────────────
    async def _probe():
        loop = asyncio.get_event_loop()
        # check_groq() treats a 429 as "up" (rate-limited, not down) — a
        # transient throttle shouldn't engage Friday Protocol.
        groq_ok      = await loop.run_in_executor(None, check_groq)
        ollama_ok    = await loop.run_in_executor(None, check_ollama)
        anthropic_ok = check_anthropic()
        state.update({
            "groq_available":   groq_ok,
            "ollama_available": ollama_ok,
            "active_model":     ("groq" if groq_ok else "ollama" if ollama_ok else "none"),
        })
        if groq_ok:
            bus.system("Groq LLM: online")
            print("[JARVIS] Groq: ✓")
        if ollama_ok:
            bus.system("Ollama: online")
            print("[JARVIS] Ollama: ✓")
        if not groq_ok and not anthropic_ok and not ollama_ok:
            state.set("status", "degraded")
            bus.alert("No LLM providers — Friday Protocol active.", "critical")
            print("[JARVIS] ⚠ Friday Protocol engaged")

    # ── Background LLM-touching services start 30s after boot ────────────────
    # The LLM probe, scheduler (consciousness/awareness/workshop jobs all
    # eventually call think()), and messaging bots all fire near-instantly on
    # a cold boot otherwise — piling straight onto Groq's rate limit before
    # the process has even finished coming up. Delaying them lets the server
    # itself become ready (health checks, chat) without a startup Groq spike.
    # This does NOT block app startup — /health etc. are live immediately.
    async def _delayed_background_start():
        try:
            await _delayed_background_start_body()
        except Exception:
            import traceback
            print("[JARVIS] _delayed_background_start crashed:")
            traceback.print_exc()

    async def _delayed_background_start_body():
        print("[JARVIS] Background services will start in 30s...")
        await asyncio.sleep(30)
        print("[JARVIS] 30s elapsed — starting background services now.")
        await _probe()

        groq_ok = state.get("groq_available", False)
        ollama_ok = state.get("ollama_available", False)

        # ── Warm the response cache — a handful of real LLM calls for
        # common queries, kept behind this same 30s stagger rather than
        # firing at raw process startup. Must go through run_in_executor
        # like _probe()'s check_groq/check_ollama calls just above — warm_cache()
        # is synchronous and blocking, and calling it directly here would run
        # it on the event loop itself, freezing every request (sync or async,
        # on this or any other route) for as long as its serial Groq calls
        # take. Normally that's under a second; under Groq rate-limiting it
        # can stretch to several seconds of total server unresponsiveness. ──
        #
        # Skipped in local dev (same ENVIRONMENT+DEV_MODE gate as
        # utils/security.py's auth bypass) — it's a one-time cost meant to
        # amortize against real production traffic; against a local dev loop
        # that restarts the process repeatedly while iterating, it's pure
        # rate-limit tax paid before a single real test message goes out.
        # Production behavior (ENVIRONMENT != "local") is unaffected.
        if ENVIRONMENT == "local" and os.getenv("DEV_MODE", "false").lower() == "true":
            print("[JARVIS] Cache warming skipped — local dev mode")
        else:
            try:
                from core.llm.router import warm_cache
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, warm_cache)
            except Exception as e:
                print(f"[JARVIS] Cache warming failed: {e}")

        # ── Suit assembly sequence — streams to any connected HUD ─────────────
        try:
            from services.suit_assembly import assembly
            for event in assembly.run_assembly_sequence(groq_ok=groq_ok):
                bus.publish("suit_assembly", event)
        except Exception as e:
            print(f"[JARVIS] Suit assembly sequence skipped: {e}")

        print("=" * 50)
        print("JARVIS V5 STARTUP COMPLETE")
        print("=" * 50)
        print(f"  Groq:    {'✓ ONLINE' if groq_ok else '✗ OFFLINE'}")
        print(f"  Ollama:  {'✓ ONLINE' if ollama_ok else '✗ OFFLINE (optional)'}")
        print("=" * 50 + "\n")

        try:
            from services.mark_system import mark_system, count_capabilities
            import services.sentinel as sentinel_mod
            mark = mark_system.current_mark(real_capability_count=count_capabilities(app))
            sentinel_armed = "armed" if sentinel_mod._running else "standing by"
            announcement = (
                f"Mark {mark.get('mark','V')} online. "
                f"{mark.get('capability_count', 0)} capabilities active. "
                f"{'Groq online.' if groq_ok else 'Groq offline — running on local systems.'} "
                f"Sentinel {sentinel_armed}. Standing by."
            )
            print(announcement)
            bus.system(announcement)
        except Exception as e:
            print(f"[JARVIS] Mark announcement skipped: {e}")

        from services.scheduler import start as scheduler_start
        scheduler_start()

        try:
            from services.messaging import start_all_background
            start_all_background()
        except Exception as e:
            print(f"[JARVIS] Messaging integrations skipped: {e}")

        # ── Fine-tuning readiness check (I/O only, no LLM call) ───────────────
        try:
            from services.fine_tuning import fine_tuner
            result = fine_tuner.prepare_training_data()
            if result.get("ready"):
                print(f"[JARVIS] Personal model ready ({result['count']} examples)")
            else:
                print(f"[JARVIS] {result.get('reason', '')}")
        except Exception as e:
            print(f"[JARVIS] Fine-tuning check skipped: {e}")

        # ── Auto-register workshop domains (free — just reads/writes JSON) ────
        try:
            from core.domain_expert import domain_expert
            domain_expert.auto_register_from_workshop()
        except Exception as e:
            print(f"[JARVIS] Domain auto-registration skipped: {e}")

        # ── Neuro profile analysis — one LLM call, only if enough history ─────
        # Staggered another 30s past _probe()'s check_groq() call above —
        # that one's cached (30s TTL) so scheduler_start()/messaging don't
        # add real Groq traffic, but this is a genuine uncached generative
        # call, and firing it right on top of _probe() was the one place
        # in this startup sequence actually capable of a same-instant
        # double-request.
        try:
            from core.memory import _load
            from config.settings import CONVERSATIONS_FILE
            convs = _load(CONVERSATIONS_FILE) or []
            if len(convs) >= 20:
                await asyncio.sleep(30)
                from core.neuro_mirror import neuro
                neuro.analyze_thinking_style(convs)
                print("[JARVIS] Neuro profile refreshed.")
        except Exception as e:
            print(f"[JARVIS] Neuro profile analysis skipped: {e}")

        # ── Suit status report (pure computation, no LLM call) ────────────────
        try:
            from services.suit_diagnostics import suit_status_report
            status = suit_status_report()
            bus.system(status)
            print(f"\n[JARVIS] {status}\n")
        except Exception as e:
            print(f"[JARVIS] Suit status skipped: {e}")

        # ── Background predictive pre-loading — opt-in, off by default ────────
        # (a standing 24/7 LLM-call generator once started; see
        # services/predictor.py for the full rationale)
        try:
            from config.settings import USE_BACKGROUND_PREDICTION
            if USE_BACKGROUND_PREDICTION:
                from services.predictor import predictor_engine
                predictor_engine.start_background_prediction()
                print("[JARVIS] Background predictive pre-loading started (USE_BACKGROUND_PREDICTION=true).")
        except Exception as e:
            print(f"[JARVIS] Background prediction skipped: {e}")

        # ── Model updater — one-time startup check (~90s further past the
        # 30s delay already elapsed above, so ~2 min after boot total) ────────
        if os.getenv("DISABLE_MODEL_UPDATER", "").lower() != "true":
            try:
                await asyncio.sleep(60)
                from services.model_updater import model_updater
                update_result = model_updater.check_and_apply()
                if update_result.get("applied"):
                    print(f"[JARVIS] Model updater: applied {update_result['applied']} update(s) on startup.")
            except Exception as e:
                print(f"[JARVIS] Model update check skipped: {e}")

        print("[JARVIS] Background LLM services started (30s post-boot delay elapsed).")

    asyncio.create_task(_delayed_background_start())

    # ── Ping FRIDAY on startup ────────────────────────────────────────────────
    async def _ping_friday():
        try:
            from services.automation import check_friday_alive
            loop = asyncio.get_event_loop()
            ok = await loop.run_in_executor(None, check_friday_alive)
            status = "online" if ok else "offline"
            state.set("friday_online", ok)
            bus.system(f"FRIDAY: {status}")
            print(f"[JARVIS] FRIDAY: {'✓' if ok else '✗ (offline)'}")
        except Exception:
            pass
    asyncio.create_task(_ping_friday())

    # ── Config validation — off the event loop entirely (not even a task):
    # it's synchronous file/env inspection, so a plain background thread
    # with a short delay keeps it out of the startup critical path without
    # needing to await anything.
    def _run_config_validation():
        import time as _t
        _t.sleep(5)
        try:
            from core.config_validator import validate_and_alert
            validate_and_alert()
        except Exception as e:
            print(f"[JARVIS] Config validation skipped: {e}")
    import threading
    threading.Thread(target=_run_config_validation, daemon=True).start()

    state.set("status", "online")
    bus.system("JARVIS V5 online. All systems nominal.")
    print("\n╔══════════════════════════════════════╗")
    print("║       J.A.R.V.I.S  V5.0  ONLINE     ║")
    print("╚══════════════════════════════════════╝\n")
    print(f"  Port:    {os.environ.get('JARVIS_PORT', 8000)}")
    print(f"  HUD:     http://localhost:8000/hud")
    print(f"  Chat:    http://localhost:8000/stark/chat/simple")
    print(f"  Docs:    http://localhost:8000/docs")
    print("  Groq/Ollama status + Mark announcement in ~30s (post-boot delay)\n")


@app.post("/stark/chat/simple")
async def chat_simple(body: dict, request: Request):
    """No-auth chat endpoint for local testing only. Self-restricted to
    loopback requests regardless of JARVIS_API_TOKEN/DEV_MODE settings —
    safe to leave in even outside dev mode since it can never be reached
    from outside the machine it's running on."""
    if request.client.host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(403, "Local only")
    from core.brain_v2 import brain
    msg = body.get("message", "")
    if not msg:
        return {"error": "No message"}
    return brain.process_dict(msg)


# Extra routes that need BackgroundTasks or are too small for their own file
@app.post("/stark/task", dependencies=[Depends(verify_token)])
def run_task(body: dict, bg: BackgroundTasks):
    from core.agents.planner_agent import run
    task = body.get("task", "")
    if body.get("async", False):
        bg.add_task(run, task)
        return {"status": "queued", "task": task}
    return run(task)

@app.post("/stark/task/parallel", dependencies=[Depends(verify_token)])
def parallel_task(body: dict):
    from core.agents.planner_agent import run_parallel
    return run_parallel(body.get("task", ""), body.get("agents", 3))

@app.get("/stark/threats", dependencies=[Depends(verify_token)])
def threats():
    from services.sentinel import summary
    return summary()

@app.get("/stark/threats/log", dependencies=[Depends(verify_token)])
def threat_log():
    from services.sentinel import threats
    return threats(24)

@app.post("/stark/baseline", dependencies=[Depends(verify_token)])
def rebuild_baseline():
    """Rebuild BOTH integrity baselines after intentional code changes:
    services/sentinel.py's file-tamper baseline (persisted to memory/baseline.json)
    AND Protocol 11's separate startup integrity check (core/protocols.py,
    persisted to config/integrity_baseline.json). Call this once after you're
    done editing so neither system flags your own changes as tampering on the
    next restart."""
    from services.sentinel import build_baseline
    from core.protocols import integrity_update_baseline
    base_dir = str(Path(__file__).parent.parent)
    sentinel_result = build_baseline(base_dir)
    integrity_update_baseline()
    return {"sentinel_baseline": sentinel_result, "protocol_11_baseline": "updated"}

@app.get("/stark/alerts", dependencies=[Depends(verify_token)])
def alerts():
    from core.event_bus import bus
    return bus.get_pending()

@app.get("/stark/friday", dependencies=[Depends(verify_token)])
def friday_status():
    from services.automation import check_friday_alive
    from core.state import state
    friday_url = os.environ.get("FRIDAY_URL", "http://localhost:8080")
    online     = check_friday_alive()
    state.set("friday_online", online)
    return {"friday_url": friday_url, "friday_online": online}
# (ElevenLabs voice endpoints live in server/routes/voice.py, prefix /stark/voice)

@app.get("/stark/evolution", dependencies=[Depends(verify_token)])
def evolution():
    from core import evolution as evo
    return evo.report()

@app.get("/stark/clips", dependencies=[Depends(verify_token)])
def clips(limit: int = 10):
    from core.memory import get_clips
    return {"clips": get_clips(limit)}

@app.post("/stark/backup", dependencies=[Depends(verify_token)])
def backup():
    from services.backup import backup_all
    return backup_all()

@app.get("/stark/briefing", dependencies=[Depends(verify_token)])
def briefing():
    from services.automation import morning_briefing
    return {"briefing": morning_briefing()}

@app.post("/stark/code/generate", dependencies=[Depends(verify_token)])
def code_gen(body: dict):
    from core.agents.coder import generate
    return generate(body.get("description",""), body.get("language","python"))

@app.post("/stark/research", dependencies=[Depends(verify_token)])
def research(body: dict):
    from core.agents.researcher import research as do_research
    return do_research(body.get("topic",""), body.get("depth",3))
