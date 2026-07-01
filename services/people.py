"""services/people.py — Relationship memory. JARVIS remembers everyone you mention."""
from __future__ import annotations
import json, logging, re
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
_PEOPLE_FILE = Path("memory/people.json")

_NAME_PATTERN = re.compile(
    r'\b(?:my\s+)?(?:friend|colleague|boss|coworker|partner|brother|sister|mom|dad|wife|husband|manager|client|contact)\s+([A-Z][a-z]+)\b'
    r'|(?:call|text|email|meet|talk\s+to|message)\s+([A-Z][a-z]+)\b'
    r'|\b([A-Z][a-z]{2,})\s+(?:said|told|asked|wants|needs|is|was|has|called|texted)',
    re.IGNORECASE
)

_RELATIONSHIP_PATTERN = re.compile(
    r'(?:my\s+)(friend|colleague|boss|coworker|partner|brother|sister|mom|dad|wife|husband|manager|client)',
    re.IGNORECASE
)


def _load() -> list:
    _PEOPLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _PEOPLE_FILE.exists():
        try:
            return json.loads(_PEOPLE_FILE.read_text())
        except Exception:
            pass
    return []


def _save(data: list):
    _PEOPLE_FILE.write_text(json.dumps(data, indent=2))


def extract_people(text: str) -> list[dict]:
    found = []
    rel_match = _RELATIONSHIP_PATTERN.search(text)
    relationship = rel_match.group(1).lower() if rel_match else "person"

    for m in _NAME_PATTERN.finditer(text):
        name = next((g for g in m.groups() if g), None)
        if not name:
            continue
        name = name.strip().title()
        if name.lower() in {"jarvis", "friday", "ok", "hey", "yes", "no", "the"}:
            continue
        found.append({
            "name":         name,
            "relationship": relationship,
            "context":      text[:200],
            "mentioned_at": datetime.now().isoformat(),
        })
    return found


def save_person(person: dict):
    people = _load()
    for p in people:
        if p["name"].lower() == person["name"].lower():
            p.update({k: v for k, v in person.items() if v})
            p["last_mentioned"] = datetime.now().isoformat()
            p.setdefault("mention_count", 0)
            p["mention_count"] += 1
            _save(people)
            return
    person["first_mentioned"] = datetime.now().isoformat()
    person["last_mentioned"]  = datetime.now().isoformat()
    person["mention_count"]   = 1
    people.append(person)
    _save(people)


def get_person(name: str) -> dict | None:
    for p in _load():
        if p["name"].lower() == name.lower():
            return p
    return None


def list_people() -> list[dict]:
    return _load()


def get_context_for_person(name: str) -> str:
    p = get_person(name)
    if not p:
        return ""
    last = p.get("last_mentioned", "")
    if last:
        delta = datetime.now() - datetime.fromisoformat(last)
        age   = f"{delta.days} days ago" if delta.days > 0 else "recently"
    else:
        age = "unknown"
    ctx = p.get("context", "")[:100]
    return f"{p['name']} ({p.get('relationship','person')}) — last mentioned {age}: \"{ctx}\""


def ingest_from_text(text: str):
    """Extract and save all people mentioned in a text."""
    for person in extract_people(text):
        save_person(person)


def get_people_context(text: str) -> str:
    """Scan text for known people and return context string."""
    people = _load()
    lines  = []
    for p in people:
        if p["name"].lower() in text.lower():
            lines.append(get_context_for_person(p["name"]))
    return "\n".join(lines) if lines else ""


def follow_up_reminders() -> list[str]:
    cutoff  = datetime.now() - timedelta(days=7)
    people  = _load()
    remind  = []
    for p in people:
        last = p.get("last_mentioned")
        if not last:
            continue
        rel = p.get("relationship", "")
        if rel in ("friend", "colleague", "client", "partner", "manager") and \
                datetime.fromisoformat(last) < cutoff:
            remind.append(f"You haven't mentioned {p['name']} in over a week.")
    return remind[:3]
