"""
Phase 13 live validation: a budgeted campaign against the real APIs.

Executes Modes A, B and C against live Groq / Jev endpoints and appends
the results through the existing experiment logger to the canonical live
destination (``experiments/benchmark_results.csv`` / ``.jsonl``). Mocked
and live records are never mixed: every row this script writes carries
``execution_type == "live"``.

Design rules (from the Phase 13 plan):
- Hard budget. The run aborts unless ``--max-live-runs`` >= tasks x modes
  x repetitions; the default 15 caps the whole campaign (5 tasks x 3
  modes x 1 repetition).
- No retries. A failed provider call is recorded honestly as a failed /
  unverifiable run and the campaign moves on.
- Real usage. Token counts come from provider-reported usage; cost is an
  *estimated equivalent* computed by the Phase 11 implementation, never
  claimed as billing. Actual expenditure stays unavailable (None) unless
  a billing source is supplied.
- Representative tasks. A curated subset of ``data/tasks.json`` keeps
  token use low while covering single-tool and multi-tool tasks.

Usage:
    python scripts/run_live_validation.py --yes
    python scripts/run_live_validation.py --tasks 3 --yes
    python scripts/run_live_validation.py --max-live-runs 15 --yes
"""

import argparse
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.economic_metrics import EconomicMetricsCalculator  # noqa: E402
from evaluation.logger import ExperimentLogger  # noqa: E402
from evaluation.metrics import extract_run_metrics, summarize_runs  # noqa: E402
from evaluation.task_verifier import TaskVerifier, load_tasks  # noqa: E402
from scripts.run_benchmark import _run_live  # noqa: E402

DEFAULT_TASK_IDS = [
    "kb_password_reset",
    "status_vpn",
    "ticket_login_issue",
    "multi_status_and_knowledge",
    "multi_knowledge_and_ticket",
]


def main():
    parser = argparse.ArgumentParser(
        description="Budgeted live validation of Modes A, B and C."
    )
    parser.add_argument(
        "--tasks", type=int, default=5,
        help="Representative tasks per mode (default 5; total = tasks x 3)."
    )
    parser.add_argument(
        "--max-live-runs", type=int, default=15,
        help="Hard cap on live executions (default 15)."
    )
    parser.add_argument(
        "--task-ids", default=None,
        help="Comma-separated task ids overriding the representative set."
    )
    parser.add_argument(
        "--max-iterations", type=int, default=5,
        help="Per-run agent iteration limit."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Confirm the live-run cost warning without prompting."
    )
    parser.add_argument(
        "--escalate-before-completion", action="store_true",
        help="Enable Mode C tool-selection escalation before the "
             "completion break (opt-in; default off)."
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-run progress lines."
    )
    args = parser.parse_args()

    if not args.yes:
        print("WARNING: this script calls the live Groq and/or Jev APIs")
        print("and incurs real token cost, bounded by --max-live-runs "
              f"({args.max_live_runs}).")
        print("Re-run with --yes to confirm. Aborting.")
        return 1

    all_tasks = load_tasks(None)
    by_id = {t["id"]: t for t in all_tasks}
    if args.task_ids:
        task_ids = [t.strip() for t in args.task_ids.split(",") if t.strip()]
        missing = [t for t in task_ids if t not in by_id]
        if missing:
            print(f"ERROR: unknown task ids: {missing}")
            return 1
    else:
        task_ids = DEFAULT_TASK_IDS[:args.tasks]
        unknown = [t for t in task_ids if t not in by_id]
        if unknown:
            print(f"ERROR: unknown default task ids: {unknown}")
            return 1

    tasks = [by_id[tid] for tid in task_ids]
    modes = ["A", "B", "C"]
    total = len(tasks) * len(modes)

    if total > args.max_live_runs:
        print(
            f"ERROR: campaign would execute {total} live runs, exceeding "
            f"the budget of {args.max_live_runs}."
        )
        return 1

    print(
        f"Live validation: {len(tasks)} task(s) x modes {modes} "
        f"= {total} run(s); budget {args.max_live_runs}."
    )

    # Canonical live destination: the same append-only benchmark files
    # the campaign runner writes, never the legacy Phase 5/6 files.
    logger = ExperimentLogger()
    verifier = TaskVerifier()
    calculator = EconomicMetricsCalculator()

    results = {mode: [] for mode in modes}

    for mode in modes:
        # Determine if Mode C should have escalate_before_completion enabled
        if mode == "C" and args.escalate_before_completion:
            mode_escalate_before_completion = True
        else:
            mode_escalate_before_completion = False

        for task in tasks:
            run_id = f"{mode}-{task['id']}-01-live-{uuid.uuid4().hex[:6]}"
            error = None
            try:
                execution = _run_live(task, mode, args.max_iterations, mode_escalate_before_completion)
                execution = execution.to_dict()
            except Exception as exc:  # noqa: BLE001 — record, never retry
                execution = {
                    "task": task["description"],
                    "final_response": "",
                    "success": False,
                    "iterations": 0,
                    "tool_calls": [],
                    "decision_history": [],
                    "llm_input_tokens": 0,
                    "llm_output_tokens": 0,
                    "llm_total_tokens": 0,
                    "llm_latency_seconds": 0.0,
                    "jev_input_tokens": 0,
                    "jev_output_tokens": 0,
                    "jev_total_tokens": 0,
                    "jev_latency_seconds": 0.0,
                    "tool_latency_seconds": 0.0,
                    "total_latency_seconds": 0.0,
                    "termination_reason": "live_execution_error",
                    "task_specification": {},
                }
                error = f"{type(exc).__name__}: {exc}"
                execution["error"] = error

            metrics = extract_run_metrics(execution)
            verification = verifier.verify(task, execution)

            # Phase 11 economic metrics from provider-reported usage.
            economic = calculator.create_task_metrics_from_execution(
                task_id=task["id"],
                mode=mode,
                execution_metrics=metrics,
                execution_type="live",
            )
            metrics.update(economic.to_dict())

            logger.log(
                mode=mode,
                task_id=task["id"],
                metrics=metrics,
                verification=verification.to_dict(),
                run_id=run_id,
                raw_execution=execution,
                repetition=1,
                execution_type="live",
                error=error,
            )

            results[mode].append({
                "run_id": run_id,
                "task_id": task["id"],
                "mode": mode,
                "execution": execution,
                "metrics": metrics,
                "verification": verification,
                "error": error,
                "execution_type": "live",
                "repetition": 1,
            })

            if not args.quiet:
                status = "ERROR" if error else verification.outcome
                print(f"  {mode} {task['id']:<32} -> {status}")

    # Per-mode summaries over the live records.
    print("\nLIVE VALIDATION SUMMARY")
    print("-" * 60)
    for mode in modes:
        runs = results[mode]
        summary = summarize_runs(
            [
                {
                    "outcome": r["verification"].outcome,
                    "metrics": r["metrics"],
                }
                for r in runs
            ],
            mode=mode,
        )
        print(
            f"Mode {mode}: runs={summary.run_count} "
            f"verified={summary.verified_successes} "
            f"failed={summary.verified_failures} "
            f"unverifiable={summary.unverifiable} "
            f"groq_tokens={summary.llm_total_tokens} "
            f"jev_tokens={summary.jev_total_tokens} "
            f"total_est=${summary.total_estimated_cost} "
            f"groq_actual={summary.groq_actual_cost} "
            f"jev_actual={summary.jev_actual_cost} "
            f"escalations={summary.escalation_count}"
        )

    print("\nRecords appended to experiments/benchmark_results.{csv,jsonl}")
    print("with execution_type='live'. Estimated cost is an equivalent,")
    print("not billing; actual expenditure is unavailable unless a billing")
    print("source supplies it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
