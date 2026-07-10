"""services/mac_bridge.py — client for the Mac Bridge (~/mac_bridge/bridge.py,
runs locally on the user's Mac, not on Render). Every request includes the
shared MAC_BRIDGE_TOKEN — the bridge itself now requires and verifies it
(constant-time comparison) since it's typically exposed to the internet
via ngrok so this Render-hosted process can reach it."""
import os
import httpx

MAC_URL = os.getenv("MAC_BRIDGE_URL", "")
MAC_TOKEN = os.getenv("MAC_BRIDGE_TOKEN", "")


class MacBridge:

    def _call(self, endpoint: str, data: dict | None = None) -> dict:
        if not MAC_URL:
            return {"error": "Mac bridge not configured"}
        try:
            r = httpx.post(
                f"{MAC_URL}/mac/{endpoint}",
                json={**(data or {}), "token": MAC_TOKEN},
                timeout=5,
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def open_app(self, app_name: str) -> dict:
        return self._call("open", {"app": app_name})

    def notify(self, title: str, msg: str) -> dict:
        return self._call("notify", {"title": title, "message": msg})

    def set_volume(self, level: int) -> dict:
        return self._call("volume", {"volume": level})

    def do_not_disturb(self, enable: bool) -> dict:
        return self._call("do_not_disturb", {"enable": enable})

    def get_battery(self) -> str:
        result = self._call("battery")
        return result.get("battery", "unknown")

    def open_url(self, url: str) -> dict:
        return self._call("browser", {"action": "open", "url": url})

    def screenshot(self) -> dict:
        return self._call("screenshot")

    def speak_locally(self, text: str) -> dict:
        """Mac TTS as fallback when ElevenLabs fails."""
        return self._call("say", {"text": text})


mac_bridge = MacBridge()
