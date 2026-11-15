
# Fast Decisions, Slow Thoughts

### A Hybrid LLM + System One Architecture for Cost-Efficient AI Agents

## Overview

This project investigates a hybrid AI agent architecture that
combines a Large Language Model (LLM) with a dedicated System One
decision model (Jev).

The objective is to investigate whether specialized decision-making
can reduce the computational cost and latency of agent control
decisions while maintaining reliable task execution.

## Experimental Modes

- **Mode A — LLM-only:** The LLM handles planning, tool selection,
  completion detection, and response generation.

- **Mode B — LLM + Jev:** The LLM handles planning and language
  generation, while Jev handles selected agent-control decisions.

- **Mode C — Hybrid with uncertainty-aware escalation:** Jev handles
  control decisions, with uncertain decisions escalated to the LLM.

## Technology Stack

- Python 3.11+
- Groq API
- GPT-OSS 120B (`openai/gpt-oss-120b`)
- TypeSafe Jev API
- Streamlit
- Pandas
- NumPy

## Project Structure

- `agents/` — Agent implementations and control logic
- `models/` — LLM and Jev API clients
- `tools/` — Simulated agent tools
- `evaluation/` — Logging, metrics and task verification
- `config/` — Project configuration
- `data/` — Knowledge base and evaluation tasks
- `experiments/` — Experiment logs and results
- `scripts/` — Test and experiment scripts
- `tests/` — Automated tests
- `documentations/` — Architecture and implementation documentation

## Current Development Status

- [x] Jev API connection and initial smoke test
- [x] Groq LLM client
- [x] Tool environment
- [x] LLM-only baseline agent
- [x] LLM + Jev hybrid agent
- [x] Uncertainty-aware escalation
- [x] Evaluation and benchmarking framework (Phase 7)
- [ ] Evaluation dashboard (Phase 8)

### Benchmark (mocked, offline)

```bash
python scripts/run_benchmark.py --mode all --repetitions 1 --output experiments/demo_mocked
```

Live runs are opt-in and require both `--live` and `--max-live-runs N`
plus `--yes` confirmation. See `documentations/HANDOFF.md`.

## Research Scope

The system is an experimental prototype. Its performance claims
will be evaluated using controlled tasks, measured token usage,
latency, task success, and decision quality.
