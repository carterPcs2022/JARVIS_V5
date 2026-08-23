"""tests/test_reflection.py — regression tests for core/reflection.py's
FINAL: extraction, so a critic model that reasons out loud instead of
answering cleanly can never leak its raw chain-of-thought into a real
JARVIS response again (confirmed live on Discord: the entire reflection
prompt's internal debate about scoring got sent as the actual reply)."""
from unittest import mock
import core.reflection as reflection_mod


def test_reflect_uses_clean_final_when_well_formed():
    raw = "SCORE: 4\nCRITIQUE: Too generic.\nFINAL: Systems nominal, sir."
    with mock.patch("core.reflection.think", return_value=raw):
        result = reflection_mod.reflect("status?", "Everything's fine!")
    assert result["final"] == "Systems nominal, sir."
    assert result["was_rewritten"] is True


def test_reflect_falls_back_to_draft_on_rambling_final():
    draft = "Systems nominal, sir."
    # Mirrors the real failure: the critic reasons out loud through the
    # whole FINAL section instead of just answering, without ever
    # re-emitting a literal "SCORE:" marker (lowercase "score it 6/10"
    # doesn't match the old guard).
    raw = (
        "SCORE: 6\nCRITIQUE: A bit clunky.\n"
        "FINAL: I'm not certain, but -- let me reconsider. I'll score it "
        "6/10 initially, but maybe I should reconsider and score it 7 "
        "instead, since it's functional. Let's think through this some "
        "more before committing to a final answer, weighing several "
        "options and rewriting multiple drafts along the way to be safe. "
        + ("Still thinking. " * 40)
    )
    with mock.patch("core.reflection.think", return_value=raw):
        result = reflection_mod.reflect("status?", draft)
    assert result["final"] == draft
    assert result["was_rewritten"] is False


def test_reflect_falls_back_to_draft_when_final_echoes_score_marker():
    raw = "SCORE: 5\nCRITIQUE: Meh.\nFINAL: Some answer\nSCORE: 8\nFINAL: Another"
    with mock.patch("core.reflection.think", return_value=raw):
        result = reflection_mod.reflect("status?", "original draft")
    assert result["final"] == "original draft"


def test_reflect_allows_a_legitimately_longer_final_for_a_short_draft():
    draft = "OK."
    raw = ("SCORE: 3\nCRITIQUE: No detail.\n"
           "FINAL: All systems nominal, sir -- arc reactor at 51%, "
           "weapons online, shields on standby.")
    with mock.patch("core.reflection.think", return_value=raw):
        result = reflection_mod.reflect("status?", draft)
    assert "arc reactor" in result["final"]
