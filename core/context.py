"""
core/context.py — JARVIS context assembler.
Pulls short-term memory, long-term recall, web search, and personality
into a single coherent context string for any LLM call.
"""
from core.memory import (get_context_string, recall_as_context, facts_as_context,
                          episodes_as_context, working_memory_as_context)
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
    """
    Assemble full context string for a prompt, respecting a hard token
    budget (MAX_CONTEXT_TOKENS). Priority order when trimming: recent
    conversation > web results > long-term memory — recent turns are the
    cheapest to lose relevance on if cut, long-term recall is the least
    time-critical of the three.
    """
    from config.settings import MAX_CONTEXT_TOKENS

    # Short-term conversation history — always included, highest priority
    short = get_context_string(n=8)

    # Working memory (core/working_memory.py, via core.memory's facade) —
    # same "built but unwired" gap facts/episodes below already had:
    # salience-ranked recent turns actually relevant to `user_input`, not
    # just the last N in raw order like `short` above. High priority,
    # right after short-term, since it's about the current session's
    # active attention rather than durable long-term knowledge.
    working = working_memory_as_context(user_input)

    # Known facts (semantic memory) — item C of the reasoning-quality
    # investigation. Real data already accumulates here (core.orchestrator,
    # core.stark_intelligence, services.reading_memory all write facts) but
    # it was never read back into reasoning before this. Short and
    # high-value, so it gets priority right after short-term.
    facts = facts_as_context(user_input)

    # Long-term memory recall
    ltm = recall_as_context(user_input)

    # Web context
    web = ""
    if include_web:
        web = _get_web_context(user_input, deep=deep)

    # Notable past episodes (episodic memory) — same gap as facts above
    # (core.brain_v2 already writes these — Mayday triggers, protocol-
    # refusal events — with nowhere for it to feed back in). Lowest budget
    # priority of the five: supplementary narrative context, not the kind
    # of thing that should push out a real web result or a known fact.
    episodes = episodes_as_context(user_input)

    def _tok_est(s: str) -> int:
        return int(len(s.split()) * 1.3)  # rough words-to-tokens estimate

    # Reserve budget in priority order (short-term, working, facts, web,
    # ltm, episodes) but assemble the final string in the original relative
    # ordering (facts/episodes framed as supporting knowledge, short-term
    # stays closest to the actual user question) — short-term stays last,
    # which tends to help recency-weighted attention.
    budget = MAX_CONTEXT_TOKENS
    include = {"short": "", "working": "", "facts": "", "web": "", "ltm": "", "episodes": ""}

    if short:
        include["short"] = short
        budget -= _tok_est(short)

    if working and budget > 0:
        working_trimmed = _trim_to_budget(working, budget)
        if working_trimmed:
            include["working"] = working_trimmed
            budget -= _tok_est(working_trimmed)

    if facts and budget > 0:
        facts_trimmed = _trim_to_budget(facts, budget)
        if facts_trimmed:
            include["facts"] = facts_trimmed
            budget -= _tok_est(facts_trimmed)

    if web and budget > 0:
        web_trimmed = _trim_to_budget(web, budget)
        if web_trimmed:
            include["web"] = web_trimmed
            budget -= _tok_est(web_trimmed)

    if ltm and budget > 0:
        ltm_trimmed = _trim_to_budget(ltm, budget)
        if ltm_trimmed:
            include["ltm"] = ltm_trimmed
            budget -= _tok_est(ltm_trimmed)

    if episodes and budget > 0:
        episodes_trimmed = _trim_to_budget(episodes, budget)
        if episodes_trimmed:
            include["episodes"] = episodes_trimmed

    parts = [include["facts"], include["ltm"], include["web"], include["episodes"],
             include["working"], include["short"]]
    return "\n\n".join(p for p in parts if p)


def _trim_to_budget(text: str, budget_tokens: int) -> str:
    """Trim text to roughly fit a token budget (word-boundary safe)."""
    if budget_tokens <= 0:
        return ""
    max_words = max(10, int(budget_tokens / 1.3))
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [truncated]"


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


def build_fable_context(user_input: str) -> str:
    """Richest possible context for the opus/fable tiers — this is where
    JARVIS beats a fresh Claude.ai session: he knows more about the user
    than a stateless chat does. Every piece is independently optional
    (try/except) since a missing module shouldn't break a Fable call."""
    parts = []

    try:
        from core.memory import get_profile
        profile = get_profile()
        if profile:
            parts.append(
                f"USER PROFILE:\n"
                f"Communication style: {profile.get('formality', 'casual')}\n"
                f"Main interests: {', '.join(profile.get('topics', []))}\n"
                f"Expertise areas: {', '.join(profile.get('expertise', []))}"
            )
    except Exception:
        pass

    try:
        from core.life_os import life_os
        morning = life_os.morning_intention()
        if morning:
            parts.append(f"TODAY'S FOCUS:\n{morning}")
    except Exception:
        pass

    try:
        from services.workshop import Workshop
        brief = Workshop().project_brief()
        if brief:
            parts.append(f"ACTIVE PROJECTS:\n{brief}")
    except Exception:
        pass

    try:
        from core.memory import universal_recall
        memory = universal_recall(user_input)
        if memory:
            parts.append(f"RELEVANT MEMORY:\n{memory}")
    except Exception:
        pass

    try:
        from core.domain_expert import domain_expert
        domain = domain_expert.detect_domain(user_input)
        if domain:
            parts.append(f"DOMAIN CONTEXT ({domain}):\n{domain_expert.get_domain_context(domain)}")
    except Exception:
        pass

    try:
        from core.neuro_mirror import neuro
        style = neuro.get_style_prompt()
        if style:
            parts.append(f"USER COGNITIVE STYLE:\n{style}")
    except Exception:
        pass

    from config.settings import now_local
    now = now_local()
    parts.append(f"CURRENT TIME: {now.strftime('%I:%M %p, %A %B %d %Y')}")

    return "\n\n".join(parts)
