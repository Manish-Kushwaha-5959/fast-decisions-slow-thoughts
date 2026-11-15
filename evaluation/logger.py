"""
Append-only experiment logger for the Phase 7 benchmark.

Two storage backends are kept in sync:

- ``experiments/benchmark_results.csv`` — flat rows for spreadsheets.
- ``experiments/benchmark_results.jsonl`` — full records including raw
  execution data and verification detail for later analysis.

The logger only ever appends. Pre-existing experiment records
(``experiments/results.csv`` and ``experiments/experiment_logs.jsonl``
from Phases 5–6) are never read, rewritten, or fabricated; the
benchmark files are separate so no historical record can be lost.

Every record distinguishes ``mocked`` from ``live`` execution so
synthetic and real API data are never mixed in analysis.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DEFAULT_CSV_PATH = DEFAULT_EXPERIMENTS_DIR / "benchmark_results.csv"
DEFAULT_JSONL_PATH = DEFAULT_EXPERIMENTS_DIR / "benchmark_results.jsonl"

CSV_FIELDS = [
    "timestamp", "run_id", "mode", "task_id", "execution_type",
    "repetition", "outcome", "agent_reported_success",
    "iterations", "tool_calls", "tool_execution_failures",
    "llm_input_tokens", "llm_output_tokens", "llm_total_tokens",
    "jev_input_tokens", "jev_output_tokens", "jev_total_tokens",
    "combined_tokens", "llm_latency_seconds", "jev_latency_seconds",
    "tool_latency_seconds", "total_latency_seconds",
    "escalation_count", "tool_selection_escalations",
    "completion_escalations", "escalation_succeeded_count",
    "termination_reason", "error"
]


class ExperimentLogger:
    """Append-only recorder for benchmark runs."""

    def __init__(
        self,
        csv_path: Any = DEFAULT_CSV_PATH,
        jsonl_path: Any = DEFAULT_JSONL_PATH,
        experiments_dir: Any = DEFAULT_EXPERIMENTS_DIR
    ):
        self.csv_path = Path(csv_path)
        self.jsonl_path = Path(jsonl_path)
        self.experiments_dir = Path(experiments_dir)

    def _append_jsonl(self, record: dict) -> None:
        """Append one full record as a JSONL line."""

        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(
                record, ensure_ascii=False, default=str
            ) + "\n")

    def _append_csv(self, row: dict) -> None:
        """Append one flat row to the CSV, writing the header once."""

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        write_header = (
            not self.csv_path.exists()
            or self.csv_path.stat().st_size == 0
        )

        with self.csv_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file, fieldnames=CSV_FIELDS, extrasaction="ignore"
            )

            if write_header:
                writer.writeheader()

            writer.writerow({
                name: row.get(name) for name in CSV_FIELDS
            })

    @staticmethod
    def _csv_safe(value: Any) -> Any:
        """Convert booleans/None into spreadsheet-friendly strings."""

        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return ""
        return value

    def log(
        self,
        mode: str,
        task_id: str,
        metrics: dict,
        verification: dict,
        run_id: str,
        raw_execution: Optional[dict] = None,
        repetition: int = 1,
        execution_type: str = "mocked",
        error: Optional[str] = None
    ) -> dict:
        """
        Append one benchmark run record.

        ``metrics`` comes from ``extract_run_metrics``; ``verification``
        is the independent ``VerificationResult.to_dict()`` output;
        ``raw_execution`` is the full agent record kept for later
        analysis. Missing metrics stay absent rather than invented.
        """

        timestamp = datetime.now(timezone.utc).isoformat()

        row: dict[str, Any] = {
            "timestamp": timestamp,
            "run_id": run_id,
            "mode": mode,
            "task_id": task_id,
            "execution_type": execution_type,
            "repetition": repetition,
            "outcome": verification.get("outcome"),
            "agent_reported_success": self._csv_safe(
                metrics.get("agent_reported_success")
            ),
            "iterations": metrics.get("iterations"),
            "tool_calls": metrics.get("tool_calls"),
            "tool_execution_failures": metrics.get(
                "tool_execution_failures"
            ),
            "llm_input_tokens": metrics.get("llm_input_tokens"),
            "llm_output_tokens": metrics.get("llm_output_tokens"),
            "llm_total_tokens": metrics.get("llm_total_tokens"),
            "jev_input_tokens": metrics.get("jev_input_tokens"),
            "jev_output_tokens": metrics.get("jev_output_tokens"),
            "jev_total_tokens": metrics.get("jev_total_tokens"),
            "combined_tokens": metrics.get("combined_tokens"),
            "llm_latency_seconds": metrics.get("llm_latency_seconds"),
            "jev_latency_seconds": metrics.get("jev_latency_seconds"),
            "tool_latency_seconds": metrics.get("tool_latency_seconds"),
            "total_latency_seconds": metrics.get("total_latency_seconds"),
            "escalation_count": metrics.get("escalation_count"),
            "tool_selection_escalations": metrics.get(
                "tool_selection_escalations"
            ),
            "completion_escalations": metrics.get(
                "completion_escalations"
            ),
            "escalation_succeeded_count": metrics.get(
                "escalation_succeeded_count"
            ),
            "termination_reason": metrics.get("termination_reason"),
            "error": error
        }

        record = dict(row)
        record["verification"] = verification
        record["raw_execution"] = raw_execution

        self._append_csv(row)
        self._append_jsonl(record)

        return record

    def count_records(self) -> int:
        """Return the number of JSONL records written so far."""

        if not self.jsonl_path.exists():
            return 0

        count = 0
        with self.jsonl_path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    count += 1
        return count

    def read_csv(self) -> list[dict]:
        """Return the CSV rows written so far (may be empty)."""

        if not self.csv_path.exists():
            return []

        with self.csv_path.open("r", encoding="utf-8") as file:
            return list(csv.DictReader(file))
