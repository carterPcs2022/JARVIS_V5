"""
core/llm/router.py — JARVIS LLM router with smart model routing.
Tries Groq first, falls back to Ollama automatically.
Tracks which provider is available and updates state.
"""
import time
import hashlib
import json
from collections import deque
from config.settings import JARVIS_PERSONALITY, GROQ_API_KEY, OLLAMA_BASE_URL, USE_SMART_ROUTING

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


def classify_query(query: str) -> str:
    """Pattern-match a query to the best model tier. Fast — no API call."""
    q = (query or "").lower().strip()
    word_count = len(query.split())

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


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> chain-of-thought blocks some reasoning
    models (Qwen3, DeepSeek-distill) prepend to their actual answer."""
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return cleaned.strip() or text  # fall back to original if stripping left nothing


def _resolve_model(force_model: str | None, query: str) -> tuple[str, dict]:
    """Returns (model_id, model_config) for a query."""
    if force_model and force_model in MODEL_REGISTRY:
        key = force_model
    elif USE_SMART_ROUTING and query:
        key = classify_query(query)
    else:
        key = _DEFAULT_TIER
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
                if not _rate_check():
                    print("[LLM Router] Approaching Groq rate limit — brief backoff before calling")
                    time.sleep(2)
                _call_times.append(time.time())
                result = groq_chat(messages, max_tokens, temperature, model=model_id)
                # Reasoning models (Qwen3, DeepSeek-style) emit raw
                # <think>...</think> chain-of-thought before the real
                # answer — strip it so it never leaks into a response.
                if "content" in result:
                    result["content"] = _strip_think_tags(result["content"])
            else:
                result = ollama_chat(messages, max_tokens, temperature)

            latency = round((time.time() - start) * 1000, 2)
            state.update({
                "active_model":   result.get("model"),
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
          force_model: str | None = None) -> str:
    """Simple one-shot think call. Returns the response string.
    Pass use_cache=True for background/non-critical calls to avoid piling
    onto the rate limit with repeated near-identical prompts.
    Pass force_model to pin a tier ("instant"/"standard"/"reasoning"/
    "research"/"coder") — otherwise smart routing auto-classifies based on
    user_input when USE_SMART_ROUTING is enabled."""
    sys_prompt = system or JARVIS_PERSONALITY
    messages = [{"role": "system", "content": sys_prompt}]
    if context:
        messages.append({"role": "system", "content": f"Context:\n{context}"})
    messages.append({"role": "user", "content": user_input})
    # temperature 0.6 = decisive without being robotic
    return chat(messages, max_tokens=max_tokens, temperature=0.6, use_cache=use_cache,
               force_model=force_model, query=user_input)["content"]


# Health checks are cached — calling these hits a real API endpoint each time
# (check_groq sends an actual chat completion). Diagnostics/HUD polling can hit
# these several times a minute; without a cache that turns a status check into
# a live-traffic generator, which can itself trigger or prolong rate limiting.
_HEALTH_CACHE: dict = {"groq": (0.0, False), "ollama": (0.0, False)}
_HEALTH_TTL = 30  # seconds


def check_groq(force: bool = False) -> bool:
    if not GROQ_API_KEY:
        return False
    ts, cached = _HEALTH_CACHE["groq"]
    if not force and (time.time() - ts) < _HEALTH_TTL:
        return cached
    try:
        from core.llm.openai import chat as groq_chat
        groq_chat([{"role": "user", "content": "ping"}], max_tokens=5)
        _HEALTH_CACHE["groq"] = (time.time(), True)
        return True
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
