"""
Mode C escalation component.

Jev makes fast control decisions. When a decision is uncertain, this
component asks the Groq LLM to review it and returns a validated,
structured recommendation. The controller (ControlLoop) always keeps
final authority: an escalation can advise, but never bypasses the
allowed-tools restriction, the create_support_ticket authorisation,
or the evidence-based completion gate.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from agents.prompts import (
    build_escalation_completion_prompt,
    build_escalation_tool_prompt
)


# Provisional defaults. They require empirical calibration before they
# can be treated as measured values (see documentations/risks.md).
DEFAULT_TOOL_CONFIDENCE_THRESHOLD = 0.60
DEFAULT_COMPLETION_AMBIGUITY_LOWER = 0.50
DEFAULT_COMPLETION_AMBIGUITY_UPPER = 0.70


@dataclass
class EscalationOutcome:
    """Validated result of one escalation review."""

    decision_type: str          # "tool_selection" | "task_completion"
    escalated: bool = True
    reason: str = ""
    recommendation: dict = field(default_factory=dict)
    succeeded: bool = False     # a usable structured response arrived
    final_decision: Any = None  # controller-ready decision value
    error: str = ""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0


class EscalationAgent:
    """
    Decides when Jev's decisions are uncertain and asks Groq to review
    them. Pure advisory role; every recommendation is re-validated by
    the controller before anything executes.
    """

    def __init__(
        self,
        llm_client: Any,
        tool_confidence_threshold: float = (
            DEFAULT_TOOL_CONFIDENCE_THRESHOLD
        ),
        completion_ambiguity_lower: float = (
            DEFAULT_COMPLETION_AMBIGUITY_LOWER
        ),
        completion_ambiguity_upper: float = (
            DEFAULT_COMPLETION_AMBIGUITY_UPPER
        )
    ):
        if not 0.0 <= tool_confidence_threshold <= 1.0:
            raise ValueError(
                "tool_confidence_threshold must be within [0.0, 1.0]."
            )

        if not (
            0.0
            <= completion_ambiguity_lower
            < completion_ambiguity_upper
            <= 1.0
        ):
            raise ValueError(
                "Completion ambiguity band must satisfy "
                "0.0 <= lower < upper <= 1.0."
            )

        self.llm = llm_client
        self.tool_confidence_threshold = tool_confidence_threshold
        self.completion_ambiguity_lower = completion_ambiguity_lower
        self.completion_ambiguity_upper = completion_ambiguity_upper

    @staticmethod
    def _normalise_probability(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(1.0, number))

    def _selected_tool_probability(
        self,
        decision: Any
    ) -> tuple[float, str]:
        """
        Return the probability of Jev's selected tool, falling back to
        the Choice confidence when the probability map is unavailable.
        """

        probabilities = getattr(decision, "tool_probabilities", None)

        if isinstance(probabilities, dict):
            raw = probabilities.get(decision.selected_tool)
            if raw is not None:
                return (
                    self._normalise_probability(raw),
                    "probability"
                )

        return (
            self._normalise_probability(
                getattr(decision, "tool_confidence", 0.0)
            ),
            "confidence"
        )

    def tool_selection_required(self, decision: Any) -> tuple[bool, str]:
        """True when Jev's tool choice is too uncertain to trust."""

        value, source = self._selected_tool_probability(decision)

        if value <= self.tool_confidence_threshold:
            return True, (
                f"Jev tool-selection {source} {value:.2f} is at or below "
                f"the escalation threshold "
                f"{self.tool_confidence_threshold:.2f}."
            )

        return False, ""

    def completion_required(self, completion_probability: float) -> tuple[bool, str]:
        """True when Jev's completion probability is ambiguous."""

        value = self._normalise_probability(completion_probability)

        if (
            self.completion_ambiguity_lower
            <= value
            < self.completion_ambiguity_upper
        ):
            return True, (
                f"Jev completion probability {value:.2f} falls inside the "
                f"ambiguous band "
                f"[{self.completion_ambiguity_lower:.2f}, "
                f"{self.completion_ambiguity_upper:.2f})."
            )

        return False, ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Escalation response was empty.")

        cleaned = content.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Escalation response did not contain valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                "Escalation response must be a JSON object."
            )

        return parsed

    def _generate(self, system_prompt: str, user_prompt: str):
        return self.llm.generate(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            response_format={"type": "json_object"}
        )

    def _usage(self, outcome: EscalationOutcome, response) -> None:
        if response is None:
            return

        outcome.input_tokens = getattr(response, "input_tokens", 0)
        outcome.output_tokens = getattr(response, "output_tokens", 0)
        outcome.total_tokens = getattr(response, "total_tokens", 0)
        outcome.latency_seconds = getattr(
            response, "latency_seconds", 0.0
        )

    def escalate_tool_selection(
        self,
        task: str,
        plan: str,
        task_specification: dict,
        decision: Any,
        available_tools: dict[str, str],
        tool_history: list[dict]
    ) -> EscalationOutcome:
        """
        Ask Groq to review an uncertain tool selection.

        The returned final_decision is always an authorised tool: Groq's
        recommendation when it validates, otherwise Jev's original
        (already authorised) selection.
        """

        value, _ = self._selected_tool_probability(decision)

        outcome = EscalationOutcome(
            decision_type="tool_selection",
            reason=(
                f"Jev tool-selection probability {value:.2f} is below "
                f"the escalation threshold "
                f"{self.tool_confidence_threshold:.2f}."
            )
        )

        prompt = build_escalation_tool_prompt(
            task=task,
            plan=plan,
            task_specification=task_specification,
            proposed_tool=decision.selected_tool,
            tool_probability=value,
            tool_confidence=self._normalise_probability(
                getattr(decision, "tool_confidence", 0.0)
            ),
            available_tools=available_tools,
            tool_history=tool_history
        )

        try:
            response = self._generate(
                (
                    "You review uncertain tool selections for a "
                    "customer-support agent. Return structured JSON."
                ),
                prompt
            )
            self._usage(outcome, response)

            parsed = self._parse_json(response.content)
            recommendation = parsed.get("selected_tool")

            outcome.recommendation = parsed

            if (
                isinstance(recommendation, str)
                and recommendation
                and recommendation in available_tools
            ):
                outcome.succeeded = True
                outcome.final_decision = recommendation
            else:
                outcome.error = (
                    "Groq recommended an unavailable or invalid tool: "
                    f"{recommendation!r}. Falling back to Jev's "
                    "authorised selection."
                )

        except Exception as exc:
            outcome.error = (
                f"Tool-selection escalation failed: {exc}. Falling "
                "back to Jev's authorised selection."
            )

        if not outcome.succeeded:
            # Safe fallback: Jev's selection was already validated
            # against the allowed-tools list by the controller.
            outcome.final_decision = decision.selected_tool

            if outcome.error:
                outcome.reason = (
                    outcome.reason + " " + outcome.error
                )

        return outcome

    def escalate_completion(
        self,
        task: str,
        task_specification: dict,
        completion_probability: float,
        tool_history: list[dict]
    ) -> EscalationOutcome:
        """
        Ask Groq to judge an ambiguously complete task.

        A successful outcome carries Groq's boolean judgement in
        final_decision. The controller still applies the evidence gate
        before accepting completion.
        """

        value = self._normalise_probability(completion_probability)

        outcome = EscalationOutcome(
            decision_type="task_completion",
            reason=(
                f"Jev completion probability {value:.2f} falls inside "
                f"the ambiguous band "
                f"[{self.completion_ambiguity_lower:.2f}, "
                f"{self.completion_ambiguity_upper:.2f})."
            )
        )

        prompt = build_escalation_completion_prompt(
            task=task,
            task_specification=task_specification,
            completion_probability=value,
            tool_history=tool_history
        )

        try:
            response = self._generate(
                (
                    "You review uncertain task-completion judgements "
                    "for a customer-support agent. Return structured "
                    "JSON."
                ),
                prompt
            )
            self._usage(outcome, response)

            parsed = self._parse_json(response.content)
            judgement = parsed.get("task_complete")

            outcome.recommendation = parsed

            if isinstance(judgement, bool):
                outcome.succeeded = True
                outcome.final_decision = judgement
            else:
                outcome.error = (
                    "Groq did not return a boolean task_complete "
                    "judgement."
                )

        except Exception as exc:
            outcome.error = f"Completion escalation failed: {exc}."

        if not outcome.succeeded and outcome.error:
            outcome.reason = outcome.reason + " " + outcome.error

        return outcome
