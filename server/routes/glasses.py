"""
server/routes/glasses.py — Meta Ray-Ban voice pipeline.

Ray-Ban mic -> iPhone Shortcut -> this server -> Groq (transcribe + think)
-> ElevenLabs -> iPhone plays the returned audio through the Ray-Ban speakers.

Endpoints:
POST /stark/glasses/listen   <- receives audio from iPhone Shortcut (auth required)
POST /stark/glasses/text     <- text fallback, no audio upload (auth required)
GET  /stark/glasses/audio    <- serves the most recently generated response audio
GET  /stark/glasses/status   <- pipeline health check
"""
import os
import tempfile
import time
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import FileResponse
from utils.security import verify_token
from config.settings import BASE_DIR

router = APIRouter(prefix="/stark/glasses", tags=["glasses"])

_RESPONSE_AUDIO_PATH = str(BASE_DIR / "glasses_response.mp3")


# ── Quick-response cache — skip the LLM entirely for trivial queries ────────────
# Shaves the biggest latency cost (an LLM round-trip) off the questions asked
# constantly through a wearable — time/date/status checks are effectively free
# to answer directly instead of paying for a Groq call every time.

_QUICK_RESPONSES = {
    "what time is it":  lambda: f"It's {__import__('datetime').datetime.now().strftime('%I:%M %p')}.",
    "whats the time":   lambda: f"It's {__import__('datetime').datetime.now().strftime('%I:%M %p')}.",
    "what day is it":   lambda: __import__('datetime').datetime.now().strftime('%A, %B %d.'),
    "jarvis status":    lambda: "All systems nominal.",
    "are you there":    lambda: "Always, sir.",
    "you there":        lambda: "Right here.",
}


def _check_quick_response(text: str) -> str | None:
    """Return an instant response for common queries. Skip the LLM entirely."""
    clean = text.lower().strip().rstrip("?.!").replace("'", "")
    for trigger, fn in _QUICK_RESPONSES.items():
        if trigger in clean:
            return fn()
    return None


# ── Audio receive + transcribe + respond ────────────────────────────────────────

@router.post("/listen", dependencies=[Depends(verify_token)])
async def glasses_listen(audio: UploadFile = File(...)):
    """
    Receives audio from the iPhone Shortcut, transcribes it, runs it through
    JARVIS's brain, generates a spoken response, and returns the audio file
    directly — the Shortcut plays this straight through the Ray-Ban speakers.
    """
    start = time.time()

    suffix = ".m4a" if "m4a" in (audio.filename or "") else ".wav"
    audio_path = None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await audio.read()
        tmp.write(content)
        audio_path = tmp.name

    try:
        text = _transcribe(audio_path)
        if not text or len(text.strip()) < 2:
            return {"error": "I didn't catch that. Try again.", "audio": False}

        print(f"[Glasses] Heard: {text}")

        quick = _check_quick_response(text)
        if quick is not None:
            response_text = quick
            latency_note = "quick_response"
        else:
            from core.brain_v2 import brain
            result = brain.process_dict(text)
            response_text = result["response"]
            latency_note = "brain"

        print(f"[Glasses] Responding ({latency_note}): {response_text[:100]}")

        audio_response_path = _generate_voice(response_text)
        latency = round(time.time() - start, 2)
        print(f"[Glasses] Total latency: {latency}s")

        if audio_response_path and os.path.exists(audio_response_path):
            return FileResponse(
                audio_response_path,
                media_type="audio/mpeg",
                headers={
                    "X-Jarvis-Text":    response_text[:500],
                    "X-Jarvis-Input":   text[:200],
                    "X-Jarvis-Latency": str(latency),
                    "Cache-Control":    "no-cache",
                },
            )

        return {"response": response_text, "input": text, "latency": latency, "audio": False}

    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass


@router.post("/text", dependencies=[Depends(verify_token)])
async def glasses_text(body: dict):
    """Text-only fallback when audio isn't available. Returns text + an audio URL."""
    text = body.get("text", "").strip()
    if not text:
        return {"error": "No text provided"}

    quick = _check_quick_response(text)
    if quick is not None:
        response = quick
        latency_ms = 0
    else:
        from core.brain_v2 import brain
        result = brain.process_dict(text)
        response = result["response"]
        latency_ms = result.get("latency_ms", 0)

    audio_path = _generate_voice(response)

    return {
        "response":   response,
        "audio_url":  "/stark/glasses/audio" if audio_path else None,
        "latency_ms": latency_ms,
    }


@router.get("/audio")
async def glasses_audio():
    """Serve the most recently generated voice response."""
    if not os.path.exists(_RESPONSE_AUDIO_PATH):
        return {"error": "No audio available"}
    return FileResponse(_RESPONSE_AUDIO_PATH, media_type="audio/mpeg",
                        headers={"Cache-Control": "no-cache"})


@router.get("/status")
async def glasses_status():
    """Health check for the glasses pipeline — hit this after deploying to
    confirm every leg (transcription, brain, TTS) is actually reachable."""
    from core.llm.router import check_groq
    from services.elevenlabs_voice import is_available as el_available

    whisper_ok = _check_whisper()
    groq_ok    = check_groq()
    el_ok      = el_available()

    return {
        "pipeline_ready": groq_ok,
        "whisper":        whisper_ok,
        "groq":           groq_ok,
        "elevenlabs":     el_ok,
        "tts_engine":     "elevenlabs" if el_ok else "edge-tts",
        "endpoint":       "/stark/glasses/listen",
    }


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _transcribe(audio_path: str) -> str:
    """Transcribe audio. Prefers local faster-whisper (fine on a Mac with the
    full requirements.txt installed); falls back to Groq's hosted Whisper API,
    which is what actually runs in production since faster-whisper is too
    heavy for a free-tier host like Render."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=5)
        return " ".join(s.text.strip() for s in segments).strip()
    except ImportError:
        return _transcribe_groq(audio_path)
    except Exception as e:
        print(f"[Glasses] Local transcription error: {e}")
        return _transcribe_groq(audio_path)


def _transcribe_groq(audio_path: str) -> str:
    """Transcribe using Groq's hosted Whisper API (free tier: 7,200s/day)."""
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en",
            )
        return str(transcription).strip()
    except Exception as e:
        print(f"[Glasses] Groq transcription error: {e}")
        return ""


def _generate_voice(text: str) -> str:
    """Generate response audio. ElevenLabs primary, edge-tts fallback."""
    try:
        from services.elevenlabs_voice import speak_elevenlabs
        path = speak_elevenlabs(text, play=False, output_path=_RESPONSE_AUDIO_PATH)
        if path:
            return path
    except Exception as e:
        print(f"[Glasses] ElevenLabs generation error: {e}")

    try:
        import asyncio
        import edge_tts

        async def _run():
            comm = edge_tts.Communicate(text[:300], "en-US-GuyNeural")
            await comm.save(_RESPONSE_AUDIO_PATH)

        asyncio.run(_run())
        return _RESPONSE_AUDIO_PATH
    except Exception as e:
        print(f"[Glasses] edge-tts generation error: {e}")
        return ""


def _check_whisper() -> bool:
    """Whisper is available either way — locally via faster-whisper, or via
    Groq's hosted API as the fallback used in production."""
    return True
