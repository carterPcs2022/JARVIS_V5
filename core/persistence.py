"""core/persistence.py — never give up on a hard problem after one try:
attempt, observe why it failed, try a different approach.

NOT wired into the default chat path — available via
POST /stark/persistence/solve. Escalates tier by attempt (reasoning ->
opus -> fable) rather than defaulting straight to paid tiers on every
attempt, since most retries succeed on the free tier once the model knows
the previous approach failed."""
from core.llm.router import think

MAX_ATTEMPTS = 3
_TIER_BY_ATTEMPT = ["reasoning", "opus", "fable"]

_FAILURE_SIGNALS = (
    "i cannot", "i'm unable", "i don't have access", "i can't determine",
    "insufficient information", "not possible", "cannot be determined",
)

_PERSISTENCE_TRIGGERS = (
    "no matter what", "keep trying", "don't give up", "figure it out",
    "make it work", "find a way", "at all costs", "however you can",
)


class PersistentSolver:

    def solve(self, problem: str, context: str = "", max_attempts: int = MAX_ATTEMPTS) -> dict:
        """Try multiple approaches until one works. Each failure informs
        the next attempt and escalates to a stronger tier."""
        attempts = []
        last_error = ""

        for i in range(max_attempts):
            attempt_prompt = f"Problem: {problem}\nContext: {context}\n"
            if last_error:
                attempt_prompt += (
                    f"\nPrevious approach failed: {last_error}\n"
                    f"Try a completely different approach.\n"
                )
            attempt_prompt += (
                f"\nAttempt {i+1} of {max_attempts}. Solve this. If you cannot, "
                f"explain specifically what's blocking you."
            )

            tier = _TIER_BY_ATTEMPT[min(i, len(_TIER_BY_ATTEMPT) - 1)]
            result = think(attempt_prompt, force_model=tier)

            failed = any(s in result.lower() for s in _FAILURE_SIGNALS)
            attempts.append({"attempt": i + 1, "tier": tier, "result": result, "failed": failed})

            if not failed:
                return {"solution": result, "attempts": i + 1, "success": True, "all_attempts": attempts}

            last_error = result[:200]
            print(f"[Persistence] Attempt {i+1} ({tier}) failed, trying again...")

        best = think(
            f"Problem: {problem}\n\nI tried {max_attempts} approaches. "
            f"Here's the best I can offer:\n"
            + "\n".join(f"Attempt {a['attempt']}: {a['result'][:200]}" for a in attempts) +
            "\n\nSynthesize the best partial answer possible.",
            force_model="fable",
        )

        return {
            "solution": best, "attempts": max_attempts, "success": False,
            "all_attempts": attempts, "note": "Best partial answer after max attempts",
        }

    def should_use_persistence(self, query: str) -> bool:
        return any(t in query.lower() for t in _PERSISTENCE_TRIGGERS)


persistent = PersistentSolver()
