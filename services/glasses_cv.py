"""services/glasses_cv.py — Ray-Ban computer vision pipeline.

JARVIS analyzes a photo taken through the glasses (via the iPhone
Shortcut in deploy/glasses/). Uses core.tools.vision.analyze() — the
actual multimodal call in this codebase (Groq LLaVA) — rather than
routing the image through core.llm.router.think(), which is text-only
and would silently describe nothing but the prompt itself.
"""
from datetime import datetime


class GlassesCV:

    def analyze_frame(self, image_path: str, question: str = "") -> dict:
        """Analyze a frame from the glasses. Speaks a one-sentence summary
        through the glasses speaker (via the existing TTS cascade) so the
        Shortcut can just play whatever /stark/glasses/audio returns next,
        same pattern as the voice pipeline in server/routes/glasses.py."""
        from core.tools.vision import analyze

        prompt = question or (
            "You are JARVIS analyzing what Tony Stark sees through his "
            "helmet cameras. Describe what you see, identify anything "
            "important, flag any threats, and provide relevant information. "
            "Be brief and direct — this is real-time HUD data."
        )

        analysis = analyze(image_path, prompt)
        if analysis.startswith("[Vision error"):
            return {"error": analysis}

        from core.llm.router import think
        brief = think(
            f"Summarize in ONE sentence for voice readout:\n{analysis}",
            force_model="instant",
        )

        try:
            from services.voice import speak
            speak(brief)
        except Exception:
            pass

        return {"analysis": analysis, "brief": brief, "ts": datetime.now().isoformat()}

    def threat_scan(self, image_path: str) -> dict:
        """Quick threat assessment of the visual field."""
        from core.tools.vision import analyze

        result = analyze(
            image_path,
            "Quick threat assessment. Any threats, weapons, or dangerous "
            "situations visible? Reply: CLEAR, CAUTION, or THREAT + brief reason.",
        )
        if result.startswith("[Vision error"):
            return {"threat_level": "unknown", "assessment": result}

        upper = result.upper()
        level = "danger" if "THREAT" in upper else "warn" if "CAUTION" in upper else "clear"

        if level == "danger":
            from core.event_bus import bus
            bus.alert(f"Glasses threat detection: {result}", severity="critical", category="VISUAL_THREAT")

        return {"threat_level": level, "assessment": result}

    def identify_person(self, image_path: str) -> dict:
        """Describe a visible person without attempting facial identification —
        same ethical stance as services/vision.py's identify_person_from_image()."""
        from core.tools.vision import analyze

        result = analyze(
            image_path,
            "Describe the person visible. Do NOT attempt to identify them by "
            "name. Describe: approximate age, demeanor, what they appear to "
            "be doing, any notable details relevant to the situation.",
        )
        if result.startswith("[Vision error"):
            return {"error": result}
        return {"description": result}


glasses_cv = GlassesCV()
