"""server/routes/calendar_auth.py — one-time Google Calendar OAuth consent
flow. Not gated behind verify_token: Google's redirect back to /callback
carries no Authorization header, so bearer auth can't apply to it — a
random `state` nonce (standard OAuth CSRF protection) is the actual guard
here instead, checked against what /auth generated for this process.

Render's disk is ephemeral, so nothing here writes a token to a file —
/callback shows the refresh token once in the response; copy it into
GOOGLE_CALENDAR_REFRESH_TOKEN in Render's env vars and redeploy. This is a
manual, run-once-by-a-human setup step, not something the app repeats.
"""
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config.settings import (
    GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_REDIRECT_URI,
)

router = APIRouter(prefix="/stark/calendar", tags=["calendar-auth"])

_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
# gmail.send added for core/tools/gmail_send.py's draft-then-confirm email
# flow — the minimum scope for sending only (not gmail.compose, which also
# manages Gmail's own Drafts resource; the "draft" here is JARVIS's own
# pending-confirmation object, not a real Gmail draft). Requesting both
# scopes in one consent screen means one refresh token covers both — a
# fresh consent click-through is unavoidable either way, since a refresh
# token is bound to whatever scopes were actually granted when issued and
# the existing one only ever covered calendar.
_SCOPE = "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/gmail.send"

# Single-process, single-user setup flow — an in-memory nonce is enough;
# no need for persistence across restarts for a flow that completes in the
# same browser session it started in.
_pending_state: str | None = None


@router.get("/auth")
def calendar_auth():
    global _pending_state
    if not (GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_REDIRECT_URI):
        return HTMLResponse(
            "<p>GOOGLE_CALENDAR_CLIENT_ID / GOOGLE_CALENDAR_REDIRECT_URI not set.</p>",
            status_code=400,
        )

    _pending_state = secrets.token_urlsafe(24)
    params = {
        "client_id":     GOOGLE_CALENDAR_CLIENT_ID,
        "redirect_uri":  GOOGLE_CALENDAR_REDIRECT_URI,
        "response_type": "code",
        "scope":         _SCOPE,
        "access_type":   "offline",   # required to get a refresh_token back
        "prompt":        "consent",   # forces refresh_token even on repeat auth
        "state":         _pending_state,
    }
    return RedirectResponse(f"{_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def calendar_callback(request: Request):
    global _pending_state
    error = request.query_params.get("error")
    if error:
        return HTMLResponse(f"<p>Google returned an error: {error}</p>", status_code=400)

    code  = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        return HTMLResponse("<p>Missing ?code from Google.</p>", status_code=400)
    if not state or state != _pending_state:
        return HTMLResponse(
            "<p>State mismatch — this callback didn't originate from a /stark/calendar/auth "
            "redirect from this server process. Visit /stark/calendar/auth again.</p>",
            status_code=400,
        )
    _pending_state = None  # one-time use

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_TOKEN_URL, data={
                "code":          code,
                "client_id":     GOOGLE_CALENDAR_CLIENT_ID,
                "client_secret": GOOGLE_CALENDAR_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_CALENDAR_REDIRECT_URI,
                "grant_type":    "authorization_code",
            })
        if resp.status_code >= 400:
            # raise_for_status()'s exception text is just the status code —
            # Google's actual error/error_description (redirect_uri_mismatch,
            # invalid_client, invalid_grant, etc.) is in the response body,
            # which is the only thing that actually tells us what to fix.
            return HTMLResponse(
                f"<p>Token exchange failed ({resp.status_code}):</p><pre>{resp.text}</pre>",
                status_code=502,
            )
        tokens = resp.json()
    except Exception as e:
        return HTMLResponse(f"<p>Token exchange failed: {e}</p>", status_code=502)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        # Google only issues a refresh_token on first consent (or with
        # prompt=consent, which /auth already sets) — if this happens,
        # the account likely already has an active grant for this exact
        # client; revoke access at myaccount.google.com/permissions and
        # retry /stark/calendar/auth.
        return HTMLResponse(
            "<p>No refresh_token in Google's response — the account may already have an "
            "active grant for this app. Revoke it at "
            "<a href='https://myaccount.google.com/permissions'>myaccount.google.com/permissions</a> "
            "and try /stark/calendar/auth again.</p>",
            status_code=400,
        )

    return HTMLResponse(
        "<p>Connected. Copy this into <code>GOOGLE_CALENDAR_REFRESH_TOKEN</code> in Render's "
        f"env vars, then redeploy:</p><pre>{refresh_token}</pre>"
        "<p>This page will not show this value again.</p>"
    )
