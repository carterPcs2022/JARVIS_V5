"""services/house_party.py — "House Party Protocol": decompose a complex
task into parallel sub-tasks, run them concurrently, merge the results.
Real cost: up to 5 concurrent "instant"-tier calls + 1 "standard"
synthesis call — bounded and reasonable for an explicitly-invoked
capability."""
import concurrent.futures
import json
import re


class HousePartyProtocol:

    def activate(self, master_task: str) -> dict:
        from core.llm.router import think

        decompose = think(
            f"Decompose this task into 3-5 parallel sub-tasks that can run simultaneously:\n"
            f"{master_task}\n\nReturn as JSON array of strings.",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", decompose).strip()
            subtasks = json.loads(clean)
            if not isinstance(subtasks, list) or not subtasks:
                raise ValueError
        except Exception:
            subtasks = [master_task]

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self._run_subtask, task): task for task in subtasks[:5]}
            for future in concurrent.futures.as_completed(futures, timeout=30):
                task = futures[future]
                try:
                    results[task] = future.result()
                except Exception as e:
                    results[task] = f"Failed: {e}"

        merged = think(
            f"Synthesize these parallel results into one coherent response for: {master_task}\n\n"
            + "\n\n".join(f"[{t}]: {r}" for t, r in results.items()),
            force_model="standard",
        )

        return {
            "master_task": master_task, "subtasks": subtasks, "results": results,
            "synthesis": merged, "agents_used": len(results),
        }

    def _run_subtask(self, task: str) -> str:
        from core.llm.router import think
        return think(task, force_model="instant")


house_party = HousePartyProtocol()
