"""
core/brain_v2.py — JARVIS V5 class-based brain pipeline.

Implements the intended architecture from the original skeleton:
  user_input → reasoner → validator → planner → executor → response

Dependency-injected so every component is swappable/testable.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Explicit "give me your best" phrasing — routes straight to
# core/stark_intelligence.py's full reasoning stack instead of the normal
# intent/plan/executor pipeline. Checked in Brain.process().
MAXIMUM_INTELLIGENCE_TRIGGERS = [
    "maximum intelligence",
    "use fable",
    "need your best",
    "pull out all the stops",
    "best you got",
    "think hard",
    "really think about",
    "most important",
]

MODEL_UPDATE_TRIGGERS = [
    "check for new models",
    "update your models",
    "are there new models",
    "upgrade your brain",
    "check for upgrades",
    "any new ai models",
    "update yourself",
]

SANDBOX_TRIGGERS = {
    "analyze yourself":     "analyze",
    "check your code":      "analyze",
    "what can you improve": "analyze",
    "improve yourself":     "improve",
    "optimize yourself":    "improve",
    "self improvement":     "improve",
    "fix your code":        "improve",
    "run sandbox":          "improve",
    "upgrade yourself":     "improve",
    "pending improvements": "pending",
}


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Intent:
    """What the user wants — extracted by the Reasoner."""
    raw:          str                    # original user input
    action:       str = "chat"          # chat | task | search | code | vision | voice
    subject:      str = ""              # what the action is about
    needs_web:    bool = False
    needs_agents: bool = False          # complex enough for multi-agent?
    complexity:   str = "simple"        # simple | moderate | complex
    context:      str = ""              # assembled context string
    system:       str = ""              # system prompt (personality-adapted)
    metadata:     dict = field(default_factory=dict)


@dataclass
class Validation:
    """Result of validating an intent."""
    ok:      bool
    reason:  str = ""
    intent:  Intent | None = None

    def __bool__(self):
        return self.ok


@dataclass
class Plan:
    """Execution plan created by the Planner."""
    intent:  Intent
    steps:   list[dict] = field(default_factory=list)
    mode:    str = "direct"            # direct | cot | multi_agent | autonomous


@dataclass
class Result:
    """Final output from the Executor."""
    response:     str
    ok:           bool = True
    model:        str = ""
    provider:     str = ""
    latency_ms:   float = 0.0
    used_cot:     bool = False
    was_rewritten: bool = False
    issues:       list = field(default_factory=list)
    raw_plan:     Plan | None = None
    confidence:   int = 0   # metadata only — never rendered into the response text


# ── Reasoner ─────────────────────────────────────────────────────────────────

class Reasoner:
    """Analyzes user input → Intent. Determines what JARVIS should do."""

    _TASK_KW   = {"research","find","search","look up","what is","who is",
                  "when did","how do","explain","tell me"}
    _CODE_KW   = {"code","write","debug","fix","function","script","program",
                  "implement","class","def ","import"}
    _VISION_KW = {"image","photo","picture","look at","analyze this"}
    _VOICE_KW  = {"say","speak","read aloud","voice","announce"}
    _COMPLEX_KW = {"plan","design","build","create","set up","configure",
                   "deploy","automate","compare","analyze"}
    _WEB_KW    = {"today","now","current","latest","news","weather","price",
                  "score","live","this week","breaking"}

    # Local filesystem operations — flagged separately so the executor can
    # refuse them on a headless cloud host instead of hallucinating success.
    _DELETE_FILE_KW = ["delete file","delete the file","remove file",
                       "remove the file","delete this file","trash the file"]
    _COMPRESS_FILE_KW = ["compress file","compress the file","zip file",
                        "zip the file","zip this file","compress this file",
                        "archive the file","archive this file"]

    def _is_delete_file(self, low: str) -> bool:
        return any(kw in low for kw in self._DELETE_FILE_KW) or (
            ("delete" in low or "remove" in low) and "file" in low)

    def _is_compress_file(self, low: str) -> bool:
        return any(kw in low for kw in self._COMPRESS_FILE_KW) or (
            ("compress" in low or "zip" in low) and "file" in low)

    # Mac / system control keywords
    _MAC_KW    = {
        "open","launch","start","close","quit","hide","show","focus",
        "play","pause","skip","next","previous","stop","mute","unmute",
        "volume","screenshot","spotify","music","email","gmail","inbox",
        "calendar","reminder","remind","notification","notify","finder",
        "clipboard","copy","paste","lock","trash","browser","chrome","safari",
        "message","facetime","notes","maps","photos","slack","discord",
        "check my","what's playing","who emailed","any emails","new emails",
        "send an email","send email","turn up","turn down","set volume",
        "what apps","running apps","take a screenshot",
    }

    def _is_mac_control(self, low: str, toks: set) -> bool:
        """True if this looks like a system/app control command."""
        if toks & {"open","launch","close","quit","play","pause","skip",
                   "mute","unmute","screenshot","remind","lock","trash"}:
            return True
        mac_phrases = [
            "check my email","check gmail","new emails","any emails","what's playing",
            "now playing","set volume","turn up the","turn down the","send an email",
            "send email","open spotify","open safari","open chrome","what apps are",
            "running apps","take a screenshot","current volume","the volume",
            "volume level","how loud","what song","current song","what's on",
            "my calendar","today's events","my emails","my inbox",
        ]
        return any(p in low for p in mac_phrases)

    def analyze(self, user_input: str) -> Intent:
        from core.context import build_context, build_system

        low  = user_input.lower()
        toks = set(low.split())

        # Action classification — delete/compress file checks come first so
        # they can never be misclassified as a generic mac_control command.
        if self._is_delete_file(low):
            action = "delete_file"
        elif self._is_compress_file(low):
            action = "compress_file"
        elif self._is_mac_control(low, toks):
            action = "mac_control"
        elif toks & self._VOICE_KW:
            action = "voice"
        elif toks & self._VISION_KW:
            action = "vision"
        elif any(kw in low for kw in self._CODE_KW):
            action = "code"
        elif any(kw in low for kw in self._TASK_KW):
            action = "task"
        else:
            action = "chat"

        # Complexity
        word_count = len(user_input.split())
        if any(kw in low for kw in self._COMPLEX_KW) or word_count > 40:
            complexity    = "complex"
            needs_agents  = True
        elif word_count > 15:
            complexity    = "moderate"
            needs_agents  = False
        else:
            complexity    = "simple"
            needs_agents  = False

        needs_web = any(kw in low for kw in self._WEB_KW) or action in ("task",)

        system_prompt = build_system()
        try:
            from core.language import detect_language, get_system_prompt_for_language
            lang = detect_language(user_input)
            if lang != "en":
                system_prompt = get_system_prompt_for_language(lang, system_prompt)
        except Exception:
            lang = "en"

        # Neurological mirroring — free (reads a cached profile, no LLM call)
        try:
            from core.neuro_mirror import neuro
            style_prompt = neuro.get_style_prompt()
            if style_prompt:
                system_prompt += f"\n\n{style_prompt}"
        except Exception:
            pass

        context = build_context(user_input, include_web=True)

        # Domain expertise — free (keyword match against registered domains)
        try:
            from core.domain_expert import domain_expert
            domain = domain_expert.detect_domain(user_input)
            if domain:
                context = domain_expert.get_domain_context(domain) + "\n\n" + context
        except Exception:
            pass

        return Intent(
            raw          = user_input,
            action       = action,
            subject      = user_input[:120],
            needs_web    = needs_web,
            needs_agents = needs_agents,
            complexity   = complexity,
            context      = context,
            system       = system_prompt,
            metadata     = {"language": lang},
        )


# ── Validator ─────────────────────────────────────────────────────────────────

class Validator:
    """Validates an intent before execution."""

    _BLOCKED = [
        "rm -rf", "drop table", "delete from", "format c:",
        "sudo rm", ":(){:|:&};:",   # fork bomb
    ]

    def check(self, intent: Intent) -> Validation:
        if not intent.raw or len(intent.raw.strip()) < 2:
            return Validation(ok=False, reason="Empty input", intent=intent)

        if len(intent.raw) > 4000:
            return Validation(ok=False, reason="Input too long (max 4000 chars)", intent=intent)

        raw_low = intent.raw.lower()
        for blocked in self._BLOCKED:
            if blocked in raw_low:
                return Validation(
                    ok=False,
                    reason=f"Input contains a blocked pattern: '{blocked}'",
                    intent=intent,
                )

        return Validation(ok=True, intent=intent)


# ── Planner ───────────────────────────────────────────────────────────────────

class Planner:
    """Creates an execution plan from a validated intent."""

    # Checked in priority order — first should_use() match wins. Kept in the
    # narrowest-trigger-first order so a query matching several loosely
    # (e.g. containing both "plan" and "estimate") lands on the more specific
    # technique rather than the first one registered.
    _REASONING_ENGINES = (
        "six_hats", "premortem", "fermi", "first_principles",
        "constraint_solver", "game_theory", "info_value", "mental_models",
    )

    def _select_reasoning_engine(self, raw: str) -> str | None:
        from core.six_hats import six_hats
        from core.premortem import premortem
        from core.fermi import fermi
        from core.first_principles import first_principles
        from core.constraint_satisfaction import constraint_solver
        from core.game_theory import game_theory
        from core.information_value import info_value
        from core.mental_models import mental_models
        engines = {
            "six_hats": six_hats, "premortem": premortem, "fermi": fermi,
            "first_principles": first_principles, "constraint_solver": constraint_solver,
            "game_theory": game_theory, "info_value": info_value, "mental_models": mental_models,
        }
        for name in self._REASONING_ENGINES:
            if engines[name].should_use(raw):
                return name
        return None

    def create(self, intent: Intent) -> Plan:
        from config.settings import ENABLE_REASONING_ENGINES
        if (ENABLE_REASONING_ENGINES and intent.action == "chat"
                and intent.complexity != "simple"):
            engine = self._select_reasoning_engine(intent.raw)
            if engine:
                return Plan(intent=intent, mode="reasoning_engine",
                            steps=[{"tool": "reasoning_engine", "args": {"engine": engine}}])

        if intent.complexity == "complex" and intent.needs_agents:
            mode  = "multi_agent"
            steps = self._decompose(intent)
        elif intent.complexity == "moderate":
            mode  = "cot"
            steps = [{"tool": "think", "args": {"prompt": intent.raw}}]
        else:
            mode  = "direct"
            steps = [{"tool": "think", "args": {"prompt": intent.raw}}]

        # Special action overrides
        if intent.action == "mac_control":
            mode  = "mac_control"
            steps = [{"tool": "mac_dispatch", "args": {"command": intent.raw}}]
        elif intent.action == "code":
            mode  = "code"
            steps = [{"tool": "code_generate",
                      "args": {"description": intent.raw}}]
        elif intent.action == "task":
            mode  = "autonomous"
            steps = self._task_steps(intent)
        elif intent.action == "vision":
            mode  = "vision"
            steps = [{"tool": "vision_analyze",
                      "args": {"prompt": intent.raw}}]
        elif intent.action == "voice":
            mode  = "voice"
            steps = [{"tool": "think", "args": {"prompt": intent.raw}}]

        return Plan(intent=intent, steps=steps, mode=mode)

    def _decompose(self, intent: Intent) -> list[dict]:
        from core.planner import decompose
        subtasks = decompose(intent.raw, n=3)
        return [{"tool": "think", "args": {"prompt": st}} for st in subtasks]

    def _task_steps(self, intent: Intent) -> list[dict]:
        from core.planner import plan
        return plan(intent.raw)


# ── Executor ─────────────────────────────────────────────────────────────────

class Executor:
    """Executes a plan and returns a Result."""

    def execute(self, plan: Plan) -> Result:
        start  = time.time()
        intent = plan.intent

        # ── Hallucination guard: never claim to touch the local filesystem
        # from a headless cloud host — JARVIS has no access to the user's Mac
        # from Render/Railway, so tell them the command to run locally instead.
        if intent.action in ("delete_file", "compress_file"):
            from config.settings import ENVIRONMENT
            if ENVIRONMENT == "render":
                command  = self._local_file_command(intent)
                response = (
                    "I can't access your local files from Render, sir. "
                    f"Run this command on your Mac instead: {command}"
                )
                return Result(response=response, model="", provider="hallucination_guard",
                              latency_ms=round((time.time() - start) * 1000, 2),
                              raw_plan=plan)

        try:
            if plan.mode == "mac_control":
                response, model, provider = self._mac_control(plan)
            elif plan.mode == "direct":
                response, model, provider = self._direct(intent)
            elif plan.mode == "cot":
                response, model, provider = self._cot(intent)
            elif plan.mode == "multi_agent":
                response, model, provider = self._multi_agent(intent)
            elif plan.mode == "autonomous":
                try:
                    response, model, provider = self._autonomous(intent)
                    if "[JARVIS OFFLINE]" in response or "All LLM providers failed" in response:
                        raise RuntimeError("All LLM providers failed during autonomous execution")
                except Exception as e:
                    print(f"[Executor] Autonomous task execution failed: {e}")
                    response, model, provider = self._direct(intent)
            elif plan.mode == "code":
                response, model, provider = self._code(plan)
            elif plan.mode == "vision":
                response, model, provider = self._vision(plan)
            elif plan.mode == "voice":
                response, model, provider = self._voice(intent)
            elif plan.mode == "reasoning_engine":
                response, model, provider = self._reasoning_engine(plan)
            else:
                response, model, provider = self._direct(intent)
        except Exception as e:
            print(f"[Executor] Execution failed: {e}")
            response = "I ran into a problem with that. Can you break it into smaller steps?"
            model = provider = "error"

        # Reflection pass
        was_rewritten = False
        if plan.mode not in ("voice", "code", "vision", "mac_control"):
            from core.reflection import reflect
            ref           = reflect(intent.raw, response)
            response      = ref["final"]
            was_rewritten = ref["was_rewritten"]

        # Validate
        from core.validator import validate
        val      = validate(response, intent.raw)
        response = val["response"]

        latency = round((time.time() - start) * 1000, 2)

        # Persist
        from core.memory import save_turn, store_long_term
        from core import evolution
        save_turn(intent.raw, response)
        store_long_term(intent.raw, response)
        evolution.log(intent.raw, response, model, latency,
                      was_rewritten=was_rewritten)

        # Voice output — always generate audio in background via ElevenLabs
        # cascade (never blocks the text response). By default this only
        # writes static_voice.mp3 for the HUD to auto-play; it does NOT also
        # sound through this machine's speakers, since a HUD tab open on the
        # same machine would otherwise play every response twice. Set
        # VOICE_LOCAL_PLAYBACK=true to also speak locally (e.g. headless use).
        from config.settings import VOICE_ENABLED, IS_RAILWAY, VOICE_LOCAL_PLAYBACK
        if VOICE_ENABLED and not IS_RAILWAY:
            import threading

            def _voice_task():
                try:
                    from core.state import state
                    from core.personality import get_voice_mode
                    from services.elevenlabs_voice import speak_with_mode, generate_for_network
                    mode = state.get("voice_mode") or get_voice_mode()
                    if VOICE_LOCAL_PLAYBACK:
                        speak_with_mode(response, mode, play=True)
                    generate_for_network(response)
                except Exception:
                    pass

            threading.Thread(target=_voice_task, daemon=True).start()

        return Result(
            response      = response,
            ok            = val["valid"],
            model         = model,
            provider      = provider,
            latency_ms    = latency,
            was_rewritten = was_rewritten,
            issues        = val["issues"],
            raw_plan      = plan,
        )

    def _direct(self, intent: Intent) -> tuple[str, str, str]:
        from core.llm.router import chat as llm_chat
        messages = [
            {"role": "system", "content": intent.system},
            {"role": "user",   "content": intent.raw},
        ]
        if intent.context:
            messages.insert(1, {"role": "system",
                                "content": f"Context:\n{intent.context}"})
        # query=intent.raw enables smart model routing (zero extra cost —
        # pattern classification only, no extra API call) so simple messages
        # go to the fast/cheap tier and complex ones to a stronger model.
        r = llm_chat(messages, temperature=0.6, query=intent.raw)
        return r["content"], r.get("model",""), r.get("provider","")

    def _cot(self, intent: Intent) -> tuple[str, str, str]:
        from core.reasoning import reason
        r = reason(intent.raw, intent.context)
        return r["answer"], "", ""

    def _multi_agent(self, intent: Intent) -> tuple[str, str, str]:
        from core.agents.planner_agent import run_parallel
        r = run_parallel(intent.raw, n_agents=3)
        return r["final"], "", "multi_agent"

    def _autonomous(self, intent: Intent) -> tuple[str, str, str]:
        from core.agents.planner_agent import run
        r = run(intent.raw)
        return r["final"], "", "autonomous"

    def _code(self, plan: Plan) -> tuple[str, str, str]:
        from core.agents.coder import generate
        r = generate(plan.intent.raw)
        code = r["code"]
        status = "✅ Syntax valid" if r["valid"] else f"⚠️ {r['error']}"
        return f"```{r['language']}\n{code}\n```\n\n{status}", "", "coder"

    def _vision(self, plan: Plan) -> tuple[str, str, str]:
        from core.tools.vision import analyze
        # Try to find an image path in the intent
        import re
        m = re.search(r"['\"]?(/[\w/. -]+\.(png|jpg|jpeg|webp|gif))['\"]?",
                      plan.intent.raw, re.I)
        path = m.group(1) if m else ""
        if not path:
            return "Please provide an image path to analyze.", "", ""
        return analyze(path, plan.intent.raw), "", "vision"

    def _voice(self, intent: Intent) -> tuple[str, str, str]:
        response, model, provider = self._direct(intent)
        return response, model, provider

    def _mac_control(self, plan: Plan) -> tuple[str, str, str]:
        from core.mac_dispatcher import dispatch
        result = dispatch(plan.intent.raw)
        return result, "", "mac"

    def _reasoning_engine(self, plan: Plan) -> tuple[str, str, str]:
        """Dispatch to whichever core/*.py reasoning technique Planner
        selected (see Planner._select_reasoning_engine). Each engine returns
        a dict of intermediate reasoning steps — pull out the final answer."""
        engine  = plan.steps[0]["args"]["engine"]
        intent  = plan.intent
        if engine == "six_hats":
            from core.six_hats import six_hats
            return six_hats.think(intent.raw)["synthesis"], "", "six_hats"
        if engine == "premortem":
            from core.premortem import premortem
            return premortem.analyze(intent.raw)["mitigations"], "", "premortem"
        if engine == "fermi":
            from core.fermi import fermi
            r = fermi.estimate(intent.raw)
            return f"{r['decomposition']}\n\n{r['sanity_check']}", "", "fermi"
        if engine == "first_principles":
            from core.first_principles import first_principles
            return first_principles.reason(intent.raw)["solution"], "", "first_principles"
        if engine == "constraint_solver":
            from core.constraint_satisfaction import constraint_solver
            return constraint_solver.solve(intent.raw, [])["solution"], "", "constraint_solver"
        if engine == "game_theory":
            from core.game_theory import game_theory
            return game_theory.analyze(intent.raw)["analysis"], "", "game_theory"
        if engine == "info_value":
            from core.information_value import info_value
            return info_value.most_valuable(intent.raw, intent.context)["analysis"], "", "info_value"
        if engine == "mental_models":
            from core.mental_models import mental_models
            r = mental_models.apply(intent.raw, intent.context)
            return r["response"], "", f"mental_model_{r.get('used_model', '')}"
        return self._direct(intent)

    def _local_file_command(self, intent: Intent) -> str:
        """Best-effort shell command the user can run locally for a
        delete/compress request we can't perform from a cloud host."""
        import re
        m    = re.search(r"['\"]?(~?/?[\w\-./ ]+\.\w+)['\"]?", intent.raw)
        path = m.group(1).strip() if m else "<file path>"
        if intent.action == "delete_file":
            return f"rm '{path}'"
        if intent.action == "compress_file":
            return f"zip -r '{path}.zip' '{path}'"
        return ""

    def check_for_pushback(self, intent: Intent) -> str | None:
        """Should JARVIS push back on this request? One LLM call — available
        on demand, not run before every message (that would double the LLM
        call cost of every single interaction). Protocol 18 (Sokovia) and
        Protocol 1 (Bodyguard) already cover the pre-execution risk check
        for the pipeline's default flow; this is for callers who explicitly
        want the "are you sure, sir?" judgment call on a specific request."""
        from core.llm.router import think
        import json
        result = think(
            f"Should JARVIS push back on this request? Consider: safety, "
            f"wisdom, better alternatives.\n\nRequest: {intent.raw}\n\n"
            f'Reply as JSON: {{"should_pushback": bool, "reason": str, "pushback_message": str}}',
            force_model="instant",
        )
        try:
            data = json.loads(result.strip())
            if data.get("should_pushback"):
                return data.get("pushback_message", "I'd advise against that, sir.")
        except Exception:
            pass
        return None


# ── Brain (assembles everything) ──────────────────────────────────────────────

class Brain:
    """
    JARVIS V5 Brain — full pipeline.
    Faithful to the original skeleton, fully implemented.
    """

    def __init__(self):
        self.reasoner  = Reasoner()
        self.validator = Validator()
        self.planner   = Planner()
        self.executor  = Executor()
        from core.protocols import protocol_engine
        self.protocols = protocol_engine

    def process(self, user_input: str) -> Result:
        from core.personality import analyze_message
        from core.event_bus import bus
        from core.state import state

        # ── Privacy mode: bypass the whole pipeline, no persistence at all ────
        from core.privacy_mode import privacy_mode
        if privacy_mode.is_active():
            response = privacy_mode.private_think(user_input)
            return Result(response=response, model="ollama", provider="ollama-private")

        analyze_message(user_input)
        bus.chat("user", user_input)
        state.set("last_interaction", datetime.now().isoformat())

        # ── Predictive cache — free lookup, instant response if pre-loaded ────
        try:
            from services.predictor import predictor_engine
            cached = predictor_engine.get_cached_response(user_input)
            if cached:
                return Result(response=cached["response"], ok=True, meta={"predicted": True})
        except Exception:
            pass

        # ── Spotify quick commands — instant, no LLM needed ──────────────────
        try:
            from services.spotify import handle_spotify_command
            spotify_response = handle_spotify_command(user_input)
            if spotify_response:
                from core.memory import save_turn
                save_turn(user_input, spotify_response)
                return Result(response=spotify_response, ok=True, provider="spotify")
        except Exception:
            pass

        # ── Smart home scene commands — instant, no LLM needed ───────────────
        try:
            from services.home_automation import handle_scene_command
            scene_response = handle_scene_command(user_input)
            if scene_response:
                from core.memory import save_turn
                save_turn(user_input, scene_response)
                return Result(response=scene_response, ok=True, provider="home_automation")
        except Exception:
            pass

        # ── Model self-update — instant, no LLM needed for the check itself ───
        if any(t in user_input.lower() for t in MODEL_UPDATE_TRIGGERS):
            try:
                from services.model_updater import model_updater
                result = model_updater.force_check_now()
                if result["status"] == "updated":
                    updates = result.get("updates", [])
                    response = (
                        f"Updates applied, sir. Upgraded {result['applied']} model(s): "
                        + ", ".join(f"{u['tier']} to {u['new_model'].split('-')[-1]}" for u in updates[:3])
                    )
                else:
                    response = "All models are current, sir. Running the latest available versions."

                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=True, provider="model_updater")
            except Exception:
                pass

        # ── Self-programming sandbox — analysis/improve/pending status ───────
        # "improve" writes candidate code and sandbox-tests it synchronously
        # (can take a while — it's a real LLM rewrite + subprocess test) but
        # never deploys anything; that always requires a separate explicit
        # approval via voice ("JARVIS approve improvement") is not wired here
        # on purpose — deployment approval goes through
        # POST /stark/sandbox/approve/{id}, not a voice trigger, since it's
        # the one action in this whole pipeline that writes a real file.
        low_input = user_input.lower()
        for trigger, action in SANDBOX_TRIGGERS.items():
            if trigger in low_input:
                try:
                    if action == "analyze":
                        from core.self_analysis import self_analysis, ALLOWED_FILES
                        result = self_analysis.analyze_self()
                        count = result.get("safe", 0)
                        response = (
                            f"Self-analysis complete, sir. Found {count} potential improvements "
                            f"across {len(ALLOWED_FILES)} core files. "
                            f"Say 'JARVIS improve yourself' to write and test them."
                            if count > 0 else
                            "All code is optimal, sir. No improvements identified."
                        )
                    elif action == "improve":
                        from core.self_improvement import self_improvement
                        result = self_improvement.run_improvement_cycle()
                        response = result.get("message", "Cycle complete.")
                    elif action == "pending":
                        from core.self_improvement import self_improvement
                        pending = self_improvement.get_pending_approvals()
                        response = (
                            f"{len(pending)} improvement(s) awaiting your approval, sir."
                            if pending else
                            "No improvements pending approval."
                        )
                    else:
                        continue

                    from core.memory import save_turn
                    save_turn(user_input, response)
                    return Result(response=response, ok=True, provider="sandbox")
                except Exception:
                    pass
                break

        # ── Maximum intelligence — explicit "give me your best" requests
        # bypass the normal intent/plan/executor pipeline entirely and run
        # every reasoning technique JARVIS has (see core/stark_intelligence.py) ─
        if any(t in user_input.lower() for t in MAXIMUM_INTELLIGENCE_TRIGGERS):
            try:
                from core.stark_intelligence import stark_intel
                result = stark_intel.maximum_intelligence(user_input)

                bus.system("Maximum intelligence engaged. Fable 5 with extended thinking active.")

                from core.memory import save_turn, store_long_term
                save_turn(user_input, result["response"])
                store_long_term(user_input, result["response"])
                return Result(response=result["response"], ok=True,
                              model=result["model"], provider="stark_intelligence")
            except Exception as e:
                print(f"[Brain] Maximum intelligence failed, falling back to normal pipeline: {e}")

        # ── Instant responses (e.g. "what time is it") — no LLM needed, and
        # answered from the user's configured timezone rather than letting
        # a model guess based on the server's UTC clock ────────────────────
        try:
            from core.llm.router import _instant_response
            instant = _instant_response(user_input)
            if instant:
                from core.memory import save_turn
                save_turn(user_input, instant)
                return Result(response=instant, ok=True, provider="instant")
        except Exception:
            pass

        # ── Protocol 14: Friday fallback if all LLMs offline ─────────────────
        from core.llm.router import check_groq, check_ollama
        from core.state import state as _state
        if not _state.get("groq_available") and not _state.get("ollama_available"):
            from core.friday_fallback import respond as friday_respond
            r = friday_respond(user_input)
            return Result(
                response  = r["response"],
                model     = r["model"],
                provider  = r["provider"],
                latency_ms= r["latency_ms"],
                issues    = r["meta"]["issues"],
            )

        # Record query pattern and extract people mentions
        try:
            from services.predictor import record_query
            record_query(user_input)
        except Exception:
            pass
        try:
            from services.people import ingest_from_text
            ingest_from_text(user_input)
        except Exception:
            pass

        # Pipeline: Reasoner → Validator → ProtocolEngine → Planner → Executor
        intent     = self.reasoner.analyze(user_input)

        # Inject people context into intent context
        try:
            from services.people import get_people_context
            pctx = get_people_context(user_input)
            if pctx:
                intent.context = pctx + "\n\n" + intent.context
        except Exception:
            pass

        # Note if this is essentially a repeated question — JARVIS uses
        # judgment on whether to mention that ("You asked me this before")
        # or just answer directly; we only give him the fact, not the phrasing.
        try:
            from core.memory import check_if_repeated
            repeat = check_if_repeated(user_input)
            if repeat and repeat.get("days_ago") is not None:
                note = (
                    f"[The user asked something very similar to this {repeat['days_ago']} "
                    f"day(s) ago. Your previous answer was: \"{repeat['ai'][:300]}\". "
                    f"Use your judgment — mention it briefly if useful, or just answer "
                    f"directly if repeating yourself would be tedious.]"
                )
                intent.context = note + "\n\n" + intent.context
        except Exception:
            pass

        validation = self.validator.check(intent)

        if not validation.ok:
            return Result(
                response = f"I can't process that: {validation.reason}",
                ok       = False,
                issues   = [validation.reason],
            )

        # ── Protocol Engine (sits between Validator and Planner) ──────────────
        proto = self.protocols.check(intent)
        if not proto.allowed:
            bus.publish("protocol", {
                "protocol": proto.protocol_triggered,
                "message":  proto.message,
            }, "warning")
            return Result(
                response = proto.message,
                ok       = False,
                issues   = [proto.protocol_triggered],
            )

        # Warn but allow — prepend protocol message to response
        proto_prefix = ""
        if proto.protocol_triggered and proto.allowed:
            proto_prefix = f"⚠ {proto.message}\n\n"
            bus.publish("protocol", {
                "protocol": proto.protocol_triggered,
                "message":  proto.message,
            }, "warning")

        plan   = self.planner.create(intent)
        result = self.executor.execute(plan)

        # ── Confidence scoring ────────────────────────────────────────────────
        try:
            from core.validator import score_confidence, add_confidence_marker
            conf_score      = score_confidence(user_input, result.response)
            result.response = add_confidence_marker(result.response, conf_score)
        except Exception:
            pass

        # ── Protocol 8: Honest Mode — confidence score, metadata only ─────────
        # Previously prepended a "[Confidence: X%]" badge to the response text
        # (honest_mode_wrap) — that leaked into the user-facing chat. The
        # score is still computed and attached to the Result, just never
        # rendered into the response string itself.
        try:
            from core.protocols import honest_mode_score
            result.confidence = honest_mode_score(result.response, user_input)
        except Exception:
            pass
        result.response = proto_prefix + result.response

        # ── Egress filtering — redact any secret/PII that made it into the
        # response before the user ever sees it. Also runs a secondary
        # provider-key-pattern scan (services/dpi) as defense in depth.
        try:
            from services.egress_filter import egress
            filtered = egress.filter(result.response)
            result.response = filtered["response"]
            if not filtered["clean"]:
                from services.audit_log import audit_log
                audit_log.record("egress_redaction", "jarvis", {}, "redacted")
        except Exception:
            pass
        try:
            from services.dpi import dpi
            dpi.monitor_response(result.response)
        except Exception:
            pass

        # ── Audit trail + suit-security interaction fingerprint ───────────────
        try:
            from services.audit_log import audit_log
            audit_log.record("chat_response", "jarvis",
                             {"query": user_input[:100], "model": result.model}, "success")
        except Exception:
            pass
        try:
            from services.suit_security import suit_security
            suit_security.record_interaction_pattern(user_input, result.latency_ms)
        except Exception:
            pass

        bus.chat("assistant", result.response)
        return result

    def process_dict(self, user_input: str) -> dict:
        """Convenience wrapper that returns a plain dict (for API routes)."""
        r = self.process(user_input)

        # active_tier is set by core.llm.router only when an Anthropic tier
        # (sonnet/opus/fable) actually served the response — absent for
        # ordinary Groq-tier turns, which is the common case.
        tier = None
        try:
            from core.state import state
            tier = state.get("active_tier")
        except Exception:
            pass

        return {
            "response":      r.response,
            "model":         r.model,
            "provider":      r.provider,
            "latency_ms":    r.latency_ms,
            "meta": {
                "action":        r.raw_plan.intent.action if r.raw_plan else "unknown",
                "complexity":    r.raw_plan.intent.complexity if r.raw_plan else "unknown",
                "mode":          r.raw_plan.mode if r.raw_plan else "unknown",
                "was_rewritten": r.was_rewritten,
                "issues":        r.issues,
                "tier":          tier,
                "confidence":    r.confidence,
            },
        }


# Singleton instance
brain = Brain()
