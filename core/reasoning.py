"""
core/reasoning.py — JARVIS chain-of-thought reasoning.
For complex queries, JARVIS thinks step by step before answering.
"""
from core.llm.router import think

_REASONING_PROMPT = """\
Think through this step by step before answering.

Question: {question}

Reasoning (think out loud):
1."""

_COMPLEXITY_KEYWORDS = [
    "how", "why", "explain", "analyze", "compare", "design",
    "plan", "should i", "what would", "best way", "difference between",
    "help me", "problem", "debug", "optimize",
]


def needs_reasoning(query: str) -> bool:
    """Determine if a query benefits from chain-of-thought reasoning."""
    q = query.lower()
    return any(kw in q for kw in _COMPLEXITY_KEYWORDS) and len(query.split()) > 6


def reason(question: str, context: str = "") -> dict:
    """
    Perform chain-of-thought reasoning.
    Returns: {reasoning, answer, used_cot}
    """
    if not needs_reasoning(question):
        answer = think(question, context)
        return {"reasoning": None, "answer": answer, "used_cot": False}

    # Step 1: generate reasoning chain
    reasoning_input = _REASONING_PROMPT.format(question=question)
    if context:
        reasoning_input = f"Context:\n{context}\n\n{reasoning_input}"

    raw_reasoning = think(reasoning_input)

    # Step 2: synthesize final answer from the reasoning
    synthesis_prompt = (
        f"Question: {question}\n\n"
        f"My reasoning:\n{raw_reasoning}\n\n"
        f"Based on this reasoning, provide a clear, direct final answer:"
    )
    final_answer = think(synthesis_prompt)

    return {
        "reasoning": raw_reasoning,
        "answer":    final_answer,
        "used_cot":  True,
    }


# ── Verification pass ──────────────────────────────────────────────────────────
# Opt-in — 3 LLM calls (generate, challenge, synthesize). Not part of the
# default reason() path above, which is already the pipeline's "complex
# query" mode; this is for when you explicitly want the extra rigor.

def reason_and_verify(question: str, context: str = "") -> dict:
    """Three-stage reasoning: generate an answer, challenge it, synthesize
    a verified final response that accounts for the challenge."""
    draft = think(question, context, force_model="reasoning")

    challenge_prompt = (
        f"Original question: {question}\n\nProposed answer: {draft}\n\n"
        f"Challenge this answer. What could be wrong? What's missing? "
        f"What assumptions are made? Be specific and critical. One paragraph."
    )
    challenge = think(challenge_prompt, force_model="instant")

    synthesis_prompt = (
        f"Question: {question}\n\nInitial answer: {draft}\n\nCritique: {challenge}\n\n"
        f"Given this critique, provide the best possible final answer. "
        f"Acknowledge any genuine uncertainty."
    )
    final = think(synthesis_prompt, force_model="standard")

    return {"answer": final, "draft": draft, "challenge": challenge, "verified": True, "used_cot": True}


# ── Second-order thinking ───────────────────────────────────────────────────────
# Opt-in — one extra LLM call on top of whatever produced first_answer.

def second_order_think(query: str, first_answer: str) -> str:
    """"And then what?" thinking — second and third-order consequences of
    an initial answer, not just the immediate one."""
    return think(
        f"Given this situation and initial answer:\n"
        f"Question: {query}\n"
        f"Initial answer: {first_answer}\n\n"
        f"Now think 2-3 steps ahead:\n"
        f"- What are the second-order consequences?\n"
        f"- What problems might this solution create?\n"
        f"- What opportunities does this open up?\n"
        f"- What should be prepared for?\n"
        f"Think like a chess player, not a checkers player.",
        force_model="reasoning",
    )
