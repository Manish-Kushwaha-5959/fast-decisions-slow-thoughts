
# Groq Model Migration: Llama 3.3 70B to GPT-OSS 120B

## 1. Background

During Phase 1 testing, the Groq API returned HTTP 404
when requesting:

`llama-3.3-70b-versatile`

Investigation of the official Groq documentation
identified that this model was decommissioned for
free and developer-tier accounts on August 16, 2026.

## 2. Reason for Migration

The selected model was no longer available to the
project's intended API tier.

This was a model-availability issue rather than
a Python implementation or project-structure issue.

## 3. New Model Configuration

| Parameter | Previous | Updated |
|---|---|---|
| Provider | Groq | Groq |
| Model | Llama 3.3 70B Versatile | GPT-OSS 120B |
| Model ID | llama-3.3-70b-versatile | openai/gpt-oss-120b |
| API interface | Chat Completions | Chat Completions |

## 4. Migration Decision

The project adopts `openai/gpt-oss-120b` as the
replacement model.

Groq identifies this model as a recommended
replacement for the retired Llama 3.3 70B model.

The replacement supports chat completions, tool use,
structured outputs and reasoning capabilities.

## 5. Implementation Impact

The existing GroqLLMClient abstraction remains unchanged
in its overall design.

The model identifier is configured through:

`GROQ_MODEL`

No agent architecture changes are required.

The actual model returned by the API must be recorded
for each experiment.

## 6. Research Considerations

The migration changes the underlying LLM used by
the project.

Therefore:

- All experimental modes must use the same new model.
- Earlier test results using a different model must not
  be mixed with the main experimental results.
- Prompt behavior must be tested again.
- Model identifier and generation settings must be
  included in experiment metadata.

## 7. References

- Groq model deprecation documentation:
  https://console.groq.com/docs/deprecations

- Groq supported models:
  https://console.groq.com/docs/models

- GPT-OSS 120B model documentation:
  https://console.groq.com/docs/model/openai/gpt-oss-120b

## 8. Status

Migration decision finalized.

API verification with the replacement model is pending.
