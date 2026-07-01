"""
core/context.py — JARVIS context assembler.
Pulls short-term memory, long-term recall, web search, and personality
into a single coherent context string for any LLM call.
"""
from core.memory import get_context_string, recall_as_context
from core.personality import build_system_prompt
from config.settings import JARVIS_PERSONALITY

# Keywords that signal the user wants live/real-time information
_LIVE_KW = {
    "today","now","current","currently","latest","recent","news","weather",
    "price","score","time","live","right now","this week","breaking","search",
    "look up","find","what is","who is","who are","where is","how much",
    "when did","when is","stock","crypto","bitcoin","headlines",
}

# Keywords that warrant deep search (fetch + synthesize)
_DEEP_KW = {
    "research","explain","summarize","tell me about","what happened",
    "how does","why did","analysis","overview","compare","difference between",
    "best","recommend","top","review",
}


def build_context(user_input: str, include_web: bool = True, deep: bool = False) -> str:
    """Assemble full context string for a prompt."""
    parts = []

    # Long-term memory recall
    ltm = recall_as_context(user_input)
    if ltm:
        parts.append(ltm)

    # Web context
    if include_web:
        web = _get_web_context(user_input, deep=deep)
        if web:
            parts.append(web)

    # Short-term conversation history
    short = get_context_string(n=8)
    if short:
        parts.append(short)

    return "\n\n".join(parts)


def build_system(custom: str | None = None) -> str:
    """Get the (personality-adapted) system prompt."""
    base = custom or JARVIS_PERSONALITY
    return build_system_prompt(base)


def needs_web(user_input: str) -> bool:
    low = user_input.lower()
    return any(kw in low for kw in _LIVE_KW)


def needs_deep(user_input: str) -> bool:
    low = user_input.lower()
    return any(kw in low for kw in _DEEP_KW) or len(user_input.split()) > 12


def _get_web_context(query: str, deep: bool = False) -> str:
    # Deep search: multi-source fetch + LLM synthesis (Perplexity-style)
    if deep or needs_deep(query):
        try:
            from core.deep_search import quick_deep
            return quick_deep(query)
        except Exception as e:
            import logging; logging.getLogger(__name__).debug("Deep search failed: %s", e)

    # Fast search: simple snippet lookup
    try:
        from core.tools.search import quick_answer
        return quick_answer(query)
    except Exception:
        return ""
