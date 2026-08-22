"""services/messaging.py — Talk to JARVIS from Telegram, SMS, and Discord.

Each integration is fully optional: if the relevant credentials aren't set in
.env, that channel simply doesn't start. All three route through the same
brain.process_dict() pipeline JARVIS already uses everywhere else.
"""
import os
import time
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_IDS,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE, MY_PHONE_NUMBER,
    DISCORD_BOT_TOKEN, DISCORD_AUTHORIZED_IDS,
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
#
# User-installable app (slash commands), not the old server-only on_message
# bot. This matters because Discord only delivers raw message content to a
# bot when it's guild-installed — a user-installed app (added to someone's
# own account, usable in any server or DM without a per-server invite) never
# gets message_content at all, by design, regardless of intents. Slash
# commands are the one interaction type Discord delivers the same way in
# every install context, so /ask and /status replace the old "JARVIS ..."
# text-prefix trigger rather than sitting alongside it.
#
# Discord requires an interaction be acknowledged within 3 seconds or it
# expires — brain.process_dict() routinely takes longer (LLM call + memory +
# protocol checks), so every command defers first (shows "JARVIS is
# thinking...") and edits in the real response once it's ready, same pattern
# Discord's own docs use for any handler backed by real work.

class JarvisDiscordBot:
    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        return bool(DISCORD_BOT_TOKEN)

    def _authorized(self, user_id: int) -> bool:
        # Same allowlist pattern as Telegram/the old on_message handler —
        # DISCORD_CHANNEL_ID no longer applies (a user-install has no
        # single "home" channel; it can be invoked from any server or DM),
        # so this is now the only gate. Unset means "not opted in", same
        # convention as every other optional gate in this codebase — set
        # it before relying on this being locked down.
        return not DISCORD_AUTHORIZED_IDS or str(user_id) in DISCORD_AUTHORIZED_IDS

    def start(self):
        if not self.is_configured():
            print("[Discord] DISCORD_BOT_TOKEN not set — skipping.")
            return
        try:
            import discord
            from discord import app_commands
        except ImportError:
            print("[Discord] discord.py not installed.")
            return

        # No message_content intent — slash commands don't need it, and a
        # user-installed app can't read message content in guilds it
        # doesn't own anyway, so requesting it here would be a no-op at
        # best and a misleading permission ask at worst.
        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)
        self._client = client

        # allowed_installs / allowed_contexts are separate stacking
        # decorators in this discord.py version (2.7.x) — not kwargs on
        # .command() itself, confirmed against the installed version
        # rather than assumed. installs(users=True) is what actually lifts
        # the "only in servers it's invited to" limitation this rewrite
        # exists to fix; contexts opens it up to guilds, DMs, and group DMs.

        @tree.command(name="ask", description="Ask JARVIS anything")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        @app_commands.describe(message="What do you want to ask JARVIS?")
        async def ask(interaction: discord.Interaction, message: str):
            if not self._authorized(interaction.user.id):
                await interaction.response.send_message("Unauthorized.", ephemeral=True)
                return
            await interaction.response.defer()  # avoids the 3s interaction timeout
            from core.brain_v2 import brain
            result = brain.process_dict(message)
            response = result["response"]
            # Discord hard-caps a single message at 2000 chars — brain
            # responses (status dumps, long reasoning) can exceed that, and
            # an unguarded send would just raise and silently drop the
            # reply. Chunk instead of truncating so nothing gets lost.
            chunks = [response[i:i + 2000] for i in range(0, len(response), 2000)] or [""]
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.channel.send(chunk)

        @tree.command(name="status", description="JARVIS system status check")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def status(interaction: discord.Interaction):
            if not self._authorized(interaction.user.id):
                await interaction.response.send_message("Unauthorized.", ephemeral=True)
                return
            await interaction.response.defer()
            try:
                from core.tools.system import snapshot
                from core.state import state as _state
                s = snapshot()
                groq_ok = _state.any_model_available("groq")
                text = (
                    f"**JARVIS Status**\n"
                    f"CPU: {s['cpu_percent']}%  |  RAM: {s['ram_used_pct']}%  |  "
                    f"Disk: {s['disk_used_pct']}%\n"
                    f"Uptime: {s['uptime_hours']:.1f}h\n"
                    f"Groq: {'✓ online' if groq_ok else '✗ unavailable'}"
                )
            except Exception as e:
                text = f"Status check failed: {e}"
            await interaction.followup.send(text)

        @client.event
        async def on_ready():
            # Slash commands need an explicit sync before Discord will show
            # them — without this, /ask and /status silently never appear
            # in the picker even though the code registering them ran fine.
            try:
                synced = await tree.sync()
                print(f"[Discord] Synced {len(synced)} slash command(s).")
            except Exception as e:
                print(f"[Discord] Command sync failed: {e}")

        # client.run() blocks until the bot disconnects/errors, then raises
        # if that wasn't a clean shutdown. Production logs show this dying
        # on discord.errors.HTTPException: 429 Too Many Requests — not
        # Discord's own rate limiting but Cloudflare (which fronts
        # discord.com) temporarily blocking the login request, seen
        # correlating with how often the host process itself restarts
        # (each restart = a fresh login attempt from this thread). Before
        # this retry loop, that exception had no handler at all: it killed
        # this daemon thread silently, and Discord stayed dead for the rest
        # of that process's life — the only way it came back was the next
        # unrelated full app restart. Retrying with backoff here means a
        # transient block recovers within the same run instead of needing
        # an external restart. A bad/revoked token (LoginFailure) is a real
        # misconfiguration, not transient, so that one isn't retried.
        backoff = 60
        max_backoff = 900
        while True:
            try:
                client.run(DISCORD_BOT_TOKEN)
                return  # clean shutdown (e.g. client.close() called)
            except discord.errors.LoginFailure:
                print("[Discord] Login failed — DISCORD_BOT_TOKEN is invalid or revoked. Not retrying.")
                return
            except Exception as e:
                print(f"[Discord] client.run() failed ({e}) — retrying in {backoff}s.")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)


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
