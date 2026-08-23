"""services/model_updater.py — JARVIS checks whether a newer release of an
already-configured model exists and patches it in live.

Deliberately narrower than "track every model family and auto-classify new
tiers": it only looks for a newer version of the exact model each tier is
already pinned to (e.g. claude-opus-4-8 -> claude-opus-4-9), and flags
(but never guesses a replacement for) a model that's vanished from the
live catalog entirely. See core/llm/router.py's MODEL_REGISTRY comment —
a past registry that trusted a model listing outright ended up with
decommissioned Groq models 404ing on every call, which is exactly the
failure mode this avoids by only ever comparing within the same family.
"""
from __future__ import annotations
import json, re
import httpx
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR

MODEL_REGISTRY_FILE = BASE_DIR / "memory" / "model_registry.json"
UPDATE_LOG_FILE      = BASE_DIR / "logs" / "model_updates.json"
SETTINGS_FILE         = BASE_DIR / "config" / "settings.py"
ROUTER_FILE           = BASE_DIR / "core" / "llm" / "router.py"

ANTHROPIC_SETTING_NAMES = {
    "sonnet": "ANTHROPIC_MODEL_SONNET",
    "opus":   "ANTHROPIC_MODEL_OPUS",
    "fable":  "ANTHROPIC_MODEL_FABLE",
}


def _base_family(model_id: str) -> str:
    """Strip version numbers so different releases of the same model
    line compare equal, e.g. llama-3.1-70b-versatile and
    llama-3.3-70b-versatile both become llama-.-70b-versatile.

    Only digit runs NOT immediately followed by a letter are stripped —
    a trailing letter (8b, 20b, 70b, 120b) marks a parameter-count/size
    suffix, not a version number, and must stay literal in the family
    string. Without this distinction, openai/gpt-oss-20b and
    openai/gpt-oss-120b both reduced to "openai/gpt-oss-b" and compared
    as if 120b were merely a newer *version* of 20b, when they're
    actually two different-sized sibling models. _is_newer() would then
    treat the size jump as a legitimate upgrade and check_and_apply()
    auto-patches + auto-commits + auto-pushes it with no human review —
    silently swapping in a materially different (far larger/slower/
    costlier) model under a tier that was deliberately pinned small
    (e.g. a low-latency threat classifier).

    Checking the lookahead only after the full greedy \\d+ run (via a
    match callback, not a regex lookahead assertion) matters here: a
    lookahead assertion backtracks \\d+ down to a partial run to satisfy
    itself -- e.g. "20b" would regex-backtrack \\d+ to just "2" (since
    "0" right after it isn't a letter), stripping half the size token
    instead of leaving it intact."""
    model_id = model_id.lower()

    def _strip_unless_size_suffix(m: re.Match) -> str:
        next_char = model_id[m.end():m.end() + 1]
        return m.group(0) if next_char.isalpha() else ""

    return re.sub(r"\d+", _strip_unless_size_suffix, model_id)


def _version_tuple(model_id: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", model_id)]


def _is_newer(candidate: str, current: str) -> bool:
    cand_v, cur_v = _version_tuple(candidate), _version_tuple(current)
    for c, k in zip(cand_v, cur_v):
        if c > k: return True
        if c < k: return False
    return len(cand_v) > len(cur_v)


class ModelUpdater:

    def __init__(self):
        self.registry = self._load_registry()

    # ── Live catalogs ──────────────────────────────────────────────────────

    def _fetch_groq_models(self) -> set[str]:
        from config.settings import GROQ_API_KEY
        if not GROQ_API_KEY:
            return set()
        try:
            r = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=10,
            )
            if r.status_code != 200:
                return set()
            return {m["id"] for m in r.json().get("data", []) if m.get("id")}
        except Exception as e:
            print(f"[ModelUpdater] Groq fetch failed: {e}")
            return set()

    def _fetch_anthropic_models(self) -> set[str]:
        from config.settings import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            return set()
        try:
            r = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                timeout=10,
            )
            if r.status_code != 200:
                return set()
            return {m["id"] for m in r.json().get("data", []) if m.get("id")}
        except Exception as e:
            print(f"[ModelUpdater] Anthropic fetch failed: {e}")
            return set()

    # ── Detection ────────────────────────────────────────────────────────

    def _check_registry(self, provider: str, registry: dict, live_ids: set[str]) -> list[dict]:
        updates = []
        for tier, cfg in registry.items():
            current_id = cfg.get("id", "")
            if not current_id:
                continue
            if current_id not in live_ids:
                updates.append({"provider": provider, "tier": tier,
                                 "new_model": None, "old_model": current_id,
                                 "type": "deprecated"})
                continue
            family = _base_family(current_id)
            newer = [m for m in live_ids
                     if m != current_id and _base_family(m) == family and _is_newer(m, current_id)]
            if newer:
                best = max(newer, key=_version_tuple)
                updates.append({"provider": provider, "tier": tier,
                                 "new_model": best, "old_model": current_id,
                                 "type": "upgrade"})
        return updates

    def check_for_updates(self) -> dict:
        print("[ModelUpdater] Checking for new models...")
        updates = []

        groq_ids = self._fetch_groq_models()
        if groq_ids:
            from core.llm.router import MODEL_REGISTRY
            updates += self._check_registry("groq", MODEL_REGISTRY, groq_ids)

        anthropic_ids = self._fetch_anthropic_models()
        if anthropic_ids:
            from core.llm.router import ANTHROPIC_REGISTRY
            updates += self._check_registry("anthropic", ANTHROPIC_REGISTRY, anthropic_ids)

        self.registry["last_checked"] = datetime.now().isoformat()
        self._save_registry()

        return {
            "updates_available": len([u for u in updates if u["type"] == "upgrade"]),
            "updates":           [u for u in updates if u["type"] == "upgrade"],
            "deprecated":        [u for u in updates if u["type"] == "deprecated"],
            "checked_at":        self.registry["last_checked"],
        }

    # ── Apply ────────────────────────────────────────────────────────────

    def apply_updates(self, updates: list) -> dict:
        if not updates:
            return {"applied": 0, "updates": [], "message": "No updates to apply"}

        applied = []
        for update in updates:
            provider, tier = update["provider"], update["tier"]
            new_model, old_model = update["new_model"], update["old_model"]
            try:
                self._update_in_memory(provider, tier, new_model)
                if provider == "anthropic":
                    self._patch_settings_file(tier, new_model)
                else:
                    self._patch_router_file(tier, new_model)
                self._log_update(update)
                applied.append(update)
                print(f"[ModelUpdater] {provider} {tier}: {old_model} -> {new_model}")
            except Exception as e:
                print(f"[ModelUpdater] Failed to apply {provider}/{tier}: {e}")

        if applied:
            self._announce_updates(applied)
            self._commit_to_github(applied)

        return {"applied": len(applied), "updates": applied,
                "message": f"Applied {len(applied)} model update(s)"}

    def _commit_to_github(self, updates: list):
        """Persist applied updates past the next Render redeploy — patching
        files on disk alone doesn't survive that, since the filesystem is
        ephemeral and nothing else here pushes to git. Only the two source
        files actually get committed; memory/model_registry.json is
        gitignored on purpose (it's local bookkeeping, not something this
        repo tracks) and isn't needed for durability anyway."""
        from utils.git_ops import commit_and_push
        names = "; ".join(f"{u['tier']} to {u['new_model']}" for u in updates[:3])
        commit_and_push(
            ["config/settings.py", "core/llm/router.py"],
            f"auto(models): update {names}",
            log_prefix="[ModelUpdater]",
        )

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
        """MODEL_REGISTRY entries are flat — {"tier": {"id": "...", ...}}, no
        nested braces — so a block-scoped regex (this tier's opening brace to
        its own closing brace) can safely replace just its "id" value."""
        if not ROUTER_FILE.exists():
            return
        content = ROUTER_FILE.read_text()
        block = re.search(rf'"{tier}":\s*\{{(.*?)\}}', content, re.DOTALL)
        if not block:
            return
        new_inner = re.sub(r'"id":\s*"[^"]*"', f'"id": "{new_model}"', block.group(1), count=1)
        if new_inner == block.group(1):
            return
        updated = content[:block.start(1)] + new_inner + content[block.end(1):]
        ROUTER_FILE.write_text(updated)
        print(f"[ModelUpdater] Patched router.py: {tier} id = {new_model}")

    # ── Persistence / reporting ──────────────────────────────────────────

    def _announce_updates(self, updates: list):
        names = ", ".join(f"{u['tier']} to {u['new_model'].split('-')[-1]}" for u in updates[:3])
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
                # "info" doesn't reach the critical/high Pushover fan-out —
                # same tier bug as tonight's other fixes.
                bus.alert(f"Model upgraded: {u['provider']}/{u['tier']} -> {u['new_model']}",
                          severity="high", category="MODEL_UPDATE")
        except Exception:
            pass

    def _log_update(self, update: dict):
        log = []
        if UPDATE_LOG_FILE.exists():
            try:
                log = json.loads(UPDATE_LOG_FILE.read_text())
            except Exception:
                log = []
        log.append({**update, "applied_at": datetime.now().isoformat()})
        UPDATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_LOG_FILE.write_text(json.dumps(log[-100:], indent=2))

    def _load_registry(self) -> dict:
        if MODEL_REGISTRY_FILE.exists():
            try:
                return json.loads(MODEL_REGISTRY_FILE.read_text())
            except Exception:
                pass
        return {"last_checked": "never"}

    def _save_registry(self):
        MODEL_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_REGISTRY_FILE.write_text(json.dumps(self.registry, indent=2))

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
                "groq":      {t: c["id"] for t, c in MODEL_REGISTRY.items()},
                "anthropic": {t: c["id"] for t, c in ANTHROPIC_REGISTRY.items()},
            },
            "last_checked":   self.registry.get("last_checked", "never"),
            "recent_updates": log,
        }

    # ── Entry points ─────────────────────────────────────────────────────

    def check_and_apply(self) -> dict:
        """Full cycle: check, apply any upgrades, log deprecations. Called
        by the weekly scheduler job and the startup check."""
        result = self.check_for_updates()
        updates = result["updates"]

        for d in result["deprecated"]:
            print(f"[ModelUpdater] WARNING: {d['provider']}/{d['tier']} model "
                  f"'{d['old_model']}' no longer appears in the live catalog.")

        if not updates:
            print("[ModelUpdater] All models up to date.")
            return {"status": "up_to_date", "found": 0, "applied": 0,
                    "updates": [], "deprecated": result["deprecated"]}

        applied = self.apply_updates(updates)
        return {
            "status":     "updated" if applied["applied"] else "apply_failed",
            "found":      len(updates),
            "applied":    applied["applied"],
            "updates":    applied["updates"],
            "deprecated": result["deprecated"],
        }

    def force_check_now(self) -> dict:
        """Voice-command / API trigger — same cycle as the scheduled job."""
        return self.check_and_apply()


model_updater = ModelUpdater()
