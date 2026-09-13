import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
USER_TIMEZONE = os.getenv("USER_TIMEZONE") or "America/New_York"


def now_local():
    from datetime import datetime
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(USER_TIMEZONE))
    except Exception:
        return datetime.now()

# Identity
JARVIS_NAME = "JARVIS"
JARVIS_VERSION = "5.0"
JARVIS_PERSONALITY = os.getenv(
    "JARVIS_PERSONALITY",
    "You are JARVIS. Be precise, calm, honest, technically capable, and security-conscious."
)
STARK_INTELLIGENCE_PROTOCOLS = os.getenv("STARK_INTELLIGENCE_PROTOCOLS", "")
JARVIS_PERSONALITY_ENHANCED = JARVIS_PERSONALITY + STARK_INTELLIGENCE_PROTOCOLS

# Deployment environment
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT", "")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
IS_RAILWAY = bool(RAILWAY_ENVIRONMENT)
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
IS_RENDER = bool(RENDER_SERVICE_ID or RENDER_EXTERNAL_URL or os.getenv("RENDER", ""))
IS_HEADLESS_CLOUD = IS_RAILWAY or IS_RENDER
ENVIRONMENT = "railway" if IS_RAILWAY else "render" if IS_RENDER else os.getenv("ENVIRONMENT", "local")
IS_LOCAL = not IS_HEADLESS_CLOUD and ENVIRONMENT == "local"

# LLMs
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_SONNET = os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-5")
ANTHROPIC_MODEL_OPUS = os.getenv("ANTHROPIC_MODEL_OPUS", "claude-opus-4-8")
ANTHROPIC_MODEL_FABLE = os.getenv("ANTHROPIC_MODEL_FABLE", "claude-fable-5")
ENABLE_SONNET = os.getenv("ENABLE_SONNET", "true").lower() == "true"
ENABLE_OPUS = os.getenv("ENABLE_OPUS", "true").lower() == "true"
ENABLE_FABLE = os.getenv("ENABLE_FABLE", "true").lower() == "true"
ENABLE_REASONING_ENGINES = os.getenv("ENABLE_REASONING_ENGINES", "true").lower() == "true"
SONNET_DAILY_CALL_LIMIT = int(os.getenv("SONNET_DAILY_CALLS", "100"))
OPUS_DAILY_CALL_LIMIT = int(os.getenv("OPUS_DAILY_CALLS", "50"))
FABLE_DAILY_CALL_LIMIT = int(os.getenv("FABLE_DAILY_CALLS", "20"))
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-4-lite")
VOYAGE_EMBED_DIM = int(os.getenv("VOYAGE_EMBED_DIM", "256"))

# Astra is intentionally opt-in and reads its API key directly in core/llm/astra.py.
ASTRA_ENABLED = os.getenv("ASTRA_ENABLED", "false").lower() == "true"
ASTRA_MODEL = os.getenv("ASTRA_MODEL", "gpt-6-astra")

# Server
HOST = os.getenv("JARVIS_HOST", "0.0.0.0")
PORT = int(os.getenv("JARVIS_PORT", "8000"))
TAILSCALE_IP = os.getenv("TAILSCALE_IP", "")

# Security: fail closed in cloud environments.
SECRET_KEY = os.getenv("JARVIS_SECRET_KEY", "")
API_TOKEN = os.getenv("JARVIS_API_TOKEN", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
SANDBOX_APPROVAL_TOKEN = os.getenv("SANDBOX_APPROVAL_TOKEN", "")
AVENGERS_PASSPHRASE = os.getenv("AVENGERS_PASSPHRASE", "")
PEPPER_TOKEN = os.getenv("PEPPER_TOKEN", "")
JARVIS_MAYDAY_PHRASE = os.getenv("JARVIS_MAYDAY_PHRASE", "code red")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Memory
MEMORY_DIR = BASE_DIR / "memory"
SHORT_TERM_FILE = MEMORY_DIR / "short_term.json"
LONG_TERM_FILE = MEMORY_DIR / "long_term.json"
CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"
MAX_SHORT_TERM = 25
MAX_LONG_TERM = 2000
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

# Services
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "6"))
SENTINEL_SCAN_INTERVAL = int(os.getenv("SENTINEL_SCAN_INTERVAL", "60"))
ALERT_CPU = float(os.getenv("ALERT_CPU", "90"))
ALERT_RAM = float(os.getenv("ALERT_RAM", "90"))
ALERT_DISK = float(os.getenv("ALERT_DISK", "85"))

# Combat mode
COMBAT_MODE_CONFIDENCE_THRESHOLD = float(os.getenv("COMBAT_MODE_CONFIDENCE_THRESHOLD", "0.75"))
COMBAT_MODE_SOFT_CONFIRM_MIN = float(os.getenv("COMBAT_MODE_SOFT_CONFIRM_MIN", "0.5"))
COMBAT_MODE_TIMEOUT_MINUTES = int(os.getenv("COMBAT_MODE_TIMEOUT_MINUTES", "10"))

# Google Calendar
GOOGLE_CALENDAR_CLIENT_ID = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "")
GOOGLE_CALENDAR_CLIENT_SECRET = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "")
GOOGLE_CALENDAR_REDIRECT_URI = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", "")
GOOGLE_CALENDAR_REFRESH_TOKEN = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "")

# Voice
JARVIS_VOICE = os.getenv("JARVIS_VOICE", "en-US-GuyNeural")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
JARVIS_VOICE_ID = os.getenv("JARVIS_VOICE_ID", "Tfs7IRLXN7mBd67lqMJs")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2")
ELEVENLABS_DAILY_CHARS = int(os.getenv("ELEVENLABS_DAILY_CHARS", "10000"))
JARVIS_EDGE_VOICE = os.getenv("JARVIS_EDGE_VOICE", "en-US-GuyNeural")
VOICE_MAX_CHARS = int(os.getenv("VOICE_MAX_CHARS", "500"))
VOICE_ENGINE = os.getenv("VOICE_ENGINE", "auto")
VOICE_LOCAL_PLAYBACK = os.getenv("VOICE_LOCAL_PLAYBACK", "false").lower() == "true"
_voice_env = os.getenv("VOICE_ENABLED")
VOICE_ENABLED = (_voice_env.lower() == "true") if _voice_env is not None else (not IS_HEADLESS_CLOUD)
WAKE_WORD_ENABLED = not IS_HEADLESS_CLOUD
SCREENSHOT_ENABLED = not IS_HEADLESS_CLOUD
PYTTSX3_AVAILABLE = False
FASTER_WHISPER_AVAILABLE = False
if IS_LOCAL:
    try:
        import pyttsx3  # noqa: F401
        PYTTSX3_AVAILABLE = True
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401
        FASTER_WHISPER_AVAILABLE = True
    except ImportError:
        pass

# Messaging
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTHORIZED_IDS = [i.strip() for i in os.getenv("TELEGRAM_AUTHORIZED_IDS", "").split(",") if i.strip()]
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_PHONE = os.getenv("TWILIO_PHONE", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")
DISCORD_AUTHORIZED_IDS = [i.strip() for i in os.getenv("DISCORD_AUTHORIZED_IDS", "").split(",") if i.strip()]

# Language
JARVIS_LANGUAGE = os.getenv("JARVIS_LANGUAGE", "auto")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "")

# Privacy / legacy / fitness
PRIVACY_MODE_PASSPHRASE = os.getenv("PRIVACY_MODE_PASSPHRASE", "")
EMERGENCY_CONTACT_EMAIL = os.getenv("EMERGENCY_CONTACT_EMAIL", "")
EMERGENCY_CONTACT_NAME = os.getenv("EMERGENCY_CONTACT_NAME", "")
INACTIVITY_DAYS = int(os.getenv("INACTIVITY_DAYS", "30"))
EMERGENCY_CONTACT_PHONE = os.getenv("EMERGENCY_CONTACT_PHONE", "")
DAILY_WATER_REMINDERS = os.getenv("DAILY_WATER_REMINDERS", "true").lower() == "true"
WATER_REMINDER_INTERVAL_HOURS = int(os.getenv("WATER_REMINDER_INTERVAL_HOURS", "2"))

# Stark protocols
MORGAN_PASSPHRASE = os.getenv("MORGAN_PASSPHRASE", "")
LOKI_SURPRISE_HOUR = int(os.getenv("LOKI_SURPRISE_HOUR", "9"))
SATURDAY_MAX_WORK_DAYS = int(os.getenv("SATURDAY_MAX_WORK_DAYS", "6"))
BENCHMARK_DAY = os.getenv("BENCHMARK_DAY", "sunday").lower()

# Brain enhancement
USE_SMART_ROUTING = os.getenv("USE_SMART_ROUTING", "true").lower() == "true"
USE_TOOL_CALLING = os.getenv("USE_TOOL_CALLING", "true").lower() == "true"
USE_MOA = os.getenv("USE_MOA", "false").lower() == "true"
USE_VERIFICATION = os.getenv("USE_VERIFICATION", "false").lower() == "true"
USE_REFLEXION = os.getenv("USE_REFLEXION", "false").lower() == "true"
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "2400"))
USE_BACKGROUND_PREDICTION = os.getenv("USE_BACKGROUND_PREDICTION", "false").lower() == "true"

# Evolution / audit paths
EVOLUTION_LOG = BASE_DIR / "logs" / "evolution.json"
REWRITE_LOG = BASE_DIR / "logs" / "rewrites.json"
HEAL_LOG = BASE_DIR / "logs" / "healing.json"
THREAT_LOG = BASE_DIR / "logs" / "threats.json"
DREAM_LOG = BASE_DIR / "logs" / "dreams.json"
TASK_LOG = BASE_DIR / "logs" / "tasks.json"
SKILLS_DIR = BASE_DIR / "plugins"
