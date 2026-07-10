# Helmet HUD — Methods B & C

For voice-only through the Ray-Bans (Method A — mic in, speaker out,
"Hey JARVIS" hands-free), see [SHORTCUT_SETUP.md](SHORTCUT_SETUP.md) —
that's already built and this doc doesn't repeat it.

This one covers the two additions: a glanceable HUD on the phone screen
while wearing the glasses, and photo-based computer vision analysis.

## Method B — Phone as HUD

The Ray-Bans show you the world; the phone in your hand (or a glance down
at your pocket) shows JARVIS's overlay.

1. Open Safari on iPhone.
2. Go to: `https://jarvis-v5-sl2y.onrender.com/hud/helmet_mobile`
3. Share → Add to Home Screen → name it "JARVIS HUD".
4. Open it from the home screen — it launches full-screen, no Safari
   chrome (the `apple-mobile-web-app-capable` meta tag handles that).
5. Tap anywhere on the screen to start a voice exchange (or use the 🎤
   button) — JARVIS responds through whatever's playing audio, which is
   the Ray-Ban speakers if they're the active Bluetooth output.
6. The camera defaults to the rear lens (unlike the Mac version, which
   defaults to the front-facing webcam) — point the phone at whatever
   the glasses are looking at, or use it independently.

The 🔍 SCAN button captures the current camera frame and runs a quick
threat assessment through `/stark/glasses/threat` — genuinely functional,
not decorative: it calls real computer vision (see Method C).

## Method C — Glasses live-frame analysis

The Ray-Ban Meta app can capture a photo through the glasses. Point the
glasses at something and have JARVIS actually look at it and describe
it — this is the part that needs its own iPhone Shortcut, separate from
the voice one in SHORTCUT_SETUP.md.

### Shortcut: "JARVIS analyze this"

1. Shortcuts app → **+** → new shortcut.
2. **Action 1 — Take Photo** (or "Select Photos" pointed at the last
   camera roll item, if you're capturing through the Meta View app
   instead of the iPhone camera directly).
3. **Action 2 — Get Contents of URL**
   - URL: `https://jarvis-v5-sl2y.onrender.com/stark/glasses/analyze`
   - Method: `POST`
   - Headers: `Authorization: Bearer YOUR_JARVIS_API_TOKEN`
   - Request Body: **Form** → field name `image`, value the photo from
     Action 1.
4. **Action 3 — Get Dictionary from Input**, then **Get Dictionary
   Value** for key `brief`.
5. **Action 4 — Speak Text**, input the value from Action 3.

Name it "JARVIS analyze this", add a Siri phrase the same way as the
voice shortcut. The response also plays through
`/stark/glasses/audio` (same endpoint the voice pipeline uses) if you'd
rather route it through JARVIS's actual voice instead of iOS's built-in
speech synthesis — swap Action 4 for another "Get Contents of URL"
against that endpoint and a "Play Sound" action, same pattern as
SHORTCUT_SETUP.md's Action 3.

### Shortcut: "JARVIS scan threats"

Same shape, pointed at `/stark/glasses/threat` instead. Reads back
`assessment` instead of `brief`.

### What's actually happening server-side

`/stark/glasses/analyze` and `/stark/glasses/threat` both go through
`core.tools.vision.analyze()` — a real multimodal call (Groq's LLaVA
model sees the actual image), not just a text prompt describing what a
photo might contain. `analyze_frame()` additionally speaks a
one-sentence summary through the existing TTS cascade so you don't have
to read anything.

### Endpoints

| Endpoint | What it does |
|---|---|
| `POST /stark/glasses/analyze` | Full scene description + one-sentence spoken summary |
| `POST /stark/glasses/threat` | Quick CLEAR/CAUTION/THREAT assessment, alerts on THREAT |
| `POST /stark/glasses/identify` | Describes a visible person (age range, demeanor, activity) — never attempts name identification |
| `GET /stark/glasses/hud_text` | Ultra-brief status string (~60 chars) formatted for the glasses' own tiny in-lens display |

## Testing

1. Open `/hud/helmet` on a Mac browser first — confirm the camera feed,
   voice button, and SCAN button all work before touching the phone
   version. SCAN needs the camera enabled first.
2. Build the "JARVIS analyze this" shortcut and run it manually (not via
   Siri yet) pointed at something ordinary — a desk, a room — and confirm
   you get a real description back, not a generic non-answer.
3. Point it at something the CLEAR/CAUTION/THREAT scan should flag
   differently and confirm the assessment actually changes.
