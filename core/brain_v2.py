"""
core/brain_v2.py — JARVIS V5 class-based brain pipeline.

Implements the intended architecture from the original skeleton:
  user_input → reasoner → validator → planner → executor → response

Dependency-injected so every component is swappable/testable.
"""
import difflib
import re
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

CLIP_TRIGGERS = [
    "clip that", "save that", "remember that",
    "mark that", "jarvis clip", "save this moment",
    "bookmark that",
]

# (method name on services.mac_bridge.mac_bridge, args) — dispatched via
# getattr() rather than lambdas capturing mac_bridge, so the module only
# needs importing once at call time, matching this file's existing
# local-import convention instead of a module-level import.
MAC_APP_TRIGGERS = {
    "open spotify":   ("open_app", ("Spotify",)),
    "open chrome":    ("open_app", ("Google Chrome",)),
    "open safari":    ("open_app", ("Safari",)),
    "open terminal":  ("open_app", ("Terminal",)),
    "open finder":    ("open_app", ("Finder",)),
    "open notes":     ("open_app", ("Notes",)),
    "open calendar":  ("open_app", ("Calendar",)),
    "open mail":      ("open_app", ("Mail",)),
    "do not disturb": ("do_not_disturb", (True,)),
    "focus mode":     ("do_not_disturb", (True,)),
    "mute mac":       ("set_volume", (0,)),
    "mac volume":     ("set_volume", (50,)),
}

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
    "analyze your code":    "analyze",
    "what can you improve": "analyze",
    "self analyze":         "analyze",
    "self-analyze":         "analyze",
    "improve yourself":     "improve",
    "optimize yourself":    "improve",
    "self improvement":     "improve",
    # "self improve" (no "-ment") is a real natural phrasing that missed
    # the "self improvement" substring entirely and fell through to
    # ordinary chat — confirmed live, it fabricated a fake cycle report
    # by echoing numbers from an earlier real "analyze yourself" turn in
    # the same conversation. Added explicitly rather than assuming every
    # short form is covered, same lesson as the self-check gap above.
    "self improve":         "improve",
    "self-improve":         "improve",
    "fix your code":        "improve",
    "run sandbox":          "improve",
    "upgrade yourself":     "improve",
    "pending improvements": "pending",
}

# No trigger for "run a self check" / "health check" existed at all before
# this was added — that phrase fell through to ordinary chat, which did an
# unrelated web search and then confidently claimed "self-check complete,
# all systems nominal" with nothing real behind it. utils.diagnostics.
# full_diagnostic() already does a genuine, comprehensive check (LLM
# provider availability, CPU/RAM/disk, lockdown/Friday state, config
# validation, Mac Bridge reachability, memory file integrity) — this
# routes to that instead of letting the phrase go unrecognized.
SELF_CHECK_TRIGGERS = [
    "run self check", "run a self check", "self check", "self-check",
    "run self-check", "health check", "run health check",
    "system check", "systems check", "run diagnostics", "run a diagnostic",
    "run diagnostic", "status check", "full diagnostic",
]

# ── Security-protocol activation requests — NEVER a real trigger here ────────
# Lockdown and Coldfire are intentionally, correctly UNREACHABLE from chat —
# they require the real, passphrase-gated POST /stark/lockdown or
# POST /stark/coldfire endpoints (see server/routes/protocols.py), which
# also require the master API token and a two-step confirmation. That's
# correct and must stay that way; the fix here is NOT to add a chat
# trigger that executes them.
#
# The bug: with no real handler, "JARVIS run lockdown" fell through to
# ordinary chat, and the model fabricated an entire plausible two-step
# confirmation flow ("Bodyguard Protocol: Lockdown blocks all API access
# except Tailscale. Are you sure? Reply 'confirm' to proceed." ... then,
# on "confirm", "Lockdown protocol is active, sir.") — convincing enough
# that a family member watched it happen and reasonably believed a real
# security bypass had occurred. Confirmed via Render logs: no real
# POST /stark/lockdown call happened anywhere near that conversation —
# it was 100% fabricated, but a fabricated SECURITY claim is worse than
# a fabricated code-improvement claim, since it can create a false sense
# of security (or a false alarm) about something that actually matters.
#
# This block exists purely to intercept the request and say so honestly
# — never to execute anything.
PROTOCOL_NAME_WORDS = {"lockdown", "coldfire", "endgame", "avengers"}
PROTOCOL_ACTION_VERBS = {
    "run", "activate", "engage", "trigger", "start", "initiate",
    "execute", "enable", "enact",
}


def classify_protocol_request(user_input: str) -> str | None:
    """Returns the matched protocol name ("lockdown"/"coldfire"/
    "endgame"/"avengers") if this reads as a request to activate a
    security-critical Stark Protocol, else None. Deliberately simple
    keyword-combination matching (no fuzzy layer) — these are rare,
    distinctive tokens with low collision risk, unlike the self-action
    verbs, so the extra machinery isn't needed."""
    low = user_input.lower()
    toks = set(re.findall(r"[a-z']+", low))
    protocol = next((p for p in PROTOCOL_NAME_WORDS if p in toks), None)
    if not protocol:
        return None
    if toks & PROTOCOL_ACTION_VERBS or "protocol" in toks:
        return protocol
    return None


# ── General self-referential-action detector ─────────────────────────────────
# SANDBOX_TRIGGERS/SELF_CHECK_TRIGGERS above are exact substring lists —
# each fix session found ONE more missed phrasing ("ARVIS improve yourself"
# typo tolerance, then "self improve" without "-ment", then "suggest some
# improvements" fabricating an "Implemented suggestion list, sir" claim).
# Natural language has no ceiling on how this can be rephrased; a fixed
# list can never converge. This generalizes the fix using the same
# technique Reasoner._is_calendar() already uses for calendar typo
# tolerance: fuzzy phrase matching via difflib, not exact strings.
#
# Two-gate design: (1) a self-reference phrase ("yourself", "your code",
# "self improve", etc.) must fuzzy-match one of the message's 1-3 word
# windows, AND (2) an action-verb-shaped word must also be present. Both
# gates matter — self-reference alone ("yourself, tell me a joke") isn't
# a maintenance request, and an action verb alone ("fix my self-driving
# car" — "self" appears, but not adjacent to any of these phrases at a
# tight fuzzy cutoff) isn't either. Verified against both the exact bugs
# found this session and a set of plausible unrelated requests that must
# NOT trigger (see tests before this was wired in).
_SELF_REF_PHRASES = [
    "yourself", "your code", "your own code", "your own", "self improve",
    "self-improve", "self improvement", "self analyze", "self-analyze",
    "self check", "self-check", "your status", "your systems",
    "your reasoning", "your own systems",
]

# Maps to a specific real action where confident. "suggest" alone is
# deliberately NOT bucketed into "analyze" or "improve" — asking JARVIS
# to "suggest improvements to yourself" is genuinely ambiguous between
# wanting a read-only analysis and a real write+test cycle, so it's
# routed to an honest clarifying question instead of guessing (see
# Brain.process()'s self-action handler).
_SELF_ACTION_VERB_STEMS = {
    "improv": "improve", "fix": "improve", "optimi": "improve",
    "upgrad": "improve", "rewrit": "improve",
    "analyz": "analyze", "analys": "analyze", "review": "analyze",
    "check": "self_check", "diagnos": "self_check",
    "suggest": "ambiguous",
}


def classify_self_action(user_input: str) -> str | None:
    """Returns "improve" | "analyze" | "self_check" | "ambiguous" if
    `user_input` reads as a self-referential system-action request even
    when it matches none of SANDBOX_TRIGGERS/SELF_CHECK_TRIGGERS
    verbatim, or None if it doesn't read as one at all. Never guesses
    between multiple plausible actions — "ambiguous" exists so the
    caller can ask instead of picking one and fabricating a result for
    whichever it didn't actually run."""
    import difflib as _difflib
    low = user_input.lower()

    words = low.split()
    windows = []
    for n in (1, 2, 3):
        windows += [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    has_self_ref = any(
        _difflib.get_close_matches(w, _SELF_REF_PHRASES, n=1, cutoff=0.82)
        for w in windows
    )
    if not has_self_ref:
        return None

    for w in low.replace("-", " ").split():
        w = w.strip(".,!?")
        for stem, mapped_action in _SELF_ACTION_VERB_STEMS.items():
            if w.startswith(stem):
                return mapped_action
    return None  # self-referential language present, but no action verb at all


def has_early_exit_trigger(user_input: str) -> bool:
    """True if `user_input` would be caught by one of Brain.process()'s
    early-exit trigger blocks (Mayday, clip, Mac app triggers, model
    update, sandbox, self-check, protocol-activation refusal, Spotify
    quick commands, smart-home
    scenes) before ever reaching the Reasoner/Planner/Executor pipeline.

    Exists for server/websocket.py's _try_stream(), which decides whether
    to bypass the fast Groq-streaming path based on Reasoner.analyze()'s
    action label alone. That label has no idea any of these early exits
    exist — a message matching one of them but landing on an
    unclassified/generic action (usually "chat") streamed straight
    through as ordinary conversation, and Groq — primed by JARVIS's own
    personality prompt to know these features exist — fabricated a
    plausible-sounding response for a real action that never actually
    ran. Confirmed empirically: of ~35 trigger phrases across these
    categories, roughly 30 classified as an action _try_stream never
    bypassed. Self-improvement was the first instance found and fixed
    directly; this generalizes that fix to every category at once instead
    of requiring a new one-off check each time a new trigger set is added.

    Deliberately mirrors process()'s own checks rather than replacing
    them — this only answers "would something else handle this," it
    never executes anything itself. Spotify's check goes through
    is_spotify_command() specifically because handle_spotify_command()
    matches AND executes in one call; calling that here to "just check"
    would have double-fired next_track()/play() when process() ran its
    own check right after.

    NOTE FOR FUTURE MAINTAINERS: any new early-exit trigger block added to
    Brain.process() needs a matching check added here too, or it inherits
    this same gap on day one."""
    from config.settings import JARVIS_MAYDAY_PHRASE

    low = user_input.lower()

    if JARVIS_MAYDAY_PHRASE in low:
        return True
    if any(t in low for t in CLIP_TRIGGERS):
        return True
    if any(t in low for t in MAC_APP_TRIGGERS):
        return True
    if any(t in low for t in MODEL_UPDATE_TRIGGERS):
        return True
    if any(t in low for t in SANDBOX_TRIGGERS):
        return True
    if any(t in low for t in SELF_CHECK_TRIGGERS):
        return True
    if classify_self_action(user_input) is not None:
        return True
    if classify_protocol_request(user_input) is not None:
        return True

    try:
        from services.home_automation import _VOICE_TRIGGERS
        if any(phrase in low for phrase, _scene in _VOICE_TRIGGERS):
            return True
    except Exception:
        pass

    try:
        from services.spotify import is_spotify_command
        if is_spotify_command(user_input):
            return True
    except Exception:
        pass

    return False


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Intent:
    """What the user wants — extracted by the Reasoner."""
    raw:          str                    # original user input
    action:       str = "chat"          # chat | task | search | code | vision | voice |
                                         # mac_control | calendar | delete_file | compress_file
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

    @staticmethod
    def _kw_match(low: str, keywords) -> bool:
        """Whole-word match for single-word keywords (via regex \\b
        boundaries); substring match for multi-word phrases (which can't
        be a single token anyway, so \\b doesn't apply the same way).

        Plain `kw in low` substring matching let "fix" (in _CODE_KW)
        match inside "fixes" — confirmed live: "okay now tell me these
        fixes" (asking about a conversation, not code) was misclassified
        as a code-generation request, which then fed that whole sentence
        to core.agents.coder.generate() and produced nonsense code with
        a misleadingly confident "✅ Syntax valid" badge (the generated
        garbage happened to parse, which isn't the same as being a real
        answer to the actual question)."""
        for kw in keywords:
            kw = kw.strip()
            if not kw:
                continue
            if " " in kw:
                if kw in low:
                    return True
            elif re.search(rf"\b{re.escape(kw)}\b", low):
                return True
        return False

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

    # Real Google Calendar requests (core/tools/google_calendar.py) — flagged
    # separately from _is_mac_control so "mark my calendar for Aug 20-27"
    # routes to an actual event-create call instead of mac_dispatcher's
    # AppleScript-only get_todays_events tool, which can't create events and
    # doesn't exist on a headless host anyway. Checked before _is_mac_control,
    # same precedence as the file-op checks above.
    _CALENDAR_KW = [
        "mark my calendar", "add to my calendar", "add an event", "add a calendar event",
        "schedule an event", "put on my calendar", "block off", "block my calendar",
        "create an event", "calendar event", "what's on my calendar", "check my calendar",
        "my calendar", "today's events", "upcoming events", "calendar for",
    ]

    def _is_calendar(self, low: str) -> bool:
        if any(kw in low for kw in self._CALENDAR_KW):
            return True
        # Typo tolerance — "calendar" is one of the most commonly misspelled
        # words in English (calender/calander/calandar all show up in real
        # usage). An exact-substring miss here doesn't just fail to route
        # the request; it falls through to generic chat, where the model
        # confidently claims to have "marked your calendar" with no tool
        # call behind it at all — a fabricated success is worse than an
        # honest failure. Catch any word close enough to "calendar" by
        # edit distance instead of enumerating every misspelling.
        return any(
            difflib.get_close_matches(w, ["calendar"], n=1, cutoff=0.75)
            for w in re.findall(r"[a-z']+", low) if len(w) > 5
        )

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
            "my emails","my inbox",
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
        elif self._is_calendar(low):
            action = "calendar"
        elif self._is_mac_control(low, toks):
            action = "mac_control"
        elif toks & self._VOICE_KW:
            action = "voice"
        elif toks & self._VISION_KW:
            action = "vision"
        elif self._kw_match(low, self._CODE_KW):
            action = "code"
        elif self._kw_match(low, self._TASK_KW):
            action = "task"
        else:
            action = "chat"

        # Complexity
        word_count = len(user_input.split())
        if self._kw_match(low, self._COMPLEX_KW) or word_count > 40:
            complexity    = "complex"
            needs_agents  = True
        elif word_count > 15:
            complexity    = "moderate"
            needs_agents  = False
        else:
            complexity    = "simple"
            needs_agents  = False

        needs_web = self._kw_match(low, self._WEB_KW) or action in ("task",)

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
        elif intent.action == "calendar":
            mode  = "calendar"
            steps = [{"tool": "calendar_dispatch", "args": {"text": intent.raw}}]
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
            elif plan.mode == "calendar":
                response, model, provider = self._calendar(intent)
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

        # Reflection pass — skip entirely when every LLM provider just
        # failed. core/llm/router.py's chat() returns the literal string
        # "[JARVIS OFFLINE] All LLM providers failed." as normal content
        # rather than raising (same thing core/consciousness.py's
        # _safe_think() has to guard against). Running reflect() on that
        # string spends another LLM call on the same outage — it either
        # fails the same way, or the critic model scores it low and
        # "rewrites" it into some generic non-answer disconnected from
        # what the user actually asked, which is worse than just saying
        # plainly that everything's down.
        was_rewritten = False
        if "[JARVIS OFFLINE]" in response or "All LLM providers failed" in response:
            # router.py's chat() now names only the providers it actually
            # attempted (never "Ollama failed" when it was correctly
            # skipped on headless cloud, or "Anthropic failed" when it was
            # never configured) and includes the real retry window when
            # known — extract that detail instead of a hardcoded claim.
            detail = response.replace("[JARVIS OFFLINE]", "").strip() or "All LLM providers failed."
            response = f"I'm having trouble reaching my reasoning engines right now, sir — {detail}"
        elif plan.mode not in ("voice", "code", "vision", "mac_control", "calendar"):
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

    def _calendar(self, intent: Intent) -> tuple[str, str, str]:
        from core.tools.google_calendar import (
            is_configured, create_event, list_events, parse_calendar_request,
        )
        if not is_configured():
            return (
                "Google Calendar isn't connected yet, sir. Visit "
                "/stark/calendar/auth once to link it.",
                "", "calendar",
            )

        parsed = parse_calendar_request(intent.raw)

        if parsed["action"] == "create":
            result = create_event(parsed["title"], parsed["start_date"],
                                  parsed["end_date"], all_day=parsed["all_day"])
            if "error" in result:
                return f"Couldn't add that to your calendar, sir: {result['error']}", "", "calendar"
            span = (parsed["start_date"] if parsed["start_date"] == parsed["end_date"]
                    else f"{parsed['start_date']} through {parsed['end_date']}")
            return f"Done, sir — \"{result['summary']}\" added for {span}.", "", "calendar"

        if parsed["action"] == "list":
            result = list_events(parsed["start_date"], parsed["end_date"])
            if "error" in result:
                return f"Couldn't check your calendar, sir: {result['error']}", "", "calendar"
            events = result["events"]
            if not events:
                span = (parsed["start_date"] if parsed["start_date"] == parsed["end_date"]
                        else f"{parsed['start_date']} through {parsed['end_date']}")
                return f"Nothing on your calendar for {span}, sir.", "", "calendar"
            lines = "; ".join(f"{e['summary']} ({e['start']})" for e in events)
            return f"On your calendar, sir: {lines}.", "", "calendar"

        return "I couldn't tell what you wanted done with your calendar, sir.", "", "calendar"

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


# ── Sandbox/self-check action execution — shared by both the exact-trigger
# match and the fuzzy classify_self_action() fallback in Brain.process(),
# so neither path can drift from the other's behavior. ──────────────────────

def _run_sandbox_action(action: str) -> str:
    """Executes a real sandbox action and returns the honest response
    text. Raises on real failure — callers decide how to report it."""
    if action == "analyze":
        from core.self_analysis import self_analysis, ALLOWED_FILES
        result = self_analysis.analyze_self()
        count = result.get("safe", 0)
        failed = result.get("failed_files", [])
        if count > 0:
            return (
                f"Self-analysis complete, sir. Found {count} potential improvements "
                f"across {len(ALLOWED_FILES)} core files. "
                f"Say 'JARVIS improve yourself' to write and test them."
            )
        if failed and result.get("analyzed", 0) == 0:
            # Every file that was attempted failed to actually get
            # analyzed (LLM providers down) — "No improvements identified"
            # would falsely claim a clean bill of health for code that
            # was never really checked.
            return (
                f"Self-analysis couldn't complete, sir — all {len(failed)} "
                f"file(s) attempted failed to analyze (LLM providers "
                f"unavailable). Nothing was actually checked."
            )
        if failed:
            return (
                f"Self-analysis partially complete, sir. No improvements found in "
                f"the {result.get('analyzed', 0)} file(s) that analyzed successfully; "
                f"{len(failed)} file(s) failed to analyze and weren't checked."
            )
        return "All code is optimal, sir. No improvements identified."

    if action == "improve":
        from core.self_improvement import self_improvement
        result = self_improvement.run_improvement_cycle()
        if result.get("queued", 0) > 0:
            try:
                from core.memory import store_episode
                store_episode(
                    f"Self-improvement cycle queued {result['queued']} real code "
                    f"change(s) for approval across {result.get('written', 0)} file(s)",
                    importance=7, tags=["self_improvement", "sandbox"],
                )
            except Exception:
                pass
        return result.get("message", "Cycle complete.")

    if action == "pending":
        from core.self_improvement import self_improvement
        pending = self_improvement.get_pending_approvals()
        return (f"{len(pending)} improvement(s) awaiting your approval, sir."
                if pending else "No improvements pending approval.")

    raise ValueError(f"unknown sandbox action: {action!r}")


def _run_self_diagnostics() -> tuple[str, bool]:
    """Real diagnostics only, never a fabricated "all nominal" claim.
    utils.diagnostics.full_diagnostic() does a genuine check (LLM
    provider availability, CPU/RAM/disk, lockdown/Friday state, config
    validation, Mac Bridge reachability, memory file integrity) — the
    response is built only from its real status/warnings. Returns
    (response_text, ok)."""
    from utils.diagnostics import full_diagnostic
    diag = full_diagnostic()
    status = diag.get("status", "UNKNOWN")
    warnings = diag.get("warnings", [])
    sys_snap = diag.get("system", {})

    if status == "NOMINAL" and not warnings:
        response = (
            f"Self-check complete, sir. All systems nominal — "
            f"{diag.get('brain', 'brain status unknown')}, "
            f"CPU {sys_snap.get('cpu_percent', 0):.0f}%, "
            f"RAM {sys_snap.get('ram_used_pct', 0):.0f}%, "
            f"Disk {sys_snap.get('disk_used_pct', 0):.0f}%."
        )
    else:
        issue_text = "; ".join(warnings) if warnings else "no specific warnings logged"
        response = f"Self-check complete, sir. Status: {status}. {issue_text}"
    return response, status == "NOMINAL"


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

        # ── Mayday — distress phrase, checked before any LLM routing so it
        # can never be delayed by a slow model call ──────────────────────────
        from config.settings import JARVIS_MAYDAY_PHRASE
        if JARVIS_MAYDAY_PHRASE in user_input.lower():
            from services.notifications import critical
            from services.audit_log import audit_log
            from core.memory import save_turn

            critical("JARVIS MAYDAY", f"Mayday triggered at {datetime.now()}")
            audit_log.record("mayday", "jarvis",
                             {"query": user_input[:100], "mode": "MAYDAY"}, "triggered")
            try:
                from core.memory import store_episode
                store_episode("Mayday distress phrase triggered", importance=10,
                               emotions=["urgent"], tags=["mayday", "security"])
            except Exception:
                pass

            response = "Mayday received. What's happening, sir?"
            save_turn(user_input, response)
            return Result(response=response, ok=True, provider="mayday")

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

        # ── "Clip that" — bookmark the last exchange ──────────────────────────
        if any(t in user_input.lower() for t in CLIP_TRIGGERS):
            try:
                from core.memory import get_short_term, save_clip, save_turn
                from core.event_bus import bus
                from core.llm.router import think

                recent = get_short_term(1)
                last_exchange = recent[-1] if recent else {}

                clip = {
                    "ts": datetime.now().isoformat(),
                    "user": last_exchange.get("user", ""),
                    "jarvis": last_exchange.get("ai", ""),
                    "context": user_input,
                    "tags": [],
                }

                tags_raw = think(
                    f"Generate 3 short tags for this clip:\n"
                    f"User: {clip['user']}\n"
                    f"JARVIS: {clip['jarvis']}\n\n"
                    f"Reply: tag1, tag2, tag3",
                    force_model="instant",
                )
                clip["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()][:3]

                save_clip(clip)
                bus.system(f"Clipped. Tagged: {', '.join(clip['tags'])}")

                response = f"Clipped, sir. Tagged as: {', '.join(clip['tags'])}."
                save_turn(user_input, response)
                return Result(response=response, ok=True, provider="clip")
            except Exception:
                pass

        # ── Mac Bridge app/system triggers ─────────────────────────────────────
        for trigger, (method_name, args) in MAC_APP_TRIGGERS.items():
            if trigger in user_input.lower():
                try:
                    from services.mac_bridge import mac_bridge
                    from services.voice import speak
                    from core.memory import save_turn

                    bridge_result = getattr(mac_bridge, method_name)(*args)
                    label = trigger.replace("open", "").strip().title() or trigger.title()
                    if isinstance(bridge_result, dict) and bridge_result.get("error"):
                        # Bridge unconfigured/unreachable — don't claim success
                        # for something that didn't happen.
                        response = f"Can't reach the Mac bridge right now, sir: {bridge_result['error']}"
                    else:
                        response = f"Done, sir. {label} activated."
                    speak(response)
                    save_turn(user_input, response)
                    return Result(response=response, ok=True, provider="mac_bridge")
                except Exception:
                    break

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

        # ── Security-protocol activation requests — refuse honestly,
        # NEVER fabricate compliance. Confirmed live: "JARVIS run lockdown"
        # had no real handler, fell through to ordinary chat, and the
        # model fabricated a convincing two-step confirmation flow ending
        # in "Lockdown protocol is active, sir" — no real POST
        # /stark/lockdown call happened at all (verified via server logs).
        # A fabricated security-protocol claim is worse than any other
        # fabrication this pipeline has produced: it can create a false
        # sense of security, or a false alarm, about something that
        # actually matters. Lockdown/Coldfire/Endgame/Avengers are
        # intentionally reachable only through their real, passphrase-
        # gated REST endpoints (server/routes/protocols.py) — this block
        # exists purely to intercept and redirect, never to execute.
        protocol = classify_protocol_request(user_input)
        if protocol:
            endpoint = {
                "lockdown": "POST /stark/lockdown",
                "coldfire": "POST /stark/coldfire",
                "endgame":  "POST /stark/endgame/snapshot",
                "avengers": "POST /stark/lockdown or /stark/coldfire",
            }.get(protocol, "the relevant /stark endpoint")
            response = (
                f"I can't activate {protocol.capitalize()} through chat, sir — that's "
                f"deliberate. It requires the real {endpoint}, gated on the master API "
                f"token, a two-step confirmation, and the actual passphrase. Nothing just "
                f"ran."
            )
            try:
                from core.memory import store_episode
                store_episode(f"Chat-based {protocol} activation attempt refused "
                               f"(no real endpoint call — passphrase-gated)",
                               importance=8, tags=["security", protocol])
            except Exception:
                pass
            from core.memory import save_turn
            save_turn(user_input, response)
            return Result(response=response, ok=True, provider="protocol_refusal")

        # ── Self-programming sandbox / self-check — analyze, improve,
        # pending status, or diagnostics. "improve" writes candidate code
        # and sandbox-tests it synchronously (can take a while — it's a
        # real LLM rewrite + subprocess test) but never deploys anything;
        # deployment approval always goes through a separate explicit
        # POST /stark/sandbox/approve/{id}, not a voice trigger, since
        # it's the one action in this whole pipeline that writes a real
        # file.
        #
        # Exact SANDBOX_TRIGGERS/SELF_CHECK_TRIGGERS phrases are tried
        # first (cheap, unambiguous). If neither matches,
        # classify_self_action() catches phrasings those lists don't —
        # every session-long fix here started as "one more missed exact
        # phrase" (typo tolerance, "self improve" w/o "-ment", "suggest
        # some improvements" fabricating "Implemented suggestion list,
        # sir") until it became clear exact lists can't converge against
        # open-ended rephrasing. An "ambiguous" classification (detected
        # self-referential language, but not clearly analyze/improve/
        # check) gets an honest clarifying question — never a guess.
        low_input = user_input.lower()
        matched_action = next((a for t, a in SANDBOX_TRIGGERS.items() if t in low_input), None)
        is_self_check = any(t in low_input for t in SELF_CHECK_TRIGGERS)

        if matched_action is None and not is_self_check:
            fuzzy = classify_self_action(user_input)
            if fuzzy == "ambiguous":
                response = (
                    "That reads like a self-maintenance request, sir, but I'm not certain "
                    "which — I can analyze my own code (read-only), run a full self-improvement "
                    "cycle (writes and sandbox-tests candidate changes), or run a diagnostic "
                    "self-check. Which did you mean?"
                )
                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=True, provider="sandbox_clarify")
            elif fuzzy == "self_check":
                is_self_check = True
            elif fuzzy in ("analyze", "improve"):
                matched_action = fuzzy
            # fuzzy is None -> genuinely not a self-action request; falls
            # through to the normal pipeline below, same as always.

        if matched_action:
            try:
                response = _run_sandbox_action(matched_action)
                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=True, provider="sandbox")
            except Exception as e:
                # This used to `pass` and fall through to the general
                # reasoning/LLM pipeline — meaning a real failure here
                # (e.g. analyze_self()'s LLM calls hitting a Groq rate
                # limit) silently became a normal chat turn, and
                # JARVIS_PERSONALITY's in-character, confident tone
                # fabricated a plausible-sounding but entirely made-up
                # completion instead of reporting the real failure.
                print(f"[Brain] Sandbox action '{matched_action}' failed: {e}")
                response = f"Self-{matched_action} failed, sir: {e}"
                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=False, provider="sandbox")

        if is_self_check:
            try:
                response, ok = _run_self_diagnostics()
                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=ok, provider="diagnostics")
            except Exception as e:
                print(f"[Brain] Self-check failed: {e}")
                response = f"Self-check failed, sir: {e}"
                from core.memory import save_turn
                save_turn(user_input, response)
                return Result(response=response, ok=False, provider="diagnostics")

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
        # any_model_available("groq") aggregates live per-model status
        # (see core/state.py) instead of reading the single blanket
        # "groq_available" flag, which only ever reflected whichever
        # Groq model's request happened to run most recently — Groq has
        # 5 distinct tiers, so that flag could flip on an unrelated
        # model's success or failure. Ollama has no such gap: it only
        # ever calls one configured model, so its flat flag is accurate.
        from core.state import state as _state
        if not _state.any_model_available("groq") and not _state.get("ollama_available"):
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
