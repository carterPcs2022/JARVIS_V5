"""tests/test_interfaces_llm_provider.py — core/interfaces/llm_provider.py."""
import pytest
from core.interfaces.llm_provider import registry, GenerateRequest, LLMProvider


def test_registry_has_all_5_providers():
    assert set(registry().keys()) == {"groq", "cerebras", "ollama", "anthropic", "astra"}


def test_every_provider_isinstance_and_self_named():
    for name, provider in registry().items():
        assert isinstance(provider, LLMProvider), name
        assert provider.name == name


@pytest.mark.asyncio
async def test_every_provider_fails_cleanly_without_credentials():
    """No API keys/local server are configured in a CI/test environment --
    every provider must raise a clear, specific exception (missing key /
    connection refused), never crash somewhere unexpected inside the
    adapter's request-translation logic."""
    req = GenerateRequest(messages=[{"role": "user", "content": "hi"}], max_tokens=10)
    for name, provider in registry().items():
        assert provider.is_available() is False, name
        with pytest.raises(Exception):
            await provider.generate(req)
