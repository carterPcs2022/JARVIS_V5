"""core/ooda.py — OODA loop (Observe/Orient/Decide/Act), the military's
core rapid-decision framework. Thin wrapper over core.llm.router.think();
the value is the four-phase structure, not new computation."""
import time

from core.llm.router import think


class OODAEngine:

    def run(self, situation: str, context: str = "") -> dict:
        """Full four-call OODA loop. Each phase feeds the next."""
        start = time.time()

        observe = think(
            f"OBSERVE phase — gather all facts:\n"
            f"Situation: {situation}\n"
            f"{f'Context: {context}' if context else ''}\n\n"
            f"What is actually happening right now? What data do we have?\n"
            f"No interpretation yet. Facts only.",
            force_model="instant",
        )

        orient = think(
            f"ORIENT phase — interpret the facts:\n"
            f"Situation: {situation}\n"
            f"Observations: {observe[:300]}\n\n"
            f"What does this mean? What patterns apply? What are the implications?",
            force_model="standard",
        )

        decide = think(
            f"DECIDE phase — choose action:\n"
            f"Situation: {situation}\n"
            f"Orientation: {orient[:300]}\n\n"
            f"What are the options? Which is best and why?\n"
            f"Decision: [clear single action]",
            force_model="standard",
        )

        act = think(
            f"ACT phase — execute and prepare:\n"
            f"Decision: {decide[:200]}\n\n"
            f"Specific next action to take NOW.\n"
            f"What to watch for in the next OBSERVE cycle. One sentence each.",
            force_model="instant",
        )

        return {
            "situation": situation, "observe": observe, "orient": orient,
            "decide": decide, "act": act,
            "loop_ms": round((time.time() - start) * 1000),
            "method": "OODA",
        }

    def rapid_ooda(self, situation: str) -> str:
        """Single-call OODA for time-critical situations."""
        return think(
            f"OODA rapid analysis:\n{situation}\n\n"
            f"OBSERVE: [facts]\nORIENT: [meaning]\nDECIDE: [action]\nACT: [now]\n\n"
            f"Four lines. Fast.",
            force_model="instant",
        )


ooda = OODAEngine()
