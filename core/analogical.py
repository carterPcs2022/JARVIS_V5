"""core/analogical.py — JARVIS explains complex things through analogies,
the way Tony always reasoned through engineering problems."""


class AnalogicalReasoning:

    def explain_with_analogy(self, concept: str, user_background: str = "") -> str:
        """Generate a resonant analogy for any concept, tailored to the
        user's known interests."""
        from core.llm.router import think
        from core.memory import get_profile

        profile = get_profile()
        interests = ", ".join(profile.get("topics", []))

        return think(
            f"Explain '{concept}' using a powerful analogy that would "
            f"resonate with someone interested in: "
            f"{interests or user_background or 'technology and AI'}.\n"
            f"Make it visceral and immediately understandable. "
            f"One analogy only. Make it memorable.",
            force_model="standard",
        )

    def find_pattern(self, situation: str) -> str:
        """Find what this situation is analogous to elsewhere."""
        from core.llm.router import think
        return think(
            f"What is this situation analogous to? Find a pattern from "
            f"history, nature, or other domains that maps onto this "
            f"situation and what lessons that pattern suggests.\n\n"
            f"Situation: {situation}",
            force_model="reasoning",
        )

    def transfer_from_domain(self, problem: str, source_domain: str = "") -> dict:
        """Solve a problem using a solution transplanted from a completely
        different domain — one "fable"-tier call, real cost, meant for
        genuinely hard/creative problems, not routine questions."""
        from core.llm.router import think
        preferred = f"Preferred source: {source_domain}\n" if source_domain else ""
        return {
            "problem": problem,
            "transfer": think(
                f"Problem: {problem}\n\n"
                f"Find a solved problem from a COMPLETELY DIFFERENT domain with the "
                f"SAME underlying structure.\n{preferred}\n"
                f"1. The analogous problem from another domain\n"
                f"2. How the structures map onto each other\n"
                f"3. How that solution applies here\n"
                f"4. What breaks down in the analogy\n"
                f"5. The transferred solution\n\n"
                f"Be creative. The most useful analogies are surprising.",
                force_model="fable",
            ),
        }


analogical = AnalogicalReasoning()
