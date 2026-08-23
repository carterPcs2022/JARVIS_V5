"""server/routes/spotify.py — full Spotify playback control.
Auth endpoints (/auth, /callback) are unauthenticated by necessity — they're
the OAuth redirect target Spotify itself calls, which can't send our
bearer token. Everything else requires it."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
async def spotify_callback(request: Request):
    """Spotify OAuth callback — reads code from query params."""
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        return {"error": f"Spotify auth denied: {error}"}

    if not code:
        # Show all query params for debugging
        params = dict(request.query_params)
        return {
            "error": "No code received",
            "received_params": params,
            "fix": "Check redirect URI matches exactly in Spotify dashboard",
        }

    from services.spotify import spotify
    refresh_token = spotify.exchange_code(code)

    if refresh_token:
        return HTMLResponse(f"""
            <html><body style="background:#040810;color:#00b4ff;
            font-family:monospace;text-align:center;padding:50px">
            <h1>⚡ JARVIS</h1>
            <h2>Spotify Connected Successfully</h2>
            <p>Copy this into <code>SPOTIFY_REFRESH_TOKEN</code> in Render's env vars,
            then redeploy — otherwise this connection won't survive the next one:</p>
            <pre style="white-space:pre-wrap;word-break:break-all">{refresh_token}</pre>
            <p>This page will not show this value again. You can close this window.</p>
            </body></html>
        """)
    return {"error": "Failed to exchange code"}


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
