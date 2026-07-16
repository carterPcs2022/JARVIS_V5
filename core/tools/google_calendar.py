"""
core/tools/google_calendar.py — Google Calendar via OAuth2 (real API,
create + list events), distinct from services/calendar_intel.py's CalDAV
integration.

Auth: a Google Cloud OAuth client (GOOGLE_CALENDAR_CLIENT_ID/_CLIENT_SECRET,
reused from the FRIDAY project's existing app registration — see
server/routes/calendar_auth.py for the one-time consent flow that mints
GOOGLE_CALENDAR_REFRESH_TOKEN) plus a long-lived refresh token. No access
token is stored — google-auth mints one from the refresh token on first use
each process start and auto-refreshes after that, so there's nothing here
that expires on Render's ephemeral disk between deploys.
"""
import re
from datetime import datetime, timedelta

from config.settings import (
    GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_REFRESH_TOKEN, USER_TIMEZONE,
)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def is_configured() -> bool:
    return bool(GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET
                and GOOGLE_CALENDAR_REFRESH_TOKEN)


def _get_service():
    """Build an authenticated Calendar API client. Raises if the google-auth/
    google-api-python-client packages aren't installed or credentials are
    missing — callers must check is_configured() first and catch import
    errors, same pattern services/calendar_intel.py uses for the optional
    `caldav` package."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,  # forces an immediate refresh via refresh_token below
        refresh_token=GOOGLE_CALENDAR_REFRESH_TOKEN,
        client_id=GOOGLE_CALENDAR_CLIENT_ID,
        client_secret=GOOGLE_CALENDAR_CLIENT_SECRET,
        token_uri=_TOKEN_URI,
        scopes=_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cacheDiscovery=False)


def create_event(title: str, start_date: str, end_date: str = "",
                  all_day: bool = True, description: str = "") -> dict:
    """start_date/end_date are ISO 'YYYY-MM-DD' strings. A single-day event
    omits end_date (defaults to start_date). Google's API treats the 'end'
    of an all-day event as exclusive, so a Aug 20-27 request needs end=Aug
    28 to actually cover the 27th — handled here, not by the caller."""
    if not is_configured():
        return {"error": "Google Calendar not connected. Visit /stark/calendar/auth to connect it."}

    end_date = end_date or start_date

    try:
        service = _get_service()
    except Exception as e:
        return {"error": f"Google Calendar client unavailable: {e}"}

    if all_day:
        end_exclusive = (datetime.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")
        body = {
            "summary": title,
            "description": description,
            "start": {"date": start_date},
            "end": {"date": end_exclusive},
        }
    else:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_date, "timeZone": USER_TIMEZONE},
            "end": {"dateTime": end_date, "timeZone": USER_TIMEZONE},
        }

    try:
        event = service.events().insert(calendarId="primary", body=body).execute()
        return {"ok": True, "id": event.get("id"), "link": event.get("htmlLink"),
                "summary": event.get("summary")}
    except Exception as e:
        return {"error": f"Calendar API error: {e}"}


def list_events(start_date: str, end_date: str = "", max_results: int = 25) -> dict:
    """start_date/end_date are ISO 'YYYY-MM-DD' strings; end_date defaults to
    start_date (a single-day query)."""
    if not is_configured():
        return {"error": "Google Calendar not connected. Visit /stark/calendar/auth to connect it."}

    end_date = end_date or start_date

    try:
        service = _get_service()
    except Exception as e:
        return {"error": f"Google Calendar client unavailable: {e}"}

    time_min = f"{start_date}T00:00:00Z"
    time_max = f"{end_date}T23:59:59Z"

    try:
        result = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            maxResults=max_results, singleEvents=True, orderBy="startTime",
        ).execute()
        events = [
            {
                "summary": e.get("summary", "(no title)"),
                "start": e.get("start", {}).get("date") or e.get("start", {}).get("dateTime"),
            }
            for e in result.get("items", [])
        ]
        return {"ok": True, "events": events}
    except Exception as e:
        return {"error": f"Calendar API error: {e}"}


_PARSE_PROMPT = """Extract a calendar action from this request. Reply with ONLY strict JSON, \
no other text, in exactly this shape:
{{"action": "create"|"list"|"none", "title": "<short 2-6 word event name>", \
"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "all_day": true|false}}

"create" = the user wants an event added to their calendar. Infer a short title from context; \
if none is given, use "Busy". start_date/end_date are the requested range (same value for a \
single day).
"list" = the user is asking what's on their calendar, not asking to add anything. \
start_date/end_date default to today if no range is given. title can be empty.
"none" = this message isn't actually a calendar request.

Today's date is {today}.

Request: {text}"""


def parse_calendar_request(text: str) -> dict:
    """LLM-based extraction (force_model='instant', same pattern as
    services/threat_detector.py and core/mac_dispatcher.py's _llm_parse) —
    date-range phrasing ("August 20- August 27", "next Tuesday", "the 3rd
    through the 5th") is too varied for a fixed regex/dateutil pass alone."""
    import json
    from core.llm.router import chat as router_chat

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        result = router_chat(
            messages=[{"role": "user", "content": _PARSE_PROMPT.format(today=today, text=text)}],
            max_tokens=150, temperature=0.0, force_model="instant",
        )
        raw = re.sub(r"```json|```", "", result["content"]).strip()
        parsed = json.loads(raw)
        return {
            "action":     parsed.get("action", "none"),
            "title":      parsed.get("title", "Busy") or "Busy",
            "start_date": parsed.get("start_date", "") or today,
            "end_date":   parsed.get("end_date", "") or parsed.get("start_date", today),
            "all_day":    bool(parsed.get("all_day", True)),
        }
    except Exception as e:
        print(f"[GoogleCalendar] parse_calendar_request failed: {e}")
        return {"action": "none", "title": "", "start_date": "", "end_date": "", "all_day": True}
