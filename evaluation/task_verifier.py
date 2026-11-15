"""
Independent task verification for the Phase 7 benchmark framework.

The verifier never trusts an agent's self-reported ``success`` flag.
It recomputes the outcome from deterministic evidence only:

- the executed tool calls and their structural results,
- the final response text,
- the task's declared verification rules.

Outcomes:
- ``verified``   — every applicable check passed.
- ``failed``     — at least one check failed (evidence shows the
                   expected outcome was not achieved).
- ``unverifiable`` — the available evidence is insufficient to judge
                   (missing execution record, no verification rules,
                   no tool history, or a run that errored).

The evidence predicates are deliberately implemented locally instead
of importing ``ControlLoop._has_valid_evidence``. The verifier must
stay independent of agent internals so it can catch agent-side bugs.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tools.registry import build_default_registry


VERIFIED = "verified"
FAILED = "failed"
UNVERIFIABLE = "unverifiable"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_PATH = PROJECT_ROOT / "data" / "tasks.json"


def _has_valid_evidence(
    tool_name: str,
    execution_status: str,
    tool_result: Any
) -> bool:
    """
    Check whether a successful tool execution produced useful,
    structurally valid evidence.

    Mirrors the controller's evidence rules but is implemented here
    independently so verification does not depend on agent code.
    """

    if execution_status != "success":
        return False

    if not isinstance(tool_result, dict):
        return False

    if "error" in tool_result:
        return False

    if tool_name == "check_service_status":
        return (
            isinstance(tool_result.get("service"), str)
            and bool(tool_result["service"].strip())
            and tool_result.get("status")
            in {"operational", "degraded", "outage"}
            and tool_result.get("source") == "local_simulation"
        )

    if tool_name == "search_knowledge_base":
        results = tool_result.get("results")

        return (
            isinstance(results, list)
            and len(results) > 0
            and tool_result.get("result_count", 0) > 0
        )

    if tool_name == "create_support_ticket":
        return (
            isinstance(tool_result.get("ticket_id"), str)
            and bool(tool_result["ticket_id"])
            and tool_result.get("status") == "created"
            and tool_result.get("simulation") is True
        )

    # Generic fallback for future registered tools.
    return bool(tool_result)


def load_tasks(path: str | Path | None = DEFAULT_TASKS_PATH) -> list[dict]:
    """Load and validate the benchmark task dataset."""

    tasks_path = Path(path) if path is not None else DEFAULT_TASKS_PATH

    if not tasks_path.exists():
        raise FileNotFoundError(f"Task dataset not found: {tasks_path}")

    with tasks_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        tasks = data.get("tasks")
    else:
        tasks = data

    if not isinstance(tasks, list) or not tasks:
        raise ValueError(
            "Task dataset must contain a non-empty 'tasks' list."
        )

    problems = validate_tasks(tasks)

    if problems:
        raise ValueError(
            "Invalid task dataset:\n" + "\n".join(f"  - {p}" for p in problems)
        )

    return tasks


def validate_tasks(tasks: list[dict]) -> list[str]:
    """
    Validate the structure of a task dataset.

    Returns a list of human-readable problems (empty when valid).
    """

    problems: list[str] = []

    if not isinstance(tasks, list) or not tasks:
        return ["Task dataset must be a non-empty list."]

    registry = build_default_registry()
    registered = set(registry.get_tool_names())
    seen_ids: set[str] = set()

    for index, task in enumerate(tasks):
        label = f"task[{index}]"

        if not isinstance(task, dict):
            problems.append(f"{label}: must be a JSON object.")
            continue

        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            problems.append(f"{label}: 'id' must be a non-empty string.")
        elif task_id in seen_ids:
            problems.append(f"{label}: duplicate id '{task_id}'.")
        else:
            seen_ids.add(task_id)

        for field in ("description", "expected_outcome"):
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(
                    f"{label} ({task_id}): '{field}' must be a "
                    "non-empty string."
                )

        for field in ("category", "difficulty"):
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(
                    f"{label} ({task_id}): '{field}' must be a "
                    "non-empty string."
                )

        expected_tools = task.get("expected_tools")
        if (
            not isinstance(expected_tools, list)
            or not expected_tools
            or not all(
                isinstance(tool, str) and tool in registered
                for tool in expected_tools
            )
        ):
            problems.append(
                f"{label} ({task_id}): 'expected_tools' must be a "
                "non-empty list of registered tool names; an "
                "unregistered tool name was found."
            )

        verification = task.get("verification")
        if not isinstance(verification, dict) or not verification:
            problems.append(
                f"{label} ({task_id}): 'verification' block is required."
            )
            continue

        for field in ("required_tools", "forbidden_tools"):
            value = verification.get(field, [])
            if (
                not isinstance(value, list)
                or not all(isinstance(item, str) for item in value)
            ):
                problems.append(
                    f"{label} ({task_id}): verification.{field} must be "
                    "a list of strings."
                )

        required = verification.get("required_tools", [])
        if any(tool not in registered for tool in required):
            problems.append(
                f"{label} ({task_id}): verification.required_tools "
                "contains an unregistered tool."
            )

        if any(tool not in expected_tools for tool in required):
            problems.append(
                f"{label} ({task_id}): verification.required_tools must "
                "be a subset of expected_tools."
            )

        for field in ("response_contains", "response_excludes"):
            value = verification.get(field, [])
            if (
                not isinstance(value, list)
                or not all(isinstance(item, str) and item for item in value)
            ):
                problems.append(
                    f"{label} ({task_id}): verification.{field} must be "
                    "a list of non-empty strings."
                )

        if not any(key in verification for key in (
            "required_tools", "forbidden_tools", "response_contains",
            "response_excludes"
        )):
            problems.append(
                f"{label} ({task_id}): verification block defines no "
                "checkable rules."
            )

    return problems


@dataclass
class CheckResult:
    """Outcome of one deterministic verification check."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail
        }


@dataclass
class VerificationResult:
    """Independent verification outcome for one executed task."""

    task_id: str
    outcome: str                    # verified | failed | unverifiable
    checks: list[CheckResult]
    reason: str
    agent_reported_success: Optional[bool]

    @property
    def passed(self) -> bool:
        return self.outcome == VERIFIED

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "checks": [check.to_dict() for check in self.checks],
            "reason": self.reason,
            "agent_reported_success": self.agent_reported_success
        }


class TaskVerifier:
    """
    Deterministically verify a benchmark task outcome.

    The agent's own ``success`` flag is recorded for comparison but
    never used as ground truth.
    """

    def verify(
        self,
        task: dict,
        execution: Any
    ) -> VerificationResult:
        """
        Verify one executed task.

        Parameters
        ----------
        task:
            A task definition from ``data/tasks.json``.
        execution:
            The agent run record (``AgentRunResult.to_dict()`` /
            ``HybridAgentRunResult.to_dict()`` output, or an error
            record built by the benchmark runner).
        """

        if not isinstance(task, dict):
            return VerificationResult(
                task_id="<invalid-task>",
                outcome=UNVERIFIABLE,
                checks=[],
                reason="Task definition is not a JSON object.",
                agent_reported_success=None
            )

        task_id = str(task.get("id", "<missing-id>"))

        if not isinstance(execution, dict):
            return VerificationResult(
                task_id=task_id,
                outcome=UNVERIFIABLE,
                checks=[],
                reason=(
                    "No execution record available; the outcome cannot "
                    "be verified."
                ),
                agent_reported_success=None
            )

        agent_success = execution.get("success")
        if not isinstance(agent_success, bool):
            agent_success = None

        # A run that crashed carries an error marker; its outcome is
        # unverifiable rather than failed.
        if execution.get("error"):
            return VerificationResult(
                task_id=task_id,
                outcome=UNVERIFIABLE,
                checks=[],
                reason=(
                    f"Run did not complete: {execution['error']}"
                ),
                agent_reported_success=agent_success
            )

        verification = task.get("verification")
        if not isinstance(verification, dict) or not verification:
            return VerificationResult(
                task_id=task_id,
                outcome=UNVERIFIABLE,
                checks=[],
                reason="Task defines no verification criteria.",
                agent_reported_success=agent_success
            )

        tool_calls = execution.get("tool_calls")
        if tool_calls is None:
            return VerificationResult(
                task_id=task_id,
                outcome=UNVERIFIABLE,
                checks=[],
                reason=(
                    "Execution record contains no tool-call history; "
                    "the run is incomplete."
                ),
                agent_reported_success=agent_success
            )

        checks: list[CheckResult] = self._run_checks(
            task, verification, execution, tool_calls
        )

        if not checks:
            return VerificationResult(
                task_id=task_id,
                outcome=UNVERIFIABLE,
                checks=[],
                reason=(
                    "Verification rules define no checkable criteria."
                ),
                agent_reported_success=agent_success
            )

        failed = [check for check in checks if not check.passed]

        if failed:
            outcome = FAILED
            reason = "; ".join(
                f"{check.name}: {check.detail}" for check in failed
            )
        else:
            outcome = VERIFIED
            reason = "All verification checks passed."

        return VerificationResult(
            task_id=task_id,
            outcome=outcome,
            checks=checks,
            reason=reason,
            agent_reported_success=agent_success
        )

    def _run_checks(
        self,
        task: dict,
        verification: dict,
        execution: dict,
        tool_calls: list[dict]
    ) -> list[CheckResult]:
        """Run every declared verification rule; return the results."""

        checks: list[CheckResult] = []

        final_response = execution.get("final_response")
        if not isinstance(final_response, str):
            final_response = ""

        normalized_response = final_response.lower()

        require_final = verification.get(
            "require_final_response", True
        )
        if require_final:
            checks.append(CheckResult(
                name="final_response_present",
                passed=bool(final_response.strip()),
                detail=(
                    "Final response is non-empty."
                    if final_response.strip()
                    else "Final response is missing or empty."
                )
            ))

        executed_tools = [
            call.get("tool_name") for call in tool_calls
            if isinstance(call, dict)
        ]

        # Required tools must have executed with valid evidence.
        if verification.get("require_valid_evidence", True):
            for tool_name in verification.get("required_tools", []):
                evidence = [
                    call for call in tool_calls
                    if isinstance(call, dict)
                    and call.get("tool_name") == tool_name
                    and _has_valid_evidence(
                        tool_name,
                        call.get("execution_status"),
                        call.get("result")
                    )
                ]
                checks.append(CheckResult(
                    name=f"required_tool_evidence:{tool_name}",
                    passed=bool(evidence),
                    detail=(
                        f"'{tool_name}' executed with valid evidence."
                        if evidence
                        else (
                            f"'{tool_name}' never executed successfully "
                            "with valid evidence."
                        )
                    )
                ))
        else:
            for tool_name in verification.get("required_tools", []):
                executed = tool_name in executed_tools
                checks.append(CheckResult(
                    name=f"required_tool_executed:{tool_name}",
                    passed=executed,
                    detail=(
                        f"'{tool_name}' was executed."
                        if executed
                        else f"'{tool_name}' was never executed."
                    )
                ))

        # Forbidden tools must never execute.
        for tool_name in verification.get("forbidden_tools", []):
            executed = tool_name in executed_tools
            checks.append(CheckResult(
                name=f"forbidden_tool_absent:{tool_name}",
                passed=not executed,
                detail=(
                    f"'{tool_name}' was not executed."
                    if not executed
                    else f"'{tool_name}' executed but is forbidden."
                )
            ))

        # Executed tools must stay within the acceptable set.
        expected_tools = task.get("expected_tools")
        if isinstance(expected_tools, list) and expected_tools:
            unexpected = [
                tool for tool in executed_tools
                if tool not in expected_tools
            ]
            checks.append(CheckResult(
                name="expected_tools_only",
                passed=not unexpected,
                detail=(
                    "Executed tools are within the acceptable set."
                    if not unexpected
                    else f"Unexpected tools executed: {unexpected}."
                )
            ))

        # Response content rules.
        for phrase in verification.get("response_contains", []):
            present = phrase.lower() in normalized_response
            checks.append(CheckResult(
                name=f"response_contains:{phrase}",
                passed=present,
                detail=(
                    f"Response contains '{phrase}'."
                    if present
                    else f"Response is missing '{phrase}'."
                )
            ))

        for phrase in verification.get("response_excludes", []):
            present = phrase.lower() in normalized_response
            checks.append(CheckResult(
                name=f"response_excludes:{phrase}",
                passed=not present,
                detail=(
                    f"Response omits '{phrase}'."
                    if not present
                    else f"Response must not contain '{phrase}'."
                )
            ))

        return checks
