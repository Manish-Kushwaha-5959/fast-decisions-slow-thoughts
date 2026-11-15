import json
import time
from dataclasses import dataclass, field
from typing import Any

from models.jev_client import JevClient, JevClientError
from models.llm_client import GroqLLMClient
from tools.registry import (
    ToolRegistry,
    ToolExecutionError
)
from agents.prompts import build_hybrid_argument_prompt


@dataclass
class ControlLoopResult:
    success: bool = False
    final_response: str = ""
    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)

    jev_input_tokens: int = 0
    jev_output_tokens: int = 0
    jev_total_tokens: int = 0
    jev_latency_seconds: float = 0.0

    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_total_tokens: int = 0
    llm_latency_seconds: float = 0.0

    tool_latency_seconds: float = 0.0
    termination_reason: str = ""


class ControlLoop:
    """
    Mode B execution controller.

    Jev controls:
    - Next-tool selection
    - Completion detection
    - Loop detection
    - Progress estimation

    Groq controls:
    - Tool argument generation
    """

    def __init__(
        self,
        llm_client: GroqLLMClient,
        jev_client: JevClient,
        registry: ToolRegistry,
        max_iterations: int = 5,
        completion_threshold: float = 0.70,
        loop_threshold: float = 0.70,
        max_identical_calls: int = 2
    ):
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1.")

        if max_identical_calls < 1:
            raise ValueError("max_identical_calls must be at least 1.")

        self.llm = llm_client
        self.jev = jev_client
        self.registry = registry
        self.max_iterations = max_iterations
        self.completion_threshold = completion_threshold
        self.loop_threshold = loop_threshold
        self.max_identical_calls = max_identical_calls

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
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "LLM response did not contain valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError("LLM response must be a JSON object.")

        return parsed

    @staticmethod
    def _normalise_probability(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(1.0, number))

    @staticmethod
    def _call_signature(tool_name: str, arguments: dict) -> str:
        return json.dumps(
            {
                "tool_name": tool_name,
                "arguments": arguments
            },
            sort_keys=True,
            ensure_ascii=False
        )

    def _record_jev_usage(self, result, decision):
        result.jev_input_tokens += decision.input_tokens
        result.jev_output_tokens += decision.output_tokens
        result.jev_total_tokens += decision.total_tokens
        result.jev_latency_seconds += decision.latency_seconds

    def _record_llm_usage(self, result, response):
        result.llm_input_tokens += response.input_tokens
        result.llm_output_tokens += response.output_tokens
        result.llm_total_tokens += response.total_tokens
        result.llm_latency_seconds += response.latency_seconds

    def run(self, task: str, plan: str) -> ControlLoopResult:
        result = ControlLoopResult()

        state = {
            "user_request": task,
            "high_level_plan": plan,
            "iteration": 0,
            "tool_history": [],
            "latest_tool_result": None,
            "progress_history": []
        }

        call_counts = {}

        available_tools = self.registry.get_tool_descriptions()

        for iteration in range(self.max_iterations + 1):
            state["iteration"] = iteration + 1
            result.iterations = iteration + 1

            # Jev evaluates the current state before the next action.
            try:
                decision = self.jev.evaluate_state(
                    state=state,
                    available_tools=available_tools
                )
                self._record_jev_usage(result, decision)

            except JevClientError as exc:
                result.termination_reason = "jev_error"
                result.final_response = (
                    "The control system could not evaluate the "
                    f"current task state: {exc}"
                )
                break

            completion_probability = self._normalise_probability(
                decision.completion_probability
            )
            loop_probability = self._normalise_probability(
                decision.loop_probability
            )

            state["progress_history"].append({
                "iteration": iteration + 1,
                "progress_score": decision.progress_score,
                "completion_probability": completion_probability,
                "loop_probability": loop_probability
            })

            # Completion takes priority over further tool selection.
            if completion_probability >= self.completion_threshold:
                result.success = True
                result.termination_reason = "jev_detected_completion"
                break

            if loop_probability >= self.loop_threshold:
                result.termination_reason = "jev_detected_loop"
                result.final_response = (
                    "The agent stopped because the control system "
                    "detected a repeated action pattern without "
                    "sufficient progress."
                )
                break

            if len(result.tool_calls) >= self.max_iterations:
                result.termination_reason = "maximum_iterations_reached"
                result.final_response = (
                    "The agent reached its maximum tool-call limit "
                    f"({self.max_iterations}). Jev did not confirm "
                    "task completion."
                )
                break

            selected_tool = decision.selected_tool

            if selected_tool not in available_tools:
                result.termination_reason = "invalid_jev_tool_selection"
                result.final_response = (
                    "The control system selected a tool that is not "
                    "registered. Execution was stopped for safety."
                )
                break

            tool_definition = self.registry.get_tool(selected_tool)

            # Groq generates arguments only; it cannot change Jev's
            # selected tool.
            argument_prompt = build_hybrid_argument_prompt(
                task=task,
                plan=plan,
                tool_name=selected_tool,
                tool_description=tool_definition.description,
                tool_parameters=tool_definition.parameters,
                history=state["tool_history"]
            )

            try:
                argument_response = self.llm.generate(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You generate arguments for a selected "
                                "customer-support tool. Follow the "
                                "requested JSON format exactly."
                            )
                        },
                        {
                            "role": "user",
                            "content": argument_prompt
                        }
                    ],
                    response_format={"type": "json_object"}
                )

                self._record_llm_usage(result, argument_response)

                parsed_arguments = self._parse_json(
                    argument_response.content
                )

                arguments = parsed_arguments.get("arguments")

                if not isinstance(arguments, dict):
                    raise ValueError(
                        "LLM did not return an arguments object."
                    )

            except Exception as exc:
                result.termination_reason = "argument_generation_error"
                result.final_response = (
                    "The language model could not generate valid "
                    f"arguments for {selected_tool}: {exc}"
                )
                break

            # Deterministic protection against identical repeated calls.
            signature = self._call_signature(
                selected_tool,
                arguments
            )

            call_counts[signature] = call_counts.get(signature, 0) + 1

            if call_counts[signature] > self.max_identical_calls:
                result.termination_reason = "repeated_tool_call"
                result.final_response = (
                    "The agent stopped because it was about to repeat "
                    "the same tool call without a new action."
                )
                break

            # Execute through the common registry.
            tool_start = time.perf_counter()

            try:
                tool_result = self.registry.execute(
                    selected_tool,
                    arguments
                )
                execution_status = "success"

            except (ToolExecutionError, Exception) as exc:
                tool_result = {"error": str(exc)}
                execution_status = "error"

            tool_latency = time.perf_counter() - tool_start
            result.tool_latency_seconds += tool_latency

            call_record = {
                "iteration": iteration + 1,
                "tool_name": selected_tool,
                "arguments": arguments,
                "execution_status": execution_status,
                "result": tool_result,
                "jev_confidence": decision.tool_confidence,
                "jev_progress_score": decision.progress_score,
                "jev_completion_probability": completion_probability,
                "jev_loop_probability": loop_probability,
                "latency_seconds": round(tool_latency, 4)
            }

            result.tool_calls.append(call_record)
            state["tool_history"].append(call_record)
            state["latest_tool_result"] = {
                "tool_name": selected_tool,
                "execution_status": execution_status,
                "result": tool_result
            }

        else:
            result.termination_reason = "maximum_iterations_reached"
            result.final_response = (
                "The agent reached its maximum tool-call limit "
                f"({self.max_iterations}) before Jev confirmed "
                "that the task was complete."
            )

        return result
