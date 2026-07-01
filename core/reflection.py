"""
core/reflection.py — JARVIS self-reflection engine.
Critiques draft responses and rewrites if quality is below threshold.
"""
import re
from core.llm.router import think

THRESHOLD = 6   # Rewrite if score below this

_CRITIC_PROMPT = """\
Rate this AI response 1-10 on: accuracy, helpfulness, clarity, conciseness.
Give ONE overall score then critique in one sentence.
If score <= {threshold}, rewrite it better.

User query: {query}
Draft response: {response}

Reply EXACTLY:
SCORE: <n>
CRITIQUE: <one sentence>
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
