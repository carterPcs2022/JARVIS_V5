"""tests/test_security_fixes.py — regression tests for Phase 0 and Phase 7's
security fixes, so none of them can silently regress in a later change."""
import os
from unittest import mock


# ── Phase 0: shell injection (core/tools/system.py::run_shell) ──────────────

def test_run_shell_blocks_injection_via_disguised_command():
    from core.tools.system import run_shell
    result = run_shell("ls; touch /tmp/jarvis_test_injection_marker")
    assert not os.path.exists("/tmp/jarvis_test_injection_marker"), \
        "shell injection succeeded -- run_shell regressed"
    if os.path.exists("/tmp/jarvis_test_injection_marker"):
        os.remove("/tmp/jarvis_test_injection_marker")  # pragma: no cover


def test_run_shell_allows_legitimate_allowlisted_command():
    from core.tools.system import run_shell
    result = run_shell("echo hello")
    assert result.get("stdout") == "hello"


def test_run_shell_rejects_non_allowlisted_command():
    from core.tools.system import run_shell
    result = run_shell("rm -rf /")
    assert "error" in result


# ── Phase 0: path traversal (server/routes/voice.py) ─────────────────────────

def test_voice_audio_path_traversal_rejected():
    import os as _os
    from pathlib import Path

    def check(target: str, static_dir: Path) -> str:
        if not target:
            return "no target"
        safe_name = _os.path.basename(target)
        if safe_name in ("", ".", "..") or safe_name != target:
            return "REJECTED"
        candidate = (static_dir / safe_name).resolve()
        try:
            candidate.relative_to(static_dir.resolve())
        except ValueError:
            return "REJECTED"
        return str(candidate)

    static_dir = Path("/tmp/jarvis_test_static")
    static_dir.mkdir(exist_ok=True)
    assert check("../../.env", static_dir) == "REJECTED"
    assert check("../../../etc/passwd", static_dir) == "REJECTED"
    assert check("/etc/passwd", static_dir) == "REJECTED"
    assert check("voice_123.mp3", static_dir) != "REJECTED"


# ── Phase 0: AppleScript injection (core/tools/mac.py) ────────────────────────

def test_mac_quit_app_escapes_quotes():
    from core.tools.mac import quit_app
    with mock.patch("core.tools.mac.run_applescript") as mock_run:
        mock_run.return_value = ""
        quit_app('Evil" -- injected')
        script = mock_run.call_args[0][0]
        assert '\\"' in script


# ── Phase 7: dev_intel.py arbitrary file read ────────────────────────────────

def test_dev_intel_rejects_path_traversal():
    from services.dev_intel import dev_intel
    result = dev_intel.explain_file("/etc/passwd")
    assert "outside allowed area" in result

    result2 = dev_intel.review_file("../../../etc/passwd")
    assert "outside allowed area" in result2["error"]


def test_dev_intel_index_project_outside_project_indexes_nothing():
    from services.dev_intel import dev_intel
    result = dev_intel.index_project("/etc")
    assert result["files_indexed"] == 0


# ── Phase 7: SSH host key checking (services/remote_control.py) ─────────────

def test_remote_control_uses_accept_new_not_no():
    import services.remote_control as rc
    with mock.patch("services.remote_control.IS_HEADLESS_CLOUD", True), \
         mock.patch("services.remote_control.TAILSCALE_IP", "100.1.2.3"), \
         mock.patch("services.remote_control.MAC_USERNAME", "bob"), \
         mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(stdout="ok", returncode=0)
        rc.RemoteMacControl().execute("lock_screen")
        called_cmd = mock_run.call_args[0][0]
        assert "StrictHostKeyChecking=accept-new" in called_cmd
        assert "StrictHostKeyChecking=no" not in called_cmd


# ── Phase 7: voice.py os.system -> subprocess.run ────────────────────────────

def test_voice_play_never_calls_os_system():
    import services.voice as voice
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("subprocess.run") as mock_run, \
         mock.patch("os.system") as mock_os_system, \
         mock.patch.dict("sys.modules", {"pygame": None}):
        mock_run.return_value = mock.Mock(returncode=0)
        voice._play("/tmp/fake.mp3")
        mock_os_system.assert_not_called()
        assert mock_run.called


# ── Phase 7: stark_security.py block_ip IP validation ────────────────────────

def test_block_ip_rejects_malformed_input():
    from services.stark_security import stark_security
    result = stark_security.block_ip("not-an-ip; rm -rf /")
    assert result["blocked"] is False
    assert "valid IP" in result["error"]


def test_block_ip_still_works_for_real_ip():
    from services.stark_security import stark_security
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        result = stark_security.block_ip("203.0.113.7")
        assert result["blocked"] is True
