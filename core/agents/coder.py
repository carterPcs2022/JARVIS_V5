"""core/agents/coder.py — Code generation, review, and debugging agent."""
import ast
from core.llm.router import think

def generate(description: str, language: str = "python") -> dict:
    prompt = (f"Write {language} code that: {description}\n"
              f"Output ONLY the code, no explanation, no markdown fences.")
    code = think(prompt, temperature=0.2)
    code = code.strip().lstrip("```"+language).lstrip("```").rstrip("```").strip()
    valid, err = _syntax_check(code, language)
    return {"code": code, "language": language, "valid": valid, "error": err}

def review(code: str) -> dict:
    review_text = think(
        f"Review this code. List bugs, improvements, security issues:\n\n{code}"
    )
    return {"review": review_text, "code": code}

def debug(code: str, error: str) -> dict:
    fixed = think(
        f"Fix this {error} in the code:\n\n{code}\n\nOutput only the fixed code."
    )
    fixed = fixed.strip().lstrip("```").rstrip("```").strip()
    return {"fixed": fixed, "original_error": error}

def _syntax_check(code: str, language: str) -> tuple[bool, str]:
    if language == "python":
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, str(e)
    return True, ""


# ── Agent adapter (core/interfaces/agent.py) ───────────────────────────────────
# This module has three entry points (generate/review/debug), not one — run()
# picks between them via context["mode"], defaulting to generate() since
# that's the common case (context also carries generate()'s `language`,
# debug()'s `error`).

import asyncio
from core.interfaces.agent import Agent, AgentResult


class CoderAgent(Agent):
    name = "coder"

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        context = context or {}
        mode = context.get("mode", "generate")
        if mode == "review":
            result = await asyncio.to_thread(review, task)
        elif mode == "debug":
            result = await asyncio.to_thread(debug, task, context.get("error", ""))
        else:
            result = await asyncio.to_thread(generate, task, context.get("language", "python"))
        success = result.get("valid", True) and not result.get("error")
        return AgentResult(output=result, success=success, metadata={"mode": mode})
