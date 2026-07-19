"""server/routes/mac.py — Direct Mac control REST endpoints."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark/mac", tags=["mac"], dependencies=[Depends(verify_token)])


@router.post("/app/open")
def app_open(body: dict):
    from core.tools.mac import open_app
    return open_app(body.get("name", ""))


@router.post("/app/quit")
def app_quit(body: dict):
    from core.tools.mac import quit_app
    return quit_app(body.get("name", ""))


@router.get("/apps")
def running_apps():
    from core.tools.mac import list_running_apps
    return {"apps": list_running_apps()}


@router.post("/volume")
def volume(body: dict):
    from core.tools.mac import set_volume, get_volume, mute, unmute
    action = body.get("action", "set")
    if action == "get":   return {"volume": get_volume()}
    if action == "mute":  return mute()
    if action == "unmute":return unmute()
    return set_volume(body.get("level", 50))


@router.post("/screenshot")
def screenshot():
    from core.tools.mac import take_screenshot
    import datetime
    path = f"/tmp/jarvis_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    return take_screenshot(path)


@router.post("/notify")
def notify(body: dict):
    from core.tools.mac import notify
    return notify(body.get("title", "JARVIS"), body.get("message", ""))


@router.get("/calendar")
def calendar():
    from core.tools.mac import get_todays_events
    return {"events": get_todays_events()}


@router.post("/reminder")
def reminder(body: dict):
    from core.tools.mac import create_reminder
    return create_reminder(body.get("title", "Reminder"), body.get("due_in_minutes", 60))


# ── Spotify ───────────────────────────────────────────────────────────────────

@router.get("/spotify/current")
def spotify_current():
    from core.tools.spotify import current_track
    return current_track()


@router.post("/spotify/control")
def spotify_control(body: dict):
    from core.tools import spotify
    action = body.get("action", "play_pause")
    actions = {
        "play":       spotify.play,
        "pause":      spotify.pause,
        "play_pause": spotify.play_pause,
        "next":       spotify.next_track,
        "prev":       spotify.prev_track,
    }
    if action == "volume":
        return spotify.set_volume(body.get("level", 50))
    if action == "search":
        return spotify.search_and_play(body.get("query", ""))
    fn = actions.get(action)
    return fn() if fn else {"error": f"Unknown action: {action}"}


# ── Gmail ─────────────────────────────────────────────────────────────────────

@router.get("/gmail/inbox")
def gmail_inbox(unread_only: bool = True, limit: int = 10):
    from core.tools.gmail import check_inbox, is_configured
    if not is_configured():
        return {"error": "Gmail not configured", "setup": "See core/tools/gmail.py"}
    return {"emails": check_inbox(limit, unread_only)}


@router.get("/gmail/search")
def gmail_search(q: str, limit: int = 5):
    from core.tools.gmail import search_emails, is_configured
    if not is_configured():
        return {"error": "Gmail not configured"}
    return {"emails": search_emails(q, limit)}


@router.post("/gmail/draft")
def gmail_draft(body: dict):
    """Draft-then-confirm only — this endpoint used to send immediately
    (POST /gmail/send calling core.tools.gmail.send_email() with zero
    confirmation step). Creates a pending draft for review; nothing here
    sends anything. See POST /gmail/confirm_send."""
    from core.tools.gmail_send import draft_email, is_configured
    if not is_configured():
        return {"error": "Gmail OAuth sending isn't configured"}
    return draft_email(body.get("to", ""), body.get("subject", ""), body.get("body", ""))


@router.post("/gmail/confirm_send")
def gmail_confirm_send(body: dict):
    from core.tools.gmail_send import send_pending_draft
    return send_pending_draft(body.get("draft_id"))


@router.post("/gmail/discard_draft")
def gmail_discard_draft():
    from core.tools.gmail_send import discard_pending_draft
    discarded = discard_pending_draft()
    return {"discarded": discarded}


@router.post("/command")
def mac_command(body: dict):
    """Natural-language Mac control — same as chatting but goes direct to dispatcher."""
    from core.mac_dispatcher import dispatch
    cmd = body.get("command", "")
    if not cmd:
        return {"error": "No command provided"}
    return {"result": dispatch(cmd)}
