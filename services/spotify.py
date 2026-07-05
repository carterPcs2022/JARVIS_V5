"""services/spotify.py — full Spotify playback control via the raw Web API
(no spotipy dependency needed — httpx + the OAuth endpoints directly)."""
import os
import time
import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import httpx

from config.settings import BASE_DIR

log = logging.getLogger(__name__)

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/stark/spotify/callback")
TOKEN_FILE = BASE_DIR / "memory" / "spotify_token.json"

_MOOD_QUERIES = {
    "focus": "focus deep work instrumental",
    "energy": "high energy workout motivation",
    "relax": "chill relaxing ambient",
    "sleep": "sleep calm peaceful",
    "happy": "happy upbeat feel good",
    "coding": "lofi hip hop coding beats",
    "creative": "creative inspiration flow state",
}


class SpotifyService:

    def _load_token(self) -> dict:
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_token(self, token: dict):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token))

    def _get_access_token(self) -> str | None:
        token = self._load_token()
        if not token:
            return None
        if time.time() > token.get("expires_at", 0) - 60:
            return self._refresh_token(token.get("refresh_token"))
        return token.get("access_token")

    def _refresh_token(self, refresh_token: str | None) -> str | None:
        if not refresh_token:
            return None
        try:
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token", "refresh_token": refresh_token,
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                },
                timeout=10,
            )
            data = r.json()
            if "access_token" not in data:
                log.warning("Spotify token refresh failed: %s", data)
                return None
            token = {
                "access_token": data["access_token"],
                # Spotify only returns a new refresh_token sometimes — keep
                # the old one if it didn't send a replacement.
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_at": time.time() + data["expires_in"],
            }
            self._save_token(token)
            return token["access_token"]
        except Exception as e:
            log.warning("Spotify token refresh error: %s", e)
            return None

    def _api(self, method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        token = self._get_access_token()
        if not token:
            return {"error": "Not authenticated — visit /stark/spotify/auth first"}
        try:
            headers = {"Authorization": f"Bearer {token}"}
            url = f"https://api.spotify.com/v1{path}"
            r = httpx.request(method, url, headers=headers, json=data, params=params, timeout=10)
            if r.status_code == 204 or not r.content:
                return {"ok": True}
            body = r.json()
            if r.status_code >= 400:
                return {"error": body.get("error", {}).get("message", str(body))}
            return body
        except Exception as e:
            return {"error": str(e)}

    def get_auth_url(self) -> str:
        scopes = (
            "user-modify-playback-state user-read-playback-state "
            "user-read-currently-playing streaming"
        )
        params = {
            "client_id": CLIENT_ID, "response_type": "code",
            "redirect_uri": REDIRECT_URI, "scope": scopes,
        }
        return f"https://accounts.spotify.com/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> bool:
        try:
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                timeout=10,
            )
            data = r.json()
            if "access_token" not in data:
                log.warning("Spotify code exchange failed: %s", data)
                return False
            self._save_token({
                "access_token": data["access_token"], "refresh_token": data["refresh_token"],
                "expires_at": time.time() + data["expires_in"],
            })
            return True
        except Exception as e:
            log.warning("Spotify code exchange error: %s", e)
            return False

    def now_playing(self) -> dict:
        return self._api("GET", "/me/player/currently-playing")

    def play(self, query: str = "") -> dict:
        if query:
            result = self.search(query)
            uri = result.get("uri")
            if uri:
                return self._api("PUT", "/me/player/play", data={"uris": [uri]})
        return self._api("PUT", "/me/player/play")

    def pause(self) -> dict:
        return self._api("PUT", "/me/player/pause")

    def next_track(self) -> dict:
        return self._api("POST", "/me/player/next")

    def previous_track(self) -> dict:
        return self._api("POST", "/me/player/previous")

    def set_volume(self, percent: int) -> dict:
        percent = max(0, min(100, percent))
        return self._api("PUT", "/me/player/volume", params={"volume_percent": percent})

    def search(self, query: str, type: str = "track") -> dict:
        token = self._get_access_token()
        if not token:
            return {}
        try:
            r = httpx.get(
                "https://api.spotify.com/v1/search",
                params={"q": query, "type": type, "limit": 1},
                headers={"Authorization": f"Bearer {token}"}, timeout=10,
            )
            items = r.json().get("tracks", {}).get("items", [])
            if items:
                return {"name": items[0]["name"], "artist": items[0]["artists"][0]["name"], "uri": items[0]["uri"]}
            return {}
        except Exception:
            return {}

    def play_mood(self, mood: str) -> dict:
        """Play music matched to a mood/context — JARVIS picks the search query."""
        query = _MOOD_QUERIES.get(mood.lower(), f"{mood} music")
        return self.play(query)

    def is_connected(self) -> bool:
        return bool(self._get_access_token())


spotify = SpotifyService()


# ── Quick voice-command parser ────────────────────────────────────────────────
# Checked before the LLM call in core/brain_v2.py — music commands are
# instant, keyword-matched, and skip the brain pipeline entirely.

def handle_spotify_command(text: str) -> str | None:
    """Returns a response string if `text` is a Spotify command, else None."""
    t = text.lower()

    if not spotify.is_connected():
        return None  # let the LLM handle it normally rather than claim music control that isn't set up

    if any(w in t for w in ("pause", "stop the music", "stop playing")):
        spotify.pause()
        return "Music paused."

    if any(w in t for w in ("next", "skip")):
        spotify.next_track()
        return "Skipping to next track."

    if any(w in t for w in ("previous", "last song", "go back")):
        spotify.previous_track()
        return "Back to the previous track."

    if "louder" in t or "turn it up" in t:
        spotify.set_volume(80)
        return "Volume up."

    if "quieter" in t or "turn it down" in t:
        spotify.set_volume(30)
        return "Volume down."

    for mood in _MOOD_QUERIES:
        if mood in t and "music" in t:
            spotify.play_mood(mood)
            return f"Playing {mood} music, boss."

    for trigger in ("play ", "put on "):
        if trigger in t:
            query = t.split(trigger, 1)[-1].strip()
            if query:
                result = spotify.search(query)
                if result:
                    spotify.play(query)
                    return f"Playing {result['name']} by {result['artist']}."
            spotify.play()
            return "Resuming music."

    return None
