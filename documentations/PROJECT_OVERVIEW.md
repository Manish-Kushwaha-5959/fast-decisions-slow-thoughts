# Project Overview

**Project:** Fast Decisions, Slow Thoughts — A Hybrid LLM + System One (Jev) Architecture for Cost-Efficient AI Agents
**Repository:** `hybrid_agent_mvp` (Python 3.11+, Windows 11)

## 1. Research Problem

Conventional agent architectures delegate **all** control decisions — planning, tool selection, argument generation, completion detection, loop detection — to a single Large Language Model. This is expensive in tokens and latency, and the LLM's control decisions are not always reliable.

This project investigates whether splitting control responsibilities between two components can produce cheaper, more reliable agents:

- **System Two — Groq LLM** (`openai/gpt-oss-120b`): reasoning, natural-language generation, tool argument generation.
- **System One — Jev** (TypeSafe API, `jev-1.14.0`): tool selection, confidence estimation, task progress, completion probability, loop detection.

## 2. Proposed Architecture

Three experimental modes share one tool registry and one tool set:

| Mode | Name | Who decides what |
|---|---|---|
| **A** | LLM-only | Groq controls planning, tool selection, argument generation, completion, loop detection. |
| **B** | LLM + Jev (hybrid) | Groq does planning, argument generation, final response. Jev does tool selection, completion detection, loop detection, progress estimation. |
| **C** | Hybrid with uncertainty-aware escalation | Jev handles control decisions; uncertain decisions are escalated to Groq. **Not yet implemented.** |

## 3. Research Questions

1. Does Jev-assisted tool selection reduce token consumption vs. LLM-only selection?
2. Does Jev-assisted completion/loop detection improve task success rate and reduce wasted tool calls?
3. Is Jev's reported confidence calibrated to empirical correctness? (Not yet measured.)
4. Does uncertainty-aware escalation (Mode C) improve success at an acceptable cost? (Not yet implemented.)

## 4. Measured Metrics (per run)

- `llm_input_tokens`, `llm_output_tokens`, `llm_total_tokens`, `llm_latency_seconds`
- `jev_input_tokens`, `jev_output_tokens`, `jev_total_tokens`, `jev_latency_seconds`
- `tool_latency_seconds`, `total_latency_seconds`
- `iterations`, `tool_calls[]`, `decision_history[]`
- `success` (bool), `termination_reason` (string)

## 5. Technologies and Dependencies

See `requirements.txt`:

- `typesafe-sdk` — Jev client SDK (`TypeSafeClient`, `Choice`, `Noul`, `Score`)
- `groq` — Groq Python SDK
- `python-dotenv` — `.env` loading
- `streamlit`, `pandas`, `numpy` — dashboard/benchmarking (declared, dashboard not implemented)
- `pytest` — test runner

**Environment variables** (see `.env.example`):
- `GROQ_API_KEY`, `GROQ_MODEL` (default `openai/gpt-oss-120b`), `GROQ_TEMPERATURE` (0.2), `GROQ_MAX_COMPLETION_TOKENS` (1024), `GROQ_TIMEOUT` (60)
- `TYPESAFE_API_KEY`, `JEV_MODEL` (default `jev-latest`, resolves to `jev-1.14.0`)

## 6. Key Facts

- All tools are **simulated/local** — no real infrastructure is contacted.
- The knowledge base is a static JSON file (`data/knowledge_base.json`) with lexical token-overlap retrieval, not semantic search.
- Service statuses are a fixed dictionary (`tools/service_status.py`).
- Support tickets are in-memory only; ticket IDs are sequential and reset between runs.
- `experiments/results.csv` and `experiments/experiment_logs.jsonl` exist but are **empty (0 bytes)** — no benchmark experiment has been run yet.