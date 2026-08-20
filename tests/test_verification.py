"""tests/test_verification.py — core/interfaces/verification.py."""
import json
import time
from core.interfaces.verification import verify_tool_result, is_transient, with_retry


def test_offline_fallback_detected_as_failure():
    """core.llm.router's literal "[JARVIS OFFLINE] ..." fallback doesn't
    contain the word "error", so the bracket-error regex alone would miss
    it -- this is the specific gap caught in review before Phase 4 shipped."""
    v = verify_tool_result("[JARVIS OFFLINE] Ollama failed.")
    assert v.success is False


def test_legit_answer_not_false_flagged():
    v = verify_tool_result("The weather today is sunny with a high of 75F.")
    assert v.success is True


def test_dict_error_convention_transient():
    v = verify_tool_result({"error": "Connection refused"})
    assert v.success is False
    assert v.recommended_action == "retry"


def test_dict_error_convention_permanent():
    v = verify_tool_result({"error": "Command not in allowlist: rm -rf /"})
    assert v.success is False
    assert v.recommended_action == "ask_user"


def test_json_string_error_detected():
    v = verify_tool_result(json.dumps({"error": "Timed out"}))
    assert v.success is False
    assert v.recommended_action == "retry"


def test_bracket_text_error_convention():
    v = verify_tool_result("[Fetch error: connection refused]")
    assert v.success is False


def test_non_reversible_tool_never_gets_retry_recommended():
    v = verify_tool_result({"error": "Connection refused"}, reversible=False)
    assert v.recommended_action == "ask_user"


def test_real_success_dict_not_false_flagged():
    v = verify_tool_result({"stdout": "hello", "returncode": 0})
    assert v.success is True


def test_is_transient_classification():
    assert is_transient("Request timed out")
    assert is_transient("429 rate limit exceeded")
    assert not is_transient("Command not in allowlist")
    assert not is_transient("Path outside allowed area")


def test_with_retry_succeeds_on_second_attempt_with_backoff():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return {"error": "Connection refused"} if calls["n"] < 2 else {"ok": True}

    start = time.time()
    result, verdict = with_retry(flaky, verify=verify_tool_result, max_attempts=3, backoff_base=0.1)
    elapsed = time.time() - start

    assert calls["n"] == 2
    assert verdict.success is True
    assert elapsed >= 0.1


def test_with_retry_caps_at_max_attempts():
    calls = {"n": 0}

    def always_flaky():
        calls["n"] += 1
        return {"error": "Timed out"}

    result, verdict = with_retry(always_flaky, verify=verify_tool_result, max_attempts=3, backoff_base=0.01)
    assert calls["n"] == 3
    assert verdict.success is False


def test_with_retry_never_retries_permanent_failure():
    calls = {"n": 0}

    def permanent_failure():
        calls["n"] += 1
        return {"error": "Command not in allowlist"}

    result, verdict = with_retry(permanent_failure, verify=verify_tool_result, max_attempts=3)
    assert calls["n"] == 1
    assert verdict.success is False
