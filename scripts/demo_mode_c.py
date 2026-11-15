"""
Mode C demonstration: uncertainty detection and escalation.

Runs the three demonstrable situations from the Phase 6
specification with mocked clients, so the demo is deterministic
and costs no API calls:

1. Normal execution — Jev is confident; Groq escalation avoided.
2. Tool uncertainty — Jev is unsure; Groq reviews the tool choice.
3. Completion uncertainty — Jev is ambiguous; Groq judges completion.

Usage:
    python scripts/demo_mode_c.py
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.hybrid_agent import HybridAgent  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402


# ---------------------------------------------------------
# Mock clients
# ---------------------------------------------------------

class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages[-1]["content"])
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


class FakeJevClient:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def evaluate_state(self, state, available_tools):
        return self.decisions.pop(0)


def jev(
    selected_tool="check_service_status",
    completion_probability=0.0,
    tool_confidence=0.95
):
    return SimpleNamespace(
        selected_tool=selected_tool,
        tool_probabilities={selected_tool: tool_confidence},
        tool_confidence=tool_confidence,
        completion_probability=completion_probability,
        loop_probability=0.0,
        progress_score=2.0,
        model="fake-jev-model",
        input_tokens=8,
        output_tokens=4,
        total_tokens=12,
        latency_seconds=0.05
    )


def plan_response():
    return json.dumps({
        "plan": "Check the requested service status.",
        "task_specification": {
            "objective": "Check the current VPN service status.",
            "required_outcomes": [
                "The status of the requested service has been determined."
            ],
            "allowed_tools": ["check_service_status"],
            "required_tools": ["check_service_status"],
            "completion_criteria": [
                "A service status result has been retrieved."
            ]
        }
    })


def arguments_response():
    return '{"arguments": {"service": "VPN"}}'


def final_response():
    return '{"response": "The VPN service status was checked."}'


def tool_escalation_response():
    return json.dumps({
        "selected_tool": "check_service_status",
        "reasoning": "The status tool directly answers the request."
    })


def completion_escalation_response(task_complete=True):
    return json.dumps({
        "task_complete": task_complete,
        "reasoning": "The status evidence satisfies the criteria."
    })


def run_scenario(name, llm_responses, jev_decisions):
    llm = FakeLLMClient(llm_responses)
    jev_client = FakeJevClient(jev_decisions)

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev_client,
        registry=build_default_registry(),
        max_iterations=5,
        enable_escalation=True
    )

    result = agent.run("Check the current VPN service status.")

    print("\n" + "=" * 64)
    print(f"SCENARIO: {name}")
    print("=" * 64)
    print(f"Mode                : {agent.mode}")
    print(f"Success             : {result.success}")
    print(f"Termination reason  : {result.termination_reason}")
    print(f"Groq calls          : {len(llm.calls)}")
    print(f"Jev calls           : {len(result.decision_history)}")
    print(f"Tool calls          : {[c['tool_name'] for c in result.tool_calls]}")

    print("\nDecision history:")
    for entry in result.decision_history:
        print(
            f"  iteration {entry['iteration']}: "
            f"tool={entry['selected_tool']}, "
            f"confidence={entry['tool_confidence']:.2f}, "
            f"completion={entry['completion_probability']:.2f}, "
            f"escalated={entry['escalated']}"
        )
        if entry["escalated"]:
            print(f"    decision_type : {entry['decision_type']}")
            print(f"    reason        : {entry['escalation_reason']}")
            print(f"    groq recommends: "
                  f"{entry['groq_recommendation']}")
            print(f"    final decision : "
                  f"{entry['final_decision']}")
            print(f"    escalation succeeded: "
                  f"{entry['escalation_succeeded']}")

    print(f"\nCombined tokens: {result.llm_total_tokens} "
          f"(Groq) + {result.jev_total_tokens} (Jev)")


def main():
    print("Mode C demonstration (mocked clients, no API cost)")

    # 1. Normal execution: Jev confident, no escalation.
    run_scenario(
        "1. Normal execution — confident Jev, no escalation",
        llm_responses=[
            plan_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            jev(tool_confidence=0.95, completion_probability=0.0),
            jev(completion_probability=0.95)
        ]
    )

    # 2. Tool uncertainty: low confidence, Groq reviews the pick.
    run_scenario(
        "2. Tool uncertainty — low confidence escalates to Groq",
        llm_responses=[
            plan_response(),
            tool_escalation_response(),
            arguments_response(),
            final_response()
        ],
        jev_decisions=[
            jev(tool_confidence=0.35, completion_probability=0.0),
            jev(completion_probability=0.95)
        ]
    )

    # 3. Completion uncertainty: ambiguous band, Groq judges. The
    #    tool runs first so the evidence gate can accept the advice.
    run_scenario(
        "3. Completion uncertainty — ambiguous probability escalates",
        llm_responses=[
            plan_response(),
            arguments_response(),
            completion_escalation_response(True),
            final_response()
        ],
        jev_decisions=[
            jev(tool_confidence=0.95, completion_probability=0.0),
            jev(tool_confidence=0.95, completion_probability=0.60)
        ]
    )

    print("\n" + "=" * 64)
    print("All three scenarios completed. Escalation events are")
    print("visible in decision_history via the 'escalated' flag.")
    print("=" * 64)


if __name__ == "__main__":
    main()
