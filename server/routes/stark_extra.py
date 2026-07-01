"""server/routes/stark_extra.py — wires the remaining Stark upgrade services into the API."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["stark-extra"], dependencies=[Depends(verify_token)])


# ── Awareness ─────────────────────────────────────────────────────────────────

@router.get("/awareness")
def get_awareness():
    from services.awareness import awareness
    return {"level": awareness.get_awareness_level(), "pending": awareness.get_pending_narrations()}

@router.post("/awareness/level")
def set_awareness_level(body: dict):
    from services.awareness import awareness
    awareness.set_awareness_level(body.get("level", "medium"))
    return {"level": awareness.get_awareness_level()}


# ── Network Intelligence ──────────────────────────────────────────────────────

@router.get("/network")
def network_map():
    from services.network_intel import network
    return network.network_map()

@router.post("/network/scan")
def network_scan():
    from services.network_intel import network
    return {"devices": network.scan_network()}

@router.get("/network/devices")
def network_devices():
    from services.network_intel import network
    return network.get_known_devices()

@router.get("/network/internet")
def network_internet():
    from services.network_intel import network
    return network.internet_health()


# ── Calendar ──────────────────────────────────────────────────────────────────

@router.get("/calendar/today")
def calendar_today():
    from services.calendar_intel import calendar_intel
    return calendar_intel.get_today()

@router.get("/calendar/upcoming")
def calendar_upcoming(hours: int = 24):
    from services.calendar_intel import calendar_intel
    return calendar_intel.get_upcoming(hours)

@router.get("/calendar/free")
def calendar_free(duration_minutes: int = 30, within_hours: int = 48):
    from services.calendar_intel import calendar_intel
    return calendar_intel.find_free_time(duration_minutes, within_hours)

@router.post("/calendar/event")
def calendar_create(body: dict):
    from services.calendar_intel import calendar_intel
    return calendar_intel.create_event(
        body.get("title", ""), body.get("start", ""),
        body.get("duration", 30), body.get("attendees", []),
    )


# ── Email ─────────────────────────────────────────────────────────────────────

@router.get("/email/inbox")
def email_inbox(max: int = 10):
    from services.email_intel import email_intel
    return email_intel.get_unread(max)

@router.get("/email/summary")
def email_summary():
    from services.email_intel import email_intel
    return {"summary": email_intel.summarize_inbox()}

@router.post("/email/draft")
def email_draft(body: dict):
    from services.email_intel import email_intel
    return email_intel.draft_reply(body.get("email_id", ""), body.get("intent", ""))


# ── Health ────────────────────────────────────────────────────────────────────

@router.post("/health")
def health_receive(body: dict):
    from services.health import health_monitor
    return health_monitor.receive_health_data(body)

@router.get("/health/latest")
def health_latest():
    from services.health import health_monitor
    return health_monitor.get_latest_health()

@router.get("/health/trends")
def health_trends():
    from services.health import health_monitor
    return health_monitor.sleep_analysis()


# ── Finance ───────────────────────────────────────────────────────────────────

@router.get("/finance/summary")
def finance_summary():
    from services.finance import finance
    return finance.account_summary()

@router.get("/finance/transactions")
def finance_transactions(days: int = 7):
    from services.finance import finance
    return finance.recent_transactions(days)

@router.get("/finance/subscriptions")
def finance_subscriptions():
    from services.finance import finance
    return finance.subscription_tracker()

@router.get("/finance/unusual")
def finance_unusual():
    from services.finance import finance
    return finance.unusual_charges()

@router.get("/stocks/{symbol}")
def stock_price(symbol: str):
    from services.finance import finance
    return finance.get_stock_price(symbol)

@router.get("/crypto/{coin}")
def crypto_price(coin: str):
    from services.finance import finance
    return finance.crypto_prices([coin])


# ── Playbook ──────────────────────────────────────────────────────────────────

@router.get("/playbook")
def playbook_list():
    from services.playbook import playbook
    return playbook.list_playbooks()

@router.post("/playbook")
def playbook_add(body: dict):
    from services.playbook import playbook
    return playbook.add_playbook(
        body.get("trigger", ""), body.get("actions", []), body.get("conditions", {}),
    )

@router.get("/playbook/history")
def playbook_history():
    from services.playbook import playbook
    return playbook.playbook_history()


# ── Developer Intelligence ────────────────────────────────────────────────────

@router.get("/code/index")
def code_index(path: str = "."):
    from services.dev_intel import dev_intel
    return dev_intel.index_project(path)

@router.post("/code/find")
def code_find(body: dict):
    from services.dev_intel import dev_intel
    return dev_intel.find_function(body.get("name", ""))

@router.post("/code/git/summary")
def code_git_summary(body: dict):
    from services.dev_intel import dev_intel
    return dev_intel.git_summary(body.get("repo_path", "."))

@router.get("/code/todos")
def code_todos(path: str = "."):
    from services.dev_intel import dev_intel
    return dev_intel.find_todos(path)


# ── Multimodal ────────────────────────────────────────────────────────────────

@router.post("/screen/capture")
def screen_capture():
    from services.multimodal import multimodal
    return {"result": multimodal.analyze_screen_content()}

@router.get("/clipboard")
def clipboard_get():
    from services.multimodal import multimodal
    return {"content": multimodal.get_clipboard()}


# ── Entertainment / Media ─────────────────────────────────────────────────────

@router.post("/media/play")
def media_play(body: dict):
    from services.entertainment import entertainment
    return entertainment.spotify_control(body.get("action", "play"))

@router.get("/media/now")
def media_now():
    from services.entertainment import entertainment
    return entertainment.spotify_now_playing()

@router.post("/media/recommend")
def media_recommend(body: dict):
    from services.entertainment import entertainment
    return {"result": entertainment.what_to_watch(body.get("mood", ""))}


# ── Tasks / Productivity ──────────────────────────────────────────────────────

@router.get("/tasks")
def tasks_list(filter: str = "active"):
    from services.productivity import productivity
    return productivity.task_list(filter)

@router.post("/tasks")
def tasks_add(body: dict):
    from services.productivity import productivity
    return productivity.add_task(
        body.get("title", ""), body.get("priority", "medium"), body.get("due"),
    )

@router.put("/tasks/{task_id}/complete")
def tasks_complete(task_id: str):
    from services.productivity import productivity
    return productivity.complete_task(task_id)

@router.get("/tasks/today")
def tasks_today():
    from services.productivity import productivity
    return {"priorities": productivity.prioritize_today()}

@router.post("/focus/start")
def focus_start(body: dict):
    from services.productivity import productivity
    return productivity.start_focus_session(body.get("duration_minutes", 25), body.get("task", ""))

@router.post("/focus/stop")
def focus_stop():
    from services.productivity import productivity
    return productivity.stop_focus_session()

@router.get("/habits")
def habits_get():
    from services.productivity import productivity
    return productivity.habit_tracker()

@router.post("/habits/log")
def habits_log(body: dict):
    from services.productivity import productivity
    return productivity.log_habit(body.get("habit_name", ""))


# ── Workshop ──────────────────────────────────────────────────────────────────

@router.get("/workshop")
def workshop_list():
    from services.workshop import workshop
    return workshop.list_projects()

@router.post("/workshop")
def workshop_add(body: dict):
    from services.workshop import workshop
    return workshop.add_project(
        body.get("name", ""), body.get("description", ""),
        body.get("path"), body.get("status", "active"),
    )

@router.put("/workshop/{name}")
def workshop_update(name: str, body: dict):
    from services.workshop import workshop
    return workshop.update_project_status(name, body.get("update", ""))

@router.get("/workshop/{name}/next")
def workshop_next(name: str):
    from services.workshop import workshop
    return {"suggestion": workshop.suggest_next_step(name)}


# ── Consciousness / World Model ───────────────────────────────────────────────

@router.get("/consciousness/journal")
def consciousness_journal():
    from core.consciousness import consciousness
    return consciousness.jarvis_journal()

@router.get("/consciousness/today")
def consciousness_today():
    from core.consciousness import consciousness
    return {"reflection": consciousness.daily_reflection()}

@router.post("/consciousness/opinion")
def consciousness_opinion(body: dict):
    from core.consciousness import consciousness
    return {"opinion": consciousness.express_opinion(body.get("topic", ""))}

@router.get("/world")
def world_summary():
    from core.world_model import world
    return {"summary": world.world_summary()}


# ── Travel ────────────────────────────────────────────────────────────────────

@router.get("/travel/flight/{flight_number}")
def travel_flight(flight_number: str):
    from services.travel import travel
    return travel.flight_status(flight_number)

@router.post("/travel/brief")
def travel_brief(body: dict):
    from services.travel import travel
    return {"brief": travel.travel_brief(body.get("destination", ""), body.get("date"))}

@router.post("/travel/currency")
def travel_currency(body: dict):
    from services.travel import travel
    return travel.currency_convert(
        body.get("amount", 0), body.get("from_cur", "USD"), body.get("to_cur", "EUR"),
    )


# ── Image Generation ──────────────────────────────────────────────────────────

@router.post("/image/generate")
def image_generate(body: dict):
    from services.image_gen import image_gen
    return image_gen.generate(
        body.get("prompt", ""), body.get("style", "realistic"), body.get("size", "1024x1024"),
    )


# ── Voice Modes ───────────────────────────────────────────────────────────────

@router.get("/voice/mode")
def voice_mode_get():
    from core.personality import get_voice_mode
    return {"mode": get_voice_mode()}

@router.post("/voice/mode")
def voice_mode_set(body: dict):
    from core.personality import set_voice_mode
    return {"mode": set_voice_mode(body.get("mode", "normal"))}


# ── Changelog ─────────────────────────────────────────────────────────────────

@router.get("/changelog")
def changelog_get():
    from core.changelog import changelog
    return changelog.full_history()

@router.get("/changelog/weekly")
def changelog_weekly():
    from core.changelog import changelog
    return {"summary": changelog.weekly_summary()}
