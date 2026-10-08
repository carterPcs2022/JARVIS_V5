"""server/websocket.py — WebSocket using Brain V2 pipeline with token streaming."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, hmac, json, os, time
from core.brain_v2 import brain
from core.event_bus import bus
from config.settings import GROQ_API_KEY, API_TOKEN, ENVIRONMENT

router = APIRouter()
_clients: dict = {}


def _ws_token_ok(websocket: WebSocket) -> bool:
    """Authenticate the WebSocket before accepting it; cloud auth fails closed."""
    if not API_TOKEN:
        return ENVIRONMENT == "local"
    if ENVIRONMENT == "local" and os.getenv("DEV_MODE", "false").lower() == "true":
        return True

    ip = websocket.client.host if websocket.client else "unknown"
    token = websocket.query_params.get("token", "")

    # Validate the credential before applying Sentinel's failed-auth block.
    # Sentinel exists to stop credential guessing, not to invalidate a valid
    # credential because the same IP previously made too many bad attempts.
    ok = bool(token) and hmac.compare_digest(token, API_TOKEN)
    if ok:
        try:
            from services.sentinel import clear_failed_auth
            clear_failed_auth(ip)
        except Exception:
            pass
        return True

    # Invalid credentials are still subject to Sentinel's temporary block.
    try:
        from services.sentinel import is_blocked
        if is_blocked(ip):
            return False
    except Exception:
        pass

    try:
        from utils.security import _record_failed_auth_safe
        _record_failed_auth_safe(ip)
    except Exception:
        pass
    return False

THREAT_CLASSIFY_TIMEOUT_SECONDS = 2


def _choice_test_enabled() -> bool:
    """Developer-only manual UI test; disabled unless explicitly enabled in the environment."""
    return os.getenv("JARVIS_CHOICE_TEST_ENABLED", "false").lower() == "true"


async def _run_choice_test(websocket: WebSocket) -> bool:
    """Send a harmless pending-choice payload through the real chat WS path."""
    if not _choice_test_enabled():
        return False
    from core.ask_user_choice import annotate_pending, propose
    pending = propose([{
        "question": "Choice-system test: which option should JARVIS use?",
        "options": ["Test A", "Test B", "Cancel"],
        "allow_multiple": False,
    }])
    if pending is None:
        await websocket.send_json({
            "type": "response",
            "response": "Choice test could not create a pending choice.",
            "model": "", "provider": "choice_test", "latency_ms": 0,
            "pending_choice": None,
        })
        return True
    pending = annotate_pending({"choice_test": True}) or pending
    await websocket.send_json({
        "type": "response",
        "response": "Choice-system test ready. Pick an option below.",
        "model": "", "provider": "choice_test", "latency_ms": 0,
        "pending_choice": pending,
        "meta": {"action": "choice_test", "complexity": "simple", "mode": "test",
                 "was_rewritten": False, "issues": []},
    })
    return True


async def _apply_threat_classification(loop: asyncio.AbstractEventLoop, msg: str,
                                        classify_task: "asyncio.Future") -> str | None:
    from services.threat_detector import classifier_failed_result
    from services.combat_mode import combat_mode
    try:
        classification = await asyncio.wait_for(classify_task, timeout=THREAT_CLASSIFY_TIMEOUT_SECONDS)
        if not classification:
            classification = classifier_failed_result("classify_task returned no result")
    except Exception as e:
        print(f"[WS] Threat classification unavailable ({e}) — asking a check-in question instead of assuming safe.")
        classification = classifier_failed_result(f"classify_task exception: {e}")
    outcome = await loop.run_in_executor(None, combat_mode.handle_classification, msg, classification)
    return outcome.get("soft_confirm_prompt")


def _boot_greeting() -> str:
    try:
        from core.memory import get_short_term
        first_time = len(get_short_term(1)) == 0
    except Exception:
        first_time = False
    if first_time:
        return "J.A.R.V.I.S. online. All systems nominal. I'm ready when you are, sir."
    from config.settings import now_local
    hour = now_local().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {time_of_day}. Systems online."


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    if not _ws_token_ok(websocket):
        await websocket.close(code=1008)
        return
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
            msg = data.get("message", "").strip()
            if not msg:
                continue
            if msg.lower() == "choice test" and await _run_choice_test(websocket):
                continue
            from core.ask_user_choice import clear_pending, get_pending, resolve_reply
            _pending = get_pending()
            if _pending is not None and _pending.get("choice_test"):
                _resolved = resolve_reply(_pending, msg)
                clear_pending()
                if _resolved:
                    await websocket.send_json({
                        "type": "response",
                        "response": f"Choice test passed — JARVIS received your selection.\n\n{_resolved}",
                        "model": "", "provider": "choice_test", "latency_ms": 0,
                        "pending_choice": None,
                        "meta": {"action": "choice_test", "selection_received": True},
                    })
                else:
                    await websocket.send_json({
                        "type": "response",
                        "response": "Choice test received the reply, but it did not match an option.",
                        "model": "", "provider": "choice_test", "latency_ms": 0,
                        "pending_choice": None,
                        "meta": {"action": "choice_test", "selection_received": False},
                    })
                continue
            from services.combat_mode import combat_mode
            if combat_mode.is_engaged():
                from services.combat_staging import try_fast_path
                staged = try_fast_path(msg)
                if staged:
                    await websocket.send_json({"type": "response", **staged})
                    continue
            loop = asyncio.get_event_loop()
            from services.threat_detector import classify as classify_threat
            classify_task = loop.run_in_executor(None, classify_threat, msg)
            streamed = await _try_stream(websocket, msg, loop, classify_task)
            if not streamed:
                result = await loop.run_in_executor(None, brain.process_dict, msg)
                soft_confirm = await _apply_threat_classification(loop, msg, classify_task)
                if soft_confirm and isinstance(result.get("response"), str):
                    result["response"] = f"{result['response']}\n\n{soft_confirm}"
                await websocket.send_json({"type": "response", **result})
    except WebSocketDisconnect:
        print(f"[JARVIS] Client disconnected — going quiet ({cid}).")
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        pump.cancel()
        bus.unsubscribe_async_queue(q)
        _clients.pop(cid, None)


async def _try_stream(websocket: WebSocket, msg: str, loop: asyncio.AbstractEventLoop,
                      classify_task: "asyncio.Future") -> bool:
    if not GROQ_API_KEY:
        return False
    from core.brain_v2 import has_early_exit_trigger
    if has_early_exit_trigger(msg):
        return False
    from core.ask_user_choice import get_pending
    if get_pending() is not None:
        return False
    from core.llm.openai import stream_chat
    from core.brain_v2 import Reasoner, Validator
    reasoner = Reasoner()
    validator = Validator()
    intent = reasoner.analyze(msg)
    from core.protocols import protocol_engine
    proto = protocol_engine.check(intent)
    if not proto.allowed or proto.protocol_triggered:
        return False
    validation = validator.check(intent)
    if not validation.ok:
        classify_task.cancel()
        await websocket.send_json({
            "type": "response",
            "response": f"I can't process that: {validation.reason}",
            "model": "", "provider": "", "latency_ms": 0,
            "meta": {"action": "chat", "complexity": "simple",
                     "mode": "direct", "was_rewritten": False, "issues": [validation.reason]},
        })
        return True
    if intent.complexity == "complex" or intent.action in (
        "mac_control", "voice", "vision", "code", "calendar", "delete_file", "compress_file",
    ):
        return False
    messages = [{"role": "system", "content": intent.system}]
    if intent.context:
        messages.append({"role": "system", "content": f"Context:\n{intent.context}"})
    messages.append({"role": "user", "content": msg})
    try:
        start = time.time()
        full_txt = ""
        await websocket.send_json({"type": "stream_start"})
        async for token in stream_chat(messages, max_tokens=1024, temperature=0.6):
            full_txt += token
            await websocket.send_json({"type": "token", "token": token})
        latency = round((time.time() - start) * 1000, 2)
        pending_choice = None
        try:
            from core.ask_user_choice import extract_marker, format_fallback_text, propose
            clean_text, parsed = extract_marker(full_txt)
            full_txt = clean_text
            if parsed is not None:
                pending_choice = propose(parsed.get("questions", []))
                if pending_choice is not None:
                    full_txt = f"{full_txt}\n\n{format_fallback_text(pending_choice)}".strip()
        except Exception:
            pass
        await loop.run_in_executor(None, _persist, msg, full_txt)
        soft_confirm = await _apply_threat_classification(loop, msg, classify_task)
        if soft_confirm:
            full_txt = f"{full_txt}\n\n{soft_confirm}"
        has_audio = False
        try:
            from config.settings import VOICE_ENABLED
            if VOICE_ENABLED:
                has_audio = True
                loop.run_in_executor(None, _generate_voice_background, full_txt, websocket, loop)
        except Exception:
            pass
        from config.settings import GROQ_MODEL
        await websocket.send_json({
            "type": "stream_end", "response": full_txt, "model": GROQ_MODEL,
            "provider": "groq", "latency_ms": latency, "has_audio": has_audio,
            "pending_choice": pending_choice,
            "meta": {"action": intent.action, "complexity": intent.complexity,
                     "mode": "stream", "was_rewritten": False, "issues": []},
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


def _generate_voice_background(text: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
    try:
        from services.elevenlabs_voice import generate_chunks_for_network
        filenames = generate_chunks_for_network(text)
        if filenames:
            asyncio.run_coroutine_threadsafe(_send_audio_ready(websocket, filenames), loop)
    except Exception as e:
        print(f"[WebSocket] Background voice generation failed: {e}")


async def _send_audio_ready(websocket: WebSocket, filenames: list[str]):
    try:
        await websocket.send_json({"type": "audio_ready", "audio_file": filenames[0], "audio_files": filenames})
    except Exception:
        pass
