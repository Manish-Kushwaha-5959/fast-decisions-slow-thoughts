import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python scripts/run_hybrid.py` from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.hybrid_agent import HybridAgent


EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
RESULTS_CSV = EXPERIMENTS_DIR / "results.csv"
LOGS_JSONL = EXPERIMENTS_DIR / "experiment_logs.jsonl"


def record_experiment(result: dict) -> None:
    """Append one run record to the experiments structure."""
    timestamp = datetime.now(timezone.utc).isoformat()

    record = {
        "timestamp": timestamp,
        "mode": "B",
        **result
    }

    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

    with LOGS_JSONL.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(
            record, ensure_ascii=False
        ) + "\n")

    fields = [
        "timestamp", "mode", "task", "success",
        "termination_reason", "iterations",
        "llm_input_tokens", "llm_output_tokens",
        "llm_total_tokens", "llm_latency_seconds",
        "jev_input_tokens", "jev_output_tokens",
        "jev_total_tokens", "jev_latency_seconds",
        "tool_latency_seconds", "total_latency_seconds",
        "combined_tokens"
    ]
    row = dict(record)
    row["combined_tokens"] = (
        result.get("llm_total_tokens", 0)
        + result.get("jev_total_tokens", 0)
    )

    write_header = not RESULTS_CSV.exists() or (
        RESULTS_CSV.stat().st_size == 0
    )

    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow({name: row.get(name) for name in fields})


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

        record_experiment(result.to_dict())

    finally:
        agent.close()


if __name__ == "__main__":
    main()
