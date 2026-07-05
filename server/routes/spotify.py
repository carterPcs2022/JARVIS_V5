"""server/routes/spotify.py — full Spotify playback control.
Auth endpoints (/auth, /callback) are unauthenticated by necessity — they're
the OAuth redirect target Spotify itself calls, which can't send our
bearer token. Everything else requires it."""
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from utils.security import verify_token

# Unauthenticated — OAuth redirect endpoints
auth_router = APIRouter(prefix="/stark/spotify", tags=["spotify"])

# Authenticated — playback control
router = APIRouter(prefix="/stark/spotify", tags=["spotify"], dependencies=[Depends(verify_token)])


@auth_router.get("/auth")
def spotify_auth():
    from services.spotify import spotify
    return RedirectResponse(spotify.get_auth_url())


@auth_router.get("/callback")
def spotify_callback(code: str):
    from services.spotify import spotify
    if spotify.exchange_code(code):
        return {"status": "Spotify connected successfully"}
    return {"error": "Authentication failed"}


@router.get("/now")
def spotify_now():
    from services.spotify import spotify
    return spotify.now_playing()


@router.post("/play")
def spotify_play(body: dict | None = None):
    from services.spotify import spotify
    return spotify.play((body or {}).get("query", ""))


@router.post("/pause")
def spotify_pause():
    from services.spotify import spotify
    return spotify.pause()


@router.post("/next")
def spotify_next():
    from services.spotify import spotify
    return spotify.next_track()


@router.post("/previous")
def spotify_previous():
    from services.spotify import spotify
    return spotify.previous_track()


@router.post("/volume")
def spotify_volume(body: dict):
    from services.spotify import spotify
    return spotify.set_volume(body.get("percent", 50))


@router.post("/mood")
def spotify_mood(body: dict):
    from services.spotify import spotify
    return spotify.play_mood(body.get("mood", "focus"))


@router.get("/status")
def spotify_status():
    from services.spotify import spotify
    return {"connected": spotify.is_connected()}
