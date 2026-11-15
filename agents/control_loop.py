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
    decision_history: list[dict] = field(default_factory=list)

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

    
    @staticmethod
    def _has_valid_evidence(
        tool_name: str,
        execution_status: str,
        tool_result: dict
    ) -> bool:
        """
        Check whether a successful tool execution produced useful,
        structurally valid evidence.
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

    @staticmethod
    def _get_fulfilled_required_tools(
        required_tools: list[str],
        tool_history: list[dict]
    ) -> list[str]:
        """Return required tools that have produced valid evidence."""

        fulfilled = set()

        for call in tool_history:
            if ControlLoop._has_valid_evidence(
                call["tool_name"],
                call["execution_status"],
                call["result"]
            ):
                fulfilled.add(call["tool_name"])

        return [
            tool for tool in required_tools
            if tool in fulfilled
        ]

    def _required_tools_fulfilled(
        self,
        required_tools: list[str],
        tool_history: list[dict]
    ) -> bool:
        """
        True only when every mandatory tool has executed successfully
        and produced structurally valid evidence.

        An empty required_tools list imposes no evidence requirement
        and therefore returns True; the Jev completion probability
        remains the sole completion signal for such tasks.
        """
        if not required_tools:
            return True

        fulfilled = self._get_fulfilled_required_tools(
            required_tools,
            tool_history
        )

        return len(fulfilled) == len(required_tools)


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

    def run(
    self,
    task: str,
    plan: str,
    task_specification: dict | None = None
    ) -> ControlLoopResult:
        result = ControlLoopResult()

        # Backward-compatible fallback for existing direct callers.
        if task_specification is None:
            available_tools = self.registry.get_tool_descriptions()
            required_tools = list(available_tools.keys())
        else:
            all_tools = self.registry.get_tool_descriptions()

            allowed_tools = task_specification["allowed_tools"]
            required_tools = task_specification["required_tools"]

            # An allowed tool that is not registered cannot be
            # executed. Reject it instead of crashing on lookup.
            unknown_allowed = [
                name for name in allowed_tools
                if name not in all_tools
            ]

            if unknown_allowed:
                result.termination_reason = (
                    "unauthorized_tool_configuration"
                )
                result.final_response = (
                    "The task specification authorised tools that "
                    "are not registered: "
                    + ", ".join(unknown_allowed)
                    + ". Execution was stopped for safety."
                )
                return result

            available_tools = {
                name: all_tools[name]
                for name in allowed_tools
            }

        # Jev requires at least one available tool.
        # A task with no required or authorised tool execution
        # can be completed without entering the decision loop.
        if not available_tools:
            result.success = True
            result.termination_reason = "no_tool_execution_required"
            return result

        state = {
            "user_request": task,
            "high_level_plan": plan,
            "task_specification": task_specification or {},
            "required_tools": required_tools,
            "allowed_tools": list(available_tools.keys()),
            "fulfilled_required_tools": [],
            "iteration": 0,
            "tool_history": [],
            "latest_tool_result": None,
            "progress_history": []
        }

        call_counts = {}
        consecutive_no_progress = 0

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

            # Preserve every Jev decision, including decisions that
            # terminate execution before another tool call.
            result.decision_history.append({
                "iteration": iteration + 1,
                "selected_tool": decision.selected_tool,
                "tool_probabilities": decision.tool_probabilities,
                "tool_confidence": decision.tool_confidence,
                "completion_probability": completion_probability,
                "loop_probability": loop_probability,
                "progress_score": decision.progress_score,
                "model": decision.model,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "latency_seconds": decision.latency_seconds
            })

            state["progress_history"].append({
                "iteration": iteration + 1,
                "progress_score": decision.progress_score,
                "completion_probability": completion_probability,
                "loop_probability": loop_probability
            })

            # Completion requires both Jev's confirmation and valid
            # execution evidence for every mandatory tool. Jev's
            # prediction alone never establishes task success.
            state["fulfilled_required_tools"] = (
                self._get_fulfilled_required_tools(
                    required_tools,
                    state["tool_history"]
                )
            )

            required_tools_fulfilled = (
                self._required_tools_fulfilled(
                    required_tools,
                    state["tool_history"]
                )
            )

            # Completion takes priority over further tool selection.
            if (
                completion_probability >= self.completion_threshold
                and required_tools_fulfilled
            ):
                result.success = True
                result.termination_reason = "jev_detected_completion"
                break

            if (
                completion_probability >= self.completion_threshold
                and not required_tools_fulfilled
            ):
                result.termination_reason = (
                    "required_tools_not_fulfilled"
                )
                result.final_response = (
                    "The control system predicted task completion, "
                    "but not every required tool produced valid "
                    "execution evidence. Execution was stopped."
                )
                break

            # A high model-predicted loop probability alone is not
            # sufficient evidence of a loop. Require multiple completed
            # tool calls and negligible progress before terminating.
            has_repeated_action_history = len(result.tool_calls) >= 2
            has_negligible_progress = (
                self._normalise_probability(
                    decision.progress_score / 5.0
                ) <= 0.20
            )

            if (
                loop_probability >= self.loop_threshold
                and has_repeated_action_history
                and has_negligible_progress
            ):
                result.termination_reason = "jev_detected_loop"
                result.final_response = (
                    "The agent stopped because the control system "
                    "detected a likely repeated action pattern "
                    "with negligible progress."
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
                result.termination_reason = (
                    "unauthorized_jev_tool_selection"
                )
                result.final_response = (
                    "The control system selected a tool that is not "
                    "authorised for this task. Execution was stopped "
                    "for safety."
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
