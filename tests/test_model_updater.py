"""Regression tests for ModelUpdater's capability-aware Groq selection."""
from services.model_updater import _base_family, _is_newer, ModelUpdater


def test_same_size_version_bump_is_same_family():
    assert _base_family("llama-3.1-70b-versatile") == _base_family("llama-3.3-70b-versatile")


def test_same_size_version_bump_is_newer():
    assert _is_newer("llama-3.3-70b-versatile", "llama-3.1-70b-versatile")


def test_different_size_siblings_are_not_same_family():
    # Size suffixes such as 20b/120b are different models, not versions.
    assert _base_family("openai/gpt-oss-20b") != _base_family("openai/gpt-oss-120b")


def test_groq_selection_does_not_treat_size_jump_as_an_upgrade():
    updater = ModelUpdater.__new__(ModelUpdater)
    live_models = {
        "openai/gpt-oss-20b": {},
        "openai/gpt-oss-120b": {},
    }
    winner = updater._best_groq_for_tier("instant", live_models, "openai/gpt-oss-20b")
    assert winner["id"] == "openai/gpt-oss-20b"


def test_groq_selection_can_choose_a_materially_better_profile():
    updater = ModelUpdater.__new__(ModelUpdater)
    live_models = {
        "openai/gpt-oss-20b": {},
        "qwen/qwen3.8-27b": {},
    }
    winner = updater._best_groq_for_tier("reasoning", live_models, "openai/gpt-oss-20b")
    assert winner["id"] == "qwen/qwen3.8-27b"


def test_missing_groq_model_gets_a_safe_profiled_replacement():
    updater = ModelUpdater.__new__(ModelUpdater)
    registry = {"reasoning": {"id": "qwen/old-model"}}
    live_models = {
        "qwen/old-model": {"active": False},
        "qwen/qwen3.8-27b": {},
    }
    updates = updater._check_groq(registry, live_models)
    assert len(updates) == 1
    assert updates[0]["type"] == "deprecated"
    assert updates[0]["new_model"] == "qwen/qwen3.8-27b"
