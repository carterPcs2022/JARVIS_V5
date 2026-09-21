"""services/spotify.py — full Spotify playback control via the raw Web API
(no spotipy dependency needed — httpx + the OAuth endpoints directly)."""
import os
import time
import json
import hashlib
import hmac
import logging
import secrets
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from config.settings import BASE_DIR

log = logging.getLogger(__name__)

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8000/stark/spotify/callback",
).strip()
_OAUTH_STATE_TTL = 600

def _validated_redirect_uri() -> str:
    """Return a Spotify-acceptable redirect URI and reject unsafe production config."""
    uri = REDIRECT_URI.strip()
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    cloud = bool(
        os.getenv("RENDER")
        or os.getenv("RENDER_SERVICE_ID")
        or os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("RAILWAY_ENVIRONMENT")
    )

    if not uri or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("SPOTIFY_REDIRECT_URI is missing or invalid.")

    if host == "localhost":
        raise RuntimeError(
            "SPOTIFY_REDIRECT_URI uses localhost, which Spotify no longer allows. "
            "Use an HTTPS Render callback in production or 127.0.0.1 for local development."
        )

    if cloud and parsed.scheme != "https":
        raise RuntimeError(
            "SPOTIFY_REDIRECT_URI must use HTTPS in cloud deployments."
        )

    return uri

def _make_oauth_state() -> str:
    """Create a short-lived signed OAuth state value without storing session data."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{timestamp}.{nonce}"
    signature = hmac.new(
        CLIENT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"

def validate_oauth_state(state: str | None) -> bool:
    """Validate a signed OAuth state value and reject expired/tampered values."""
    if not state or not CLIENT_SECRET:
        return False
    parts = state.split(".", 2)
    if len(parts) != 3:
        return False
    timestamp, nonce, signature = parts
    try:
        issued = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - issued) > _OAUTH_STATE_TTL:
        return False
    payload = f"{timestamp}.{nonce}"
    expected = hmac.new(
        CLIENT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

# Same durability gap Calendar OAuth already solved (see
# server/routes/calendar_auth.py): the access/refresh token pair only ever
# lived in TOKEN_FILE, which is on Render's ephemeral filesystem and is
# gitignored on top of that — so it silently disappeared on every redeploy,
# forcing a re-auth through /stark/spotify/auth each time. This env var is
# the same fallback seed Calendar uses: set once from the value
# /stark/spotify/callback prints after a real auth, it survives redeploys
# even though TOKEN_FILE itself doesn't.
SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN", "")
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
        # TOKEN_FILE doesn't survive a redeploy; SPOTIFY_REFRESH_TOKEN does.
        # expires_at 0 forces _get_access_token() to refresh immediately,
        # which re-populates TOKEN_FILE for the rest of this process's life.
        if SPOTIFY_REFRESH_TOKEN:
            return {"refresh_token": SPOTIFY_REFRESH_TOKEN, "access_token": "", "expires_at": 0}
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
            "user-read-currently-playing playlist-read-private "
            "playlist-read-collaborative"
        )
        redirect_uri = _validated_redirect_uri()
        params = {
            "client_id": CLIENT_ID, "response_type": "code",
            "redirect_uri": redirect_uri, "scope": scopes,
            "state": _make_oauth_state(),
        }
        return f"https://accounts.spotify.com/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> str | None:
        """Returns the refresh_token on success (so the caller can show it
        once, the same way calendar_auth.py's /callback does — see
        SPOTIFY_REFRESH_TOKEN above), or None on failure."""
        try:
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": _validated_redirect_uri(), "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                timeout=10,
            )
            data = r.json()
            if "access_token" not in data:
                log.warning("Spotify code exchange failed: %s", data)
                return None
            self._save_token({
                "access_token": data["access_token"], "refresh_token": data["refresh_token"],
                "expires_at": time.time() + data["expires_in"],
            })
            return data["refresh_token"]
        except Exception as e:
            log.warning("Spotify code exchange error: %s", e)
            return None

    def now_playing(self) -> dict:
        return self._api("GET", "/me/player/currently-playing")

    def get_playlists(self) -> list:
        """Return the user's Spotify playlists, including private ones."""
        token = self._get_access_token()
        if not token:
            return []
        playlists = []
        offset = 0
        try:
            while True:
                r = httpx.get(
                    "https://api.spotify.com/v1/me/playlists",
                    params={"limit": 50, "offset": offset},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                if r.status_code >= 400:
                    log.warning("Spotify playlist lookup failed: %s", r.text)
                    return playlists
                data = r.json()
                items = data.get("items", [])
                playlists.extend(
                    {
                        "id": item.get("id", ""),
                        "name": item.get("name", ""),
                        "uri": item.get("uri", ""),
                        "url": (item.get("external_urls") or {}).get("spotify", ""),
                    }
                    for item in items if item.get("id") and item.get("uri")
                )
                if not data.get("next") or not items:
                    break
                offset += len(items)
            return playlists
        except Exception as e:
            log.warning("Spotify playlist lookup error: %s", e)
            return playlists

    @staticmethod
    def _normalize_playlist_name(value: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def find_playlist(self, query: str) -> dict | None:
        """Find the closest match among the user's playlists."""
        import difflib
        wanted = self._normalize_playlist_name(query)
        if not wanted:
            return None
        playlists = self.get_playlists()
        for playlist in playlists:
            if self._normalize_playlist_name(playlist["name"]) == wanted:
                return playlist
        for playlist in playlists:
            name = self._normalize_playlist_name(playlist["name"])
            if wanted in name or name in wanted:
                return playlist
        best, best_score = None, 0.0
        for playlist in playlists:
            name = self._normalize_playlist_name(playlist["name"])
            score = difflib.SequenceMatcher(None, wanted, name).ratio()
            if score > best_score:
                best, best_score = playlist, score
        return best if best_score >= 0.72 else None

    def play_playlist(self, query: str, device_id: str | None = None) -> dict:
        """Play one of the user's playlists on an active Spotify device."""
        token = self._get_access_token()
        if not token:
            return {"error": "Not authenticated"}
        playlist = self.find_playlist(query)
        if not playlist:
            return {"error": f"Couldn't find your playlist: {query}"}
        devices = self._get_devices()
        if not devices:
            return {"error": "No active Spotify device found",
                    "fix": "Open Spotify on your iPhone first so Spotify exposes it as a Connect device."}
        if device_id:
            device = next((d for d in devices if d.get("id") == device_id), None)
            if device is None:
                return {"error": "The selected Spotify device is no longer available. Open Spotify on your iPhone and try again."}
        else:
            device = devices[0]
        resp = self._api(
            "PUT", "/me/player/play",
            data={"context_uri": playlist["uri"]},
            params={"device_id": device["id"]},
        )
        if "error" in resp:
            return resp
        return {"playing": True, "playlist": playlist["name"],
                "device": device.get("name", "your device")}

    def play(self, query: str = "", device_id: str | None = None) -> dict:
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
                "fix": "Open Spotify on your iPhone first so Spotify exposes it as a Connect device.",
            }

        if device_id:
            device = next((d for d in devices if d.get("id") == device_id), None)
            if device is None:
                return {"error": "The selected Spotify device is no longer available. Open Spotify on your iPhone and try again."}
        else:
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

    def get_devices(self) -> list:
        """Return safe Spotify Connect devices suitable for a user choice UI."""
        return self._get_devices()

    def _get_devices(self) -> list:
        """List available Spotify Connect devices, preferring the user's iPhone.

        JARVIS runs remotely, so it cannot play audio itself. Spotify's Web API
        sends playback to a Spotify Connect device owned by the user. Prefer
        an active smartphone, then any smartphone, then another active device.
        This keeps JARVIS from accidentally targeting an old Mac or speaker.
        """
        resp = self._api("GET", "/me/player/devices")
        if "error" in resp:
            return []

        devices = [
            d for d in resp.get("devices", [])
            if d.get("id") and not d.get("is_restricted")
        ]

        # Phone-first: the user's current setup is iPhone-only.
        smartphones = [d for d in devices if str(d.get("type", "")).lower() == "smartphone"]
        active = [d for d in smartphones if d.get("is_active")]
        if active:
            return active + [d for d in smartphones if d not in active]

        if smartphones:
            return smartphones + [d for d in devices if d not in smartphones and d.get("is_active")]

        # No phone was exposed by Spotify; only use an already-active fallback
        # rather than waking up an arbitrary remembered device.
        return [d for d in devices if d.get("is_active")]

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

    if "playlist" in t and (
        "my playlist" in t
        or "playlist called" in t
        or "playlist named" in t
        or ("play " in t and t.endswith("playlist"))
    ):
        query = t
        for marker in ("playlist called", "playlist named", "my playlist"):
            query = query.replace(marker, " ")
        query = query.replace("on spotify", " ").replace("play", " ").strip()
        query = query.removesuffix(" playlist").strip()
        return {"action": "playlist", "query": query}

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

    # Always claim explicit Spotify commands here. If OAuth is unavailable,
    # handle_spotify_command() returns a clear setup/auth message instead of
    # falling through to the legacy Mac dispatcher (which cannot reach the
    # user's iPhone).
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
    """Execute a Spotify command, asking the user to choose a device when needed."""
    detected = detect_spotify_command(text)
    if not detected:
        return None

    if not spotify.is_connected():
        return "Spotify isn't connected to JARVIS yet, sir. Visit /stark/spotify/auth to connect it."

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

    command = detected.get("command", {})
    if kind in ("playlist", "play_or_pause") and command.get("action") == "pause":
        spotify.pause()
        return "Music paused."

    if kind not in ("playlist", "play_or_pause"):
        return None

    query = command.get("query", "")
    devices = spotify.get_devices()
    if not devices:
        return _format_play_response({"error": "No active Spotify device found"})

    if len(devices) > 1:
        from core.ask_user_choice import annotate_pending, propose
        options = [d.get("name", "Unnamed Spotify device") for d in devices]
        pending = propose([{
            "question": "Which Spotify device should I use?",
            "options": options,
            "allow_multiple": False,
        }])
        if pending:
            annotate_pending({
                "action": "spotify_device_selection",
                "spotify_command": command,
                "device_ids": {name: d["id"] for name, d in zip(options, devices)},
            })
            return "I found multiple Spotify devices. Which one should I use, sir?"

    device_id = devices[0]["id"]
    if kind == "playlist":
        return _format_play_response(spotify.play_playlist(query, device_id=device_id))
    return _format_play_response(spotify.play(query, device_id=device_id))


def _format_play_response(result: dict) -> str:
    """Turn a play()/play_mood() result dict into a single confirmed-or-explained
    response — never asks the user to confirm, just plays it and says so, or
    explains exactly why it couldn't (e.g. no active device)."""
    if result.get("playing"):
        if result.get("playlist"):
            return f"Playing your {result['playlist']} playlist on {result.get('device', 'your device')}, sir."
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
