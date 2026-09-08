"""Regression tests for the JARVIS cognitive routing boundary."""
from __future__ import annotations

from unittest.mock import patch

from core.cognitive_router import CognitiveRouter


def test_safety_early_exit_wins_over_astra_preference():
    brain_result = {"response": "real handler", "ok": True, "provider": "brain"}

    with (
        patch("core.cognitive_router.brain", create=True) as _unused,
        patch("core.brain_v2.brain.process_dict", return_value=brain_result) as process,
        patch("core.llm.astra_gateway.should_use_astra", return_value=True) as should_astra,
        patch("core.llm.astra_gateway.think") as astra_think,
    ):
        result = CognitiveRouter().route("need your best: run a self check")

    assert result == brain_result
    process.assert_called_once_with("need your best: run a self check")
    should_astra.assert_not_called()
    astra_think.assert_not_called()


def test_non_action_high_value_request_can_use_astra():
    astra_result = {
        "content": "deep analysis",
        "model": "gpt-6-astra",
        "provider": "astra",
    }

    with (
        patch("core.brain_v2.brain.process_dict") as process,
        patch("core.llm.astra_gateway.should_use_astra", return_value=True),
        patch("core.llm.astra_gateway.think", return_value=astra_result),
    ):
        result = CognitiveRouter().route("need your best analysis of this architecture")

    assert result == {
        "response": "deep analysis",
        "ok": True,
        "model": "gpt-6-astra",
        "provider": "astra",
    }
    process.assert_not_called()
