from types import SimpleNamespace

from agents.baseline_agent import BaselineAgent
from tools.registry import build_default_registry


class FakeLLMClient:
    """Mock LLM client for deterministic agent tests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def generate(self, messages, temperature=None, max_completion_tokens=None, response_format=None):
        if not self.responses:
            raise RuntimeError("No mock responses remaining.")

        self.call_count += 1
        content = self.responses.pop(0)

        return SimpleNamespace(
            content=content,
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
            latency_seconds=0.1
        )

    def close(self):
        pass


def test_baseline_returns_final_response():
    llm = FakeLLMClient([
        """
        {
            "action": "final",
            "response": "Hello! How can I help you?",
            "decision_summary": "No tool is needed."
        }
        """
    ])

    agent = BaselineAgent(
        llm_client=llm,
        registry=build_default_registry()
    )

    result = agent.run("Hello")

    assert result.final_response == "Hello! How can I help you?"
    assert result.success is True
    assert result.iterations == 1
    assert result.termination_reason == "llm_decided_complete"
    assert len(result.tool_calls) == 0


def test_baseline_executes_tool_then_returns_final():
    llm = FakeLLMClient([
        """
        {
            "action": "tool_call",
            "tool_name": "check_service_status",
            "arguments": {
                "service": "vpn"
            },
            "decision_summary": "Check VPN availability."
        }
        """,
        """
        {
            "action": "final",
            "response": "The VPN service is currently degraded.",
            "decision_summary": "The service status answers the request."
        }
        """
    ])

    agent = BaselineAgent(
        llm_client=llm,
        registry=build_default_registry()
    )

    result = agent.run("Check the VPN service status.")

    assert result.success is True
    assert len(result.tool_calls) == 1

    assert (
        result.tool_calls[0]["tool_name"]
        == "check_service_status"
    )

    assert (
        result.tool_calls[0]["execution_status"]
        == "success"
    )

    assert (
        result.tool_calls[0]["result"]["status"]
        == "degraded"
    )

    assert result.iterations == 2


def test_baseline_handles_tool_execution_error():
    llm = FakeLLMClient([
        """
        {
            "action": "tool_call",
            "tool_name": "unknown_tool",
            "arguments": {},
            "decision_summary": "Attempt an unknown tool."
        }
        """,
        """
        {
            "action": "final",
            "response": "I could not access that tool.",
            "decision_summary": "The tool was unavailable."
        }
        """
    ])

    agent = BaselineAgent(
        llm_client=llm,
        registry=build_default_registry()
    )

    result = agent.run("Check something.")

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["execution_status"] == "error"
    assert result.success is True


def test_baseline_stops_at_iteration_limit():
    llm = FakeLLMClient([
        """
        {
            "action": "tool_call",
            "tool_name": "check_service_status",
            "arguments": {
                "service": "vpn"
            },
            "decision_summary": "Check VPN."
        }
        """,
        """
        {
            "action": "tool_call",
            "tool_name": "check_service_status",
            "arguments": {
                "service": "email"
            },
            "decision_summary": "Check email."
        }
        """
    ])

    agent = BaselineAgent(
        llm_client=llm,
        registry=build_default_registry(),
        max_iterations=2
    )

    result = agent.run("Check multiple services.")

    assert result.success is False
    assert result.iterations == 2

    assert (
        result.termination_reason
        == "maximum_iterations_reached"
    )

    assert len(result.tool_calls) == 2


def test_baseline_handles_invalid_json():
    llm = FakeLLMClient([
        "This is not valid JSON."
    ])

    agent = BaselineAgent(
        llm_client=llm,
        registry=build_default_registry()
    )

    result = agent.run("Test invalid output.")

    assert result.success is False

    assert (
        result.termination_reason
        == "invalid_llm_response"
    )


def test_baseline_rejects_empty_task():
    agent = BaselineAgent(
        llm_client=FakeLLMClient([]),
        registry=build_default_registry()
    )

    try:
        agent.run("   ")
        assert False, "Expected ValueError."

    except ValueError:
        pass


def test_baseline_rejects_invalid_iteration_limit():
    try:
        BaselineAgent(
            llm_client=FakeLLMClient([]),
            registry=build_default_registry(),
            max_iterations=0
        )

        assert False, "Expected ValueError."

    except ValueError:
        pass
