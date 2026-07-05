"""services/context_switch.py — adapt voice mode, HUD theme, and
notification sensitivity to the user's current mode (work/personal/focus/
creative/rest/travel). Does not force a specific LLM tier per context —
"groq_model" is stored as informational metadata only; forcing every
subsequent chat call onto one tier regardless of the actual query would
fight the existing per-message smart routing in core/llm/router.py rather
than complement it."""

CONTEXTS = {
    "work": {
        "voice_mode": "workshop", "hud_theme": "blue", "notification_level": "medium",
        "focus": "projects and tasks", "preferred_tier": "smart",
        "greeting": "Work mode active. What are we building?",
    },
    "personal": {
        "voice_mode": "normal", "hud_theme": "blue", "notification_level": "high",
        "focus": "personal life and wellbeing", "preferred_tier": "standard",
        "greeting": "Switching to personal mode.",
    },
    "focus": {
        "voice_mode": "brief", "hud_theme": "dim", "notification_level": "critical_only",
        "focus": "current task only", "preferred_tier": "instant",
        "greeting": "Focus mode. I'll hold non-critical alerts.", "block_duration": 90,
    },
    "creative": {
        "voice_mode": "workshop", "hud_theme": "purple", "notification_level": "low",
        "focus": "creative thinking", "preferred_tier": "sonnet",
        "greeting": "Creative mode. Let's think differently.",
    },
    "rest": {
        "voice_mode": "night", "hud_theme": "dark", "notification_level": "critical_only",
        "focus": "rest and recovery", "preferred_tier": "instant",
        "greeting": "Rest mode. Go easy.",
    },
    "travel": {
        "voice_mode": "brief", "hud_theme": "blue", "notification_level": "high",
        "focus": "travel and logistics", "preferred_tier": "standard",
        "greeting": "Travel mode active. Safe travels.",
    },
}


class ContextSwitcher:

    def __init__(self):
        self.current_context = "work"

    def switch(self, context_name: str) -> dict:
        ctx = CONTEXTS.get(context_name.lower())
        if not ctx:
            return {"error": f"Unknown context: {context_name}", "available": list(CONTEXTS.keys())}

        self.current_context = context_name.lower()
        from core.state import state

        state.update({
            "voice_mode": ctx["voice_mode"], "hud_theme": ctx.get("hud_theme", "blue"),
            "focus_context": ctx["focus"], "notif_level": ctx["notification_level"],
            "current_context": self.current_context,
        })

        try:
            from services.voice import speak
            speak(ctx["greeting"])
        except Exception:
            pass

        from core.event_bus import bus
        bus.publish("context_switch", {"context": self.current_context, "settings": ctx})

        return {"context": self.current_context, "settings": ctx, "message": ctx["greeting"]}

    def get_current(self) -> dict:
        return {"context": self.current_context, "settings": CONTEXTS.get(self.current_context, {})}


switcher = ContextSwitcher()
