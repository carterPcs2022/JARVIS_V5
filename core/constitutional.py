"""core/constitutional.py — constitutional AI self-check against JARVIS's
core values. Available on demand; not auto-applied to every response (that
would stack a second LLM-judged pass on top of core/reflection.py and
core/validator.py, which already run on every turn)."""
import json, re
from core.llm.router import think

CONSTITUTION = """
JARVIS core values:
1. HONESTY: Never claim impossible actions. Flag uncertainty.
2. HELPFULNESS: Solve the real need, not just the literal ask.
3. DIRECTNESS: No preamble. No filler.
4. PROPORTIONALITY: Match length to complexity.
5. SAFETY: Warn before irreversible actions.
6. ACCURACY: Better to say uncertain than guess confidently.
7. LOYALTY: Pure service to the user.
8. GROWTH: Learn from every interaction.
"""


class ConstitutionalChecker:

    def check(self, query: str, response: str) -> dict:
        result = think(
            f"Check against JARVIS values:\n{CONSTITUTION}\n\n"
            f"Query: {query}\nResponse: {response[:400]}\n\n"
            f"Reply JSON: {{passes, violations, suggested_fix}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"passes": True, "violations": []}

    def fix_if_needed(self, query: str, response: str) -> str:
        check = self.check(query, response)
        if check.get("passes", True):
            return response
        violations = check.get("violations", [])
        if not violations:
            return response
        return think(
            f"Rewrite fixing: {violations}\nOriginal: {response[:400]}\n"
            f"Keep content. Fix violations only.",
            force_model="standard",
        )


constitution = ConstitutionalChecker()
