"""services/glasses_hud.py — formats JARVIS data for the Ray-Ban's own
tiny in-lens display. Ray-Ban shows a small text overlay, so JARVIS sends
ultra-brief status strings rather than the full HUD payload other
surfaces get.
"""


class GlassesHUD:

    def get_status_text(self) -> str:
        """Ultra-brief status for the glasses display — ~60 chars max."""
        from core.state import state
        from datetime import datetime
        import os
        import zoneinfo

        # core.state never sets a "sentinel_threats" key — the real
        # 24h threat count lives in services.sentinel.summary().
        try:
            from services.sentinel import summary
            threats = summary().get("last_24h", 0)
        except Exception:
            threats = 0

        tier = state.get("active_tier") or "GROQ"

        try:
            tz = zoneinfo.ZoneInfo(os.getenv("USER_TIMEZONE", "America/New_York"))
        except Exception:
            tz = None
        now = datetime.now(tz).strftime("%I:%M %p") if tz else datetime.now().strftime("%I:%M %p")

        if threats > 10:
            return f"⚠ {threats} THREATS | {now} | JARVIS ONLINE"
        return f"JARVIS ONLINE | {tier.upper()} | {now}"

    def format_response_for_glasses(self, response: str) -> str:
        """Format a JARVIS response for the glasses speaker/display — short,
        no markdown, no lists."""
        if len(response) <= 120:
            return response
        from core.llm.router import think
        return think(
            f"Summarize for voice earpiece in under 20 words:\n{response}",
            force_model="instant",
        )


glasses_hud = GlassesHUD()
