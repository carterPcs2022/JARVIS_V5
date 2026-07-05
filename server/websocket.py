"""server/websocket.py — WebSocket using Brain V2 pipeline with token streaming."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, time
from core.brain_v2 import brain
from core.event_bus import bus
from config.settings import GROQ_API_KEY

router = APIRouter()
_clients: dict = {}


def _boot_greeting() -> str:
    """JARVIS introduces himself on a brand-new install, or gives a
    time-of-day acknowledgment on every connection after that."""
    try:
        from core.memory import get_short_term
        first_time = len(get_short_term(1)) == 0
    except Exception:
        first_time = False

    if first_time:
        return "J.A.R.V.I.S. online. All systems nominal. I'm ready when you are, sir."

    from datetime import datetime
    hour = datetime.now().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {time_of_day}. Systems online."


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    cid = str(id(websocket))
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _clients[cid] = q
    bus.subscribe_async_queue(q)
    await websocket.send_json({"type": "system", "message": _boot_greeting()})

    async def _pump():
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.1)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                pass
            except Exception:
                break

    pump = asyncio.create_task(_pump())
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            msg  = data.get("message", "").strip()
            if not msg:
                continue

            # Try streaming path first (Groq only)
            streamed = await _try_stream(websocket, msg)
            if not streamed:
                # Fallback: blocking brain call (Ollama or error)
                result = await asyncio.get_event_loop().run_in_executor(
                    None, brain.process_dict, msg)
                await websocket.send_json({"type": "response", **result})

    except WebSocketDisconnect:
        print(f"[JARVIS] Client disconnected — going quiet ({cid}).")
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        pump.cancel()
        bus.unsubscribe_async_queue(q)
        _clients.pop(cid, None)


async def _try_stream(websocket: WebSocket, msg: str) -> bool:
    """
    Attempt Groq streaming. Returns True if streaming succeeded.
    On success, sends token/stream_end events and persists the turn.
    """
    if not GROQ_API_KEY:
        return False

    from core.llm.openai import stream_chat
    from core.brain_v2 import Reasoner, Validator
    from core.context import build_context, build_system
    from config.settings import JARVIS_PERSONALITY

    reasoner  = Reasoner()
    validator = Validator()

    intent     = reasoner.analyze(msg)
    validation = validator.check(intent)
    if not validation.ok:
        await websocket.send_json({
            "type": "response",
            "response": f"I can't process that: {validation.reason}",
            "model": "", "provider": "", "latency_ms": 0,
            "meta": {"action": "chat", "complexity": "simple",
                     "mode": "direct", "was_rewritten": False, "issues": [validation.reason]},
        })
        return True

    # Stream chat, task, and search queries — context already has web results embedded
    # Only drop to full pipeline for true multi-step complex tasks or mac/voice/vision
    if intent.complexity == "complex" or intent.action in ("mac_control", "voice", "vision", "code"):
        return False

    messages = [{"role": "system", "content": intent.system}]
    if intent.context:
        messages.append({"role": "system", "content": f"Context:\n{intent.context}"})
    messages.append({"role": "user", "content": msg})

    try:
        start    = time.time()
        full_txt = ""
        await websocket.send_json({"type": "stream_start"})

        async for token in stream_chat(messages, max_tokens=1024, temperature=0.6):
            full_txt += token
            await websocket.send_json({"type": "token", "token": token})

        latency = round((time.time() - start) * 1000, 2)

        # Persist turn
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _persist, msg, full_txt)

        # Render has no speakers, but the browser does — generate audio in
        # the background (never blocks the text response) and tell the
        # client it's ready to fetch from /stark/voice/audio. Previously
        # only the non-streaming full pipeline (core/brain_v2.py Executor)
        # did this; this fast streaming path — the one actually used for
        # ordinary chat — never generated audio at all.
        has_audio = False
        try:
            from config.settings import VOICE_ENABLED
            if VOICE_ENABLED:
                has_audio = True
                loop.run_in_executor(None, _generate_voice_background, full_txt)
        except Exception:
            pass

        from config.settings import GROQ_MODEL
        await websocket.send_json({
            "type":     "stream_end",
            "response": full_txt,
            "model":    GROQ_MODEL,
            "provider": "groq",
            "latency_ms": latency,
            "has_audio": has_audio,
            "meta": {
                "action":        intent.action,
                "complexity":    intent.complexity,
                "mode":          "stream",
                "was_rewritten": False,
                "issues":        [],
            },
        })
        bus.chat("assistant", full_txt)
        return True

    except Exception as e:
        print(f"[WS Stream] Groq stream failed: {e}")
        return False


def _persist(user_msg: str, response: str):
    from core.memory import save_turn, store_long_term
    from core import evolution
    save_turn(user_msg, response)
    store_long_term(user_msg, response)
    evolution.log(user_msg, response, "stream", 0)


def _generate_voice_background(text: str):
    """Writes static_voice.mp3 (served at GET /stark/voice/audio) — never
    called on the event loop directly, always via run_in_executor."""
    try:
        from services.elevenlabs_voice import generate_for_network
        generate_for_network(text)
    except Exception as e:
        print(f"[WebSocket] Background voice generation failed: {e}")
