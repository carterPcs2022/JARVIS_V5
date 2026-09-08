"""Tests for bounded, approval-gated self-evolution."""

import pytest

from core.self_evolution import EvolutionPolicy, SelfEvolutionCoordinator


def test_default_policy_requires_human_approval_and_no_auto_deploy():
    policy = EvolutionPolicy()
    assert policy.require_human_approval is True
    assert policy.allow_auto_deploy is False
    assert policy.allow_auto_push is False


def test_policy_rejects_unbounded_or_autonomous_execution():
    with pytest.raises(ValueError):
        SelfEvolutionCoordinator(EvolutionPolicy(max_cycles=6))
    with pytest.raises(ValueError):
        SelfEvolutionCoordinator(EvolutionPolicy(allow_auto_deploy=True))
    with pytest.raises(ValueError):
        SelfEvolutionCoordinator(EvolutionPolicy(require_human_approval=False))


def test_coordinator_stops_when_cycle_finds_nothing(monkeypatch):
    class FakeEngine:
        def run_improvement_cycle(self):
            return {"queued": 0, "tested": 0}

    monkeypatch.setattr("core.self_improvement.self_improvement", FakeEngine())
    result = SelfEvolutionCoordinator(EvolutionPolicy(max_cycles=5)).run()
    assert len(result["cycles"]) == 1
    assert result["approval_required"] is True
    assert result["auto_deploy"] is False
