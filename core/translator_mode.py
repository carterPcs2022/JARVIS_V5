"""core/translator_mode.py — Live translator mode.

When active, JARVIS stops conversing and instead relays straight
translations: every message in gets translated and handed back verbatim,
no personality, no reasoning pipeline. Two shapes:

- One-way (only target_language set): every message is translated into
  that language, whatever language it arrives in.
- Conversation (target_language + source_language both set): the same
  back-and-forth pattern phone translator apps use — each message is
  detected and sent to whichever of the two configured languages it
  ISN'T already in, so two people speaking different languages can go
  back and forth through the same session.

Translation itself is real (DeepL/LibreTranslate/LLM fallback chain via
core.language.translate) — same "no flavor caveat" exception the base
translate_text tool already gets.
"""
from datetime import datetime

from core.language import _detect_raw, translate as _translate

# Exact-match phrases checked before translation on every turn while
# active — the one channel this mode doesn't lock out. Once translator
# mode takes over, every other trigger/command in Brain.process() is
# bypassed (that's the point — it's a strict override, same as privacy
# mode), which means chat is the *only* way out for a Discord/Telegram/SMS
# user with no REST/HUD access. Without this, enabling translator mode
# from one of those channels would be a one-way door.
EXIT_PHRASES = {
    "stop translating", "exit translator mode", "end translator mode",
    "turn off translator mode", "disable translator mode",
    "translator mode off", "stop translator mode",
}


class TranslatorMode:
    def __init__(self):
        self._active = False
        self._target: str | None = None
        self._source: str | None = None
        self._enabled_at: str | None = None
        self._turns = 0

    def enable(self, target_language: str, source_language: str | None = None) -> dict:
        target_language = (target_language or "").strip().lower()
        if not target_language:
            return {"ok": False, "message": "A target language (e.g. 'es', 'fr', 'ja') is required."}
        source_language = (source_language or "").strip().lower() or None
        if source_language and source_language == target_language:
            return {"ok": False, "message": "Source and target language can't be the same."}

        self._active = True
        self._target = target_language
        self._source = source_language
        self._enabled_at = datetime.now().isoformat()
        self._turns = 0
        return {"ok": True, **self.status()}

    def disable(self) -> dict:
        turns = self._turns
        self._active = False
        self._target = None
        self._source = None
        self._enabled_at = None
        self._turns = 0
        return {"ok": True, "message": "Translator mode deactivated.", "turns_translated": turns}

    def is_active(self) -> bool:
        return self._active

    def status(self) -> dict:
        return {
            "active":           self._active,
            "target_language":  self._target,
            "source_language":  self._source,
            "mode":             "conversation" if (self._target and self._source) else "one_way",
            "enabled_at":       self._enabled_at,
            "turns_translated": self._turns,
        }

    def is_exit_phrase(self, user_input: str) -> bool:
        return (user_input or "").strip().lower().rstrip(".!?") in EXIT_PHRASES

    def translate_turn(self, user_input: str) -> str:
        """Translate one message and return the translation — nothing else,
        no commentary, since the reply IS the payload here."""
        text = (user_input or "").strip()
        if not text:
            return ""

        if self._source and self._target:
            # Conversation mode: whichever configured language this message
            # ISN'T in (by real detection, not the JARVIS_LANGUAGE chat
            # preference) is where it's headed.
            detected = _detect_raw(text)
            dest = self._source if detected == self._target else self._target
        else:
            dest = self._target

        result = _translate(text, target=dest)
        self._turns += 1
        return result


translator_mode = TranslatorMode()
