import json
import re
import time

from dataclasses import dataclass, field
from typing import Any, Optional

from models.llm_client import GroqLLMClient
from tools.registry import (
    ToolRegistry,
    ToolExecutionError,
    build_default_registry
)

from agents.prompts import (
    build_baseline_system_prompt,
    build_initial_user_message
)


@dataclass
class AgentRunResult:
    task: str
    final_response: str
    success: bool

    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)

    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_total_tokens: int = 0

    llm_latency_seconds: float = 0.0
    tool_latency_seconds: float = 0.0
    total_latency_seconds: float = 0.0

    termination_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task,
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
            "tool_latency_seconds": round(
                self.tool_latency_seconds, 4
            ),
            "total_latency_seconds": round(
                self.total_latency_seconds, 4
            ),
            "termination_reason": self.termination_reason
        }


class BaselineAgent:
    """
    LLM-only customer-support agent.

    The Groq LLM controls:
    - Tool selection
    - Tool argument generation
    - Continuation decisions
    - Task completion decisions

    No Jev decisions are used in this agent.
    """

    def __init__(
        self,
        llm_client: Optional[GroqLLMClient] = None,
        registry: Optional[ToolRegistry] = None,
        max_iterations: int = 5
    ):
        if max_iterations < 1:
            raise ValueError(
                "max_iterations must be at least 1."
            )

        self.llm = llm_client or GroqLLMClient()

        self.registry = (
            registry or build_default_registry()
        )

        self.max_iterations = max_iterations

    @staticmethod
    def _parse_action(content: str) -> dict:
        """
        Parse the JSON action returned by the LLM.

        Also handles accidental Markdown code fences.
        """

        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned an empty response.")

        cleaned = content.strip()

        # Remove optional Markdown code fences.
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned
        )

        try:
            action = json.loads(cleaned)

        except json.JSONDecodeError:
            # Attempt to extract a JSON object if the model
            # accidentally included surrounding text.
            match = re.search(
                r"\{.*\}",
                cleaned,
                flags=re.DOTALL
            )

            if not match:
                raise ValueError(
                    "LLM response did not contain valid JSON."
                )

            action = json.loads(match.group(0))

        if not isinstance(action, dict):
            raise ValueError(
                "LLM action must be a JSON object."
            )

        return action

    def run(self, task: str) -> AgentRunResult:
        """
        Execute one customer-support task.
        """

        if not isinstance(task, str) or not task.strip():
            raise ValueError(
                "Task must be a non-empty string."
            )

        task = task.strip()

        self.registry.reset_state()

        messages = [
            {
                "role": "system",
                "content": build_baseline_system_prompt(
                    tool_schemas=self.registry.get_llm_tool_schemas(),
                    max_iterations=self.max_iterations
                )
            },
            {
                "role": "user",
                "content": build_initial_user_message(task)
            }
        ]

        result = AgentRunResult(
            task=task,
            final_response="",
            success=False
        )

        run_start = time.perf_counter()

        for iteration in range(self.max_iterations):

            result.iterations = iteration + 1

            # Ask the LLM to make the next control decision.
            llm_response = self.llm.generate(
                messages=messages,
                response_format={"type": "json_object"}
            )

            result.llm_input_tokens += (
                llm_response.input_tokens
            )

            result.llm_output_tokens += (
                llm_response.output_tokens
            )

            result.llm_total_tokens += (
                llm_response.total_tokens
            )

            result.llm_latency_seconds += (
                llm_response.latency_seconds
            )

            # Parse the LLM's structured action.
            try:
                action = self._parse_action(
                    llm_response.content
                )

            except ValueError as exc:
                result.final_response = (
                    "I could not interpret the decision "
                    f"returned by the language model: {exc}"
                )

                result.termination_reason = "invalid_llm_response"
                break

            action_type = action.get("action")

            if action_type == "final":

                final_response = action.get("response", "")

                if not isinstance(final_response, str):
                    final_response = ""

                result.final_response = final_response
                result.success = bool(final_response.strip())

                result.termination_reason = (
                    "llm_decided_complete"
                )

                break

            if action_type != "tool_call":

                messages.append({
                    "role": "assistant",
                    "content": llm_response.content
                })

                messages.append({
                    "role": "user",
                    "content": (
                        "Invalid action. The action field must be "
                        "'tool_call' or 'final'. Return a valid JSON "
                        "object using the required response format."
                    )
                })

                continue

            tool_name = action.get("tool_name")
            arguments = action.get("arguments")

            if not isinstance(tool_name, str):
                tool_name = ""

            if not isinstance(arguments, dict):
                arguments = {}

            decision_summary = action.get(
                "decision_summary", ""
            )

            # Execute the requested tool.
            tool_start = time.perf_counter()

            try:
                tool_result = self.registry.execute(
                    tool_name,
                    arguments
                )

                execution_status = "success"

            except ToolExecutionError as exc:
                tool_result = {
                    "error": str(exc)
                }

                execution_status = "error"

            except Exception as exc:
                tool_result = {
                    "error": (
                        f"Unexpected tool execution error: {exc}"
                    )
                }

                execution_status = "error"

            tool_latency = (
                time.perf_counter() - tool_start
            )

            result.tool_latency_seconds += tool_latency

            result.tool_calls.append({
                "iteration": iteration + 1,
                "tool_name": tool_name,
                "arguments": arguments,
                "decision_summary": decision_summary,
                "execution_status": execution_status,
                "result": tool_result,
                "latency_seconds": round(
                    tool_latency, 4
                )
            })

            # Add the model's decision and tool result
            # to the conversation history.
            messages.append({
                "role": "assistant",
                "content": llm_response.content
            })

            messages.append({
                "role": "user",
                "content": (
                    "TOOL EXECUTION RESULT:\n"
                    + json.dumps(
                        {
                            "tool_name": tool_name,
                            "execution_status": execution_status,
                            "result": tool_result
                        },
                        ensure_ascii=False
                    )
                    + "\n\nReview this result and decide "
                    "the next action. Return only valid JSON."
                )
            })

        else:
            result.termination_reason = (
                "maximum_iterations_reached"
            )

            result.final_response = (
                "I could not complete the request within "
                f"the limit of {self.max_iterations} tool calls. "
                "Here is the information gathered so far: "
                + json.dumps(
                    [
                        call["result"]
                        for call in result.tool_calls
                    ],
                    ensure_ascii=False
                )
            )

        result.total_latency_seconds = (
            time.perf_counter() - run_start
        )

        return result

    def close(self):
        """Close the underlying Groq client."""
        close_method = getattr(
            self.llm,
            "close",
            None
        )

        if callable(close_method):
            close_method()
