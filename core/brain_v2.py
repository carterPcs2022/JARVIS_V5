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

        # Action classification — mac_control takes priority over generic actions
        if self._is_mac_control(low, toks):
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

    def create(self, intent: Intent) -> Plan:
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
                response, model, provider = self._autonomous(intent)
            elif plan.mode == "code":
                response, model, provider = self._code(plan)
            elif plan.mode == "vision":
                response, model, provider = self._vision(plan)
            elif plan.mode == "voice":
                response, model, provider = self._voice(intent)
            else:
                response, model, provider = self._direct(intent)
        except Exception as e:
            response = f"I encountered an error: {e}"
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

        # ── Protocol 8: Honest Mode — wrap confidence score ───────────────────
        from core.protocols import honest_mode_wrap
        result.response = proto_prefix + honest_mode_wrap(result.response, user_input)

        # ── Proactive suggestion (non-intrusive append) ───────────────────────
        try:
            from services.predictor import get_proactive_suggestions
            suggestions = get_proactive_suggestions()
            if suggestions:
                result.response += f"\n\n_FYI: {suggestions[0]}_"
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
            },
        }


# Singleton instance
brain = Brain()
