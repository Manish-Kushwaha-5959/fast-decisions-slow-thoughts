
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from agents.control_loop import ControlLoop
from agents.prompts import (
    build_hybrid_planning_prompt,
    build_hybrid_final_prompt
)
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

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "plan": self.plan,
            "final_response": self.final_response,
            "success": self.success,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
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
            "termination_reason": self.termination_reason
        }


class HybridAgent:
    """
    Hybrid customer-support agent (Mode B).

    Groq:
    - High-level planning
    - Tool argument generation
    - Final response generation

    Jev:
    - Tool selection
    - Completion detection
    - Loop detection
    - Progress estimation
    """

    def __init__(
        self,
        llm_client: Optional[GroqLLMClient] = None,
        jev_client: Optional[JevClient] = None,
        registry: Optional[ToolRegistry] = None,
        max_iterations: int = 5
    ):
        self.llm = llm_client or GroqLLMClient()
        self.jev = jev_client or JevClient()
        self.registry = registry or build_default_registry()

        self.control_loop = ControlLoop(
            llm_client=self.llm,
            jev_client=self.jev,
            registry=self.registry,
            max_iterations=max_iterations
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

    def run(self, task: str) -> HybridAgentRunResult:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Task must be a non-empty string.")

        task = task.strip()
        self.registry.reset_state()

        result = HybridAgentRunResult(task=task)
        run_start = time.perf_counter()

        # Phase 1: Groq creates the high-level plan.
        try:
            planning_response = self.llm.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the planning component of a "
                            "hybrid customer-support agent."
                        )
                    },
                    {
                        "role": "user",
                        "content": build_hybrid_planning_prompt(task)
                    }
                ],
                response_format={"type": "json_object"}
            )

            result.llm_input_tokens += planning_response.input_tokens
            result.llm_output_tokens += planning_response.output_tokens
            result.llm_total_tokens += planning_response.total_tokens
            result.llm_latency_seconds += planning_response.latency_seconds

            planning_data = self._parse_json(
                planning_response.content
            )

            plan = planning_data.get("plan")

            if not isinstance(plan, str) or not plan.strip():
                raise ValueError("LLM did not provide a usable plan.")

            result.plan = plan.strip()

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
            plan=result.plan
        )

        result.iterations = loop_result.iterations
        result.tool_calls = loop_result.tool_calls
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
