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
        """Play on the user's active Spotify Connect device — JARVIS never
        streams audio itself (Render has no speakers to play through and no
        access to the user's), it just tells Spotify's own service which
        device to play on, same as tapping play in the Spotify app."""
        token = self._get_access_token()
        if not token:
            return {"error": "Not authenticated"}

        devices = self._get_devices()
        if not devices:
            return {
                "error": "No active Spotify device found",
                "fix": "Open Spotify on your phone or Mac first",
            }

        device = devices[0]
        device_id = device["id"]

        if query:
            result = self.search(query)
            uri = result.get("uri")
            if not uri:
                return {"error": f"Could not find: {query}"}

            resp = self._api("PUT", "/me/player/play", data={"uris": [uri]}, params={"device_id": device_id})
            if "error" in resp:
                return resp
            return {
                "playing": True,
                "track":   result.get("name", ""),
                "artist":  result.get("artist", ""),
                "device":  device.get("name", "your device"),
            }

        resp = self._api("PUT", "/me/player/play", params={"device_id": device_id})
        if "error" in resp:
            return resp
        return {"playing": True, "device": device.get("name", "your device")}

    def _get_devices(self) -> list:
        """List the user's available Spotify Connect devices."""
        resp = self._api("GET", "/me/player/devices")
        return resp.get("devices", []) if "error" not in resp else []

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

# Checked before SPOTIFY_PLAY so "no play the song" stops rather than plays.
SPOTIFY_STOP = [
    "stop playing", "pause", "no play", "stop music", "stop the music",
    "turn off music", "silence",
]

SPOTIFY_PLAY = ["now play", "play ", "put on ", "start playing", "jarvis play"]


def parse_spotify_command(text: str) -> dict | None:
    """Classify a Spotify voice command as stop or play, distinguishing
    "no play X" (stop) from "now play X" / "play X" (play a specific song)."""
    t = text.lower().strip()

    if any(s in t for s in SPOTIFY_STOP):
        return {"action": "pause"}

    for trigger in SPOTIFY_PLAY:
        if trigger in t:
            query = t.split(trigger, 1)[-1].strip()
            query = query.replace("on spotify", "").strip()
            return {"action": "play", "query": query}

    return None


def detect_spotify_command(text: str) -> dict | None:
    """Side-effect-free: returns what handle_spotify_command() *would* do
    without doing it, or None if `text` isn't a Spotify command. Exists so
    callers that only need to know "is this a Spotify command" (e.g.
    server/websocket.py's streaming-bypass check) can ask without risking
    a double next_track()/play() if handle_spotify_command() were called
    twice for the same message."""
    t = text.lower()

    if not spotify.is_connected():
        return None  # let the LLM handle it normally rather than claim music control that isn't set up

    if any(w in t for w in ("next", "skip")):
        return {"kind": "next"}

    if any(w in t for w in ("previous", "last song", "go back")):
        return {"kind": "previous"}

    if "louder" in t or "turn it up" in t:
        return {"kind": "volume_up"}

    if "quieter" in t or "turn it down" in t:
        return {"kind": "volume_down"}

    for mood in _MOOD_QUERIES:
        if mood in t and "music" in t:
            return {"kind": "mood", "mood": mood}

    command = parse_spotify_command(text)
    if command:
        return {"kind": "play_or_pause", "command": command}

    return None


def is_spotify_command(text: str) -> bool:
    return detect_spotify_command(text) is not None


def handle_spotify_command(text: str) -> str | None:
    """Returns a response string if `text` is a Spotify command, else None.
    Detection and execution are split (see detect_spotify_command()) so the
    "is this a match" question can be answered without side effects; this
    function is still the only place that actually calls the mutating
    spotify.* methods."""
    detected = detect_spotify_command(text)
    if not detected:
        return None

    kind = detected["kind"]
    if kind == "next":
        spotify.next_track()
        return "Skipping to next track."
    if kind == "previous":
        spotify.previous_track()
        return "Back to the previous track."
    if kind == "volume_up":
        spotify.set_volume(80)
        return "Volume up."
    if kind == "volume_down":
        spotify.set_volume(30)
        return "Volume down."
    if kind == "mood":
        return _format_play_response(spotify.play_mood(detected["mood"]))
    if kind == "play_or_pause":
        command = detected["command"]
        if command["action"] == "pause":
            spotify.pause()
            return "Music paused."
        return _format_play_response(spotify.play(command["query"]))

    return None


def _format_play_response(result: dict) -> str:
    """Turn a play()/play_mood() result dict into a single confirmed-or-explained
    response — never asks the user to confirm, just plays it and says so, or
    explains exactly why it couldn't (e.g. no active device)."""
    if result.get("playing"):
        track  = result.get("track", "")
        artist = result.get("artist", "")
        device = result.get("device", "your device")
        if track:
            return f"Playing {track}" + (f" by {artist}" if artist else "") + f" on {device}, sir."
        return f"Resuming music on {device}, sir."

    error = result.get("error", "")
    if "No active Spotify device" in error:
        return "No active Spotify device found. Open Spotify on your phone or Mac first, sir."
    return f"Couldn't play that: {error}" if error else "Couldn't play that, sir."
