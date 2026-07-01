"""core/language.py — JARVIS responds in whatever language you speak to him in."""
from config.settings import JARVIS_LANGUAGE, DEEPL_API_KEY, LIBRETRANSLATE_URL

_LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
    "zh-cn": "Chinese", "ru": "Russian", "ar": "Arabic", "hi": "Hindi",
    "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "tr": "Turkish",
}


def detect_language(text: str) -> str:
    """Detect language of input text. Returns ISO 639-1 code."""
    if JARVIS_LANGUAGE != "auto":
        return JARVIS_LANGUAGE
    if not text or len(text.strip()) < 4:
        return "en"
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return "en"


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
