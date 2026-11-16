"""
Regression tests for Phase 13 logging fixes.

Prove that:
- new records carry the supported economic cost fields,
- CSV and JSONL serialisation preserve them identically,
- historical records without cost fields still load,
- missing actual expenditure stays None (never a fabricated zero),
- mocked and live execution types are correctly identified.
"""

import csv
import json

import pytest

from evaluation.economic_metrics import (
    EconomicMetricsCalculator,
    TaskEconomicMetrics,
)
from evaluation.logger import CSV_FIELDS, ExperimentLogger
from evaluation.metrics import extract_run_metrics, summarize_runs
from evaluation.task_verifier import TaskVerifier

from agents.hybrid_agent import HybridAgent  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402


def _plan_response():
    import json

    return json.dumps({
        "plan": "Execute the required tool and report the result.",
        "task_specification": {
            "objective": "Check the current VPN service status.",
            "required_outcomes": ["The VPN status is obtained."],
            "allowed_tools": ["check_service_status"],
            "required_tools": ["check_service_status"],
            "completion_criteria": [
                "The result from check_service_status is available."
            ]
        }
    })


def _arguments_response(service="VPN"):
    import json

    return json.dumps({"arguments": {"service": service}})


def _final_response():
    import json

    return json.dumps(
        {"response": "The VPN service status was checked."}
    )


def _escalation_tool_response(tool="check_service_status"):
    import json

    return json.dumps({
        "selected_tool": tool,
        "reasoning": "The status tool directly answers the request."
    })


def _escalation_completion_response(task_complete=True):
    import json

    return json.dumps({
        "task_complete": task_complete,
        "reasoning": "The status evidence satisfies the criteria."
    })


def _execution_record(**overrides):
    """A minimal AgentRunResult-shaped record for metric extraction."""

    record = {
        "task": "test task",
        "final_response": "done",
        "success": True,
        "iterations": 2,
        "tool_calls": [],
        "decision_history": [],
        "llm_input_tokens": 20,
        "llm_output_tokens": 10,
        "llm_total_tokens": 30,
        "llm_latency_seconds": 0.2,
        "jev_input_tokens": 16,
        "jev_output_tokens": 8,
        "jev_total_tokens": 24,
        "jev_latency_seconds": 0.1,
        "tool_latency_seconds": 0.0,
        "total_latency_seconds": 0.3,
        "termination_reason": "llm_decided_complete",
        "task_specification": {},
    }
    record.update(overrides)
    return record


def _verified_metrics(execution, execution_type="mocked", mode="B"):
    metrics = extract_run_metrics(execution)
    economic = EconomicMetricsCalculator().create_task_metrics_from_execution(
        task_id="t", mode=mode, execution_metrics=metrics,
        execution_type=execution_type
    )
    metrics.update(economic.to_dict())
    return metrics


# ------------------------------------------------------------------
# New records contain the supported economic fields
# ------------------------------------------------------------------


class TestEconomicFieldsInNewRecords:
    def test_logger_schema_has_required_fields(self):
        required = {
            "llm_input_tokens", "llm_output_tokens",
            "groq_estimated_cost", "jev_estimated_cost",
            "total_estimated_cost", "groq_actual_cost", "jev_actual_cost",
            "total_actual_cost", "usage_measurement_method",
            "pricing_version", "cost_per_successful_task",
            "cost_per_failed_task", "groq_cost_contribution",
            "jev_cost_contribution",
        }
        missing = required - set(CSV_FIELDS)
        assert not missing, f"schema missing fields: {missing}"

    def test_new_mocked_run_records_cost_metrics(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl",
        )
        execution = _execution_record()
        metrics = _verified_metrics(execution)

        logger.log(
            mode="B", task_id="t", metrics=metrics,
            verification=TaskVerifier().verify(
                {"id": "t", "description": "d", "expected_tools": [],
                 "verification": {"required_tools": []}},
                execution
            ).to_dict(),
            run_id="B-t-01-abc123",
            raw_execution=execution,
            repetition=1,
            execution_type="mocked",
        )

        row = logger.read_csv()[0]
        assert row["groq_estimated_cost"]
        assert row["jev_estimated_cost"]
        assert row["total_estimated_cost"]
        assert row["usage_measurement_method"] == "mocked"
        assert row["pricing_version"]
        # Groq actual is not measured -> absent, never a fabricated 0.
        assert row["groq_actual_cost"] == ""

    def test_usage_method_labels_mocked_and_live(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl",
        )
        execution = _execution_record()
        verification = TaskVerifier().verify(
            {"id": "t", "description": "d", "expected_tools": [],
             "verification": {"required_tools": []}},
            execution
        ).to_dict()

        for exec_type in ("mocked", "live"):
            metrics = _verified_metrics(execution, execution_type=exec_type)
            logger.log(
                mode="A", task_id="t", metrics=metrics,
                verification=verification,
                run_id=f"A-t-01-{exec_type}", raw_execution=execution,
                repetition=1, execution_type=exec_type,
            )

        rows = logger.read_csv()
        assert rows[0]["execution_type"] == "mocked"
        assert rows[1]["execution_type"] == "live"
        assert rows[0]["usage_measurement_method"] == "mocked"
        assert rows[1]["usage_measurement_method"] == "provider_reported"


# ------------------------------------------------------------------
# CSV / JSONL serialisation
# ------------------------------------------------------------------


class TestSerialisation:
    def test_csv_and_jsonl_carry_same_run_data(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl",
        )
        execution = _execution_record()
        metrics = _verified_metrics(execution)
        metrics.update({
            "cost_per_successful_task": 0.001,
            "cost_per_failed_task": None,
            "groq_cost_contribution": 0.9,
            "jev_cost_contribution": 0.1,
        })

        logger.log(
            mode="C", task_id="t", metrics=metrics,
            verification={"outcome": "verified"},
            run_id="C-t-01-xyz", raw_execution=execution,
            repetition=1, execution_type="mocked",
        )

        csv_row = logger.read_csv()[0]
        with logger.jsonl_path.open("r", encoding="utf-8") as file:
            jsonl_record = json.loads(file.readline())

        assert csv_row["run_id"] == jsonl_record["run_id"]
        assert csv_row["groq_estimated_cost"] == str(
            jsonl_record["groq_estimated_cost"]
        )
        assert csv_row["total_estimated_cost"] == str(
            jsonl_record["total_estimated_cost"]
        )
        assert csv_row["usage_measurement_method"] == (
            jsonl_record["usage_measurement_method"]
        )
        # Summary fields survive both backends.
        assert jsonl_record["groq_cost_contribution"] == 0.9
        assert jsonl_record["cost_per_failed_task"] is None

    def test_missing_actual_is_not_written_as_zero(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl",
        )
        execution = _execution_record()
        metrics = _verified_metrics(execution)

        logger.log(
            mode="B", task_id="t", metrics=metrics,
            verification={"outcome": "verified"},
            run_id="B-t-01-none", raw_execution=execution,
            repetition=1, execution_type="live",
        )

        csv_row = logger.read_csv()[0]
        # Absent in CSV (empty string) and null in JSONL — not "0".
        assert csv_row["groq_actual_cost"] == ""
        with logger.jsonl_path.open("r", encoding="utf-8") as file:
            record = json.loads(file.readline())
        assert record["groq_actual_cost"] is None
        assert record["total_actual_cost"] is None
        assert record["jev_actual_cost"] is None


# ------------------------------------------------------------------
# Historical compatibility
# ------------------------------------------------------------------


class TestHistoricalCompatibility:
    def test_historical_rows_without_cost_fields_load(self, tmp_path):
        csv_path = tmp_path / "old.csv"
        historical_header = (
            "timestamp,run_id,mode,task_id,execution_type,repetition,"
            "outcome,agent_reported_success,iterations,tool_calls,"
            "llm_input_tokens,llm_output_tokens,llm_total_tokens,"
            "jev_input_tokens,jev_output_tokens,jev_total_tokens,"
            "combined_tokens,total_latency_seconds,escalation_count,"
            "termination_reason,error\n"
        )
        historical_row = (
            "2020-01-01T00:00:00+00:00,A-t-01-old,A,t,mocked,1,verified,"
            "true,2,1,20,10,30,,,,30,0.001,0,llm_decided_complete,\n"
        )
        csv_path.write_text(historical_header + historical_row, encoding="utf-8")

        logger = ExperimentLogger(csv_path=csv_path, jsonl_path=tmp_path / "n.jsonl")
        rows = logger.read_csv()
        assert len(rows) == 1
        assert rows[0]["mode"] == "A"
        assert rows[0].get("groq_estimated_cost") is None  # absent, not zero
        assert rows[0].get("pricing_version") is None

    def test_summarize_historical_runs_keeps_costs_none(self):
        runs = [{
            "outcome": "verified",
            "metrics": {
                "total_latency_seconds": 0.5,
                "iterations": 2,
                "escalation_count": 0,
            },
        }]
        summary = summarize_runs(runs, mode="A")
        assert summary.groq_estimated_cost is None
        assert summary.total_estimated_cost is None
        assert summary.groq_cost_contribution is None
        assert summary.cost_per_successful_task is None
        assert summary.total_actual_cost is None


# ------------------------------------------------------------------
# Execution-type identification
# ------------------------------------------------------------------


class TestExecutionTypeIdentification:
    def test_economic_metrics_flags_live_and_mocked(self):
        calc = EconomicMetricsCalculator()
        live = calc.create_task_metrics_from_execution(
            task_id="t", mode="A",
            execution_metrics={"llm_input_tokens": 5, "llm_output_tokens": 2},
            execution_type="live",
        )
        mocked = calc.create_task_metrics_from_execution(
            task_id="t", mode="A",
            execution_metrics={"llm_input_tokens": 5, "llm_output_tokens": 2},
            execution_type="mocked",
        )
        assert live.has_live_api_calls is True
        assert mocked.has_live_api_calls is False
        assert live.usage_measurement_method == "provider_reported"
        assert mocked.usage_measurement_method == "mocked"

    def test_live_run_recorded_with_live_execution_type(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl",
        )
        execution = _execution_record()
        metrics = _verified_metrics(execution)
        record = logger.log_live_run(
            mode="A", task_id="t", metrics=metrics,
            verification={"outcome": "verified"},
            run_id="A-t-01-live", raw_execution=execution,
        )
        assert record["execution_type"] == "live"
        assert logger.read_csv()[0]["execution_type"] == "live"
        # Logged exactly once.
        assert logger.count_records() == 1
        assert len(logger.read_csv()) == 1


# ------------------------------------------------------------------
# Mode C escalation branch — deterministic mocked validation
# ------------------------------------------------------------------
#
# The live campaign (scripts/run_live_validation.py) is budgeted to
# representative tasks whose scripted/live Jev confidences sit outside
# the escalation band, so escalation is validated here with controlled
# confidence values. This is a unit test of the branch, explicitly NOT
# live experimental evidence.


class TestModeCEscalationBranch:
    def test_low_confidence_triggers_groq_advisory_review(self):
        from types import SimpleNamespace

        class FakeLLM:
            def __init__(self, responses):
                self.responses = list(responses)
                self.calls = []

            def generate(self, messages, **kwargs):
                self.calls.append(messages[-1]["content"])
                content = self.responses.pop(0)
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

        class FakeJev:
            def __init__(self, decisions):
                self.decisions = list(decisions)
                self.calls = []

            def evaluate_state(self, state, available_tools):
                self.calls.append(state)
                return self.decisions.pop(0)

        def jev_decision(tool_confidence, completion_probability,
                         selected_tool="check_service_status"):
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

        llm = FakeLLM([
            _plan_response(),
            _escalation_tool_response(),
            _arguments_response(),
            _final_response(),
        ])
        jev = FakeJev([
            # tool confidence 0.30 <= 0.60 threshold -> escalate
            jev_decision(tool_confidence=0.30, completion_probability=0.0),
            jev_decision(tool_confidence=0.95, completion_probability=0.95),
        ])

        agent = HybridAgent(
            llm_client=llm,
            jev_client=jev,
            registry=build_default_registry(),
            max_iterations=5,
            enable_escalation=True,
        )
        result = agent.run("Check the current VPN service status.")

        records = [
            entry for entry in result.decision_history
            if entry.get("escalated") is True
        ]
        assert len(records) == 1
        assert records[0]["escalation_succeeded"] is True
        assert records[0]["tool_confidence"] == 0.30
        # Groq advisory review was executed for the escalation.
        assert any(
            "status" in str(call).lower() for call in llm.calls
        )
        # Controller kept final authority: the run completed and verified.
        assert result.success is True
        agent.close()

    def test_confident_decision_does_not_escalate(self):
        from types import SimpleNamespace

        class FakeLLM:
            def __init__(self, responses):
                self.responses = list(responses)

            def generate(self, messages, **kwargs):
                content = self.responses.pop(0)
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

        class FakeJev:
            def __init__(self, decisions):
                self.decisions = list(decisions)

            def evaluate_state(self, state, available_tools):
                return self.decisions.pop(0)

        def jev_decision(tool_confidence, completion_probability):
            return SimpleNamespace(
                selected_tool="check_service_status",
                tool_probabilities={"check_service_status": tool_confidence},
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

        llm = FakeLLM([
            _plan_response(),
            _arguments_response(),
            _final_response(),
        ])
        jev = FakeJev([
            jev_decision(tool_confidence=0.95, completion_probability=0.0),
            jev_decision(tool_confidence=0.95, completion_probability=0.95),
        ])

        agent = HybridAgent(
            llm_client=llm,
            jev_client=jev,
            registry=build_default_registry(),
            max_iterations=5,
            enable_escalation=True,
        )
        result = agent.run("Check the current VPN service status.")

        escalated = [
            entry for entry in result.decision_history
            if entry.get("escalated") is True
        ]
        assert escalated == []
        assert result.success is True
        agent.close()
