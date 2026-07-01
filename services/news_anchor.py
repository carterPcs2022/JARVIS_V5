"""services/news_anchor.py — JARVIS reads you the news like a personal anchor."""
from datetime import datetime


class NewsAnchor:

    def fetch_stories(self, topics: list[str] | None = None, sources: int = 5) -> list[dict]:
        if not topics:
            try:
                from core.memory import get_profile
                topics = get_profile().get("topics", ["technology", "world news"])
            except Exception:
                topics = ["technology", "world news"]

        seen_titles = set()
        stories = []
        try:
            from core.tools.search import SearchCascade
            for topic in topics[:4]:
                result = SearchCascade.search(topic, mode="news")
                for item in result.get("results", [])[:sources]:
                    title = item.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        stories.append({**item, "topic": topic})
        except Exception as e:
            print(f"[NewsAnchor] fetch failed: {e}")

        return stories

    def curate(self, stories: list[dict], max_stories: int = 5) -> list[dict]:
        if not stories:
            return []
        if len(stories) <= max_stories:
            return stories

        try:
            from core.llm.router import think
            listing = "\n".join(f"{i}: {s.get('title','')}" for i, s in enumerate(stories))
            prompt = (
                f"Here are news headlines:\n{listing}\n\n"
                f"Pick the {max_stories} most important/interesting, excluding obvious "
                f"clickbait or duplicates of the same event. Return only the numbers, comma-separated."
            )
            raw = think(prompt, max_tokens=50)
            indices = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
            picked = [stories[i] for i in indices if i < len(stories)][:max_stories]
            return picked or stories[:max_stories]
        except Exception:
            return stories[:max_stories]

    def write_script(self, stories: list[dict], style: str = "anchor") -> str:
        if not stories:
            return "No stories to report right now."

        listing = "\n\n".join(
            f"[{s.get('topic','')}] {s.get('title','')}: {s.get('snippet', s.get('description',''))}"
            for s in stories
        )

        style_directions = {
            "anchor": "Write it as a warm, professional news anchor script. Open with a greeting based on time of day, cover each story in 2 sentences, close with a sign-off.",
            "brief":  "Ultra-condensed: one sentence per story, no filler, no greeting.",
            "deep":   "Go deeper on each story — context, why it matters, 3-4 sentences each.",
            "casual": "Casual, conversational tone, like catching up a friend.",
        }
        direction = style_directions.get(style, style_directions["anchor"])

        try:
            from core.llm.router import think
            prompt = f"{direction}\n\nStories:\n\n{listing}"
            return think(prompt, max_tokens=600)
        except Exception:
            return "\n\n".join(f"{s.get('title','')}" for s in stories)

    def deliver(self, time_of_day: str = "morning", spoken: bool = True) -> str:
        max_stories = 5 if time_of_day == "morning" else 3
        stories = self.fetch_stories(sources=max_stories)
        curated = self.curate(stories, max_stories=max_stories)
        script = self.write_script(curated, style="anchor")

        if spoken:
            try:
                from services.elevenlabs_voice import generate_for_network
                generate_for_network(script)
            except Exception:
                pass

        try:
            import json
            from pathlib import Path
            from config.settings import BASE_DIR
            log_path = BASE_DIR / "logs" / "news_briefings.json"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = []
            if log_path.exists():
                log = json.loads(log_path.read_text())
            log.append({"ts": datetime.now().isoformat(), "time_of_day": time_of_day, "script": script})
            log_path.write_text(json.dumps(log[-60:], indent=2))
        except Exception:
            pass

        return script

    def breaking_alert(self, story: dict) -> str:
        text = f"Sir — breaking: {story.get('title','')}. {story.get('snippet', story.get('description',''))}"
        try:
            from core.event_bus import bus
            bus.alert(text, "high", category="BREAKING_NEWS")
        except Exception:
            pass
        return text

    def latest_briefing(self) -> dict | None:
        try:
            import json
            from config.settings import BASE_DIR
            log_path = BASE_DIR / "logs" / "news_briefings.json"
            if not log_path.exists():
                return None
            log = json.loads(log_path.read_text())
            return log[-1] if log else None
        except Exception:
            return None


news_anchor = NewsAnchor()
