"""tests/test_memory_working.py — Phase 5's working-memory write/read
wiring (core/memory.py::save_turn() -> core/working_memory.py ->
core/memory.py::working_memory_as_context())."""
from unittest import mock
import core.memory as mem
from core.working_memory import working_mem


def _save_turn_isolated(user: str, ai: str):
    with mock.patch("core.memory._load", return_value=[]), \
         mock.patch("core.memory._save", return_value=True), \
         mock.patch("core.protocols.shield.scan_and_redact", side_effect=lambda x: x):
        mem.save_turn(user, ai)


def test_save_turn_populates_working_memory():
    _save_turn_isolated("I'm debugging a memory leak in the Rust allocator", "Let's look at it.")
    _save_turn_isolated("what's the weather like", "Sunny, 72F.")
    assert working_mem.summary()["items"] == 2


def test_working_memory_as_context_is_content_relevant_not_just_recent():
    _save_turn_isolated("I'm debugging a memory leak in the Rust allocator", "Let's look at it.")
    _save_turn_isolated("what's the weather like", "Sunny, 72F.")

    relevant = mem.working_memory_as_context("tell me about the Rust allocator issue")
    assert "Rust allocator" in relevant

    irrelevant = mem.working_memory_as_context("completely unrelated topic xyz123")
    assert "Rust" not in irrelevant


def test_capacity_eviction_caps_at_7():
    for i in range(10):
        _save_turn_isolated(f"turn number {i} with some words to vary length {i * i}", "ok")
    assert working_mem.summary()["items"] == 7


def test_search_notes_no_dead_code_crash():
    """Regression test for the Phase 5 fix: search_notes() used to have an
    unreachable second `return clips[-limit:]` referencing undefined
    names -- harmless while unreachable, but confirm the function returns
    cleanly and doesn't somehow execute it."""
    with mock.patch("core.memory._load", return_value=[]):
        assert mem.search_notes("anything") == []
