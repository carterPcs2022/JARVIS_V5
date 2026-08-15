"""core/language.py — JARVIS responds in whatever language you speak to him in."""
from config.settings import JARVIS_LANGUAGE, DEEPL_API_KEY, LIBRETRANSLATE_URL

_LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
    "zh-cn": "Chinese", "ru": "Russian", "ar": "Arabic", "hi": "Hindi",
    "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "tr": "Turkish",
}


_MIN_DETECT_LEN  = 20    # langdetect is unreliable below this — short common
                          # English words/phrases ("ok", "nice", "sure", "yo",
                          # even "hello") get confidently misdetected as
                          # Slovak, Polish, French, Turkish, Finnish, etc.
_MIN_CONFIDENCE = 0.85    # require high confidence even once long enough


def _detect_raw(text: str) -> str:
    """Real per-message detection, ignoring JARVIS_LANGUAGE. Split out of
    detect_language() for callers (translator mode) that need to tell two
    specific languages apart on every message regardless of any fixed
    chat-response language preference — JARVIS_LANGUAGE="es" should still
    let translator mode notice an English sentence is English."""
    text = (text or "").strip()
    if len(text) < _MIN_DETECT_LEN:
        return "en"

    try:
        from langdetect import detect_langs
        candidates = detect_langs(text)
        if not candidates:
            return "en"
        top = candidates[0]
        if top.prob < _MIN_CONFIDENCE:
            return "en"
        return top.lang
    except Exception:
        return "en"


def detect_language(text: str) -> str:
    """Detect language of input text. Returns ISO 639-1 code.

    Defaults to English unless the input is long enough and the detector is
    confident enough to trust — otherwise JARVIS can end up replying in a
    language the user never used, from a single short message like "ok" or
    "nice" being misread as Slovak or Polish."""
    if JARVIS_LANGUAGE != "auto":
        return JARVIS_LANGUAGE
    return _detect_raw(text)


def get_system_prompt_for_language(lang: str, base_prompt: str) -> str:
    """Append a language directive to the base JARVIS system prompt."""
    if lang == "en":
        return base_prompt
    name = _LANG_NAMES.get(lang, lang)
    return (
        base_prompt
        + f"\n\nThe user is writing in {name}. Respond entirely in {name}, "
          f"maintaining your personality and wit — do not switch to English."
    )


def translate(text: str, target: str = "en") -> str:
    """Translate text via DeepL (if key set) or LibreTranslate (if URL set)."""
    if DEEPL_API_KEY:
        try:
            import deepl
            translator = deepl.Translator(DEEPL_API_KEY)
            result = translator.translate_text(text, target_lang=target.upper())
            return result.text
        except Exception as e:
            print(f"[Language] DeepL translation failed: {e}")

    if LIBRETRANSLATE_URL:
        try:
            import httpx
            r = httpx.post(f"{LIBRETRANSLATE_URL}/translate", json={
                "q": text, "source": "auto", "target": target, "format": "text",
            }, timeout=10)
            return r.json().get("translatedText", text)
        except Exception as e:
            print(f"[Language] LibreTranslate failed: {e}")

    # Fallback: ask the LLM to translate directly
    try:
        from core.llm.router import think
        name = _LANG_NAMES.get(target, target)
        return think(f"Translate the following into {name}. Return only the translation:\n\n{text}",
                     max_tokens=len(text) * 2 + 100)
    except Exception:
        return text


def set_preferred_language(lang: str):
    """Set JARVIS's preferred response language, stored in the user profile."""
    from core.memory import update_profile
    update_profile({"preferred_language": lang})
    return {"preferred_language": lang}
