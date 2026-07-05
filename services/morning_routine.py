"""services/morning_routine.py — full morning sequence: greeting, weather,
calendar, top priorities, news, morning playlist, phone push. Every piece
after the greeting is independently optional (try/except) so a missing
integration (e.g. Spotify never authenticated, no calendar configured)
degrades gracefully instead of breaking the whole routine."""
import os
from datetime import datetime


class MorningRoutine:

    def run(self) -> dict:
        parts = [f"Good morning. It's {datetime.now().strftime('%I:%M %p')}."]

        try:
            from core.tools.web import get_weather
            weather = get_weather("your location")
            if weather:
                parts.append(f"Weather: {weather}")
        except Exception:
            pass

        try:
            from services.calendar_intel import calendar_intel
            today = calendar_intel.get_today()
            if today:
                first = today[0]
                parts.append(f"You have {len(today)} event(s) today. First: {first.get('title','')} at {first.get('start','')}")
        except Exception:
            pass

        try:
            from core.life_os import life_os
            intentions = life_os.morning_intention()
            if intentions:
                parts.append(intentions)
        except Exception:
            pass

        try:
            from services.news_anchor import NewsAnchor
            brief = NewsAnchor().deliver(time_of_day="morning", spoken=False)
            if brief:
                parts.append(brief[:200])
        except Exception:
            pass

        full_brief = " ".join(parts)

        try:
            from services.voice import speak
            speak(full_brief)
        except Exception:
            pass

        try:
            from services.spotify import spotify
            if spotify.is_connected():
                spotify.play_mood("happy")
        except Exception:
            pass

        try:
            self._push_to_phone(full_brief)
        except Exception:
            pass

        return {"brief": full_brief, "status": "morning_routine_complete"}

    def _push_to_phone(self, message: str):
        import httpx
        user = os.getenv("PUSHOVER_USER_KEY", "")
        token = os.getenv("PUSHOVER_APP_TOKEN", "")
        if user and token:
            httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": token, "user": user, "title": "Good Morning — JARVIS Brief", "message": message[:500]},
                timeout=10,
            )

    def schedule(self, wake_time: str = "07:30") -> dict:
        from services import scheduler as jarvis_scheduler
        hour, minute = map(int, wake_time.split(":"))
        jarvis_scheduler.add_job(self.run, "cron", hour=hour, minute=minute, id="morning_routine", replace_existing=True)
        return {"scheduled": wake_time}


morning = MorningRoutine()
