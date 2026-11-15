import argparse
import json

from agents.baseline_agent import BaselineAgent


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
