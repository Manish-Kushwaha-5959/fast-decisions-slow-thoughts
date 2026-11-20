"""
Phase 6 tests: Mode C uncertainty detection and escalation.

Covers:
- Tool-selection escalation (high/low confidence, authorised and
  unauthorised Groq recommendations, malformed responses, API failure).
- Task-completion escalation (clear decisions, ambiguous band, Groq
  completion with/without evidence, Groq continuation, escalation
  failure).
- Threshold configuration validation.
- Mode B regression (escalation disabled preserves Phase 5 behaviour).

All clients are mocked; no live API is contacted.
"""

import json
from types import SimpleNamespace

import pytest

from agents.escalation_agent import (
    DEFAULT_COMPLETION_AMBIGUITY_LOWER,
    DEFAULT_COMPLETION_AMBIGUITY_UPPER,
    DEFAULT_TOOL_CONFIDENCE_THRESHOLD,
    EscalationAgent,
    EscalationOutcome
)
from agents.hybrid_agent import HybridAgent
from models.jev_client import JevClientError
from tools.registry import build_default_registry


# ---------------------------------------------------------
# Mock clients (mirrors test_hybrid_agent.py helpers)
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


def make_jev_decision(
    selected_tool="check_service_status",
    completion_probability=0.0,
    loop_probability=0.0,
    progress_score=2.0,
    tool_confidence=0.95,
    tool_probabilities=None
):
    # The probability map defaults to the selected tool carrying the
    # confidence value so that explicit confidence/probability
    # arguments both drive the escalation checks.
    if tool_probabilities is None:
        tool_probabilities = {selected_tool: tool_confidence}

    return SimpleNamespace(
        selected_tool=selected_tool,
        tool_probabilities=tool_probabilities,
        tool_confidence=tool_confidence,
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


def plan_response(
    plan="Check the requested service status.",
    allowed_tools=None,
    required_tools=None,
    objective="Check the current VPN service status.",
    required_outcomes=None,
    completion_criteria=None
):
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
    return '{"arguments": {"service": "' + service + '"}}'


def final_response():
    return '{"response": "The VPN service status was checked."}'


def escalation_tool_response(tool="check_service_status"):
    return json.dumps({
        "selected_tool": tool,
        "reasoning": "The status tool directly answers the request."
    })


def escalation_completion_response(task_complete=True):
    return json.dumps({
        "task_complete": task_complete,
        "reasoning": "The status evidence satisfies the criteria."
    })


def make_agent(
    llm_responses,
    jev_decisions=None,
    max_iterations=5,
    jev_error=None,
    enable_escalation=True,
    tool_confidence_threshold=None,
    completion_ambiguity_lower=None,
    completion_ambiguity_upper=None,
    escalate_before_completion=False
):
    llm = FakeLLMClient(llm_responses)
    jev = FakeJevClient(
        decisions=jev_decisions,
        error=jev_error
    )
    registry = build_default_registry()

    kwargs = {}
    if tool_confidence_threshold is not None:
        kwargs["tool_confidence_threshold"] = tool_confidence_threshold
    if completion_ambiguity_lower is not None:
        kwargs["completion_ambiguity_lower"] = completion_ambiguity_lower
    if completion_ambiguity_upper is not None:
        kwargs["completion_ambiguity_upper"] = completion_ambiguity_upper

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev,
        registry=registry,
        max_iterations=max_iterations,
        enable_escalation=enable_escalation,
        escalate_before_completion=escalate_before_completion,
        **kwargs
    )

    return agent, llm, jev


def find_escalation_records(result):
    """Return decision-history entries where escalation occurred."""
    return [
        entry for entry in result.decision_history
        if entry.get("escalated") is True
    ]


# ---------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------

def test_default_thresholds_match_specification():
    agent = EscalationAgent(llm_client=None)

    assert agent.tool_confidence_threshold == 0.60
    assert agent.completion_ambiguity_lower == 0.50
    assert agent.completion_ambiguity_upper == 0.70


def test_threshold_constants_are_provisional_defaults():
    assert DEFAULT_TOOL_CONFIDENCE_THRESHOLD == 0.60
    assert DEFAULT_COMPLETION_AMBIGUITY_LOWER == 0.50
    assert DEFAULT_COMPLETION_AMBIGUITY_UPPER == 0.70


def test_invalid_tool_confidence_threshold_is_rejected():
    with pytest.raises(ValueError):
        EscalationAgent(
            llm_client=None,
            tool_confidence_threshold=1.5
        )


def test_invalid_ambiguity_band_is_rejected():
    with pytest.raises(ValueError):
        EscalationAgent(
            llm_client=None,
            completion_ambiguity_lower=0.80,
            completion_ambiguity_upper=0.70
        )


# ---------------------------------------------------------
# Tool-selection escalation
# ---------------------------------------------------------

def test_high_confidence_jev_decision_does_not_escalate():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(tool_confidence=0.95),
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
    assert find_escalation_records(result) == []

    # Groq calls: planning, arguments, final response only.
    assert len(llm.calls) == 3
    assert agent.mode == "C"


def test_low_confidence_jev_decision_escalates():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            escalation_tool_response("check_service_status"),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.40,
                tool_probabilities={"check_service_status": 0.40}
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

    records = find_escalation_records(result)
    assert len(records) == 1
    assert records[0]["decision_type"] == "tool_selection"
    assert records[0]["escalated"] is True
    assert records[0]["escalation_succeeded"] is True
    assert "below the escalation threshold" in (
        records[0]["escalation_reason"]
    )

    # Groq was consulted for the review.
    assert len(llm.calls) == 4

    # The executed tool came from the authorised selection.
    assert result.tool_calls[0]["tool_name"] == "check_service_status"


def test_groq_recommends_authorised_tool():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(allowed_tools=[
                "check_service_status",
                "search_knowledge_base"
            ]),
            escalation_tool_response("search_knowledge_base"),
            '{"arguments": {"query": "wifi"}}',
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="check_service_status",
                tool_confidence=0.30,
                tool_probabilities={
                    "check_service_status": 0.30,
                    "search_knowledge_base": 0.50
                }
            ),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ]
    )

    result = agent.run(
        "Find Wi-Fi troubleshooting steps."
    )

    assert result.success is True

    # Groq's authorised recommendation replaced Jev's uncertain pick.
    assert result.tool_calls[0]["tool_name"] == "search_knowledge_base"

    record = find_escalation_records(result)[0]
    assert record["groq_recommendation"]["selected_tool"] == (
        "search_knowledge_base"
    )
    assert record["final_decision"] == "search_knowledge_base"


def test_groq_recommends_unauthorized_tool():
    """An unauthorised Groq recommendation falls back to Jev's pick."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            escalation_tool_response("delete_database"),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30}
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

    # The unauthorised recommendation was rejected; Jev's authorised
    # selection executed instead. Nothing unsafe ran.
    assert result.tool_calls[0]["tool_name"] == "check_service_status"
    assert result.tool_calls[0]["execution_status"] == "success"

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert "invalid tool" in record["escalation_reason"]
    assert record["final_decision"] == "check_service_status"


def test_malformed_escalation_response():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            "This is not valid JSON.",
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.20,
                tool_probabilities={"check_service_status": 0.20}
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

    # The run continues safely on Jev's authorised selection.
    assert result.tool_calls[0]["tool_name"] == "check_service_status"
    assert result.tool_calls[0]["execution_status"] == "success"

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert "valid JSON" in record["escalation_reason"]
    assert record["final_decision"] == "check_service_status"
    assert record["final_decision"] == "check_service_status"


def test_escalation_api_failure_falls_back_safely():
    class ExplodingLLMClient:
        def generate(self, messages, **kwargs):
            raise RuntimeError("Simulated Groq outage.")

    llm = FakeLLMClient([
        plan_response(),
        arguments_response("VPN"),
        final_response()
    ])
    jev = FakeJevClient([
        make_jev_decision(
            tool_confidence=0.25,
            tool_probabilities={"check_service_status": 0.25}
        ),
        make_jev_decision(
            completion_probability=0.95,
            progress_score=5.0
        )
    ])

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev,
        registry=build_default_registry(),
        max_iterations=5
    )

    # Replace the Groq client used for escalation with one that fails.
    agent.escalation_agent.llm = ExplodingLLMClient()

    result = agent.run(
        "Check the current VPN service status."
    )

    # The escalation failed but the run completed on Jev's pick.
    assert result.success is True
    assert result.tool_calls[0]["tool_name"] == "check_service_status"

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert "Groq outage" in record["escalation_reason"]
    assert record["final_decision"] == "check_service_status"


# ---------------------------------------------------------
# Task-completion escalation
# ---------------------------------------------------------

def test_clear_completion_does_not_escalate():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(completion_probability=0.95)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert find_escalation_records(result) == []

    # Groq calls: planning and final response only.
    assert len(llm.calls) == 2


def test_clear_low_completion_does_not_escalate():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(completion_probability=0.10),
            make_jev_decision(completion_probability=0.95)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert find_escalation_records(result) == []


def test_ambiguous_completion_escalates():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            escalation_completion_response(True),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(completion_probability=0.60)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert result.termination_reason == "groq_confirmed_completion"

    records = find_escalation_records(result)
    assert len(records) == 1
    assert records[0]["decision_type"] == "task_completion"
    assert records[0]["escalation_succeeded"] is True
    assert records[0]["final_decision"] is True
    assert "ambiguous band" in records[0]["escalation_reason"]

    # Groq was consulted exactly once for the review.
    assert len(llm.calls) == 3


def test_groq_completion_with_valid_evidence():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=["check_service_status"],
                required_tools=["check_service_status"]
            ),
            arguments_response("VPN"),
            escalation_completion_response(True),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(),
            make_jev_decision(completion_probability=0.55)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert result.termination_reason == "groq_confirmed_completion"

    # The mandatory tool executed before completion was accepted.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["execution_status"] == "success"


def test_groq_completion_without_required_evidence():
    """Groq cannot override the evidence gate."""
    # check_service_status is mandatory, but Jev keeps selecting the
    # knowledge-base search. Groq later claims completion while the
    # mandatory tool has never run.
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ],
                required_tools=["check_service_status"]
            ),
            escalation_completion_response(True),
            arguments_response("wifi"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                selected_tool="search_knowledge_base",
                completion_probability=0.60
            ),
            make_jev_decision(
                selected_tool="search_knowledge_base",
                completion_probability=0.95
            )
        ]
    )

    result = agent.run(
        "Check the current VPN service status."
    )

    # Groq recommended completion, but the mandatory tool never ran.
    # The controller ignored the recommendation and the Phase 5
    # evidence gate stopped the run exactly as before.
    assert result.success is False
    assert result.termination_reason == "required_tools_not_fulfilled"
    assert [
        call["tool_name"] for call in result.tool_calls
    ] == ["search_knowledge_base"]

    record = find_escalation_records(result)[0]
    assert record["decision_type"] == "task_completion"
    assert record["final_decision"] is False


def test_groq_recommends_continuing_execution():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            escalation_completion_response(False),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(completion_probability=0.60),
            make_jev_decision(completion_probability=0.95)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"

    # Groq said "not complete", so execution continued.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "check_service_status"

    record = find_escalation_records(result)[0]
    assert record["final_decision"] is False


def test_completion_escalation_failure_does_not_complete():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            "not json at all",
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(completion_probability=0.60),
            make_jev_decision(completion_probability=0.95)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    # The failed escalation must not falsely mark the task complete;
    # execution continues instead.
    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"
    assert len(result.tool_calls) == 1

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert record["final_decision"] is False


def test_completion_escalation_api_failure_does_not_complete():
    class ExplodingLLMClient:
        def generate(self, messages, **kwargs):
            raise RuntimeError("Simulated Groq outage.")

    llm = FakeLLMClient([
        plan_response(),
        arguments_response("VPN"),
        final_response()
    ])
    jev = FakeJevClient([
        make_jev_decision(completion_probability=0.60),
        make_jev_decision(completion_probability=0.95)
    ])

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev,
        registry=build_default_registry(),
        max_iterations=5
    )
    agent.escalation_agent.llm = ExplodingLLMClient()

    result = agent.run("Check the current VPN service status.")

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"
    assert len(result.tool_calls) == 1

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert "Groq outage" in record["escalation_reason"]


# ---------------------------------------------------------
# Boundary behaviour of the ambiguous band
# ---------------------------------------------------------

def test_ambiguity_band_boundaries():
    agent = EscalationAgent(llm_client=None)

    # Lower bound inclusive.
    assert agent.completion_required(0.50)[0] is True
    # Upper bound exclusive (0.70 already triggers the clear rule).
    assert agent.completion_required(0.70)[0] is False
    # Just inside the band.
    assert agent.completion_required(0.6999)[0] is True
    # Below the band.
    assert agent.completion_required(0.49)[0] is False


def test_tool_confidence_threshold_boundary():
    agent = EscalationAgent(llm_client=None)

    # At the threshold the decision counts as uncertain (escalate).
    decision = make_jev_decision(tool_confidence=0.60)
    assert agent.tool_selection_required(decision)[0] is True

    # Just above the threshold the decision is trusted.
    decision = make_jev_decision(tool_confidence=0.61)
    assert agent.tool_selection_required(decision)[0] is False


def test_selected_tool_probability_used_over_confidence():
    agent = EscalationAgent(llm_client=None)

    # Probability of the selected tool is the primary signal.
    decision = make_jev_decision(
        tool_confidence=0.95,
        tool_probabilities={"check_service_status": 0.50}
    )
    assert agent.tool_selection_required(decision)[0] is True

    # Falls back to Choice confidence when the map lacks the pick.
    decision = make_jev_decision(
        tool_confidence=0.55,
        tool_probabilities={"other_tool": 0.55}
    )
    assert agent.tool_selection_required(decision)[0] is True


# ---------------------------------------------------------
# Mode B regression (escalation disabled)
# ---------------------------------------------------------

def test_escalation_disabled_preserves_mode_b_behaviour():
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.20,
                tool_probabilities={"check_service_status": 0.20},
                completion_probability=0.0
            ),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        enable_escalation=False
    )

    result = agent.run("Check the current VPN service status.")

    # No escalation despite low confidence that would escalate in
    # Mode C: escalation is disabled, so the run behaves exactly like
    # Phase 5 Mode B.
    assert agent.mode == "B"
    assert find_escalation_records(result) == []

    # Planning, one argument call, and the final response.
    assert len(llm.calls) == 3

    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"


# ---------------------------------------------------------
# Phase 5 regression guards (Mode C enabled)
# ---------------------------------------------------------

def test_escalation_cannot_execute_unauthorised_tool():
    """Groq must never authorise a tool outside allowed_tools."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(allowed_tools=["check_service_status"]),
            escalation_tool_response("create_support_ticket"),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30}
            ),
            make_jev_decision(completion_probability=0.95)
        ]
    )

    result = agent.run("Check the current VPN service status.")

    # The ticket tool is outside allowed_tools and was never executed.
    assert result.tool_calls[0]["tool_name"] == "check_service_status"
    executed = [
        call["tool_name"] for call in result.tool_calls
    ]
    assert "create_support_ticket" not in executed


def test_escalation_preserves_jev_error_handling():
    agent, llm, jev = make_agent(
        llm_responses=[plan_response(), final_response()],
        jev_decisions=[],
        jev_error=JevClientError("Simulated Jev API failure.")
    )

    result = agent.run("Check the current VPN service status.")

    assert result.success is False
    assert result.termination_reason == "jev_error"
    assert "control system" in result.final_response.lower()
    assert result.tool_calls == []


def test_escalation_outcome_records_usage():
    agent = EscalationAgent(llm_client=None)

    outcome = EscalationOutcome(
        decision_type="tool_selection",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        latency_seconds=0.1
    )

    assert outcome.decision_type == "tool_selection"
    assert outcome.total_tokens == 15


# ---------------------------------------------------------
# Observable Mode C escalation (escalate_before_completion)
# ---------------------------------------------------------

def test_escalate_before_completion_triggers_on_low_confidence_with_completion():
    """With the opt-in flag, low confidence + completion signal escalates."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            escalation_tool_response("check_service_status"),
            final_response()
        ],
        jev_decisions=[
            # Low tool confidence with high completion probability and
            # fulfilled required tool (check_service_status ran earlier).
            make_jev_decision(
                selected_tool="check_service_status",
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30},
                completion_probability=0.95,
                progress_score=5.0
            ),
            make_jev_decision(
                selected_tool="check_service_status",
                tool_confidence=0.95,
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        escalate_before_completion=True,
        enable_escalation=True
    )

    result = agent.run("Check the current VPN service status.")

    # The escalation must fire before the completion break.
    records = find_escalation_records(result)
    assert len(records) == 1
    assert records[0]["decision_type"] == "tool_selection"
    assert records[0]["escalated"] is True
    assert records[0]["escalation_succeeded"] is True

    # Groq was consulted for the advisory review.
    assert len(llm.calls) == 3

    # The task still completed successfully via the normal path.
    assert result.success is True


def test_escalate_before_completion_respects_evidence_gate():
    """Escalation must not allow task completion without evidence."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(
                allowed_tools=[
                    "check_service_status",
                    "search_knowledge_base"
                ],
                required_tools=["check_service_status"]
            ),
            escalation_tool_response("check_service_status"),
            arguments_response("wifi"),
            final_response()
        ],
        jev_decisions=[
            # Low confidence, high completion, but mandatory tool NOT
            # yet executed (search_knowledge_base was chosen instead).
            make_jev_decision(
                selected_tool="search_knowledge_base",
                tool_confidence=0.20,
                tool_probabilities={"search_knowledge_base": 0.20},
                completion_probability=0.95,
                progress_score=5.0
            ),
            make_jev_decision(
                selected_tool="search_knowledge_base",
                tool_confidence=0.95,
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        escalate_before_completion=True,
        enable_escalation=True
    )

    result = agent.run("Check the current VPN service status.")

    # Even after escalation, the evidence gate must hold: no completion.
    assert result.success is False
    assert result.termination_reason == "required_tools_not_fulfilled"
    # The escalation was recorded but did not complete the task.
    records = find_escalation_records(result)
    assert len(records) == 1
    assert records[0]["decision_type"] == "tool_selection"
    assert records[0]["escalated"] is True


def test_escalate_before_completion_unauthorised_recommendation_rejected():
    """An unauthorised Groq recommendation must not become the tool."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(allowed_tools=["check_service_status"]),
            escalation_tool_response("delete_database"),
            arguments_response("VPN"),
            final_response()
        ],
        jev_decisions=[
            # Low confidence on first iteration triggers escalation;
            # completion is low so the tool still executes.
            make_jev_decision(
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30},
                completion_probability=0.0,
                progress_score=5.0
            ),
            make_jev_decision(
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        escalate_before_completion=True,
        enable_escalation=True
    )

    result = agent.run("Check the current VPN service status.")

    # The unauthorised recommendation was rejected; Jev's authorised
    # pick executed instead. Nothing unsafe ran.
    assert result.tool_calls[0]["tool_name"] == "check_service_status"
    assert result.tool_calls[0]["execution_status"] == "success"

    record = find_escalation_records(result)[0]
    assert record["escalation_succeeded"] is False
    assert "invalid tool" in record["escalation_reason"]
    assert record["final_decision"] == "check_service_status"


def test_escalate_before_completion_default_off():
    """Default behaviour must remain unchanged (completion-first)."""
    agent, llm, jev = make_agent(
        llm_responses=[
            plan_response(),
            final_response()
        ],
        jev_decisions=[
            make_jev_decision(
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30},
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        enable_escalation=True,
        escalate_before_completion=False
    )

    result = agent.run("Check the current VPN service status.")

    # No escalation should occur by default.
    assert find_escalation_records(result) == []
    # Groq was not consulted for an escalation review.
    assert len(llm.calls) == 2
    # The run completed via the normal completion path.
    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"


def test_escalate_before_completion_advisory_but_unused():
    """
    If completion fires immediately after an advisory escalation,
    the record must not imply the recommended tool was executed.
    """
    agent, llm, jev = make_agent(
        llm_responses=[
            # planning, escalation review, final response (no tool
            # execution needed because completion succeeded).
            plan_response(),
            escalation_tool_response("check_service_status"),
            final_response()
        ],
        jev_decisions=[
            # Low confidence + high completion + fulfilled evidence:
            # escalation fires, then completion break fires before any
            # tool execution.
            make_jev_decision(
                selected_tool="check_service_status",
                tool_confidence=0.30,
                tool_probabilities={"check_service_status": 0.30},
                completion_probability=0.95,
                progress_score=5.0
            )
        ],
        escalate_before_completion=True,
        enable_escalation=True
    )

    result = agent.run("Check the current VPN service status.")

    records = find_escalation_records(result)
    assert len(records) == 1
    assert records[0]["decision_type"] == "tool_selection"
    assert records[0]["escalated"] is True
    assert records[0]["final_decision"] is not None

    # Completion fired; no tool was executed after the escalation.
    assert result.success is True
    assert result.termination_reason == "jev_detected_completion"
    assert result.tool_calls == []
