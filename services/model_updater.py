"""services/model_updater.py — capability-aware live model selection.

The old updater only compared numeric versions inside the same model-family
string. That was too narrow for provider catalogs: it could miss a successor
when naming changed (qwen3-32b -> qwen3.6-27b), and it could announce a newer
model without proving that it was actually a better fit for JARVIS.

This updater now:
  * discovers the live provider catalog;
  * scores known candidates by tier, capabilities, speed, context, maturity,
    tool behavior and recency instead of version numbers alone;
  * treats preview status as a real stability cost rather than blindly
    preferring the newest ID;
  * only auto-upgrades when a candidate materially beats the current model;
  * records the decision and its reasons;
  * never auto-selects an unknown model profile merely because its name looks
    newer;
  * still fails safely when a configured model disappears.

The goal is "newest *good* model for this JARVIS tier", not "largest number in
an ID".
"""
from __future__ import annotations

import json
import re
import time
import httpx
from pathlib import Path
from datetime import datetime, timezone
from config.settings import BASE_DIR

MODEL_REGISTRY_FILE = BASE_DIR / "memory" / "model_registry.json"
UPDATE_LOG_FILE = BASE_DIR / "logs" / "model_updates.json"
SETTINGS_FILE = BASE_DIR / "config" / "settings.py"
ROUTER_FILE = BASE_DIR / "core" / "llm" / "router.py"

ANTHROPIC_SETTING_NAMES = {
    "sonnet": "ANTHROPIC_MODEL_SONNET",
    "opus": "ANTHROPIC_MODEL_OPUS",
    "fable": "ANTHROPIC_MODEL_FABLE",
}

# Provider metadata is deliberately small and auditable.  The live API tells
# us which IDs exist; this table tells JARVIS what those known IDs are good at.
# Unknown models are NOT auto-selected until they have an explicit profile.
GROQ_MODEL_PROFILES: dict[str, dict] = {
    "openai/gpt-oss-20b": {
        "tiers": {"instant", "standard", "coder"}, "production": True,
        "reasoning": True, "tools": True, "parallel_tools": False,
        "vision": False, "json": True, "built_in_tools": True,
        "speed": 1000, "context": 131072, "quality": 78,
    },
    "openai/gpt-oss-120b": {
        "tiers": {"standard", "reasoning", "research", "coder"}, "production": True,
        "reasoning": True, "tools": True, "parallel_tools": False,
        "vision": False, "json": True, "built_in_tools": True,
        "speed": 500, "context": 131072, "quality": 93,
    },
    "qwen/qwen3.6-27b": {
        "tiers": {"standard", "reasoning", "research", "coder"}, "production": False,
        "reasoning": True, "tools": True, "parallel_tools": True,
        "vision": True, "json": True, "built_in_tools": False,
        "speed": 500, "context": 131072, "quality": 94,
    },
    "qwen/qwen3.8-27b": {
        "tiers": {"standard", "reasoning", "research", "coder"}, "production": False,
        "reasoning": True, "tools": True, "parallel_tools": False,
        "vision": True, "json": True, "built_in_tools": False,
        "speed": 450, "context": 131042, "quality": 97,
    },
    "minimaxai/minimax-m2.7": {
        "tiers": {"standard", "reasoning", "research", "coder"}, "production": False,
        "reasoning": True, "tools": True, "parallel_tools": True,
        "vision": False, "json": True, "built_in_tools": False,
        "speed": 260, "context": 196608, "quality": 95,
    },
    "groq/compound": {
        "tiers": {"research"}, "production": True,
        "reasoning": True, "tools": True, "parallel_tools": False,
        "vision": False, "json": True, "built_in_tools": True,
        "speed": 450, "context": 131072, "quality": 96,
    },
    "groq/compound-mini": {
        "tiers": {"standard", "research"}, "production": True,
        "reasoning": True, "tools": True, "parallel_tools": False,
        "vision": False, "json": True, "built_in_tools": True,
        "speed": 450, "context": 131072, "quality": 88,
    },
}

# Minimum improvement required before an automatic change.  This prevents a
# one-point score fluctuation from rewriting the repo every week.
_MIN_SCORE_GAIN = 7


def _version_tuple(model_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model_id))


def _is_newer(candidate: str, current: str) -> bool:
    cand_v, cur_v = _version_tuple(candidate), _version_tuple(current)
    for c, k in zip(cand_v, cur_v):
        if c > k:
            return True
        if c < k:
            return False
    return len(cand_v) > len(cur_v)


def _base_family(model_id: str) -> str:
    """Best-effort family key used only for reporting/fallbacks.

    This is intentionally NOT used as the upgrade gate anymore.  Different
    generations are allowed to compete when their capability profiles say
    they serve the same JARVIS tier.
    """
    model_id = model_id.lower()

    def strip_version(m: re.Match) -> str:
        next_char = model_id[m.end():m.end() + 1]
        return m.group(0) if next_char.isalpha() else ""

    return re.sub(r"\d+", strip_version, model_id)


def _safe_ratio(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


class ModelUpdater:

    def __init__(self):
        self.registry = self._load_registry()

    # ── Live catalogs ───────────────────────────────────────────────────

    def _fetch_groq_models(self) -> dict[str, dict]:
        """Return the live Groq catalog keyed by model ID.

        Keep the metadata returned by Groq (created/active/context/etc.) so
        selection can use more than the spelling of an ID.
        """
        from config.settings import GROQ_API_KEY
        if not GROQ_API_KEY:
            return {}
        try:
            r = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=10,
            )
            r.raise_for_status()
            return {
                m["id"]: m for m in r.json().get("data", [])
                if m.get("id") and m.get("active", True)
            }
        except Exception as e:
            print(f"[ModelUpdater] Groq fetch failed: {e}")
            return {}

    def _fetch_anthropic_models(self) -> dict[str, dict]:
        from config.settings import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            return {}
        try:
            r = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10,
            )
            r.raise_for_status()
            return {
                m["id"]: m for m in r.json().get("data", [])
                if m.get("id")
            }
        except Exception as e:
            print(f"[ModelUpdater] Anthropic fetch failed: {e}")
            return {}

    # ── Capability scoring ──────────────────────────────────────────────

    def _score_groq(self, tier: str, model_id: str, metadata: dict) -> tuple[float, list[str]] | None:
        profile = GROQ_MODEL_PROFILES.get(model_id)
        if not profile or tier not in profile["tiers"]:
            return None

        score = float(profile["quality"])
        reasons: list[str] = []

        # Tier-specific capabilities matter more than raw parameter count.
        if tier == "instant":
            speed_score = _safe_ratio(profile["speed"], 250, 1000) * 18
            score += speed_score
            reasons.append(f"{profile['speed']} tok/s speed profile")
        elif tier in {"reasoning", "research"}:
            if profile["reasoning"]:
                score += 8
                reasons.append("reasoning capable")
            if profile["tools"]:
                score += 5
                reasons.append("tool use")
            if tier == "research" and profile["context"] >= 131000:
                score += 4
                reasons.append("large context")
        elif tier == "coder":
            if profile["reasoning"]:
                score += 6
                reasons.append("reasoning for code tasks")
            if profile["tools"]:
                score += 6
                reasons.append("tool use")
            if profile["json"]:
                score += 3
                reasons.append("structured JSON")

        # JARVIS uses tools heavily, so parallel tool calls are a real
        # advantage.  This is why Qwen 3.8 is not allowed to win simply by
        # having a larger version number.
        if profile["parallel_tools"] and tier in {"standard", "reasoning", "research", "coder"}:
            score += 7
            reasons.append("parallel tool calls")
        elif tier in {"reasoning", "research", "coder"}:
            score -= 2
            reasons.append("no parallel tool calls")

        if profile["vision"] and tier in {"standard", "research", "reasoning"}:
            score += 4
            reasons.append("vision capable")

        # Production status is a deliberate stability advantage.  Preview
        # models can be discontinued at short notice, so novelty is not free.
        if profile["production"]:
            score += 10
            reasons.append("production model")
        else:
            score -= 10
            reasons.append("preview model penalty")

        # Prefer larger context where it is materially different.
        live_context = int(metadata.get("context_window") or profile["context"] or 0)
        if live_context >= 131000:
            score += 2

        # Recency is a tie-breaker, not the primary criterion.
        created = metadata.get("created")
        if isinstance(created, (int, float)):
            age_days = max(0.0, (time.time() - created) / 86400)
            score += max(0.0, 3.0 - min(age_days / 120.0, 3.0))

        return score, reasons

    def _best_groq_for_tier(self, tier: str, live_models: dict[str, dict], current_id: str) -> dict | None:
        candidates = []
        for model_id, metadata in live_models.items():
            scored = self._score_groq(tier, model_id, metadata)
            if scored is None:
                continue
            score, reasons = scored
            candidates.append({
                "id": model_id,
                "score": round(score, 2),
                "reasons": reasons,
                "metadata": metadata,
            })

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x["score"], _version_tuple(x["id"])), reverse=True)
        winner = candidates[0]
        current = next((c for c in candidates if c["id"] == current_id), None)
        winner["current_score"] = current["score"] if current else None
        winner["candidate_count"] = len(candidates)
        winner["runner_up"] = candidates[1]["id"] if len(candidates) > 1 else None
        return winner

    # ── Detection ───────────────────────────────────────────────────────

    def _check_groq(self, registry: dict, live_models: dict[str, dict]) -> list[dict]:
        updates = []
        for tier, cfg in registry.items():
            current_id = cfg.get("id", "")
            if not current_id:
                continue

            if current_id not in live_models:
                # A vanished model is an emergency/deprecation signal.  Pick
                # the safest profiled replacement rather than leaving JARVIS
                # permanently broken, but record that this was forced by
                # disappearance rather than a normal upgrade.
                winner = self._best_groq_for_tier(tier, live_models, current_id)
                updates.append({
                    "provider": "groq", "tier": tier,
                    "new_model": winner["id"] if winner else None,
                    "old_model": current_id,
                    "type": "deprecated",
                    "reason": "configured model is absent from the live catalog",
                    "selection": winner,
                })
                continue

            winner = self._best_groq_for_tier(tier, live_models, current_id)
            if not winner or winner["id"] == current_id:
                continue

            current_score = winner["current_score"]
            # If the current model has no profile we do not auto-replace it
            # unless it is actually gone. Unknown models require review.
            if current_score is None:
                continue

            gain = winner["score"] - current_score
            if gain >= _MIN_SCORE_GAIN:
                updates.append({
                    "provider": "groq", "tier": tier,
                    "new_model": winner["id"], "old_model": current_id,
                    "type": "upgrade", "score_gain": round(gain, 2),
                    "reason": "capability score materially exceeds current model",
                    "selection": winner,
                })
        return updates

    def _check_anthropic(self, registry: dict, live_models: dict[str, dict]) -> list[dict]:
        """Anthropic gets conservative family/version handling for now.

        We don't guess cross-family Anthropic replacements.  Their model IDs
        carry enough structured version information for safe same-family
        upgrades, while unknown families remain human-review only.
        """
        updates = []
        for tier, cfg in registry.items():
            current_id = cfg.get("id", "")
            if not current_id:
                continue
            if current_id not in live_models:
                updates.append({
                    "provider": "anthropic", "tier": tier,
                    "new_model": None, "old_model": current_id,
                    "type": "deprecated",
                    "reason": "configured model is absent from the live catalog",
                })
                continue

            family = _base_family(current_id)
            newer = [
                model_id for model_id in live_models
                if model_id != current_id
                and _base_family(model_id) == family
                and _is_newer(model_id, current_id)
            ]
            if newer:
                best = max(newer, key=_version_tuple)
                updates.append({
                    "provider": "anthropic", "tier": tier,
                    "new_model": best, "old_model": current_id,
                    "type": "upgrade",
                    "reason": "newer live release in the same Anthropic model family",
                })
        return updates

    def check_for_updates(self) -> dict:
        print("[ModelUpdater] Checking live model catalogs...")
        updates = []

        groq_models = self._fetch_groq_models()
        if groq_models:
            from core.llm.router import MODEL_REGISTRY
            updates += self._check_groq(MODEL_REGISTRY, groq_models)

        anthropic_models = self._fetch_anthropic_models()
        if anthropic_models:
            from core.llm.router import ANTHROPIC_REGISTRY
            updates += self._check_anthropic(ANTHROPIC_REGISTRY, anthropic_models)

        self.registry["last_checked"] = datetime.now(timezone.utc).isoformat()
        self.registry["last_selection"] = [
            {
                "provider": u["provider"], "tier": u["tier"],
                "old_model": u["old_model"], "new_model": u["new_model"],
                "score_gain": u.get("score_gain"), "reason": u.get("reason"),
                "candidate_count": (u.get("selection") or {}).get("candidate_count"),
                "runner_up": (u.get("selection") or {}).get("runner_up"),
            }
            for u in updates
        ]
        self._save_registry()

        return {
            "updates_available": len([u for u in updates if u["type"] == "upgrade"]),
            "updates": [u for u in updates if u["type"] == "upgrade"],
            "deprecated": [u for u in updates if u["type"] == "deprecated"],
            "checked_at": self.registry["last_checked"],
        }

    # ── Apply ────────────────────────────────────────────────────────────

    def apply_updates(self, updates: list) -> dict:
        if not updates:
            return {"applied": 0, "updates": [], "message": "No updates to apply"}

        applied = []
        for update in updates:
            provider, tier = update["provider"], update["tier"]
            new_model, old_model = update["new_model"], update["old_model"]
            if not new_model:
                print(f"[ModelUpdater] No safe replacement for {provider}/{tier}; review required.")
                continue
            try:
                self._update_in_memory(provider, tier, new_model)
                if provider == "anthropic":
                    self._patch_settings_file(tier, new_model)
                else:
                    self._patch_router_file(tier, new_model)
                self._log_update(update)
                applied.append(update)
                print(
                    f"[ModelUpdater] {provider} {tier}: {old_model} -> {new_model} "
                    f"({update.get('reason', 'selected')})"
                )
            except Exception as e:
                print(f"[ModelUpdater] Failed to apply {provider}/{tier}: {e}")

        if applied:
            self._announce_updates(applied)
            self._commit_to_github(applied)

        return {
            "applied": len(applied), "updates": applied,
            "message": f"Applied {len(applied)} model update(s)",
        }

    def _commit_to_github(self, updates: list):
        """Persist source changes past the next Render redeploy."""
        from utils.git_ops import commit_and_push
        names = "; ".join(f"{u['tier']} to {u['new_model']}" for u in updates[:3])
        result = commit_and_push(
            ["config/settings.py", "core/llm/router.py"],
            f"auto(models): update {names}",
            log_prefix="[ModelUpdater]",
        )
        if not result.get("pushed"):
            print(f"[ModelUpdater] WARNING: model change was not pushed: {result}")

    def _update_in_memory(self, provider: str, tier: str, new_model: str):
        from core.llm import router
        registry = router.ANTHROPIC_REGISTRY if provider == "anthropic" else router.MODEL_REGISTRY
        if tier in registry:
            registry[tier]["id"] = new_model

    def _patch_settings_file(self, tier: str, new_model: str):
        setting_name = ANTHROPIC_SETTING_NAMES.get(tier)
        if not setting_name or not SETTINGS_FILE.exists():
            return
        content = SETTINGS_FILE.read_text()
        pattern = rf'{setting_name}\s*=\s*"[^"]*"'
        updated = re.sub(pattern, f'{setting_name} = "{new_model}"', content, count=1)
        if updated != content:
            SETTINGS_FILE.write_text(updated)
            print(f"[ModelUpdater] Patched settings.py: {setting_name} = {new_model}")

    def _patch_router_file(self, tier: str, new_model: str):
        if not ROUTER_FILE.exists():
            return
        content = ROUTER_FILE.read_text()
        block = re.search(rf'"{tier}":\s*\{{(.*?)\}}', content, re.DOTALL)
        if not block:
            return
        new_inner = re.sub(
            r'"id":\s*"[^"]*"',
            f'"id": "{new_model}"',
            block.group(1), count=1,
        )
        if new_inner == block.group(1):
            return
        updated = content[:block.start(1)] + new_inner + content[block.end(1):]
        ROUTER_FILE.write_text(updated)
        print(f"[ModelUpdater] Patched router.py: {tier} id = {new_model}")

    # ── Persistence / reporting ─────────────────────────────────────────

    def _announce_updates(self, updates: list):
        names = ", ".join(f"{u['tier']} to {u['new_model']}" for u in updates[:3])
        message = f"Model update{'s' if len(updates) > 1 else ''} applied, sir. {names}."
        try:
            from services.voice import speak
            speak(message)
        except Exception:
            pass
        try:
            from core.event_bus import bus
            bus.system(message)
            for u in updates:
                bus.alert(
                    f"Model upgraded: {u['provider']}/{u['tier']} -> {u['new_model']} "
                    f"({u.get('reason', 'selected')})",
                    severity="high", category="MODEL_UPDATE",
                )
        except Exception:
            pass

    def _log_update(self, update: dict):
        log = []
        if UPDATE_LOG_FILE.exists():
            try:
                log = json.loads(UPDATE_LOG_FILE.read_text())
            except Exception:
                log = []
        log.append({**update, "applied_at": datetime.now(timezone.utc).isoformat()})
        UPDATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_LOG_FILE.write_text(json.dumps(log[-100:], indent=2, default=str))

    def _load_registry(self) -> dict:
        if MODEL_REGISTRY_FILE.exists():
            try:
                return json.loads(MODEL_REGISTRY_FILE.read_text())
            except Exception:
                pass
        return {"last_checked": "never"}

    def _save_registry(self):
        MODEL_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_REGISTRY_FILE.write_text(json.dumps(self.registry, indent=2, default=str))

    def get_status(self) -> dict:
        from core.llm.router import MODEL_REGISTRY, ANTHROPIC_REGISTRY
        log = []
        if UPDATE_LOG_FILE.exists():
            try:
                log = json.loads(UPDATE_LOG_FILE.read_text())[-5:]
            except Exception:
                pass
        return {
            "current_models": {
                "groq": {t: c["id"] for t, c in MODEL_REGISTRY.items()},
                "anthropic": {t: c["id"] for t, c in ANTHROPIC_REGISTRY.items()},
            },
            "last_checked": self.registry.get("last_checked", "never"),
            "last_selection": self.registry.get("last_selection", []),
            "recent_updates": log,
        }

    # ── Entry points ─────────────────────────────────────────────────────

    def check_and_apply(self) -> dict:
        """Check live catalogs and apply only materially better models."""
        result = self.check_for_updates()

        for d in result["deprecated"]:
            if d.get("new_model"):
                print(
                    f"[ModelUpdater] DEPRECATED: {d['provider']}/{d['tier']} "
                    f"'{d['old_model']}' -> safe replacement '{d['new_model']}'."
                )
            else:
                print(
                    f"[ModelUpdater] WARNING: {d['provider']}/{d['tier']} "
                    f"'{d['old_model']}' vanished and no profiled replacement exists."
                )

        updates = result["updates"]
        if not updates:
            print("[ModelUpdater] No materially better models found.")
            return {
                "status": "up_to_date", "found": 0, "applied": 0,
                "updates": [], "deprecated": result["deprecated"],
            }

        applied = self.apply_updates(updates)
        return {
            "status": "updated" if applied["applied"] else "apply_failed",
            "found": len(updates), "applied": applied["applied"],
            "updates": applied["updates"], "deprecated": result["deprecated"],
        }

    def force_check_now(self) -> dict:
        return self.check_and_apply()


model_updater = ModelUpdater()
