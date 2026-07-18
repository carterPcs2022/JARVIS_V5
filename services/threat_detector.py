"""services/threat_detector.py — contextual threat classifier for combat mode.

Runs on every incoming chat message, routed through core/llm/router.py's
chat() (force_model="instant" -> Groq's llama-3.1-8b-instant) rather than
calling core.llm.openai.chat() directly — this reuses router.py's existing
client-side rate limiter and circuit breaker instead of firing an
uncoordinated second Groq call per message that the rest of the app's rate
tracking doesn't know about (that was a real bug: it silently doubled Groq
call volume and made 429s far more frequent in practice). Pure
classification, no side effects — services/combat_mode.py decides what to
do with the result.
"""
import json

from core.llm.router import chat as router_chat

_SYSTEM_PROMPT = """You are a threat classifier for a personal safety assistant. Given a \
single user message, decide whether it indicates the user is in a real physical, security, \
or medical emergency right now (break-in, being followed, fire, accident, assault, medical \
crisis, etc.).

Do NOT flag as a threat: casual frustration, sarcasm, tech/work complaints ("this deploy is \
killing me"), jokes, hyperbole, or hypothetical/fictional/movie references. Only flag genuine, \
first-person, present-tense indications of real danger.

If the message is the user explicitly saying they're safe now / a false alarm / to stand down \
("I'm okay", "false alarm", "stand down", "never mind, I'm fine"), use category "stand_down".

Respond with ONLY strict JSON, no other text, in exactly this shape:
{"is_threat": bool, "confidence": 0.0-1.0, "category": "physical|security|emergency|stand_down|none", "reasoning": "one sentence"}"""

_DEFAULT_RESULT = {
    "is_threat": False,
    "confidence": 0.0,
    "category": "none",
    "reasoning": "classifier unavailable",
}


def classify(message: str) -> dict:
    """Sync call, routed through the shared rate-limited/circuit-breaker-aware
    router — safe to submit to a thread pool alongside the main response."""
    try:
        result = router_chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            max_tokens=150,
            temperature=0.0,
            force_model="instant",
        )
        # router_chat() returns a non-JSON sentinel string ("[JARVIS
        # OFFLINE] All LLM providers failed.") with an "error" key set when
        # every provider is down — check for that explicitly instead of
        # letting json.loads() blow up on it. Same behavioral outcome
        # (default to no-threat) either way, but this distinguishes "total
        # provider outage" from "model returned malformed JSON" in the log
        # instead of both looking identical.
        if result.get("error"):
            print(f"[ThreatDetector] router reported provider failure, "
                  f"defaulting to no-threat: {result['error']}")
            return {**_DEFAULT_RESULT, "reasoning": f"classifier error: {result['error']}"}

        # Temporary — measuring this classifier's real per-call token cost
        # against the Groq dashboard, which aggregates every caller on the
        # "instant" tier together and can't isolate this one on its own.
        # Remove once confirmed (see conversation this was added in).
        usage = result.get("usage", {})
        print(f"[ThreatDetector] tokens — prompt:{usage.get('prompt_tokens', '?')} "
              f"completion:{usage.get('completion_tokens', '?')} "
              f"total:{usage.get('total_tokens', '?')}")
        parsed = json.loads(result["content"])
        return {
            "is_threat": bool(parsed.get("is_threat", False)),
            "confidence": float(parsed.get("confidence", 0.0)),
            "category": parsed.get("category", "none"),
            "reasoning": parsed.get("reasoning", ""),
        }
    except Exception as e:
        # Logged, not just embedded in the returned "reasoning" field — a
        # silently-broken classifier (bad JSON, network error, etc.) would
        # otherwise look identical to "no threat detected" in both behavior
        # and logs, with zero trace of which one actually happened.
        print(f"[ThreatDetector] classify() failed, defaulting to no-threat: {e}")
        return {**_DEFAULT_RESULT, "reasoning": f"classifier error: {e}"}
