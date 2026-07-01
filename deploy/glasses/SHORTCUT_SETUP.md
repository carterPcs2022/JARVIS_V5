# JARVIS Ray-Ban Shortcut Setup

## What this does
You speak through the Ray-Ban mic ->
iPhone records in the background ->
Sends the recording to JARVIS on Render ->
JARVIS responds through the Ray-Ban speakers.

## Build the Shortcut (takes 5 minutes)

Open the **Shortcuts** app on iPhone.
Tap **+** to create a new shortcut.

Add these actions IN ORDER:

---
### ACTION 1: "Record Audio"
Search for: **Record Audio**

Settings:
- Start recording when run: **ON**
- Transcribe audio: **OFF**
- Stop recording: **After pause in speech** (or set a fixed time limit, e.g. 10 seconds)

This records your voice through the Ray-Ban mic (paired as the iPhone's audio input over Bluetooth).

---
### ACTION 2: "Get Contents of URL"
Search for: **Get Contents of URL**

- URL: `https://jarvis-v5-sl2y.onrender.com/stark/glasses/listen`
- Method: `POST`
- Headers:
  - `Authorization`: `Bearer YOUR_JARVIS_API_TOKEN`
- Request Body: **Form**
  - Field name: `audio`
  - Value: `[Recorded Audio]` — tap the variable from Action 1

Replace `YOUR_JARVIS_API_TOKEN` with your real `JARVIS_API_TOKEN` value (same one from your `.env`).

This sends your voice to JARVIS on Render, which transcribes it, runs it through the brain, generates a spoken reply, and returns that reply as an audio file directly in the response.

---
### ACTION 3: "Play Sound"
Search for: **Play Sound**

- Input: `[Contents of URL]` from Action 2

This plays JARVIS's voice response through your Ray-Ban speakers via the iPhone's Bluetooth audio connection.

---
### SHORTCUT SETTINGS

- Name: `Hey JARVIS`
- Icon: pick something you like (a circuit board icon fits the theme)
- Color: blue

- Add to Home Screen: **Yes**
- Add to Apple Watch: **Yes**, if you have one

---
### SET UP THE SIRI TRIGGER

Settings -> Siri -> All Shortcuts -> find **Hey JARVIS** -> Add Siri Phrase -> record: **"Hey JARVIS"**

Now saying **"Hey Siri, Hey JARVIS"** runs the shortcut, the glasses mic records, and JARVIS responds through the speakers.

## Making it even smoother

**One-step activation without Siri (Back Tap):**
Settings -> Accessibility -> Touch -> Back Tap -> Double Tap -> select the **Hey JARVIS** shortcut.
Now double-tapping the back of your iPhone (even through a pocket) triggers JARVIS directly.

**iPhone 15 Pro / 16 Action Button:**
Settings -> Action Button -> Shortcut -> **Hey JARVIS**.
One press of the side button triggers JARVIS.

**Ray-Ban frame tap:**
Meta View app -> assign the frame's camera-capture gesture to a Siri Shortcut -> point it at **Hey JARVIS**.
Tapping the glasses frame triggers the Siri phrase, which runs the shortcut.

## Testing

1. Build the shortcut as described above.
2. Run it manually from the Shortcuts app first (tap it directly, don't use Siri yet).
3. Speak clearly: "JARVIS, what time is it?"
4. You should hear JARVIS respond through the glasses speakers within a couple of seconds.
5. Once that works reliably, set up the Siri trigger (or Back Tap / Action Button) for hands-free use.

## Troubleshooting

- **No audio comes back / silence**: check `https://jarvis-v5-sl2y.onrender.com/stark/glasses/status` in a browser — `pipeline_ready` should be `true`. If `elevenlabs` is `false`, it's silently falling back to edge-tts, which still works but sounds different.
- **"I didn't catch that" every time**: the recording is likely too short or silent — check the Record Audio action's stop condition and make sure the Ray-Bans are actually the active microphone (check Bluetooth audio routing in Control Center while recording).
- **401 Unauthorized**: your `Authorization` header token doesn't match `JARVIS_API_TOKEN` on Render — double check both.
- **Long delay before responding**: if Render's free tier put your instance to sleep, the first request after idle time can take ~30 seconds to wake it back up. Set up a free UptimeRobot monitor pinging `/health` every 5 minutes to keep it warm (see the latency notes in the main deployment docs).
