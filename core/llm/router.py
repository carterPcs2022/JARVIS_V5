"""
core/llm/router.py — JARVIS LLM router with smart model routing.
Tries Groq first, falls back to Ollama automatically. Above the free Groq
tiers sit three paid Anthropic tiers (sonnet/opus/fable) for genuinely hard
problems — reserved by trigger keywords and hard daily call caps, not used
for everything (that would defeat the point of having a free fast tier at
all). Tracks which provider is available and updates state.
"""
import time
import hashlib
import json
from collections import deque
from pathlib import Path
from datetime import date
from config.settings import (
    JARVIS_PERSONALITY, GROQ_API_KEY, OLLAMA_BASE_URL, USE_SMART_ROUTING,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL_SONNET, ANTHROPIC_MODEL_OPUS, ANTHROPIC_MODEL_FABLE,
    ENABLE_SONNET, ENABLE_OPUS, ENABLE_FABLE,
    SONNET_DAILY_CALL_LIMIT, OPUS_DAILY_CALL_LIMIT, FABLE_DAILY_CALL_LIMIT,
    BASE_DIR,
)

# ── Model registry ─────────────────────────────────────────────────────────────
# Verified live against Groq's /models endpoint — earlier drafts of this
# registry (and every third-party "Groq model list" floating around online)
# include deepseek-r1-distill-llama-70b, mixtral-8x7b-32768, and gemma2-9b-it.
# All three are decommissioned; using them would 404 on every call. Only
# models actually present in Groq's live catalog are listed here.
MODEL_REGISTRY = {
    "instant": {
        "id": "llama-3.1-8b-instant", "max_tokens": 1024,
        "best_for": ["greeting", "simple_fact", "time", "status"],
    },
    "standard": {
        "id": "llama-3.3-70b-versatile", "max_tokens": 2048,
        "best_for": ["chat", "analysis", "planning", "general"],
    },
    "reasoning": {
        "id": "qwen/qwen3-32b", "max_tokens": 4096,
        "best_for": ["complex_reasoning", "math", "logic", "debate"],
    },
    "research": {
        "id": "openai/gpt-oss-120b", "max_tokens": 8192,
        "best_for": ["research", "synthesis", "long_document", "comparison"],
    },
    "coder": {
        "id": "llama-3.3-70b-versatile", "max_tokens": 4096,
        "best_for": ["code_generation", "code_review", "debugging"],
        "system_suffix": "\nYou are operating in code mode. Prioritize "
                         "correctness, efficiency, and clean code above all else.",
    },
}
_DEFAULT_TIER = "standard"

# ── Anthropic tiers (paid — reserved for genuinely hard problems) ─────────────
ANTHROPIC_REGISTRY = {
    "sonnet": {"id": ANTHROPIC_MODEL_SONNET, "max_tokens": 4096, "enabled": ENABLE_SONNET,
              "daily_limit": SONNET_DAILY_CALL_LIMIT},
    "opus":   {"id": ANTHROPIC_MODEL_OPUS, "max_tokens": 4096, "enabled": ENABLE_OPUS,
              "daily_limit": OPUS_DAILY_CALL_LIMIT},
    "fable":  {"id": ANTHROPIC_MODEL_FABLE, "max_tokens": 8192, "enabled": ENABLE_FABLE,
              "daily_limit": FABLE_DAILY_CALL_LIMIT},
}

# Fable is reserved for the trigger explicitly asking for it — not classified
# into automatically from ordinary "hard" phrasing, since Opus already
# covers that at a third of the cost.
_FABLE_TRIGGERS = (
    "use fable", "fable 5", "maximum intelligence", "need your absolute best",
    "pull out all the stops", "bring out the big guns", "everything you have",
    "need your best", "best you got",
)
_OPUS_TRIGGERS = (
    "critical decision", "life changing", "most important decision",
    "comprehensive analysis", "expert opinion", "think carefully about",
    "hardest problem", "breakthrough", "cutting edge",
    # Security questions route to opus (not fable — that's reserved for
    # explicit "use fable" asks, and would burn through fable's scarce
    # 20/day cap on routine questions like "is this password strong
    # enough"). Opus's 50/day cap and reasoning quality are a solid fit.
    "vulnerability", "exploit", "security breach", "authentication bypass",
    "penetration test", "zero day", "how would an attacker",
)
_SONNET_TRIGGERS = (
    "write a", "creative", "write me a story", "write an essay",
    "draft a", "compose a", "long form",
)


def classify_query(query: str) -> str:
    """Pattern-match a query to the best model tier. Fast — no API call.
    Checks paid Anthropic tiers first (only actually routes there if the
    tier is enabled, configured, and under its daily cap — see
    _resolve_model), then the free Groq tiers."""
    q = (query or "").lower().strip()
    word_count = len(query.split())

    if ANTHROPIC_API_KEY and any(p in q for p in _FABLE_TRIGGERS):
        return "fable"
    if ANTHROPIC_API_KEY and any(p in q for p in _OPUS_TRIGGERS):
        return "opus"
    if ANTHROPIC_API_KEY and any(p in q for p in _SONNET_TRIGGERS):
        return "sonnet"

    if word_count < 5 or any(p in q for p in (
        "what time", "what's the time", "good morning", "good night",
        "hello", "hi jarvis", "status", "how are you", "you there",
    )):
        return "instant"

    if any(p in q for p in (
        "write code", "debug", "fix this", "function", "class ",
        "import ", "def ", "error on line", "syntax", "algorithm",
        "implement", "refactor",
    )):
        return "coder"

    if any(p in q for p in (
        "research", "summarize", "explain in detail", "everything about",
        "deep dive", "compare", "pros and cons", "comprehensive",
    )):
        return "research"

    if any(p in q for p in (
        "should i", "what would you recommend", "best approach",
        "think through", "reasoning", "argument", "debate", "decide",
        "tradeoff", "calculate", "math", "logic",
    )):
        return "reasoning"

    return _DEFAULT_TIER


# ── Daily usage tracking for paid tiers ───────────────────────────────────────
USAGE_FILE = BASE_DIR / "memory" / "model_usage.json"


def _get_usage() -> dict:
    today = date.today().isoformat()
    if USAGE_FILE.exists():
        try:
            data = json.loads(USAGE_FILE.read_text())
            if data.get("date") == today:
                return data
        except Exception:
            pass
    return {"date": today, "fable": 0, "opus": 0, "sonnet": 0}


def _record_usage(tier: str):
    usage = _get_usage()
    usage[tier] = usage.get(tier, 0) + 1
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(usage, indent=2))


def _under_daily_limit(tier: str) -> bool:
    config = ANTHROPIC_REGISTRY.get(tier)
    if not config:
        return True
    return _get_usage().get(tier, 0) < config["daily_limit"]


# Escalation path used when a tier is disabled/unconfigured/over its daily
# cap — always falls toward a free tier eventually, never silently drops
# the request.
_ANTHROPIC_FALLBACK = {"fable": "opus", "opus": "sonnet", "sonnet": "reasoning"}


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> chain-of-thought blocks some reasoning
    models (Qwen3, DeepSeek-distill) prepend to their actual answer."""
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return cleaned.strip() or text  # fall back to original if stripping left nothing


def _resolve_tier(force_model: str | None, query: str) -> str:
    """Returns the tier key to use — may be a Groq tier or an Anthropic
    tier ("sonnet"/"opus"/"fable"). Anthropic tiers fall back down the
    escalation chain if disabled, unconfigured, or over their daily cap."""
    if force_model and (force_model in MODEL_REGISTRY or force_model in ANTHROPIC_REGISTRY):
        key = force_model
    elif USE_SMART_ROUTING and query:
        key = classify_query(query)
    else:
        key = _DEFAULT_TIER

    while key in ANTHROPIC_REGISTRY:
        config = ANTHROPIC_REGISTRY[key]
        if config["enabled"] and ANTHROPIC_API_KEY and _under_daily_limit(key):
            return key
        print(f"[LLM Router] {key} unavailable/over daily cap — falling back to {_ANTHROPIC_FALLBACK[key]}")
        key = _ANTHROPIC_FALLBACK[key]

    return key


def _resolve_model(force_model: str | None, query: str) -> tuple[str, dict]:
    """Returns (model_id, model_config) for a Groq-tier query. Anthropic
    tiers are handled separately in chat() since they need a different
    call path (see _resolve_tier)."""
    key = _resolve_tier(force_model, query)
    if key in ANTHROPIC_REGISTRY:
        key = "standard"  # should not happen — chat() intercepts Anthropic tiers first
    config = MODEL_REGISTRY[key]
    return config["id"], config

# ── Client-side rate limiting ─────────────────────────────────────────────────
# Groq's free tier caps requests per minute. Background callers (consciousness,
# workshop, awareness, mark system) can otherwise pile onto real chat traffic
# and trip 429s. This tracks our own call rate and briefly backs off before
# we'd exceed it, rather than firing blindly and hoping.
_call_times: deque = deque(maxlen=25)
_RATE_WINDOW = 60   # seconds
_RATE_LIMIT  = 25   # max Groq calls per window (leaves headroom under Groq's 30/min)


def _rate_check() -> bool:
    now = time.time()
    while _call_times and now - _call_times[0] > _RATE_WINDOW:
        _call_times.popleft()
    return len(_call_times) < _RATE_LIMIT


# ── Response cache for non-critical/background calls ──────────────────────────
_cache: dict = {}
_CACHE_TTL = 300  # seconds


def _cache_key(messages: list) -> str:
    return hashlib.md5(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def _call_anthropic_tier(tier: str, messages: list[dict], max_tokens: int, query: str,
                         temperature: float | None = None) -> dict | None:
    """Dispatch a chat() call to one of the Anthropic tiers. Enriches
    system context for opus/fable only (sonnet stays fast/cheap — the rich
    context builder itself costs nothing extra in API calls, but adding it
    to every sonnet call would bloat input tokens for a tier meant for
    quick creative asks)."""
    from core.llm.anthropic_client import call_anthropic, get_thinking_budget

    config = ANTHROPIC_REGISTRY[tier]
    system = ""
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
            break
    user_messages = [m for m in messages if m["role"] != "system"]

    if tier in ("opus", "fable") and query:
        try:
            from core.context import build_fable_context
            rich_context = build_fable_context(query)
            if rich_context:
                system = f"{system}\n\n{rich_context}"
        except Exception as e:
            print(f"[LLM Router] build_fable_context failed (non-fatal): {e}")

    budget = get_thinking_budget(tier, query) if query else 0
    result = call_anthropic(user_messages, system, config["id"],
                            max_tokens=min(max_tokens, config["max_tokens"]) if max_tokens else config["max_tokens"],
                            thinking_budget=budget, temperature=temperature)
    if not result:
        return None

    _record_usage(tier)

    try:
        from core.state import state
        state.update({"active_model": result["model"], "active_provider": "anthropic", "active_tier": tier})
    except Exception:
        pass

    if tier == "fable":
        try:
            from core.event_bus import bus
            bus.system("Routing to Fable 5. Maximum intelligence engaged.")
            print("[JARVIS] Fable 5 activated")
        except Exception:
            pass

    if result.get("thinking"):
        try:
            from core.memory import store_thinking
            store_thinking(query, result["content"], result["thinking"], result["model"])
        except Exception:
            pass

    try:
        from core.evolution import record_fable_response
        if tier == "fable":
            record_fable_response(query, result["content"],
                                  result["usage"]["input"], result["usage"]["output"])
    except Exception:
        pass

    return {"content": result["content"], "model": result["model"], "provider": "anthropic",
            "tier": tier, "thinking_used": result.get("thinking_used", False)}


def chat(messages: list[dict], max_tokens: int = 1024,
         temperature: float = 0.7, prefer: str = "groq", use_cache: bool = False,
         force_model: str | None = None, query: str = "") -> dict:
    """
    Route a chat request to the best available LLM.

    use_cache=True is for background/non-critical calls (consciousness
    reflections, workshop status, awareness narration) — identical requests
    within CACHE_TTL return the cached response instead of hitting Groq again.

    force_model: one of MODEL_REGISTRY's keys ("instant"/"standard"/
    "reasoning"/"research"/"coder") to pin a specific tier. Otherwise, if
    USE_SMART_ROUTING is on and `query` is given, the tier is auto-classified.

    Returns: {content, model, provider, latency_ms, error}
    """
    from core.llm.openai import chat as groq_chat
    from core.llm.ollama import chat as ollama_chat
    from core.state import state

    if use_cache:
        key = _cache_key(messages)
        cached = _cache.get(key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return {**cached[1], "cached": True}

    _anthropic_start = time.time()
    tier = _resolve_tier(force_model, query)
    if tier in ANTHROPIC_REGISTRY:
        result = _call_anthropic_tier(tier, messages, max_tokens, query, temperature=temperature)
        if result:
            result["latency_ms"] = round((time.time() - _anthropic_start) * 1000, 2)
            if use_cache:
                _cache[_cache_key(messages)] = (time.time(), result)
            return result
        # Anthropic call itself failed (not just over-limit, which
        # _resolve_tier already handles) — fall through to Groq/Ollama.
        print(f"[LLM Router] {tier} call failed — falling back to Groq/Ollama")

    # Track the actual Groq tier (instant/standard/reasoning/research/coder)
    # instead of just clearing it — state persists across requests, and
    # this call is now definitely going through Groq/Ollama.
    groq_tier = _resolve_tier(force_model, query)
    state.set("active_tier", groq_tier)

    model_id, model_config = _resolve_model(force_model, query)
    if "system_suffix" in model_config:
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] += model_config["system_suffix"]
                break
    max_tokens = min(max_tokens, model_config["max_tokens"]) if max_tokens else model_config["max_tokens"]

    start = time.time()
    providers = (["groq", "ollama"] if prefer == "groq"
                 else ["ollama", "groq"])

    for provider in providers:
        try:
            if provider == "groq":
                if not GROQ_API_KEY:
                    continue
                from services.circuit_breaker import cb, CircuitOpenError
                if not cb.is_available("groq"):
                    print("[LLM Router] Groq circuit open — skipping straight to next provider")
                    continue
                if not _rate_check():
                    print("[LLM Router] Approaching Groq rate limit — brief backoff before calling")
                    time.sleep(2)
                _call_times.append(time.time())
                try:
                    result = cb.call("groq", groq_chat, messages, max_tokens, temperature, model=model_id)
                except CircuitOpenError as e:
                    print(f"[LLM Router] {e}")
                    continue
                # Reasoning models (Qwen3, DeepSeek-style) emit raw
                # <think>...</think> chain-of-thought before the real
                # answer — strip it so it never leaks into a response.
                if "content" in result:
                    result["content"] = _strip_think_tags(result["content"])
            else:
                result = ollama_chat(messages, max_tokens, temperature)

            latency = round((time.time() - start) * 1000, 2)
            state.update({
                "active_model":    result.get("model"),
                "active_provider": provider,
                "groq_available": provider == "groq",
                "ollama_available": True if provider == "ollama" else state.get("ollama_available"),
            })
            final = {**result, "provider": provider, "latency_ms": latency}

            if use_cache:
                _cache[_cache_key(messages)] = (time.time(), final)

            return final

        except Exception as e:
            print(f"[LLM Router] {provider} failed: {e}")
            if provider == "groq":
                state.set("groq_available", False)
            continue

    return {
        "content":    "[JARVIS OFFLINE] All LLM providers failed.",
        "model":      "none",
        "provider":   "none",
        "latency_ms": round((time.time() - start) * 1000, 2),
        "error":      "All providers failed",
    }


def think(user_input: str, context: str = "",
          system: str | None = None, max_tokens: int = 1024, use_cache: bool = False,
          force_model: str | None = None, temperature: float | None = None) -> str:
    """Simple one-shot think call. Returns the response string.
    Pass use_cache=True for background/non-critical calls to avoid piling
    onto the rate limit with repeated near-identical prompts.
    Pass force_model to pin a tier — free Groq tiers ("instant"/"standard"/
    "reasoning"/"research"/"coder") or paid Anthropic tiers ("sonnet"/
    "opus"/"fable", each gated on ANTHROPIC_API_KEY + enabled + daily cap,
    falling back down the chain otherwise) — or leave unset for smart
    auto-classification when USE_SMART_ROUTING is enabled.
    Pass temperature to override the default (0.6 — decisive without being
    robotic). Ignored when routed to an Anthropic tier with extended
    thinking enabled: the API requires temperature=1 whenever a `thinking`
    block is present, and core/llm/anthropic_client.py already enforces
    that regardless of what's passed here — silently overriding a caller's
    explicit choice would be more surprising than just documenting it."""
    sys_prompt = system or JARVIS_PERSONALITY
    messages = [{"role": "system", "content": sys_prompt}]
    if context:
        messages.append({"role": "system", "content": f"Context:\n{context}"})
    messages.append({"role": "user", "content": user_input})
    return chat(messages, max_tokens=max_tokens, temperature=temperature if temperature is not None else 0.6,
               use_cache=use_cache, force_model=force_model, query=user_input)["content"]


# Health checks are cached — calling these hits a real API endpoint each time
# (check_groq sends an actual chat completion). Diagnostics/HUD polling can hit
# these several times a minute; without a cache that turns a status check into
# a live-traffic generator, which can itself trigger or prolong rate limiting.
_HEALTH_CACHE: dict = {"groq": (0.0, False), "ollama": (0.0, False)}
_HEALTH_TTL = 30  # seconds


def check_groq(force: bool = False) -> bool:
    """True if Groq is usable right now. A 429 counts as usable — it means
    Groq is up and just rate-limiting us, which is transient and already
    handled by the retry-after-10s in core/llm/openai.chat(); it is not the
    same condition as Groq being down, and shouldn't be treated as one for
    DEGRADED-status purposes."""
    if not GROQ_API_KEY:
        return False
    ts, cached = _HEALTH_CACHE["groq"]
    if not force and (time.time() - ts) < _HEALTH_TTL:
        return cached
    import httpx
    try:
        from core.llm.openai import chat as groq_chat
        groq_chat([{"role": "user", "content": "ping"}], max_tokens=5)
        _HEALTH_CACHE["groq"] = (time.time(), True)
        return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print("[LLM Router] Groq health check hit 429 (rate limited, not down)")
            _HEALTH_CACHE["groq"] = (time.time(), True)
            return True
        _HEALTH_CACHE["groq"] = (time.time(), False)
        return False
    except Exception:
        _HEALTH_CACHE["groq"] = (time.time(), False)
        return False


def check_ollama(force: bool = False) -> bool:
    ts, cached = _HEALTH_CACHE["ollama"]
    if not force and (time.time() - ts) < _HEALTH_TTL:
        return cached
    try:
        import httpx
        with httpx.Client(timeout=3) as c:
            r = c.get(f"{OLLAMA_BASE_URL}/api/tags")
            ok = r.status_code == 200
            _HEALTH_CACHE["ollama"] = (time.time(), ok)
            return ok
    except Exception:
        _HEALTH_CACHE["ollama"] = (time.time(), False)
        return False


def check_anthropic() -> bool:
    """True if an Anthropic tier is configured as a usable fallback. This is
    a config check, not a live API call — unlike Groq's free tier, hitting
    Anthropic on every ~30s HUD poll would burn real money for a status
    check alone. Anthropic's API is reliable enough that "configured and
    enabled" is a reasonable proxy for "available" here."""
    return bool(ANTHROPIC_API_KEY) and (ENABLE_SONNET or ENABLE_OPUS or ENABLE_FABLE)
