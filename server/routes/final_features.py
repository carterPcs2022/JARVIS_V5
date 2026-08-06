"""server/routes/final_features.py — Wires the final major feature set into the API:
webhooks, personal search, second brain, privacy mode, news anchor, decisions,
tutor, legacy, fitness, content creation, visualization, emotional state,
offline mode, language, translator mode, and the SMS webhook."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, PlainTextResponse
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["final-features"])
protected = APIRouter(prefix="/stark", tags=["final-features"], dependencies=[Depends(verify_token)])


# ── Webhooks (github/stripe only; each verified against its own signing
#    scheme in verify_webhook_source before the body is parsed — see
#    services/webhooks.py) ──────────────────────────────────────────────────

@router.post("/webhook/{source}")
async def receive_webhook(source: str, request: Request):
    import json
    from services.webhooks import WebhookManager, verify_webhook_source
    raw_body = await request.body()
    verify_webhook_source(source, request, raw_body)
    payload = json.loads(raw_body) if raw_body else {}
    return WebhookManager.process(source, payload)


@protected.get("/webhook/history")
def webhook_history():
    from services.webhooks import WebhookManager
    return WebhookManager.history()


# ── SMS via Twilio (X-Twilio-Signature verified against TWILIO_AUTH_TOKEN;
#    no bearer token, since Twilio can't send one — see verify_twilio_signature) ──

@router.post("/sms/incoming")
async def sms_incoming(request: Request):
    from services.messaging import handle_incoming_sms, send_sms
    from utils.security import verify_twilio_signature
    form = await request.form()
    verify_twilio_signature(request, dict(form))
    from_number = form.get("From", "")
    body = form.get("Body", "")
    reply = handle_incoming_sms(from_number, body)
    send_sms(reply, to=from_number)
    return PlainTextResponse("<Response></Response>", media_type="application/xml")


# ── Personal search ───────────────────────────────────────────────────────────

@protected.post("/search/personal")
def personal_search(body: dict):
    from core.personal_search import search, search_and_synthesize
    if body.get("synthesize"):
        return {"synthesis": search_and_synthesize(body.get("query", ""))}
    return search(body.get("query", ""), body.get("sources"), body.get("limit", 20))


# ── Second brain ──────────────────────────────────────────────────────────────

@protected.get("/brain/notes")
def brain_notes_list():
    from services.second_brain import second_brain
    return second_brain.list_notes()


@protected.post("/brain/capture")
def brain_capture(body: dict):
    from services.second_brain import second_brain
    return second_brain.capture(body.get("content", ""), body.get("tags"), body.get("source", ""))


@protected.post("/brain/dump")
def brain_dump(body: dict):
    from services.second_brain import second_brain
    return second_brain.brain_dump(body.get("text", ""))


@protected.get("/brain/daily")
def brain_daily():
    from services.second_brain import second_brain
    return second_brain.daily_note()


@protected.get("/brain/weekly-review")
def brain_weekly():
    from services.second_brain import second_brain
    return {"review": second_brain.weekly_review()}


@protected.get("/brain/search")
def brain_search(q: str):
    from services.second_brain import second_brain
    return second_brain.search_notes(q)


# ── Privacy mode ──────────────────────────────────────────────────────────────

@protected.post("/privacy/enable")
def privacy_enable(body: dict):
    from core.privacy_mode import privacy_mode
    return privacy_mode.enable(body.get("passphrase"))


@protected.post("/privacy/disable")
def privacy_disable():
    from core.privacy_mode import privacy_mode
    return privacy_mode.disable()


@protected.get("/privacy/status")
def privacy_status():
    from core.privacy_mode import privacy_mode
    return privacy_mode.status()


# ── News anchor ───────────────────────────────────────────────────────────────

@protected.get("/news")
def news_latest():
    from services.news_anchor import news_anchor
    latest = news_anchor.latest_briefing()
    return latest or {"message": "No briefing generated yet."}


@protected.post("/news/deliver")
def news_deliver(body: dict):
    from services.news_anchor import news_anchor
    script = news_anchor.deliver(body.get("time_of_day", "morning"), body.get("spoken", True))
    return {"script": script}


# ── Decision support ───────────────────────────────────────────────────────────

@protected.post("/decisions/analyze")
def decisions_analyze(body: dict):
    from services.decisions import decisions
    return decisions.analyze(body.get("decision", ""), body.get("options"), body.get("criteria"))


@protected.post("/decisions/pros-cons")
def decisions_pros_cons(body: dict):
    from services.decisions import decisions
    return decisions.pros_cons(body.get("topic", ""))


@protected.post("/decisions/devil-advocate")
def decisions_devil(body: dict):
    from services.decisions import decisions
    return {"argument": decisions.devil_advocate(body.get("decision", ""), body.get("chosen_option", ""))}


@protected.post("/decisions/risk")
def decisions_risk(body: dict):
    from services.decisions import decisions
    return decisions.risk_analysis(body.get("plan", ""))


@protected.post("/decisions/swot")
def decisions_swot(body: dict):
    from services.decisions import decisions
    return decisions.swot(body.get("subject", ""))


@protected.get("/decisions/log")
def decisions_log():
    from services.decisions import decisions
    return decisions.decision_log()


@protected.post("/decisions/log")
def decisions_log_create(body: dict):
    from services.decisions import decisions
    return decisions.log_decision(body.get("decision", ""), body.get("chosen_option", ""), body.get("notes", ""))


# ── Tutor ──────────────────────────────────────────────────────────────────────

@protected.post("/tutor/explain")
def tutor_explain(body: dict):
    from services.tutor import tutor
    return {"explanation": tutor.explain(body.get("topic", ""), body.get("level", "auto"))}


@protected.post("/tutor/socratic")
def tutor_socratic(body: dict):
    from services.tutor import tutor
    return {"question": tutor.socratic_mode(body.get("topic", ""), body.get("prior_exchange", ""))}


@protected.post("/tutor/flashcards")
def tutor_flashcards(body: dict):
    from services.tutor import tutor
    return tutor.flashcard_session(body.get("topic", ""), body.get("n_cards", 10))


@protected.post("/tutor/quiz")
def tutor_quiz(body: dict):
    from services.tutor import tutor
    return tutor.quiz_me(body.get("topic", ""), body.get("difficulty", "medium"))


@protected.post("/tutor/study-plan")
def tutor_study_plan(body: dict):
    from services.tutor import tutor
    return tutor.study_plan(body.get("subject", ""), body.get("goal", ""), body.get("weeks", 4))


@protected.post("/tutor/explain-error")
def tutor_explain_error(body: dict):
    from services.tutor import tutor
    return {"explanation": tutor.explain_error(body.get("error_message", ""), body.get("language", "python"))}


# ── Digital legacy (extra scrutiny — master token only where it matters most) ──

@protected.get("/legacy/status")
def legacy_status():
    from services.legacy import digital_legacy
    return digital_legacy.legacy_status()


@protected.post("/legacy/contact")
def legacy_contact(body: dict):
    from services.legacy import digital_legacy
    return digital_legacy.set_emergency_contact(
        body.get("name", ""), body.get("email", ""), body.get("access_level", "read_only"))


@protected.post("/legacy/final-message")
def legacy_final_message(body: dict):
    from services.legacy import digital_legacy
    return digital_legacy.write_final_message(body.get("message", ""))


@protected.post("/legacy/data-will")
def legacy_data_will(body: dict):
    from services.legacy import digital_legacy
    return digital_legacy.data_will(body.get("categories"))


# ── Fitness ────────────────────────────────────────────────────────────────────

@protected.post("/fitness/plan")
def fitness_plan(body: dict):
    from services.fitness import fitness_coach
    return fitness_coach.workout_plan(
        body.get("goal", "general fitness"), body.get("days_per_week", 3),
        body.get("equipment"), body.get("duration_minutes", 45))


@protected.post("/fitness/log")
def fitness_log(body: dict):
    from services.fitness import fitness_coach
    return fitness_coach.log_workout(body.get("exercises", []))


@protected.get("/fitness/suggest")
def fitness_suggest():
    from services.fitness import fitness_coach
    return {"suggestion": fitness_coach.suggest_today()}


@protected.post("/fitness/nutrition")
def fitness_nutrition(body: dict):
    from services.fitness import fitness_coach
    return fitness_coach.nutrition_log(body.get("meal", ""))


@protected.get("/fitness/summary")
def fitness_summary(period: str = "week"):
    from services.fitness import fitness_coach
    return {"summary": fitness_coach.fitness_summary(period)}


# ── Content creation ───────────────────────────────────────────────────────────

@protected.post("/content/post")
def content_post(body: dict):
    from services.content import content_creation
    return {"content": content_creation.write_post(body.get("topic", ""), body.get("platform", "twitter"), body.get("tone", "professional"))}


@protected.post("/content/email")
def content_email(body: dict):
    from services.content import content_creation
    return {"content": content_creation.write_email(body.get("to", ""), body.get("subject", ""), body.get("intent", ""), body.get("context", ""))}


@protected.post("/content/script")
def content_script(body: dict):
    from services.content import content_creation
    return {"content": content_creation.write_script(body.get("topic", ""), body.get("format", "youtube"), body.get("duration_minutes", 5))}


@protected.post("/content/summarize")
def content_summarize(body: dict):
    from services.content import content_creation
    return {"summary": content_creation.summarize(body.get("content", ""), body.get("style", "bullets"), body.get("max_words", 150))}


@protected.post("/content/rewrite")
def content_rewrite(body: dict):
    from services.content import content_creation
    return {"content": content_creation.rewrite(body.get("content", ""), body.get("goal", ""))}


@protected.post("/content/proofread")
def content_proofread(body: dict):
    from services.content import content_creation
    return content_creation.proofread(body.get("content", ""))


@protected.post("/content/title")
def content_title(body: dict):
    from services.content import content_creation
    return {"titles": content_creation.generate_title(body.get("content", ""), body.get("n_options", 5))}


@protected.post("/content/calendar")
def content_calendar(body: dict):
    from services.content import content_creation
    return content_creation.content_calendar(body.get("topics", []), body.get("days", 30))


# ── Data visualization ─────────────────────────────────────────────────────────

@router.get("/viz/{chart_id}")
def viz_serve(chart_id: str):
    from services.visualization import data_viz
    path = data_viz.get_chart_path(chart_id)
    if not path:
        return {"error": "Chart not found"}
    return FileResponse(path, media_type="text/html")


@protected.post("/viz/generate")
def viz_generate(body: dict):
    from services.visualization import data_viz
    chart_id = data_viz.chart(body.get("data", {}), body.get("chart_type", "auto"), body.get("title", ""))
    return {"chart_id": chart_id, "url": f"/stark/viz/{chart_id}" if chart_id else None}


@protected.get("/viz/spending")
def viz_spending(period: str = "month"):
    from services.visualization import data_viz
    chart_id = data_viz.spending_chart(period)
    return {"chart_id": chart_id, "url": f"/stark/viz/{chart_id}" if chart_id else None}


@protected.get("/viz/health")
def viz_health(metric: str = "sleep", days: int = 30):
    from services.visualization import data_viz
    chart_id = data_viz.health_timeline(metric, days)
    return {"chart_id": chart_id, "url": f"/stark/viz/{chart_id}" if chart_id else None}


@protected.get("/viz/system")
def viz_system(metric: str = "cpu", hours: int = 24):
    from services.visualization import data_viz
    chart_id = data_viz.system_history(metric, hours)
    return {"chart_id": chart_id, "url": f"/stark/viz/{chart_id}" if chart_id else None}


# ── Emotional state ────────────────────────────────────────────────────────────

@protected.get("/emotion")
def emotion_get():
    from core.emotional_state import emotional_state
    emotional_state.update()
    return emotional_state.get()

@protected.get("/emotion/describe")
def emotion_describe():
    from core.emotional_state import emotional_state
    return {"description": emotional_state.describe()}

@protected.get("/emotion/history")
def emotion_history(hours: int = 24):
    from core.emotional_state import emotional_state
    return emotional_state.history(hours)


# ── Offline mode ───────────────────────────────────────────────────────────────

@protected.get("/offline/status")
def offline_status():
    from core.offline import status
    return status()


# ── Language ───────────────────────────────────────────────────────────────────

@protected.post("/language/detect")
def language_detect(body: dict):
    from core.language import detect_language
    return {"language": detect_language(body.get("text", ""))}


@protected.post("/language/translate")
def language_translate(body: dict):
    from core.language import translate
    return {"translated": translate(body.get("text", ""), body.get("target", "en"))}


@protected.post("/language/set-preferred")
def language_set(body: dict):
    from core.language import set_preferred_language
    return set_preferred_language(body.get("language", "en"))


# ── Translator mode ────────────────────────────────────────────────────────────
# Live relay mode: while active, JARVIS stops conversing and just translates
# every message — one-way into target_language, or back-and-forth if
# source_language is also given (see core/translator_mode.py). Say
# "stop translating" (or similar) in chat to exit from a channel with no
# REST/HUD access, e.g. Discord/Telegram/SMS.

@protected.post("/translator/enable")
def translator_enable(body: dict):
    from core.translator_mode import translator_mode
    return translator_mode.enable(body.get("target_language", ""), body.get("source_language"))


@protected.post("/translator/disable")
def translator_disable():
    from core.translator_mode import translator_mode
    return translator_mode.disable()


@protected.get("/translator/status")
def translator_status():
    from core.translator_mode import translator_mode
    return translator_mode.status()
