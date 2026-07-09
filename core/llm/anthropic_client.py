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

THINKING_BUDGETS = {
    "sonnet": {"default": 1000, "deep": 3000, "maximum": 5000},
    "opus": {"default": 3000, "deep": 6000, "maximum": 10000},
    "fable": {"default": 5000, "deep": 10000, "maximum": 16000},
}

_CRITICAL_KEYWORDS = (
    "most important", "life changing", "critical", "biggest decision",
    "everything depends", "career", "relationship", "quit my job",
)


def get_thinking_budget(tier: str, query: str) -> int:
    """Longer/higher-stakes queries get more thinking time."""
    budgets = THINKING_BUDGETS.get(tier, {})
    words = len(query.split())

    if any(k in query.lower() for k in _CRITICAL_KEYWORDS):
        return budgets.get("maximum", 10000)
    if words > 40 or "analyze" in query.lower():
        return budgets.get("deep", 3000)
    return budgets.get("default", 1000)


def call_anthropic(messages: list, system: str, model: str, max_tokens: int = 1024,
                   thinking_budget: int = 0, temperature: float | None = None) -> dict | None:
    """Call an Anthropic model, optionally with extended thinking.
    thinking_budget=0 disables it, so `temperature` (if given) is honored.
    thinking_budget>0 enables it, which forces temperature=1 per the API's
    requirement — any explicit `temperature` is ignored in that case rather
    than sent and rejected by the API."""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        client = _get_client()

        params = {
            "model": model, "max_tokens": max_tokens,
            "system": system, "messages": messages,
        }

        should_think = thinking_budget > 0 and any(m in model for m in THINKING_CAPABLE_MODELS)
        if should_think:
            # budget_tokens must leave room for the actual output within max_tokens.
            budget = min(thinking_budget, max(max_tokens - 512, 1024))
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["temperature"] = 1
        elif temperature is not None:
            params["temperature"] = temperature

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
        # API issue with the beta param), retry once without it rather than
        # failing the whole request.
        if thinking_budget > 0:
            return call_anthropic(messages, system, model, max_tokens, thinking_budget=0, temperature=temperature)
        return None
