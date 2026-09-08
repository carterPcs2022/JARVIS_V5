"""Tests for decision pushback and local recovery behavior."""

import pytest

from core.decision_guard import assess_decision, pushback_message
from core.resilience import fragment_state


def test_pushback_requires_action_plus_pressure():
    result = assess_decision("delete it right now, just do it")
    assert result.should_push_back is True
    assert result.risk_score >= 70
    assert "irreversible" in pushback_message(result)


def test_emotion_alone_does_not_block():
    result = assess_decision("I'm furious about this bug; explain what happened")
    assert result.should_push_back is False


def test_normal_action_does_not_block():
    result = assess_decision("deploy the tested update tomorrow")
    assert result.should_push_back is False


def test_recovery_fragments_are_bounded_and_local():
    fragments = fragment_state("abcdef" * 100, chunk_size=256)
    assert fragments
    assert max(len(item["data"]) for item in fragments) <= 256
    assert [item["index"] for item in fragments] == list(range(len(fragments)))


def test_recovery_fragments_reject_secret_like_content():
    with pytest.raises(ValueError):
        fragment_state("api_key=not-for-storage")
