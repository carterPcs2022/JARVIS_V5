"""tests/test_mac_dispatcher.py — macOS dispatcher confirmation flows."""
from unittest import mock
import core.mac_dispatcher as md


def _fake_llm_parse_factory(mapping: dict):
    def fake(command: str) -> dict:
        low = command.lower()
        for key, parsed in mapping.items():
            if key in low:
                return parsed
        return {"tool": "chat", "args": {"response": command}}
    return fake


def _reset_confirmation_state():
    from core.interfaces import permissions
    md._last_pending_id = None
    for pending_id in list(permissions._PENDING):
        permissions.discard(pending_id)


def test_routine_tool_executes_immediately():
    _reset_confirmation_state()
    fake_parse = _fake_llm_parse_factory({"spotify": {"tool": "open_app", "args": {"name": "Spotify"}}})
    with mock.patch.object(md, "_llm_parse", side_effect=fake_parse), \
         mock.patch("core.tools.mac.open_app", return_value={"ok": True, "message": "Opened Spotify"}):
        result = md.dispatch("open Spotify")
        assert "Spotify" in result


def test_empty_trash_proposes_without_executing_then_confirms():
    _reset_confirmation_state()
    fake_parse = _fake_llm_parse_factory({
        "empty": {"tool": "empty_trash", "args": {}},
    })
    with mock.patch.object(md, "_llm_parse", side_effect=fake_parse), \
         mock.patch("core.tools.mac.empty_trash") as mock_empty:
        proposal = md.dispatch("empty the trash")
        mock_empty.assert_not_called()
        assert "confirm" in proposal.lower()

        mock_empty.return_value = {"ok": True, "message": "Trash emptied"}
        result = md.dispatch("confirm")
        mock_empty.assert_called_once()
        assert "Trash emptied" in result


def test_unrelated_followup_discards_pending_action():
    _reset_confirmation_state()
    fake_parse = _fake_llm_parse_factory({
        "empty": {"tool": "empty_trash", "args": {}},
        "safari": {"tool": "open_app", "args": {"name": "Safari"}},
    })
    with mock.patch.object(md, "_llm_parse", side_effect=fake_parse), \
         mock.patch("core.tools.mac.empty_trash") as mock_empty, \
         mock.patch("core.tools.mac.open_app", return_value={"ok": True, "message": "Opened Safari"}):
        md.dispatch("empty the trash")
        result = md.dispatch("open safari")
        mock_empty.assert_not_called()
        assert "Safari" in result


def test_gmail_send_not_double_gated_by_generic_confirmation():
    """Gmail's own draft-then-confirm flow is separate from the generic
    macOS confirmation gate and must not inherit stale dispatcher state."""
    _reset_confirmation_state()
    fake_parse = _fake_llm_parse_factory({
        "send an email": {"tool": "gmail_send", "args": {"to": "bob@x.com", "subject": "Hi", "body": "Hello"}},
        "send it": {"tool": "gmail_confirm_send", "args": {}},
    })
    with mock.patch.object(md, "_llm_parse", side_effect=fake_parse), \
         mock.patch("core.tools.gmail_send.is_configured", return_value=True), \
         mock.patch("core.tools.gmail_send.draft_email",
                    return_value={"id": "abc", "to": "bob@x.com", "subject": "Hi", "body": "Hello"}) as mock_draft:
        result = md.dispatch("send an email to bob@x.com saying hello")
        mock_draft.assert_called_once()
        assert "draft" in result.lower()
        assert md._last_pending_id is None

    with mock.patch.object(md, "_llm_parse", side_effect=fake_parse), \
         mock.patch("core.tools.gmail_send.send_pending_draft",
                    return_value={"ok": True, "message": "Sent to bob@x.com."}) as mock_send:
        result2 = md.dispatch("send it")
        mock_send.assert_called_once()
        assert "Sent to bob@x.com" in result2
