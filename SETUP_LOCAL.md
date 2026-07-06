# Running JARVIS locally with full voice

Render only installs `requirements.txt`, which deliberately excludes
`pyttsx3` and `faster-whisper` — both need real audio hardware and would
fail a Render build.

To get full local voice (offline TTS fallback + local Whisper STT) on your
Mac:

```bash
pip install -r requirements-local.txt
```

Render always uses `requirements.txt` automatically — no action needed
there.
