"""server/routes/absolute_final.py — House Party Protocol, Situation Room,
context switching, morning/evening routines, legal/investment/career
analysis, meeting transcription, price/package tracking, breach
monitoring, writing style engine."""
from fastapi import APIRouter, Depends, UploadFile, File
import tempfile

from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["absolute-final"], dependencies=[Depends(verify_token)])


# ── House Party Protocol ───────────────────────────────────────────────────────

@router.post("/house_party")
def house_party_activate(body: dict):
    from services.house_party import house_party
    return house_party.activate(body.get("task", ""))


# ── Situation Room ─────────────────────────────────────────────────────────────

@router.post("/situation/activate")
def situation_activate(body: dict | None = None):
    from services.situation_room import situation_room
    return situation_room.activate((body or {}).get("reason", ""))


@router.post("/situation/deactivate")
def situation_deactivate():
    from services.situation_room import situation_room
    return situation_room.deactivate()


@router.get("/situation/report")
def situation_report():
    from services.situation_room import situation_room
    return situation_room.status_report()


# ── Context switching ─────────────────────────────────────────────────────────

@router.post("/context/{name}")
def context_switch(name: str):
    from services.context_switch import switcher
    return switcher.switch(name)


@router.get("/context")
def context_current():
    from services.context_switch import switcher
    return switcher.get_current()


# ── Morning / evening routines ─────────────────────────────────────────────────

@router.post("/morning/run")
def morning_run():
    from services.morning_routine import morning
    return morning.run()


@router.post("/morning/schedule")
def morning_schedule(body: dict):
    from services.morning_routine import morning
    return morning.schedule(body.get("wake_time", "07:30"))


@router.post("/evening/run")
def evening_run():
    from services.evening_routine import evening
    return evening.run()


@router.post("/evening/schedule")
def evening_schedule(body: dict):
    from services.evening_routine import evening
    return evening.schedule(body.get("time", "22:00"))


# ── Legal ──────────────────────────────────────────────────────────────────────

@router.post("/legal/analyze")
def legal_analyze(body: dict):
    from services.legal import legal
    return legal.analyze_contract(body.get("text", ""))


@router.post("/legal/redflags")
def legal_redflags(body: dict):
    from services.legal import legal
    return {"red_flags": legal.find_red_flags(body.get("text", ""))}


@router.post("/legal/simplify")
def legal_simplify(body: dict):
    from services.legal import legal
    return {"explanation": legal.simplify_clause(body.get("clause", ""))}


# ── Investment ─────────────────────────────────────────────────────────────────

@router.post("/invest/stock")
def invest_stock(body: dict):
    from services.investment import investor
    return investor.analyze_stock(body.get("symbol", ""))


@router.post("/invest/crypto")
def invest_crypto(body: dict):
    from services.investment import investor
    return investor.crypto_analysis(body.get("coin", ""))


@router.post("/invest/compare")
def invest_compare(body: dict):
    from services.investment import investor
    return investor.compare(body.get("symbols", []))


# ── Meeting transcription ────────────────────────────────────────────────────────

@router.post("/meeting/transcribe")
async def meeting_transcribe(audio: UploadFile = File(...)):
    from services.meeting import meeting

    suffix = "." + (audio.filename.rsplit(".", 1)[-1] if audio.filename and "." in audio.filename else "wav")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        path = tmp.name

    try:
        return meeting.transcribe_and_analyze(path)
    finally:
        import os
        try:
            os.unlink(path)
        except Exception:
            pass


# ── Price tracker ──────────────────────────────────────────────────────────────

@router.post("/prices/watch")
def prices_watch(body: dict):
    from services.price_tracker import price_tracker
    return price_tracker.watch(body.get("product_name", ""), body.get("url", ""), body.get("target_price", 0))


@router.get("/prices/check")
def prices_check():
    from services.price_tracker import price_tracker
    return price_tracker.check_all()


@router.get("/prices/list")
def prices_list():
    from services.price_tracker import price_tracker
    return price_tracker.list_watches()


# ── Package tracker ──────────────────────────────────────────────────────────────

@router.post("/packages/add")
def packages_add(body: dict):
    from services.packages import packages
    return packages.add(body.get("tracking_number", ""), body.get("carrier", ""), body.get("description", ""))


@router.get("/packages/check")
def packages_check():
    from services.packages import packages
    return packages.check_all()


@router.get("/packages/list")
def packages_list():
    from services.packages import packages
    return packages.list_packages()


# ── Career ─────────────────────────────────────────────────────────────────────

@router.post("/career/resume")
def career_resume(body: dict):
    from services.career import career
    return career.optimize_resume(body.get("resume", ""), body.get("job_description", ""))


@router.post("/career/cover_letter")
def career_cover_letter(body: dict):
    from services.career import career
    return {"cover_letter": career.cover_letter(body.get("resume", ""), body.get("job_description", ""), body.get("company", ""))}


@router.post("/career/interview_prep")
def career_interview_prep(body: dict):
    from services.career import career
    return career.interview_prep(body.get("job_description", ""), body.get("company", ""))


@router.post("/career/salary")
def career_salary(body: dict):
    from services.career import career
    return career.salary_research(body.get("role", ""), body.get("location", ""))


# ── Breach monitor ─────────────────────────────────────────────────────────────

@router.post("/security/breach_check")
def security_breach_check(body: dict):
    from services.breach_monitor import breach_monitor
    return breach_monitor.check_email(body.get("email", ""))


@router.post("/security/password_check")
def security_password_check(body: dict):
    from services.breach_monitor import breach_monitor
    return breach_monitor.check_password_strength(body.get("password", ""))


# ── Writing style ──────────────────────────────────────────────────────────────

@router.post("/style/analyze")
def style_analyze(body: dict):
    from core.writing_style import writing_style
    return writing_style.analyze_style(body.get("samples", []))


@router.post("/style/write")
def style_write(body: dict):
    from core.writing_style import writing_style
    return {"written": writing_style.write_in_my_style(body.get("content", ""), body.get("format", "message"))}


@router.post("/style/rewrite")
def style_rewrite(body: dict):
    from core.writing_style import writing_style
    return {"rewritten": writing_style.write_in_my_style(body.get("content", ""), body.get("format", "message"))}
