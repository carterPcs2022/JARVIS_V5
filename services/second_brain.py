"""services/second_brain.py — Zettelkasten-style personal knowledge management.

Atomic notes, auto-linking, daily notes, weekly review, and Obsidian export.
Stored as one JSON file per note under memory/second_brain/.
"""
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from config.settings import BASE_DIR

NOTES_DIR = BASE_DIR / "memory" / "second_brain"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", (text or "").lower()))


class SecondBrain:

    def _ensure_dir(self):
        NOTES_DIR.mkdir(parents=True, exist_ok=True)

    def _note_path(self, note_id: str) -> Path:
        return NOTES_DIR / f"{note_id}.json"

    def list_notes(self) -> list[dict]:
        self._ensure_dir()
        notes = []
        for f in NOTES_DIR.glob("*.json"):
            try:
                notes.append(json.loads(f.read_text()))
            except Exception:
                continue
        return sorted(notes, key=lambda n: n.get("created", ""), reverse=True)

    def _generate_title(self, content: str) -> str:
        try:
            from core.llm.router import think
            raw = think(
                f"Generate a short (5-8 word) title for this note. "
                f"Reply with ONLY the title itself — no quotes, no commentary, no extra sentences.\n\n{content[:500]}",
                max_tokens=20,
            )
            # Defensive: keep only the first line in case the model adds commentary anyway.
            title = raw.strip().split("\n")[0].strip().strip('"').strip()
            if title:
                return title
        except Exception:
            pass
        words = content.split()[:8]
        return " ".join(words) + ("..." if len(content.split()) > 8 else "")

    def _suggest_tags(self, content: str) -> list[str]:
        try:
            from core.llm.router import think
            raw = think(f"Suggest 2-4 single-word lowercase tags for this note, comma separated only:\n\n{content[:500]}",
                       max_tokens=30)
            return [t.strip().lower() for t in raw.split(",") if t.strip()][:4]
        except Exception:
            return []

    def capture(self, content: str, tags: list[str] | None = None, source: str = "") -> dict:
        self._ensure_dir()
        note_id = uuid.uuid4().hex[:12]
        title = self._generate_title(content)
        tags = tags or self._suggest_tags(content)
        links = [n["id"] for n in self.find_connections_by_content(content, limit=3)]

        note = {
            "id": note_id, "title": title, "content": content,
            "tags": tags, "links": links, "source": source,
            "created": datetime.now().isoformat(),
        }
        self._note_path(note_id).write_text(json.dumps(note, indent=2))
        return note

    def find_connections_by_content(self, content: str, limit: int = 5) -> list[dict]:
        toks = _tokenize(content)
        scored = []
        for n in self.list_notes():
            other_toks = _tokenize(n.get("content", ""))
            overlap = len(toks & other_toks)
            if overlap > 2:
                scored.append((n, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [n for n, _ in scored[:limit]]

    def find_connections(self, note_id: str) -> list[dict]:
        path = self._note_path(note_id)
        if not path.exists():
            return []
        note = json.loads(path.read_text())
        return self.find_connections_by_content(note["content"])

    def get_note(self, note_id: str) -> dict | None:
        path = self._note_path(note_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def daily_note(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        existing = [n for n in self.list_notes() if n.get("source") == f"daily:{today}"]
        if existing:
            return existing[0]

        parts = [f"# {datetime.now().strftime('%A, %B %d, %Y')}"]
        try:
            from services.calendar_intel import calendar_intel
            events = calendar_intel.get_today()
            if events:
                parts.append("## Today's events\n" + "\n".join(f"- {e.get('title','')}" for e in events))
        except Exception:
            pass
        try:
            from services.productivity import productivity
            tasks = productivity.task_list("active")
            if tasks:
                parts.append("## Open tasks\n" + "\n".join(f"- {t.get('title','')}" for t in tasks[:10]))
        except Exception:
            pass
        try:
            from core.llm.router import think
            focus = think("Suggest three things to focus on today, one line each, no preamble.", max_tokens=100)
            parts.append(f"## Focus today\n{focus}")
        except Exception:
            pass

        content = "\n\n".join(parts)
        return self.capture(content, tags=["daily"], source=f"daily:{today}")

    def weekly_review(self) -> str:
        week_ago = datetime.now() - timedelta(days=7)
        recent = [n for n in self.list_notes()
                  if n.get("created", "") >= week_ago.isoformat()]
        summary = "\n".join(f"- {n['title']}" for n in recent[:30])
        try:
            from core.llm.router import think
            prompt = (
                f"Here are this week's captured notes:\n{summary}\n\n"
                "Guide a weekly review: what was accomplished, what's still open, "
                "what should move to next week, and any patterns you notice. Be concise."
            )
            return think(prompt, max_tokens=400)
        except Exception:
            return f"This week you captured {len(recent)} notes:\n{summary}"

    def brain_dump(self, text: str) -> dict:
        """Split a raw dump of thoughts into distinct notes with action items extracted."""
        try:
            from core.llm.router import think
            raw = think(
                "Split this brain dump into distinct ideas. For each, give a one-line "
                "summary. Then list any action items separately, prefixed with 'ACTION:'. "
                f"Text:\n\n{text}", max_tokens=600
            )
        except Exception:
            raw = text

        ideas = [line.strip("- ").strip() for line in raw.split("\n")
                 if line.strip() and not line.strip().startswith("ACTION:")]
        actions = [line.split("ACTION:", 1)[1].strip() for line in raw.split("\n")
                   if "ACTION:" in line]

        created_notes = [self.capture(idea, source="brain_dump") for idea in ideas if idea]
        return {"notes_created": len(created_notes), "notes": created_notes, "action_items": actions}

    def search_notes(self, query: str) -> list[dict]:
        q_toks = _tokenize(query)
        scored = []
        for n in self.list_notes():
            overlap = len(q_toks & _tokenize(n.get("content", "") + " " + n.get("title", "")))
            if overlap:
                scored.append((n, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [n for n, _ in scored[:20]]

    def export_obsidian(self, output_dir: str) -> str:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for n in self.list_notes():
            safe_title = re.sub(r"[^\w\- ]", "", n["title"])[:60] or n["id"]
            links = "\n".join(f"[[{lid}]]" for lid in n.get("links", []))
            tags = " ".join(f"#{t}" for t in n.get("tags", []))
            body = f"# {n['title']}\n\n{n['content']}\n\n{tags}\n\n## Links\n{links}\n"
            (out / f"{safe_title}.md").write_text(body)
        return str(out)


second_brain = SecondBrain()
