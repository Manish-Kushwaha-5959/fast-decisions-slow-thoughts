import time
from dataclasses import dataclass
from typing import Optional, Sequence

from groq import (
    Groq,
    APIConnectionError,
    APIStatusError,
    RateLimitError
)

from config.settings import settings


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_seconds: float
    finish_reason: Optional[str]
    request_id: Optional[str]


class GroqClientError(RuntimeError):
    """Raised when a Groq API request fails."""


class GroqLLMClient:

    def __init__(self):
        settings.validate_groq()

        self.model = settings.groq_model
        self.temperature = settings.groq_temperature
        self.max_completion_tokens = (
            settings.groq_max_completion_tokens
        )

        self.client = Groq(
            api_key=settings.groq_api_key,
            timeout=settings.groq_timeout
        )

    def generate(
        self,
        messages: Sequence[dict],
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
        response_format: Optional[dict] = None
    ) -> LLMResponse:

        request_params = {
            "model": self.model,
            "messages": list(messages),
            "temperature": (
                temperature
                if temperature is not None
                else self.temperature
            ),
            "max_completion_tokens": (
                max_completion_tokens
                if max_completion_tokens is not None
                else self.max_completion_tokens
            ),
        }

        if response_format is not None:
            request_params["response_format"] = response_format

        start_time = time.perf_counter()

        try:
            completion = self.client.chat.completions.create(
                **request_params
            )

        except RateLimitError as exc:
            raise GroqClientError(
                "Groq rate limit exceeded. Check your usage limits."
            ) from exc

        except APIConnectionError as exc:
            raise GroqClientError(
                "Could not connect to the Groq API."
            ) from exc

        except APIStatusError as exc:
            details = exc.response.text if exc.response else str(exc)

            raise GroqClientError(
                f"Groq API error: HTTP {exc.status_code}\n"
                f"Details: {details}"
            ) from exc

        except Exception as exc:
            raise GroqClientError(
                f"Unexpected Groq client error: {exc}"
            ) from exc

        latency = time.perf_counter() - start_time

        choice = completion.choices[0]
        usage = completion.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=completion.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            latency_seconds=round(latency, 4),
            finish_reason=choice.finish_reason,
            request_id=completion.id
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None
    ) -> LLMResponse:

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        return self.generate(
            messages=messages,
            temperature=temperature
        )

    def close(self):
        self.client.close()
