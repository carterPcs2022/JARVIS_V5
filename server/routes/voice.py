"""server/routes/voice.py — REST TTS + WebSocket voice pipeline."""
import asyncio, base64, tempfile, os
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from utils.security import verify_token
from services.voice import speak, transcribe

router = APIRouter(prefix="/stark/voice", tags=["voice"])


@router.post("/speak", dependencies=[Depends(verify_token)])
def tts(body: dict):
    """Speak text through the TTS cascade (ElevenLabs -> edge-tts -> pyttsx3).
    On local Mac: plays through speakers immediately.
    Also saves a uniquely-named file under static/ for remote clients
    (fetchable via GET /stark/voice/audio) if `remote` is set."""
    text   = body.get("text", "")
    engine = body.get("engine", "auto")
    remote = body.get("remote", False)
    play   = body.get("play", True)

    if not text:
        return {"error": "No text provided"}

    local_path = speak(text, play=play, force_engine=engine if engine != "auto" else None)

    remote_path = ""
    if remote:
        from services.elevenlabs_voice import generate_for_network
        remote_path = generate_for_network(text)

    return {
        "status":       "spoken" if local_path else "failed",
        "file":         local_path,
        "spoken":       bool(local_path),
        "engine_used":  local_path if local_path else "failed",
        "remote_ready": bool(remote_path),
        "remote_path":  remote_path,
    }


@router.get("/audio")
async def voice_audio(file: str = ""):
    """Serve JARVIS voice audio. Pass ?file=voice_xxx.mp3 for a specific
    generation (services.elevenlabs_voice.generate_for_network's return
    value); omit it to get whichever generation is currently latest
    (tracked in core.state, set only after that file finishes writing).
    Any device on the network can hit this to play JARVIS's speech.

    Full no-cache headers (not just Cache-Control) since each generation
    now has a unique filename anyway — belt and suspenders against any
    client/proxy that still caches by URL."""
    from fastapi.responses import FileResponse
    from config.settings import BASE_DIR

    static_dir = BASE_DIR / "static"
    target = file
    if not target:
        from core.state import state
        target = state.get("latest_audio_file", "")

    path = static_dir / target if target else None
    if not path or not path.exists():
        # Legacy fallback for anything still expecting the old fixed file
        legacy = BASE_DIR / "static_voice.mp3"
        path = legacy if legacy.exists() else None

    if not path:
        return {"error": "No audio available"}

    return FileResponse(
        str(path),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma":        "no-cache",
            "Expires":       "0",
        },
    )


@router.get("/status", dependencies=[Depends(verify_token)])
def voice_status():
    from services.voice import voice_engine_status
    return voice_engine_status()


@router.get("/usage", dependencies=[Depends(verify_token)])
def voice_usage():
    from services.elevenlabs_voice import get_usage
    return get_usage()


@router.get("/voices", dependencies=[Depends(verify_token)])
def voice_list():
    from services.elevenlabs_voice import list_voices
    return list_voices()


@router.post("/engine", dependencies=[Depends(verify_token)])
def set_voice_engine(body: dict):
    """Switch voice engine on the fly. {"engine": "elevenlabs" | "edge" | "pyttsx3" | "auto"}"""
    import os as _os
    engine = body.get("engine", "auto")
    _os.environ["VOICE_ENGINE"] = engine
    return {"engine": engine, "status": "switched"}


@router.websocket("/ws")
async def voice_ws(websocket: WebSocket):
    """
    Full-duplex voice pipeline.

    Client sends:  {"type": "audio", "data": "<base64 wav bytes>"}
                or {"type": "text",  "message": "..."}   (typed input)

    Server sends:  {"type": "transcript", "text": "..."}
                   {"type": "token",      "token": "..."}   (streamed)
                   {"type": "stream_end", "response": "...", ...}
                   {"type": "audio",      "data": "<base64 mp3>"}
                   {"type": "error",      "message": "..."}
    """
    await websocket.accept()
    await websocket.send_json({"type": "system", "message": "Voice pipeline ready."})

    try:
        while True:
            raw = await websocket.receive_text()
            import json
            data = json.loads(raw)

            if data.get("type") == "audio":
                # Decode + transcribe
                audio_bytes = base64.b64decode(data["data"])
                tmp = tempfile.mktemp(suffix=".wav")
                with open(tmp, "wb") as f:
                    f.write(audio_bytes)
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, transcribe, tmp)
                os.remove(tmp)

                if text.startswith("["):
                    await websocket.send_json({"type": "error", "message": text})
                    continue
                await websocket.send_json({"type": "transcript", "text": text})

            elif data.get("type") == "text":
                text = data.get("message", "").strip()
                if not text:
                    continue
            else:
                continue

            # Stream response through brain
            response_text = await _stream_and_collect(websocket, text)

            # Speak the response
            if response_text:
                loop = asyncio.get_event_loop()
                audio_path = await loop.run_in_executor(
                    None, lambda: speak(response_text, play=False))
                if audio_path and os.path.exists(audio_path):
                    with open(audio_path, "rb") as f:
                        audio_b64 = base64.b64encode(f.read()).decode()
                    await websocket.send_json({"type": "audio", "data": audio_b64})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})


async def _stream_and_collect(websocket: WebSocket, msg: str) -> str:
    """Stream Groq tokens to the voice WebSocket; return full response text."""
    from config.settings import GROQ_API_KEY, GROQ_MODEL
    from core.brain_v2 import Reasoner, Validator
    from core.llm.openai import stream_chat
    import time

    if not GROQ_API_KEY:
        # Fallback: blocking call
        from core.brain_v2 import brain
        result = brain.process_dict(msg)
        await websocket.send_json({"type": "stream_end", **result})
        return result["response"]

    reasoner  = Reasoner()
    validator = Validator()
    intent    = reasoner.analyze(msg)
    val       = validator.check(intent)

    if not val.ok:
        await websocket.send_json({"type": "error", "message": val.reason})
        return ""

    messages = [{"role": "system", "content": intent.system}]
    if intent.context:
        messages.append({"role": "system", "content": f"Context:\n{intent.context}"})
    messages.append({"role": "user", "content": msg})

    try:
        start, full = time.time(), ""
        await websocket.send_json({"type": "stream_start"})
        async for token in stream_chat(messages):
            full += token
            await websocket.send_json({"type": "token", "token": token})
        latency = round((time.time() - start) * 1000, 2)
        await websocket.send_json({
            "type": "stream_end", "response": full,
            "model": GROQ_MODEL, "provider": "groq", "latency_ms": latency,
            "meta": {"mode": "voice_stream"},
        })
        return full
    except Exception as e:
        print(f"[VoiceWS] stream failed: {e}")
        from core.brain_v2 import brain
        result = brain.process_dict(msg)
        await websocket.send_json({"type": "stream_end", **result})
        return result["response"]
