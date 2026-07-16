"""core/llm/anthropic_client.py — real Anthropic API calls for JARVIS's top
three tiers (sonnet/opus/fable), with extended thinking support.

Model IDs are the real, current ones: claude-sonnet-5, claude-opus-4-8,
claude-fable-5. The source build doc for this feature used fictional IDs
(claude-sonnet-4-6, claude-opus-4-6, claude-fable-5-20260609) — those don't
exist; every call with them would 404."""
import httpx
from config.settings import ANTHROPIC_API_KEY

# Connect-timeout, not a flat total-request cap — extended thinking on the
# deep/maximum tiers can legitimately take well over 8s to finish
# generating (thinking budgets go up to 16000 tokens for fable); a fixed
# short cap on the whole call would make those tiers fail constantly. This
# still fails fast if the connection itself stalls, which is the actual
# problem worth guarding against.
_TIMEOUT_CONFIG = httpx.Timeout(connect=8.0, read=120.0, write=8.0, pool=8.0)

# Anthropic is called far less often than Groq, but pooling the client is
# free — same reasoning as core/llm/openai.py's _CLIENT (a fresh client
# per call means a fresh TCP+TLS handshake every time).
_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        import anthropic
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_TIMEOUT_CONFIG)
    return _CLIENT


# Extended thinking is supported on all three top tiers.
THINKING_CAPABLE_MODELS = ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-5")

# All three tiers are on the current (4.6+) API surface: `thinking.budget_tokens`
# is removed there (400) in favor of `thinking: {type: "adaptive"}` plus a
# separate `output_config.effort` dial. Effort is a property of how hard the
# model should work, not of which model it is, so — unlike the old per-tier
# token budgets — one mapping now covers all three tiers.
_CRITICAL_KEYWORDS = (
    "most important", "life changing", "critical", "biggest decision",
    "everything depends", "career", "relationship", "quit my job",
)


def get_effort_level(query: str) -> str:
    """Longer/higher-stakes queries get more thinking effort. Returns "" for
    an empty query (caller should skip thinking entirely), else one of
    "medium"/"high"/"max" for output_config.effort."""
    if not query:
        return ""
    words = len(query.split())

    if any(k in query.lower() for k in _CRITICAL_KEYWORDS):
        return "max"
    if words > 40 or "analyze" in query.lower():
        return "high"
    return "medium"


def call_anthropic(messages: list, system: str, model: str, max_tokens: int = 1024,
                   effort: str = "", volatile_context: str = "") -> dict | None:
    """Call an Anthropic model, optionally with extended thinking.

    effort="" disables thinking; a non-empty value ("medium"/"high"/"max")
    enables adaptive thinking at that depth. All three tiers this client
    calls (sonnet-5, opus-4-8, fable-5) are on the post-4.6 API surface,
    which removed `thinking.budget_tokens` (400) and `temperature`/`top_p`/
    `top_k` (400) entirely — thinking depth is controlled by
    `output_config.effort` instead, and sampling params aren't sent at all
    for these models (steer via prompting, not temperature).

    Pass volatile_context for per-query content (e.g. core.context's
    build_fable_context result) that shouldn't sit inside the cached system
    block — it changes on every call, so bundling it into `system` would
    make every request write a fresh cache entry instead of reading the
    stable one."""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        client = _get_client()

        # JARVIS_PERSONALITY (~1800 tokens, plus STARK_INTELLIGENCE_PROTOCOLS
        # for opus/fable) is the system prompt on nearly every call and
        # barely changes between requests — cache it. 1h TTL (not the 5m
        # default) since JARVIS conversations happen in bursts with gaps
        # between them; a 5m cache would go cold between bursts and pay the
        # write premium every time. Costs more per write (2x vs 1.25x) but
        # pays off once a burst has 3+ calls, which is the common case here.
        #
        # volatile_context goes in a second, uncached block *after* the
        # cached one — caching is a prefix match, so appending per-query
        # content directly onto `system` would invalidate the cache on
        # every single call (paying the write premium with no read ever
        # landing). Keeping it as a separate trailing block means the
        # stable prefix still caches even though this part changes.
        system_blocks = []
        if system:
            system_blocks.append({"type": "text", "text": system,
                                  "cache_control": {"type": "ephemeral", "ttl": "1h"}})
        if volatile_context:
            system_blocks.append({"type": "text", "text": volatile_context})

        params = {
            "model": model, "max_tokens": max_tokens,
            "system": system_blocks if system_blocks else system,
            "messages": messages,
        }

        # No temperature/top_p/top_k on any of these three models — all
        # reject a non-default value with 400, so the param is never sent
        # here at all (was previously forced to 1 for thinking calls and
        # passed through otherwise; both paths now 400).
        should_think = bool(effort) and any(m in model for m in THINKING_CAPABLE_MODELS)
        is_fable = "claude-fable-5" in model
        if should_think:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": effort}
        elif not is_fable:
            # Fable 5 has thinking always on — an explicit {"type": "disabled"}
            # 400s there, so this branch (thinking off) is skipped for it and
            # the param is omitted entirely, which Fable 5 treats as adaptive-on.
            # Opus 4.8 / Sonnet 5 both accept "disabled" explicitly.
            params["thinking"] = {"type": "disabled"}

        response = client.messages.create(**params)

        text_content, think_content = "", ""
        for block in response.content:
            if getattr(block, "type", None) == "thinking":
                think_content = block.thinking
            elif getattr(block, "type", None) == "text":
                text_content = block.text

        return {
            "content": text_content, "thinking": think_content,
            "model": model, "provider": "anthropic", "thinking_used": should_think,
            "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens},
        }

    except Exception as e:
        print(f"[LLM] Anthropic error ({model}): {e}")
        # If extended thinking itself caused the failure (e.g. a transient
        # API issue), retry once without it rather than failing the whole
        # request.
        if effort:
            return call_anthropic(messages, system, model, max_tokens, volatile_context=volatile_context)
        return None


def call_anthropic_vision(image_b64: str, media_type: str, prompt: str,
                           model: str = "claude-sonnet-5", max_tokens: int = 300) -> str | None:
    """One-shot image + text call — separate from call_anthropic() because
    vision requests need an image content block, not a plain message list,
    and callers here (a quick 'what am I looking at' HUD readout) never
    need extended thinking or the fuller response envelope. Returns the
    text response, or None on failure/missing key."""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return None
    except Exception as e:
        print(f"[LLM] Anthropic vision error ({model}): {e}")
        return None
