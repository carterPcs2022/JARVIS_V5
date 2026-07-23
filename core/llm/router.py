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
    JARVIS_PERSONALITY, GROQ_API_KEY, GROQ_MODEL, OLLAMA_BASE_URL, USE_SMART_ROUTING,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL_SONNET, ANTHROPIC_MODEL_OPUS, ANTHROPIC_MODEL_FABLE,
    ENABLE_SONNET, ENABLE_OPUS, ENABLE_FABLE,
    SONNET_DAILY_CALL_LIMIT, OPUS_DAILY_CALL_LIMIT, FABLE_DAILY_CALL_LIMIT,
    BASE_DIR, USER_TIMEZONE,
)


_TIME_TRIGGERS = ("what time", "what's the time", "time is it", "current time", "the time")
_DATE_TRIGGERS = ("what day", "what's the date", "today's date", "what date")


def _now_local():
    from config.settings import now_local
    return now_local()


def _instant_response(query: str) -> str | None:
    """Answer a handful of queries directly, with no LLM call — currently
    time/date. JARVIS runs on Render/Railway, whose server clock is UTC;
    the LLM has no way to know that isn't the user's local time, so
    routing "what time is it" through a model risks a wrong or server-UTC
    answer. Returns None for anything else so the caller falls through to
    the normal LLM pipeline.

    Only short-circuits when the trigger phrase IS essentially the whole
    message. It used to substring-match anywhere in the query — "Jarvis
    what time is it also make a note for me upgrading you at 9 AM today
    please" contains "time is it", so the entire second half (a real,
    separate request) silently vanished with zero acknowledgment: the
    instant answer returns straight from Brain.process()'s early-exit
    block, before the rest of the message is ever looked at again. A
    compound message needs the real pipeline so the non-time part still
    gets a response instead of being dropped."""
    q = query.lower().strip().rstrip("?!.")
    word_count = len(q.split())
    if any(t in q for t in _TIME_TRIGGERS) and word_count <= 7:
        now = _now_local()
        return f"It's {now.strftime('%I:%M %p').lstrip('0')}, sir."
    if any(t in q for t in _DATE_TRIGGERS) and word_count <= 7:
        now = _now_local()
        return now.strftime("%A, %B %d.")
    return None

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
        # qwen/qwen3-32b was decommissioned; qwen/qwen3.6-27b is its
        # successor in Groq's live catalog. ModelUpdater's automatic
        # same-family check missed this one because the version-numbering
        # format itself changed ("3-32b" -> "3.6-27b") — the extra "."
        # breaks its digit-stripping family comparison, so this needed a
        # manual pick. Verified live: 200 OK, still emits <think> tags the
        # same way (already handled by _strip_think_tags() below).
        "id": "qwen/qwen3.6-27b", "max_tokens": 4096,
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


# ── Daily request-cap awareness ────────────────────────────────────────────
# _rate_check() above only guards Groq's 30-requests-per-minute figure — it
# has no idea about the separate, much easier to exhaust cap: 1,000
# requests/day on both llama-3.1-8b-instant and llama-3.3-70b-versatile
# (confirmed against Groq's published limits, not assumed). That averages
# out to ~41 requests/hour, shared across real user chat, every scheduled
# background job (predictive pre-caching, proactive insights, research),
# and every health-check ping — and nothing tracked it before this.
#
# Real user messages are never gated by this — only background/speculative
# calls (chat(..., background=True)) get throttled once a model's daily
# usage crosses a safety margin, so a background job can't be the thing
# that burns the day's remaining budget out from under someone actually
# waiting on a real answer later.
_daily_call_times: dict = {}
_DAILY_WINDOW = 86400  # seconds — rolling 24h, not a calendar-day reset
_MODEL_DAILY_LIMITS = {
    "llama-3.1-8b-instant":    1000,
    "llama-3.3-70b-versatile": 1000,
}
_DEFAULT_DAILY_LIMIT = 1000  # conservative default for any model not explicitly listed
_DAILY_SAFETY_MARGIN = 0.9   # background calls stop at 90% of the real daily cap


def _record_daily_call(model_id: str):
    _daily_call_times.setdefault(model_id, deque()).append(time.time())


def _daily_budget_ok(model_id: str) -> bool:
    dq = _daily_call_times.setdefault(model_id, deque())
    now = time.time()
    while dq and now - dq[0] > _DAILY_WINDOW:
        dq.popleft()
    limit = _MODEL_DAILY_LIMITS.get(model_id, _DEFAULT_DAILY_LIMIT)
    return len(dq) < limit * _DAILY_SAFETY_MARGIN


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
    from core.llm.anthropic_client import call_anthropic, get_effort_level

    config = ANTHROPIC_REGISTRY[tier]
    system = ""
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
            break
    user_messages = [m for m in messages if m["role"] != "system"]

    volatile_context = ""
    if tier in ("opus", "fable") and query:
        # Enhanced personality depth for opus/fable only — Groq calls keep
        # the base JARVIS_PERSONALITY for token efficiency. Appended to the
        # stable system string (not the volatile per-query context below) —
        # it's static text, so it belongs in the cacheable prefix alongside
        # JARVIS_PERSONALITY rather than after content that changes every call.
        try:
            from config.settings import STARK_INTELLIGENCE_PROTOCOLS
            system = f"{system}\n\n{STARK_INTELLIGENCE_PROTOCOLS}"
        except Exception:
            pass

        try:
            from core.context import build_fable_context
            volatile_context = build_fable_context(query) or ""
        except Exception as e:
            print(f"[LLM Router] build_fable_context failed (non-fatal): {e}")

    # `temperature` isn't forwarded — sonnet-5/opus-4-8/fable-5 all 400 on
    # any explicit temperature/top_p/top_k, so call_anthropic never sends
    # one. It's still accepted as a param here since chat() passes it
    # uniformly across the groq/ollama/anthropic dispatch, and Groq/Ollama
    # calls elsewhere in chat() still use it normally.
    effort = get_effort_level(query) if query else ""
    result = call_anthropic(user_messages, system, config["id"],
                            max_tokens=min(max_tokens, config["max_tokens"]) if max_tokens else config["max_tokens"],
                            effort=effort, volatile_context=volatile_context)
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
         force_model: str | None = None, query: str = "", background: bool = False) -> dict:
    """
    Route a chat request to the best available LLM.

    use_cache=True is for background/non-critical calls (consciousness
    reflections, workshop status, awareness narration) — identical requests
    within CACHE_TTL return the cached response instead of hitting Groq again.

    background=True marks this as a speculative/non-critical call (scheduled
    jobs: predictive pre-caching, proactive insights, research — never real
    user chat). Once a Groq model's rolling-24h call count crosses
    _DAILY_SAFETY_MARGIN of its real published daily cap, background calls
    skip that model and fall through to the next provider instead of
    spending the day's remaining budget — a background job should never be
    the reason a real user message later in the day has nothing left to
    call. Real (non-background) calls are never gated by this.

    force_model: one of MODEL_REGISTRY's keys ("instant"/"standard"/
    "reasoning"/"research"/"coder") to pin a specific tier. Otherwise, if
    USE_SMART_ROUTING is on and `query` is given, the tier is auto-classified.

    Returns: {content, model, provider, latency_ms, error}
    """
    if query:
        instant = _instant_response(query)
        if instant is not None:
            return {"content": instant, "model": "instant", "provider": "local",
                   "latency_ms": 0.0}

    from core.llm.openai import chat as groq_chat
    from core.llm.ollama import chat as ollama_chat
    from core.state import state

    if use_cache:
        key = _cache_key(messages)
        cached = _cache.get(key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return {**cached[1], "cached": True}

    # Tracks which providers were genuinely attempted (not skipped for lack
    # of config/circuit-open/headless-cloud) and the most specific
    # retry-after seen, so the final all-failed message can name only what
    # actually ran instead of a hardcoded list that claims Ollama "failed"
    # even when it was correctly never tried.
    _attempted: list[str] = []
    _last_retry_after: float | None = None

    _anthropic_start = time.time()
    tier = _resolve_tier(force_model, query)
    if tier in ANTHROPIC_REGISTRY:
        _attempted.append("anthropic")
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
    from services.circuit_breaker import cb, CircuitOpenError
    # Ollama can never be reached from a headless cloud deployment (Render/
    # Railway) — OLLAMA_BASE_URL defaults to localhost, which inside that
    # container is the container itself; no Ollama process runs there. Every
    # attempt in production was a guaranteed "connection refused" burning a
    # slot in the fallback chain. Still fully attempted on local/dev, where
    # it's the intended fallback.
    from config.settings import IS_HEADLESS_CLOUD, CEREBRAS_API_KEY
    _candidates = ["groq"] if IS_HEADLESS_CLOUD else ["groq", "ollama"]
    if CEREBRAS_API_KEY:
        # Cerebras is a separate free account/quota from Groq — normally
        # tried last among the free options, since its real published free
        # tier (5 RPM / 30K TPM / 1M TPD — see core/llm/cerebras.py) is far
        # tighter than Groq's, so it can't absorb Groq's full volume by
        # default. But all 5 Groq-hosted tiers (instant/standard/reasoning/
        # research/coder) previously shared one point of failure — a Groq
        # outage took out everything until the per-request reactive
        # fallback below kicked in, and every request paid that failed
        # attempt first. The "reasoning" tier specifically is the right
        # one to proactively default to Cerebras instead: it's real-world
        # low-volume (only reached via explicit trigger phrases like
        # "should i"/"debate"/"calculate", not the general chat catchall
        # _DEFAULT_TIER="standard" gets), so it won't blow through
        # Cerebras's 5 RPM cap, and Cerebras's configured model
        # (CEREBRAS_MODEL, default gpt-oss-120b) is itself a genuine
        # reasoning-oriented model, not a mismatch for this tier. Every
        # other tier keeps the existing Groq-first, Cerebras-as-fallback
        # behavior unchanged.
        if groq_tier == "reasoning" or time.time() < state.get("groq_prefer_alt_until", 0):
            _candidates.insert(0, "cerebras")
        else:
            _candidates.append("cerebras")
    providers = _candidates if prefer == "groq" else list(reversed(_candidates))

    for provider in providers:
        try:
            if provider == "groq":
                if not GROQ_API_KEY:
                    continue
                # Keyed per-model, not just "groq" — Groq enforces rate
                # limits (especially tokens-per-day) per model, so one
                # model being exhausted (e.g. llama-3.3-70b-versatile at
                # its daily cap) shouldn't trip the circuit for every other
                # Groq model too, including ones with plenty of budget left
                # (e.g. llama-3.1-8b-instant, used by the threat classifier
                # and simple-query routing).
                circuit_key = f"groq:{model_id}"
                if not cb.is_available(circuit_key):
                    print(f"[LLM Router] Groq circuit open for {model_id} — skipping straight to next provider")
                    # Per-model, not the blanket "groq_available" flag —
                    # that flag is reserved for check_groq()'s real health
                    # probe (see core/state.py's set_model_status docstring
                    # for why per-request writes must never touch it).
                    state.set_model_status("groq", model_id, False)
                    continue
                if background and not _daily_budget_ok(model_id):
                    print(f"[LLM Router] {model_id} near its daily cap — skipping this background call")
                    continue
                if not _rate_check():
                    print("[LLM Router] Approaching Groq rate limit — brief backoff before calling")
                    time.sleep(2)
                _call_times.append(time.time())
                _record_daily_call(model_id)
                _attempted.append("groq")
                try:
                    result = cb.call(circuit_key, groq_chat, messages, max_tokens, temperature, model=model_id)
                except CircuitOpenError as e:
                    print(f"[LLM Router] {e}")
                    state.set_model_status("groq", model_id, False)
                    continue
                # Reasoning models (Qwen3, DeepSeek-style) emit raw
                # <think>...</think> chain-of-thought before the real
                # answer — strip it so it never leaks into a response.
                if "content" in result:
                    result["content"] = _strip_think_tags(result["content"])
            elif provider == "cerebras":
                from core.llm.cerebras import chat as cerebras_chat
                circuit_key = "cerebras"
                if not cb.is_available(circuit_key):
                    print("[LLM Router] Cerebras circuit open — skipping straight to next provider")
                    continue
                _attempted.append("cerebras")
                try:
                    result = cb.call(circuit_key, cerebras_chat, messages, max_tokens, temperature)
                except CircuitOpenError as e:
                    print(f"[LLM Router] {e}")
                    continue
                if "content" in result:
                    result["content"] = _strip_think_tags(result["content"])
            else:
                _attempted.append("ollama")
                result = ollama_chat(messages, max_tokens, temperature)

            latency = round((time.time() - start) * 1000, 2)
            state.update({
                "active_model":    result.get("model"),
                "active_provider": provider,
                "ollama_available": True if provider == "ollama" else state.get("ollama_available"),
            })
            if provider == "groq":
                state.set_model_status("groq", model_id, True)
            elif provider == "cerebras":
                # Groq/Anthropic both log something on every path (success
                # or failure); this branch previously only logged failure,
                # so a Cerebras save after a real Groq outage was
                # invisible in the logs — only inferable from a reflection
                # score existing at all. Log it explicitly instead.
                print(f"[LLM Router] Cerebras answered ({result.get('model')}) after Groq/Ollama failure")
            final = {**result, "provider": provider, "latency_ms": latency}

            if use_cache:
                _cache[_cache_key(messages)] = (time.time(), final)

            return final

        except Exception as e:
            print(f"[LLM Router] {provider} failed: {e}")
            if provider == "groq":
                state.set_model_status("groq", model_id, False)
            if provider in ("groq", "cerebras"):
                retry_after = getattr(e, "retry_after", None)
                if retry_after:
                    _last_retry_after = retry_after
            continue

    # Last resort: every free-tier Groq option (and Ollama, where
    # applicable) is exhausted. If Anthropic is configured but wasn't
    # already tried above (that only happens via explicit trigger phrases
    # — "critical decision", "use fable", etc. — not as a fallback), reach
    # for the cheapest enabled tier now rather than going fully offline
    # while a real, working key sits unused. This is genuine spend, so it
    # only fires here — once Groq has actually failed — never on the
    # ordinary happy path.
    if "anthropic" not in _attempted:
        for fallback_tier in ("sonnet", "opus", "fable"):
            config = ANTHROPIC_REGISTRY.get(fallback_tier)
            if config and config["enabled"] and ANTHROPIC_API_KEY and _under_daily_limit(fallback_tier):
                _attempted.append("anthropic")
                print(f"[LLM Router] Groq/Ollama exhausted — trying Anthropic ({fallback_tier}) as last resort")
                result = _call_anthropic_tier(fallback_tier, messages, max_tokens, query, temperature=temperature)
                if result:
                    print(f"[LLM Router] Anthropic ({fallback_tier}) last-resort call succeeded")
                    result["latency_ms"] = round((time.time() - start) * 1000, 2)
                    if use_cache:
                        _cache[_cache_key(messages)] = (time.time(), result)
                    return result
                print(f"[LLM Router] Anthropic ({fallback_tier}) last-resort call also failed")
                break  # one attempt only — a failing key/service won't succeed on the next tier either

    # Name only what was actually attempted — Ollama being skipped entirely
    # on headless cloud (see above) or Anthropic never being configured
    # must not be reported as "failed" alongside a real Groq failure. The
    # "[JARVIS OFFLINE]" prefix is a stable marker several other modules
    # check for (core/validator.py, core/brain_v2.py, core/consciousness.py,
    # services/self_audit.py, core/protocols.py) — keep it exact even
    # though the rest of the message is now dynamic.
    if _attempted:
        names = [p.capitalize() for p in _attempted]
        joined = names[0] if len(names) == 1 else (
            f"{names[0]} and {names[1]}" if len(names) == 2
            else f"{', '.join(names[:-1])}, and {names[-1]}"
        )
        detail = f"{joined} failed."
    else:
        detail = "No providers were configured to try."
    if _last_retry_after:
        mins = round(_last_retry_after / 60, 1)
        detail += f" Retry in about {mins:g} min." if mins >= 1 else f" Retry in about {int(_last_retry_after)}s."

    return {
        "content":    f"[JARVIS OFFLINE] {detail}",
        "model":      "none",
        "provider":   "none",
        "latency_ms": round((time.time() - start) * 1000, 2),
        "error":      "All providers failed",
        "attempted":  _attempted,
        "retry_after": _last_retry_after,
    }


def think(user_input: str, context: str = "",
          system: str | None = None, max_tokens: int = 1024, use_cache: bool = False,
          force_model: str | None = None, temperature: float | None = None,
          background: bool = False) -> str:
    """Simple one-shot think call. Returns the response string.
    Pass use_cache=True for background/non-critical calls to avoid piling
    onto the rate limit with repeated near-identical prompts.
    Pass background=True for scheduled/speculative calls (never real user
    chat) — see chat()'s docstring for what this does.
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

    user_content = user_input
    # Dual-process (System 1/2) routing: only kicks in when the caller hasn't
    # already pinned a tier (agents/tools that pass force_model deliberately
    # keep their exact behavior) and the query isn't an instant time/date
    # shortcut (chat() answers those with zero LLM calls regardless of tier,
    # so classifying them would just be wasted work).
    if force_model is None and _instant_response(user_input) is None:
        from core.dual_process import dual_process  # deferred: dual_process imports think() at module load, so a top-level import here would be circular
        if dual_process.classify(user_input) == "system2":
            force_model = "opus"
            user_content = f"[SLOW DELIBERATE THINKING]\nQuestion: {user_input}"

    messages.append({"role": "user", "content": user_content})
    return chat(messages, max_tokens=max_tokens, temperature=temperature if temperature is not None else 0.6,
               use_cache=use_cache, force_model=force_model, query=user_input,
               background=background)["content"]


# ── Response cache warming ─────────────────────────────────────────────────────
COMMON_QUERIES = [
    "what time is it",
    "what's the date",
    "how are you",
    "are you online",
    "status",
    "good morning",
]


def warm_cache():
    """Pre-compute common query responses so the first real request for one
    of these doesn't pay full LLM latency. Calls think(use_cache=True)
    directly rather than writing into _cache by hand — that guarantees the
    cache key matches exactly what a live request will look up (same
    default system prompt, no context). "what time is it"/"what's the
    date" are answered instantly by _instant_response() and never even
    reach the cache; the rest go through a real (cached) Groq call.
    Called from server/api.py's 30s-post-boot delayed background start,
    not directly at startup, to stay behind the existing Groq-rate-limit
    stagger rather than adding another cold-boot spike. That same stagger
    logic previously stopped at the loop's edge: the 4 non-instant queries
    here (2 of the 6 are answered by _instant_response with no API call)
    used to fire back-to-back with zero delay, right after _probe()'s own
    real Groq call in check_groq() — 5 real requests in under a second on
    every boot, easily enough to trip a free-tier per-second/burst limit
    even when nothing else is calling Groq. A small sleep between each
    call costs nothing here (already off the event loop, via
    run_in_executor) and spreads the burst out."""
    for query in COMMON_QUERIES:
        try:
            think(query, use_cache=True)
        except Exception as e:
            print(f"[Router] warm_cache failed for '{query}': {e}")
        time.sleep(1)
    print("[Router] Response cache warmed")


# Health checks are cached — calling these hits a real API endpoint each time
# (check_groq sends an actual chat completion). Diagnostics/HUD polling can hit
# these several times a minute; without a cache that turns a status check into
# a live-traffic generator, which can itself trigger or prolong rate limiting.
#
# Was 30s — confirmed live that three independent periodic callers (HUD
# polling every 5s, services/scheduler.py's 2-min health refresh, and its
# 60s snap-monitor check) all read/refresh this same cache with no
# force=True bypass anywhere, so the real ping-call frequency is bounded
# by whichever TTL is set here. At 30s that's up to ~2,880 real "ping"
# completions/day against Groq's actual 1,000-requests-per-day cap on
# llama-3.1-8b-instant (confirmed via Groq's published limits, not
# assumed) — pure health-check overhead competing with real chat traffic
# for the same daily budget. Nothing here needs Groq's up/down status
# fresher than a few minutes; it's a background indicator, not something
# gating a live request.
_HEALTH_CACHE: dict = {"groq": (0.0, False), "ollama": (0.0, False)}
_HEALTH_TTL = 300  # seconds (was 30 — see comment above)


def check_groq(force: bool = False) -> bool:
    """True if Groq is usable right now. A 429 counts as usable — it means
    Groq is up and just rate-limiting us, which is transient (the actual
    wait — seconds for a per-minute limit, 40+ minutes for a daily one — is
    carried on GroqRateLimitError.retry_after and honored by
    services/circuit_breaker.py); it is not the same condition as Groq
    being down, and shouldn't be treated as one for DEGRADED-status
    purposes."""
    if not GROQ_API_KEY:
        return False
    ts, cached = _HEALTH_CACHE["groq"]
    if not force and (time.time() - ts) < _HEALTH_TTL:
        return cached
    import httpx
    try:
        from core.llm.openai import chat as groq_chat, GroqRateLimitError
        # This calls core.llm.openai.chat() directly, bypassing this
        # module's own chat()/_daily_budget_ok() gating entirely — it
        # still counts as a real request against Groq's actual daily cap,
        # so record it here or the daily-budget tracker undercounts real
        # usage and background jobs would keep calling past the real limit.
        groq_chat([{"role": "user", "content": "ping"}], max_tokens=5)
        _record_daily_call(GROQ_MODEL)
        _HEALTH_CACHE["groq"] = (time.time(), True)
        return True
    except (httpx.HTTPStatusError, GroqRateLimitError) as e:
        is_429 = isinstance(e, GroqRateLimitError) or (
            isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429)
        if is_429:
            print("[LLM Router] Groq health check hit 429 (rate limited, not down)")
            _HEALTH_CACHE["groq"] = (time.time(), True)
            # Proactive switch: this fires from the 30s post-boot probe
            # (server/api.py) and the 2-min scheduled health refresh
            # (services/scheduler.py) alike — either way, don't make the
            # next live chat message pay to rediscover a 429 we already
            # just saw. chat() checks this to try Cerebras (separate free
            # account/quota) before Groq for a short window. Capped at 5
            # min even for a real tokens-per-day retry_after (40+ min) —
            # Cerebras's own free tier is rate-limited too (5 RPM), so
            # parking there for the full outage isn't necessarily better;
            # the next health check simply refreshes this window if Groq
            # is still down.
            retry_after = e.retry_after if isinstance(e, GroqRateLimitError) else None
            cooldown = min(retry_after or 60, 300)
            from core.state import state
            state.set("groq_prefer_alt_until", time.time() + cooldown)
            return True
        _HEALTH_CACHE["groq"] = (time.time(), False)
        return False
    except Exception:
        _HEALTH_CACHE["groq"] = (time.time(), False)
        return False


def check_ollama(force: bool = False) -> bool:
    from config.settings import IS_HEADLESS_CLOUD
    if IS_HEADLESS_CLOUD:
        # Same reason chat()'s fallback chain skips Ollama in prod — never
        # reachable from a headless cloud container, so don't spend a real
        # (if fast) connection attempt on every /hud/status poll for a
        # result that can't ever be anything but False.
        return False
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
