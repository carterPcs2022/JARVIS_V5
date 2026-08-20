"""services/voice.py — TTS + STT service.

TTS cascade:
1. ElevenLabs (cinematic, paid — uses your key)
2. edge-tts (free, neural voice, Microsoft)
3. pyttsx3 (offline, robotic but always works)
"""
import os, re, asyncio, tempfile, wave, subprocess
from config.settings import (
    JARVIS_VOICE, JARVIS_EDGE_VOICE, WHISPER_MODEL, VOICE_ENABLED, IS_RAILWAY,
    PYTTSX3_AVAILABLE,
)


def speak(text: str, play: bool = True, force_engine: str | None = None) -> str:
    """
    Main speak function. Tries engines in priority order.
    force_engine: "elevenlabs" | "edge" | "pyttsx3" | None

    Returns: path to audio file, or "" if all failed.
    """
    if not VOICE_ENABLED or IS_RAILWAY:
        return ""

    if force_engine == "elevenlabs":
        return _speak_elevenlabs(text, play)
    if force_engine == "edge":
        return _speak_edge(text, play)
    if force_engine == "pyttsx3":
        return _speak_pyttsx3(text, play)

    # Auto cascade
    if is_elevenlabs_available():
        result = _speak_elevenlabs(text, play)
        if result:
            return result
        print("[Voice] ElevenLabs failed — falling back to edge-tts")

    result = _speak_edge(text, play)
    if result:
        return result
    print("[Voice] edge-tts failed — falling back to pyttsx3")

    return _speak_pyttsx3(text, play)


def _speak_elevenlabs(text: str, play: bool) -> str:
    from services.elevenlabs_voice import speak_elevenlabs
    return speak_elevenlabs(text, play)


def _speak_edge(text: str, play: bool) -> str:
    """edge-tts fallback."""
    clean = re.sub(r"[*_`#\[\]()]", "", text).strip()
    clean = re.sub(r"\n+", ". ", clean)
    out   = tempfile.mktemp(suffix=".mp3")
    try:
        import edge_tts
        async def _run():
            comm = edge_tts.Communicate(clean, JARVIS_EDGE_VOICE or JARVIS_VOICE)
            await comm.save(out)
        asyncio.run(_run())
        if play:
            _play(out)
        return out
    except Exception as e:
        print(f"[Voice] edge-tts error: {e}")
        return ""


def _speak_pyttsx3(text: str, play: bool) -> str:
    """pyttsx3 offline fallback — local Mac only, needs requirements-local.txt."""
    if not PYTTSX3_AVAILABLE:
        return ""
    clean = re.sub(r"[*_`#\[\]()]", "", text).strip()
    clean = re.sub(r"\n+", ". ", clean)
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 170)
        engine.setProperty("volume", 1.0)
        for v in engine.getProperty("voices"):
            if any(n in v.name.lower() for n in ["david", "alex", "daniel", "male"]):
                engine.setProperty("voice", v.id)
                break
        if play:
            engine.say(clean)
            engine.runAndWait()
        return "pyttsx3"
    except Exception as e:
        print(f"[Voice] pyttsx3 error: {e}")
        return ""


def is_elevenlabs_available() -> bool:
    from services.elevenlabs_voice import is_available
    return is_available()


def voice_engine_status() -> dict:
    """Which TTS engines are available right now."""
    el_ok = is_elevenlabs_available()
    try:
        import edge_tts  # noqa: F401
        edge_ok = True
    except ImportError:
        edge_ok = False
    py_ok = PYTTSX3_AVAILABLE

    active = ("elevenlabs" if el_ok else "edge-tts" if edge_ok else "pyttsx3" if py_ok else "none")

    return {
        "active_engine": active,
        "elevenlabs":    el_ok,
        "edge_tts":      edge_ok,
        "pyttsx3":       py_ok,
        "voice_enabled": VOICE_ENABLED,
        "is_railway":    IS_RAILWAY,
    }


def _play(path: str):
    if not os.path.exists(path): return
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        return
    except Exception: pass
    # list-args subprocess.run (no shell=True) instead of the previous
    # os.system(f"afplay '{path}' ... || aplay '{path}' ...") — `path` is
    # always internally generated (tempfile.mktemp()) today, not
    # attacker-controlled, but os.system+f-string is a command-injection
    # anti-pattern regardless of current call sites; same fix already
    # applied to core/tools/{system,mac}.py. Tries afplay first, falls
    # back to aplay on failure or if it isn't installed, same as the
    # original shell `||`.
    for player in ("afplay", "aplay"):
        try:
            result = subprocess.run([player, path], capture_output=True)
            if result.returncode == 0:
                return
        except FileNotFoundError:
            continue

def listen(seconds: int = 6) -> str:
    try:
        import pyaudio
        CHUNK, FORMAT, CHAN, RATE = 1024, 8, 1, 16000  # paInt16=8
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHAN, rate=RATE, input=True, frames_per_buffer=CHUNK)
        frames = [stream.read(CHUNK) for _ in range(int(RATE/CHUNK*seconds))]
        stream.stop_stream(); stream.close(); p.terminate()
        tmp = tempfile.mktemp(suffix=".wav")
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(CHAN); wf.setsampwidth(2); wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))
        return transcribe(tmp)
    except Exception as e:
        return f"[Listen error: {e}]"

def transcribe(path: str) -> str:
    """Transcribe audio. Prefers local faster-whisper; falls back to Groq's
    hosted Whisper API — the fallback is what actually runs in production
    since faster-whisper is too heavy for a free-tier host like Render.

    This is the single shared implementation used by both the glasses
    pipeline (server/routes/glasses.py) and the browser HUD's transcribe
    endpoint (server/routes/voice.py) — don't fork a second copy of this
    "prefer local, fall back to Groq" logic."""
    from config.settings import IS_RENDER, FASTER_WHISPER_AVAILABLE
    if IS_RENDER or not FASTER_WHISPER_AVAILABLE:
        return transcribe_groq(path)
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path, beam_size=5)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text if text else transcribe_groq(path)
    except Exception as e:
        print(f"[Voice] Local transcription error: {e}")
        return transcribe_groq(path)



# Whisper's `prompt` param biases transcription toward expected vocabulary —
# it's not a system prompt/instruction, just example text in the style/
# terms you expect, which measurably cuts mishears on proper nouns a
# general-purpose model has no reason to prefer over a similar-sounding
# common word. Real names/terms that actually appear in this assistant's
# own domain, not invented filler. Zero added latency (same request),
# no new dependency.
_TRANSCRIBE_PROMPT_HINT = (
    "JARVIS, FRIDAY, Groq, Anthropic, Claude, Sentinel, combat mode, "
    "Mark, Stark, Resemblyzer, Whisper."
)


def transcribe_groq(path: str) -> str:
    """Transcribe using Groq's hosted Whisper API (free tier: 7,200s/day)."""
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(path), f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en",
                prompt=_TRANSCRIBE_PROMPT_HINT,
            )
        return str(transcription).strip()
    except Exception as e:
        print(f"[Voice] Groq transcription error: {e}")
        return f"[Transcribe error: {e}]"


# ── Audio Signature Alerts ─────────────────────────────────────────────────────

SOUND_SIGNATURES = {
    "boot":     [(261, 80), (330, 80), (392, 80), (523, 160)],  # C4→E4→G4→C5
    "alert":    [(440, 120), (0, 60), (440, 120)],               # A4 two-tone
    "critical": [(440, 60)] * 5,                                  # rapid A4 pulse
    "success":  [(392, 120), (523, 200)],                         # G4→C5 resolution
    "scatter":  [(523, 80), (392, 80), (330, 80), (261, 160)],   # C5→G4→E4→C4 descending
    "online":   [(261, 60), (330, 60), (392, 60), (440, 60), (523, 120)],
    "offline":  [(523, 80), (440, 80), (392, 80), (330, 80), (261, 160)],
    "handoff":  [(330, 100), (440, 100)],
}


def _make_tone(freq: int, duration_ms: int, sample_rate: int = 22050) -> bytes:
    """Generate a sine wave tone as 16-bit PCM bytes."""
    import math, struct
    n_samples = int(sample_rate * duration_ms / 1000)
    if freq == 0:
        return b"\x00\x00" * n_samples
    samples = []
    for i in range(n_samples):
        val = int(32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        # Envelope: fade in/out over 10ms to avoid clicks
        fade = min(1.0, i / (sample_rate * 0.01), (n_samples - i) / (sample_rate * 0.01))
        samples.append(struct.pack("<h", int(val * fade)))
    return b"".join(samples)


def play_signature(event: str):
    """Play an audio signature for a system event. Non-blocking."""
    notes = SOUND_SIGNATURES.get(event)
    if not notes:
        return
    try:
        import pygame, numpy as np
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        pcm = b"".join(_make_tone(freq, dur) for freq, dur in notes)
        arr = np.frombuffer(pcm, dtype=np.int16)
        sound = pygame.sndarray.make_sound(arr)
        sound.play()
    except Exception:
        pass  # Audio optional — never crash on missing pygame/numpy
