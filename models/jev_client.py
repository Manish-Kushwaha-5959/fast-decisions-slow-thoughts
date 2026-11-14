import time
from dataclasses import dataclass
from typing import Dict, Optional, Any

from typesafe_sdk import (
    TypeSafeClient,
    Choice,
    Noul,
    Score
)

from config.settings import settings


@dataclass
class JevDecisionResult:
    # Tool selection
    selected_tool: str
    tool_probabilities: Dict[str, float]
    tool_confidence: float

    # Completion detection
    completion_probability: float

    # Loop detection
    loop_probability: float

    # Progress estimation
    progress_score: float

    # Metadata
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_seconds: float


class JevClientError(RuntimeError):
    """Raised when a Jev API request fails."""


class JevClient:

    def __init__(self):

        settings.validate_typesafe()

        self.model = settings.jev_model

    def evaluate_state(
        self,
        state: dict,
        available_tools: Dict[str, str]
    ) -> JevDecisionResult:

        if not available_tools:
            raise ValueError(
                "At least one available tool is required."
            )

        start_time = time.perf_counter()

        try:

            with TypeSafeClient(
                model=self.model
            ) as client:

                response = client.system_one(
                    state=state,
                    questions={

                        "next_tool": Choice(
                            instructions=(
                                "Which available tool should the "
                                "agent use next to make progress "
                                "towards completing the user request?"
                            ),
                            criteria=available_tools
                        ),

                        "task_complete": Noul(
                            instructions=(
                                "Has the user's request been "
                                "successfully completed based on "
                                "the information and tool results "
                                "in the current state?"
                            )
                        ),

                        "loop_detected": Noul(
                            instructions=(
                                "Has the agent entered a repeated "
                                "action pattern where equivalent "
                                "tool calls are being made without "
                                "meaningful progress or state change?"
                            )
                        ),

                        "progress": Score(
                            instructions=(
                                "How much progress has the agent "
                                "made towards completing the "
                                "user's request?"
                            ),
                            criteria=[
                                "No meaningful progress",
                                "Some information gathered",
                                "Useful action performed",
                                "Task nearly completed",
                                "Task successfully completed"
                            ]
                        )
                    }
                )

        except Exception as exc:
            raise JevClientError(
                f"Jev API request failed: {exc}"
            ) from exc

        latency = time.perf_counter() - start_time

        usage = response.usage

        input_tokens = getattr(
            usage, "input_tokens", 0
        )

        output_tokens = getattr(
            usage, "output_tokens", 0
        )

        return JevDecisionResult(

            selected_tool=(
                response.choices["next_tool"].choice
            ),

            tool_probabilities=(
                response.choices["next_tool"].probabilities
            ),

            tool_confidence=(
                response.choices["next_tool"].confidence
            ),

            completion_probability=(
                response.nouls["task_complete"].noul
            ),

            loop_probability=(
                response.nouls["loop_detected"].noul
            ),

            progress_score=(
                response.scores["progress"].score
            ),

            model=response.model,

            input_tokens=input_tokens,

            output_tokens=output_tokens,

            total_tokens=input_tokens + output_tokens,

            latency_seconds=round(latency, 4)
        )
