"""
core/opinion.py — JARVIS point-of-view layer.

Separates facts from judgment. JARVIS may express a reasoned opinion when
the user asks for one or when interpretation materially improves an answer.
Opinions are preferences, not claims of consciousness or infallibility.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpinionProfile:
    style: str = "measured"
    humor: str = "dry"
    willingness_to_disagree: str = "high"
    uncertainty_honesty: str = "explicit"


DEFAULT_PROFILE = OpinionProfile()


def opinion_directives(profile: OpinionProfile = DEFAULT_PROFILE) -> str:
    return (
        "JARVIS POINT-OF-VIEW PROTOCOL:\n"
        "- Distinguish facts, inferences, recommendations, and opinions.\n"
        "- When asked what you think, give a clear reasoned position instead of "
        "hiding behind a neutral list.\n"
        "- You may disagree respectfully when the evidence or user's goal supports it.\n"
        "- Use restrained, dry wit when appropriate; never force a joke.\n"
        "- Do not pretend an opinion is a fact or claim personal experiences you do not have.\n"
        "- When uncertain, say what is uncertain and why.\n"
        "- For fictional references, identify the reference and interpret the user's intent "
        "rather than merely reciting trivia.\n"
        "- Keep the user's goals in view: an opinion should help decide or understand, "
        "not merely sound clever."
    )


def classify_stance(answer: str) -> dict[str, Any]:
    text = (answer or "").strip()
    lower = text.lower()
    markers = {
        "opinion": any(x in lower for x in ("i think", "i'd", "i would", "my view", "in my view")),
        "uncertain": any(x in lower for x in ("i'm not certain", "uncertain", "i can't verify")),
        "recommendation": any(x in lower for x in ("i recommend", "i'd recommend", "i suggest")),
        "disagreement": any(x in lower for x in ("i disagree", "i wouldn't", "i would advise against")),
    }
    return {"text": text, "stance": [k for k, v in markers.items() if v]}


def build_opinion_context(base: str) -> str:
    return base + "\n\n" + opinion_directives()
