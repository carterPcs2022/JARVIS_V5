"""
core/event_bus.py — JARVIS internal event bus.
Modules publish events; subscribers (WebSocket, voice, HUD) react.
"""
import asyncio
import threading
import queue
from datetime import datetime
from typing import Callable, Any


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._async_queues: list[asyncio.Queue] = []
        self._sync_queue: queue.Queue = queue.Queue(maxsize=500)
        self._lock = threading.Lock()

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe a sync callback to an event type. Use '*' for all events."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)
            self._subscribers.setdefault("*", [])

    def subscribe_async_queue(self, q: asyncio.Queue):
        """Subscribe an async queue (used by WebSocket handler)."""
        with self._lock:
            self._async_queues.append(q)

    def unsubscribe_async_queue(self, q: asyncio.Queue):
        with self._lock:
            self._async_queues = [x for x in self._async_queues if x is not q]

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(self, event_type: str, data: Any = None,
                severity: str = "info"):
        event = {
            "type":      event_type,
            "data":      data,
            "severity":  severity,
            "timestamp": datetime.now().isoformat(),
        }

        # Push to sync queue
        try:
            self._sync_queue.put_nowait(event)
        except queue.Full:
            pass

        # Push to async queues (WebSocket clients)
        for q in list(self._async_queues):
            try:
                q.put_nowait(event)
            except Exception:
                pass

        # Trigger sync subscribers
        with self._lock:
            handlers = (self._subscribers.get(event_type, []) +
                        self._subscribers.get("*", []))
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Handler error for {event_type}: {e}")

    def get_pending(self) -> list[dict]:
        """Drain and return all pending sync events."""
        events = []
        while not self._sync_queue.empty():
            try:
                events.append(self._sync_queue.get_nowait())
            except queue.Empty:
                break
        return events

    # ── Convenience emitters ──────────────────────────────────────────────────

    def alert(self, message: str, severity: str = "warning",
              category: str = "ALERT"):
        self.publish("alert", {
            "message":  message,
            "category": category,
        }, severity=severity)
        print(f"[JARVIS][{severity.upper()}] {message}")

        # Pushover — this is the single highest-leverage fix from the
        # scheduler audit: every one of this method's 17+ call sites across
        # the codebase (lockdown, snap mode, canary/honeypot hits, dead
        # man's switch, sentinel threat scores, daily secret scan, DEFCON
        # changes, SIEM matches, etc.) relied on voice/Telegram/phone below,
        # none of which are configured on Render — so a "critical" alert
        # reached zero real-world channels in production, only an internal
        # HUD publish visible if a browser tab happened to be open. Routing
        # through services/notifications.py's existing Pushover-aware
        # functions (rather than duplicating that HTTP call here) fixes all
        # of those call sites at once instead of patching each individually.
        if severity in ("critical", "high"):
            try:
                from services.notifications import critical as _po_critical, alert as _po_alert
                if severity == "critical":
                    _po_critical(category, message)
                else:
                    _po_alert(category, message)
            except Exception:
                pass

            # Independent second channel — Gmail API via a completely
            # different account/provider than Pushover, so a Pushover-side
            # failure (trial expiry, account issue, Pushover itself being
            # down) can't take this one down with it. Still runs inside
            # this same JARVIS process, though — if the whole service is
            # down, neither channel fires; this covers Pushover-specific
            # failure, not JARVIS-process-down.
            try:
                from services.alert_email import send_alert_email
                send_alert_email(severity, category, message)
            except Exception:
                pass

        # Speak critical and high alerts immediately
        if severity in ("critical", "high"):
            try:
                from config.settings import VOICE_ENABLED, IS_RAILWAY, VOICE_LOCAL_PLAYBACK
                if VOICE_ENABLED and not IS_RAILWAY:
                    import threading

                    def _speak_alert():
                        try:
                            from services.elevenlabs_voice import speak_with_mode, generate_for_network
                            text = f"Alert. {message}"
                            speak_with_mode(text, mode="combat", play=VOICE_LOCAL_PLAYBACK)
                            generate_for_network(text)
                        except Exception:
                            pass

                    threading.Thread(target=_speak_alert, daemon=True).start()
            except Exception:
                pass

            # Also push to Telegram, if configured
            try:
                import threading
                from services.messaging import telegram_bot
                if telegram_bot.is_configured():
                    threading.Thread(
                        target=telegram_bot.send_alert_sync, args=(message,), daemon=True
                    ).start()
            except Exception:
                pass

        # Critical alerts also place an actual phone call, if Twilio is
        # configured — a Telegram push or HUD toast is easy to miss;
        # "JARVIS is calling you" is not.
        if severity == "critical":
            try:
                import threading
                import os
                from services.phone import phone, _twilio_configured
                to_number = os.getenv("MY_PHONE_NUMBER", "")
                if _twilio_configured() and to_number:
                    threading.Thread(
                        target=phone.send_alert_call, args=(message, to_number), daemon=True
                    ).start()
            except Exception:
                pass

    def system(self, message: str):
        self.publish("system", {"message": message})

    def chat(self, role: str, content: str):
        self.publish("chat", {"role": role, "content": content})


# Singleton
bus = EventBus()
