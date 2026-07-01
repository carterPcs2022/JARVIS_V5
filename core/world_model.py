"""
core/world_model.py — JARVIS World Model.

Maintains a structured knowledge graph of people, places, projects, assets,
events, interests, and behavioural patterns extracted from conversations.
All extraction is done via regex + keyword heuristics — no LLM calls here.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MODEL_FILE = Path(__file__).parent.parent / "memory" / "world_model.json"

_EMPTY_MODEL: dict[str, dict] = {
    "people":    {},
    "places":    {},
    "projects":  {},
    "assets":    {},
    "events":    {},
    "interests": {},
    "patterns":  {},
}

# ── Regex patterns ────────────────────────────────────────────────────────────

# People: capitalized word(s) after social-context keywords
_PERSON_RE = re.compile(
    r"(?:with|from|called|meeting|talked to|spoke to|email|message|contact|"
    r"invited|hire|hired|told|asked|see|saw|knows?|knows? about|friend|colleague|"
    r"boss|manager|client|partner)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    re.IGNORECASE,
)

# Places: capitalized word after prepositions
_PLACE_RE = re.compile(
    r"(?:at|in|to|from|near|around|visit|visited|going to|live in|based in|"
    r"office in|located in|flew to|travel to|heading to)\s+([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)?)",
    re.IGNORECASE,
)

# Projects: capitalized noun after ownership/article words + project synonyms
_PROJECT_RE = re.compile(
    r"(?:the|my|our|your|this|that|a|an)\s+([A-Z][a-zA-Z0-9_\-]{2,}|[a-z][a-zA-Z0-9_\-]{2,})"
    r"\s+(?:project|app|system|repo|repository|platform|service|tool|bot|agent|site|api|backend|frontend)",
    re.IGNORECASE,
)

# Known city names for extra place detection
_MAJOR_CITIES = frozenset([
    "London", "New York", "Paris", "Tokyo", "Berlin", "Sydney", "Toronto",
    "Los Angeles", "Chicago", "Singapore", "Dubai", "Seoul", "Mumbai",
    "Beijing", "Shanghai", "Moscow", "Lagos", "Cairo", "São Paulo",
    "Mexico City", "Amsterdam", "Madrid", "Rome", "Bangkok", "Jakarta",
    "San Francisco", "Seattle", "Boston", "Austin", "Miami", "Denver",
    "Atlanta", "Dallas", "Phoenix", "Las Vegas", "Nashville",
])


def _normalise(name: str) -> str:
    return name.strip().title()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorldModel:
    """Structured knowledge model of the user's world, extracted from conversations."""

    def __init__(self) -> None:
        _MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._model = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if _MODEL_FILE.exists():
            try:
                with open(_MODEL_FILE) as f:
                    data = json.load(f)
                # Ensure all categories present
                for key in _EMPTY_MODEL:
                    data.setdefault(key, {})
                return data
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("world_model.json unreadable, starting fresh: %s", exc)
        return {k: {} for k in _EMPTY_MODEL}

    def _save(self) -> None:
        try:
            with open(_MODEL_FILE, "w") as f:
                json.dump(self._model, f, indent=2, default=str)
        except OSError as exc:
            log.error("Failed to save world_model.json: %s", exc)

    def _touch_entity(self, category: str, name: str, extra: dict | None = None) -> None:
        """Create or update an entity, always refreshing last_seen."""
        bucket = self._model.setdefault(category, {})
        if name not in bucket:
            bucket[name] = {
                "first_seen": _now(),
                "last_seen":  _now(),
                "mention_count": 1,
            }
        else:
            bucket[name]["last_seen"] = _now()
            bucket[name]["mention_count"] = bucket[name].get("mention_count", 0) + 1
        if extra:
            bucket[name].update(extra)

    # ── Extraction ────────────────────────────────────────────────────────────

    def update_from_conversation(self, text: str) -> dict[str, list[str]]:
        """
        Extract entities from conversation text using regex + keyword heuristics.
        No LLM calls — fast, deterministic, side-effect free on failure.

        Returns dict of {category: [extracted names]} for inspection.
        """
        extracted: dict[str, list[str]] = {
            "people": [], "places": [], "projects": []
        }

        # ── People ────────────────────────────────────────────────────────────
        for m in _PERSON_RE.finditer(text):
            name = _normalise(m.group(1))
            if len(name) > 2 and name not in {"The", "A", "An", "It", "He", "She", "They"}:
                self._touch_entity("people", name)
                extracted["people"].append(name)

        # ── Places ────────────────────────────────────────────────────────────
        for m in _PLACE_RE.finditer(text):
            name = _normalise(m.group(1))
            if len(name) > 2:
                self._touch_entity("places", name)
                extracted["places"].append(name)

        # Also catch well-known city names mentioned bare in text
        for city in _MAJOR_CITIES:
            if re.search(rf"\b{re.escape(city)}\b", text):
                self._touch_entity("places", city)
                if city not in extracted["places"]:
                    extracted["places"].append(city)

        # ── Projects ─────────────────────────────────────────────────────────
        for m in _PROJECT_RE.finditer(text):
            name = _normalise(m.group(1))
            if len(name) >= 2:
                self._touch_entity("projects", name)
                extracted["projects"].append(name)

        # ── Interests / topics ────────────────────────────────────────────────
        interest_re = re.compile(
            r"(?:interested in|into|love|enjoy|studying|learning about|researching|"
            r"working on|passionate about)\s+([a-zA-Z\s]{3,30}?)(?:[,.\n]|$)",
            re.IGNORECASE,
        )
        for m in interest_re.finditer(text):
            interest = m.group(1).strip().lower()
            if 3 <= len(interest) <= 50:
                self._touch_entity("interests", interest)

        self._save()
        return extracted

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_context_for_query(self, query: str) -> str:
        """
        Search the world model for entities relevant to the query.
        Returns a short context string.
        """
        query_lower = query.lower()
        hits: list[str] = []

        for category, entities in self._model.items():
            if not isinstance(entities, dict):
                continue
            for name, data in entities.items():
                if name.lower() in query_lower or query_lower in name.lower():
                    count = data.get("mention_count", 1)
                    last  = str(data.get("last_seen", ""))[:10]
                    hits.append(f"{category.title()}: {name} (seen {count}x, last {last})")

        if not hits:
            return ""
        return "Relevant context from world model:\n" + "\n".join(hits[:10])

    def world_summary(self) -> str:
        """Return a brief summary with entity counts per category."""
        lines = ["World Model Summary:"]
        for category, entities in self._model.items():
            count = len(entities) if isinstance(entities, dict) else 0
            lines.append(f"  {category.title()}: {count} known")
        return "\n".join(lines)

    def get_model(self) -> dict:
        """Return the full raw model dict."""
        return self._model

    def update_entity(self, category: str, name: str, data: dict) -> None:
        """
        Directly update or create a specific entity in any category.

        Args:
            category: One of the world model keys.
            name:     Entity name.
            data:     Arbitrary key-value data to merge in.
        """
        if category not in self._model:
            self._model[category] = {}
        self._touch_entity(category, name, extra=data)
        self._save()
        log.debug("World model updated: %s / %s", category, name)


# ── Module-level singleton ────────────────────────────────────────────────────
world = WorldModel()
