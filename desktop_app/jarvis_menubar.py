"""desktop_app/jarvis_menubar.py — JARVIS in the Mac menu bar.

One click to talk, status without opening the browser.
Requires: pip install -r requirements-local.txt (adds rumps)
Run: python3 desktop_app/jarvis_menubar.py

JARVIS_URL and JARVIS_API_TOKEN are read from the environment only — never
hardcode a real token here, this file is committed to source control.
"""
import os

import requests
import rumps

JARVIS_URL = os.getenv("JARVIS_URL", "http://localhost:8000")
TOKEN = os.getenv("JARVIS_API_TOKEN", "")


class JarvisMenuBar(rumps.App):

    def __init__(self):
        super().__init__("⚡", quit_button=None)
        self.menu = [
            "Open HUD",
            "Quick Command",
            rumps.separator,
            "Check Status",
            "Morning Brief",
            "News Brief",
            rumps.separator,
            "Quit JARVIS",
        ]

    @rumps.clicked("Open HUD")
    def open_hud(self, _):
        import subprocess
        subprocess.run(["open", f"{JARVIS_URL}/hud"])

    @rumps.clicked("Quick Command")
    def quick_command(self, _):
        response = rumps.Window("Command, sir...", "JARVIS", dimensions=(320, 40)).run()
        if response.clicked and response.text:
            result = self._send(response.text)
            if result:
                rumps.alert("JARVIS", result[:500])

    @rumps.clicked("Check Status")
    def check_status(self, _):
        try:
            r = requests.get(f"{JARVIS_URL}/hud/status", timeout=5)
            data  = r.json()
            model = data.get("model", "unknown")
            rumps.alert("JARVIS Status", f"Status: ONLINE\nModel: {model}")
        except Exception:
            rumps.alert("JARVIS Status", "OFFLINE")

    @rumps.clicked("Morning Brief")
    def morning_brief(self, _):
        result = self._send("JARVIS give me a morning briefing")
        if result:
            rumps.alert("Morning Brief", result[:500])

    @rumps.clicked("News Brief")
    def news_brief(self, _):
        result = self._send("JARVIS give me a news briefing")
        if result:
            rumps.alert("News Brief", result[:500])

    @rumps.clicked("Quit JARVIS")
    def quit_app(self, _):
        rumps.quit_application()

    def _send(self, message: str) -> str:
        try:
            r = requests.post(
                f"{JARVIS_URL}/stark/chat",
                json={"message": message},
                headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {},
                timeout=15,
            )
            return r.json().get("response", "")
        except Exception as e:
            return f"Error: {e}"

    @rumps.timer(30)
    def update_status(self, _):
        """Update menu bar icon based on server status."""
        try:
            r = requests.get(f"{JARVIS_URL}/health", timeout=3)
            self.title = "⚡" if r.status_code == 200 else "⚠️"
        except Exception:
            self.title = "⚫"


if __name__ == "__main__":
    JarvisMenuBar().run()
