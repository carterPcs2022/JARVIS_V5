"""
core/personality.py — JARVIS adaptive personality.
Tracks user communication style and adapts tone, verbosity, and vocabulary.
"""
import re
from datetime import datetime
from collections import Counter
from core.memory import get_profile, update_profile
from core.state import state

VOICE_MODES = {
    "normal":   "Default JARVIS — witty, helpful, complete.",
    "brief":    "Ultra-short. Clipped. No pleasantries. One sentence when possible.",
    "combat":   "Fast, urgent, highest-priority only. Skip all pleasantries. Direct commands.",
    "workshop": "Verbose, technical, deep analysis mode. Full detail welcome.",
    "social":   "Warm, casual, minimal tech jargon. Others may be listening.",
    "stealth":  "Text only. No voice output implied. Keep it low-key.",
    "night":    "Whispered tone. Minimal words. Dim, quiet energy — it's late.",
}


def get_voice_mode() -> str:
    mode = state.get("voice_mode")
    if mode:
        return mode
    hour = datetime.now().hour
    if hour >= 23 or hour < 7:
        return "night"
    return "normal"


def set_voice_mode(mode: str) -> str:
    mode = mode.lower().strip()
    if mode not in VOICE_MODES:
        mode = "normal"
    state.set("voice_mode", mode)
    return mode

_CASUAL    = {"lol","lmao","bruh","yo","gonna","wanna","kinda","dude","yeah","nah","tbh","imo","haha"}
_ADVANCED  = {"algorithm","asynchronous","concurrency","heuristic","polymorphism",
               "recursion","entropy","paradigm","latency","throughput","inference","deterministic"}
_HUMOR     = {"lol","lmao","haha","hehe","funny","joke","rofl","jk","kidding","hilarious"}
_TECH      = {"code","python","api","server","database","docker","linux","security",
               "network","ai","model","llm","terminal","bash","script","deploy"}


def analyze_message(user_msg: str):
    """Update personality profile based on a user message."""
    tokens  = set(re.findall(r"[a-z]+", user_msg.lower()))
    profile = get_profile()

    profile.setdefault("interaction_count", 0)
    profile["interaction_count"] += 1

    # Formality
    if tokens & _CASUAL:
        profile["formality"] = "casual"
    elif len(tokens & _ADVANCED) >= 2:
        profile["formality"] = "technical"
    else:
        profile.setdefault("formality", "professional")

    # Humor
    if tokens & _HUMOR:
        profile["humor"] = True
    else:
        profile.setdefault("humor", False)

    # Verbosity
    wc = len(user_msg.split())
    if wc > 60:
        profile["verbosity"] = "detailed"
    elif wc < 8:
        profile["verbosity"] = "brief"
    else:
        profile.setdefault("verbosity", "balanced")

    # Vocab complexity
    adv = len(tokens & _ADVANCED)
    cas = len(tokens & _CASUAL)
    if adv >= 3:
        profile["vocab"] = "advanced"
    elif cas >= 2:
        profile["vocab"] = "simple"
    else:
        profile.setdefault("vocab", "medium")

    # Topics
    profile.setdefault("topic_counts", {})
    for w in tokens & _TECH:
        profile["topic_counts"][w] = profile["topic_counts"].get(w, 0) + 1
    tc = Counter(profile["topic_counts"])
    profile["topics"] = [t for t, _ in tc.most_common(5)]

    # Name detection
    m = re.search(r"(?:call me|my name is|i'm|i am)\s+([A-Z][a-z]+)", user_msg)
    if m:
        profile["preferred_name"] = m.group(1)

    update_profile(profile)


def build_system_prompt(base: str) -> str:
    """Inject personality adaptations into the base system prompt."""
    profile = get_profile()
    if not profile:
        return base

    additions = []
    formality = profile.get("formality", "professional")
    verbosity = profile.get("verbosity", "balanced")

    if formality == "casual":
        additions.append("Be conversational and relaxed — match the user's casual energy.")
    elif formality == "technical":
        additions.append("The user is technically fluent. Use precise language, skip basics.")

    if verbosity == "brief":
        additions.append("Keep responses SHORT. One paragraph max unless complexity demands more.")
    elif verbosity == "detailed":
        additions.append("The user appreciates thorough, detailed responses. Go deep.")

    if profile.get("humor"):
        additions.append("Light wit is welcome — the user has a sense of humor.")

    if profile.get("vocab") == "advanced":
        additions.append("Use sophisticated vocabulary freely.")

    name = profile.get("preferred_name")
    if name:
        additions.append(f"Address the user as '{name}'.")

    topics = profile.get("topics", [])
    if topics:
        additions.append(f"User's main interests: {', '.join(topics)}.")

    mode = get_voice_mode()
    if mode != "normal":
        additions.append(f"VOICE MODE ({mode.upper()}): {VOICE_MODES[mode]}")

    if not additions:
        return base

    return base + "\n\nUSER ADAPTATIONS:\n" + "\n".join(f"- {a}" for a in additions)


def calibrate_expertise(topic: str) -> str:
    """What's the user's expertise level on this topic, based on past
    conversations? Returns: beginner / intermediate / expert."""
    from core.llm.router import think
    from core.memory import recall_facts

    facts = recall_facts(topic, k=5)
    conversation_history = (
        "\n".join(f["fact"] for f in facts) if facts
        else "No prior conversations on this topic."
    )

    result = think(
        f"Based on past conversations, assess the user's expertise level "
        f"on '{topic}'.\n"
        f"History: {conversation_history}\n"
        f"Reply: beginner, intermediate, or expert",
        force_model="instant",
    )
    return result.strip().lower()
