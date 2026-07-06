"""services/wakeword.py — local "Hey JARVIS" wake-word detection.

Runs only on a local Mac with a real microphone (requirements-local.txt +
`sounddevice`). Records short chunks continuously, transcribes each via
Groq's hosted Whisper (same API server/routes/glasses.py falls back to),
and fires a callback when the wake phrase is heard. Never transmits audio
anywhere except the Groq transcription call already used elsewhere for voice.
"""
from __future__ import annotations

import logging
import os
import threading

from config.settings import ENVIRONMENT

log = logging.getLogger(__name__)

WAKEWORD = os.getenv("JARVIS_WAKEWORD", "hey jarvis").lower()
_SAMPLE_RATE = 16000
_CHUNK_SECONDS = 2


class WakeWordDetector:

    def __init__(self):
        self._listening = False
        self._callback = None
        self._thread: threading.Thread | None = None

    def start(self, callback) -> None:
        """Start listening for the wake word. No-op off a local Mac (no mic)."""
        if ENVIRONMENT != "local":
            return
        self._callback = callback
        self._listening = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="jarvis-wakeword")
        self._thread.start()
        log.info("Listening for wake word '%s'", WAKEWORD)

    def stop(self) -> None:
        self._listening = False

    def _listen_loop(self) -> None:
        try:
            import sounddevice as sd
            import numpy as np
            import tempfile
            import wave
        except ImportError:
            log.warning("sounddevice not installed — run: pip install -r requirements-local.txt")
            return

        while self._listening:
            try:
                audio = sd.rec(int(_CHUNK_SECONDS * _SAMPLE_RATE), samplerate=_SAMPLE_RATE, channels=1, dtype=np.int16)
                sd.wait()

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    with wave.open(tmp.name, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(_SAMPLE_RATE)
                        wf.writeframes(audio.tobytes())
                    tmp_path = tmp.name

                transcript = self._transcribe(tmp_path)
                os.unlink(tmp_path)

                if transcript and WAKEWORD in transcript.lower():
                    log.info("Wake word detected: %s", transcript)
                    if self._callback:
                        self._callback()
            except Exception as e:
                log.debug("Wake word listen loop error: %s", e)

    def _transcribe(self, audio_path: str) -> str:
        try:
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            with open(audio_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), f.read()),
                    model="whisper-large-v3-turbo",
                    response_format="text",
                )
            return str(result).strip().lower()
        except Exception as e:
            log.debug("Wake word transcription failed: %s", e)
            return ""


wakeword = WakeWordDetector()
