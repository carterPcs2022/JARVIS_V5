# Railway Deployment Guide

## Setup (5 minutes, no credit card)

1. Go to railway.app
2. Click "Start a New Project"
3. Click "Deploy from GitHub repo"
4. Connect your GitHub account (free)
5. Select your JARVIS_V5 repository
6. Railway auto-detects Python (via `nixpacks.toml`) and starts building

## Add your environment variables

In Railway dashboard → your project → Variables tab.
Add each of these (copy from your local `.env`):

**REQUIRED** (JARVIS won't work without these):
- `GROQ_API_KEY`
- `JARVIS_API_TOKEN` (generate a strong random string)
- `JARVIS_SECRET_KEY` (generate a strong random string)

**OPTIONAL** (enables extra features):
- `ANTHROPIC_API_KEY`
- `OLLAMA_BASE_URL` (only if you have Ollama reachable somewhere)
- `SERPER_API_KEY`, `TAVILY_API_KEY`, `SERPAPI_KEY`
- `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN`
- `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN`
- (add others as you get the API keys — see `.env` for the full list)

**DO NOT ADD:**
- Real passwords
- Bank credentials
- Anything already in `.gitignore`

## Get your public URL

Railway gives you a free URL like:
```
https://jarvis-v5-production.up.railway.app
```

This is your JARVIS URL. Use it everywhere:
- Siri Shortcuts: replace `localhost:8000` with this URL
- FRIDAY's `JARVIS_URL` env var
- Your phone's HUD bookmark (`/hud`)

## Auto-deploys

Every push to GitHub triggers a rebuild:
```bash
git add .
git commit -m "feat: added new feature"
git push
```
Railway rebuilds and redeploys automatically with zero downtime.

## Keep it alive

Railway's free tier doesn't sleep. JARVIS stays online 24/7 as long as you
have free credits ($5/month, resets monthly — running JARVIS costs roughly
$2–4/month). If you run out, add a card or upgrade to the $5/month plan.

## Monitor JARVIS on Railway

The Railway dashboard shows CPU/memory usage, live logs, deployment history,
and request volume.

---

## Also deploy FRIDAY to Railway

Create a **second** Railway service pointed at the `FRIDAY/` folder (or a
separate `FRIDAY` repo).

FRIDAY env vars on Railway:
- `ANTHROPIC_API_KEY`
- `JARVIS_URL=https://your-jarvis-url.up.railway.app`
- `JARVIS_API_TOKEN` (same as JARVIS)
- `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN`

Then update JARVIS's `FRIDAY_URL` env var to point at FRIDAY's Railway URL.
Now both JARVIS and FRIDAY run 24/7, free, monitoring each other with
automatic failover.

## Update Siri Shortcuts

Old URL: `http://localhost:8000/siri/ask`
New URL: `https://your-jarvis-url.up.railway.app/siri/ask`

Railway gives HTTPS automatically:
- Siri Shortcuts work correctly (they prefer HTTPS)
- iPhone microphone works in the HUD (requires HTTPS)
- No certificate setup needed

## Local Mac still works too

```
Railway (cloud, always on)
  JARVIS brain, API, HUD, WebSocket — reachable from anywhere via HTTPS

Your Mac (local, when on)
  python3 app.py → runs local JARVIS with voice input/output (mic + speakers)
  Better for development and testing

iPhone
  Opens https://your-jarvis-url.railway.app/hud
  Siri Shortcuts point at the Railway URL — works even when your Mac is off
```

When running locally (not on Railway), `IS_RAILWAY` is `False` in
`config/settings.py`, which keeps voice input/output, wake word, and
screenshot features enabled. On Railway, those are automatically disabled
since there's no mic, speaker, or display on the server — the API, brain,
and HUD run there instead.

## Test sequence

1. Test locally first:
   ```
   python3 app.py
   curl http://localhost:8000/health   # → OK
   curl http://localhost:8000/          # → JARVIS ONLINE
   ```

2. Push to GitHub:
   ```
   git add . && git commit -m "Railway deployment" && git push
   ```

3. Check Railway build logs for errors.

4. Test the Railway deployment:
   ```
   curl https://your-url.up.railway.app/health
   ```
   Open `https://your-url.up.railway.app/hud` in a browser.

5. Test Siri: update the shortcut URL, say "Hey Siri, ask JARVIS" — should
   work from anywhere, even with your Mac off.

6. Test FRIDAY failover: pause the JARVIS deployment on Railway. FRIDAY
   should detect the outage within 30 seconds. Send it a command — it
   should handle it. Resume JARVIS — FRIDAY should hand back off.
