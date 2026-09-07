"""core/interfaces/llm_provider.py — uniform provider interface and lazy registry.

The live router remains responsible for production routing/fallback behavior.
This interface lets higher-level agent code address providers uniformly,
including the optional GPT-6 Astra Responses API adapter.
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
    system: str = ""
    effort: str = ""  # Extended reasoning effort where supported.


@dataclass
class ModelResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, Any] = field(default_factory=dict)
    thinking: str = ""
    raw: dict | None = None


class LLMProvider(ABC):
    """One model client, callable uniformly regardless of API shape."""
    name: str = "base"

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> ModelResponse:
        ...

    def is_available(self) -> bool:
        """Whether credentials/endpoint are configured; not a health check."""
        return True


_PROVIDERS: dict[str, LLMProvider] | None = None


def _build_registry() -> dict[str, LLMProvider]:
    from core.llm.openai import GroqProvider
    from core.llm.cerebras import CerebrasProvider
    from core.llm.ollama import OllamaProvider
    from core.llm.anthropic_client import AnthropicProvider
    from core.llm.astra import AstraProvider

    providers: list[LLMProvider] = [
        GroqProvider(),
        CerebrasProvider(),
        OllamaProvider(),
        AnthropicProvider(),
        AstraProvider(),
    ]
    return {p.name: p for p in providers}


def registry() -> dict[str, LLMProvider]:
    global _PROVIDERS
    if _PROVIDERS is None:
        _PROVIDERS = _build_registry()
    return _PROVIDERS


def get_provider(name: str) -> LLMProvider | None:
    return registry().get(name)
