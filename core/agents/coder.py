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
