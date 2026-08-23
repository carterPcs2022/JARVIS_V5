"""tests/test_sandbox_deploy.py — regression tests for the self-programming
sandbox's actual deploy/approve/persist path (core/sandbox.py::deploy(),
core/self_improvement.py::approve_improvement()/persist_deployment()).

This is the highest-stakes code in the app -- it can write JARVIS's own
source files -- and had zero direct test coverage before this file existed
(only rollback(), its sibling write path, was covered). These tests pin
down the "no Ultron scenarios" guarantees: LOCKED_FILES/ALLOWED_FILES is
enforced, nothing reaches a real file without going through validate_code(),
and persist_deployment() is the only path that ever pushes to GitHub."""
from unittest import mock
import core.sandbox as sandbox_mod
from core.sandbox import JarvisSandbox
from core.self_improvement import SelfImprovementEngine


def _sandbox(tmp_path):
    sb = JarvisSandbox.__new__(JarvisSandbox)
    return sb


# ── core/sandbox.py::deploy() ────────────────────────────────────────────────

def test_deploy_refuses_locked_file(tmp_path):
    sb = _sandbox(tmp_path)
    result = sb.deploy("config/settings.py", "x = 1\n", {"description": "test"})
    assert result["success"] is False
    assert "locked" in result["error"].lower()


def test_deploy_refuses_file_outside_allowlist(tmp_path):
    sb = _sandbox(tmp_path)
    result = sb.deploy("server/api.py", "x = 1\n", {"description": "test"})
    assert result["success"] is False


def test_deploy_refuses_banned_pattern(tmp_path):
    sb = _sandbox(tmp_path)
    result = sb.deploy("services/spotify.py", "import os\nos.system('rm -rf /')\n",
                        {"description": "test"})
    assert result["success"] is False
    assert "Validation failed" in result["error"]


def test_deploy_writes_file_backs_up_and_never_pushes(tmp_path):
    sb = _sandbox(tmp_path)
    target = sandbox_mod.BASE_DIR / "services" / "spotify.py"
    original = target.read_text()
    backup_dir = tmp_path / "backups"

    try:
        with mock.patch.object(sandbox_mod, "BACKUP_DIR", backup_dir), \
             mock.patch.object(sandbox_mod, "DEPLOY_LOG", tmp_path / "deployments.json"), \
             mock.patch("services.audit_log.audit_log.record"), \
             mock.patch("core.protocols.extremis.hot_reload",
                         return_value={"success": True}), \
             mock.patch("utils.git_ops.commit_and_push") as mock_push:
            new_code = "# deployed candidate\n"
            result = sb.deploy("services/spotify.py", new_code, {"description": "test change"})

            assert result["success"] is True
            assert result["persisted"] is False
            assert target.read_text() == new_code
            assert backup_dir.exists() and any(backup_dir.iterdir())
            mock_push.assert_not_called()  # deploy() must never itself push
    finally:
        target.write_text(original)


# ── core/self_improvement.py::approve_improvement() / persist_deployment() ──

def test_approve_improvement_not_found_returns_error():
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    with mock.patch.object(engine, "_load_queue", return_value=[]):
        result = engine.approve_improvement("nonexistent-id")
        assert result["success"] is False


def test_approve_improvement_deploys_and_dequeues():
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    queued = [{"id": "abc123", "filepath": "services/spotify.py",
               "new_code": "# x\n", "improvement": {"description": "d"}}]
    with mock.patch.object(engine, "_load_queue", return_value=queued), \
         mock.patch.object(engine, "_save_queue") as mock_save, \
         mock.patch.object(engine, "_announce_deployment") as mock_announce, \
         mock.patch("core.sandbox.jarvis_sandbox.deploy",
                     return_value={"success": True, "hot_reloaded": True}):
        result = engine.approve_improvement("abc123")
        assert result["success"] is True
        # dequeued: the saved queue no longer contains this id
        saved_queue = mock_save.call_args[0][0]
        assert all(i["id"] != "abc123" for i in saved_queue)
        mock_announce.assert_called_once()


def test_approve_improvement_never_calls_commit_and_push():
    """approve_improvement() deploys LOCALLY only -- persist_deployment() is
    the sole path that ever pushes to GitHub. See both docstrings."""
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    queued = [{"id": "abc123", "filepath": "services/spotify.py",
               "new_code": "# x\n", "improvement": {"description": "d"}}]
    with mock.patch.object(engine, "_load_queue", return_value=queued), \
         mock.patch.object(engine, "_save_queue"), \
         mock.patch.object(engine, "_announce_deployment"), \
         mock.patch("core.sandbox.jarvis_sandbox.deploy",
                     return_value={"success": True, "hot_reloaded": True}), \
         mock.patch("utils.git_ops.commit_and_push") as mock_push:
        engine.approve_improvement("abc123")
        mock_push.assert_not_called()


def test_persist_deployment_not_found_returns_error():
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    with mock.patch("core.sandbox.jarvis_sandbox.get_deployment", return_value=None):
        result = engine.persist_deployment("nonexistent")
        assert result["success"] is False


def test_persist_deployment_already_persisted_refuses():
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    deployment = {"filepath": "services/spotify.py", "persisted": True}
    with mock.patch("core.sandbox.jarvis_sandbox.get_deployment", return_value=deployment), \
         mock.patch("utils.git_ops.commit_and_push") as mock_push:
        result = engine.persist_deployment("dep-1")
        assert result["success"] is False
        mock_push.assert_not_called()


def test_persist_deployment_pushes_and_marks_persisted():
    engine = SelfImprovementEngine.__new__(SelfImprovementEngine)
    deployment = {"filepath": "services/spotify.py", "persisted": False,
                  "improvement": {"description": "d"}}
    with mock.patch("core.sandbox.jarvis_sandbox.get_deployment", return_value=deployment), \
         mock.patch("core.sandbox.jarvis_sandbox.mark_persisted") as mock_mark, \
         mock.patch("utils.git_ops.commit_and_push") as mock_push:
        result = engine.persist_deployment("dep-1")
        assert result["success"] is True
        mock_push.assert_called_once()
        mock_mark.assert_called_once_with("dep-1")
