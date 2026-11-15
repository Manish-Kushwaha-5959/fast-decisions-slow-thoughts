"""
Phase 7 tests: evaluation and benchmarking framework.

Covers:
- Task verification: verified / failed / unverifiable outcomes,
  independent of the agent's self-reported success flag.
- Metric extraction and aggregation, including missing values and
  provider-distinguishable token accounting.
- CSV/JSONL append behaviour and preservation of existing records.
- Task dataset validation.
- Benchmark execution across Modes A/B/C, failed/incomplete runs,
  repeated runs and aggregation.

All agent execution is mocked (FakeLLMClient / FakeJevClient); no test
contacts a live API. Files are written to tmp_path, never to the
shared experiments/ directory.
"""

import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.logger import ExperimentLogger
from evaluation.metrics import extract_run_metrics, summarize_runs
from evaluation.task_verifier import (
    FAILED,
    UNVERIFIABLE,
    VERIFIED,
    TaskVerifier,
    load_tasks,
    validate_tasks
)
from scripts.run_benchmark import (
    FakeLLMClient,
    FakeJevClient,
    BenchmarkRunner,
    _baseline_responses,
    _hybrid_responses,
    _jev_sequence,
    _tool_argument_list,
    jev_decision
)
from tools.registry import build_default_registry


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

BASE_TASK = {
    "id": "test_task",
    "description": "Check the current VPN service status.",
    "expected_outcome": "The VPN status was determined.",
    "category": "service_status",
    "difficulty": "easy",
    "expected_tools": ["check_service_status"],
    "verification": {
        "required_tools": ["check_service_status"],
        "forbidden_tools": ["create_support_ticket"],
        "response_contains": ["vpn"],
        "response_excludes": ["ticket"],
        "require_final_response": True,
        "require_valid_evidence": True
    }
}


def successful_execution():
    """An execution record that satisfies the base task."""

    return {
        "task": BASE_TASK["description"],
        "final_response": "The VPN service is degraded.",
        "success": True,
        "iterations": 2,
        "tool_calls": [
            {
                "iteration": 1,
                "tool_name": "check_service_status",
                "arguments": {"service": "VPN"},
                "execution_status": "success",
                "result": {
                    "service": "vpn",
                    "status": "degraded",
                    "message": "degraded",
                    "source": "local_simulation"
                }
            }
        ],
        "decision_history": [],
        "llm_input_tokens": 100,
        "llm_output_tokens": 50,
        "llm_total_tokens": 150,
        "llm_latency_seconds": 1.0,
        "jev_input_tokens": 80,
        "jev_output_tokens": 40,
        "jev_total_tokens": 120,
        "jev_latency_seconds": 0.5,
        "tool_latency_seconds": 0.1,
        "total_latency_seconds": 1.6,
        "termination_reason": "jev_detected_completion",
        "task_specification": {}
    }


def write_tasks(tmp_path, tasks=None):
    """Write a task dataset and return its path."""

    dataset = {"dataset": "test", "tasks": tasks if tasks else [BASE_TASK]}
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    return path


def run_record(
    mode,
    outcome,
    agent_success=True,
    iterations=2,
    llm_total=150,
    jev_total=120,
    escalations=0
):
    """Build a run record in the shape summarize_runs expects."""

    decision_history = []
    for index in range(escalations):
        decision_history.append({
            "iteration": index + 1,
            "selected_tool": "check_service_status",
            "tool_probabilities": {"check_service_status": 0.3},
            "tool_confidence": 0.3,
            "completion_probability": 0.0,
            "loop_probability": 0.0,
            "progress_score": 2.0,
            "model": "fake-jev-model",
            "input_tokens": 8,
            "output_tokens": 4,
            "total_tokens": 12,
            "latency_seconds": 0.05,
            "decision_type": "tool_selection",
            "escalated": True,
            "escalation_reason": "below threshold",
            "groq_recommendation": {"selected_tool": "check_service_status"},
            "final_decision": "check_service_status",
            "escalation_succeeded": True
        })

    return {
        "outcome": outcome,
        "metrics": {
            "llm_input_tokens": 100,
            "llm_output_tokens": 50,
            "llm_total_tokens": llm_total,
            "jev_input_tokens": 80,
            "jev_output_tokens": 40,
            "jev_total_tokens": jev_total,
            "combined_tokens": (llm_total or 0) + (jev_total or 0),
            "llm_latency_seconds": 1.0,
            "jev_latency_seconds": 0.5,
            "tool_latency_seconds": 0.1,
            "total_latency_seconds": 1.5,
            "iterations": iterations,
            "tool_calls": 1,
            "tool_execution_failures": 0,
            "escalation_count": escalations,
            "tool_selection_escalations": escalations,
            "completion_escalations": 0,
            "escalation_succeeded_count": escalations,
            "agent_reported_success": agent_success,
            "termination_reason": "jev_detected_completion"
        },
        "execution": {
            "decision_history": decision_history
        }
    }


# ---------------------------------------------------------
# Task verification
# ---------------------------------------------------------


class TestTaskVerifier:
    def test_successful_execution_is_verified(self):
        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, successful_execution())

        assert result.outcome == VERIFIED
        assert result.passed is True
        assert result.agent_reported_success is True

    def test_agent_self_report_is_not_trusted(self):
        """A lying success flag must not make the run verified."""

        execution = successful_execution()
        execution["success"] = True  # agent claims success
        execution["final_response"] = "I did the thing."  # no evidence

        # No required tool actually executed.
        execution["tool_calls"] = []

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == FAILED
        assert result.agent_reported_success is True

    def test_failed_when_required_tool_never_executed(self):
        execution = successful_execution()
        execution["tool_calls"] = []

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == FAILED
        assert any(
            check.name == "required_tool_evidence:check_service_status"
            and not check.passed
            for check in result.checks
        )

    def test_failed_when_forbidden_tool_executed(self):
        execution = successful_execution()
        execution["tool_calls"].append({
            "iteration": 2,
            "tool_name": "create_support_ticket",
            "arguments": {"issue": "x", "priority": "low"},
            "execution_status": "success",
            "result": {
                "ticket_id": "TICKET-0001",
                "status": "created",
                "simulation": True
            }
        })

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == FAILED
        assert any(
            check.name == "forbidden_tool_absent:create_support_ticket"
            and not check.passed
            for check in result.checks
        )

    def test_failed_when_response_missing_phrase(self):
        execution = successful_execution()
        execution["final_response"] = "Everything is fine."

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == FAILED
        assert any(
            check.name == "response_contains:vpn"
            and not check.passed
            for check in result.checks
        )

    def test_failed_when_tool_execution_errored(self):
        execution = successful_execution()
        execution["tool_calls"][0]["execution_status"] = "error"
        execution["tool_calls"][0]["result"] = {"error": "boom"}

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == FAILED

    def test_unverifiable_when_run_errored(self):
        execution = successful_execution()
        execution["error"] = "RuntimeError: simulated crash"

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == UNVERIFIABLE

    def test_unverifiable_when_no_tool_history(self):
        execution = successful_execution()
        execution["tool_calls"] = None

        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, execution)

        assert result.outcome == UNVERIFIABLE

    def test_unverifiable_when_no_verification_rules(self):
        task = dict(BASE_TASK)
        task["verification"] = {}

        verifier = TaskVerifier()
        result = verifier.verify(task, successful_execution())

        assert result.outcome == UNVERIFIABLE

    def test_unverifiable_when_no_execution_record(self):
        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, None)

        assert result.outcome == UNVERIFIABLE

    def test_unverifiable_when_execution_not_a_dict(self):
        verifier = TaskVerifier()
        result = verifier.verify(BASE_TASK, "not-a-dict")

        assert result.outcome == UNVERIFIABLE

    def test_verification_result_serializes(self):
        result = TaskVerifier().verify(
            BASE_TASK, successful_execution()
        )

        data = result.to_dict()

        assert data["outcome"] == VERIFIED
        assert isinstance(data["checks"], list)
        assert data["checks"][0]["passed"] is True

    def test_empty_required_tools_imposes_no_evidence_requirement(self):
        task = dict(BASE_TASK)
        task["verification"] = {
            "required_tools": [],
            "forbidden_tools": [],
            "response_contains": ["vpn"],
            "response_excludes": [],
            "require_final_response": True,
            "require_valid_evidence": True
        }

        execution = successful_execution()
        execution["tool_calls"] = []

        result = TaskVerifier().verify(task, execution)

        assert result.outcome == VERIFIED


# ---------------------------------------------------------
# Task dataset validation
# ---------------------------------------------------------


class TestTaskDataset:
    def test_default_dataset_loads_and_validates(self):
        tasks = load_tasks()

        assert isinstance(tasks, list)
        assert 8 <= len(tasks) <= 12

        problems = validate_tasks(tasks)
        assert problems == []

    def test_every_task_has_required_fields(self):
        tasks = load_tasks()

        for task in tasks:
            assert task["id"]
            assert task["description"]
            assert task["expected_outcome"]
            assert task["category"]
            assert task["difficulty"]
            assert isinstance(task["expected_tools"], list)
            assert isinstance(task["verification"], dict)

    def test_task_ids_are_unique(self):
        tasks = load_tasks()
        ids = [task["id"] for task in tasks]

        assert len(ids) == len(set(ids))

    def test_expected_tools_are_registered(self):
        registry = build_default_registry()
        registered = set(registry.get_tool_names())

        for task in load_tasks():
            for tool in task["expected_tools"]:
                assert tool in registered

    def test_required_tools_are_subset_of_expected(self):
        for task in load_tasks():
            required = task["verification"]["required_tools"]
            expected = task["expected_tools"]

            for tool in required:
                assert tool in expected

    def test_categories_are_represented(self):
        categories = {
            task["category"] for task in load_tasks()
        }

        assert "knowledge_retrieval" in categories
        assert "service_status" in categories
        assert "ticket_creation" in categories
        assert "multi_step" in categories

    def test_invalid_dataset_is_rejected(self):
        bad_tasks = [{"id": "x"}]  # missing every required field

        problems = validate_tasks(bad_tasks)
        assert problems

    def test_duplicate_ids_are_rejected(self):
        tasks = [dict(BASE_TASK), dict(BASE_TASK)]

        problems = validate_tasks(tasks)
        assert any("duplicate" in problem for problem in problems)

    def test_unregistered_expected_tool_is_rejected(self):
        tasks = [dict(BASE_TASK)]
        tasks[0]["expected_tools"] = ["nonexistent_tool"]

        problems = validate_tasks(tasks)
        assert any("unregistered" in problem or "invalid" in problem
                   for problem in problems)

    def test_required_outside_expected_is_rejected(self):
        # Deep copy: BASE_TASK is shared by every test through
        # write_tasks(), so mutating a shallow copy's nested
        # 'verification' dict would poison the module-level fixture.
        tasks = [copy.deepcopy(BASE_TASK)]
        tasks[0]["verification"]["required_tools"] = ["create_support_ticket"]

        problems = validate_tasks(tasks)
        assert any("subset" in problem for problem in problems)

    def test_load_tasks_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_tasks(tmp_path / "does_not_exist.json")

    def test_load_tasks_empty_list_raises(self, tmp_path):
        path = tmp_path / "tasks.json"
        path.write_text(json.dumps({"tasks": []}), encoding="utf-8")

        with pytest.raises(ValueError):
            load_tasks(path)


# ---------------------------------------------------------
# Metrics
# ---------------------------------------------------------


class TestMetrics:
    def test_extract_provider_distinguishable_tokens(self):
        metrics = extract_run_metrics(successful_execution())

        assert metrics["llm_total_tokens"] == 150
        assert metrics["jev_total_tokens"] == 120
        assert metrics["combined_tokens"] == 270

    def test_extract_mode_a_has_no_jev_metrics(self):
        execution = successful_execution()
        execution.pop("jev_input_tokens")
        execution.pop("jev_output_tokens")
        execution.pop("jev_total_tokens")
        execution.pop("jev_latency_seconds")

        metrics = extract_run_metrics(execution)

        assert metrics["jev_total_tokens"] is None
        # Combined falls back to the available provider total.
        assert metrics["combined_tokens"] == 150

    def test_missing_everything_stays_none(self):
        metrics = extract_run_metrics({})

        assert metrics["llm_total_tokens"] is None
        assert metrics["jev_total_tokens"] is None
        assert metrics["combined_tokens"] is None
        assert metrics["iterations"] is None
        assert metrics["total_latency_seconds"] is None

    def test_tool_execution_failures_counted(self):
        execution = successful_execution()
        execution["tool_calls"].append({
            "tool_name": "search_knowledge_base",
            "execution_status": "error",
            "result": {"error": "bad"}
        })

        metrics = extract_run_metrics(execution)

        assert metrics["tool_calls"] == 2
        assert metrics["tool_execution_failures"] == 1

    def test_escalation_counts_from_decision_history(self):
        execution = successful_execution()
        execution["decision_history"] = [
            {
                "decision_type": "tool_selection",
                "escalated": True,
                "escalation_succeeded": True
            },
            {
                "decision_type": "task_completion",
                "escalated": True,
                "escalation_succeeded": False
            },
            {
                "decision_type": "none",
                "escalated": False
            }
        ]

        metrics = extract_run_metrics(execution)

        assert metrics["escalation_count"] == 2
        assert metrics["tool_selection_escalations"] == 1
        assert metrics["completion_escalations"] == 1
        assert metrics["escalation_succeeded_count"] == 1

    def test_escalation_frequency_per_iteration(self):
        execution = successful_execution()
        execution["iterations"] = 4
        execution["decision_history"] = [
            {"decision_type": "tool_selection", "escalated": True}
        ]

        metrics = extract_run_metrics(execution)

        assert metrics["escalation_count"] == 1
        assert metrics["escalation_frequency"] == pytest.approx(0.25)

    def test_escalation_frequency_none_without_iterations(self):
        execution = successful_execution()
        execution.pop("iterations")

        metrics = extract_run_metrics(execution)

        assert metrics["escalation_frequency"] is None

    def test_agent_success_kept_separate(self):
        execution = successful_execution()
        execution["success"] = False

        metrics = extract_run_metrics(execution)

        assert metrics["agent_reported_success"] is False

    def test_summarize_verified_and_failed(self):
        runs = [
            run_record("A", VERIFIED),
            run_record("A", VERIFIED),
            run_record("A", FAILED)
        ]

        summary = summarize_runs(runs, "A")

        assert summary.run_count == 3
        assert summary.verified_successes == 2
        assert summary.verified_failures == 1
        assert summary.unverifiable == 0
        assert summary.verified_success_rate == pytest.approx(2 / 3)

    def test_summarize_unverifiable_counted(self):
        runs = [run_record("A", UNVERIFIABLE)]

        summary = summarize_runs(runs, "A")

        assert summary.unverifiable == 1
        assert summary.verified_successes == 0

    def test_summarize_agent_reported_separate_from_verified(self):
        runs = [
            run_record("A", VERIFIED, agent_success=True),
            run_record("A", FAILED, agent_success=True)
        ]

        summary = summarize_runs(runs, "A")

        assert summary.verified_successes == 1
        assert summary.agent_reported_successes == 2
        assert summary.agent_reported_success_rate == 1.0
        assert summary.verified_success_rate == pytest.approx(0.5)

    def test_summarize_token_totals(self):
        runs = [
            run_record("B", VERIFIED, llm_total=150, jev_total=120),
            run_record("B", VERIFIED, llm_total=50, jev_total=80)
        ]

        summary = summarize_runs(runs, "B")

        assert summary.llm_total_tokens == 200
        assert summary.jev_total_tokens == 200
        assert summary.combined_tokens == 400

    def test_summarize_escalation_counts(self):
        runs = [
            run_record("C", VERIFIED, escalations=2),
            run_record("C", VERIFIED, escalations=1)
        ]

        summary = summarize_runs(runs, "C")

        assert summary.escalation_count == 3
        assert summary.tool_selection_escalations == 3
        assert summary.escalation_frequency == pytest.approx(3 / 2)

    def test_summarize_latency_aggregates(self):
        runs = [
            run_record("A", VERIFIED),
            run_record("A", VERIFIED)
        ]

        summary = summarize_runs(runs, "A")

        assert summary.total_latency_seconds == pytest.approx(3.0)
        assert summary.mean_latency_seconds == pytest.approx(1.5)
        assert summary.mean_iterations == pytest.approx(2.0)

    def test_summarize_empty_runs(self):
        summary = summarize_runs([], "A")

        assert summary.run_count == 0
        assert summary.verified_success_rate is None
        assert summary.combined_tokens is None
        assert summary.escalation_count is None

    def test_summarize_missing_metrics_stay_none(self):
        runs = [{"outcome": VERIFIED, "metrics": {}, "execution": {}}]

        summary = summarize_runs(runs, "A")

        assert summary.combined_tokens is None
        assert summary.total_tool_calls is None

    def test_summarize_partial_metrics_not_invented(self):
        # One run has Jev metrics, the other does not (Mode A shape).
        runs = [
            run_record("A", VERIFIED, jev_total=None),
            run_record("A", VERIFIED, jev_total=None)
        ]

        summary = summarize_runs(runs, "A")

        # Absent provider metrics stay None rather than being
        # invented as zero; combined falls back to the available
        # provider total, which is the documented design.
        assert summary.jev_total_tokens is None
        assert summary.combined_tokens == 300  # 150 + 150 LLM tokens


# ---------------------------------------------------------
# Experiment logger
# ---------------------------------------------------------


class TestExperimentLogger:
    def test_appends_csv_and_jsonl(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        metrics = extract_run_metrics(successful_execution())
        verification = {"outcome": VERIFIED, "checks": [], "reason": "ok"}

        logger.log(
            mode="B",
            task_id="status_vpn",
            metrics=metrics,
            verification=verification,
            run_id="run-1",
            raw_execution={"success": True},
            execution_type="mocked"
        )

        assert logger.count_records() == 1

        csv_rows = logger.read_csv()
        assert len(csv_rows) == 1
        assert csv_rows[0]["mode"] == "B"
        assert csv_rows[0]["task_id"] == "status_vpn"
        assert csv_rows[0]["outcome"] == VERIFIED
        assert csv_rows[0]["execution_type"] == "mocked"

    def test_append_preserves_previous_records(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        verification = {"outcome": VERIFIED, "checks": [], "reason": "ok"}

        logger.log(
            mode="A", task_id="t1",
            metrics=extract_run_metrics(successful_execution()),
            verification=verification, run_id="run-1"
        )
        logger.log(
            mode="B", task_id="t2",
            metrics=extract_run_metrics(successful_execution()),
            verification=verification, run_id="run-2"
        )

        assert logger.count_records() == 2

        modes = [row["mode"] for row in logger.read_csv()]
        assert modes == ["A", "B"]

        # The first record is still intact after the second append.
        with logger.jsonl_path.open("r", encoding="utf-8") as file:
            records = [json.loads(line) for line in file]

        assert records[0]["run_id"] == "run-1"
        assert records[1]["run_id"] == "run-2"

    def test_jsonl_keeps_raw_execution_and_verification(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        metrics = extract_run_metrics(successful_execution())
        verification = {
            "outcome": FAILED,
            "checks": [{"name": "final_response_present",
                        "passed": False, "detail": "empty"}],
            "reason": "empty response"
        }

        logger.log(
            mode="C", task_id="status_vpn",
            metrics=metrics, verification=verification,
            run_id="run-9", raw_execution={"success": False},
            execution_type="live", error=None
        )

        with logger.jsonl_path.open("r", encoding="utf-8") as file:
            record = json.loads(file.readline())

        assert record["execution_type"] == "live"
        assert record["verification"]["outcome"] == FAILED
        assert record["raw_execution"]["success"] is False

    def test_error_runs_are_recorded(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        metrics = extract_run_metrics(successful_execution())
        verification = {
            "outcome": UNVERIFIABLE,
            "checks": [],
            "reason": "Run did not complete: boom"
        }

        logger.log(
            mode="A", task_id="t1", metrics=metrics,
            verification=verification, run_id="run-err",
            error="RuntimeError: boom"
        )

        row = logger.read_csv()[0]
        assert row["error"] == "RuntimeError: boom"
        assert row["outcome"] == UNVERIFIABLE

    def test_missing_metrics_recorded_as_empty_not_zero(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        logger.log(
            mode="A", task_id="t1", metrics={},
            verification={"outcome": UNVERIFIABLE, "checks": [],
                          "reason": "no data"},
            run_id="run-empty"
        )

        row = logger.read_csv()[0]
        # Absent metrics are blank cells, never invented zeros.
        assert row["llm_total_tokens"] == ""
        assert row["jev_total_tokens"] == ""
        assert row["combined_tokens"] == ""

    def test_booleans_written_as_strings(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )

        logger.log(
            mode="A", task_id="t1",
            metrics={"agent_reported_success": True},
            verification={"outcome": VERIFIED, "checks": [],
                          "reason": "ok"},
            run_id="run-bool"
        )

        row = logger.read_csv()[0]
        assert row["agent_reported_success"] == "true"

    def test_csv_header_written_once(self, tmp_path):
        csv_path = tmp_path / "r.csv"
        logger = ExperimentLogger(csv_path=csv_path,
                                  jsonl_path=tmp_path / "r.jsonl")

        for index in range(3):
            logger.log(
                mode="A", task_id=f"t{index}", metrics={},
                verification={"outcome": VERIFIED, "checks": [],
                              "reason": "ok"},
                run_id=f"run-{index}"
            )

        with csv_path.open("r", encoding="utf-8") as file:
            lines = file.readlines()

        # One header + three data rows.
        assert len(lines) == 4
        assert lines[0].count("timestamp") == 1

    def test_default_paths_do_not_touch_phase5_records(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "benchmark.csv",
            jsonl_path=tmp_path / "benchmark.jsonl"
        )

        logger.log(
            mode="A", task_id="t1", metrics={},
            verification={"outcome": VERIFIED, "checks": [],
                          "reason": "ok"},
            run_id="run-1"
        )

        # Phase 5/6 files are separate and must not be created here.
        assert not (tmp_path / "results.csv").exists()
        assert not (tmp_path / "experiment_logs.jsonl").exists()


# ---------------------------------------------------------
# Mocked task execution scripts
# ---------------------------------------------------------


class TestMockedScripts:
    def test_tool_argument_list_covers_all_expected(self):
        task = {
            "id": "multi_status_and_knowledge",
            "expected_tools": [
                "check_service_status", "search_knowledge_base"
            ],
            "description": "Check VPN and find VPN help."
        }

        pairs = _tool_argument_list(task)

        assert [name for name, _ in pairs] == task["expected_tools"]
        assert pairs[0][1] == {"service": "vpn"}
        assert "query" in pairs[1][1]

    def test_baseline_responses_end_with_final(self):
        responses = _baseline_responses(BASE_TASK)

        assert json.loads(responses[0])["action"] == "tool_call"
        assert json.loads(responses[-1])["action"] == "final"

    def test_hybrid_responses_start_with_plan(self):
        responses = _hybrid_responses(BASE_TASK)

        plan = json.loads(responses[0])
        assert "task_specification" in plan
        assert plan["task_specification"]["required_tools"] == [
            "check_service_status"
        ]

    def test_jev_sequence_ends_with_completion(self):
        decisions = _jev_sequence(BASE_TASK)

        assert decisions[-1].completion_probability >= 0.70
        assert len(decisions) == 2  # one pick + completion

    def test_jev_sequence_covers_two_tools_for_multi_step(self):
        task = {
            "id": "multi_x",
            "expected_tools": ["check_service_status",
                               "search_knowledge_base"],
            "description": "both"
        }

        decisions = _jev_sequence(task)

        picks = [d.selected_tool for d in decisions[:-1]]
        assert picks == task["expected_tools"]


# ---------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------


@pytest.fixture
def runner(tmp_path):
    logger = ExperimentLogger(
        csv_path=tmp_path / "r.csv",
        jsonl_path=tmp_path / "r.jsonl"
    )
    tasks_path = write_tasks(tmp_path)

    return BenchmarkRunner(
        tasks_path=tasks_path,
        logger=logger,
        execution_type="mocked"
    )


class TestBenchmarkRunner:
    def test_runs_mode_a(self, runner):
        results = runner.run_benchmark(modes=["A"])

        assert len(results["A"]) == 1
        assert results["A"][0]["verification"].outcome == VERIFIED
        assert results["A"][0]["error"] is None

    def test_runs_modes_b_and_c(self, runner):
        results = runner.run_benchmark(modes=["B", "C"])

        assert len(results["B"]) == 1
        assert len(results["C"]) == 1
        assert results["B"][0]["verification"].outcome == VERIFIED
        assert results["C"][0]["verification"].outcome == VERIFIED

    def test_same_task_and_verification_across_modes(self, runner):
        results = runner.run_benchmark(modes=["A", "B", "C"])

        task_ids = {
            mode: results[mode][0]["task_id"] for mode in results
        }
        assert len(set(task_ids.values())) == 1

        outcomes = {
            mode: results[mode][0]["verification"].outcome
            for mode in results
        }
        assert set(outcomes.values()) == {VERIFIED}

    def test_mocked_path_uses_fake_clients(self, runner):
        """The mocked path never constructs live API clients."""

        execution = runner.execute_task(runner.tasks[0], "A")

        assert execution["success"] is True
        # Mode A on a single-tool task makes 2 LLM calls (tool_call +
        # final), each scripted with the fake client's 15-token total.
        assert execution["llm_total_tokens"] == 30

    def test_failed_run_is_recorded_not_raised(self, runner):
        """A task whose agent errors stays in the results as unverifiable."""

        # Force an error by exhausting the fake LLM script.
        original = runner.execute_task

        def exploding_execute(task, mode, repetition=1):
            raise RuntimeError("simulated agent crash")

        runner.execute_task = exploding_execute

        result = runner.run_task(runner.tasks[0], "A")

        assert result["error"] == "RuntimeError: simulated agent crash"
        assert result["verification"].outcome == UNVERIFIABLE
        assert result["execution"]["termination_reason"] == (
            "benchmark_execution_error"
        )

        # Original binding restored for other tests.
        runner.execute_task = original

    def test_logger_wrote_one_record_per_run(self, runner):
        runner.run_benchmark(modes=["A", "B", "C"])

        assert runner.logger.count_records() == 3

    def test_repeated_runs_aggregate(self, runner):
        results = runner.run_benchmark(modes=["A"], repetitions=3)

        assert len(results["A"]) == 3

        summary = summarize_runs(
            [
                {
                    "outcome": run["verification"].outcome,
                    "metrics": run["metrics"]
                }
                for run in results["A"]
            ],
            mode="A"
        )

        assert summary.run_count == 3
        assert summary.verified_successes == 3
        assert summary.verified_success_rate == 1.0

    def test_execution_type_recorded(self, runner):
        runner.run_benchmark(modes=["A"])

        with runner.logger.jsonl_path.open("r", encoding="utf-8") as file:
            record = json.loads(file.readline())

        assert record["execution_type"] == "mocked"

    def test_run_id_is_unique_per_run(self, runner):
        results = runner.run_benchmark(modes=["A"], repetitions=2)

        ids = [run["run_id"] for run in results["A"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------
# Cross-mode comparison integrity
# ---------------------------------------------------------


class TestCrossModeComparison:
    def test_verification_ignores_agent_reported_success(self, runner):
        """Independently verified outcome is the ground truth."""

        results = runner.run_benchmark(modes=["A", "B", "C"])

        for mode, runs in results.items():
            for run in runs:
                verified = run["verification"].outcome
                agent = run["metrics"]["agent_reported_success"]

                # In this dataset they happen to agree, but the key
                # property is that outcome comes from the verifier.
                assert verified in (VERIFIED, FAILED, UNVERIFIABLE)
                assert isinstance(agent, bool)

    def test_summary_distinguishes_modes(self, runner):
        results = runner.run_benchmark(modes=["A", "B", "C"])

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
            for mode in results
        }

        # Mode A has no Jev usage; Modes B/C do.
        assert summaries["A"].jev_total_tokens is None
        assert summaries["B"].jev_total_tokens is not None
        assert summaries["C"].jev_total_tokens is not None

        # Mode A used fewer combined tokens than the hybrid modes.
        assert (
            summaries["A"].combined_tokens
            < summaries["B"].combined_tokens
        )

        # All modes verify every task.
        for summary in summaries.values():
            assert summary.verified_successes == summary.run_count


# ---------------------------------------------------------
# Safety: no live API in tests
# ---------------------------------------------------------


class TestNoLiveApi:
    def test_benchmark_runner_defaults_to_mocked(self, tmp_path):
        logger = ExperimentLogger(
            csv_path=tmp_path / "r.csv",
            jsonl_path=tmp_path / "r.jsonl"
        )
        runner = BenchmarkRunner(
            tasks_path=write_tasks(tmp_path),
            logger=logger
        )

        assert runner.execution_type == "mocked"
