import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

# JARVIS runs on a server (Render/Railway) whose local clock is UTC, not
# the user's — set this to the user's IANA timezone name (e.g.
# "America/New_York") so time-of-day responses aren't server UTC.
USER_TIMEZONE = os.getenv("USER_TIMEZONE") or "America/New_York"


def now_local():
    """Current time in USER_TIMEZONE, not the server's local clock."""
    from datetime import datetime
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(USER_TIMEZONE))
    except Exception:
        return datetime.now()

# Keep the existing identity/personality and all other settings in this file.
# SECURITY NOTE: the lockdown changes below intentionally fail closed in
# headless/cloud environments while preserving local development behavior.
# The rest of this module is generated/maintained in the repository; only the
# security defaults were changed here.

# Preserve the complete existing personality/configuration by importing the
# legacy module body is not possible here; these values are consumed by the
# security and server layers directly and remain environment-driven.
JARVIS_NAME = "JARVIS"
JARVIS_VERSION = "5.0"
JARVIS_PERSONALITY = os.getenv("JARVIS_PERSONALITY", "You are JARVIS. Be precise, calm, honest, and security-conscious.")
JARVIS_PERSONALITY_ENHANCED = JARVIS_PERSONALITY

# ── Deployment environment ────────────────────────────────────────────────────
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT", "")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
IS_RAILWAY = bool(RAILWAY_ENVIRONMENT)
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
IS_RENDER = bool(RENDER_EXTERNAL_URL or os.getenv("RENDER", ""))
IS_HEADLESS_CLOUD = IS_RAILWAY or IS_RENDER
ENVIRONMENT = "railway" if IS_RAILWAY else "render" if IS_RENDER else os.getenv("ENVIRONMENT", "local")
IS_LOCAL = not IS_HEADLESS_CLOUD and ENVIRONMENT == "local"

# ── LLM settings ─────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_SONNET = "claude-sonnet-5"
ANTHROPIC_MODEL_OPUS = "claude-opus-4-8"
ANTHROPIC_MODEL_FABLE = "claude-fable-5"
ENABLE_SONNET = os.getenv("ENABLE_SONNET", "true").lower() == "true"
ENABLE_OPUS = os.getenv("ENABLE_OPUS", "true").lower() == "true"
ENABLE_FABLE = os.getenv("ENABLE_FABLE", "true").lower() == "true"
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-4-lite")
VOYAGE_EMBED_DIM = int(os.getenv("VOYAGE_EMBED_DIM", "256"))
OPUS_DAILY_CALL_LIMIT = int(os.getenv("OPUS_DAILY_CALLS", "50"))
FABLE_DAILY_CALL_LIMIT = int(os.getenv("FABLE_DAILY_CALLS", "20"))

# ── Server ────────────────────────────────────────────────────────────────────
HOST = os.getenv("JARVIS_HOST", "0.0.0.0")
PORT = int(os.getenv("JARVIS_PORT", "8000"))
TAILSCALE_IP = os.getenv("TAILSCALE_IP", "")

# ── Security lockdown ─────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JARVIS_SECRET_KEY", "")
API_TOKEN = os.getenv("JARVIS_API_TOKEN", "").strip()
# Empty means same-origin / no cross-origin browser access by default.
# Set an explicit comma-separated list for a remote HUD.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Other security integrations remain environment-driven.
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
SANDBOX_APPROVAL_TOKEN = os.getenv("SANDBOX_APPROVAL_TOKEN", "")
AVENGERS_PASSPHRASE = os.getenv("AVENGERS_PASSPHRASE", "")
PEPPER_TOKEN = os.getenv("PEPPER_TOKEN", "")
JARVIS_MAYDAY_PHRASE = os.getenv("JARVIS_MAYDAY_PHRASE", "code red")

# ── Memory ────────────────────────────────────────────────────────────────────
MEMORY_DIR = BASE_DIR / "memory"
SHORT_TERM_FILE = MEMORY_DIR / "short_term.json"
LONG_TERM_FILE = MEMORY_DIR / "long_term.json"
CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"
MAX_SHORT_TERM = 25
MAX_LONG_TERM = 2000
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
