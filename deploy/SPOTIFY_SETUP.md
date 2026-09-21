# Spotify Setup

## Requirements
Requires a **Spotify Premium** account — the Web API's playback-control
endpoints (`/play`, `/pause`, `/next`, `/volume`, etc.) return 403 for free
accounts. Playback also has to already be active on some device (phone,
desktop app, speaker) — Spotify's API controls existing playback, it
doesn't start audio out of nowhere on a device with nothing open.

## Setup
1. Go to [developer.spotify.com](https://developer.spotify.com/dashboard).
2. Create an app — name it JARVIS (or anything).
3. Add a redirect URI:
   - Local: `http://127.0.0.1:8000/stark/spotify/callback`
   - Render: `https://jarvis-v5-sl2y.onrender.com/stark/spotify/callback`
4. Copy the Client ID and Client Secret into `.env`:
   ```
   SPOTIFY_CLIENT_ID=...
   SPOTIFY_CLIENT_SECRET=...
   SPOTIFY_REDIRECT_URI=https://jarvis-v5-sl2y.onrender.com/stark/spotify/callback
   ```
   (For Render, use the HTTPS URI above exactly. Spotify requires an exact match and does not allow `localhost`.)
5. Restart JARVIS.
6. Open `/stark/spotify/auth` in a browser and approve.
7. Done — say "JARVIS play some focus music."

## Voice commands that work
```
"JARVIS play some focus music"
"JARVIS play [song name]"
"JARVIS pause the music"
"JARVIS next song"
"JARVIS turn it up" / "JARVIS turn it down"
"JARVIS play something relaxing"
"JARVIS coding music" / "JARVIS happy music"
"JARVIS stop the music"
```
These are matched by keyword in `services/spotify.handle_spotify_command()`
and answered instantly — no LLM call, checked before the brain pipeline in
`core/brain_v2.py`.

## Notes
- No `spotipy` dependency needed — this integration talks to the Spotify
  Web API directly over `httpx` (already a project dependency).
- The refresh token is stored in `memory/spotify_token.json`, which
  persists across restarts. If playback commands start failing with "Not
  authenticated", re-run the auth flow (step 6).
