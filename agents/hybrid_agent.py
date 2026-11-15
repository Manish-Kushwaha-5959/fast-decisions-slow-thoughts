
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from agents.control_loop import ControlLoop
from agents.escalation_agent import EscalationAgent
from agents.prompts import (
    build_hybrid_planning_prompt,
    build_hybrid_final_prompt
)
from config.settings import settings
from models.jev_client import JevClient
from models.llm_client import GroqLLMClient
from tools.registry import ToolRegistry, build_default_registry


@dataclass
class HybridAgentRunResult:
    task: str
    plan: str = ""
    final_response: str = ""
    success: bool = False

    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    decision_history: list[dict] = field(default_factory=list)

    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_total_tokens: int = 0
    llm_latency_seconds: float = 0.0

    jev_input_tokens: int = 0
    jev_output_tokens: int = 0
    jev_total_tokens: int = 0
    jev_latency_seconds: float = 0.0

    tool_latency_seconds: float = 0.0
    total_latency_seconds: float = 0.0

    termination_reason: str = ""
    task_specification: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "plan": self.plan,
            "final_response": self.final_response,
            "success": self.success,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "decision_history": self.decision_history,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_total_tokens": self.llm_total_tokens,
            "llm_latency_seconds": round(
                self.llm_latency_seconds, 4
            ),
            "jev_input_tokens": self.jev_input_tokens,
            "jev_output_tokens": self.jev_output_tokens,
            "jev_total_tokens": self.jev_total_tokens,
            "jev_latency_seconds": round(
                self.jev_latency_seconds, 4
            ),
            "tool_latency_seconds": round(
                self.tool_latency_seconds, 4
            ),
            "total_latency_seconds": round(
                self.total_latency_seconds, 4
            ),
            "termination_reason": self.termination_reason,
            "task_specification": self.task_specification
        }


class HybridAgent:
    """
    Hybrid customer-support agent (Mode B / Mode C).

    Groq:
    - High-level planning
    - Tool argument generation
    - Final response generation
    - Uncertainty review when Jev escalates (Mode C)

    Jev:
    - Tool selection
    - Completion detection
    - Loop detection
    - Progress estimation

    Mode C extends Mode B with uncertainty-driven escalation: Jev's
    low-confidence tool selections and ambiguous completion
    probabilities are sent to Groq for review. Groq advises; the
    controller keeps final authority and every Phase 5 safeguard
    (allowed_tools, ticket authorisation, evidence gate) still applies.
    """

    def __init__(
        self,
        llm_client: Optional[GroqLLMClient] = None,
        jev_client: Optional[JevClient] = None,
        registry: Optional[ToolRegistry] = None,
        max_iterations: int = 5,
        enable_escalation: bool = True,
        tool_confidence_threshold: Optional[float] = None,
        completion_ambiguity_lower: Optional[float] = None,
        completion_ambiguity_upper: Optional[float] = None
    ):
        self.llm = llm_client or GroqLLMClient()
        self.jev = jev_client or JevClient()
        self.registry = registry or build_default_registry()

        self.escalation_agent: Optional[EscalationAgent] = None

        if enable_escalation:
            self.escalation_agent = EscalationAgent(
                llm_client=self.llm,
                tool_confidence_threshold=(
                    tool_confidence_threshold
                    if tool_confidence_threshold is not None
                    else settings.tool_confidence_threshold
                ),
                completion_ambiguity_lower=(
                    completion_ambiguity_lower
                    if completion_ambiguity_lower is not None
                    else settings.completion_ambiguity_lower
                ),
                completion_ambiguity_upper=(
                    completion_ambiguity_upper
                    if completion_ambiguity_upper is not None
                    else settings.completion_ambiguity_upper
                )
            )

        self.mode = "C" if self.escalation_agent else "B"

        self.control_loop = ControlLoop(
            llm_client=self.llm,
            jev_client=self.jev,
            registry=self.registry,
            max_iterations=max_iterations,
            escalation_agent=self.escalation_agent
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned an empty response.")

        cleaned = content.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "LLM response was not valid JSON."
            ) from exc

        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object.")

        return result

    
    @staticmethod
    def _validate_task_specification(
        specification: dict,
        available_tools: dict[str, str],
        task: str
    ) -> dict:
        """
        Validate the planner's task specification before execution.
        """

        if not isinstance(specification, dict):
            raise ValueError(
                "Task specification must be a JSON object."
            )

        required_fields = {
            "objective",
            "required_outcomes",
            "allowed_tools",
            "required_tools",
            "completion_criteria"
        }

        if set(specification.keys()) != required_fields:
            raise ValueError(
                "Task specification must contain exactly: "
                f"{sorted(required_fields)}"
            )

        objective = specification["objective"]
        outcomes = specification["required_outcomes"]
        allowed_tools = specification["allowed_tools"]
        required_tools = specification["required_tools"]
        criteria = specification["completion_criteria"]

        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("Task objective must be a non-empty string.")

        if (
            not isinstance(outcomes, list)
            or not outcomes
            or not all(
                isinstance(item, str) and item.strip()
                for item in outcomes
            )
        ):
            raise ValueError(
                "required_outcomes must be a non-empty list of strings."
            )

        if (
            not isinstance(allowed_tools, list)
            or not all(
                isinstance(item, str) and item in available_tools
                for item in allowed_tools
            )
        ):
            raise ValueError(
                "allowed_tools contains an invalid or unregistered tool."
            )

        if len(allowed_tools) != len(set(allowed_tools)):
            raise ValueError("allowed_tools must not contain duplicates.")

        if (
            not isinstance(required_tools, list)
            or not all(
                isinstance(item, str) and item.strip()
                for item in required_tools
            )
        ):
            raise ValueError(
                "required_tools must be a list of strings."
            )

        # Every required tool must be among the allowed tools.
        for tool in required_tools:
            if tool not in allowed_tools:
                raise ValueError(
                    "Required tool is not in allowed_tools: "
                    f"{tool}"
                )

        if (
            not isinstance(criteria, list)
            or not criteria
            or not all(
                isinstance(item, str) and item.strip()
                for item in criteria
            )
        ):
            raise ValueError(
                "completion_criteria must be a non-empty list of strings."
            )

        # Creating a support ticket is a state-changing action.
        # Require explicit user authorisation independently of
        # the planner's interpretation.
        if "create_support_ticket" in allowed_tools:
            explicit_ticket_request = re.search(
                r"\b(create|open|raise|file|submit|log)\b"
                r".{0,50}\b(ticket|support ticket)\b"
                r"|\b(ticket|support ticket)\b"
                r".{0,50}\b(create|open|raise|file|submit|log)\b",
                task,
                flags=re.IGNORECASE
            )

            if not explicit_ticket_request:
                raise ValueError(
                    "Support-ticket creation was not explicitly "
                    "requested by the user."
                )

        return {
            "objective": objective.strip(),
            "required_outcomes": [
                item.strip() for item in outcomes
            ],
            "allowed_tools": allowed_tools.copy(),
            "required_tools": [item.strip() for item in required_tools],
            "completion_criteria": [
                item.strip() for item in criteria
            ]
        }


    def run(self, task: str) -> HybridAgentRunResult:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Task must be a non-empty string.")

        task = task.strip()
        self.registry.reset_state()

        result = HybridAgentRunResult(task=task)
        run_start = time.perf_counter()

        # Phase 1: Groq creates the plan and task specification.
        available_tools = self.registry.get_tool_descriptions()

        try:
            planning_response = self.llm.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the task-planning component of a "
                            "hybrid customer-support agent. "
                            "Return a valid structured task specification."
                        )
                    },
                    {
                        "role": "user",
                        "content": build_hybrid_planning_prompt(
                            task=task,
                            available_tools=available_tools
                        )
                    }
                ],
                response_format={"type": "json_object"}
            )

            result.llm_input_tokens += planning_response.input_tokens
            result.llm_output_tokens += planning_response.output_tokens
            result.llm_total_tokens += planning_response.total_tokens
            result.llm_latency_seconds += (
                planning_response.latency_seconds
            )

            planning_data = self._parse_json(
                planning_response.content
            )

            plan = planning_data.get("plan")
            specification = planning_data.get("task_specification")

            if not isinstance(plan, str) or not plan.strip():
                raise ValueError(
                    "LLM did not provide a usable plan."
                )

            result.plan = plan.strip()

            result.task_specification = (
                self._validate_task_specification(
                    specification=specification,
                    available_tools=available_tools,
                    task=task
                )
            )

        except Exception as exc:
            result.termination_reason = "planning_error"
            result.final_response = (
                f"The planning stage could not be completed: {exc}"
            )
            result.total_latency_seconds = (
                time.perf_counter() - run_start
            )
            return result


        # Phase 2: Jev-controlled execution loop.
        loop_result = self.control_loop.run(
            task=task,
            plan=result.plan,
            task_specification=result.task_specification
        )

        result.iterations = loop_result.iterations
        result.tool_calls = loop_result.tool_calls
        result.decision_history = loop_result.decision_history
        result.termination_reason = loop_result.termination_reason

        result.llm_input_tokens += loop_result.llm_input_tokens
        result.llm_output_tokens += loop_result.llm_output_tokens
        result.llm_total_tokens += loop_result.llm_total_tokens
        result.llm_latency_seconds += loop_result.llm_latency_seconds

        result.jev_input_tokens = loop_result.jev_input_tokens
        result.jev_output_tokens = loop_result.jev_output_tokens
        result.jev_total_tokens = loop_result.jev_total_tokens
        result.jev_latency_seconds = loop_result.jev_latency_seconds

        result.tool_latency_seconds = loop_result.tool_latency_seconds

                # Phase 3: Groq prepares the final user-facing response.

        # Handle Jev API failures directly instead of asking Groq
        # to generate a response that might incorrectly imply success.
        if result.termination_reason == "jev_error":
            result.final_response = (
                "I couldn't complete your request because the control "
                "system encountered an error. Please try again later."
            )

        else:
            try:
                final_response = self.llm.generate(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are the final-response component of "
                                "a customer-support agent."
                            )
                        },
                        {
                            "role": "user",
                            "content": build_hybrid_final_prompt(
                                task=task,
                                plan=result.plan,
                                tool_history=result.tool_calls,
                                termination_reason=result.termination_reason
                            )
                        }
                    ],
                    response_format={"type": "json_object"}
                )

                result.llm_input_tokens += final_response.input_tokens
                result.llm_output_tokens += final_response.output_tokens
                result.llm_total_tokens += final_response.total_tokens
                result.llm_latency_seconds += final_response.latency_seconds

                final_data = self._parse_json(final_response.content)
                response_text = final_data.get("response", "")

                if not isinstance(response_text, str):
                    raise ValueError(
                        "Final response field must be a string."
                    )

                result.final_response = response_text.strip()

            except Exception as exc:
                # Preserve the execution result if final response generation
                # fails. Do not claim that the task was completed.
                result.final_response = (
                    "The execution stage finished, but the final response "
                    f"could not be generated: {exc}\n\n"
                    "Execution summary:\n"
                    + json.dumps(
                        result.tool_calls,
                        ensure_ascii=False,
                        indent=2
                    )
                )

                result.termination_reason += "_final_response_error"

        result.success = (
            loop_result.success
            and bool(result.final_response.strip())
        )

        result.total_latency_seconds = (
            time.perf_counter() - run_start
        )

        return result

    def close(self):
        for client in (self.llm,):
            close_method = getattr(client, "close", None)
            if callable(close_method):
                close_method()
