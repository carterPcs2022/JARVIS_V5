"""services/screen_monitor.py — JARVIS watches your screen and offers relevant
help. Mac-only (uses `screencapture`); a no-op everywhere else, same guard
pattern as services/wakeword.py and the rest of the local-hardware services."""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from config.settings import ENVIRONMENT

log = logging.getLogger(__name__)

_SCREENSHOT_PATH = "/tmp/jarvis_screen.png"
_last_analysis: str | None = None
_last_topic_hash: str | None = None


class ScreenMonitor:

    def capture_screen(self) -> str | None:
        """Capture the current screen. Mac-only — returns None on Render/Railway
        or if `screencapture` isn't available (e.g. no display, no permission)."""
        if ENVIRONMENT != "local":
            return None
        try:
            subprocess.run(["screencapture", "-x", _SCREENSHOT_PATH], timeout=5, capture_output=True)
            if Path(_SCREENSHOT_PATH).exists():
                return _SCREENSHOT_PATH
        except Exception as e:
            log.debug("Screen capture failed: %s", e)
        return None

    def analyze_screen(self, question: str = "") -> dict:
        """Analyze current screen content."""
        global _last_analysis
        path = self.capture_screen()
        if not path:
            return {"error": "Screen capture not available (local Mac only)."}

        from services.vision import analyze_image
        prompt = question or (
            "What is on this screen? What is the user working on? "
            "Any suggestions or insights?"
        )
        try:
            analysis = analyze_image(path, prompt)
        except Exception as e:
            return {"error": f"Analysis failed: {e}"}

        _last_analysis = analysis
        return {"analysis": analysis, "ts": datetime.now().isoformat(), "screenshot": path}

    def proactive_monitor(self) -> dict | None:
        """Background check — if the screen shows something JARVIS can help
        with, proactively offer it once (skips if the same topic was already
        surfaced last check, so it doesn't repeat itself every 5 minutes)."""
        global _last_topic_hash
        if ENVIRONMENT != "local":
            return None

        result = self.analyze_screen(
            "Is the user doing something I could help with right now? "
            "Reply starting with YES or NO, and if YES say specifically what."
        )
        analysis = result.get("analysis", "")
        if not analysis or not analysis.upper().startswith("YES"):
            return None

        import hashlib
        topic_hash = hashlib.sha256(analysis[:120].encode()).hexdigest()
        if topic_hash == _last_topic_hash:
            return None
        _last_topic_hash = topic_hash

        from core.event_bus import bus
        bus.system(f"I noticed: {analysis[:200]}")
        return result


screen_monitor = ScreenMonitor()
