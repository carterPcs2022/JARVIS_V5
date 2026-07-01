"""SmartRouter — routes requests to the best available LLM based on task type, cost, and availability."""
from __future__ import annotations
import os, time, logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


class Provider(str, Enum):
    GROQ      = "groq"
    ANTHROPIC = "anthropic"
    OLLAMA    = "ollama"


@dataclass
class RouteResult:
    provider: Provider
    model: str
    reason: str
    cost_estimate: float = 0.0


@dataclass
class UsageStats:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    errors: int = 0


_STATS: dict[Provider, UsageStats] = {p: UsageStats() for p in Provider}

# Cost per 1M tokens (input / output)
_COST = {
    Provider.GROQ:      (0.59,  0.79),
    Provider.ANTHROPIC: (3.00, 15.00),
    Provider.OLLAMA:    (0.0,   0.0),
}


def _groq_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _anthropic_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _ollama_available() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"), timeout=2)
        return True
    except Exception:
        return False


def route(intent: str, complexity: str = "moderate", private: bool = False) -> RouteResult:
    """Return the best provider/model for the given request.

    complexity: "simple" | "moderate" | "complex"
    private:    True → prefer local Ollama, never send to cloud
    """
    if private:
        if _ollama_available():
            return RouteResult(Provider.OLLAMA, os.getenv("OLLAMA_MODEL", "llama3"), "private mode → local model")
        return RouteResult(Provider.GROQ, os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "private requested but Ollama unavailable")

    if complexity == "complex":
        if _anthropic_available():
            return RouteResult(Provider.ANTHROPIC, "claude-sonnet-5", "complex task → Claude Sonnet 5", cost_estimate=0.01)
        if _groq_available():
            return RouteResult(Provider.GROQ, os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "complex fallback → Groq 70B")

    # Default: Groq for speed/cost
    if _groq_available():
        return RouteResult(Provider.GROQ, os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "standard → Groq (fast+cheap)")

    if _ollama_available():
        return RouteResult(Provider.OLLAMA, os.getenv("OLLAMA_MODEL", "llama3"), "Groq unavailable → Ollama local")

    raise RuntimeError("No LLM provider available")


def record_usage(provider: Provider, tokens_in: int = 0, tokens_out: int = 0, error: bool = False):
    s = _STATS[provider]
    s.calls += 1
    s.tokens_in  += tokens_in
    s.tokens_out += tokens_out
    if error:
        s.errors += 1
    cin, cout = _COST[provider]
    s.cost_usd += (tokens_in * cin + tokens_out * cout) / 1_000_000


def usage_report() -> dict:
    return {
        p.value: {
            "calls":     s.calls,
            "tokens_in": s.tokens_in,
            "tokens_out":s.tokens_out,
            "cost_usd":  round(s.cost_usd, 4),
            "errors":    s.errors,
        }
        for p, s in _STATS.items()
    }
