"""
services/image_gen.py — ImageGeneration: DALL-E 3, Stability AI, local SD, and utilities.
"""
import base64
import os
from pathlib import Path

try:
    import openai as _openai
except ImportError:
    _openai = None

try:
    import requests as _requests
except ImportError:
    _requests = None

from core.llm.router import think


class ImageGeneration:

    # ------------------------------------------------------------------ #
    # Prompt enhancement                                                   #
    # ------------------------------------------------------------------ #

    def _enhance_prompt(self, prompt: str, style: str) -> str:
        style_suffixes = {
            "realistic": "photorealistic, 8k, detailed",
            "anime":     "anime art style, Studio Ghibli",
            "painting":  "oil painting, masterpiece, artistic",
        }
        suffix = style_suffixes.get(style, "")
        return f"{prompt}, {suffix}" if suffix else prompt

    # ------------------------------------------------------------------ #
    # Core generate                                                        #
    # ------------------------------------------------------------------ #

    def generate(self, prompt: str, style: str = "realistic", size: str = "1024x1024") -> dict:
        """Try DALL-E 3 → Stability AI → local SD. Return image URL or base64."""
        enhanced_prompt = self._enhance_prompt(prompt, style)

        # 1. OpenAI DALL-E 3
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key and _openai is not None:
            try:
                client = _openai.OpenAI(api_key=openai_key)
                resp = client.images.generate(
                    model="dall-e-3",
                    prompt=enhanced_prompt,
                    size=size,
                    n=1,
                )
                url = resp.data[0].url
                return {
                    "url": url,
                    "prompt": prompt,
                    "style": style,
                    "provider": "dall-e-3",
                }
            except Exception as e:
                pass  # fall through to next provider

        # 2. Stability AI
        stability_key = os.environ.get("STABILITY_API_KEY")
        if stability_key and _requests is not None:
            try:
                resp = _requests.post(
                    "https://api.stability.ai/v1/generation/"
                    "stable-diffusion-xl-1024-v1-0/text-to-image",
                    headers={
                        "Authorization": f"Bearer {stability_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={
                        "text_prompts": [{"text": enhanced_prompt}],
                        "cfg_scale": 7,
                        "width": int(size.split("x")[0]),
                        "height": int(size.split("x")[1]),
                        "steps": 30,
                        "samples": 1,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                image_data = resp.json()["artifacts"][0]["base64"]
                return {
                    "image_data": image_data,
                    "prompt": prompt,
                    "style": style,
                    "provider": "stability-ai",
                }
            except Exception:
                pass

        # 3. Local Stable Diffusion (Automatic1111)
        sd_url = os.environ.get("SD_LOCAL_URL")
        if sd_url and _requests is not None:
            try:
                w, h = size.split("x")
                resp = _requests.post(
                    f"{sd_url.rstrip('/')}/sdapi/v1/txt2img",
                    json={
                        "prompt": enhanced_prompt,
                        "steps": 20,
                        "width": int(w),
                        "height": int(h),
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                image_b64 = resp.json()["images"][0]
                return {
                    "image_data": image_b64,
                    "prompt": prompt,
                    "style": style,
                    "provider": "stable-diffusion-local",
                }
            except Exception:
                pass

        # 4. Nothing configured
        return {
            "error": "no_image_gen_configured",
            "prompt": prompt,
            "message": (
                "Configure OPENAI_API_KEY, STABILITY_API_KEY, or run local "
                "Stable Diffusion and set SD_LOCAL_URL"
            ),
        }

    # ------------------------------------------------------------------ #
    # Utilities                                                            #
    # ------------------------------------------------------------------ #

    def generate_hud_background(self) -> dict:
        """Generate an Iron Man HUD-style background for the JARVIS interface."""
        return self.generate(
            "Iron Man HUD interface, dark blue holographic displays, arc reactor glow, "
            "technical readouts, JARVIS interface, cinematic, sci-fi",
            style="realistic",
        )

    def edit_image(self, image_path: str, instruction: str) -> dict:
        """Edit an existing image using OpenAI images.edit."""
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key or _openai is None:
            return {"error": "requires_openai", "message": "Set OPENAI_API_KEY to use image editing."}

        try:
            client = _openai.OpenAI(api_key=openai_key)
            with open(image_path, "rb") as img_file:
                resp = client.images.edit(
                    image=img_file,
                    prompt=instruction,
                    n=1,
                    size="1024x1024",
                )
            return {
                "url": resp.data[0].url,
                "instruction": instruction,
                "provider": "dall-e-edit",
            }
        except Exception as e:
            return {"error": str(e), "requires_openai": True}

    def describe_and_generate(self, concept: str) -> dict:
        """LLM expands a concept into a detailed prompt, then generates the image."""
        detailed_prompt = think(
            f"Create a detailed image generation prompt for: {concept}. "
            "Be specific about style, lighting, composition, mood. Return only the prompt."
        )
        return self.generate(detailed_prompt)


# Module-level singleton
image_gen = ImageGeneration()
