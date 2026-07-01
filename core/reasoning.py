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
