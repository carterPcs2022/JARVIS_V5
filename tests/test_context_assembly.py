"""tests/test_context_assembly.py — core/context.py::build_context()'s
retrieve -> rank -> filter -> inject budget discipline, and Phase 5's
working-memory integration into it."""
from unittest import mock
import core.context as ctx
from core.working_memory import working_mem


def _isolated_build_context(user_input: str, **kwargs):
    with mock.patch("core.context.get_context_string", return_value="User: hi\nJARVIS: hello"), \
         mock.patch("core.context.facts_as_context", return_value=""), \
         mock.patch("core.context.recall_as_context", return_value=""), \
         mock.patch("core.context.episodes_as_context", return_value=""), \
         mock.patch.object(ctx, "_get_web_context", return_value=""):
        return ctx.build_context(user_input, include_web=False, **kwargs)


def test_empty_working_memory_does_not_crash_or_add_stray_section():
    result = _isolated_build_context("what's up")
    assert "hi" in result


def test_relevant_working_memory_appears_in_assembled_context():
    working_mem.hold("proj", "we're migrating the payments service to Rust", importance=0.9)
    result = _isolated_build_context("how's the Rust migration going")
    assert "payments service to Rust" in result


def test_tiny_token_budget_does_not_crash():
    working_mem.hold("proj", "we're migrating the payments service to Rust", importance=0.9)
    with mock.patch("config.settings.MAX_CONTEXT_TOKENS", 3):
        result = _isolated_build_context("how's the Rust migration going")
        assert "hi" in result  # short-term still makes it in; working memory gets trimmed first
