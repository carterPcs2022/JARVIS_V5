"""tests/test_model_updater.py — regression tests for ModelUpdater's
same-family version comparison, so a real version bump (e.g. llama-3.1 ->
llama-3.3) keeps auto-applying while a same-family-looking size jump
(e.g. gpt-oss-20b -> gpt-oss-120b) never gets silently auto-applied as if
it were one."""
from services.model_updater import _base_family, _is_newer


def test_same_size_version_bump_is_same_family():
    assert _base_family("llama-3.1-70b-versatile") == _base_family("llama-3.3-70b-versatile")


def test_same_size_version_bump_is_newer():
    assert _is_newer("llama-3.3-70b-versatile", "llama-3.1-70b-versatile")


def test_different_size_siblings_are_not_same_family():
    # openai/gpt-oss-20b and openai/gpt-oss-120b are two different models,
    # not sequential versions of one model -- the size suffix (a digit run
    # immediately followed by a letter) must not be stripped like a
    # version number, or ModelUpdater will auto-swap one in for the other.
    assert _base_family("openai/gpt-oss-20b") != _base_family("openai/gpt-oss-120b")


def test_different_size_siblings_not_flagged_via_check_registry():
    from services.model_updater import ModelUpdater
    updater = ModelUpdater.__new__(ModelUpdater)
    registry = {"instant": {"id": "openai/gpt-oss-20b"}}
    live_ids = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
    updates = updater._check_registry("groq", registry, live_ids)
    assert updates == []
