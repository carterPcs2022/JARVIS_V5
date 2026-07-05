"""services/evening_routine.py — evening wind-down: day summary, tomorrow
preview, unfinished tasks, night mode, calm music."""


class EveningRoutine:

    def run(self) -> dict:
        from core.state import state
        state.set("voice_mode", "night")

        parts = ["Good evening."]

        try:
            from services.goals import get_goals
            incomplete = get_goals("active")
            if incomplete:
                parts.append(f"You have {len(incomplete)} unfinished item(s) from today.")
        except Exception:
            pass

        try:
            from services.calendar_intel import calendar_intel
            tomorrow = calendar_intel.get_upcoming(hours=24)
            if tomorrow:
                first = tomorrow[0]
                parts.append(f"Tomorrow: {first.get('title','')} at {first.get('start','')}.")
        except Exception:
            pass

        parts.append("Rest well.")
        message = " ".join(parts)

        try:
            from services.voice import speak
            speak(message)
        except Exception:
            pass

        try:
            from services.spotify import spotify
            if spotify.is_connected():
                spotify.play_mood("sleep")
        except Exception:
            pass

        return {"message": message, "status": "evening_complete"}

    def schedule(self, time: str = "22:00") -> dict:
        from services import scheduler as jarvis_scheduler
        hour, minute = map(int, time.split(":"))
        jarvis_scheduler.add_job(self.run, "cron", hour=hour, minute=minute, id="evening_routine", replace_existing=True)
        return {"scheduled": time}


evening = EveningRoutine()
