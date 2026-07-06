"""server/routes/new_features.py — the final batch: document upload analysis,
screen monitor, smart home scenes, reading memory, sleep intelligence,
relationship follow-ups, predictive scheduling, and code review/improve."""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["new-features"], dependencies=[Depends(verify_token)])


# ── Document analysis (drag-and-drop) ────────────────────────────────────────

@router.post("/documents/analyze")
async def documents_analyze(file: UploadFile = File(...), question: str = ""):
    from services import documents

    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = documents.ingest(tmp_path)
        if not result.get("ok"):
            return {"error": result.get("error", "Could not analyze document")}

        analysis = result["summary"]
        if question:
            analysis = documents.ask_about(result["id"], question)

        return {"file": file.filename, "analysis": analysis, "word_count": result.get("word_count", 0)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Screen monitor ────────────────────────────────────────────────────────────

@router.post("/screen/analyze")
def screen_analyze(body: dict | None = None):
    from services.screen_monitor import screen_monitor
    return screen_monitor.analyze_screen((body or {}).get("question", ""))


# ── Smart home scenes ─────────────────────────────────────────────────────────

@router.post("/home/scene")
def home_scene(body: dict):
    from services.home_automation import activate_scene
    return activate_scene(body.get("scene", ""))


@router.get("/home/scenes")
def home_scenes():
    from services.home_automation import SCENES
    return {"scenes": list(SCENES.keys())}


# ── Reading memory ────────────────────────────────────────────────────────────

@router.post("/reading/index")
def reading_index(body: dict):
    from services.reading_memory import reading_mem
    return reading_mem.index_url(body.get("url", ""), body.get("title", ""))


@router.post("/reading/search")
def reading_search(body: dict):
    from services.reading_memory import reading_mem
    return {"results": reading_mem.search_reading(body.get("query", ""))}


# ── Sleep intelligence ────────────────────────────────────────────────────────

@router.post("/sleep/log")
def sleep_log(body: dict):
    from services.sleep_intel import sleep_intel
    return sleep_intel.log_sleep(
        body.get("hours", 0), body.get("quality", 0),
        body.get("bedtime", ""), body.get("wake_time", ""),
    )


@router.get("/sleep/debt")
def sleep_debt():
    from services.sleep_intel import sleep_intel
    return sleep_intel.sleep_debt()


# ── Relationship intelligence ─────────────────────────────────────────────────

@router.get("/people/followups")
def people_followups():
    from services.people import should_follow_up
    return {"follow_ups": should_follow_up()}


@router.post("/people/interaction")
def people_interaction(body: dict):
    from services.people import record_interaction
    person = record_interaction(body.get("name", ""), body.get("notes", ""))
    if not person:
        return {"error": f"Person '{body.get('name', '')}' not found."}
    return person


# ── Predictive scheduling ─────────────────────────────────────────────────────

@router.get("/schedule/optimize")
def schedule_optimize():
    from services.predictive_scheduling import scheduler_intel
    return scheduler_intel.optimize_day()


# ── Finance — portfolio check ─────────────────────────────────────────────────

@router.get("/finance/portfolio")
def finance_portfolio(symbols: str = ""):
    from services.finance import finance
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    return finance.portfolio_check(symbol_list)


# ── Code intelligence ─────────────────────────────────────────────────────────

@router.post("/code/review")
def code_review(body: dict):
    from services.dev_intel import dev_intel
    return dev_intel.review_file(body.get("file", ""))


@router.post("/code/improve")
def code_improve(body: dict):
    from services.dev_intel import dev_intel
    return {"suggestions": dev_intel.suggest_improvements(body.get("code", ""))}


@router.post("/code/explain")
def code_explain(body: dict):
    from services.dev_intel import dev_intel
    return {"explanation": dev_intel.explain_file(body.get("file", ""))}
