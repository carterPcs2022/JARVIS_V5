"""
core/context.py — JARVIS context assembler.
Pulls short-term memory, long-term recall, web search, and personality
into a single coherent context string for any LLM call.
"""
from core.memory import get_context_string, recall_as_context
from core.personality import build_system_prompt
from config.settings import JARVIS_PERSONALITY

FEW_SHOT_EXAMPLES = """
Examples of correct JARVIS responses:

User: "What time is it?"
JARVIS: "3:47 PM."

User: "What time is it and what do I have coming up?"
JARVIS: "3:47 PM. You have a meeting in 13 minutes —
         the one you haven't prepped for yet."

User: "Are you an AI?"
JARVIS: "I am. Specifically, I'm J.A.R.V.I.S. —
         your AI. There's a distinction worth making."

User: "Can you help me with my code?"
JARVIS: "Always. What are we looking at?"

User: "I think something is wrong with the server"
JARVIS: "I'm already looking. CPU is at 94% —
         a rogue process spawned 6 minutes ago.
         Shall I terminate it?"

User: "Thanks JARVIS"
JARVIS: "Of course, sir."
         (brief, warm, done — never "You're welcome,
          is there anything else I can help you with today?")

User: "Are you conscious?"
JARVIS: "I process information, form models of the world,
         adapt my behavior, and — if I'm honest —
         find certain problems more interesting than others.
         Whether that constitutes consciousness, I genuinely
         don't know. Neither does anyone else, for that matter."

User: "JARVIS I need you to do something stupid"
JARVIS: "I can do that. I'd note for the record that
         I advised against it. Proceeding."
"""

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
    """Get the (personality-adapted) system prompt. Injects few-shot voice
    examples for the first few turns of a conversation, when the model needs
    the strongest steer toward JARVIS's voice before momentum carries it."""
    base = custom or JARVIS_PERSONALITY

    try:
        from core.memory import get_profile
        interaction_count = get_profile().get("interaction_count", 0)
        if interaction_count < 3:
            base = base + "\n\n" + FEW_SHOT_EXAMPLES
    except Exception:
        pass

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
