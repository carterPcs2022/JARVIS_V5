"""core/agents/deep_research.py — long-running autonomous research: JARVIS
spends real minutes (not hours by default — see MAX_RUNTIME) reading
sources, extracting insights, and synthesizing a report.

Genuinely expensive: up to 10 questions * up to 2 sources each * 1 "instant"
extraction call, plus 1 "research"-tier synthesis call. Only runs when a
caller explicitly starts it — never scheduled automatically."""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

REPORTS_DIR = BASE_DIR / "memory" / "research_reports"

# depth -> (max runtime seconds, max questions)
_DEPTH_BUDGETS = {
    "quick": (15 * 60, 4),
    "standard": (45 * 60, 7),
    "comprehensive": (2 * 60 * 60, 10),
}


class DeepResearchAgent:

    def __init__(self):
        self._active: dict = {}

    def research(self, topic: str, depth: str = "standard") -> dict:
        """Kicks off the research pipeline on a background thread. Returns
        immediately with a research_id; poll status via get_status()."""
        max_runtime, max_questions = _DEPTH_BUDGETS.get(depth, _DEPTH_BUDGETS["standard"])
        research_id = f"research_{int(time.time())}"

        self._active[research_id] = {
            "topic": topic, "depth": depth, "status": "running",
            "started": datetime.now().isoformat(), "progress": "Generating research questions...",
        }

        t = threading.Thread(
            target=self._run, args=(research_id, topic, max_runtime, max_questions),
            daemon=True, name=f"jarvis-research-{research_id}",
        )
        t.start()

        return {
            "research_id": research_id,
            "message": "Research initiated. I'll report back when complete.",
            "topic": topic,
            "estimated_minutes": round(max_runtime / 60),
        }

    def _run(self, research_id: str, topic: str, max_runtime: float, max_questions: int):
        from core.llm.router import think
        from core.tools.web import search

        start_time = time.time()
        print(f"[DeepResearch] Starting: {topic}")

        try:
            questions = self._generate_research_questions(topic, max_questions)
            sources, insights = [], []

            for i, question in enumerate(questions):
                if time.time() - start_time > max_runtime:
                    break
                self._active[research_id]["progress"] = f"Researching question {i+1}/{len(questions)}"
                print(f"[DeepResearch] Q{i+1}/{len(questions)}: {question[:50]}")

                results = search(question, max_results=3)
                for result in results[:2]:
                    snippet = result.get("snippet", "")
                    title = result.get("title", "")
                    if not snippet:
                        continue
                    insight = think(
                        f"Extract the most important insight from:\n"
                        f"Title: {title}\nContent: {snippet}\n\n"
                        f"Related to: {topic}\nOne sentence insight only.",
                        force_model="instant",
                    )
                    sources.append({"title": title, "url": result.get("url", ""), "insight": insight})
                    insights.append(insight)

                time.sleep(1)  # be respectful to search backends

            synthesis = think(
                f"You have researched: '{topic}'\n\n"
                f"Key insights gathered:\n" + "\n".join(f"• {i}" for i in insights[:15]) +
                f"\n\nWrite a comprehensive intelligence report:\n"
                f"1. Executive Summary (3 sentences)\n"
                f"2. Key Findings (bullet points)\n"
                f"3. Surprising Discoveries\n"
                f"4. Implications and Opportunities\n"
                f"5. Recommended Next Steps\n"
                f"6. Knowledge Gaps (what needs more research)\n\n"
                f"Be specific. Be insightful. Be useful.",
                force_model="research",
            )

            elapsed = round(time.time() - start_time, 0)
            report = {
                "id": research_id, "topic": topic, "synthesis": synthesis,
                "sources": sources, "insights": insights,
                "elapsed_s": elapsed, "ts": datetime.now().isoformat(),
            }

            try:
                from services.stark_docs import stark_docs
                doc = stark_docs.generate_report(f"RESEARCH REPORT: {topic.upper()}", synthesis, "CLASSIFIED")
                report["document"] = doc
            except Exception:
                pass

            self._save_report(report)
            self._active[research_id] = {
                "topic": topic, "status": "complete",
                "started": self._active[research_id]["started"],
                "finished": datetime.now().isoformat(), "elapsed_s": elapsed,
            }

            from core.event_bus import bus
            bus.system(
                f"Research complete, sir. '{topic[:50]}' — analyzed {len(sources)} sources "
                f"in {int(elapsed/60)} minutes. Report ready."
            )
        except Exception as e:
            self._active[research_id] = {
                "topic": topic, "status": "failed", "error": str(e),
                "started": self._active[research_id]["started"],
            }

    def _generate_research_questions(self, topic: str, n: int) -> list[str]:
        from core.llm.router import think
        result = think(
            f"Generate {n} research questions to fully understand: '{topic}'\n"
            f"Cover: basics, history, current state, controversies, future, key players, opportunities.\n"
            f"One question per line. No numbering.",
            force_model="standard",
        )
        return [q.strip() for q in result.strip().split("\n") if q.strip() and len(q) > 10][:n]

    def get_status(self, research_id: str) -> dict:
        return self._active.get(research_id, {"error": "Unknown research_id"})

    def active(self) -> list[dict]:
        return [{"research_id": rid, **info} for rid, info in self._active.items()]

    def list_reports(self) -> list[dict]:
        if not REPORTS_DIR.exists():
            return []
        reports = []
        for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                reports.append({"id": data.get("id"), "topic": data.get("topic"), "ts": data.get("ts")})
            except Exception:
                continue
        return reports

    def get_report(self, research_id: str) -> dict | None:
        path = REPORTS_DIR / f"{research_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_report(self, report: dict):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / f"{report['id']}.json").write_text(json.dumps(report, indent=2))


deep_research = DeepResearchAgent()
