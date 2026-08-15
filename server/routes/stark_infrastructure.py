"""server/routes/stark_infrastructure.py — Stark Security, phone (Twilio),
deep research, GitHub intelligence, Life OS, natural-language data queries,
and social intelligence. /metrics is registered separately in server/api.py
(unauthenticated, standard for a Prometheus scrape target)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["stark-infrastructure"], dependencies=[Depends(verify_token)])

# Twilio webhooks can't send our bearer token, so they're registered on
# their own unauthenticated router — Twilio's request signature is the only
# verification available without extra setup, matching the source spec.
phone_router = APIRouter(prefix="/stark/phone", tags=["phone"])


# ── Stark Security ───────────────────────────────────────────────────────────

@router.post("/security/register_device")
def security_register_device(body: dict):
    from services.stark_security import stark_security
    return stark_security.register_device(body.get("device_name", ""), body.get("device_fingerprint", ""))


@router.get("/security/audit")
def security_audit():
    from services.stark_security import stark_security
    return stark_security.security_audit()


@router.get("/security/devices")
def security_devices():
    from services.stark_security import stark_security
    return stark_security.list_devices()


@router.get("/security/attack_log")
def security_attack_log(limit: int = 50):
    from services.stark_security import stark_security
    return stark_security.attack_log(limit)


# ── Phone (Twilio) ────────────────────────────────────────────────────────────

@phone_router.post("/call")
async def phone_incoming_call():
    from services.phone import phone
    return Response(content=phone.handle_incoming_call(), media_type="text/xml")


@phone_router.post("/respond")
async def phone_respond(request: Request):
    from services.phone import phone
    form = await request.form()
    transcript = form.get("TranscriptionText") or "Hello JARVIS"
    return Response(content=phone.handle_response(transcript), media_type="text/xml")


@phone_router.post("/transcribed")
async def phone_transcribed():
    """Twilio's async transcription callback — nothing to do, /respond
    already handled the turn with its own (faster) transcription."""
    return Response(content="", media_type="text/xml")


@phone_router.post("/sms")
async def phone_sms(request: Request):
    from services.phone import phone
    form = await request.form()
    phone.handle_sms(form.get("From", ""), form.get("Body", ""))
    return Response(content="<Response/>", media_type="text/xml")


@router.post("/phone/alert")
def phone_alert(body: dict):
    import os
    from services.phone import phone
    to_number = body.get("to") or os.getenv("MY_PHONE_NUMBER", "")
    return phone.send_alert_call(body.get("message", ""), to_number)


@router.post("/phone/call")
def phone_call_someone(body: dict):
    """Have JARVIS place a real call and speak a message — 'call X and tell
    them Y', not an emergency-only path. Reuses the same Twilio call the
    critical-alert escalation and emergency contacts use."""
    from services.phone import phone
    to_number = body.get("to", "")
    message = body.get("message", "")
    if not to_number or not message:
        return {"error": "Both 'to' and 'message' are required"}
    return phone.send_alert_call(message, to_number)


# ── Emergency contacts ──────────────────────────────────────────────────────
# Real people alerted on a Mayday trigger (see core/brain_v2.py) — not an
# automated 911/dispatch integration. See services/emergency_contacts.py.

@router.get("/emergency_contacts")
def emergency_contacts_list():
    from services.emergency_contacts import list_contacts
    return {"contacts": list_contacts()}


@router.post("/emergency_contacts")
def emergency_contacts_add(body: dict):
    from services.emergency_contacts import add_contact
    return add_contact(
        body.get("name", ""), body.get("phone", ""),
        body.get("call", True), body.get("sms", True),
    )


@router.delete("/emergency_contacts/{name}")
def emergency_contacts_remove(name: str):
    from services.emergency_contacts import remove_contact
    return remove_contact(name)


@router.post("/emergency_contacts/alert")
def emergency_contacts_alert_now(body: dict):
    """Manual trigger — same alert_all() path Mayday uses, without needing
    to speak/type the actual Mayday phrase."""
    from services.emergency_contacts import alert_all
    message = body.get("message", "JARVIS emergency alert triggered manually.")
    return alert_all(message, reason=body.get("reason", "manual"))


# ── Deep Research ─────────────────────────────────────────────────────────────

@router.post("/research/start")
def research_start(body: dict):
    from core.agents.deep_research import deep_research
    return deep_research.research(body.get("topic", ""), body.get("depth", "standard"))


@router.get("/research/status")
def research_status(research_id: str = ""):
    from core.agents.deep_research import deep_research
    if research_id:
        return deep_research.get_status(research_id)
    return deep_research.active()


@router.get("/research/reports")
def research_reports():
    from core.agents.deep_research import deep_research
    return deep_research.list_reports()


@router.get("/research/{research_id}")
def research_get(research_id: str):
    from core.agents.deep_research import deep_research
    report = deep_research.get_report(research_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


# ── GitHub Intelligence ────────────────────────────────────────────────────────

@router.get("/github/repos")
def github_repos():
    from services.github_intel import github
    return github.get_repos()


@router.get("/github/commits/{repo}")
def github_commits(repo: str, days: int = 7):
    from services.github_intel import github
    return github.get_recent_commits(repo, days)


@router.post("/github/review")
def github_review(body: dict):
    from services.github_intel import github
    return github.review_pr(body.get("repo", ""), body.get("pr_number", 0))


@router.get("/github/summary/{repo}")
def github_summary(repo: str):
    from services.github_intel import github
    return {"repo": repo, "summary": github.code_summary(repo)}


@router.get("/github/brief")
def github_brief():
    from services.github_intel import github
    return {"brief": github.daily_dev_brief()}


# ── Life OS ────────────────────────────────────────────────────────────────────

@router.post("/life/vision")
def life_vision(body: dict):
    from core.life_os import life_os
    return life_os.set_vision(body.get("vision", ""))


@router.post("/life/values")
def life_values(body: dict):
    from core.life_os import life_os
    return life_os.set_values(body.get("values", []))


@router.post("/life/area")
def life_area(body: dict):
    from core.life_os import life_os
    return life_os.add_life_area(
        body.get("area", ""), body.get("current_state", ""), body.get("desired_state", ""), body.get("score", 5)
    )


@router.get("/life/alignment")
def life_alignment():
    from core.life_os import life_os
    return life_os.alignment_check()


@router.get("/life/review/weekly")
def life_weekly_review():
    from core.life_os import life_os
    return life_os.weekly_review()


@router.get("/life/morning")
def life_morning():
    from core.life_os import life_os
    return {"intention": life_os.morning_intention()}


@router.get("/life/dashboard")
def life_dashboard():
    from core.life_os import life_os
    return life_os.dashboard()


# ── Natural language query ────────────────────────────────────────────────────

@router.post("/query")
def nl_query_endpoint(body: dict):
    from core.nl_query import nl_query
    return nl_query.query(body.get("question", ""))


# ── Social intelligence ────────────────────────────────────────────────────────

@router.post("/intel/person")
def intel_person(body: dict):
    from services.social_intel import social
    return social.person_brief(body.get("name", ""), body.get("company", ""), body.get("context", ""))


@router.post("/intel/company")
def intel_company(body: dict):
    from services.social_intel import social
    return social.company_brief(body.get("company", ""))
