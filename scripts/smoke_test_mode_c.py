"""
Controlled live smoke test for Mode C escalation.

One live task with a strict budget: planning call, at most two Jev
evaluations, the argument/final calls the run needs, and at most one
escalation review. Stops early if Jev never becomes uncertain, which
keeps the cost bounded and still exercises the Mode C path.

Usage:
    python scripts/smoke_test_mode_c.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.hybrid_agent import HybridAgent  # noqa: E402
from models.llm_client import GroqLLMClient  # noqa: E402
from models.jev_client import JevClient  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402


TASK = "Check the current VPN service status."

MAX_JEV_CALLS = 2


def main():
    llm = GroqLLMClient()
    jev = JevClient()

    agent = HybridAgent(
        llm_client=llm,
        jev_client=jev,
        registry=build_default_registry(),
        max_iterations=2,
        enable_escalation=True
    )

    # Hard budget: abort after the second Jev evaluation.
    original_evaluate = jev.evaluate_state
    calls = {"n": 0}

    def budgeted_evaluate(state, available_tools):
        calls["n"] += 1
        if calls["n"] > MAX_JEV_CALLS:
            raise RuntimeError(
                "Live smoke-test budget reached; stopping early."
            )
        return original_evaluate(state, available_tools)

    jev.evaluate_state = budgeted_evaluate

    try:
        result = agent.run(TASK)

        print("\n========== LIVE MODE C SMOKE TEST ==========\n")
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        print("\n========== ESCALATION SUMMARY ==========")
        escalated = [
            e for e in result.decision_history if e.get("escalated")
        ]
        print(f"mode            : {agent.mode}")
        print(f"success         : {result.success}")
        print(f"termination     : {result.termination_reason}")
        print(f"jev calls       : {calls['n']}")
        print(f"groq calls      : {result.llm_total_tokens} total tokens")
        print(f"escalations     : {len(escalated)}")
        for entry in escalated:
            print(
                "  -", entry["decision_type"],
                "| succeeded:", entry["escalation_succeeded"],
                "| final:", entry["final_decision"]
            )

    except Exception as exc:
        print(f"\nLive smoke test aborted: {exc}")

    finally:
        agent.close()


if __name__ == "__main__":
    main()
