import pytest

from types import SimpleNamespace

from agents.hybrid_agent import HybridAgent
from models.jev_client import JevClientError
from tools.registry import build_default_registry


# ---------------------------------------------------------
# Mock Groq client
# ---------------------------------------------------------

class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append({
            "messages": messages,
            "kwargs": kwargs
        })

        if not self.responses:
            raise AssertionError(
                "FakeLLMClient received an unexpected generate call."
            )

        content = self.responses.pop(0)

        return SimpleNamespace(
            content=content,
            model="fake-groq-model",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            latency_seconds=0.1,
            finish_reason="stop",
            request_id="fake-request"
        )

    def close(self):
        pass


# ---------------------------------------------------------
# Mock Jev client
# ---------------------------------------------------------

def make_jev_decision(
    selected_tool="check_service_status",
    completion_probability=0.0,
    loop_probability=0.0,
    progress_score=2.0
):
    return SimpleNamespace(
        selected_tool=selected_tool,
        tool_probabilities={selected_tool: 0.95},
        tool_confidence=0.95,
        completion_probability=completion_probability,
        loop_probability=loop_probability,
        progress_score=progress_score,
        model="fake-jev-model",
        input_tokens=8,
        output_tokens=4,
        total_tokens=12,
        latency_seconds=0.05
    )


class FakeJevClient:
    def __init__(self, decisions=None, error=None):
        self.decisions = list(decisions or [])
        self.error = error
        self.calls = []

    def evaluate_state(self, state, available_tools):
        self.calls.append({
            "state": state,
            "available_tools": available_tools
        })

        if self.error:
            raise self.error

        if not self.decisions:
            raise AssertionError(
                "FakeJevClient received an unexpected evaluation call."
            )

        return self.decisions.pop(0)


# ---------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------

def plan_response():
    return '{"plan": "Check the requested service status."}'


def arguments_response(service="VPN"):
    return (
        '{"arguments": {"service": "' + service + '"}}'
    )


def final_response():
    return '{"response": "The VPN service status was checked."}'


def make_agent(
    llm_responses,
    jev_decisions=None,
    max_iterations=5,
    jev_error=None
):
    llm = FakeLLMClient(llm_responses)

    jev = FakeJevClient(
        decisions=jev_decisions,
        error=jev_error
    )

    registry = build_default_registry()

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev,
        registry=registry,
        max_iterations=max_iterations
    )

    return agent, llm, jev


# ---------------------------------------------------------
# Planning tests
# ---------------------------------------------------------

def test_hybrid_generates_plan():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.plan == (
        "Check the requested service status."
    )

    assert result.success is True
    assert len(llm.calls) == 2
    assert len(jev.calls) == 1


def test_hybrid_handles_invalid_planning_json():
    agent, llm, jev = make_agent(
        llm_responses=[
            "This is not valid JSON."
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "planning_error"
    assert "planning stage" in result.final_response.lower()

    # Planning failed, so Jev must not be called.
    assert len(jev.calls) == 0


def test_hybrid_rejects_empty_task():
    agent, llm, jev = make_agent(
        llm_responses=[]
    )

    with pytest.raises(ValueError):
        agent.run(" ")

    assert len(llm.calls) == 0
    assert len(jev.calls) == 0


# ---------------------------------------------------------
# Tool execution and completion tests
# ---------------------------------------------------------

def test_hybrid_executes_jev_selected_tool():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == (
        "check_service_status"
    )

    assert result.tool_calls[0]["execution_status"] == "success"

    assert len(jev.calls) == 2


def test_hybrid_respects_jev_tool_selection():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="check_service_status"
            ),
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.tool_calls[0]["tool_name"] == (
        "check_service_status"
    )

    # Groq generates arguments, but does not choose the tool.
    argument_prompt = llm.calls[1]["messages"][1]["content"]

    assert "check_service_status" in argument_prompt


def test_hybrid_detects_completion_without_tool_execution():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    result = agent.run(
        "I need no additional support."
    )

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"
    assert result.tool_calls == []

    # Only planning and final response generation.
    assert len(llm.calls) == 2


# ---------------------------------------------------------
# Loop detection and safety tests
# ---------------------------------------------------------

def test_hybrid_stops_when_jev_detects_loop():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                loop_probability=0.95
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "jev_detected_loop"

    # The first tool call happened, but the loop prevented another.
    assert len(result.tool_calls) == 1


def test_hybrid_rejects_unregistered_jev_tool():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="delete_database"
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "invalid_jev_tool_selection"
    )
    assert result.tool_calls == []

    # Groq is not asked to generate arguments for an invalid tool.
    assert len(llm.calls) == 2


def test_hybrid_limits_identical_tool_calls():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            arguments_response("VPN"),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(),
            make_jev_decision()
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "repeated_tool_call"

    # The default permits two identical calls.
    # The third identical call is blocked.
    assert len(result.tool_calls) == 2


# ---------------------------------------------------------
# Iteration limit tests
# ---------------------------------------------------------

def test_hybrid_evaluates_state_after_last_allowed_tool_call():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        max_iterations=1
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert len(result.tool_calls) == 1

    # The extra Jev evaluation can confirm completion,
    # but cannot authorize another tool call.
    assert len(jev.calls) == 2

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"


def test_hybrid_stops_at_maximum_tool_call_limit():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.10
            )
        ],
        max_iterations=1
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "maximum_iterations_reached"
    )

    assert len(result.tool_calls) == 1
    assert len(jev.calls) == 2


# ---------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------

def test_hybrid_handles_invalid_argument_json():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            "Invalid argument JSON.",
            final_response()
        ],
        jev_decisions=[
            make_jev_decision()
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "argument_generation_error"
    )
    assert result.tool_calls == []


def test_hybrid_handles_jev_api_error():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_error=JevClientError(
            "Simulated Jev API failure."
        )
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "jev_error"
    assert "control system" in result.final_response.lower()

    assert result.tool_calls == []


# ---------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------

def test_hybrid_records_llm_and_jev_metrics():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    # Three Groq calls: planning, arguments, final response.
    assert result.llm_input_tokens == 30
    assert result.llm_output_tokens == 15
    assert result.llm_total_tokens == 45

    # Two Jev evaluations.
    assert result.jev_input_tokens == 16
    assert result.jev_output_tokens == 8
    assert result.jev_total_tokens == 24

    assert result.llm_latency_seconds > 0
    assert result.jev_latency_seconds > 0
    assert result.total_latency_seconds > 0
