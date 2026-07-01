"""
services/elevenlabs_voice.py — JARVIS ElevenLabs Voice Engine

TTS Priority cascade:
1. ElevenLabs eleven_turbo_v2 (cinematic, best quality)
2. edge-tts en-US-GuyNeural (free, good quality fallback)
3. pyttsx3 (offline fallback)

STT (speech-to-text) is handled separately by faster-whisper.
This file handles OUTPUT only.
"""
import os
import re
import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from config.settings import (
    ELEVENLABS_API_KEY, JARVIS_VOICE_ID, ELEVENLABS_MODEL,
    ELEVENLABS_DAILY_CHARS, VOICE_ENABLED, IS_RAILWAY, BASE_DIR,
)

CHARACTER_BUDGET_FILE = BASE_DIR / "memory" / "elevenlabs_budget.json"

# ── Lazy client ────────────────────────────────────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    try:
        from elevenlabs.client import ElevenLabs
        _client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        return _client
    except ImportError:
        raise RuntimeError("elevenlabs not installed. Run: pip install elevenlabs")


# ── Text cleaning for voice ─────────────────────────────────────────────────────

def clean_for_voice(text: str, max_chars: int = 500) -> str:
    """Clean text for natural spoken output. Remove markdown, truncate, fix punctuation."""
    if not text:
        return ""

    text = re.sub(r"```[\s\S]*?```", "", text)              # code blocks
    text = re.sub(r"`[^`]+`", "", text)                      # inline code
    text = re.sub(r"#{1,6}\s", "", text)                      # headers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)      # bold/italic
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)     # links
    text = re.sub(r"[-*•]\s", "", text)                       # list bullets
    text = re.sub(r"\n+", " ", text)                          # newlines -> space
    text = re.sub(r"\s+", " ", text)                          # normalize spaces

    # Expand abbreviations for natural speech
    for abbr, spoken in [
        ("CPU", "C P U"), ("RAM", "ram"), ("API", "A P I"), ("HUD", "hud"),
        ("IP", "I P"), ("URL", "U R L"), ("TTS", "T T S"), ("LLM", "L L M"),
    ]:
        text = text.replace(abbr, spoken)

    if len(text) > max_chars:
        truncated = text[:max_chars]
        last_end = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last_end > max_chars * 0.6:
            text = text[:last_end + 1]
        else:
            text = truncated.rstrip() + "..."

    return text.strip()


# ── Character budget tracking ───────────────────────────────────────────────────

def _track_chars(char_count: int) -> int:
    CHARACTER_BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    budget = {}
    if CHARACTER_BUDGET_FILE.exists():
        try:
            budget = json.loads(CHARACTER_BUDGET_FILE.read_text())
        except Exception:
            budget = {}
    if budget.get("date") != today:
        budget = {"date": today, "chars_used": 0}
    budget["chars_used"] += char_count
    CHARACTER_BUDGET_FILE.write_text(json.dumps(budget))
    return budget["chars_used"]


def _check_budget(text: str) -> bool:
    """Return True if we have budget to speak this text via ElevenLabs."""
    char_count = len(text)
    today = date.today().isoformat()
    try:
        budget = json.loads(CHARACTER_BUDGET_FILE.read_text())
        if budget.get("date") == today:
            used = budget.get("chars_used", 0)
            if used + char_count > ELEVENLABS_DAILY_CHARS:
                print(f"[ElevenLabs] Daily budget reached "
                      f"({used}/{ELEVENLABS_DAILY_CHARS} chars). Falling back to edge-tts.")
                return False
    except Exception:
        pass
    return True


def get_budget_status() -> dict:
    today = date.today().isoformat()
    used = 0
    try:
        budget = json.loads(CHARACTER_BUDGET_FILE.read_text())
        if budget.get("date") == today:
            used = budget.get("chars_used", 0)
    except Exception:
        pass
    return {
        "chars_used":  used,
        "chars_limit": ELEVENLABS_DAILY_CHARS,
        "pct_used":    round(used / ELEVENLABS_DAILY_CHARS * 100, 1) if ELEVENLABS_DAILY_CHARS else 0,
        "date":        today,
    }


# ── ElevenLabs TTS ───────────────────────────────────────────────────────────────

def speak_elevenlabs(text: str, play: bool = True, output_path: str | None = None) -> str:
    """
    Generate speech with ElevenLabs and optionally play it.
    Returns path to generated audio file, or "" on failure.
    """
    if not VOICE_ENABLED or IS_RAILWAY:
        return ""

    cleaned = clean_for_voice(text)
    if not cleaned:
        return ""

    if not _check_budget(cleaned):
        return ""

    path = output_path or tempfile.mktemp(suffix=".mp3")

    try:
        client = _get_client()
        audio_bytes = b"".join(
            client.text_to_speech.convert(
                voice_id=JARVIS_VOICE_ID,
                text=cleaned,
                model_id=ELEVENLABS_MODEL,
                voice_settings={
                    "stability":         0.5,
                    "similarity_boost":  0.85,
                    "style":             0.3,
                    "use_speaker_boost": True,
                }
            )
        )
        with open(path, "wb") as f:
            f.write(audio_bytes)

        _track_chars(len(cleaned))

        if play:
            _play_audio(path)

        return path

    except RuntimeError as e:
        print(f"[ElevenLabs] {e}")
        return ""
    except Exception as e:
        print(f"[ElevenLabs] TTS failed: {e}")
        return ""


def speak_elevenlabs_stream(text: str) -> bool:
    """Stream ElevenLabs audio directly to speakers. Lower first-byte latency."""
    if not VOICE_ENABLED or IS_RAILWAY:
        return False

    cleaned = clean_for_voice(text)
    if not cleaned or not _check_budget(cleaned):
        return False

    try:
        client = _get_client()
        audio_stream = client.text_to_speech.convert_as_stream(
            voice_id=JARVIS_VOICE_ID,
            text=cleaned,
            model_id=ELEVENLABS_MODEL,
        )

        path = tempfile.mktemp(suffix=".mp3")
        with open(path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)

        _track_chars(len(cleaned))
        _play_audio(path)

        try:
            os.unlink(path)
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"[ElevenLabs Stream] Failed: {e}")
        return False


def generate_for_network(text: str, output_path: str | None = None) -> str:
    """
    Generate audio file so any device on the network can play it
    via GET /stark/voice/audio. Returns file path or "".
    """
    output_path = output_path or str(BASE_DIR / "static_voice.mp3")
    cleaned = clean_for_voice(text, max_chars=800)
    if not cleaned or not VOICE_ENABLED or IS_RAILWAY:
        return ""
    if not _check_budget(cleaned):
        return ""

    try:
        client = _get_client()
        audio_bytes = b"".join(
            client.text_to_speech.convert(
                voice_id=JARVIS_VOICE_ID,
                text=cleaned,
                model_id=ELEVENLABS_MODEL,
            )
        )
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        _track_chars(len(cleaned))
        return output_path
    except Exception as e:
        print(f"[ElevenLabs Network] Failed: {e}")
        return ""


# ── Voice modes ──────────────────────────────────────────────────────────────────

VOICE_MODE_SETTINGS = {
    "normal":   {"model_id": "eleven_turbo_v2",       "stability": 0.5, "similarity": 0.85, "style": 0.3},
    "combat":   {"model_id": "eleven_turbo_v2",       "stability": 0.8, "similarity": 0.9,  "style": 0.0},
    "workshop": {"model_id": "eleven_multilingual_v2", "stability": 0.3, "similarity": 0.85, "style": 0.4},
    "night":    {"model_id": "eleven_turbo_v2",       "stability": 0.7, "similarity": 0.8,  "style": 0.1},
    "brief":    {"model_id": "eleven_turbo_v2",       "stability": 0.6, "similarity": 0.85, "style": 0.2},
    "social":   {"model_id": "eleven_turbo_v2",       "stability": 0.4, "similarity": 0.85, "style": 0.4},
    "stealth":  {"model_id": "eleven_turbo_v2",       "stability": 0.5, "similarity": 0.85, "style": 0.3},
}


def speak_with_mode(text: str, mode: str = "normal", play: bool = True) -> str:
    """Speak with ElevenLabs settings tuned for the current voice mode.
    Falls back to the full engine cascade on any failure.

    play=False generates the audio (for network/HUD playback via
    generate_for_network or the returned path) without also sounding it
    through the server's local speakers — use this when a HUD/browser is
    expected to play the audio itself, to avoid hearing every response twice."""
    if not VOICE_ENABLED or IS_RAILWAY:
        return ""

    cleaned = clean_for_voice(text)
    if not cleaned:
        return ""

    settings = VOICE_MODE_SETTINGS.get(mode, VOICE_MODE_SETTINGS["normal"])

    if not _check_budget(cleaned):
        if not play:
            return ""
        from services.voice import speak
        return speak(text)

    try:
        client = _get_client()
        audio_bytes = b"".join(
            client.text_to_speech.convert(
                voice_id=JARVIS_VOICE_ID,
                text=cleaned,
                model_id=settings["model_id"],
                voice_settings={
                    "stability":        settings["stability"],
                    "similarity_boost": settings["similarity"],
                    "style":            settings["style"],
                }
            )
        )
        path = tempfile.mktemp(suffix=".mp3")
        with open(path, "wb") as f:
            f.write(audio_bytes)
        _track_chars(len(cleaned))
        if play:
            _play_audio(path)
        return path
    except Exception as e:
        print(f"[ElevenLabs Mode] {mode} failed: {e}")
        if not play:
            return ""
        from services.voice import speak
        return speak(text)


# ── Audio playback ────────────────────────────────────────────────────────────────

def _play_audio(path: str) -> bool:
    """Play an audio file. Cross-platform: afplay (Mac) -> mpg123/aplay/ffplay (Linux) -> pygame."""
    if not Path(path).exists():
        return False

    try:
        result = subprocess.run(["afplay", path], capture_output=True, timeout=60)
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    for player in [["mpg123", "-q", path], ["aplay", path], ["ffplay", "-nodisp", "-autoexit", path]]:
        try:
            result = subprocess.run(player, capture_output=True, timeout=60)
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        return True
    except Exception:
        pass

    print(f"[Voice] Could not play audio: {path}")
    return False


# ── ElevenLabs utilities ──────────────────────────────────────────────────────────

def list_voices() -> list[dict]:
    try:
        client = _get_client()
        voices = client.voices.get_all()
        return [
            {"id": v.voice_id, "name": v.name, "category": v.category, "labels": v.labels}
            for v in voices.voices
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_usage() -> dict:
    """Check ElevenLabs character usage. Prefers the account-level API (needs the
    `user_read` API key permission); falls back to our own local daily tracker,
    which always works regardless of key scope."""
    result = {"daily_budget": get_budget_status()}
    try:
        client = _get_client()
        info = client.user.get()
        sub = info.subscription
        result.update({
            "characters_used":      sub.character_count,
            "characters_limit":     sub.character_limit,
            "characters_remaining": sub.character_limit - sub.character_count,
            "pct_used":  round(sub.character_count / sub.character_limit * 100, 1) if sub.character_limit else 0,
            "tier":      sub.tier,
            "next_reset": str(sub.next_character_count_reset_unix),
        })
    except Exception as e:
        msg = str(e)
        if "missing_permissions" in msg or "user_read" in msg:
            result["account_api"] = "unavailable — API key lacks the user_read permission (local daily tracker below still works)"
        else:
            result["account_api_error"] = msg
    return result


def is_available() -> bool:
    """Quick check — is ElevenLabs configured and reachable?"""
    if not ELEVENLABS_API_KEY:
        return False
    try:
        _get_client()
        return True
    except Exception:
        return False
