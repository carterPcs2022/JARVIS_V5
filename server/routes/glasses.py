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
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import FileResponse
from utils.security import verify_token
from config.settings import BASE_DIR, USER_TIMEZONE

router = APIRouter(prefix="/stark/glasses", tags=["glasses"])

_RESPONSE_AUDIO_PATH = str(BASE_DIR / "glasses_response.mp3")


def _now_local() -> datetime:
    """JARVIS runs on Render/Railway (server clock is UTC) — use the
    user's configured timezone so the spoken time/date is correct."""
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(USER_TIMEZONE))
    except Exception:
        return datetime.now()


# ── Quick-response cache — skip the LLM entirely for trivial queries ────────────
# Shaves the biggest latency cost (an LLM round-trip) off the questions asked
# constantly through a wearable — time/date/status checks are effectively free
# to answer directly instead of paying for a Groq call every time.

_QUICK_RESPONSES = {
    "what time is it":  lambda: f"It's {_now_local().strftime('%I:%M %p')}.",
    "whats the time":   lambda: f"It's {_now_local().strftime('%I:%M %p')}.",
    "what day is it":   lambda: _now_local().strftime('%A, %B %d.'),
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
            # Tone analysis costs one extra "instant"-tier LLM call, so skip
            # it on the quick-response path above — only run it when we're
            # already paying for a full brain call.
            tone = analyze_voice_tone(text)
            brain_input = text
            if tone.get("stress_level", 5) > 7:
                brain_input = f"[User sounds stressed/urgent — be extra supportive and direct] {text}"
            elif tone.get("energy") == "high":
                brain_input = f"[User's energy is high — match their energy] {text}"

            from core.brain_v2 import brain
            result = brain.process_dict(brain_input)
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


# ── Computer vision — analyze a photo taken through the glasses ─────────────────

async def _save_upload(image: UploadFile) -> str:
    suffix = ".jpg"
    name = (image.filename or "").lower()
    if "png" in name:
        suffix = ".png"
    elif "webp" in name:
        suffix = ".webp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await image.read())
        return tmp.name


@router.post("/analyze", dependencies=[Depends(verify_token)])
async def glasses_analyze(image: UploadFile = File(...), question: str = ""):
    """Analyze a photo captured through the glasses — describes what's
    visible, flags anything important, and speaks a one-sentence summary
    through the glasses speaker."""
    from services.glasses_cv import glasses_cv

    path = await _save_upload(image)
    try:
        return glasses_cv.analyze_frame(path, question)
    finally:
        os.unlink(path)


@router.post("/threat", dependencies=[Depends(verify_token)])
async def glasses_threat(image: UploadFile = File(...)):
    """Quick threat assessment of a photo captured through the glasses."""
    from services.glasses_cv import glasses_cv

    path = await _save_upload(image)
    try:
        return glasses_cv.threat_scan(path)
    finally:
        os.unlink(path)


@router.post("/identify", dependencies=[Depends(verify_token)])
async def glasses_identify(image: UploadFile = File(...)):
    """Describe a person visible in a glasses photo — never attempts
    name identification, matching services/vision.py's ethical stance."""
    from services.glasses_cv import glasses_cv

    path = await _save_upload(image)
    try:
        return glasses_cv.identify_person(path)
    finally:
        os.unlink(path)


@router.get("/hud_text", dependencies=[Depends(verify_token)])
async def glasses_hud_text():
    """Ultra-brief status string formatted for the glasses' own tiny
    in-lens display — distinct from /status, which is a pipeline health
    check (JSON diagnostics), not a display string."""
    from services.glasses_hud import glasses_hud
    return {"text": glasses_hud.get_status_text()}


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _transcribe(audio_path: str) -> str:
    """Prefer local faster-whisper, fall back to Groq's hosted Whisper API —
    shared with the browser HUD's transcribe endpoint via services.voice so
    this logic only lives in one place (see services/voice.py:transcribe)."""
    from services.voice import transcribe as _shared_transcribe
    text = _shared_transcribe(audio_path)
    return "" if text.startswith("[Transcribe error") else text


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


def analyze_voice_tone(transcript: str) -> dict:
    """Analyze emotional tone from the spoken transcript (word choice,
    punctuation, urgency) — one cheap 'instant' tier LLM call.
    Returns: {emotion, energy, stress_level, confidence}."""
    from core.llm.router import think
    import json

    result = think(
        f"Analyze the emotional tone and energy level in this spoken "
        f"message:\n\n'{transcript}'\n\n"
        f"Consider: word choice, punctuation patterns, urgency, sentiment.\n"
        f'Reply as JSON: {{"emotion": str, "energy": "low/medium/high", '
        f'"stress_level": 1-10, "confidence": "low/medium/high"}}',
        force_model="instant",
    )
    try:
        tone = json.loads(result.strip())
    except Exception:
        tone = {"emotion": "neutral", "energy": "medium", "stress_level": 5, "confidence": "low"}

    try:
        from core.memory import store_emotional_memory
        store_emotional_memory(
            topic=transcript[:50],
            emotion=tone.get("emotion", "neutral"),
            intensity=tone.get("stress_level", 5),
        )
    except Exception:
        pass

    return tone
