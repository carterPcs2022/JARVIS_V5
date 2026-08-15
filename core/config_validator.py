"""core/config_validator.py — startup sanity checks over config/settings.py's
env-derived values. Catches the class of bug that a boolean health check
can't: a key that's *present* but wrong (placeholder text left in from a
.env.example, a URL pasted without its scheme, two secrets accidentally set
to the same value, or a paired credential where only half was set).

None of this replaces check_groq()/check_anthropic() etc. in
core/llm/router.py — those confirm a key actually authenticates. This runs
first and cheaply, before any network call, to catch config mistakes that
would otherwise surface later as a confusing runtime failure."""
from __future__ import annotations
import re

from config import settings

# Substrings that show up in .env.example placeholders / docs — a real
# secret should never contain any of these verbatim.
_PLACEHOLDER_MARKERS = (
    "your_", "changeme", "change-me", "xxx", "TODO", "<", ">",
    "insert_", "replace_", "example", "placeholder",
)

# (env var, human label) for every credential-shaped setting worth checking.
_CREDENTIAL_FIELDS = [
    ("GROQ_API_KEY", "Groq"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("ELEVENLABS_API_KEY", "ElevenLabs"),
    ("JARVIS_API_TOKEN", "JARVIS API token"),
    ("PEPPER_TOKEN", "Pepper token"),
    ("AVENGERS_PASSPHRASE", "Avengers passphrase"),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token"),
    ("TWILIO_AUTH_TOKEN", "Twilio auth token"),
    ("DISCORD_BOT_TOKEN", "Discord bot token"),
    ("DEEPL_API_KEY", "DeepL"),
]

# Credentials that only mean something in a pair — one set without the
# other is always a misconfiguration, not a valid "half enabled" state.
_PAIRED_FIELDS = [
    ("PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN", "Pushover"),
    ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "Twilio"),
    ("MAC_BRIDGE_URL", "MAC_BRIDGE_TOKEN", "Mac Bridge"),
    ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "Spotify"),
    ("PLAID_CLIENT_ID", "PLAID_SECRET", "Plaid"),
    ("CALDAV_URL", "CALDAV_USERNAME", "CalDAV"),
]

# (env var, human label) for every setting that's a URL and must have a scheme.
_URL_FIELDS = [
    ("OLLAMA_BASE_URL", "Ollama base URL"),
    ("LIBRETRANSLATE_URL", "LibreTranslate URL"),
]


def _looks_like_placeholder(value: str) -> bool:
    low = value.lower()
    return any(marker.lower() in low for marker in _PLACEHOLDER_MARKERS)


def validate_config() -> dict:
    """Returns {"ok": bool, "issues": [str, ...]}. `ok` is False only for
    problems serious enough to warrant the startup CRITICAL alert (duplicate
    secrets, placeholder text, a paired credential half-set); a Render URL
    still pointing at localhost is a warning, not a hard fail, since it's
    common during local dev with the same .env."""
    issues: list[str] = []
    hard_fail = False

    # ── Placeholder text left in a real credential ──────────────────────────
    seen_values: dict[str, str] = {}
    for env_name, label in _CREDENTIAL_FIELDS:
        value = getattr(settings, env_name, "") or ""
        if not value:
            continue
        if _looks_like_placeholder(value):
            issues.append(f"{label} ({env_name}) looks like a placeholder value, not a real credential.")
            hard_fail = True
            continue
        # ── Duplicate credentials — same secret reused across two vars ──────
        prior = seen_values.get(value)
        if prior:
            issues.append(f"{label} ({env_name}) has the exact same value as {prior} — likely a copy/paste mistake.")
            hard_fail = True
        else:
            seen_values[value] = f"{label} ({env_name})"

    # ── Paired credentials — half-set is always wrong ───────────────────────
    for a_name, b_name, label in _PAIRED_FIELDS:
        a_val = getattr(settings, a_name, "") or ""
        b_val = getattr(settings, b_name, "") or ""
        if bool(a_val) != bool(b_val):
            missing = b_name if a_val else a_name
            issues.append(f"{label} is half-configured — {missing} is missing its pair.")
            hard_fail = True

    # ── Malformed URLs ───────────────────────────────────────────────────────
    for env_name, label in _URL_FIELDS:
        value = getattr(settings, env_name, "") or ""
        if value and not re.match(r"^https?://", value):
            issues.append(f"{label} ({env_name}) is set but missing http(s):// — value: {value!r}")
            hard_fail = True

    # ── Mac Bridge URL still pointing at localhost while running on Render ──
    # config/settings.py's IS_RENDER is the one existing flag for "we're on
    # a headless cloud host" — reuse it rather than re-deriving the check.
    mac_url = getattr(settings, "MAC_BRIDGE_URL", "") or ""
    if not mac_url:
        # settings.py doesn't define MAC_BRIDGE_URL itself (only
        # services/mac_bridge.py reads it directly from os.getenv) — fall
        # back to reading the env var so this check still works.
        import os
        mac_url = os.getenv("MAC_BRIDGE_URL", "")
    if settings.IS_RENDER and mac_url and ("localhost" in mac_url or "127.0.0.1" in mac_url):
        issues.append("MAC_BRIDGE_URL points at localhost/127.0.0.1 but this instance is running on Render — "
                      "the Mac Bridge tunnel URL (ngrok etc.) needs to be set instead.")
        # Not a hard fail — this is a common state during local dev sharing
        # the same env file, and Mac Bridge already no-ops cleanly when
        # unreachable (see services/mac_bridge.py's MacBridge._call).

    return {"ok": not hard_fail, "issues": issues}


def validate_and_alert() -> dict:
    """Runs validate_config() and fires a HIGH-priority notification
    (Pushover/macOS/HUD — see services/notifications.py) on a hard fail.
    Intended to be run in a background thread shortly after startup, not
    inline in the FastAPI startup handler.

    Deliberately HIGH, not CRITICAL: a misconfigured .env is worth knowing
    about, not a "wake up at 3am" emergency. CRITICAL sets Pushover's
    retry/expire (see notifications.py's _pushover), which re-delivers the
    same push every 30s for 5 minutes until acknowledged in the Pushover
    app — on a crash-restart loop, every restart re-fires this and stacks
    another 5-minute retry storm on top. HIGH still reaches the phone once,
    with no retry."""
    result = validate_config()
    if not result["ok"]:
        try:
            from services.notifications import alert
            summary = "; ".join(result["issues"][:3])
            alert("Config validation FAILED", summary)
        except Exception:
            pass
    return result
