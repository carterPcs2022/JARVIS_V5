"""
core/reflection.py — JARVIS self-reflection engine.
Critiques draft responses and rewrites if quality is below threshold.
"""
import re
from core.llm.router import think

THRESHOLD = 6   # Rewrite if score below this

_CRITIC_PROMPT = """\
Review this response for JARVIS voice quality — precise, calm, dry wit,
confident, never sycophantic. Score 1-10.

JARVIS voice violations (each drops the score):
- Starts with "Certainly/Of course/Absolutely" (-3)
- Says "Great question" or similar (-3)
- Ends with "Is there anything else?" (-2)
- Uses "As an AI" (-2)
- Overly apologetic (-1)
- Too long for a simple question (-1)
- Missing dry wit when appropriate (-1)
- Generic/forgettable phrasing (-1)

If score <= {threshold}, rewrite it in JARVIS's voice: precise, dry wit,
confident, addresses the user as "sir"/"ma'am" naturally, never fishes for
more work, never opens with a compliment or filler.

User query: {query}
Draft response: {response}

Reply EXACTLY:
SCORE: <n>
CRITIQUE: <one sentence — what's wrong if anything>
FINAL: <final response — original if good, rewrite if not>"""


def reflect(query: str, draft: str, threshold: int = THRESHOLD) -> dict:
    """
    Critique and optionally rewrite a draft response.
    Returns: {score, critique, final, was_rewritten}
    """
    prompt = _CRITIC_PROMPT.format(
        query=query, response=draft, threshold=threshold)
    raw = think(prompt)

    score_m    = re.search(r"SCORE:\s*(\d+)", raw)
    critique_m = re.search(r"CRITIQUE:\s*(.+?)(?=\nFINAL:|$)", raw, re.S)
    final_m    = re.search(r"FINAL:\s*(.+)", raw, re.S)

    score     = int(score_m.group(1)) if score_m else 7
    critique  = critique_m.group(1).strip() if critique_m else ""
    final_raw = final_m.group(1).strip() if final_m else ""
    # Fall back to original draft if parsing failed or LLM echoed the template
    final     = final_raw if final_raw and "SCORE:" not in final_raw else draft
    rewritten = score <= threshold and final != draft

    if rewritten:
        print(f"[JARVIS Reflect] Score {score}/10 — rewrote. {critique}")
    else:
        print(f"[JARVIS Reflect] Score {score}/10 — approved.")

    return {
        "score":        score,
        "critique":     critique,
        "final":        final,
        "was_rewritten": rewritten,
        "draft":        draft,
    }


# ── Adversarial self-checking ─────────────────────────────────────────────────
# Opt-in (2 extra LLM calls) — only worth running on responses that actually
# make a claim or recommendation, and only when explicitly requested; not
# wired into the default reflect() pass above.

_ADVERSARIAL_TRIGGER_WORDS = [
    "you should", "i recommend", "the best", "definitely",
    "certainly", "always", "never", "is better", "is worse",
]


def adversarial_check(query: str, response: str) -> dict:
    """JARVIS steelmans the opposite of his own answer. If the answer can't
    withstand the strongest counterargument, it's flagged for review."""
    if not any(w in response.lower() for w in _ADVERSARIAL_TRIGGER_WORDS):
        return {"passed": True, "steelman": None}

    steelman_prompt = (
        f"Someone gave this answer to: '{query}'\n\nAnswer: {response}\n\n"
        f"Give the strongest possible argument AGAINST this answer. "
        f"Be specific. What's wrong, missing, or misleading?"
    )
    steelman = think(steelman_prompt)

    counter_prompt = (
        f"Original answer: {response}\n\nStrongest counterargument: {steelman}\n\n"
        f"Can the original answer withstand this critique? "
        f"Reply: HOLDS or WEAKENED, then one sentence why."
    )
    verdict = think(counter_prompt)

    passed = "HOLDS" in verdict.upper()
    return {"passed": passed, "steelman": steelman, "verdict": verdict, "flagged": not passed}
