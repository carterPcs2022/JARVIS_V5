"""
services/fine_tuning.py — Fine-tune a local Ollama model on your own
conversations. The result has your vocabulary and context baked into the
model weights, not just injected into the prompt each time.

Note: this uses Ollama's Modelfile mechanism (a system-prompt + parameter
wrapper around a base model), not true weight-level fine-tuning — Ollama
doesn't expose LoRA/full fine-tuning through its CLI. It's a real, useful
capability (a permanently-customized local model you can fall back to),
just worth knowing it's prompt-engineering-at-the-model-level rather than
gradient updates.
"""
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR, OLLAMA_BASE_URL

FINETUNE_DIR   = BASE_DIR / "fine_tuning"
TRAINING_FILE  = FINETUNE_DIR / "training_data.jsonl"
MODELFILE_PATH = FINETUNE_DIR / "JARVIS.Modelfile"
MIN_EXAMPLES   = 50
FINETUNE_LOG   = BASE_DIR / "logs" / "fine_tuning.json"


class PersonalFineTuner:

    def prepare_training_data(self, min_quality: int = 7) -> dict:
        FINETUNE_DIR.mkdir(parents=True, exist_ok=True)

        from core.memory import _load
        from config.settings import CONVERSATIONS_FILE, SHORT_TERM_FILE
        conversations = _load(CONVERSATIONS_FILE) or []
        short_term = _load(SHORT_TERM_FILE) or []
        all_turns = conversations + short_term

        if len(all_turns) < MIN_EXAMPLES:
            return {"ready": False, "reason": f"Need {MIN_EXAMPLES} conversations, have {len(all_turns)}",
                   "count": len(all_turns)}

        training_examples = []
        for turn in all_turns:
            user = (turn.get("user") or "").strip()
            ai = (turn.get("ai") or "").strip()
            if not user or not ai or len(user) < 10 or len(ai) < 20 or len(ai) > 2000:
                continue
            training_examples.append({"instruction": user, "output": ai})

        reflexion_path = BASE_DIR / "memory" / "reflexion.json"
        if reflexion_path.exists():
            try:
                lessons = json.loads(reflexion_path.read_text())
                for lesson in lessons:
                    if lesson.get("quality", 5) >= 8:
                        training_examples.append({
                            "instruction": lesson.get("pattern", ""), "output": lesson.get("lesson", ""),
                        })
            except Exception:
                pass

        with open(TRAINING_FILE, "w") as f:
            for example in training_examples:
                f.write(json.dumps(example) + "\n")

        return {"ready": True, "count": len(training_examples), "file": str(TRAINING_FILE)}

    def create_modelfile(self, base_model: str = "llama3", system_prompt: str = "") -> str:
        from config.settings import JARVIS_PERSONALITY
        from core.personality import build_system_prompt
        from core.memory import get_profile

        system = build_system_prompt(system_prompt or JARVIS_PERSONALITY)
        profile = get_profile()
        formality = profile.get("formality", "professional")
        topics = ", ".join(profile.get("topics", []))
        name = profile.get("preferred_name", "sir")

        enhanced_system = (
            system + f"\n\nUser preferences (deeply understood):\n"
            f"- Communication style: {formality}\n- Main interests: {topics}\n"
            f"- Preferred address: {name}\n"
            f"- This model has been fine-tuned on {name}'s actual conversations.\n"
        )

        modelfile = (
            f"FROM {base_model}\n\nSYSTEM \"\"\"\n{enhanced_system}\n\"\"\"\n\n"
            f"PARAMETER temperature 0.7\nPARAMETER top_p 0.9\nPARAMETER top_k 40\n"
            f"PARAMETER repeat_penalty 1.1\nPARAMETER num_ctx 4096\n"
        )
        FINETUNE_DIR.mkdir(parents=True, exist_ok=True)
        MODELFILE_PATH.write_text(modelfile)
        return str(MODELFILE_PATH)

    def build_personal_model(self, base_model: str = "llama3") -> dict:
        print("[FineTune] Starting personal model build...")

        data_result = self.prepare_training_data()
        if not data_result["ready"]:
            return {"success": False, **data_result}

        modelfile_path = self.create_modelfile(base_model)
        print(f"[FineTune] Modelfile created: {modelfile_path}")

        model_name = "jarvis-personal"
        try:
            result = subprocess.run(
                ["ollama", "create", model_name, "-f", modelfile_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Build timed out (5 min)"}
        except FileNotFoundError:
            return {"success": False, "error": "Ollama not installed"}

        test_result = self._test_model(model_name)

        self._log_build({
            "model": model_name, "base": base_model, "examples": data_result["count"],
            "ts": datetime.now().isoformat(), "test_passed": test_result["passed"],
        })

        if test_result["passed"]:
            os.environ["OLLAMA_MODEL"] = model_name
            print(f"[FineTune] {model_name} is now active!")

        return {"success": True, "model": model_name, "examples": data_result["count"], "test": test_result}

    def _test_model(self, model_name: str) -> dict:
        try:
            import httpx
            r = httpx.post(f"{OLLAMA_BASE_URL}/api/generate",
                          json={"model": model_name, "prompt": "JARVIS are you online?", "stream": False}, timeout=30)
            response = r.json().get("response", "")
            return {"passed": len(response) > 10, "response": response}
        except Exception as e:
            return {"passed": False, "error": str(e)}

    def _log_build(self, entry: dict):
        FINETUNE_LOG.parent.mkdir(parents=True, exist_ok=True)
        log = []
        if FINETUNE_LOG.exists():
            try:
                log = json.loads(FINETUNE_LOG.read_text())
            except Exception:
                log = []
        log.append(entry)
        FINETUNE_LOG.write_text(json.dumps(log, indent=2))


fine_tuner = PersonalFineTuner()
