"""
Phase 7 benchmark runner: compare Modes A, B, and C.

The same task definitions and the same deterministic verification
criteria are used for every mode, so results are directly comparable.

Two execution paths:

- ``mocked`` (default) — deterministic fake Groq/Jev clients. Runs the
  whole benchmark offline, costs nothing, and is what the automated
  test-suite uses.
- ``live`` (opt-in) — real Groq/Jev APIs. Requires ``--live`` and a
  positive ``--max-live-runs`` budget; otherwise the runner aborts
  before contacting any API.

Every run is verified independently by ``evaluation/task_verifier.py``
and appended through ``evaluation/logger.py`` (append-only).

Usage examples:
    # mocked comparison of all three modes (default, free)
    python scripts/run_benchmark.py --mode all

    # one mode, two repetitions, small output
    python scripts/run_benchmark.py --mode B --repetitions 2 --quiet

    # live run with an explicit budget of three executions
    python scripts/run_benchmark.py --mode A --live --max-live-runs 3

    # threshold analysis over the recorded data
    python scripts/run_benchmark.py --threshold-analysis
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.baseline_agent import BaselineAgent  # noqa: E402
from agents.hybrid_agent import HybridAgent  # noqa: E402
from evaluation.logger import ExperimentLogger  # noqa: E402
from evaluation.metrics import (
    extract_run_metrics,
    summarize_runs
)  # noqa: E402
from evaluation.economic_metrics import (
    EconomicMetricsCalculator,
    TaskEconomicMetrics
)  # noqa: E402
from config.pricing import get_pricing_config  # noqa: E402
from evaluation.task_verifier import TaskVerifier, load_tasks  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402


DATASET_VERSION = "hybrid_agent_benchmark_v1"

LIVE_CONFIRMATION = (
    "I understand that this will call the live Groq and/or Jev APIs, "
    "incur real token cost, and respect the configured budget."
)


# ---------------------------------------------------------
# Mocked providers (deterministic, offline)
# ---------------------------------------------------------


class FakeLLMClient:
    """
    Stateful fake Groq client.

    Each task runs on a fresh instance, so a scripted response list is
    consumed exactly once. ``None`` entries stand in for a failed API
    call (raises RuntimeError) so failure paths are testable.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages[-1]["content"])

        if not self.responses:
            raise RuntimeError(
                "FakeLLMClient ran out of scripted responses."
            )

        content = self.responses.pop(0)

        if content is None:
            raise RuntimeError("Simulated Groq API failure.")

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
    """Deterministic fake Jev client with scripted decisions."""

    def __init__(self, decisions=None, error=None):
        self.decisions = list(decisions or [])
        self.error = error
        self.calls = []

    def evaluate_state(self, state, available_tools):
        self.calls.append({"state": state, "available_tools": available_tools})

        if self.error:
            raise RuntimeError(self.error)

        if not self.decisions:
            raise AssertionError(
                "FakeJevClient received an unexpected evaluation call."
            )

        return self.decisions.pop(0)


def jev_decision(
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


# ---------------------------------------------------------
# Task execution scripts (mocked path only)
# ---------------------------------------------------------


def _tool_argument_list(task):
    """Ordered (tool, arguments) pairs covering every expected tool."""

    pairs = []

    for tool_name in task["expected_tools"]:
        if tool_name == "search_knowledge_base":
            pairs.append((tool_name, {"query": task["description"]}))
        elif tool_name == "check_service_status":
            service = (
                task["id"].split("_", 1)[1]
                if task["id"].startswith("status_")
                else "vpn"
            )
            pairs.append((tool_name, {"service": service}))
        elif tool_name == "create_support_ticket":
            pairs.append((tool_name, {
                "issue": task["description"], "priority": "medium"
            }))

    return pairs


def _baseline_responses(task):
    """Mode A script: one tool call per expected tool, then final."""

    responses = []

    for tool_name, tool_args in _tool_argument_list(task):
        responses.append(json.dumps({
            "action": "tool_call",
            "tool_name": tool_name,
            "arguments": tool_args,
            "decision_summary": "Gather evidence with the required tool."
        }))

    responses.append(json.dumps({
        "action": "final",
        "response": (
            "The requested information was retrieved: "
            f"{task['expected_outcome']}"
        ),
        "decision_summary": "Task complete."
    }))

    return responses


def _plan_response(task):
    return json.dumps({
        "plan": "Execute the required tool and report the result.",
        "task_specification": {
            "objective": task["description"],
            "required_outcomes": [task["expected_outcome"]],
            "allowed_tools": list(task["expected_tools"]),
            "required_tools": list(task["expected_tools"]),
            "completion_criteria": [
                "The required tool executed and produced valid evidence."
            ]
        }
    })


def _hybrid_responses(task):
    """Mode B/C script: plan, one arguments call per tool, final."""

    responses = [_plan_response(task)]

    for _tool_name, tool_args in _tool_argument_list(task):
        responses.append(json.dumps({"arguments": tool_args}))

    responses.append(json.dumps({
        "response": (
            "The requested information was retrieved: "
            f"{task['expected_outcome']}"
        )
    }))

    return responses


def _jev_sequence(task):
    """
    Mode B/C Jev decisions: one confident pick per expected tool, then
    a final confirmed completion.
    """

    decisions = [
        jev_decision(
            selected_tool=tool_name,
            completion_probability=0.0,
            tool_confidence=0.95
        )
        for tool_name, _ in _tool_argument_list(task)
    ]

    decisions.append(
        jev_decision(
            selected_tool=task["expected_tools"][0],
            completion_probability=0.95,
            tool_confidence=0.95
        )
    )

    return decisions


def _run_mode_a_mocked(task):
    agent = BaselineAgent(
        llm_client=FakeLLMClient(_baseline_responses(task)),
        registry=build_default_registry(),
        max_iterations=5
    )
    try:
        return agent.run(task["description"])
    finally:
        agent.close()


def _run_modes_bc_mocked(task, enable_escalation):
    agent = HybridAgent(
        llm_client=FakeLLMClient(_hybrid_responses(task)),
        jev_client=FakeJevClient(_jev_sequence(task)),
        registry=build_default_registry(),
        max_iterations=5,
        enable_escalation=enable_escalation
    )
    try:
        return agent.run(task["description"])
    finally:
        agent.close()


def _run_live(task, mode, max_iterations):
    """Execute one task against the real APIs (opt-in only)."""

    from models.llm_client import GroqLLMClient  # local import: live-only

    if mode == "A":
        agent = BaselineAgent(
            llm_client=GroqLLMClient(),
            registry=build_default_registry(),
            max_iterations=max_iterations
        )
    else:
        from models.jev_client import JevClient  # live-only

        agent = HybridAgent(
            llm_client=GroqLLMClient(),
            jev_client=JevClient(),
            registry=build_default_registry(),
            max_iterations=max_iterations,
            enable_escalation=(mode == "C")
        )

    try:
        return agent.run(task["description"])
    finally:
        agent.close()


# ---------------------------------------------------------
# Benchmark core
# ---------------------------------------------------------


class BenchmarkRunner:
    """Executes the benchmark dataset across modes A/B/C."""

    def __init__(
        self,
        tasks_path=None,
        logger=None,
        execution_type="mocked",
        max_iterations=5
    ):
        self.tasks = load_tasks(tasks_path)
        self.verifier = TaskVerifier()
        self.logger = logger or ExperimentLogger()
        self.execution_type = execution_type
        self.max_iterations = max_iterations
        self.economic_calculator = EconomicMetricsCalculator()

    def execute_task(self, task, mode, repetition=1):
        """Run one task in one mode; return the raw execution record."""

        if self.execution_type == "live":
            execution = _run_live(task, mode, self.max_iterations)
        elif mode == "A":
            execution = _run_mode_a_mocked(task)
        else:
            execution = _run_modes_bc_mocked(
                task, enable_escalation=(mode == "C")
            )

        return execution.to_dict()

    def run_task(self, task, mode, repetition=1):
        """
        Execute + independently verify one (task, mode, repetition).

        Never raises: a task that errors is recorded as an unverifiable
        run so one failure cannot abort the benchmark.
        """

        run_id = f"{mode}-{task['id']}-{repetition:02d}-{uuid.uuid4().hex[:6]}"
        error = None

        try:
            execution = self.execute_task(task, mode, repetition)
        except Exception as exc:  # noqa: BLE001 — record and continue
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
                "termination_reason": "benchmark_execution_error",
                "task_specification": {}
            }
            error = f"{type(exc).__name__}: {exc}"
            # Mark the record itself so the verifier classifies a
            # crashed run as unverifiable rather than failed.
            execution["error"] = error

        metrics = extract_run_metrics(execution)

        verification = self.verifier.verify(task, execution)

        # Calculate economic metrics (Phase 11: cost accounting)
        economic_metrics = self.economic_calculator.create_task_metrics_from_execution(
            task_id=task["id"],
            mode=mode,
            execution_metrics=metrics,
            execution_type=self.execution_type
        )

        # Merge economic metrics into the metrics dict for logging
        metrics.update(economic_metrics.to_dict())

        self.logger.log(
            mode=mode,
            task_id=task["id"],
            metrics=metrics,
            verification=verification.to_dict(),
            run_id=run_id,
            raw_execution=execution,
            repetition=repetition,
            execution_type=self.execution_type,
            error=error
        )

        return {
            "run_id": run_id,
            "task_id": task["id"],
            "mode": mode,
            "execution": execution,
            "metrics": metrics,
            "verification": verification,
            "error": error
        }

    def run_benchmark(self, modes, tasks=None, repetitions=1):
        """
        Execute every (task, mode) pair ``repetitions`` times.

        Returns ``{mode: [run_record, ...]}``.
        """

        results = {mode: [] for mode in modes}
        task_list = tasks if tasks is not None else self.tasks

        for mode in modes:
            for task in task_list:
                for repetition in range(1, repetitions + 1):
                    run = self.run_task(task, mode, repetition)
                    results[mode].append(run)

        return results


# ---------------------------------------------------------
# Reporting
# ---------------------------------------------------------


def print_summary(summaries):
    """Print one concise comparison table across modes."""

    print("\n" + "=" * 72)
    print("BENCHMARK SUMMARY (independently verified outcomes)")
    print("=" * 72)

    header = (
        f"{'mode':<6}{'runs':>6}{'verified':>10}{'failed':>8}"
        f"{'unverif.':>10}{'agent ok':>10}{'verif rate':>12}"
        f"{'agent rate':>12}{'tokens':>10}{'latency s':>11}"
        f"{'escal.':>8}"
    )
    print(header)
    print("-" * len(header))

    for mode in sorted(summaries):
        s = summaries[mode]
        print(
            f"{s.mode:<6}{s.run_count:>6}{s.verified_successes:>10}"
            f"{s.verified_failures:>8}{s.unverifiable:>10}"
            f"{s.agent_reported_successes:>10}"
            f"{(s.verified_success_rate if s.verified_success_rate is not None else 0):>12.2f}"
            f"{(s.agent_reported_success_rate if s.agent_reported_success_rate is not None else 0):>12.2f}"
            f"{(s.combined_tokens if s.combined_tokens is not None else 0):>10}"
            f"{(s.mean_latency_seconds if s.mean_latency_seconds is not None else 0):>11.3f}"
            f"{(s.escalation_count if s.escalation_count is not None else 0):>8}"
        )

    print("-" * len(header))
    print(
        "verified/failed/unverifiable are independent outcomes; agent ok "
        "is the agent's self-report. tokens are combined (Groq+Jev)."
    )


def print_economic_summary(economic_summaries):
    """Print per-mode economic cost summary (Phase 11)."""

    print("\n" + "=" * 72)
    print("ECONOMIC COST SUMMARY (estimated equivalent cost, USD)")
    print("=" * 72)

    header = (
        f"{'mode':<6}{'runs':>6}{'groq est.':>12}{'jev est.':>12}"
        f"{'total est.':>12}{'avg/task':>12}{'groq %':>8}{'jev %':>8}"
    )
    print(header)
    print("-" * len(header))

    for mode in sorted(economic_summaries):
        s = economic_summaries[mode]
        groq_pct = (
            f"{s.groq_cost_contribution * 100:>7.1f}"
            if s.groq_cost_contribution is not None
            else "     —"
        )
        jev_pct = (
            f"{s.jev_cost_contribution * 100:>7.1f}"
            if s.jev_cost_contribution is not None
            else "     —"
        )
        print(
            f"{s.mode:<6}{s.run_count:>6}"
            f"{s.total_groq_estimated_cost:>12.6f}"
            f"{s.total_jev_estimated_cost:>12.6f}"
            f"{s.total_estimated_cost:>12.6f}"
            f"{(s.avg_cost_per_task if s.avg_cost_per_task is not None else 0):>12.6f}"
            f"{groq_pct}{jev_pct}"
        )

    print("-" * len(header))
    print(
        "Estimated equivalent cost applies reference paid pricing to recorded "
        "tokens; it is not actual billing. Actual expenditure is tracked "
        "separately (Groq free tier = $0; Jev actual must come from its "
        "billing route). Pricing version: "
        f"{get_pricing_config().groq_gpt_oss_120b.pricing_version}."
    )


def print_threshold_analysis(runs):
    """
    Lightweight Mode C threshold analysis.

    Uses only the escalation probabilities actually recorded in each
    run's decision history. With no observations at or below the
    thresholds this is reported as a data gap, not as evidence that the
    thresholds are correct.
    """

    print("\n" + "=" * 72)
    print("MODE C THRESHOLD ANALYSIS (provisional defaults)")
    print("=" * 72)
    print("tool_confidence_threshold = 0.60")
    print("completion_ambiguity band = [0.50, 0.70)")

    decisions = []
    for run in runs:
        for entry in run["execution"].get("decision_history", []):
            if isinstance(entry, dict):
                decisions.append({
                    "tool_confidence": entry.get("tool_confidence"),
                    "completion_probability": entry.get(
                        "completion_probability"
                    ),
                    "escalated": entry.get("escalated") is True
                })

    if not decisions:
        print("\nNo Mode C decision history recorded — nothing to analyse.")
        return

    tool_values = [
        d["tool_confidence"] for d in decisions
        if isinstance(d["tool_confidence"], (int, float))
    ]
    completion_values = [
        d["completion_probability"] for d in decisions
        if isinstance(d["completion_probability"], (int, float))
    ]
    escalations = sum(1 for d in decisions if d["escalated"])

    print(f"\ndecisions recorded        : {len(decisions)}")
    print(f"escalations fired         : {escalations}")

    if tool_values:
        below = sum(1 for v in tool_values if v <= 0.60)
        print(
            f"tool confidence <= 0.60   : {below}/{len(tool_values)}"
        )
        print(
            f"tool confidence range     : "
            f"{min(tool_values):.2f} .. {max(tool_values):.2f}"
        )

    if completion_values:
        in_band = sum(
            1 for v in completion_values
            if 0.50 <= v < 0.70
        )
        print(
            f"completion in [0.50,0.70) : "
            f"{in_band}/{len(completion_values)}"
        )
        print(
            f"completion range          : "
            f"{min(completion_values):.2f} .. {max(completion_values):.2f}"
        )

    print(
        "\nFinding: the recorded decisions sit outside the escalation "
        "thresholds, so the escalation branches were not exercised by "
        "this dataset."
    )
    print(
        "This is a data gap, not evidence that the defaults are "
        "correct. Calibration requires observations near the "
        "thresholds; do not change production defaults on this data."
    )


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------


def _confirm_live(args):
    """Return True only when the user explicitly opts into live runs."""

    if not args.live:
        return False

    if args.max_live_runs is None or args.max_live_runs < 1:
        print("ERROR: --live requires --max-live-runs >= 1.")
        return False

    if not args.yes:
        print("WARNING: you requested a LIVE benchmark run.")
        print("This will call the real Groq and/or Jev APIs and incur")
        print(f"real token cost, bounded by --max-live-runs "
              f"({args.max_live_runs}).")
        print("Re-run with --yes to confirm. Aborting.")
        return False

    print(LIVE_CONFIRMATION)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Phase 7 benchmark: compare Modes A, B, C."
    )

    parser.add_argument(
        "--mode", choices=["A", "B", "C", "all"], default="all",
        help="Which mode(s) to benchmark (default: all)."
    )
    parser.add_argument(
        "--tasks", default=None,
        help="Path to tasks JSON (default: data/tasks.json)."
    )
    parser.add_argument(
        "--repetitions", type=int, default=1,
        help="How many times to repeat each (task, mode) pair."
    )
    parser.add_argument(
        "--max-iterations", type=int, default=5,
        help="Per-run agent iteration limit."
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Opt in to live API calls (mocked otherwise)."
    )
    parser.add_argument(
        "--max-live-runs", type=int, default=0,
        help="Hard cap on live executions (required with --live)."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Confirm the live-run cost warning without prompting."
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-run progress lines."
    )
    parser.add_argument(
        "--output", default=None,
        help="Where to write results (default: experiments/)."
    )
    parser.add_argument(
        "--threshold-analysis", action="store_true",
        help="Print Mode C threshold analysis after the summary."
    )

    args = parser.parse_args()

    if args.live and not _confirm_live(args):
        sys.exit(1)

    modes = (
        ["A", "B", "C"] if args.mode == "all" else [args.mode]
    )

    execution_type = "live" if args.live else "mocked"

    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        logger = ExperimentLogger(
            csv_path=out_dir / "benchmark_results.csv",
            jsonl_path=out_dir / "benchmark_results.jsonl"
        )
    else:
        logger = ExperimentLogger()

    runner = BenchmarkRunner(
        tasks_path=args.tasks,
        logger=logger,
        execution_type=execution_type,
        max_iterations=args.max_iterations
    )

    print(
        f"Running benchmark [{execution_type}] modes={modes} "
        f"tasks={len(runner.tasks)} repetitions={args.repetitions}"
    )

    if args.live:
        total = len(runner.tasks) * len(modes) * args.repetitions
        if total > args.max_live_runs:
            print(
                f"ERROR: benchmark would execute {total} live runs, "
                f"exceeding the budget of {args.max_live_runs}."
            )
            sys.exit(1)
        print(f"Live budget: {args.max_live_runs} execution(s).")

    results = runner.run_benchmark(
        modes=modes, repetitions=args.repetitions
    )

    # Per-run progress / error reporting.
    if not args.quiet:
        for mode in modes:
            for run in results[mode]:
                status = run["verification"].outcome
                flag = "ERROR" if run["error"] else status
                print(
                    f"  {mode} {run['task_id']:<32} "
                    f"iter{run['metrics'].get('iterations') or 0:>2} "
                    f"-> {flag}"
                )

    summaries = {
        mode: summarize_runs(
            [
                {
                    "outcome": run["verification"].outcome,
                    "metrics": run["metrics"]
                }
                for run in results[mode]
            ],
            mode=mode
        )
        for mode in modes
    }

    # Calculate economic summaries per mode
    economic_calculator = EconomicMetricsCalculator()
    economic_summaries = {}
    for mode in modes:
        economic_task_metrics = [
            economic_calculator.create_task_metrics_from_execution(
                task_id=run["task_id"],
                mode=mode,
                execution_metrics=run["metrics"],
                execution_type=run.get("execution_type", "mocked")
            )
            for run in results[mode]
        ]

        economic_summaries[mode] = (
            economic_calculator.aggregate_economic_metrics(
                economic_task_metrics, mode
            )
        )

    print_summary(summaries)

    # Print economic cost summary (Phase 11)
    print_economic_summary(economic_summaries)

    if args.threshold_analysis and "C" in results:
        print_threshold_analysis(results["C"])
    elif args.threshold_analysis:
        print(
            "\nThreshold analysis requested but Mode C was not run."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
