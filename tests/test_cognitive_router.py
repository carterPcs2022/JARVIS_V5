"""Regression tests for the JARVIS cognitive routing boundary."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from core.cognitive_router import CognitiveRouter, should_use_agent_loop


def test_safety_early_exit_wins_over_astra_preference():
    brain_result = {"response": "real handler", "ok": True, "provider": "brain"}
    with (
        patch("core.brain_v2.brain.process_dict", return_value=brain_result) as process,
        patch("core.llm.astra_gateway.should_use_astra", return_value=True) as should_astra,
        patch("core.llm.astra_gateway.think") as astra_think,
    ):
        result = CognitiveRouter().route("use astra: run a self check")
    assert result["response"] == brain_result["response"]
    assert result["provider"] == brain_result["provider"]
    assert result["conscience"]["recommendation"] == "proceed_if_authorized"
    process.assert_called_once_with("use astra: run a self check")
    should_astra.assert_not_called()
    astra_think.assert_not_called()


def test_decision_guard_pushes_back_before_astra():
    with (
        patch("core.brain_v2.brain.process_dict") as process,
        patch("core.llm.astra_gateway.should_use_astra", return_value=True) as should_astra,
        patch("core.llm.astra_gateway.think") as astra_think,
    ):
        result = CognitiveRouter().route("use astra, delete it right now, just do it")
    assert result["ok"] is False
    assert result["requires_review"] is True
    assert result["provider"] == "decision_guard"
    assert result["conscience"]["recommendation"] == "pause_and_review"
    process.assert_not_called()
    should_astra.assert_not_called()
    astra_think.assert_not_called()


def test_non_action_high_value_request_can_use_astra():
    astra_result = {"content": "deep analysis", "model": "gpt-6-astra", "provider": "astra"}
    with (
        patch("core.brain_v2.brain.process_dict") as process,
        patch("core.llm.astra_gateway.should_use_astra", return_value=True),
        patch("core.llm.astra_gateway.think", return_value=astra_result),
    ):
        result = CognitiveRouter().route("use astra for analysis of this architecture")
    assert result["response"] == "deep analysis"
    assert result["ok"] is True
    assert result["model"] == "gpt-6-astra"
    assert result["provider"] == "astra"
    assert result["conscience"]["values_checked"]
    process.assert_not_called()


def test_agent_loop_intent_detects_github_work():
    with patch("core.llm.astra_gateway.should_use_astra", return_value=False):
        assert should_use_agent_loop("review my GitHub pull request") is True


def test_async_router_connects_real_agent_loop():
    result = {
        "content": "I found the repository.",
        "model": "gpt-6-astra",
        "provider": "astra",
        "executed": [{"tool": "github_repos", "ok": True, "attempts": 1}],
        "rounds": 2,
    }
    with patch("core.agent_loop.agent_loop.run_astra", new_callable=AsyncMock, return_value=result) as run:
        import asyncio
        routed = asyncio.run(CognitiveRouter().route_async("review my GitHub repositories"))
    assert routed["response"] == result["content"]
    assert routed["agent"]["executed"] == result["executed"]
    assert routed["provider"] == "astra"
    run.assert_awaited_once()
