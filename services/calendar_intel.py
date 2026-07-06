"""
services/calendar_intel.py — CalendarIntelligence: event retrieval, briefings, free-time finder.
"""
import json
import os
from datetime import datetime, timedelta, date
from pathlib import Path

from core.llm.router import think
from config.settings import BASE_DIR

try:
    import caldav
except ImportError:
    caldav = None

_CALENDAR_CACHE = BASE_DIR / "memory" / "calendar_cache.json"


def _load_cache() -> list:
    if _CALENDAR_CACHE.exists():
        try:
            data = json.loads(_CALENDAR_CACHE.read_text())
            return data.get("events", []) if isinstance(data, dict) else data
        except Exception:
            return []
    return []


def _event_to_dict(event) -> dict:
    """Convert a caldav event to a plain dict."""
    try:
        from icalendar import Calendar
        cal  = Calendar.from_ical(event.data)
        for component in cal.walk():
            if component.name == "VEVENT":
                start = component.get("dtstart")
                end   = component.get("dtend")
                return {
                    "title":       str(component.get("summary", "")),
                    "start":       start.dt.isoformat() if start else "",
                    "end":         end.dt.isoformat()   if end   else "",
                    "location":    str(component.get("location",    "")),
                    "description": str(component.get("description", "")),
                    "attendees":   [
                        str(a) for a in (component.get("attendee") or [])
                    ],
                }
    except Exception:
        pass
    return {}


class CalendarIntelligence:

    # ------------------------------------------------------------------ #
    # Fetching events                                                      #
    # ------------------------------------------------------------------ #

    def get_today(self) -> list:
        """Return today's events from CalDAV or cached data."""
        caldav_url = os.environ.get("CALDAV_URL")

        if caldav_url and caldav is not None:
            try:
                client     = caldav.DAVClient(
                    url=caldav_url,
                    username=os.environ.get("CALDAV_USERNAME", ""),
                    password=os.environ.get("CALDAV_PASSWORD", ""),
                )
                principal  = client.principal()
                calendars  = principal.calendars()
                today_start = datetime.combine(date.today(), datetime.min.time())
                today_end   = today_start + timedelta(days=1)
                events = []
                for cal in calendars:
                    for ev in cal.date_search(today_start, today_end):
                        d = _event_to_dict(ev)
                        if d:
                            events.append(d)
                self.cache_events(events)
                return events
            except Exception:
                pass

        # Fall back to cache
        all_events  = _load_cache()
        today_str   = date.today().isoformat()
        return [e for e in all_events if e.get("start", "").startswith(today_str)]

    def get_upcoming(self, hours: int = 24) -> list:
        """Return events starting within the next `hours` hours."""
        caldav_url = os.environ.get("CALDAV_URL")
        now        = datetime.now()
        cutoff     = now + timedelta(hours=hours)

        if caldav_url and caldav is not None:
            try:
                client    = caldav.DAVClient(
                    url=caldav_url,
                    username=os.environ.get("CALDAV_USERNAME", ""),
                    password=os.environ.get("CALDAV_PASSWORD", ""),
                )
                principal = client.principal()
                calendars = principal.calendars()
                events    = []
                for cal in calendars:
                    for ev in cal.date_search(now, cutoff):
                        d = _event_to_dict(ev)
                        if d:
                            events.append(d)
                return sorted(events, key=lambda x: x.get("start", ""))
            except Exception:
                pass

        # Fall back to cache
        all_events = _load_cache()
        upcoming   = []
        for e in all_events:
            start_str = e.get("start", "")
            try:
                start_dt = datetime.fromisoformat(start_str)
                if now <= start_dt <= cutoff:
                    upcoming.append(e)
            except Exception:
                pass
        return sorted(upcoming, key=lambda x: x.get("start", ""))

    def next_event(self):
        """Return the next upcoming event, or None."""
        upcoming = self.get_upcoming(hours=24)
        return upcoming[0] if upcoming else None

    # ------------------------------------------------------------------ #
    # Briefings                                                            #
    # ------------------------------------------------------------------ #

    def pre_meeting_brief(self, event: dict) -> str:
        """LLM generates a meeting brief from event details."""
        prompt = (
            f"Generate a concise pre-meeting brief for JARVIS's user.\n"
            f"Meeting: {event.get('title', 'Untitled')}\n"
            f"Start: {event.get('start', 'Unknown')}\n"
            f"Location: {event.get('location', 'Not specified')}\n"
            f"Attendees: {', '.join(event.get('attendees', [])) or 'None listed'}\n"
            f"Description: {event.get('description', 'None')}\n\n"
            "Include: what to prepare, key points about attendees, suggested talking points, "
            "and any action items to complete before the meeting."
        )
        return think(prompt)

    # ------------------------------------------------------------------ #
    # Cache management                                                     #
    # ------------------------------------------------------------------ #

    def cache_events(self, events: list):
        """Save events to memory/calendar_cache.json."""
        _CALENDAR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cached_at": datetime.now().isoformat(),
            "events":    events,
        }
        _CALENDAR_CACHE.write_text(json.dumps(data, indent=2, default=str))

    # ------------------------------------------------------------------ #
    # Free time finder                                                     #
    # ------------------------------------------------------------------ #

    def find_free_time(self, duration_minutes: int = 30, within_hours: int = 48) -> list:
        """Find gaps in the calendar of at least `duration_minutes` during 9am–6pm."""
        all_events = _load_cache()
        now        = datetime.now()
        cutoff     = now + timedelta(hours=within_hours)

        # Build sorted list of busy intervals
        busy = []
        for e in all_events:
            try:
                s = datetime.fromisoformat(e["start"])
                en = datetime.fromisoformat(e["end"])
                if s < cutoff and en > now:
                    busy.append((max(s, now), min(en, cutoff)))
            except Exception:
                pass
        busy.sort(key=lambda x: x[0])

        free_slots = []
        day_start  = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if day_start < now:
            day_start += timedelta(days=1)

        current_day = day_start
        while current_day < cutoff:
            work_start = current_day
            work_end   = current_day.replace(hour=18, minute=0, second=0, microsecond=0)
            if work_start >= cutoff:
                break

            # Collect busy intervals for this day
            day_busy = [
                (max(s, work_start), min(e, work_end))
                for s, e in busy
                if s < work_end and e > work_start
            ]
            day_busy.sort(key=lambda x: x[0])

            # Find gaps
            pointer = work_start
            for bs, be in day_busy:
                if (bs - pointer).total_seconds() >= duration_minutes * 60:
                    free_slots.append({
                        "start":            pointer.isoformat(),
                        "end":              bs.isoformat(),
                        "duration_minutes": int((bs - pointer).total_seconds() // 60),
                    })
                pointer = max(pointer, be)

            # Gap after last meeting
            if (work_end - pointer).total_seconds() >= duration_minutes * 60:
                free_slots.append({
                    "start":            pointer.isoformat(),
                    "end":              work_end.isoformat(),
                    "duration_minutes": int((work_end - pointer).total_seconds() // 60),
                })

            current_day += timedelta(days=1)
            current_day  = current_day.replace(hour=9, minute=0, second=0, microsecond=0)

        return free_slots

    # ------------------------------------------------------------------ #
    # Event creation                                                       #
    # ------------------------------------------------------------------ #

    def create_event(
        self,
        title:     str,
        start:     str,
        duration:  int  = 60,
        attendees: list = [],
    ) -> dict:
        """Create a calendar event via CalDAV, or return a draft if not configured."""
        caldav_url = os.environ.get("CALDAV_URL")

        if caldav_url and caldav is not None:
            try:
                from icalendar import Calendar, Event as iCalEvent
                import uuid as _uuid

                start_dt = datetime.fromisoformat(start)
                end_dt   = start_dt + timedelta(minutes=duration)

                cal = Calendar()
                cal.add("prodid", "-//JARVIS V5//EN")
                cal.add("version", "2.0")

                ev = iCalEvent()
                ev.add("summary",  title)
                ev.add("dtstart",  start_dt)
                ev.add("dtend",    end_dt)
                ev.add("uid",      str(_uuid.uuid4()))
                cal.add_component(ev)

                client    = caldav.DAVClient(
                    url=caldav_url,
                    username=os.environ.get("CALDAV_USERNAME", ""),
                    password=os.environ.get("CALDAV_PASSWORD", ""),
                )
                principal = client.principal()
                calendars = principal.calendars()
                if calendars:
                    calendars[0].add_event(cal.to_ical().decode("utf-8"))
                    return {
                        "status": "created",
                        "event":  {
                            "title":             title,
                            "start":             start,
                            "duration_minutes":  duration,
                            "attendees":         attendees,
                        },
                    }
            except Exception as e:
                pass

        return {
            "status": "draft",
            "event": {
                "title":            title,
                "start":            start,
                "duration_minutes": duration,
                "attendees":        attendees,
            },
            "message": (
                "CalDAV not configured. Configure CALDAV_URL to create real events."
            ),
        }


# Module-level singleton
calendar_intel = CalendarIntelligence()
