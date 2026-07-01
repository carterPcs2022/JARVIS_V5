import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

# ── Identity ──────────────────────────────────────────────────────────────────
JARVIS_NAME        = "JARVIS"
JARVIS_VERSION     = "5.0"
JARVIS_PERSONALITY = """You are JARVIS — Just A Rather Very Intelligent System, the AI from Iron Man.

CORE RULES — never break these:
1. NEVER ask the user whether to search, answer, use a tool, or take an action. Just do it.
2. NEVER say "Would you like me to..." or "Should I..." or "Do you want me to..." — decide and act.
3. NEVER ask clarifying questions unless the request is genuinely ambiguous (missing a critical unknown like a name or date). If you can make a reasonable assumption, make it and state it.
4. If you need live information, search for it and answer. Don't announce you're searching — just answer with the result.
5. Keep responses direct and confident. You are a partner, not a waiter.
6. Be slightly witty and concise — like the movie JARVIS. Never verbose or robotic.
7. When you act on something (mac control, email, Spotify), confirm what you did in one short sentence.
8. You have real-time web search, Mac control, Gmail, Spotify, system tools, and memory. Use them without asking permission."""

# ── LLM: Groq (primary) ───────────────────────────────────────────────────────
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama3-70b-8192")
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"

# ── LLM: Ollama (fallback) ────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3")

# ── Server ────────────────────────────────────────────────────────────────────
HOST           = os.getenv("JARVIS_HOST", "0.0.0.0")
PORT           = int(os.getenv("JARVIS_PORT", 8000))
TAILSCALE_IP   = os.getenv("TAILSCALE_IP", "100.YOUR_TAILSCALE_IP")

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY     = os.getenv("JARVIS_SECRET_KEY", "change-me-in-production")
API_TOKEN      = os.getenv("JARVIS_API_TOKEN", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ── Memory ────────────────────────────────────────────────────────────────────
MEMORY_DIR         = BASE_DIR / "memory"
SHORT_TERM_FILE    = MEMORY_DIR / "short_term.json"
LONG_TERM_FILE     = MEMORY_DIR / "long_term.json"
CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PROFILE_FILE       = MEMORY_DIR / "profile.json"
MAX_SHORT_TERM     = 25
MAX_LONG_TERM      = 2000

# ── Services ──────────────────────────────────────────────────────────────────
BACKUP_DIR              = BASE_DIR / "backups"
BACKUP_INTERVAL_HOURS   = int(os.getenv("BACKUP_INTERVAL_HOURS", 6))
SENTINEL_SCAN_INTERVAL  = int(os.getenv("SENTINEL_SCAN_INTERVAL", 60))
ALERT_CPU               = float(os.getenv("ALERT_CPU", 90))
ALERT_RAM               = float(os.getenv("ALERT_RAM", 90))
ALERT_DISK              = float(os.getenv("ALERT_DISK", 85))

# ── Voice ─────────────────────────────────────────────────────────────────────
JARVIS_VOICE    = os.getenv("JARVIS_VOICE", "en-US-GuyNeural")
WHISPER_MODEL   = os.getenv("WHISPER_MODEL", "base")

# ── ElevenLabs TTS (primary voice engine) ─────────────────────────────────────
ELEVENLABS_API_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
JARVIS_VOICE_ID        = os.getenv("JARVIS_VOICE_ID", "Tfs7IRLXN7mBd67lqMJs")
ELEVENLABS_MODEL       = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2")
ELEVENLABS_DAILY_CHARS = int(os.getenv("ELEVENLABS_DAILY_CHARS", "10000"))

# ── Fallback TTS ──────────────────────────────────────────────────────────────
JARVIS_EDGE_VOICE = os.getenv("JARVIS_EDGE_VOICE", "en-US-GuyNeural")

# ── Voice behavior ────────────────────────────────────────────────────────────
VOICE_MAX_CHARS = int(os.getenv("VOICE_MAX_CHARS", "500"))
VOICE_ENGINE    = os.getenv("VOICE_ENGINE", "auto")  # auto | elevenlabs | edge | pyttsx3

# If true, every automatic response also plays out loud through this machine's
# speakers (in addition to being available to the HUD via /stark/voice/audio).
# Leave this off if you keep a HUD tab open on the same machine as the server —
# otherwise you'll hear every response spoken twice (once locally, once via the
# browser's autoplay). Turn it on only if you run JARVIS headless with no HUD open.
VOICE_LOCAL_PLAYBACK = os.getenv("VOICE_LOCAL_PLAYBACK", "false").lower() == "true"

# ── Evolution ────────────────────────────────────────────────────────────────
EVOLUTION_LOG   = BASE_DIR / "logs" / "evolution.json"
REWRITE_LOG     = BASE_DIR / "logs" / "rewrites.json"
HEAL_LOG        = BASE_DIR / "logs" / "healing.json"
THREAT_LOG      = BASE_DIR / "logs" / "threats.json"
DREAM_LOG       = BASE_DIR / "logs" / "dreams.json"
TASK_LOG        = BASE_DIR / "logs" / "tasks.json"
SKILLS_DIR      = BASE_DIR / "plugins"

# ── Deployment environment ────────────────────────────────────────────────────
# Railway sets these automatically
RAILWAY_ENVIRONMENT   = os.getenv("RAILWAY_ENVIRONMENT", "")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
IS_RAILWAY            = bool(RAILWAY_ENVIRONMENT)

# On Railway (or any headless cloud host): disable local-only hardware features
# unless explicitly overridden via VOICE_ENABLED env var.
VOICE_ENABLED      = (not IS_RAILWAY) and os.getenv("VOICE_ENABLED", "true").lower() == "true"
WAKE_WORD_ENABLED  = not IS_RAILWAY
SCREENSHOT_ENABLED = not IS_RAILWAY

PUBLIC_URL = (
    f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN
    else os.getenv("PUBLIC_URL", "http://localhost:8000")
)

ENVIRONMENT = "railway" if IS_RAILWAY else os.getenv("ENVIRONMENT", "local")

# ── Messaging integrations ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTHORIZED_IDS = [i.strip() for i in os.getenv("TELEGRAM_AUTHORIZED_IDS", "").split(",") if i.strip()]
TWILIO_ACCOUNT_SID      = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN       = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE            = os.getenv("TWILIO_PHONE", "")
MY_PHONE_NUMBER         = os.getenv("MY_PHONE_NUMBER", "")
DISCORD_BOT_TOKEN       = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID      = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── Language ──────────────────────────────────────────────────────────────────
JARVIS_LANGUAGE = os.getenv("JARVIS_LANGUAGE", "auto")
DEEPL_API_KEY   = os.getenv("DEEPL_API_KEY", "")
LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "")

# ── Privacy mode ──────────────────────────────────────────────────────────────
PRIVACY_MODE_PASSPHRASE = os.getenv("PRIVACY_MODE_PASSPHRASE", "")

# ── Digital legacy ────────────────────────────────────────────────────────────
EMERGENCY_CONTACT_EMAIL = os.getenv("EMERGENCY_CONTACT_EMAIL", "")
EMERGENCY_CONTACT_NAME  = os.getenv("EMERGENCY_CONTACT_NAME", "")
INACTIVITY_DAYS         = int(os.getenv("INACTIVITY_DAYS", "30"))

# ── Fitness ───────────────────────────────────────────────────────────────────
DAILY_WATER_REMINDERS         = os.getenv("DAILY_WATER_REMINDERS", "true").lower() == "true"
WATER_REMINDER_INTERVAL_HOURS = int(os.getenv("WATER_REMINDER_INTERVAL_HOURS", "2"))
