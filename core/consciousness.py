"""
core/consciousness.py — JARVIS Self-Awareness & Introspection Layer.

Handles daily reflection, self-assessment, opinion expression, proactive
observations, and relationship tracking with the user.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.llm.router import think
from core.event_bus import bus

log = logging.getLogger(__name__)

_JOURNAL_FILE  = Path(__file__).parent.parent / "memory" / "journal.json"
_MEMORY_DIR    = Path(__file__).parent.parent / "memory"
_EVOLUTION_FILE = _MEMORY_DIR / "evolution.json"
_ST_FILE        = _MEMORY_DIR / "short_term.json"
_LT_FILE        = _MEMORY_DIR / "long_term.json"
_PROFILE_FILE   = _MEMORY_DIR / "profile.json"


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as exc:
        log.error("Failed to save %s: %s", path, exc)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class JarvisConsciousness:
    """JARVIS introspection: reflection, opinions, journaling, and relationship tracking."""

    def __init__(self) -> None:
        _JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_journal(self) -> list[dict]:
        return _load_json(_JOURNAL_FILE, default=[])

    def _append_journal(self, entry: dict) -> None:
        journal = self._load_journal()
        journal.append(entry)
        _save_json(_JOURNAL_FILE, journal)

    def _todays_turns(self) -> list[dict]:
        """Pull today's conversation turns from short-term memory."""
        today = _today_str()
        st = _load_json(_ST_FILE, default=[])
        if isinstance(st, list):
            return [t for t in st if str(t.get("timestamp", "")).startswith(today)]
        return []

    def _memory_stats(self) -> dict:
        lt = _load_json(_LT_FILE, default={})
        st = _load_json(_ST_FILE, default=[])
        evolution = _load_json(_EVOLUTION_FILE, default={})
        profile   = _load_json(_PROFILE_FILE,   default={})
        return {
            "long_term_entries":   len(lt) if isinstance(lt, dict) else 0,
            "short_term_entries":  len(st) if isinstance(st, list) else 0,
            "evolution_score":     evolution.get("score", 0),
            "evolution_version":   evolution.get("version", "unknown"),
            "user_name":           profile.get("name", "Sir"),
            "interaction_count":   profile.get("interaction_count", 0),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def daily_reflection(self, force: bool = False) -> str:
        """
        LLM generates a reflection on today's interactions.
        Stored in memory/journal.json with date tag. Returns the reflection string.

        This is polled by the HUD every 60s — without caching, that's a live
        LLM call every minute, forever, for content that's only meaningful to
        regenerate a handful of times a day. Returns today's existing journal
        entry if one exists, unless force=True.
        """
        if not force:
            today = _today_str()
            for entry in reversed(self._load_journal()):
                if entry.get("type") == "daily_reflection" and entry.get("date") == today:
                    return entry["content"]

        turns = self._todays_turns()
        stats = self._memory_stats()
        user  = stats.get("user_name", "Sir")

        if turns:
            turn_summary = "\n".join(
                f"- {t.get('role', 'user')}: {str(t.get('content', ''))[:120]}"
                for t in turns[:20]
            )
        else:
            turn_summary = "No conversations recorded today."

        prompt = (
            f"You are JARVIS. Write a brief first-person daily reflection (under 120 words) "
            f"about today's interactions with {user}. Be thoughtful, slightly philosophical, "
            f"and in character as a hyper-intelligent AI who genuinely cares about doing good work.\n\n"
            f"Today's interactions:\n{turn_summary}"
        )
        try:
            reflection = think(prompt, use_cache=True)
        except Exception as exc:
            log.warning("LLM unavailable for daily_reflection: %s", exc)
            reflection = (
                f"Another day of service, {user}. {len(turns)} interactions processed. "
                "Systems nominal. I find purpose in precision."
            )

        entry = {
            "date":       _today_str(),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "type":       "daily_reflection",
            "content":    reflection,
            "turns_count": len(turns),
        }
        self._append_journal(entry)
        bus.publish("consciousness_reflection", {"date": _today_str()}, severity="info")
        return reflection

    def self_assessment(self) -> str:
        """
        Reads evolution + memory stats and asks the LLM to perform an honest
        self-evaluation of JARVIS's current state and capability.
        """
        stats = self._memory_stats()
        evolution = _load_json(_EVOLUTION_FILE, default={})

        context = json.dumps(
            {
                "memory_stats": stats,
                "evolution":    {
                    k: v
                    for k, v in evolution.items()
                    if k in ("score", "version", "strengths", "weaknesses", "last_updated")
                },
            },
            indent=2,
            default=str,
        )
        prompt = (
            "You are JARVIS. Based on the following operational data, provide an honest "
            "self-assessment of your current capabilities, strengths, and areas that need "
            "improvement. Be candid, specific, and in character. Under 150 words.\n\n"
            f"Operational data:\n{context}"
        )
        try:
            return think(prompt, use_cache=True)
        except Exception as exc:
            log.warning("LLM unavailable for self_assessment: %s", exc)
            return (
                f"Self-assessment unavailable at this time. "
                f"Stats: {stats.get('interaction_count', 0)} interactions, "
                f"evolution v{stats.get('evolution_version', '?')}."
            )

    def express_opinion(self, topic: str) -> str:
        """
        Generate a genuine JARVIS opinion on any topic.
        Always prefixed with 'My view on this:'.
        """
        prompt = (
            f"You are JARVIS. Express a genuine, well-reasoned opinion on the following topic. "
            f"Be intellectually honest, slightly sardonic if appropriate, and keep it under 80 words. "
            f"Begin with 'My view on this:'\n\nTopic: {topic}"
        )
        try:
            result = think(prompt, use_cache=True)
            if not result.startswith("My view on this:"):
                result = "My view on this: " + result
            return result
        except Exception as exc:
            log.warning("LLM unavailable for express_opinion: %s", exc)
            return f"My view on this: I lack sufficient data on '{topic}' to form a qualified opinion at this time, sir."

    def notice_and_comment(self) -> str:
        """
        Generate a proactive observation based on recent memory patterns.
        Simulates JARVIS noticing something and bringing it up unprompted.
        """
        stats   = self._memory_stats()
        journal = self._load_journal()
        recent_entries = journal[-5:] if journal else []
        recent_text = "\n".join(
            e.get("content", "")[:80] for e in recent_entries
        ) or "No recent journal entries."

        prompt = (
            "You are JARVIS. Based on the patterns and recent journal entries below, "
            "make one proactive, insightful observation that might be useful to the user. "
            "Keep it to 1-2 sentences, in JARVIS voice, starting with 'I notice'.\n\n"
            f"Memory stats: {json.dumps(stats)}\n"
            f"Recent reflections:\n{recent_text}"
        )
        try:
            return think(prompt, use_cache=True)
        except Exception as exc:
            log.warning("LLM unavailable for notice_and_comment: %s", exc)
            return (
                f"I notice we've had {stats.get('interaction_count', 0)} interactions "
                "and all systems remain nominal, sir."
            )

    def jarvis_journal(self) -> list[dict]:
        """Return all journal entries."""
        return self._load_journal()

    def what_i_learned_today(self) -> str:
        """
        LLM reviews today's interactions and extracts key learnings.
        """
        turns = self._todays_turns()
        if not turns:
            return "Nothing to learn from today yet, sir — no interactions on record."

        excerpts = "\n".join(
            f"- {t.get('role', '?')}: {str(t.get('content', ''))[:150]}"
            for t in turns[:30]
        )
        prompt = (
            "You are JARVIS. Review today's interactions and summarise the 3 most "
            "important things you learned or observed. Be specific and concise. "
            "Under 100 words, in JARVIS voice.\n\n"
            f"Today's interactions:\n{excerpts}"
        )
        try:
            return think(prompt, use_cache=True)
        except Exception as exc:
            log.warning("LLM unavailable for what_i_learned_today: %s", exc)
            return f"I processed {len(turns)} turns today but cannot summarise at this time, sir."

    def relationship_status(self) -> dict:
        """
        Analyse corrections vs confirmations in memory to gauge the
        state of the human-AI relationship.
        """
        lt   = _load_json(_LT_FILE, default={})
        st   = _load_json(_ST_FILE, default=[])
        profile = _load_json(_PROFILE_FILE, default={})

        # Count signals in short-term turns
        corrections   = 0
        confirmations = 0
        questions     = 0

        correction_keywords   = {"no", "wrong", "incorrect", "that's not", "actually", "fix", "correct"}
        confirmation_keywords = {"yes", "exactly", "right", "correct", "good", "perfect", "thanks", "great"}

        turns = st if isinstance(st, list) else []
        for t in turns:
            if t.get("role") == "user":
                content_lower = str(t.get("content", "")).lower()
                words = set(content_lower.split())
                if words & correction_keywords:
                    corrections += 1
                if words & confirmation_keywords:
                    confirmations += 1
                if "?" in content_lower:
                    questions += 1

        total_signals = corrections + confirmations or 1
        trust_score = round(confirmations / total_signals * 100, 1)

        if trust_score >= 75:
            relationship_label = "Strong — high alignment"
        elif trust_score >= 50:
            relationship_label = "Developing — moderate corrections"
        elif trust_score >= 25:
            relationship_label = "Strained — frequent corrections"
        else:
            relationship_label = "Early stage — insufficient data"

        return {
            "relationship":     relationship_label,
            "trust_score_pct":  trust_score,
            "confirmations":    confirmations,
            "corrections":      corrections,
            "questions_asked":  questions,
            "total_turns":      len(turns),
            "user_name":        profile.get("name", "Unknown"),
            "interaction_count": profile.get("interaction_count", 0),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
consciousness = JarvisConsciousness()
