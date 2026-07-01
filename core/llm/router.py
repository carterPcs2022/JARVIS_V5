"""
core/llm/router.py — JARVIS LLM router.
Tries Groq first, falls back to Ollama automatically.
Tracks which provider is available and updates state.
"""
import time
import hashlib
import json
from collections import deque
from config.settings import JARVIS_PERSONALITY, GROQ_API_KEY, OLLAMA_BASE_URL

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
         temperature: float = 0.7, prefer: str = "groq", use_cache: bool = False) -> dict:
    """
    Route a chat request to the best available LLM.

    use_cache=True is for background/non-critical calls (consciousness
    reflections, workshop status, awareness narration) — identical requests
    within CACHE_TTL return the cached response instead of hitting Groq again.

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
                result = groq_chat(messages, max_tokens, temperature)
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
          system: str | None = None, max_tokens: int = 1024, use_cache: bool = False) -> str:
    """Simple one-shot think call. Returns the response string.
    Pass use_cache=True for background/non-critical calls to avoid piling
    onto the rate limit with repeated near-identical prompts."""
    sys_prompt = system or JARVIS_PERSONALITY
    messages = [{"role": "system", "content": sys_prompt}]
    if context:
        messages.append({"role": "system", "content": f"Context:\n{context}"})
    messages.append({"role": "user", "content": user_input})
    # temperature 0.6 = decisive without being robotic
    return chat(messages, max_tokens=max_tokens, temperature=0.6, use_cache=use_cache)["content"]


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
