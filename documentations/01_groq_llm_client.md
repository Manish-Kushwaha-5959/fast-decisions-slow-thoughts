
# Phase 1: Groq LLM Client Implementation

## 1. Objective

Implement a reusable LLM client using the Groq API and
Llama 3.3 70B Versatile.

The client provides a common interface for all three
experimental agent configurations.

## 2. Model Configuration

| Parameter | Configuration |
|---|---|
| Provider | Groq |
| Model | llama-3.3-70b-versatile |
| API interface | Chat Completions |
| Python SDK | groq |
| Authentication | GROQ_API_KEY |
| Default temperature | 0.2 |
| Default maximum completion tokens | 1024 |
| Request timeout | 60 seconds |

The model and generation parameters are configurable
through environment variables.

## 3. Architectural Decision

A dedicated GroqLLMClient class is used instead of
calling the Groq API directly from agent implementations.

This provides:

- Separation between model communication and agent logic.
- Consistent model configuration across experimental modes.
- Centralized API error handling.
- Standardized response metadata.
- Reusable methods for text and structured responses.

## 4. Client Interface

### generate()

Accepts a sequence of chat messages and optional
generation parameters.

Returns an LLMResponse object.

### generate_text()

A convenience method accepting a system prompt
and user prompt.

### LLMResponse

The response object contains:

| Field | Description |
|---|---|
| content | Generated text |
| model | Actual model identifier returned |
| input_tokens | Prompt token usage |
| output_tokens | Completion token usage |
| total_tokens | Total token usage |
| latency_seconds | API request latency |
| finish_reason | Completion termination reason |
| request_id | Provider request identifier |

## 5. Experimental Consistency

The same Groq model and default generation settings
will be used across Modes A, B and C.

This is intended to reduce model-related differences
when comparing the experimental architectures.

Any changes to model versions, prompts, or generation
parameters must be recorded in experiment metadata.

## 6. Error Handling

The client handles:

- API rate-limit errors.
- API connection errors.
- API status errors.
- Unexpected client errors.

Failures are surfaced through GroqClientError.

## 7. Environment Variables

The following configuration is stored in `.env`:

- GROQ_API_KEY
- GROQ_MODEL
- GROQ_TEMPERATURE
- GROQ_MAX_COMPLETION_TOKENS
- GROQ_TIMEOUT
- TYPESAFE_API_KEY

Credentials must never be committed to version control.

## 8. Cost and Performance Measurement

Every successful response records input tokens,
output tokens, total tokens and request latency.

The experiment logger will use these values to
calculate aggregate usage and cost metrics.

Actual monetary costs will be calculated using the
applicable provider pricing and account plan at
the time of each experiment.

## 9. Implementation Status

Implementation code has been prepared.

The Groq connection test must be executed successfully
before this phase is marked complete.

## 10. Next Phase

Implement the Jev client wrapper in `models/jev_client.py`.

The wrapper will provide a standardized interface for
Choice, Noul and Score decisions and expose their
probability distributions, confidence values and
usage metadata.
