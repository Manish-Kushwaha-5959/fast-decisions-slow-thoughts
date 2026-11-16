"""
Economic metrics for cost accounting and evaluation across experimental modes.

Implements Phase 11 requirements: model cost accounting and economic evaluation.
Calculates estimated economic costs of completing tasks across all three modes.

Key design decisions:
- Token usage fields are NOT duplicated here; they come from extract_run_metrics.
- Only cost fields and metadata are added to avoid overwriting None values
  (e.g., Mode A has no Jev usage, so jev_* tokens stay None).
- Estimated cost applies reference pricing to recorded tokens.
- Actual expenditure is tracked separately (Groq free tier = $0).
"""

from typing import Optional, Literal
from dataclasses import dataclass, field
from config.pricing import (
    get_pricing_config,
    PRICING_VERSION,
    PRICING_EFFECTIVE_DATE
)


@dataclass
class TaskEconomicMetrics:
    """Economic metrics for one task execution."""

    task_id: str
    mode: str
    # Token usage (from provider-reported usage, not duplicated in logs)
    groq_input_tokens: int
    groq_output_tokens: int
    groq_total_tokens: int
    jev_input_tokens: int
    jev_output_tokens: int
    jev_total_tokens: int
    # Cost calculations (estimated = reference pricing; actual = billed)
    groq_estimated_cost: float = 0.0
    groq_actual_cost: float = 0.0
    jev_estimated_cost: float = 0.0
    jev_actual_cost: float = 0.0
    total_estimated_cost: float = 0.0
    total_actual_cost: float = 0.0
    # Metadata
    usage_measurement_method: str = "actual"
    pricing_version: str = PRICING_VERSION
    pricing_date: str = PRICING_EFFECTIVE_DATE
    groq_usage: bool = True
    jev_usage: bool = True
    escalation_count: int = 0
    has_live_api_calls: bool = False
    free_tier_used: bool = False

    def __post_init__(self) -> None:
        if not self.pricing_date:
            self.pricing_date = PRICING_EFFECTIVE_DATE
        self._update_costs()

    def _update_costs(self) -> None:
        """Update cost fields based on token usage and pricing config."""
        self.groq_estimated_cost = self._calculate_groq_estimated_cost()
        self.jev_estimated_cost = self._calculate_jev_estimated_cost()
        self.total_estimated_cost = (
            self.groq_estimated_cost + self.jev_estimated_cost
        )
        # Actual expenditure: Groq free tier = $0; Jev typically free.
        # These are placeholder values; real billing data would come from
        # provider dashboards, not token counts.
        self.groq_actual_cost = 0.0 if self.free_tier_used else self.groq_estimated_cost
        self.jev_actual_cost = 0.0
        self.total_actual_cost = self.groq_actual_cost + self.jev_actual_cost

    def _calculate_groq_estimated_cost(self) -> float:
        pricing = get_pricing_config().get_pricing_for_provider("groq")
        if pricing is None:
            return 0.0
        return pricing.calculate_cost(
            self.groq_input_tokens, self.groq_output_tokens
        )

    def _calculate_jev_estimated_cost(self) -> float:
        pricing = get_pricing_config().get_pricing_for_provider("jev")
        if pricing is None:
            return 0.0
        return pricing.calculate_cost(
            self.jev_input_tokens, self.jev_output_tokens
        )

    def add_escalation(self, escalation_cost: float = 0.0) -> None:
        """Add escalation review cost to Groq estimated cost.

        The escalation count is set at construction from the recorded
        decision history; this method only accumulates advisory cost.
        """
        self.groq_estimated_cost += escalation_cost
        self.total_estimated_cost = (
            self.groq_estimated_cost + self.jev_estimated_cost
        )

    def to_dict(self) -> dict:
        """Return cost fields only (no token fields to avoid overwriting None)."""
        return {
            "groq_estimated_cost": self.groq_estimated_cost,
            "jev_estimated_cost": self.jev_estimated_cost,
            "total_estimated_cost": self.total_estimated_cost,
            "groq_actual_cost": self.groq_actual_cost,
            "jev_actual_cost": self.jev_actual_cost,
            "total_actual_cost": self.total_actual_cost,
            "usage_measurement_method": self.usage_measurement_method,
            "pricing_version": self.pricing_version,
            "pricing_date": self.pricing_date
        }


@dataclass
class EconomicMetricsSummary:
    """Aggregated economic metrics across multiple runs of one mode."""

    mode: str
    run_count: int = 0
    total_groq_estimated_cost: float = 0.0
    total_groq_actual_cost: float = 0.0
    total_jev_estimated_cost: float = 0.0
    total_jev_actual_cost: float = 0.0
    total_estimated_cost: float = 0.0
    total_actual_cost: float = 0.0
    total_groq_input_tokens: int = 0
    total_groq_output_tokens: int = 0
    total_groq_tokens: int = 0
    total_jev_input_tokens: int = 0
    total_jev_output_tokens: int = 0
    total_jev_tokens: int = 0
    avg_cost_per_task: Optional[float] = None
    median_cost_per_task: Optional[float] = None
    cost_per_successful_task: Optional[float] = None
    cost_per_failed_task: Optional[float] = None
    cost_by_mode: dict = field(default_factory=dict)
    groq_cost_contribution: Optional[float] = None
    jev_cost_contribution: Optional[float] = None

    def update_with_task_metrics(self, task_metrics: TaskEconomicMetrics) -> None:
        """Aggregate one task's economic metrics into this summary."""
        self.run_count += 1
        self.total_groq_estimated_cost += task_metrics.groq_estimated_cost
        self.total_groq_actual_cost += task_metrics.groq_actual_cost
        self.total_jev_estimated_cost += task_metrics.jev_estimated_cost
        self.total_jev_actual_cost += task_metrics.jev_actual_cost
        self.total_estimated_cost += task_metrics.total_estimated_cost
        self.total_actual_cost += task_metrics.total_actual_cost
        self.total_groq_input_tokens += task_metrics.groq_input_tokens
        self.total_groq_output_tokens += task_metrics.groq_output_tokens
        self.total_groq_tokens += task_metrics.groq_total_tokens
        self.total_jev_input_tokens += task_metrics.jev_input_tokens
        self.total_jev_output_tokens += task_metrics.jev_output_tokens
        self.total_jev_tokens += task_metrics.jev_total_tokens

    def finalize(
        self,
        verified_successes: int = 0,
        verified_failures: int = 0,
        individual_costs: Optional[list] = None
    ) -> None:
        """Compute derived per-task metrics after all runs are aggregated."""
        if self.run_count > 0:
            self.avg_cost_per_task = self.total_estimated_cost / self.run_count
            self.cost_by_mode = {self.mode: self.total_estimated_cost}
        if self.total_estimated_cost > 0:
            self.groq_cost_contribution = (
                self.total_groq_estimated_cost / self.total_estimated_cost
            )
            self.jev_cost_contribution = (
                self.total_jev_estimated_cost / self.total_estimated_cost
            )
        if verified_successes > 0:
            self.cost_per_successful_task = (
                self.total_estimated_cost / verified_successes
            )
        if verified_failures > 0:
            self.cost_per_failed_task = (
                self.total_estimated_cost / verified_failures
            )

        # Median cost per task from individual task costs.
        if individual_costs:
            sorted_costs = sorted(individual_costs)
            n = len(sorted_costs)
            mid = n // 2
            if n % 2 == 1:
                self.median_cost_per_task = sorted_costs[mid]
            else:
                self.median_cost_per_task = (
                    sorted_costs[mid - 1] + sorted_costs[mid]
                ) / 2


class EconomicMetricsCalculator:
    """Builds TaskEconomicMetrics from execution records."""

    def __init__(self) -> None:
        self.pricing = get_pricing_config()

    def create_task_metrics_from_execution(
        self,
        task_id: str,
        mode: str,
        execution_metrics: dict,
        execution_type: Literal["mocked", "live"] = "mocked",
        escalation_count: Optional[int] = None
    ) -> TaskEconomicMetrics:
        """Create economic metrics from extracted run metrics."""
        groq_input = execution_metrics.get("llm_input_tokens")
        groq_output = execution_metrics.get("llm_output_tokens")
        groq_total = execution_metrics.get("llm_total_tokens")
        jev_input = execution_metrics.get("jev_input_tokens")
        jev_output = execution_metrics.get("jev_output_tokens")
        jev_total = execution_metrics.get("jev_total_tokens")

        # Mode A never invokes Jev; its Jev metrics stay None.
        jev_usage = mode in ("B", "C")

        # Escalation count from Mode C decision history if not provided.
        if escalation_count is None:
            escalation_count = execution_metrics.get("escalation_count") or 0

        task = TaskEconomicMetrics(
            task_id=task_id,
            mode=mode,
            groq_input_tokens=groq_input or 0,
            groq_output_tokens=groq_output or 0,
            groq_total_tokens=groq_total or 0,
            jev_input_tokens=jev_input or 0,
            jev_output_tokens=jev_output or 0,
            jev_total_tokens=jev_total or 0,
            groq_usage=True,
            jev_usage=jev_usage,
            has_live_api_calls=(execution_type == "live"),
            free_tier_used=True,  # Groq free tier assumed for mocked runs
            # Label how the usage was obtained: live runs carry
            # provider-reported usage; mocked runs carry synthetic
            # client usage (never presented as provider data).
            usage_measurement_method=(
                "actual" if execution_type == "live" else "mocked"
            ),
            pricing_version=PRICING_VERSION,
            escalation_count=escalation_count
        )

        # Add advisory escalation review cost (Mode C Groq reviews).
        escalation_cost = self._calculate_escalation_cost(
            execution_metrics, mode
        )
        if escalation_cost > 0:
            task.add_escalation(escalation_cost)

        return task

    def _calculate_escalation_cost(self, execution_metrics: dict, mode: str) -> float:
        """Estimate cost of Groq advisory reviews in Mode C escalations."""
        if mode != "C":
            return 0.0
        escalation_count = execution_metrics.get("escalation_count") or 0
        if not escalation_count:
            return 0.0
        # Advisory review token estimate (conservative; real usage would
        # come from the escalation LLM call records).
        escalation_input = 10
        escalation_output = 5
        pricing = self.pricing.get_pricing_for_provider("groq")
        if pricing is None:
            return 0.0
        return pricing.calculate_cost(
            escalation_input, escalation_output
        ) * escalation_count

    def aggregate_economic_metrics(
        self,
        task_metrics_list: list[TaskEconomicMetrics],
        mode: str,
        verified_successes: int = 0,
        verified_failures: int = 0
    ) -> EconomicMetricsSummary:
        """Aggregate task-level economic metrics into a mode summary."""
        summary = EconomicMetricsSummary(mode=mode)
        individual_costs = []
        for task_metrics in task_metrics_list:
            summary.update_with_task_metrics(task_metrics)
            individual_costs.append(task_metrics.total_estimated_cost)
        summary.finalize(
            verified_successes, verified_failures, individual_costs
        )
        return summary
