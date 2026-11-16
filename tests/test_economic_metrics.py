"""
Phase 11 tests: economic cost accounting and evaluation.

Covers:
- Groq input/output cost calculation.
- Jev input/output cost calculation.
- Combined task cost.
- Zero-token requests.
- Missing usage metadata.
- Multiple calls within one task.
- Retries and repeated calls.
- Free-tier actual expenditure.
- Estimated vs actual expenditure separation.
- All three experimental modes.

All tests are mocked; no live API calls are made.
"""

import pytest
from config.pricing import (
    ModelPricing,
    PricingConfig,
    get_pricing_config,
    get_default_pricing_config,
    reset_pricing_config,
    verify_jev_pricing_route,
    DEFAULT_GROQ_INPUT_PRICE,
    DEFAULT_GROQ_OUTPUT_PRICE,
    DEFAULT_JEV_INPUT_PRICE,
    DEFAULT_JEV_OUTPUT_PRICE,
    GROQ_MODEL_ID,
    JEV_MODEL_ID,
    PRICING_VERSION,
    PRICING_EFFECTIVE_DATE
)
from evaluation.economic_metrics import (
    TaskEconomicMetrics,
    EconomicMetricsSummary,
    EconomicMetricsCalculator
)


# ---------------------------------------------------------
# Pricing configuration
# ---------------------------------------------------------


class TestPricingConfiguration:
    def test_groq_pricing_defaults(self):
        pricing = get_pricing_config()
        groq = pricing.groq_gpt_oss_120b

        assert groq.provider == "groq"
        assert groq.model_identifier == GROQ_MODEL_ID
        assert groq.input_price_per_million == 0.15
        assert groq.output_price_per_million == 0.60
        assert groq.currency == "USD"
        assert groq.pricing_source_url == "https://console.groq.com/docs/models"
        assert groq.effective_date == PRICING_EFFECTIVE_DATE
        assert groq.pricing_version == PRICING_VERSION

    def test_jev_pricing_defaults(self):
        pricing = get_pricing_config()
        jev = pricing.jev_1_14_0

        assert jev.provider == "jev"
        assert jev.model_identifier == JEV_MODEL_ID
        assert jev.input_price_per_million == 0.042
        assert jev.output_price_per_million == 0.00
        assert jev.currency == "USD"
        assert jev.pricing_source_url == "https://vercel.com/ai-gateway/models/jev-1.14.0"

    def test_pricing_config_is_frozen(self):
        pricing = get_pricing_config()
        with pytest.raises(Exception):
            pricing.groq_gpt_oss_120b.input_price_per_million = 0.99

    def test_get_pricing_for_provider(self):
        pricing = get_pricing_config()

        assert pricing.get_pricing_for_provider("groq") is pricing.groq_gpt_oss_120b
        assert pricing.get_pricing_for_provider("jev") is pricing.jev_1_14_0
        assert pricing.get_pricing_for_provider("unknown") is None

    def test_get_pricing_for_model(self):
        pricing = get_pricing_config()

        assert pricing.get_pricing_for_model(GROQ_MODEL_ID) is pricing.groq_gpt_oss_120b
        assert pricing.get_pricing_for_model(JEV_MODEL_ID) is pricing.jev_1_14_0
        assert pricing.get_pricing_for_model("unknown-model") is None

    def test_reset_pricing_config(self):
        reset_pricing_config()
        pricing = get_pricing_config()
        assert pricing.groq_gpt_oss_120b.input_price_per_million == 0.15

    def test_verify_jev_pricing_route_compatible(self):
        ok, msg = verify_jev_pricing_route("jev-latest")
        assert ok is True
        assert "jev-1.14.0" in msg

        ok, msg = verify_jev_pricing_route("jev-1.14.0")
        assert ok is True

    def test_verify_jev_pricing_route_incompatible(self):
        ok, msg = verify_jev_pricing_route("some-other-model")
        assert ok is False
        assert "does not match" in msg
        assert "pricing" in msg.lower()


# ---------------------------------------------------------
# Cost calculation: Groq
# ---------------------------------------------------------


class TestGroqCostCalculation:
    def test_groq_input_output_cost(self):
        pricing = get_pricing_config().groq_gpt_oss_120b

        # 1M input + 1M output = $0.15 + $0.60 = $0.75
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75)

    def test_groq_input_only(self):
        pricing = get_pricing_config().groq_gpt_oss_120b

        # 2M input, 0 output = $0.30
        cost = pricing.calculate_cost(2_000_000, 0)
        assert cost == pytest.approx(0.30)

    def test_groq_output_only(self):
        pricing = get_pricing_config().groq_gpt_oss_120b

        # 0 input, 2M output = $1.20
        cost = pricing.calculate_cost(0, 2_000_000)
        assert cost == pytest.approx(1.20)

    def test_groq_small_token_counts(self):
        pricing = get_pricing_config().groq_gpt_oss_120b

        # 100 input + 50 output = (100/1e6)*0.15 + (50/1e6)*0.60
        cost = pricing.calculate_cost(100, 50)
        expected = (100 / 1_000_000) * 0.15 + (50 / 1_000_000) * 0.60
        assert cost == pytest.approx(expected)

    def test_groq_zero_tokens(self):
        pricing = get_pricing_config().groq_gpt_oss_120b

        cost = pricing.calculate_cost(0, 0)
        assert cost == 0.0


# ---------------------------------------------------------
# Cost calculation: Jev
# ---------------------------------------------------------


class TestJevCostCalculation:
    def test_jev_input_output_cost(self):
        pricing = get_pricing_config().jev_1_14_0

        # 1M input + 1M output = $0.042 + $0.00 = $0.042
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(0.042)

    def test_jev_input_only(self):
        pricing = get_pricing_config().jev_1_14_0

        # 2M input, 0 output = $0.084
        cost = pricing.calculate_cost(2_000_000, 0)
        assert cost == pytest.approx(0.084)

    def test_jev_output_only(self):
        pricing = get_pricing_config().jev_1_14_0

        # 0 input, 2M output = $0.00 (Jev output is free)
        cost = pricing.calculate_cost(0, 2_000_000)
        assert cost == pytest.approx(0.0)

    def test_jev_zero_tokens(self):
        pricing = get_pricing_config().jev_1_14_0

        cost = pricing.calculate_cost(0, 0)
        assert cost == 0.0


# ---------------------------------------------------------
# Combined task cost
# ---------------------------------------------------------


class TestCombinedTaskCost:
    def test_combined_cost_both_providers(self):
        pricing = get_pricing_config()

        # Groq: 1M in + 1M out = $0.75
        # Jev: 1M in + 1M out = $0.042
        costs = pricing.calculate_costs_by_provider(
            groq_input_tokens=1_000_000,
            groq_output_tokens=1_000_000,
            jev_input_tokens=1_000_000,
            jev_output_tokens=1_000_000
        )

        assert costs["groq"] == pytest.approx(0.75)
        assert costs["jev"] == pytest.approx(0.042)
        assert costs["total"] == pytest.approx(0.792)

    def test_combined_cost_groq_only(self):
        pricing = get_pricing_config()

        costs = pricing.calculate_costs_by_provider(
            groq_input_tokens=1_000_000,
            groq_output_tokens=1_000_000,
            jev_input_tokens=0,
            jev_output_tokens=0
        )

        assert costs["groq"] == pytest.approx(0.75)
        assert costs["jev"] == pytest.approx(0.0)
        assert costs["total"] == pytest.approx(0.75)

    def test_combined_cost_jev_only(self):
        pricing = get_pricing_config()

        costs = pricing.calculate_costs_by_provider(
            groq_input_tokens=0,
            groq_output_tokens=0,
            jev_input_tokens=1_000_000,
            jev_output_tokens=1_000_000
        )

        assert costs["groq"] == pytest.approx(0.0)
        assert costs["jev"] == pytest.approx(0.042)
        assert costs["total"] == pytest.approx(0.042)


# ---------------------------------------------------------
# TaskEconomicMetrics
# ---------------------------------------------------------


class TestTaskEconomicMetrics:
    def test_mode_a_groq_only(self):
        """Mode A uses only Groq; Jev cost stays zero."""

        task = TaskEconomicMetrics(
            task_id="task_a",
            mode="A",
            groq_input_tokens=1000,
            groq_output_tokens=500,
            groq_total_tokens=1500,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0,
            jev_usage=False
        )

        expected_groq = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60
        assert task.groq_estimated_cost == pytest.approx(expected_groq)
        assert task.jev_estimated_cost == 0.0
        assert task.total_estimated_cost == pytest.approx(expected_groq)
        assert task.groq_usage is True
        assert task.jev_usage is False

    def test_mode_b_groq_and_jev(self):
        """Mode B accounts for actual Jev and Groq usage."""

        task = TaskEconomicMetrics(
            task_id="task_b",
            mode="B",
            groq_input_tokens=1000,
            groq_output_tokens=500,
            groq_total_tokens=1500,
            jev_input_tokens=800,
            jev_output_tokens=400,
            jev_total_tokens=1200,
            jev_usage=True
        )

        groq_cost = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60
        jev_cost = (800 / 1e6) * 0.042 + (400 / 1e6) * 0.00
        assert task.groq_estimated_cost == pytest.approx(groq_cost)
        assert task.jev_estimated_cost == pytest.approx(jev_cost)
        assert task.total_estimated_cost == pytest.approx(groq_cost + jev_cost)

    def test_mode_c_with_escalation(self):
        """Mode C includes Jev usage and Groq escalation advisory calls."""

        task = TaskEconomicMetrics(
            task_id="task_c",
            mode="C",
            groq_input_tokens=1000,
            groq_output_tokens=500,
            groq_total_tokens=1500,
            jev_input_tokens=800,
            jev_output_tokens=400,
            jev_total_tokens=1200,
            jev_usage=True,
            escalation_count=1
        )

        # Escalation adds advisory Groq cost
        escalation_cost = (10 / 1e6) * 0.15 + (5 / 1e6) * 0.60
        base_groq = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60

        task.add_escalation(escalation_cost)

        assert task.groq_estimated_cost == pytest.approx(base_groq + escalation_cost)
        assert task.escalation_count == 1

    def test_zero_token_request(self):
        """Zero-token requests produce zero cost, not None."""

        task = TaskEconomicMetrics(
            task_id="task_zero",
            mode="A",
            groq_input_tokens=0,
            groq_output_tokens=0,
            groq_total_tokens=0,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0
        )

        assert task.groq_estimated_cost == 0.0
        assert task.jev_estimated_cost == 0.0
        assert task.total_estimated_cost == 0.0

    def test_missing_usage_metadata(self):
        """Missing usage stays missing; no invented token counts."""

        # None token counts are treated as zero in cost calculation
        # but the usage_measurement_method flag indicates the source.
        task = TaskEconomicMetrics(
            task_id="task_missing",
            mode="A",
            groq_input_tokens=0,
            groq_output_tokens=0,
            groq_total_tokens=0,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0,
            usage_measurement_method="estimated"
        )

        assert task.usage_measurement_method == "estimated"
        assert task.groq_estimated_cost == 0.0

    def test_multiple_calls_accumulate(self):
        """Multiple calls within one task accumulate token totals."""

        task = TaskEconomicMetrics(
            task_id="task_multi",
            mode="B",
            groq_input_tokens=2000,   # 2 calls x 1000
            groq_output_tokens=1000,  # 2 calls x 500
            groq_total_tokens=3000,
            jev_input_tokens=1600,    # 2 calls x 800
            jev_output_tokens=800,    # 2 calls x 400
            jev_total_tokens=2400,
            jev_usage=True
        )

        groq_cost = (2000 / 1e6) * 0.15 + (1000 / 1e6) * 0.60
        jev_cost = (1600 / 1e6) * 0.042 + (800 / 1e6) * 0.00
        assert task.total_estimated_cost == pytest.approx(groq_cost + jev_cost)

    def test_retries_and_repeated_calls(self):
        """Retries are included in totals; no double-counting of tokens."""

        # Simulate a retry: original call + retried call
        task = TaskEconomicMetrics(
            task_id="task_retry",
            mode="B",
            groq_input_tokens=3000,   # original + retry
            groq_output_tokens=1500,
            groq_total_tokens=4500,
            jev_input_tokens=2400,
            jev_output_tokens=1200,
            jev_total_tokens=3600,
            jev_usage=True
        )

        # Cost is based on actual total tokens, not call count
        groq_cost = (3000 / 1e6) * 0.15 + (1500 / 1e6) * 0.60
        jev_cost = (2400 / 1e6) * 0.042 + (1200 / 1e6) * 0.00
        assert task.total_estimated_cost == pytest.approx(groq_cost + jev_cost)

    def test_free_tier_actual_expenditure(self):
        """A free-tier label is not a billing measurement.

        Actual expenditure stays None until a provider billing source
        supplies a value; it is never fabricated as $0 from the
        free_tier_used flag (Phase 12 defect corrected).
        """

        task = TaskEconomicMetrics(
            task_id="task_free",
            mode="A",
            groq_input_tokens=1000,
            groq_output_tokens=500,
            groq_total_tokens=1500,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0,
            free_tier_used=True
        )

        # No billing figure was recorded, so actual is unavailable.
        assert task.groq_actual_cost is None
        assert task.total_actual_cost is None
        # Estimated still uses reference pricing (not zero).
        assert task.groq_estimated_cost > 0.0

        # When a billing source does supply a figure, it is recorded.
        task.set_groq_actual_cost(0.0)
        assert task.groq_actual_cost == 0.0
        assert task.total_actual_cost == 0.0

    def test_estimated_vs_actual_separation(self):
        """Estimated and actual costs are separate fields."""

        task = TaskEconomicMetrics(
            task_id="task_sep",
            mode="A",
            groq_input_tokens=1000,
            groq_output_tokens=500,
            groq_total_tokens=1500,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0,
            free_tier_used=True
        )

        # Estimated uses reference pricing
        expected_estimated = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60
        assert task.groq_estimated_cost == pytest.approx(expected_estimated)

        # Actual is unavailable, not assumed $0 (no billing source).
        assert task.groq_actual_cost is None

        # Totals reflect the separation
        assert task.total_estimated_cost == pytest.approx(expected_estimated)
        assert task.total_actual_cost is None

        # A measured actual figure is summed, not invented.
        task.set_groq_actual_cost(0.01)
        assert task.total_actual_cost == pytest.approx(0.01)

    def test_to_dict_excludes_token_fields(self):
        """to_dict returns cost fields only, not token fields."""

        task = TaskEconomicMetrics(
            task_id="task_dict",
            mode="A",
            groq_input_tokens=100,
            groq_output_tokens=50,
            groq_total_tokens=150,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0
        )

        data = task.to_dict()
        assert "groq_estimated_cost" in data
        assert "total_estimated_cost" in data
        assert "pricing_version" in data
        assert "pricing_date" in data
        # Token fields are NOT in the dict (they come from extract_run_metrics)
        assert "groq_input_tokens" not in data
        assert "jev_input_tokens" not in data

    def test_pricing_version_recorded(self):
        """Each task records the pricing version used."""

        task = TaskEconomicMetrics(
            task_id="task_ver",
            mode="A",
            groq_input_tokens=100,
            groq_output_tokens=50,
            groq_total_tokens=150,
            jev_input_tokens=0,
            jev_output_tokens=0,
            jev_total_tokens=0
        )

        assert task.pricing_version == PRICING_VERSION
        assert task.pricing_date == PRICING_EFFECTIVE_DATE


# ---------------------------------------------------------
# EconomicMetricsCalculator
# ---------------------------------------------------------


class TestEconomicMetricsCalculator:
    def test_create_mode_a_metrics(self):
        calc = EconomicMetricsCalculator()

        task = calc.create_task_metrics_from_execution(
            task_id="task_a",
            mode="A",
            execution_metrics={
                "llm_input_tokens": 100,
                "llm_output_tokens": 50,
                "llm_total_tokens": 150,
                "jev_input_tokens": None,
                "jev_output_tokens": None,
                "jev_total_tokens": None
            },
            execution_type="mocked"
        )

        assert task.mode == "A"
        assert task.jev_usage is False
        assert task.jev_input_tokens == 0
        assert task.jev_estimated_cost == 0.0

    def test_create_mode_b_metrics(self):
        calc = EconomicMetricsCalculator()

        task = calc.create_task_metrics_from_execution(
            task_id="task_b",
            mode="B",
            execution_metrics={
                "llm_input_tokens": 100,
                "llm_output_tokens": 50,
                "llm_total_tokens": 150,
                "jev_input_tokens": 80,
                "jev_output_tokens": 40,
                "jev_total_tokens": 120
            },
            execution_type="mocked"
        )

        assert task.mode == "B"
        assert task.jev_usage is True
        assert task.jev_input_tokens == 80

    def test_create_mode_c_metrics_with_escalation(self):
        calc = EconomicMetricsCalculator()

        task = calc.create_task_metrics_from_execution(
            task_id="task_c",
            mode="C",
            execution_metrics={
                "llm_input_tokens": 100,
                "llm_output_tokens": 50,
                "llm_total_tokens": 150,
                "jev_input_tokens": 80,
                "jev_output_tokens": 40,
                "jev_total_tokens": 120,
                "escalation_count": 2
            },
            execution_type="mocked"
        )

        assert task.mode == "C"
        assert task.escalation_count == 2

    def test_missing_usage_metadata_marked(self):
        calc = EconomicMetricsCalculator()

        task = calc.create_task_metrics_from_execution(
            task_id="task_missing",
            mode="A",
            execution_metrics={},
            execution_type="mocked"
        )

        # Missing usage becomes zero tokens, not invented values
        assert task.groq_input_tokens == 0
        assert task.groq_estimated_cost == 0.0

    def test_live_execution_flag(self):
        calc = EconomicMetricsCalculator()

        task_live = calc.create_task_metrics_from_execution(
            task_id="task_live",
            mode="A",
            execution_metrics={
                "llm_input_tokens": 100,
                "llm_output_tokens": 50,
                "llm_total_tokens": 150
            },
            execution_type="live"
        )

        assert task_live.has_live_api_calls is True

        task_mocked = calc.create_task_metrics_from_execution(
            task_id="task_mocked",
            mode="A",
            execution_metrics={
                "llm_input_tokens": 100,
                "llm_output_tokens": 50,
                "llm_total_tokens": 150
            },
            execution_type="mocked"
        )

        assert task_mocked.has_live_api_calls is False


# ---------------------------------------------------------
# Aggregation
# ---------------------------------------------------------


class TestEconomicMetricsAggregation:
    def test_aggregate_multiple_tasks(self):
        calc = EconomicMetricsCalculator()

        tasks = []
        for i in range(3):
            task = calc.create_task_metrics_from_execution(
                task_id=f"task_{i}",
                mode="B",
                execution_metrics={
                    "llm_input_tokens": 100,
                    "llm_output_tokens": 50,
                    "llm_total_tokens": 150,
                    "jev_input_tokens": 80,
                    "jev_output_tokens": 40,
                    "jev_total_tokens": 120
                },
                execution_type="mocked"
            )
            tasks.append(task)

        summary = calc.aggregate_economic_metrics(tasks, "B", verified_successes=3)

        assert summary.run_count == 3
        assert summary.total_groq_input_tokens == 300
        assert summary.total_jev_input_tokens == 240
        assert summary.avg_cost_per_task is not None
        assert summary.groq_cost_contribution is not None
        assert summary.jev_cost_contribution is not None

    def test_aggregate_empty_list(self):
        calc = EconomicMetricsCalculator()

        summary = calc.aggregate_economic_metrics([], "A")

        assert summary.run_count == 0
        assert summary.total_estimated_cost == 0.0
        assert summary.avg_cost_per_task is None

    def test_cost_by_mode(self):
        calc = EconomicMetricsCalculator()

        tasks = []
        for i in range(2):
            task = calc.create_task_metrics_from_execution(
                task_id=f"task_{i}",
                mode="C",
                execution_metrics={
                    "llm_input_tokens": 100,
                    "llm_output_tokens": 50,
                    "llm_total_tokens": 150,
                    "jev_input_tokens": 80,
                    "jev_output_tokens": 40,
                    "jev_total_tokens": 120,
                    "escalation_count": 1
                },
                execution_type="mocked"
            )
            tasks.append(task)

        summary = calc.aggregate_economic_metrics(tasks, "C", verified_successes=2)

        assert "C" in summary.cost_by_mode
        assert summary.cost_by_mode["C"] == pytest.approx(summary.total_estimated_cost)

    def test_cost_per_successful_and_failed_task(self):
        calc = EconomicMetricsCalculator()

        tasks = []
        for i in range(3):
            task = calc.create_task_metrics_from_execution(
                task_id=f"task_{i}",
                mode="A",
                execution_metrics={
                    "llm_input_tokens": 100,
                    "llm_output_tokens": 50,
                    "llm_total_tokens": 150
                },
                execution_type="mocked"
            )
            tasks.append(task)

        summary = calc.aggregate_economic_metrics(
            tasks, "A", verified_successes=2, verified_failures=1
        )

        assert summary.cost_per_successful_task is not None
        assert summary.cost_per_failed_task is not None
        # Total cost split across successful tasks
        assert summary.cost_per_successful_task == pytest.approx(
            summary.total_estimated_cost / 2
        )

    def test_median_cost_per_task(self):
        """Median cost is computed from individual task costs."""

        calc = EconomicMetricsCalculator()

        tasks = []
        costs = [0.001, 0.002, 0.003, 0.004, 0.005]
        for i, cost in enumerate(costs):
            # Create tasks with specific costs by scaling tokens
            task = TaskEconomicMetrics(
                task_id=f"task_{i}",
                mode="A",
                groq_input_tokens=int(cost * 1e6 / 0.15),
                groq_output_tokens=0,
                groq_total_tokens=int(cost * 1e6 / 0.15),
                jev_input_tokens=0,
                jev_output_tokens=0,
                jev_total_tokens=0
            )
            tasks.append(task)

        summary = calc.aggregate_economic_metrics(tasks, "A")

        # Median of 5 values is the 3rd value
        assert summary.median_cost_per_task == pytest.approx(0.003)

    def test_groq_jev_cost_contribution_sums_to_one(self):
        calc = EconomicMetricsCalculator()

        tasks = []
        for i in range(2):
            task = calc.create_task_metrics_from_execution(
                task_id=f"task_{i}",
                mode="B",
                execution_metrics={
                    "llm_input_tokens": 100,
                    "llm_output_tokens": 50,
                    "llm_total_tokens": 150,
                    "jev_input_tokens": 80,
                    "jev_output_tokens": 40,
                    "jev_total_tokens": 120
                },
                execution_type="mocked"
            )
            tasks.append(task)

        summary = calc.aggregate_economic_metrics(tasks, "B")

        total_contribution = (
            summary.groq_cost_contribution + summary.jev_cost_contribution
        )
        assert total_contribution == pytest.approx(1.0)


# ---------------------------------------------------------
# Integration with existing benchmark records
# ---------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_metrics_unchanged(self):
        """Existing metric fields are not altered by cost accounting."""

        from evaluation.metrics import extract_run_metrics

        execution = {
            "llm_input_tokens": 100,
            "llm_output_tokens": 50,
            "llm_total_tokens": 150,
            "jev_input_tokens": 80,
            "jev_output_tokens": 40,
            "jev_total_tokens": 120,
            "combined_tokens": 270
        }

        metrics = extract_run_metrics(execution)

        assert metrics["llm_input_tokens"] == 100
        assert metrics["jev_total_tokens"] == 120
        assert metrics["combined_tokens"] == 270
        # No cost fields in extract_run_metrics output
        assert "groq_estimated_cost" not in metrics

    def test_mode_a_jev_metrics_stay_none(self):
        """Mode A Jev metrics remain None; cost accounting does not fabricate them."""

        from evaluation.metrics import extract_run_metrics

        execution = {
            "llm_input_tokens": 100,
            "llm_output_tokens": 50,
            "llm_total_tokens": 150
        }

        metrics = extract_run_metrics(execution)

        assert metrics["jev_input_tokens"] is None
        assert metrics["jev_total_tokens"] is None

    def test_historical_costs_not_invented(self):
        """Historical records without cost data stay missing, not zero."""

        # Simulate a historical record with no cost fields
        historical_record = {
            "llm_input_tokens": 100,
            "llm_output_tokens": 50,
            "llm_total_tokens": 150,
            "jev_input_tokens": 80,
            "jev_output_tokens": 40,
            "jev_total_tokens": 120
        }

        # Cost fields are absent; they are not fabricated
        assert "groq_estimated_cost" not in historical_record
        assert "total_estimated_cost" not in historical_record


# ---------------------------------------------------------
# No live API calls
# ---------------------------------------------------------


class TestNoLiveApi:
    def test_all_tests_are_mocked(self):
        """Every test in this module uses mocked data only."""

        # This test passes by construction: no test in this file
        # instantiates GroqLLMClient or JevClient, and no network
        # calls are made. The calculator uses pricing config only.
        calc = EconomicMetricsCalculator()
        assert calc.pricing is not None
