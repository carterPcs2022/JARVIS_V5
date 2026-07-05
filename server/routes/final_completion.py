"""server/routes/final_completion.py — final completion batch: suit
assembly, holographic/intel HUD pages, scenario engine, debate prep,
autonomous handler, remote Mac control, Stark docs, missions, and the
brain-enhancement endpoints (Socratic/analogical/synthesis/second-order/
expertise calibration)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["final-completion"], dependencies=[Depends(verify_token)])

HUD_DIR = Path(__file__).parent.parent.parent / "hud_mobile"


# ── Scenario probability engine ────────────────────────────────────────────────

@router.post("/scenario/probability")
def scenario_probability(body: dict):
    from core.scenario_engine import scenario_engine
    return scenario_engine.calculate_probability(body.get("scenario", ""), body.get("context"))


@router.post("/scenario/simulate")
def scenario_simulate(body: dict):
    from core.scenario_engine import scenario_engine
    return scenario_engine.run_simulation(
        body.get("scenario", ""), body.get("variables"), body.get("iterations", 100)
    )


@router.post("/scenario/compare")
def scenario_compare(body: dict):
    from core.scenario_engine import scenario_engine
    return scenario_engine.compare_scenarios(body.get("scenarios", []))


# ── Debate prep ─────────────────────────────────────────────────────────────────

@router.post("/debate/prepare")
def debate_prepare(body: dict):
    from services.debate_prep import debate
    return debate.prepare(
        body.get("topic", ""), body.get("your_position", ""), body.get("opponent_type", "general")
    )


@router.post("/debate/practice")
def debate_practice(body: dict):
    from services.debate_prep import debate
    return {"response": debate.practice_debate(body.get("topic", ""), body.get("your_statement", ""))}


# ── Autonomous handler ("I'll handle it") ───────────────────────────────────────

@router.post("/handle")
def handle_task(body: dict):
    from services.autonomous_handler import handler
    return handler.handle(body.get("task", ""), body.get("notify_on_complete", True))


@router.get("/handle/active")
def handle_active():
    from services.autonomous_handler import handler
    return handler.active_tasks()


@router.get("/handle/completed")
def handle_completed(limit: int = 10):
    from services.autonomous_handler import handler
    return handler.completed_tasks(limit)


# ── Remote Mac control (SSH via Tailscale when hosted, direct when local) ──────

@router.post("/remote/command")
def remote_command(body: dict):
    from services.remote_control import mac
    return mac.execute(body.get("command", ""))


@router.get("/remote/commands")
def remote_commands():
    from services.remote_control import mac
    return {"commands": list(mac.SAFE_COMMANDS.keys())}


@router.post("/remote/screenshot")
def remote_screenshot():
    from services.remote_control import mac
    b64 = mac.get_screenshot()
    if not b64:
        return {"error": "Screenshot unavailable (remote SSH can't retrieve files without scp)"}
    return {"image_base64": b64}


# ── Stark Industries document generation ────────────────────────────────────────

@router.post("/docs/report")
def docs_report(body: dict):
    from services.stark_docs import stark_docs
    return stark_docs.generate_report(
        body.get("title", "REPORT"), body.get("content", ""), body.get("classification", "INTERNAL")
    )


@router.get("/docs/{doc_id}")
def docs_get(doc_id: str):
    from services.stark_docs import stark_docs
    path = stark_docs.get_report_path(doc_id)
    if not path:
        raise HTTPException(404, "Document not found")
    return FileResponse(path, media_type="text/html")


# ── Mission objectives ───────────────────────────────────────────────────────────

@router.post("/missions")
def missions_add(body: dict):
    from services.goals import add_mission
    return add_mission(body.get("title", ""), body.get("deadline", ""), body.get("priority", "high"))


@router.get("/missions")
def missions_list():
    from services.goals import list_missions
    return list_missions()


# ── Intel feed (backs hud_mobile/intelligence_map.html) ─────────────────────────
# GET /stark/threats/log already exists in server/api.py — the map fetches
# that directly rather than duplicating it here.

@router.get("/watches/hits")
def watches_hits():
    """Placeholder — no keyword/news-watch feed is wired up yet, so this
    returns an empty list rather than fabricating data for the intel map."""
    return []


# ── Brain enhancements ───────────────────────────────────────────────────────────

@router.post("/socratic/guide")
def socratic_guide(body: dict):
    from core.socratic import socratic
    query = body.get("query", "")
    if not socratic.should_use_socratic(query):
        return {"used_socratic": False, "message": "Query doesn't match Socratic triggers — answer directly instead."}
    return {"used_socratic": True, "message": socratic.guide(query, body.get("context", ""))}


@router.post("/analogical/explain")
def analogical_explain(body: dict):
    from core.analogical import analogical
    return {"explanation": analogical.explain_with_analogy(body.get("concept", ""), body.get("user_background", ""))}


@router.post("/analogical/pattern")
def analogical_pattern(body: dict):
    from core.analogical import analogical
    return {"pattern": analogical.find_pattern(body.get("situation", ""))}


@router.post("/synthesis/cross-domain")
def synthesis_cross_domain(body: dict):
    from core.synthesis import synthesis
    return synthesis.cross_domain_synthesis(body.get("topic", ""))


@router.get("/synthesis/weekly")
def synthesis_weekly():
    from core.synthesis import synthesis
    return {"synthesis": synthesis.weekly_synthesis()}


@router.post("/reasoning/second-order")
def reasoning_second_order(body: dict):
    from core.reasoning import second_order_think
    return {"analysis": second_order_think(body.get("query", ""), body.get("first_answer", ""))}


@router.get("/expertise/{topic}")
def expertise_calibrate(topic: str):
    from core.personality import calibrate_expertise
    return {"topic": topic, "level": calibrate_expertise(topic)}
