"""core/tools/spotify.py — Spotify control via AppleScript."""
from core.tools.mac import run_applescript, open_app, is_app_running


def _ensure_open() -> bool:
    if not is_app_running("Spotify"):
        r = open_app("Spotify")
        if not r["ok"]:
            return False
        import time; time.sleep(2)
    return True


def current_track() -> dict:
    if not is_app_running("Spotify"):
        return {"ok": False, "message": "Spotify is not running"}
    # Single AppleScript call avoids multiple round-trips and timeouts
    script = '''
        tell application "Spotify"
            set t to name of current track
            set a to artist of current track
            set al to album of current track
            set s to player state as string
            return t & "|" & a & "|" & al & "|" & s
        end tell
    '''
    raw = run_applescript(script)
    if raw.startswith("[AppleScript"):
        return {"ok": False, "message": f"Spotify not responding: {raw}"}
    parts  = raw.split("|")
    track  = parts[0].strip() if len(parts) > 0 else "Unknown"
    artist = parts[1].strip() if len(parts) > 1 else "Unknown"
    album  = parts[2].strip() if len(parts) > 2 else ""
    state  = parts[3].strip() if len(parts) > 3 else "unknown"
    return {
        "ok":     True,
        "track":  track,
        "artist": artist,
        "album":  album,
        "state":  state,
        "message": f"Now {'playing' if state == 'playing' else 'paused'}: {track} by {artist}",
    }


def play() -> dict:
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    run_applescript('tell application "Spotify" to play')
    return {"ok": True, "message": "Spotify playing"}


def pause() -> dict:
    if not is_app_running("Spotify"): return {"ok": False, "message": "Spotify not running"}
    run_applescript('tell application "Spotify" to pause')
    return {"ok": True, "message": "Spotify paused"}


def play_pause() -> dict:
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    run_applescript('tell application "Spotify" to playpause')
    state = run_applescript('tell application "Spotify" to player state as string')
    return {"ok": True, "message": f"Spotify {state}"}


def next_track() -> dict:
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    run_applescript('tell application "Spotify" to next track')
    import time; time.sleep(0.5)
    return current_track()


def prev_track() -> dict:
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    run_applescript('tell application "Spotify" to previous track')
    import time; time.sleep(0.5)
    return current_track()


def set_volume(level: int) -> dict:
    level = max(0, min(100, int(level)))
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    run_applescript(f'tell application "Spotify" to set sound volume to {level}')
    return {"ok": True, "message": f"Spotify volume set to {level}%"}


def search_and_play(query: str) -> dict:
    """Search Spotify and play the first result via URI search."""
    if not _ensure_open(): return {"ok": False, "message": "Could not open Spotify"}
    safe = query.replace('"', '\\"')
    # Open Spotify search URI — Spotify handles the search natively
    import subprocess
    uri = f"spotify:search:{query.replace(' ', '%20')}"
    subprocess.run(["open", uri], timeout=5)
    import time; time.sleep(1)
    return {"ok": True, "message": f"Searched Spotify for: {query}"}


def get_state() -> str:
    if not is_app_running("Spotify"):
        return "stopped"
    return run_applescript('tell application "Spotify" to player state as string')
