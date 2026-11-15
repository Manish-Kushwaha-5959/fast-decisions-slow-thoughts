import argparse
import json

from agents.hybrid_agent import HybridAgent


def main():
    parser = argparse.ArgumentParser(
        description="Run the Jev + Groq hybrid agent (Mode B)."
    )

    parser.add_argument(
        "--task",
        required=True,
        help="Task for the hybrid agent."
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5
    )

    args = parser.parse_args()

    agent = HybridAgent(
        max_iterations=args.max_iterations
    )

    try:
        result = agent.run(args.task)

        print("\n========== HYBRID AGENT RESULT ==========\n")
        print(json.dumps(
            result.to_dict(),
            indent=4,
            ensure_ascii=False
        ))

        print("\n========== TOKEN SUMMARY ==========")
        print("LLM tokens:", result.llm_total_tokens)
        print("Jev tokens:", result.jev_total_tokens)
        print(
            "Combined tokens:",
            result.llm_total_tokens + result.jev_total_tokens
        )
        print("LLM latency:", result.llm_latency_seconds)
        print("Jev latency:", result.jev_latency_seconds)
        print("Total latency:", result.total_latency_seconds)
        print("Success:", result.success)
        print("Termination:", result.termination_reason)

    finally:
        agent.close()


if __name__ == "__main__":
    main()
