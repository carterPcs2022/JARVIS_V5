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

from utils.security import add_cors, verify_token
from server.websocket import router as ws_router
from server.routes.chat        import router as chat_router
from server.routes.telemetry   import router as telemetry_router
from server.routes.diagnostics import router as diag_router
from server.routes.health      import router as health_router
from server.routes.memory      import router as memory_router
from server.routes.voice       import router as voice_router
from server.routes.mac         import router as mac_router
from server.routes.protocols   import router as protocols_router
from server.routes.scatter     import router as scatter_router
from server.routes.search      import router as search_router
from server.routes.mark        import router as mark_router
from server.routes.stark_extra import router as stark_extra_router
from server.routes.final_features import router as final_router, protected as final_protected_router
from server.routes.glasses import router as glasses_router
from server.routes.protocols_18_35 import router as protocols_18_35_router
from server.routes.brain_enhancement import router as brain_enhancement_router
from server.routes.final_upgrade import router as final_upgrade_router
from server.routes.final_completion import router as final_completion_router
from server.routes.stark_infrastructure import router as stark_infra_router, phone_router as stark_phone_router
from server.routes.mythos import router as mythos_router
from server.routes.spotify import router as spotify_router, auth_router as spotify_auth_router
from server.routes.ultimate_brain import router as ultimate_brain_router
from server.routes.absolute_final import router as absolute_final_router

app = FastAPI(title="JARVIS", description="Just A Rather Very Intelligent System V5", version="5.0")
add_cors(app)

app.include_router(ws_router)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(telemetry_router)
app.include_router(diag_router)
app.include_router(memory_router)
app.include_router(voice_router)
app.include_router(mac_router)
app.include_router(protocols_router)
app.include_router(scatter_router)
app.include_router(search_router)
app.include_router(mark_router)
app.include_router(stark_extra_router)
app.include_router(final_router)
app.include_router(final_protected_router)
app.include_router(glasses_router)
app.include_router(protocols_18_35_router)
app.include_router(brain_enhancement_router)
app.include_router(final_upgrade_router)
app.include_router(final_completion_router)
app.include_router(stark_infra_router)
app.include_router(stark_phone_router)
app.include_router(mythos_router)
app.include_router(spotify_router)
app.include_router(spotify_auth_router)
app.include_router(ultimate_brain_router)
app.include_router(absolute_final_router)


@app.get("/metrics")
def metrics():
    """Prometheus scrape target — intentionally unauthenticated, matching
    the standard Prometheus pattern (the metrics endpoint is usually only
    reachable from an internal scraper, not the public internet)."""
    from services.metrics import generate_latest, CONTENT_TYPE_LATEST, update_system_metrics
    update_system_metrics()
    from fastapi.responses import Response as _Response
    return _Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


HUD_DIR = Path(__file__).parent.parent / "hud_mobile"


@app.get("/hud")
async def hud_router(request: Request):
    """Detect device type from User-Agent and serve correct HUD.
    Respects ?view=desktop or ?view=mobile query param."""
    view = request.query_params.get("view", "auto")

    if view == "desktop":
        return FileResponse(HUD_DIR / "desktop.html")
    if view == "mobile":
        return FileResponse(HUD_DIR / "index.html")

    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(kw in ua for kw in ["iphone", "android", "mobile", "tablet", "ipad"])

    return FileResponse(HUD_DIR / ("index.html" if is_mobile else "desktop.html"))


@app.get("/hud/desktop")
async def hud_desktop():
    return FileResponse(HUD_DIR / "desktop.html")


@app.get("/hud/mobile")
async def hud_mobile_view():
    return FileResponse(HUD_DIR / "index.html")


@app.get("/hud/holographic")
async def holographic_hud():
    return FileResponse(HUD_DIR / "holographic.html")


@app.get("/hud/ambient.js")
async def hud_ambient_js():
    from services.ambient import AMBIENT_HUD_SCRIPT
    from fastapi.responses import Response as _Response
    return _Response(AMBIENT_HUD_SCRIPT, media_type="application/javascript")


@app.get("/hud/intel")
async def intel_map():
    return FileResponse(HUD_DIR / "intelligence_map.html")


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


@app.get("/hud/status")
async def hud_status():
    """Single combined endpoint both HUDs poll every few seconds."""
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
        recent_alerts = bus.get_pending()
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
            "threats_24h":  threat_sum.get("last_24h", 0),
            "by_severity":  threat_sum.get("by_severity", {}),
            "baseline_set": threat_sum.get("baseline_set", False),
        },
        "mark":          mark,
        "friday_online": friday_online,
        "alerts":        recent_alerts[:10],
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


# Static assets (CSS/JS/icons) still served from hud_mobile/
app.mount("/hud/static", StaticFiles(directory=str(HUD_DIR)), name="hud_static")


@app.on_event("startup")
async def startup():
    import asyncio
    from core.state import state
    from services.sentinel import start as sentinel_start
    from core.event_bus import bus
    from core.llm.router import check_groq, check_ollama
    from config.settings import ENVIRONMENT

    state.set("environment", ENVIRONMENT)
    print(f"[JARVIS] Environment: {ENVIRONMENT}")

    # ── Protocol 11: Integrity Check — FIRST ─────────────────────────────────
    from core.protocols import (
        integrity_check_startup, register_dead_mans_switch,
        start_endgame_loop, start_yinsen_watch
    )
    integrity_result = integrity_check_startup()
    if integrity_result.get("modified"):
        print(f"[P11 INTEGRITY] ⚠ Modified files: {integrity_result['modified']}")

    # ── Protocol 2: Dead Man's Switch ────────────────────────────────────────
    register_dead_mans_switch()

    base_dir = str(Path(__file__).parent.parent)
    sentinel_start(base_dir)  # loads a saved baseline from disk if one exists, else builds fresh

    # ── Protocol 16: Endgame — hourly snapshot thread ─────────────────────────
    start_endgame_loop()

    # ── Protocol 9: Yinsen — idle check-in thread ────────────────────────────
    start_yinsen_watch(hours=24)

    # ── LLM probe ──────────────────────────────────────────────────────────────
    async def _probe():
        loop = asyncio.get_event_loop()
        groq_ok   = await loop.run_in_executor(None, check_groq)
        ollama_ok = await loop.run_in_executor(None, check_ollama)
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
        if not groq_ok and not ollama_ok:
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
        try:
            from core.neuro_mirror import neuro
            from core.memory import _load
            from config.settings import CONVERSATIONS_FILE
            convs = _load(CONVERSATIONS_FILE) or []
            if len(convs) >= 20:
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

        print("[JARVIS] Background LLM services started (30s post-boot delay elapsed).")

    asyncio.create_task(_delayed_background_start())

    # ── Ping FRIDAY on startup ────────────────────────────────────────────────
    async def _ping_friday():
        try:
            from services.automation import check_friday_alive
            ok = await loop.run_in_executor(None, check_friday_alive)
            status = "online" if ok else "offline"
            state.set("friday_online", ok)
            bus.system(f"FRIDAY: {status}")
            print(f"[JARVIS] FRIDAY: {'✓' if ok else '✗ (offline)'}")
        except Exception:
            pass
    asyncio.create_task(_ping_friday())

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
