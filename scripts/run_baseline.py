import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/run_baseline.py` from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.baseline_agent import BaselineAgent  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Run the LLM-only baseline agent."
    )

    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="The customer-support task to execute."
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum number of LLM decision iterations."
    )

    args = parser.parse_args()

    agent = BaselineAgent(
        max_iterations=args.max_iterations
    )

    try:
        result = agent.run(args.task)

        print("\n========== BASELINE AGENT RESULT ==========\n")

        print(json.dumps(
            result.to_dict(),
            indent=4,
            ensure_ascii=False
        ))

        print("\n===========================================\n")

    finally:
        agent.close()


if __name__ == "__main__":
    main()
