"""server/routes/vision_identify.py — "look at something and tell me what
it is" HUD readout. Crude first version: phone camera photo in, one Claude
vision call, spoken answer out.

Deliberately separate from server/routes/glasses.py's /stark/glasses/analyze
pipeline, which uses Groq LLaVA (see core/tools/vision.py) — this uses the
Anthropic vision API instead, per the actual request. Not a replacement for
the Groq-based glasses pipeline, a sibling for a different input source
(phone, not Ray-Ban glasses) and a different vision backend.
"""
import base64
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import FileResponse
from utils.security import verify_token
from config.settings import BASE_DIR

router = APIRouter(prefix="/stark/vision", tags=["vision"])

_RESPONSE_AUDIO_PATH = str(BASE_DIR / "vision_identify_response.mp3")

_MEDIA_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp", "gif": "image/gif",
}

_HUD_PROMPT = (
    "Identify and briefly describe what's in this image, as if speaking to "
    "someone wearing a HUD who needs a quick answer. Reply in exactly this "
    "format, nothing else:\n"
    "LABEL: <2-5 word name for the main subject>\n"
    "SPOKEN: <1-2 short sentences, spoken out loud>"
)


def _parse_identify_response(text: str) -> tuple[str, str]:
    """Split the LABEL:/SPOKEN: response into (label, spoken). Falls back to
    treating the whole reply as the spoken line if the model didn't follow
    the format — better than dropping the answer entirely."""
    label, spoken = "", ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("LABEL:"):
            label = line.split(":", 1)[1].strip()
        elif line.upper().startswith("SPOKEN:"):
            spoken = line.split(":", 1)[1].strip()
    if not spoken:
        spoken = text.strip()
    return label, spoken


@router.post("/identify", dependencies=[Depends(verify_token)])
async def vision_identify(image: UploadFile = File(...)):
    """Accept a photo, identify what's in it via Claude vision, and return
    a spoken response as audio — same file-response pattern as
    /stark/glasses/listen, so a Shortcut can just play what it gets back."""
    from core.llm.anthropic_client import call_anthropic_vision

    name = (image.filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else "jpg"
    media_type = _MEDIA_TYPES.get(ext, "image/jpeg")

    content = await image.read()
    image_b64 = base64.b64encode(content).decode()

    result = call_anthropic_vision(image_b64, media_type, _HUD_PROMPT)
    if not result:
        return {"error": "Vision call failed.", "audio": False}

    label, spoken = _parse_identify_response(result)

    audio_path = _generate_voice(spoken)
    if audio_path and os.path.exists(audio_path):
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            headers={
                "X-Jarvis-Label":  label[:200],
                "X-Jarvis-Text":   spoken[:500],
                "Cache-Control":   "no-cache",
            },
        )

    return {"label": label, "spoken": spoken, "audio": False}


def _generate_voice(text: str) -> str:
    """ElevenLabs primary, edge-tts fallback — same cascade as
    server/routes/glasses.py's _generate_voice()."""
    try:
        from services.elevenlabs_voice import speak_elevenlabs
        path = speak_elevenlabs(text, play=False, output_path=_RESPONSE_AUDIO_PATH)
        if path:
            return path
    except Exception as e:
        print(f"[VisionIdentify] ElevenLabs generation error: {e}")

    try:
        import asyncio
        import edge_tts

        async def _run():
            comm = edge_tts.Communicate(text[:300], "en-US-GuyNeural")
            await comm.save(_RESPONSE_AUDIO_PATH)

        asyncio.run(_run())
        return _RESPONSE_AUDIO_PATH
    except Exception as e:
        print(f"[VisionIdentify] edge-tts generation error: {e}")
        return ""
