import json

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

def plan_response(
    plan="Check the requested service status.",
    allowed_tools=None,
    required_tools=None,
    objective="Check the current VPN service status.",
    required_outcomes=None,
    completion_criteria=None
):
    """
    Build a valid planning response matching the current
    HybridAgent planning contract.

    The planner must return a plan plus a structured
    task_specification with exactly five fields:
    objective, required_outcomes, allowed_tools,
    required_tools and completion_criteria.
    """
    if allowed_tools is None:
        allowed_tools = ["check_service_status"]

    if required_tools is None:
        required_tools = []

    if required_outcomes is None:
        required_outcomes = [
            "The status of the requested service has been determined."
        ]

    if completion_criteria is None:
        completion_criteria = [
            "A service status result has been retrieved."
        ]

    return json.dumps({
        "plan": plan,
        "task_specification": {
            "objective": objective,
            "required_outcomes": required_outcomes,
            "allowed_tools": allowed_tools,
            "required_tools": required_tools,
            "completion_criteria": completion_criteria
        }
    })


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


def test_hybrid_rejects_incomplete_task_specification():
    # Valid JSON, but the required task_specification is missing.
    agent, llm, jev = make_agent(
        llm_responses=[
            '{"plan": "Check the requested service status."}'
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "planning_error"
    assert "planning stage" in result.final_response.lower()

    # An incomplete specification must not reach Jev.
    assert len(jev.calls) == 0


def test_hybrid_accepts_valid_five_field_specification():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                required_tools=["check_service_status"]
            ),
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

    # The validated specification preserves required_tools.
    assert result.task_specification["required_tools"] == [
        "check_service_status"
    ]

    assert result.task_specification["allowed_tools"] == [
        "check_service_status"
    ]

    # The mandatory tool executed successfully before Jev's
    # completion signal was accepted.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == (
        "check_service_status"
    )
    assert result.tool_calls[0]["execution_status"] == "success"

    # Planning, argument generation, and final response.
    assert len(jev.calls) == 2
    assert len(llm.calls) == 3


def test_hybrid_rejects_missing_required_field():
    from agents.hybrid_agent import HybridAgent

    try:
        HybridAgent._validate_task_specification(
            specification={
                "objective": "Check the current VPN service status.",
                "required_outcomes": ["A service status result."],
                "allowed_tools": ["check_service_status"],
                "completion_criteria": ["A status result."]
            },
            available_tools=build_default_registry().get_tool_descriptions(),
            task="Check the current VPN service status."
        )
        assert False, "Expected ValueError for missing required_tools."

    except ValueError as exc:
        assert "required_tools" in str(exc)


def test_hybrid_rejects_unexpected_field():
    from agents.hybrid_agent import HybridAgent

    try:
        HybridAgent._validate_task_specification(
            specification={
                "objective": "Check the current VPN service status.",
                "required_outcomes": ["A service status result."],
                "allowed_tools": ["check_service_status"],
                "required_tools": [],
                "completion_criteria": ["A status result."],
                "extra_field": "unexpected"
            },
            available_tools=build_default_registry().get_tool_descriptions(),
            task="Check the current VPN service status."
        )
        assert False, "Expected ValueError for unexpected field."

    except ValueError as exc:
        assert "must contain exactly" in str(exc)


def test_hybrid_accepts_empty_required_tools():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(required_tools=[]),
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

    assert result.success is True
    assert result.task_specification["required_tools"] == []


def test_hybrid_rejects_required_tool_not_in_allowed_tools():
    from agents.hybrid_agent import HybridAgent

    try:
        HybridAgent._validate_task_specification(
            specification={
                "objective": "Check the current VPN service status.",
                "required_outcomes": ["A service status result."],
                "allowed_tools": ["check_service_status"],
                "required_tools": ["create_support_ticket"],
                "completion_criteria": ["A status result."]
            },
            available_tools=build_default_registry().get_tool_descriptions(),
            task="Check the current VPN service status."
        )
        assert False, (
            "Expected ValueError for required tool outside allowed_tools."
        )

    except ValueError as exc:
        assert "not in allowed_tools" in str(exc)


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
            arguments_response("VPN"),
            arguments_response("Email"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(),
            make_jev_decision(
                loop_probability=0.95,
                progress_score=0.5
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "jev_detected_loop"

    # Loop termination requires at least two completed tool calls
    # and negligible progress.
    assert len(result.tool_calls) == 2


def test_hybrid_does_not_stop_for_loop_score_after_one_successful_tool():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            arguments_response("Email"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                loop_probability=0.83,
                completion_probability=0.41,
                progress_score=1.87
            ),
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
    assert len(result.tool_calls) == 2

    # A high loop score after only one action must not terminate.
    assert result.decision_history[1]["loop_probability"] == 0.83

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
        "unauthorized_jev_tool_selection"
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
# Tool authorization tests (Phase 5)
# ---------------------------------------------------------

def test_hybrid_executes_authorised_tool():
    """A tool inside allowed_tools may be selected and executed."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(allowed_tools=["check_service_status"]),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(selected_tool="check_service_status"),
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
    assert result.tool_calls[0]["tool_name"] == (
        "check_service_status"
    )
    assert result.tool_calls[0]["execution_status"] == "success"


def test_hybrid_blocks_tool_outside_allowed_tools():
    """Jev cannot select a tool the planner excluded."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(allowed_tools=["check_service_status"]),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="create_support_ticket"
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "unauthorized_jev_tool_selection"
    )
    assert result.tool_calls == []

    # Groq is never asked to argue for an unauthorised tool.
    assert len(llm.calls) == 2
    assert len(jev.calls) == 1


def test_hybrid_keeps_ticket_authorization_guard():
    """create_support_ticket stays gated on explicit user request."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "check_service_status",
                    "create_support_ticket"
                ],
                required_tools=[]
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == "planning_error"
    assert "explicitly requested" in result.final_response.lower()

    # The authorisation failure must stop the run before Jev.
    assert len(jev.calls) == 0
    assert len(llm.calls) == 1


def test_hybrid_allows_ticket_when_user_authorises():
    """Explicit user request permits the state-changing tool."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "create_support_ticket"
                ],
                required_tools=["create_support_ticket"],
                objective=(
                    "Create a support ticket for a payment failure."
                )
            ),
            (
                '{"arguments": {"issue": "Payment portal down", '
                '"priority": "high"}}'
            ),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="create_support_ticket"
            ),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ]
    )

    result = agent.run(
        "Please create a support ticket for the payment failure."
    )

    assert result.success is True
    assert result.tool_calls[0]["tool_name"] == (
        "create_support_ticket"
    )
    assert result.tool_calls[0]["execution_status"] == "success"
    assert result.tool_calls[0]["result"]["status"] == "created"


# ---------------------------------------------------------
# Evidence-gated completion tests (Phase 5)
# ---------------------------------------------------------

def test_hybrid_completion_requires_required_tool_evidence():
    """Jev completion alone is not success when a mandatory tool
    has not produced valid evidence."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=["check_service_status"],
                required_tools=["check_service_status"]
            ),
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

    assert result.success is False
    assert result.termination_reason == (
        "required_tools_not_fulfilled"
    )
    assert result.tool_calls == []
    assert result.decision_history[-1][
        "completion_probability"
    ] == 0.95


def test_hybrid_failed_tool_execution_is_not_evidence():
    """A failed mandatory execution cannot satisfy the gate."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=["check_service_status"],
                required_tools=["check_service_status"]
            ),
            arguments_response(""),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    # An empty service argument fails execution, so the mandatory
    # tool never produces valid evidence.
    result = agent.run(
        "Check the current VPN service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "required_tools_not_fulfilled"
    )
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["execution_status"] == "error"
    assert "error" in result.tool_calls[0]["result"]


def test_hybrid_invalid_evidence_does_not_complete():
    """Structurally invalid evidence is not completion evidence."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=["check_service_status"],
                required_tools=["check_service_status"]
            ),
            arguments_response("NotARealService"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(
                completion_probability=0.95
            )
        ]
    )

    # "unknown" status fails the check_service_status evidence rule.
    result = agent.run(
        "Check the current NotARealService service status."
    )

    assert result.success is False
    assert result.termination_reason == (
        "required_tools_not_fulfilled"
    )


def test_hybrid_all_required_tools_with_evidence_complete():
    """Every mandatory tool with valid evidence permits completion."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ],
                required_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ]
            ),
            arguments_response("VPN"),
            (
                '{"arguments": {"query": "wifi connection"}}'
            ),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="check_service_status"
            ),
            make_jev_decision(
                selected_tool="search_knowledge_base"
            ),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ]
    )

    result = agent.run(
        "Check the VPN status and find Wi-Fi troubleshooting steps."
    )

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"

    executed = [
        call["tool_name"] for call in result.tool_calls
    ]
    assert executed == [
        "check_service_status",
        "search_knowledge_base"
    ]

    assert all(
        call["execution_status"] == "success"
        for call in result.tool_calls
    )


def test_hybrid_partial_required_tools_block_completion():
    """Completion is blocked until every mandatory tool succeeds."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ],
                required_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ]
            ),
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
        "Check the VPN status and find Wi-Fi troubleshooting steps."
    )

    assert result.success is False
    assert result.termination_reason == (
        "required_tools_not_fulfilled"
    )

    # Only the first mandatory tool executed; the second was
    # never attempted, so evidence is incomplete.
    assert len(result.tool_calls) == 1


def test_hybrid_rejects_unknown_allowed_tool_configuration():
    """An allowed tool missing from the registry is rejected cleanly."""
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

    # Bypass the planner validator, which would already reject the
    # unregistered tool, and feed the control loop directly.
    loop_result = agent.control_loop.run(
        task="Check the current VPN service status.",
        plan="Check the status.",
        task_specification={
            "objective": "Check the current VPN service status.",
            "required_outcomes": ["A service status result."],
            "allowed_tools": ["check_service_status", "ghost_tool"],
            "required_tools": ["check_service_status"],
            "completion_criteria": ["A status result."]
        }
    )

    assert loop_result.success is False
    assert loop_result.termination_reason == (
        "unauthorized_tool_configuration"
    )
    assert "ghost_tool" in loop_result.final_response
    assert loop_result.tool_calls == []


def test_hybrid_empty_required_tools_completes_on_jev():
    """An empty required_tools list imposes no evidence gate."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(required_tools=[]),
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
    assert result.task_specification["required_tools"] == []

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
