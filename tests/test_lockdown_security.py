from types import SimpleNamespace


def test_tool_rejects_unknown_arguments():
    from core.interfaces.tool import Tool

    tool = Tool(
        name="demo",
        description="demo",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string", "maxLength": 10}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=lambda args: args,
    )
    result = tool.execute({"value": "ok", "unexpected": True})
    assert not result.ok
    assert "invalid_arguments" in result.error


def test_tool_rejects_oversized_string():
    from core.interfaces.tool import Tool

    tool = Tool(
        name="demo",
        description="demo",
        parameters={"type": "object", "properties": {"value": {"type": "string", "maxLength": 4}}, "required": ["value"]},
        handler=lambda args: args,
    )
    result = tool.execute({"value": "12345"})
    assert not result.ok


def test_browser_rejects_private_destinations():
    from core.tools.browser import _validate_url

    assert _validate_url("http://127.0.0.1:8000/secret") == "destination_not_public"
    assert _validate_url("http://localhost:8000/") == "destination_not_public"
    assert _validate_url("file:///etc/passwd") == "only_http_https_urls_allowed"


def test_cloud_auth_fails_closed_without_token(monkeypatch):
    import utils.security as security

    monkeypatch.setattr(security, "API_TOKEN", "")
    monkeypatch.setattr(security, "ENVIRONMENT", "render")
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.10"))
    try:
        security.verify_token(request, None)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
    else:
        raise AssertionError("cloud auth must fail closed when token is missing")


def test_local_auth_can_remain_open_for_development(monkeypatch):
    import utils.security as security

    monkeypatch.setattr(security, "API_TOKEN", "")
    monkeypatch.setattr(security, "ENVIRONMENT", "local")
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    assert security.verify_token(request, None) is True
