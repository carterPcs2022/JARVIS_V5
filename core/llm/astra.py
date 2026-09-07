"""core/llm/astra.py — optional GPT-6 Astra Responses API provider.

Astra is intentionally an optional, explicit high-end provider. This adapter
only exposes text generation through the common LLMProvider interface for now;
computer-use/tool execution remains behind JARVIS's own authorization,
verification, and executor layers rather than bypassing them.
"""
from __future__ import annotations

import httpx
from typing import Any

from core.interfaces.llm_provider import LLMProvider, GenerateRequest, ModelResponse


API_URL = "https://api.openai.com/v1/responses"
TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0)


def _config() -> tuple[str, str]:
    # Read lazily so local/test imports never require an OpenAI key and so
    # environment changes made before the first call are respected.
    import os
    return (
        os.getenv("OPENAI_API_KEY", "").strip(),
        os.getenv("ASTRA_MODEL", "gpt-6-astra").strip() or "gpt-6-astra",
    )


def _text_from_response(data: dict[str, Any]) -> str:
    """Extract visible assistant text from a Responses API JSON payload."""
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


class AstraProvider(LLMProvider):
    name = "astra"

    def is_available(self) -> bool:
        key, _ = _config()
        return bool(key)

    async def generate(self, request: GenerateRequest) -> ModelResponse:
        api_key, configured_model = _config()
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        # Responses accepts role-based input items, including a separate
        # system/developer message. Preserve the existing provider-neutral
        # message shape rather than flattening conversation state.
        input_items = list(request.messages)
        if request.system:
            input_items = [{"role": "system", "content": request.system}] + input_items

        effort = (request.effort or "high").lower()
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            effort = "high"

        payload: dict[str, Any] = {
            "model": request.model or configured_model,
            "input": input_items,
            "max_output_tokens": max(1, request.max_tokens),
            "reasoning": {"effort": effort},
        }

        # GPT-6 Astra does not accept the legacy temperature control, so the
        # common GenerateRequest temperature is intentionally not forwarded.
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = _text_from_response(data)
        if not content:
            raise RuntimeError("GPT-6 Astra returned no visible text output")

        usage_raw = data.get("usage") or {}
        usage = {
            "input": usage_raw.get("input_tokens", 0),
            "output": usage_raw.get("output_tokens", 0),
            "total": usage_raw.get("total_tokens", 0),
        }
        return ModelResponse(
            content=content,
            model=data.get("model", request.model or configured_model),
            provider=self.name,
            usage=usage,
            raw=data,
        )
