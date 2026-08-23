"""tests/test_playbook_token_rotation.py — regression test for the
JARVIS_API_TOKEN rotation playbook action.

Before this fix, _action_rotate_api_token() wrote the new token only to
.env_token_update -- a file on Render's ephemeral filesystem, wiped by the
next redeploy with the new value recorded nowhere else. That happened for
real on Aug 22 (docs/AUDIT.md) and locked the token out from under the
owner with no way to recover the new value. The fix routes the new token
through send_alert_email() as a durable second copy."""
from pathlib import Path
from unittest import mock
import services.playbook as playbook_mod

_TOKEN_FILE = Path(playbook_mod.__file__).parent.parent / ".env_token_update"


def _cleanup():
    _TOKEN_FILE.unlink(missing_ok=True)


def test_rotate_api_token_emails_new_value_on_success():
    engine = playbook_mod.ThreatPlaybook.__new__(playbook_mod.ThreatPlaybook)
    try:
        with mock.patch("services.alert_email.send_alert_email",
                         return_value={"ok": True, "gmail_message_id": "abc"}) as mock_email, \
             mock.patch("core.event_bus.bus.system") as mock_bus:
            result = engine._action_rotate_api_token({})

        assert "emailed" in result
        assert mock_email.called
        severity, category, message = mock_email.call_args[0]
        assert severity == "high"
        assert category == "TOKEN_ROTATION"
        assert "JARVIS_API_TOKEN=" in message
        # the token must not land in the first 80 chars (send_alert_email
        # truncates the subject line, and notification previews do too)
        assert "JARVIS_API_TOKEN=" not in message[:80]
        mock_bus.assert_called_once()
        assert _TOKEN_FILE.exists()
        assert "JARVIS_API_TOKEN=" in _TOKEN_FILE.read_text()
    finally:
        _cleanup()


def test_rotate_api_token_reports_failure_when_email_fails():
    engine = playbook_mod.ThreatPlaybook.__new__(playbook_mod.ThreatPlaybook)
    try:
        with mock.patch("services.alert_email.send_alert_email",
                         return_value={"ok": False, "error": "not configured"}), \
             mock.patch("core.event_bus.bus.system") as mock_bus:
            result = engine._action_rotate_api_token({})

        assert "email failed" in result
        assert "apply it manually" in result
        mock_bus.assert_not_called()
        # the file is still written -- the fallback path for a failed email
        assert _TOKEN_FILE.exists()
    finally:
        _cleanup()
