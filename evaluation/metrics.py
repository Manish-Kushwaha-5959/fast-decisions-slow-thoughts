"""
Metric collection and aggregation for the Phase 7 benchmark.

Design rules:
- Provider metrics stay distinguishable: Groq (LLM) tokens and Jev
  tokens are never merged into one provider's bucket. ``combined``
  is computed once, from provider totals, and is the only summed
  figure.
- Missing values are recorded as ``None`` / empty lists, never
  invented or defaulted to zero when the underlying field is absent.
- Escalation counts are read from ``decision_history`` (Mode C), not
  from API-call counts; one escalation is one decision review, not
  one provider request.
- An ``agent_reported_success`` field is kept separate from the
  independently verified outcome.
"""

from dataclasses import dataclass
from statistics import median
from typing import Any, Optional


def _safe_int(value: Any) -> Optional[int]:
    """Return an int, or None when the value is missing/invalid."""

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Return a float, or None when the value is missing/invalid."""

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class MetricSummary:
    """Aggregated benchmark metrics for one mode over N runs."""

    mode: str
    run_count: int = 0
    # Independent verification.
    verified_successes: int = 0
    verified_failures: int = 0
    unverifiable: int = 0
    agent_reported_successes: int = 0
    # Latency (seconds); None when unavailable.
    total_latency_seconds: Optional[float] = None
    mean_latency_seconds: Optional[float] = None
    # Provider token usage.
    llm_input_tokens: Optional[int] = None
    llm_output_tokens: Optional[int] = None
    llm_total_tokens: Optional[int] = None
    jev_input_tokens: Optional[int] = None
    jev_output_tokens: Optional[int] = None
    jev_total_tokens: Optional[int] = None
    combined_tokens: Optional[int] = None
    # Effort.
    mean_iterations: Optional[float] = None
    total_tool_calls: Optional[int] = None
    total_tool_execution_failures: Optional[int] = None
    # Mode C escalation behaviour.
    escalation_count: Optional[int] = None
    tool_selection_escalations: Optional[int] = None
    completion_escalations: Optional[int] = None
    escalation_frequency: Optional[float] = None
    # Mode C only: how often Groq's advisory review was usable.
    escalation_succeeded_count: Optional[int] = None
    # Per-mode success rate against independent verification.
    verified_success_rate: Optional[float] = None
    agent_reported_success_rate: Optional[float] = None
    # Economic cost fields (Phase 11). None when no run in the mode
    # carries cost data (e.g. historical rows predating Phase 11).
    groq_estimated_cost: Optional[float] = None
    jev_estimated_cost: Optional[float] = None
    total_estimated_cost: Optional[float] = None
    groq_actual_cost: Optional[float] = None
    jev_actual_cost: Optional[float] = None
    total_actual_cost: Optional[float] = None
    avg_cost_per_task: Optional[float] = None
    median_cost_per_task: Optional[float] = None
    cost_by_mode: Optional[dict] = None
    groq_cost_contribution: Optional[float] = None
    jev_cost_contribution: Optional[float] = None
    total_runs_in_mode: Optional[int] = None
    cost_per_successful_task: Optional[float] = None
    cost_per_failed_task: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "run_count": self.run_count,
            "verified_successes": self.verified_successes,
            "verified_failures": self.verified_failures,
            "unverifiable": self.unverifiable,
            "agent_reported_successes": self.agent_reported_successes,
            "verified_success_rate": self.verified_success_rate,
            "agent_reported_success_rate": (
                self.agent_reported_success_rate
            ),
            "total_latency_seconds": self.total_latency_seconds,
            "mean_latency_seconds": self.mean_latency_seconds,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_total_tokens": self.llm_total_tokens,
            "jev_input_tokens": self.jev_input_tokens,
            "jev_output_tokens": self.jev_output_tokens,
            "jev_total_tokens": self.jev_total_tokens,
            "combined_tokens": self.combined_tokens,
            "mean_iterations": self.mean_iterations,
            "total_tool_calls": self.total_tool_calls,
            "total_tool_execution_failures": (
                self.total_tool_execution_failures
            ),
            "escalation_count": self.escalation_count,
            "tool_selection_escalations": (
                self.tool_selection_escalations
            ),
            "completion_escalations": self.completion_escalations,
            "escalation_frequency": self.escalation_frequency,
            "escalation_succeeded_count": (
                self.escalation_succeeded_count
            ),
            # Phase 11 economic cost fields
            "groq_estimated_cost": self.groq_estimated_cost,
            "jev_estimated_cost": self.jev_estimated_cost,
            "total_estimated_cost": self.total_estimated_cost,
            "groq_actual_cost": self.groq_actual_cost,
            "jev_actual_cost": self.jev_actual_cost,
            "total_actual_cost": self.total_actual_cost,
            "avg_cost_per_task": self.avg_cost_per_task,
            "median_cost_per_task": self.median_cost_per_task,
            "cost_by_mode": self.cost_by_mode,
            "groq_cost_contribution": self.groq_cost_contribution,
            "jev_cost_contribution": self.jev_cost_contribution,
            "total_runs_in_mode": self.total_runs_in_mode,
            "cost_per_successful_task": self.cost_per_successful_task,
            "cost_per_failed_task": self.cost_per_failed_task
        }


def extract_run_metrics(execution: dict) -> dict:
    """
    Flatten one agent run record into provider-distinguishable metrics.

    Accepts ``AgentRunResult.to_dict()`` / ``HybridAgentRunResult.to_dict()``
    output, plus benchmark error records. Missing fields become ``None``.
    """

    if not isinstance(execution, dict):
        execution = {}

    llm_input = _safe_int(execution.get("llm_input_tokens"))
    llm_output = _safe_int(execution.get("llm_output_tokens"))
    llm_total = _safe_int(execution.get("llm_total_tokens"))
    jev_input = _safe_int(execution.get("jev_input_tokens"))
    jev_output = _safe_int(execution.get("jev_output_tokens"))
    jev_total = _safe_int(execution.get("jev_total_tokens"))

    # Combined tokens are computed once from the provider totals.
    if llm_total is not None and jev_total is not None:
        combined = llm_total + jev_total
    elif llm_total is not None:
        combined = llm_total
    elif jev_total is not None:
        combined = jev_total
    else:
        combined = None

    # Jev is only used by Modes B/C; Mode A has no Jev metrics and
    # they stay None rather than being fabricated as zero.
    decision_history = execution.get("decision_history")
    if not isinstance(decision_history, list):
        decision_history = []

    tool_calls = execution.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []

    tool_failures = sum(
        1 for call in tool_calls
        if isinstance(call, dict)
        and call.get("execution_status") == "error"
    )

    escalations = [
        entry for entry in decision_history
        if isinstance(entry, dict) and entry.get("escalated") is True
    ]

    tool_selection_escalations = sum(
        1 for entry in escalations
        if entry.get("decision_type") == "tool_selection"
    )
    completion_escalations = sum(
        1 for entry in escalations
        if entry.get("decision_type") == "task_completion"
    )
    escalation_succeeded = sum(
        1 for entry in escalations
        if entry.get("escalation_succeeded") is True
    )

    iterations = _safe_int(execution.get("iterations"))
    escalation_frequency = (
        len(escalations) / iterations
        if iterations and iterations > 0
        else None
    )

    return {
        "llm_input_tokens": llm_input,
        "llm_output_tokens": llm_output,
        "llm_total_tokens": llm_total,
        "jev_input_tokens": jev_input,
        "jev_output_tokens": jev_output,
        "jev_total_tokens": jev_total,
        "combined_tokens": combined,
        "llm_latency_seconds": _safe_float(
            execution.get("llm_latency_seconds")
        ),
        "jev_latency_seconds": _safe_float(
            execution.get("jev_latency_seconds")
        ),
        "tool_latency_seconds": _safe_float(
            execution.get("tool_latency_seconds")
        ),
        "total_latency_seconds": _safe_float(
            execution.get("total_latency_seconds")
        ),
        "iterations": iterations,
        "tool_calls": len(tool_calls),
        "tool_execution_failures": tool_failures,
        "escalation_count": len(escalations),
        "tool_selection_escalations": tool_selection_escalations,
        "completion_escalations": completion_escalations,
        "escalation_frequency": escalation_frequency,
        "escalation_succeeded_count": escalation_succeeded,
        "agent_reported_success": execution.get("success"),
        "termination_reason": execution.get("termination_reason")
    }


def _mean(values: list[float]) -> Optional[float]:
    """Mean of a non-empty list, else None (no invented value)."""

    usable = [value for value in values if value is not None]

    if not usable:
        return None

    return sum(usable) / len(usable)


def _sum(values: list[int]) -> Optional[int]:
    """Sum of a non-empty list, else None (no invented value)."""

    usable = [value for value in values if value is not None]

    if not usable:
        return None

    return sum(usable)


def summarize_runs(runs: list[dict], mode: str) -> MetricSummary:
    """
    Aggregate verified benchmark runs for one mode.

    ``runs`` is a list of per-run dictionaries, each carrying at
    least ``outcome`` (verified/failed/unverifiable), the raw run
    record, and the extracted metrics.
    """

    summary = MetricSummary(mode=mode, run_count=len(runs))

    if not runs:
        return summary

    latencies: list[float] = []
    iterations: list[float] = []
    total_iterations = 0

    for run in runs:
        outcome = run.get("outcome")
        metrics = run.get("metrics", {}) or {}

        if outcome == "verified":
            summary.verified_successes += 1
        elif outcome == "failed":
            summary.verified_failures += 1
        else:
            summary.unverifiable += 1

        if metrics.get("agent_reported_success") is True:
            summary.agent_reported_successes += 1

        latency = metrics.get("total_latency_seconds")
        if latency is not None:
            latencies.append(latency)

        iteration_count = metrics.get("iterations")
        if iteration_count is not None:
            iterations.append(float(iteration_count))
            total_iterations += iteration_count

    def _total(key: str) -> Optional[int]:
        """Sum only runs where the provider metric was recorded."""

        values = [
            run.get("metrics", {}).get(key)
            for run in runs
        ]
        values = [value for value in values if value is not None]

        return sum(values) if values else None

    summary.llm_input_tokens = _total("llm_input_tokens")
    summary.llm_output_tokens = _total("llm_output_tokens")
    summary.llm_total_tokens = _total("llm_total_tokens")
    summary.jev_input_tokens = _total("jev_input_tokens")
    summary.jev_output_tokens = _total("jev_output_tokens")
    summary.jev_total_tokens = _total("jev_total_tokens")
    summary.combined_tokens = _total("combined_tokens")
    summary.total_tool_calls = _total("tool_calls")
    summary.total_tool_execution_failures = _total(
        "tool_execution_failures"
    )
    summary.escalation_count = _total("escalation_count")
    summary.tool_selection_escalations = _total(
        "tool_selection_escalations"
    )
    summary.completion_escalations = _total("completion_escalations")
    summary.escalation_succeeded_count = _total(
        "escalation_succeeded_count"
    )
    summary.total_latency_seconds = _sum(latencies)
    summary.mean_latency_seconds = _mean(latencies)
    summary.mean_iterations = _mean(iterations)

    # Phase 11: economic cost aggregation. Costs are summed only across
    # runs that actually carry cost data; historical rows without the
    # fields keep every cost aggregate as None (never invented).
    def _float_total(key: str) -> Optional[float]:
        values = [
            run.get("metrics", {}).get(key)
            for run in runs
        ]
        values = [value for value in values if value is not None]
        return float(sum(values)) if values else None

    summary.groq_estimated_cost = _float_total("groq_estimated_cost")
    summary.jev_estimated_cost = _float_total("jev_estimated_cost")
    summary.total_estimated_cost = _float_total("total_estimated_cost")
    summary.groq_actual_cost = _float_total("groq_actual_cost")
    summary.jev_actual_cost = _float_total("jev_actual_cost")
    summary.total_actual_cost = _float_total("total_actual_cost")
    summary.total_runs_in_mode = len(runs)

    if summary.total_estimated_cost is not None and summary.run_count:
        summary.avg_cost_per_task = (
            summary.total_estimated_cost / summary.run_count
        )

    individual_costs = [
        run.get("metrics", {}).get("total_estimated_cost")
        for run in runs
    ]
    individual_costs = [c for c in individual_costs if c is not None]
    if individual_costs:
        summary.median_cost_per_task = median(individual_costs)

    if summary.total_estimated_cost:
        summary.cost_by_mode = {mode: summary.total_estimated_cost}
        if summary.groq_estimated_cost is not None:
            summary.groq_cost_contribution = (
                summary.groq_estimated_cost / summary.total_estimated_cost
            )
        if summary.jev_estimated_cost is not None:
            summary.jev_cost_contribution = (
                summary.jev_estimated_cost / summary.total_estimated_cost
            )

    # Cost per successful / failed task, where meaningful.
    if summary.verified_successes and summary.total_estimated_cost is not None:
        summary.cost_per_successful_task = (
            summary.total_estimated_cost / summary.verified_successes
        )
    if summary.verified_failures and summary.total_estimated_cost is not None:
        summary.cost_per_failed_task = (
            summary.total_estimated_cost / summary.verified_failures
        )

    # Escalation frequency: escalation events per control-loop
    # iteration, aggregated across all runs of the mode.
    if summary.escalation_count and total_iterations:
        summary.escalation_frequency = (
            summary.escalation_count / total_iterations
        )

    # Rates are derived from independently verified outcomes, never
    # from the agent's self-report.
    summary.verified_success_rate = (
        summary.verified_successes / summary.run_count
        if summary.run_count else None
    )
    summary.agent_reported_success_rate = (
        summary.agent_reported_successes / summary.run_count
        if summary.run_count else None
    )

    if summary.run_count and summary.escalation_count is not None:
        summary.escalation_frequency = (
            summary.escalation_count / summary.run_count
        )

    return summary
