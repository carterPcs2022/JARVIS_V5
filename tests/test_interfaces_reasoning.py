"""tests/test_interfaces_reasoning.py — core/interfaces/reasoning.py."""
import asyncio
import pytest
from core.interfaces.reasoning import registry, get_strategy, ReasoningStrategy


def test_registry_has_all_16_strategies():
    r = registry()
    # 8 from Phase 1 (orchestrator.py's side-door set) + 8 from Phase 2
    # (brain_v2.py's native reasoning-engine set) -- the two never overlap.
    expected = {
        "direct", "chain_of_thought", "verify", "react", "tree_of_thought",
        "graph_of_thought", "self_consistency", "mixture_of_agents",
        "six_hats", "premortem", "fermi", "first_principles",
        "constraint_solver", "game_theory", "info_value", "mental_models",
    }
    assert set(r.keys()) == expected


def test_every_strategy_isinstance_and_self_named():
    for name, strategy in registry().items():
        assert isinstance(strategy, ReasoningStrategy), name
        assert strategy.name == name


@pytest.mark.asyncio
async def test_direct_strategy_solve_degrades_gracefully_without_llm_keys():
    """No LLM keys are configured in a CI/test environment -- solve() must
    not raise, and must return a ReasoningResult with SOME answer text
    (core.llm.router degrades to "[JARVIS OFFLINE] ..." rather than
    raising, and this must survive the async plumbing unchanged)."""
    strategy = get_strategy("direct")
    result = await strategy.solve("what is 2+2?")
    assert result.answer
    assert result.strategy == "direct"


def test_get_strategy_unknown_name_returns_none():
    assert get_strategy("not_a_real_strategy") is None
