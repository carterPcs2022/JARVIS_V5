"""core/interfaces/llm_provider.py — the LLMProvider protocol each model
client in core/llm/ (openai.py/Groq, cerebras.py, ollama.py,
anthropic_client.py) now implements, plus a lazy registry over them.

core/llm/router.py remains the live, real routing/fallback/caching logic —
this doesn't replace it or change how it calls each provider module today.
It's a uniform surface *alongside* router.py's existing one, for whatever
in Phase 2+ wants to call "a provider" without knowing that Anthropic's
client takes `system` as a separate argument while the other three expect
it inlined in `messages`, or that only Anthropic supports `effort`.

core/llm/cascade.py already sketches a Provider enum + RouteResult for
exactly this purpose but is unused (confirmed by the audit — nothing
imports it) and only names three of the four real providers (no Cerebras).
Left untouched here rather than folded in, since reconciling the two is
real routing-logic work for a later phase, not a Phase 1 "add interfaces
without moving/rewriting anything" change.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerateRequest:
    messages: list[dict]
    max_tokens: int = 1024
    temperature: float = 0.7
    model: str | None = None
    system: str = ""     # only Anthropic's client takes this separately; the
                          # OpenAI-compatible ones (Groq/Cerebras/Ollama) expect
                          # a {"role": "system", ...} message in `messages` instead
    effort: str = ""      # Anthropic extended-thinking effort; ignored elsewhere


@dataclass
class ModelResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, Any] = field(default_factory=dict)
    thinking: str = ""
    raw: dict | None = None


class LLMProvider(ABC):
    """One model client, callable uniformly regardless of the underlying
    API's actual request/response shape."""
    name: str = "base"

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> ModelResponse:
        ...

    def is_available(self) -> bool:
        """Whether this provider's credentials/endpoint are configured at
        all — not a live health check. Default True; providers that read
        an API key override this."""
        return True


_PROVIDERS: dict[str, LLMProvider] | None = None


def _build_registry() -> dict[str, LLMProvider]:
    from core.llm.openai import GroqProvider
    from core.llm.cerebras import CerebrasProvider
    from core.llm.ollama import OllamaProvider
    from core.llm.anthropic_client import AnthropicProvider

    providers: list[LLMProvider] = [
        GroqProvider(), CerebrasProvider(), OllamaProvider(), AnthropicProvider(),
    ]
    return {p.name: p for p in providers}


def registry() -> dict[str, LLMProvider]:
    global _PROVIDERS
    if _PROVIDERS is None:
        _PROVIDERS = _build_registry()
    return _PROVIDERS


def get_provider(name: str) -> LLMProvider | None:
    return registry().get(name)
