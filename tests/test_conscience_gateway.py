"""Regression tests for the simulated conscience and tool gateway."""

from core.conscience import Conscience, SelfModel
from core.interfaces.tool import Tool
from core.tool_gateway import ToolGateway


def test_conscience_tracks_self_model_and_pauses_on_uncertainty():
    model = SelfModel()
    c = Conscience(self_model=model)
    c.register_capability("github_read")
    assessment = c.deliberate("review repository", uncertainty=80)
    assert assessment.recommendation == "pause_and_review"
    assert "github_read" in model.capabilities
    assert model.active_goal == "review repository"


def test_conscience_allows_low_risk_authorized_intent():
    assessment = Conscience().deliberate("summarize repository", risk_score=10, uncertainty=10)
    assert assessment.recommendation == "proceed_if_authorized"


def test_gateway_lists_metadata_without_handlers():
    tool = Tool(
        name="example", description="Example", parameters={"type": "object"},
        handler=lambda args: "ok", permissions=["read"],
    )
    gateway = ToolGateway({"example": tool})
    metadata = gateway.list_tools()[0]
    assert metadata["name"] == "example"
    assert "handler" not in metadata


def test_gateway_enforces_confirmation_before_execution():
    called = []
    tool = Tool(
        name="danger", description="Danger", parameters={"type": "object"},
        handler=lambda args: called.append(args) or "done",
        risk_level="high", requires_confirmation=True, reversible=False,
    )
    gateway = ToolGateway({"danger": tool})
    result = gateway.execute("danger", {"x": 1})
    assert result.ok is False
    assert result.error == "confirmation_required"
    assert called == []
