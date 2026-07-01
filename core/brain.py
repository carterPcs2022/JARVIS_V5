"""
core/brain.py — JARVIS main brain.
Full pipeline: context → reason → think → reflect → validate → respond.
"""
import time
from core.llm.router import think as llm_think, chat as llm_chat
from core.context import build_context, build_system
from core.reasoning import reason
from core.reflection import reflect
from core.validator import validate
from core.memory import save_turn, store_long_term
from core.personality import analyze_message
from core import evolution
from core.event_bus import bus


def process(user_input: str,
            use_reasoning:   bool = True,
            use_reflection:  bool = True,
            use_web:         bool = True) -> dict:
    """
    Full JARVIS response pipeline.

    Returns: {response, model, provider, latency_ms, meta}
    """
    start = time.time()
    analyze_message(user_input)

    # Build context
    context = build_context(user_input, include_web=use_web)
    system  = build_system()

    # Reason (CoT for complex queries)
    if use_reasoning:
        reasoning_result = reason(user_input, context)
        draft    = reasoning_result["answer"]
        used_cot = reasoning_result["used_cot"]
    else:
        messages = [
            {"role": "system",  "content": system},
            {"role": "system",  "content": f"Context:\n{context}"} if context else None,
            {"role": "user",    "content": user_input},
        ]
        messages = [m for m in messages if m]
        result   = llm_chat(messages)
        draft    = result["content"]
        used_cot = False

    model    = "unknown"
    provider = "unknown"

    # Reflect
    was_rewritten = False
    if use_reflection:
        reflection = reflect(user_input, draft)
        draft         = reflection["final"]
        was_rewritten = reflection["was_rewritten"]

    # Validate
    validation = validate(draft, user_input)
    response   = validation["response"]

    latency = round((time.time() - start) * 1000, 2)

    # Persist to memory
    save_turn(user_input, response)
    store_long_term(user_input, response)

    # Log evolution
    evolution.log(user_input, response, model, latency,
                  was_rewritten=was_rewritten)

    # Publish to event bus
    bus.chat("assistant", response)

    return {
        "response":      response,
        "model":         model,
        "provider":      provider,
        "latency_ms":    latency,
        "meta": {
            "used_cot":       used_cot,
            "was_rewritten":  was_rewritten,
            "context_length": len(context),
            "issues":         validation["issues"],
        },
    }
