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

def classifier_failed_result(reason: str) -> dict:
    """Shared shape for "the classifier didn't actually run" — used both
    by classify()'s own internal failure paths below, and by every caller
    that awaits/submits classify() with its own timeout (server/
    websocket.py, server/routes/chat.py) and needs the identical marker
    when THAT wait fails, not just when classify() itself raises.

    is_threat stays False so nothing downstream that only checks that one
    field silently breaks, but classifier_failed=True is the real signal:
    services.combat_mode.handle_classification() checks this FIRST, before
    is_threat, specifically so a failed classification can never be
    silently treated as "confirmed not a threat" — this is a personal
    safety/emergency-detection feature, and defaulting an unknown to
    "safe" is the wrong direction to fail in. A real emergency message
    that happens to hit a classifier hiccup (malformed JSON, timeout,
    provider outage) must still surface *something*, not nothing."""
    return {
        "is_threat": False,
        "confidence": 0.0,
        "category": "none",
        "reasoning": reason,
        "classifier_failed": True,
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
                  f"classifier could not run: {result['error']}")
            return classifier_failed_result(f"provider failure: {result['error']}")

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
            "classifier_failed": False,
        }
    except Exception as e:
        # Logged, not just embedded in the returned "reasoning" field — a
        # silently-broken classifier (bad JSON, network error, etc.) would
        # otherwise look identical to "no threat detected" in both behavior
        # and logs, with zero trace of which one actually happened.
        print(f"[ThreatDetector] classify() failed, classifier could not run: {e}")
        return classifier_failed_result(f"classify() exception: {e}")
