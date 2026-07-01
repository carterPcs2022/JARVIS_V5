"""services/messaging.py — Talk to JARVIS from Telegram, SMS, and Discord.

Each integration is fully optional: if the relevant credentials aren't set in
.env, that channel simply doesn't start. All three route through the same
brain.process_dict() pipeline JARVIS already uses everywhere else.
"""
import os
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_IDS,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE, MY_PHONE_NUMBER,
    DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID,
)


# ── Telegram ───────────────────────────────────────────────────────────────────

class TelegramBot:
    def __init__(self):
        self._app = None

    def is_configured(self) -> bool:
        return bool(TELEGRAM_BOT_TOKEN)

    def start(self):
        """Start polling in the current thread. Call from a background thread."""
        if not self.is_configured():
            print("[Telegram] TELEGRAM_BOT_TOKEN not set — skipping.")
            return
        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            print("[Telegram] python-telegram-bot not installed.")
            return

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self._app = app
        app.run_polling(close_loop=False)

    async def handle_message(self, update, context):
        chat_id = str(update.effective_chat.id)

        if TELEGRAM_AUTHORIZED_IDS and chat_id not in TELEGRAM_AUTHORIZED_IDS:
            await update.message.reply_text("Unauthorized.")
            return

        text = update.message.text
        from core.brain_v2 import brain
        result = brain.process_dict(text)
        response = result["response"]

        await update.message.reply_text(response)

        try:
            from services.elevenlabs_voice import generate_for_network
            audio_path = generate_for_network(response)
            if audio_path and os.path.exists(audio_path):
                with open(audio_path, "rb") as f:
                    await update.message.reply_voice(f)
        except Exception:
            pass

    async def send_alert(self, message: str, chat_id: str | None = None):
        """Push an alert to Telegram from anywhere in JARVIS."""
        if not self.is_configured():
            return
        target = chat_id or (TELEGRAM_AUTHORIZED_IDS[0] if TELEGRAM_AUTHORIZED_IDS else None)
        if not target:
            return
        try:
            from telegram import Bot
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=target, text=f"⚡ JARVIS: {message}")
        except Exception as e:
            print(f"[Telegram] send_alert failed: {e}")

    def send_alert_sync(self, message: str, chat_id: str | None = None):
        """Fire-and-forget alert from synchronous code (e.g. event_bus)."""
        if not self.is_configured():
            return
        try:
            import asyncio
            asyncio.run(self.send_alert(message, chat_id))
        except Exception as e:
            print(f"[Telegram] send_alert_sync failed: {e}")


telegram_bot = TelegramBot()


# ── SMS via Twilio ─────────────────────────────────────────────────────────────

def sms_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE)


def send_sms(message: str, to: str | None = None) -> dict:
    """Send SMS via Twilio."""
    if not sms_configured():
        return {"ok": False, "error": "Twilio not configured"}
    to = to or MY_PHONE_NUMBER
    if not to:
        return {"ok": False, "error": "No destination phone number"}
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(body=f"JARVIS: {message[:1500]}", from_=TWILIO_PHONE, to=to)
        return {"ok": True, "sid": msg.sid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_incoming_sms(from_number: str, body: str) -> str:
    """Process an incoming SMS through the brain and return the reply text
    (caller is responsible for sending it back, e.g. via TwiML or send_sms)."""
    from core.brain_v2 import brain
    result = brain.process_dict(body)
    return result["response"]


# ── Discord ────────────────────────────────────────────────────────────────────

class JarvisDiscordBot:
    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        return bool(DISCORD_BOT_TOKEN)

    def start(self):
        if not self.is_configured():
            print("[Discord] DISCORD_BOT_TOKEN not set — skipping.")
            return
        try:
            import discord
        except ImportError:
            print("[Discord] discord.py not installed.")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_message(message):
            if message.author == client.user:
                return
            if DISCORD_CHANNEL_ID and message.channel.id != DISCORD_CHANNEL_ID:
                return
            if not message.content.upper().startswith("JARVIS"):
                return

            prompt = message.content[6:].strip()
            from core.brain_v2 import brain
            result = brain.process_dict(prompt)

            async with message.channel.typing():
                await message.reply(result["response"])

        client.run(DISCORD_BOT_TOKEN)


discord_bot = JarvisDiscordBot()


def start_all_background():
    """Start all configured messaging integrations in daemon threads."""
    import threading
    if telegram_bot.is_configured():
        threading.Thread(target=telegram_bot.start, daemon=True).start()
        print("[Messaging] Telegram bot starting...")
    if discord_bot.is_configured():
        threading.Thread(target=discord_bot.start, daemon=True).start()
        print("[Messaging] Discord bot starting...")
    if not telegram_bot.is_configured() and not discord_bot.is_configured():
        print("[Messaging] No Telegram/Discord tokens configured — skipping both.")
