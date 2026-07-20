"""core/self_improvement.py — Level 3 of the self-programming sandbox.

Full cycle: analyze -> write -> test -> queue for approval. There is
deliberately no autonomous auto-deploy path, at any confidence or risk
level — every single change reaches a real file only via
approve_improvement(), which requires an explicit human action (voice
command or POST /stark/sandbox/approve/{id}). The sandbox test in
core/sandbox.py is a genuine functional smoke test (the candidate module
actually gets imported and executed) but it's still not a real OS-level
sandbox, and an LLM's self-reported confidence score is not an
independent correctness check — so nothing here treats either as a
substitute for a human looking at the diff before it ships.
"""
from __future__ import annotations
import json, secrets
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR

IMPROVEMENT_QUEUE = BASE_DIR / "memory" / "improvement_queue.json"


class SelfImprovementEngine:

    def run_improvement_cycle(self) -> dict:
        """1. Analyze code. 2. Write candidate improvements. 3. Test each
        in the sandbox. 4. Queue every one that passes for human approval
        — nothing is ever deployed from this method.

        Sets core.state's "current_task" at each step so a real cycle in
        progress is independently observable (GET /hud/status) rather
        than something only knowable by trusting whatever the chat
        response claims — this is exactly the gap that let tonight's
        streaming bug fabricate a fake cycle report with nothing to
        contradict it. Always cleared in `finally`, including on an
        unhandled exception, so a crash mid-cycle can't leave a stale
        "still running" status behind forever."""
        from core.self_analysis import self_analysis
        from core.sandbox import jarvis_sandbox
        from core.state import state

        results = {
            "analyzed": 0, "written": 0, "tested": 0,
            "queued": 0, "failed": 0, "improvements": [],
        }

        try:
            state.set("current_task", "self_improvement_cycle: analyzing core files")
            analysis = self_analysis.analyze_self()
            improvements = analysis.get("improvements", [])
            results["analyzed"] = len(improvements)

            if not improvements:
                return {**results, "message": "No improvements identified."}

            for improvement in improvements[:3]:  # Max 3 per cycle
                filepath = improvement.get("file", "")
                if not filepath or not (BASE_DIR / filepath).exists():
                    continue

                try:
                    state.set("current_task", f"self_improvement_cycle: writing candidate for {filepath}")
                    written = jarvis_sandbox.write_improvement(filepath, improvement)
                    new_code = written.get("new_code", "")
                    if not new_code:
                        results["failed"] += 1
                        continue
                    results["written"] += 1

                    state.set("current_task", f"self_improvement_cycle: sandbox-testing {filepath}")
                    test_result = jarvis_sandbox.run_in_sandbox(new_code, filepath)
                    if not test_result.get("success"):
                        results["failed"] += 1
                        improvement["test_failure"] = test_result.get("error") or test_result.get("stderr", "")
                        continue
                    results["tested"] += 1

                    self._queue_for_approval(filepath, new_code, improvement)
                    results["queued"] += 1
                    results["improvements"].append(improvement)

                except Exception as e:
                    results["failed"] += 1
                    print(f"[SelfImprovement] Error: {e}")

            results["message"] = self._generate_summary(results)
            return results
        finally:
            state.set("current_task", None)

    def approve_improvement(self, improvement_id: str) -> dict:
        """Human approves a queued improvement — the only path that ever
        calls jarvis_sandbox.deploy(). Deploys and hot-reloads locally
        ONLY — does not commit or push to GitHub. That used to happen
        automatically in this same call; it's now a deliberate, separate
        persist_deployment() action (see below) so approving a change
        that turns out to be wrong in production never has to be undone
        on the shared repo — it just wasn't pushed there yet."""
        from core.sandbox import jarvis_sandbox

        queue = self._load_queue()
        item = next((i for i in queue if i.get("id") == improvement_id), None)
        if not item:
            return {"success": False, "error": "Improvement not found"}

        deploy = jarvis_sandbox.deploy(item["filepath"], item["new_code"], item["improvement"])

        if deploy.get("success"):
            queue = [i for i in queue if i.get("id") != improvement_id]
            self._save_queue(queue)
            self._announce_deployment(item["filepath"], item["improvement"], deploy.get("hot_reloaded", False))

        return deploy

    def persist_deployment(self, deployment_id: str) -> dict:
        """Second, explicit step after approve_improvement(): commit and
        push an already-deployed change to GitHub so it survives Render's
        ephemeral filesystem across a redeploy. Until this is called, the
        change is live in the running process but exists nowhere else —
        a redeploy (or a rollback) would erase it with no trace on the
        shared repo, which is the point: approval alone commits to
        nothing beyond 'try this for real right now.'"""
        from core.sandbox import jarvis_sandbox

        deployment = jarvis_sandbox.get_deployment(deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.get("persisted"):
            return {"success": False, "error": "Already persisted", "deployment_id": deployment_id}

        self._commit_improvement_to_github(deployment["filepath"], deployment["improvement"])
        jarvis_sandbox.mark_persisted(deployment_id)
        return {"success": True, "filepath": deployment["filepath"], "deployment_id": deployment_id}

    def _commit_improvement_to_github(self, filepath: str, improvement: dict):
        """Persist an already human-approved, already-deployed change past
        the next Render redeploy. Only ever called from
        persist_deployment() — a separate, explicit action from approval
        itself (see approve_improvement()'s docstring for why)."""
        from utils.git_ops import commit_and_push
        desc = improvement.get("description", "optimization")[:50]
        commit_and_push(
            [filepath],
            f"auto(self-improve): {desc} in {filepath.split('/')[-1]}",
            log_prefix="[SelfImprovement]",
        )

    def reject_improvement(self, improvement_id: str) -> dict:
        queue = self._load_queue()
        queue = [i for i in queue if i.get("id") != improvement_id]
        self._save_queue(queue)
        return {"success": True, "message": "Improvement rejected"}

    def get_pending_approvals(self) -> list:
        return self._load_queue()

    def _queue_for_approval(self, filepath: str, new_code: str, improvement: dict):
        queue = self._load_queue()
        queue.append({
            "id":          secrets.token_hex(8),
            "filepath":    filepath,
            "new_code":    new_code,
            "improvement": improvement,
            "queued_at":   datetime.now().isoformat(),
        })
        self._save_queue(queue)

        from core.event_bus import bus
        bus.system(
            f"Improvement ready for review: {improvement.get('description', '')[:80]} "
            f"in {filepath}. Confidence: {improvement.get('confidence', 0)}%. "
            f"Awaiting your approval, sir."
        )

    def _announce_deployment(self, filepath: str, improvement: dict, hot_reloaded: bool):
        from services.voice import speak
        from core.event_bus import bus

        # hot_reloaded reflects whether core.protocols.extremis actually
        # reloaded the changed module in place (core/sandbox.py's deploy())
        # — "running the updated code now" used to be claimed unconditionally,
        # which was false whenever the reload failed or the target was
        # server/api.py itself (Extremis can't hot-reload that; it needs a
        # real restart).
        tail = "Running the updated code now." if hot_reloaded else (
            "It's on disk and will take effect on the next restart, sir "
            "— hot-reload didn't take for this one."
        )
        msg = (
            f"Self-improvement deployed, sir. "
            f"{improvement.get('description', 'Optimization')[:60]} "
            f"in {filepath.split('/')[-1]}. {tail}"
        )
        try:
            speak(msg)
        except Exception:
            pass
        bus.system(msg)

    def _generate_summary(self, results: dict) -> str:
        from core.llm.router import think
        try:
            return think(
                f"Generate a brief JARVIS-style summary of this self-improvement cycle:\n"
                f"Analyzed: {results['analyzed']} improvements found\n"
                f"Written: {results['written']} rewrites\n"
                f"Tested: {results['tested']} passed the sandbox\n"
                f"Queued: {results['queued']} awaiting your approval\n"
                f"Failed: {results['failed']}\n\n"
                f"One sentence. JARVIS voice. No fluff.",
                force_model="instant",
            )
        except Exception:
            return (f"Analyzed {results['analyzed']}, tested {results['tested']}, "
                    f"queued {results['queued']} for your approval.")

    def _load_queue(self) -> list:
        if IMPROVEMENT_QUEUE.exists():
            try:
                return json.loads(IMPROVEMENT_QUEUE.read_text())
            except Exception:
                return []
        return []

    def _save_queue(self, queue: list):
        IMPROVEMENT_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        IMPROVEMENT_QUEUE.write_text(json.dumps(queue, indent=2))


self_improvement = SelfImprovementEngine()
