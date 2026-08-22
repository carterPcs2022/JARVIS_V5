"""tests/test_interfaces_agent.py — core/interfaces/agent.py."""
import pytest
from core.interfaces.agent import registry, get_agent, Agent


def test_registry_has_all_5_agents():
    assert set(registry().keys()) == {
        "coder", "researcher", "planner", "deep_research", "agentic_loop",
    }


def test_every_agent_isinstance_and_self_named():
    for name, agent in registry().items():
        assert isinstance(agent, Agent), name
        assert agent.name == name


@pytest.mark.asyncio
async def test_coder_agent_runs_and_reports_failure_honestly():
    """No LLM keys configured -- generate() gets back the offline
    placeholder string, which is not valid Python, so the syntax check
    correctly fails and success=False propagates. Proves the adapter
    doesn't silently swallow that and claim success."""
    agent = get_agent("coder")
    result = await agent.run("write a function that adds two numbers", {"mode": "generate"})
    assert result.success is False


@pytest.mark.asyncio
async def test_deep_research_agent_reports_started_not_finished():
    """deep_research.research() starts a background thread and returns
    immediately -- run()'s success=True means "the job started", not "the
    report is done"."""
    agent = get_agent("deep_research")
    result = await agent.run("a test topic", {"depth": "quick"})
    assert result.success is True
    assert result.metadata["status"] == "started"
    assert result.metadata["research_id"]
