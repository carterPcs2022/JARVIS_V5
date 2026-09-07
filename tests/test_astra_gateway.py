"""Tests for the optional Astra cognitive gateway."""
import pytest

from core.llm.astra_gateway import should_use_astra, astra_enabled


def test_astra_is_opt_in(monkeypatch):
    monkeypatch.delenv("ASTRA_ENABLED", raising=False)
    assert astra_enabled() is False
    assert should_use_astra("maximum intelligence") is False


def test_high_value_trigger_requires_opt_in(monkeypatch):
    monkeypatch.setenv("ASTRA_ENABLED", "true")
    assert should_use_astra("Use Astra for this hardest problem") is True


def test_normal_query_does_not_select_astra(monkeypatch):
    monkeypatch.setenv("ASTRA_ENABLED", "true")
    assert should_use_astra("what time is it") is False


def test_truthful_provider_shape(monkeypatch):
    """The gateway's fallback contract must identify the router path."""
    monkeypatch.setenv("ASTRA_ENABLED", "false")
    from core.llm import astra_gateway

    monkeypatch.setattr(
        "core.llm.router.think",
        lambda *args, **kwargs: "fallback answer",
    )
    result = astra_gateway.think("normal request")
    assert result["content"] == "fallback answer"
    assert result["provider"] == "router"
