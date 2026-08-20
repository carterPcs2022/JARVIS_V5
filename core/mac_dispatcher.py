"""
core/mac_dispatcher.py — Natural-language → macOS tool call dispatcher.

The LLM reads the user's command and picks the right tool + args.
This lets JARVIS handle anything: "open Spotify", "check my email",
"skip this song", "set volume to 40", etc.
"""
import json, re
from config.settings import JARVIS_PERSONALITY

# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    # App control
    "open_app":         {"desc": "Open any macOS app by name", "args": ["name"]},
    "quit_app":         {"desc": "Quit/close a running app", "args": ["name"]},
    "focus_app":        {"desc": "Bring an app to the foreground", "args": ["name"]},
    "list_running_apps":{"desc": "List all currently running apps", "args": []},

    # System
    "set_volume":       {"desc": "Set system volume 0-100", "args": ["level"]},
    "get_volume":       {"desc": "Get current system volume", "args": []},
    "mute":             {"desc": "Mute system audio", "args": []},
    "unmute":           {"desc": "Unmute system audio", "args": []},
    "take_screenshot":  {"desc": "Take a screenshot", "args": []},
    "lock_screen":      {"desc": "Lock the screen", "args": []},
    "empty_trash":      {"desc": "Empty the Trash", "args": []},
    "get_clipboard":    {"desc": "Read the clipboard contents", "args": []},
    "set_clipboard":    {"desc": "Set clipboard to a value", "args": ["text"]},
    "notify":           {"desc": "Show a macOS notification", "args": ["title", "message"]},
    "open_url":         {"desc": "Open a URL in the default browser", "args": ["url"]},
    "get_todays_events":{"desc": "Get today's Calendar events", "args": []},
    "create_reminder":  {"desc": "Create a Reminder", "args": ["title", "due_in_minutes"]},

    # Spotify
    "spotify_play":     {"desc": "Start/resume Spotify playback", "args": []},
    "spotify_pause":    {"desc": "Pause Spotify", "args": []},
    "spotify_play_pause":{"desc":"Toggle play/pause on Spotify", "args": []},
    "spotify_next":     {"desc": "Skip to next track on Spotify", "args": []},
    "spotify_prev":     {"desc": "Go to previous track on Spotify", "args": []},
    "spotify_volume":   {"desc": "Set Spotify volume 0-100", "args": ["level"]},
    "spotify_current":  {"desc": "Get currently playing Spotify track", "args": []},
    "spotify_search":   {"desc": "Search and play a song/artist on Spotify", "args": ["query"]},

    # Gmail
    "gmail_inbox":      {"desc": "Check Gmail inbox (unread emails)", "args": []},
    "gmail_search":     {"desc": "Search Gmail", "args": ["query"]},
    "gmail_send":       {"desc": "Draft an email for review — NEVER sends immediately, "
                                  "only creates a pending draft the user must separately confirm",
                          "args": ["to", "subject", "body"]},
    "gmail_confirm_send": {"desc": "Confirm and actually send the currently pending email draft",
                            "args": []},
    "gmail_discard_draft": {"desc": "Cancel/discard the currently pending email draft without sending",
                             "args": []},
    "gmail_unread_count":{"desc":"Get number of unread Gmail messages", "args": []},

    # Disambiguation — use ONLY when the command is genuinely ambiguous
    # between real, distinct options (e.g. which of several named scenes
    # was meant). Never use this for routine clarifying questions, and
    # never when there's enough information to just act — guessing
    # reasonably and letting the user correct you is almost always
    # better than stopping to ask.
    "ask_user_choice":  {"desc": "Ask the user to pick between 2-4 short options when a command is "
                                  "genuinely ambiguous between real choices — not for questions you "
                                  "could just answer or a command you could reasonably act on directly",
                          "args": ["question", "options", "allow_multiple"]},

    # Fallback
    "chat":             {"desc": "No tool matches — answer conversationally", "args": ["response"]},
}

_TOOL_LIST = "\n".join(
    f'  "{k}": {v["desc"]}  args={v["args"]}'
    for k, v in TOOLS.items()
)

_SYSTEM = (
    JARVIS_PERSONALITY + "\n\n"
    "You are also JARVIS's Mac control dispatcher. "
    "When given a user command, select the best tool and return ONLY valid JSON "
    "with keys 'tool' and 'args'. No explanation, no markdown, just raw JSON.\n\n"
    "Available tools:\n" + _TOOL_LIST
)

_EXAMPLE = """Examples:
  "open Spotify"           → {"tool":"open_app","args":{"name":"Spotify"}}
  "check my email"         → {"tool":"gmail_inbox","args":{}}
  "skip this song"         → {"tool":"spotify_next","args":{}}
  "set volume to 40"       → {"tool":"set_volume","args":{"level":40}}
  "what's playing"         → {"tool":"spotify_current","args":{}}
  "send an email to bob@x.com saying hello" → {"tool":"gmail_send","args":{"to":"bob@x.com","subject":"Hello","body":"Hello"}}
  "send it" / "yes send it" / "confirm" (referring to a just-drafted email) → {"tool":"gmail_confirm_send","args":{}}
  "cancel that email" / "don't send it" / "discard the draft" → {"tool":"gmail_discard_draft","args":{}}
  "remind me to call mom in 30 minutes" → {"tool":"create_reminder","args":{"title":"Call mom","due_in_minutes":30}}
  "take a screenshot"      → {"tool":"take_screenshot","args":{}}
  "turn on the mood lighting" (ambiguous between several real named scenes) →
      {"tool":"ask_user_choice","args":{"question":"Which scene did you mean?","options":["Movie","Focus","Reading","Night"]}}
"""


def _llm_parse(command: str) -> dict:
    """Ask the LLM to map the user command to a tool call."""
    from core.llm.router import chat as llm_chat
    messages = [
        {"role": "system", "content": _SYSTEM + "\n\n" + _EXAMPLE},
        {"role": "user",   "content": f"Command: {command}\n\nJSON:"},
    ]
    raw = llm_chat(messages, max_tokens=200, temperature=0.1)["content"].strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    return json.loads(raw)


def _fallback_parse(command: str) -> dict:
    """Rule-based fallback if LLM parse fails."""
    low = command.lower()

    # Spotify
    if any(w in low for w in ("skip","next song","next track")):
        return {"tool": "spotify_next", "args": {}}
    if any(w in low for w in ("previous","prev song","last track")):
        return {"tool": "spotify_prev", "args": {}}
    if "pause" in low and "spotify" in low:
        return {"tool": "spotify_pause", "args": {}}
    if any(w in low for w in ("play","resume")) and "spotify" in low:
        return {"tool": "spotify_play", "args": {}}
    if "what's playing" in low or "now playing" in low or "current song" in low:
        return {"tool": "spotify_current", "args": {}}
    if "mute" in low and "spotify" not in low:
        return {"tool": "mute", "args": {}}
    if "unmute" in low:
        return {"tool": "unmute", "args": {}}

    # Volume
    m = re.search(r"volume\s+(?:to\s+)?(\d+)", low)
    if m:
        return {"tool": "set_volume", "args": {"level": int(m.group(1))}}
    if "turn up" in low:
        return {"tool": "set_volume", "args": {"level": 70}}
    if "turn down" in low:
        return {"tool": "set_volume", "args": {"level": 30}}

    # Open app
    m = re.search(r"(?:open|launch|start)\s+(.+)", low)
    if m:
        return {"tool": "open_app", "args": {"name": m.group(1).strip().title()}}

    # Close/quit
    m = re.search(r"(?:close|quit)\s+(.+)", low)
    if m:
        return {"tool": "quit_app", "args": {"name": m.group(1).strip().title()}}

    # Gmail
    if any(w in low for w in ("email","gmail","inbox","unread")):
        return {"tool": "gmail_inbox", "args": {}}

    # Screenshot
    if "screenshot" in low:
        return {"tool": "take_screenshot", "args": {}}

    # Calendar
    if any(w in low for w in ("calendar","events","schedule","today")):
        return {"tool": "get_todays_events", "args": {}}

    return {"tool": "chat", "args": {"response": f"I'm not sure how to handle: {command}"}}


# ── Tool executor ─────────────────────────────────────────────────────────────

def _execute_tool(tool: str, args: dict) -> str:
    from core.tools import mac, spotify, gmail as gm

    try:
        # ── App control ───────────────────────────────────────────────────────
        if tool == "open_app":
            r = mac.open_app(args.get("name", ""))
            return r["message"]

        elif tool == "quit_app":
            r = mac.quit_app(args.get("name", ""))
            return r["message"]

        elif tool == "focus_app":
            r = mac.focus_app(args.get("name", ""))
            return r["message"]

        elif tool == "list_running_apps":
            apps = mac.list_running_apps()
            return f"Running apps: {', '.join(apps)}" if apps else "No apps detected."

        # ── System ────────────────────────────────────────────────────────────
        elif tool == "set_volume":
            r = mac.set_volume(args.get("level", 50))
            return r["message"]

        elif tool == "get_volume":
            v = mac.get_volume()
            return f"Current volume: {v}%"

        elif tool == "mute":
            return mac.mute()["message"]

        elif tool == "unmute":
            return mac.unmute()["message"]

        elif tool == "take_screenshot":
            import datetime
            path = f"/tmp/jarvis_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            r = mac.take_screenshot(path)
            return f"Screenshot saved to {r['path']}" if r["ok"] else r["message"]

        elif tool == "lock_screen":
            return mac.lock_screen()["message"]

        elif tool == "empty_trash":
            return mac.empty_trash()["message"]

        elif tool == "get_clipboard":
            c = mac.get_clipboard()
            return f"Clipboard: {c[:500]}"

        elif tool == "set_clipboard":
            return mac.set_clipboard(args.get("text", ""))["message"]

        elif tool == "notify":
            return mac.notify(args.get("title","JARVIS"), args.get("message",""))["message"]

        elif tool == "open_url":
            return mac.open_url(args.get("url",""))["message"]

        elif tool == "get_todays_events":
            events = mac.get_todays_events()
            if not events:
                return "No events on your calendar today."
            return "Today's events:\n" + "\n".join(f"• {e['event']}" for e in events)

        elif tool == "create_reminder":
            return mac.create_reminder(
                args.get("title", "Reminder"),
                int(args.get("due_in_minutes", 60))
            )["message"]

        # ── Spotify ───────────────────────────────────────────────────────────
        elif tool == "spotify_play":
            return spotify.play()["message"]

        elif tool == "spotify_pause":
            return spotify.pause()["message"]

        elif tool == "spotify_play_pause":
            return spotify.play_pause()["message"]

        elif tool == "spotify_next":
            r = spotify.next_track()
            return r.get("message", "Skipped track")

        elif tool == "spotify_prev":
            r = spotify.prev_track()
            return r.get("message", "Previous track")

        elif tool == "spotify_volume":
            return spotify.set_volume(args.get("level", 50))["message"]

        elif tool == "spotify_current":
            r = spotify.current_track()
            return r.get("message", "Nothing playing")

        elif tool == "spotify_search":
            return spotify.search_and_play(args.get("query", ""))["message"]

        # ── Gmail ─────────────────────────────────────────────────────────────
        elif tool == "gmail_inbox":
            if not gm.is_configured():
                return ("Gmail isn't set up yet. Place your Google OAuth credentials at "
                        "config/gmail_credentials.json — see the setup guide in core/tools/gmail.py")
            emails = gm.check_inbox(max_results=5)
            if not emails:
                return "Your inbox is empty — no unread messages."
            if "error" in emails[0]:
                return f"Gmail error: {emails[0]['error']}"
            lines = [f"You have {len(emails)} unread email(s):"]
            for e in emails:
                lines.append(f"  • From: {e['from'][:40]}  |  {e['subject'][:60]}")
                if e.get("snippet"):
                    lines.append(f"    {e['snippet'][:100]}")
            return "\n".join(lines)

        elif tool == "gmail_search":
            if not gm.is_configured():
                return "Gmail not configured. See core/tools/gmail.py for setup."
            emails = gm.search_emails(args.get("query",""), max_results=5)
            if not emails or "error" in emails[0]:
                return "No results found."
            lines = [f"Found {len(emails)} email(s):"]
            for e in emails:
                lines.append(f"  • {e['from'][:40]} — {e['subject'][:60]}")
            return "\n".join(lines)

        elif tool == "gmail_send":
            # Draft-then-confirm only, non-negotiable — this used to call
            # gm.send_email() immediately, meaning "send an email to X
            # saying Y" sent for real with zero confirmation the instant
            # the LLM parser matched this tool. Creates a pending draft
            # and reads it back instead; nothing here ever sends.
            from core.tools import gmail_send
            if not gmail_send.is_configured():
                return "Gmail sending isn't set up yet — needs gmail.send added to the Google OAuth consent (see server/routes/calendar_auth.py)."
            draft = gmail_send.draft_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
            return (f"Here's the draft, sir — to {draft['to']}, subject \"{draft['subject']}\": "
                    f"\"{draft['body']}\". Say \"send it\" to send, or \"cancel\" to discard.")

        elif tool == "gmail_confirm_send":
            from core.tools import gmail_send
            r = gmail_send.send_pending_draft()
            return r["message"]

        elif tool == "gmail_discard_draft":
            from core.tools import gmail_send
            discarded = gmail_send.discard_pending_draft()
            return "Draft discarded." if discarded else "There's no pending draft to discard."

        elif tool == "gmail_unread_count":
            if not gm.is_configured():
                return "Gmail not configured."
            count = gm.get_unread_count()
            return f"You have {count} unread email(s) in your inbox."

        # ── Disambiguation ────────────────────────────────────────────────────
        elif tool == "ask_user_choice":
            from core.ask_user_choice import format_fallback_text, propose
            question = {
                "question": args.get("question", ""),
                "options": args.get("options", []),
                "allow_multiple": bool(args.get("allow_multiple", False)),
            }
            pending = propose([question])
            if pending is None:
                # Validation dropped it (e.g. fewer than 2 real options) —
                # degrade to just asking conversationally rather than
                # silently doing nothing.
                return args.get("question", "Which did you mean?")
            return format_fallback_text(pending)

        # ── Fallback ──────────────────────────────────────────────────────────
        elif tool == "chat":
            return args.get("response", "I'm not sure what you'd like me to do.")

        else:
            return f"Unknown tool: {tool}"

    except Exception as e:
        return f"Tool '{tool}' failed: {e}"


# ── Public entry point ────────────────────────────────────────────────────────

def dispatch(command: str) -> str:
    """Parse a natural-language command and execute the right macOS tool."""
    # Try LLM parse first
    try:
        parsed = _llm_parse(command)
        tool   = parsed.get("tool", "chat")
        args   = parsed.get("args", {})
    except Exception as e:
        print(f"[MacDispatcher] LLM parse failed ({e}), using fallback")
        parsed = _fallback_parse(command)
        tool   = parsed["tool"]
        args   = parsed["args"]

    print(f"[MacDispatcher] → {tool}({args})")
    result = _execute_tool(tool, args)

    # Wrap plain result in a JARVIS-style sentence if it's just a status
    if len(result) < 80 and not result.startswith(("You have","Today","Found","Running","Clipboard")):
        return f"Done, sir. {result}"
    return result
