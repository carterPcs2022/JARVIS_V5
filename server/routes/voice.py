"""server/routes/voice.py — REST TTS + WebSocket voice pipeline."""
import asyncio, base64, tempfile, os
import httpx
from fastapi import APIRouter, Depends, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from utils.security import verify_token
from services.voice import speak, transcribe
from config.settings import AVENGERS_PASSPHRASE

router = APIRouter(prefix="/stark/voice", tags=["voice"])

MAC_BRIDGE_URL = os.getenv("MAC_BRIDGE_URL", "")
MAC_BRIDGE_TOKEN = os.getenv("MAC_BRIDGE_TOKEN", "")

# Anyone with a valid API token could otherwise wipe or overwrite the
# enrolled voiceprint outright — the token gates access to the app, not
# specifically to this identity-critical, hard-to-notice action. Reuses
# AVENGERS_PASSPHRASE (already the codebase's standing secondary-auth
# secret for other sensitive/destructive actions — see
# core/protocols.py's Protocol 24 restore(), core/privacy_mode.py) rather
# than inventing a new secret. Same convention as those: if the env var
# isn't set at all, this gate doesn't apply (matches every other passphrase
# check in this codebase — an intentionally unset secret means "not opted
# into this gate", not "broken").
#
# "Already enrolled" is defined as a COMPLETE profile (sample_count >=
# ENROLL_TARGET), not just "a profile file exists" — enrollment happens as
# ENROLL_TARGET separate POST /enroll calls, and gating on mere existence
# would demand a passphrase midway through a brand-new, still-in-progress
# enrollment (the file exists after sample 1) as if it were tampering with
# someone else's already-established identity. A partial profile is still
# just first-time setup in progress.
ENROLL_TARGET = 5


def _passphrase_ok(body: dict) -> bool:
    if not AVENGERS_PASSPHRASE:
        return True
    return body.get("passphrase", "") == AVENGERS_PASSPHRASE


async def _profile_fully_enrolled(profile: str) -> bool:
    """Fails CLOSED (treats an unreachable bridge as "fully enrolled," i.e.
    keeps the gate up) — the opposite of /transcribe's speaker-verification
    fail-open. That asymmetry is deliberate: fail-open there protects
    against a bridge hiccup locking out a legitimate command; fail-closed
    here protects against a bridge hiccup being used as an excuse to skip
    re-auth before destroying or overwriting the stored voiceprint."""
    if not MAC_BRIDGE_URL:
        return True
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MAC_BRIDGE_URL}/voice/profile/status",
                params={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            data = resp.json()
            return bool(data.get("enrolled")) and data.get("sample_count", 0) >= ENROLL_TARGET
    except Exception:
        return True


def _reauth_required_response() -> JSONResponse:
    return JSONResponse(status_code=403, content={
        "error": "Re-authentication required — a voice profile is already enrolled.",
        "reauth_required": True,
    })


@router.post("/transcribe", dependencies=[Depends(verify_token)])
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe an uploaded audio clip — used by the HUD's browser-based
    wake-word/hands-free capture (hud_mobile/desktop.html) to turn a
    recorded command into text. Token-gated like every other POST route on
    this router; the HUD already attaches `Authorization: Bearer <token>`
    on its own fetch calls (see authHeaders() in desktop.html), so this
    matches the convention rather than opening a public hole."""
    suffix = ".webm" if "webm" in (audio.filename or "") else ".wav"
    audio_bytes = await audio.read()

    # Speaker verification is a soft gate, not a hard dependency — any bridge
    # hiccup (down, timeout, misconfigured) must fall through to normal
    # transcription rather than lock a legitimate command out. But "soft"
    # was silently indistinguishable from "not running at all" (no
    # MAC_BRIDGE_URL, or every call raising) — print loudly in both cases so
    # that isn't discovered by an unverified command executing instead of
    # in the logs.
    if not MAC_BRIDGE_URL:
        print("[Voice] MAC_BRIDGE_URL not configured — speaker verification is OFF, any voice will execute commands")
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{MAC_BRIDGE_URL}/voice/verify",
                    files={"audio": (audio.filename or "audio.webm", audio_bytes)},
                    data={"profile": "default"},
                    headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
                )
                result = resp.json()
            if result.get("verified") and result.get("match") is False:
                return {
                    "text": "",
                    "rejected": True,
                    "reason": "voice_mismatch",
                    "score": result.get("score"),
                }
        except Exception as e:
            print(f"[Voice] Speaker verification unreachable, falling through unverified: {e}")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        audio_path = tmp.name

    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, transcribe, audio_path)
        if text.startswith("["):
            return {"text": "", "error": text}
        return {"text": text}
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass


async def _proxy_to_bridge_response(resp: httpx.Response) -> JSONResponse:
    """A 4xx/5xx from the bridge (e.g. token mismatch) must not be
    disguised as a 200 to the browser — that's what let a rejected
    enrollment show up as a Render-log 200 while the HUD silently failed."""
    try:
        resp.raise_for_status()
        return JSONResponse(status_code=200, content=resp.json())
    except httpx.HTTPStatusError:
        try:
            body = resp.json()
        except Exception:
            body = {"error": resp.text}
        return JSONResponse(status_code=resp.status_code, content=body)


@router.post("/enroll", dependencies=[Depends(verify_token)])
async def enroll_voice(audio: UploadFile = File(...), profile: str = Form("default"), passphrase: str = Form("")):
    """Thin proxy to the Mac Bridge's voiceprint enrollment — the bridge
    token never reaches the browser, only this server holds it.

    Gated behind AVENGERS_PASSPHRASE once a profile is already fully
    enrolled — see _profile_fully_enrolled()'s docstring for why "fully"
    and not merely "exists". A fresh, in-progress enrollment (samples
    1..ENROLL_TARGET-1 of a brand-new profile) is never gated.

    `profile` and `passphrase` must be declared as Form(...), not plain
    str defaults — FastAPI silently ignores non-Form-annotated params when
    an UploadFile/File is also present in the same endpoint, so without
    this both fields would always read as their Python default regardless
    of what was actually submitted (found while testing this gate: a
    correct passphrase was still rejected because it was never actually
    being read from the multipart body)."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    if await _profile_fully_enrolled(profile) and not _passphrase_ok({"passphrase": passphrase}):
        return _reauth_required_response()
    audio_bytes = await audio.read()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{MAC_BRIDGE_URL}/voice/enroll",
                files={"audio": (audio.filename or "audio.webm", audio_bytes)},
                data={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            return await _proxy_to_bridge_response(resp)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@router.get("/profile/status", dependencies=[Depends(verify_token)])
async def voice_profile_status(profile: str = "default"):
    """Thin proxy to the Mac Bridge's enrollment status check."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MAC_BRIDGE_URL}/voice/profile/status",
                params={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            return await _proxy_to_bridge_response(resp)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@router.post("/reset", dependencies=[Depends(verify_token)])
async def reset_voice_profile(body: dict):
    """Thin proxy to the Mac Bridge's /voice/reset — deletes the stored
    profile so a polluted enrollment (partial/garbage samples from the
    enrollment-button loop bug) can be wiped and re-enrolled from scratch
    without SSHing in to rm the file by hand.

    Gated behind AVENGERS_PASSPHRASE once a profile is already fully
    enrolled (see _profile_fully_enrolled()) — resetting is what actually
    destroys an established voiceprint, so this is the more important of
    the two gates. A still-in-progress partial enrollment isn't gated,
    since reset is also the documented recovery path for cleaning up a
    botched first-time setup."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    profile = body.get("profile", "default")
    if await _profile_fully_enrolled(profile) and not _passphrase_ok(body):
        return _reauth_required_response()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{MAC_BRIDGE_URL}/voice/reset",
                data={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            return await _proxy_to_bridge_response(resp)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


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
    from server.websocket import _ws_token_ok
    if not _ws_token_ok(websocket):
        # This endpoint had the exact same gap /ws/chat had before last
        # night's fix — no token check at all, unlike every REST route
        # in this same file. It went unaudited then because the audit
        # only covered /ws/chat; hud_mobile/app.js (the /hud/mobile
        # frontend, the only client of this endpoint) connects here for
        # its full voice pipeline (audio transcription + streamed text
        # replies), so this was reachable by anyone with zero
        # credentials, same severity as the original finding.
        await websocket.close(code=1008)
        return

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
