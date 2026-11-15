# Handoff

## Current development state

- **Phases 1–5 complete and verified** (live-API validated for phases 1–2; unit-tested for phases 3–4).
- **Phase 5 complete, unit-tested, and live-validated:** the five-field `task_specification` contract is consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`; the planner's `allowed_tools` restriction is enforced throughout execution; completion is evidence-gated on every required tool producing valid evidence; 32/32 hybrid tests pass. One live Mode B run succeeded end-to-end (2026-11-15, `success=true`, `jev_detected_completion`, 3729 combined tokens, 5.92 s; recorded in `experiments/results.csv` + `experiment_logs.jsonl`).
- **Phase 6 complete and unit-tested:** Mode C uncertainty-driven escalation is implemented in `agents/escalation_agent.py` and wired into `agents/control_loop.py` + `agents/hybrid_agent.py`; thresholds live in `config/settings.py`; 25/25 escalation tests pass; the three demonstration scenarios run deterministically via `scripts/demo_mode_c.py`. One controlled live Mode C smoke run succeeded end-to-end (2026-11-16, `success=true`, `jev_detected_completion`, 2 Jev calls, 1916 Groq tokens, 4.04 s); Jev was fully confident so the escalation branches did not fire live — they remain mocked-test-verified.
- **Phases 7–8 not started** (`evaluation/*.py`, `scripts/run_benchmark.py`, `data/tasks.json`, `app.py` are 0 bytes).
- Working tree is uncommitted: `agents/escalation_agent.py` (new), `agents/control_loop.py`, `agents/hybrid_agent.py`, `agents/prompts.py`, `config/settings.py`, `scripts/run_hybrid.py`, `scripts/demo_mode_c.py`, `tests/test_escalation.py`, `.env.example`, `documentations/*.md` modified; `experiments/results.csv` and `experiments/experiment_logs.jsonl` contain the first real (Mode B) run; `control_loop.py.bak`, `hybrid_agent.py.bak` are stray backups.

## Verified test results (2026-11-16)

```
77 tests: 77 passed, 0 failed
  tests/test_agents.py       7/7   PASSED
  tests/test_hybrid_agent.py 32/32 PASSED  ← five-field contract + authorization + evidence-gated completion (unchanged)
  tests/test_tools.py        13/13 PASSED
  tests/test_escalation.py   25/25 PASSED  ← Mode C escalation scenarios (new)
```

All tests are **mocked** (`FakeLLMClient`, `FakeJevClient`); no test touches a live API. Live validation is the single recorded Mode B run in `experiments/`.

## Current working components

- `GroqLLMClient` (models/llm_client.py) — live-tested, 107/296/403 tokens, 2.45 s.
- `JevClient` (models/jev_client.py) — live-tested, model `jev-1.14.0`, 535/92/627 tokens, 1.68 s.
- `ToolRegistry` + 3 tools — 13/13 tests.
- `BaselineAgent` (Mode A) — 7/7 tests.
- `ControlLoop` + `HybridAgent` — authorization-enforced, evidence-gated completion; Mode B/C; 57/57 hybrid+escalation tests pass; live Mode B run succeeded 2026-11-15.
- `EscalationAgent` (agents/escalation_agent.py) — Mode C advisory escalation; threshold checks + Groq review parsing + safe fallback; 25/25 tests pass.

## Immediate next development priorities

1. **One controlled live Mode C smoke test** (if credentials/budget allow) — confirm a real Jev response can cross the provisional thresholds and that escalation works end-to-end; record the run in `experiments/`. Avoid repeated expensive calls.
2. **Implement Phase 7** (task verification, metrics aggregation, cost model, benchmark) before relying on cross-mode comparisons or threshold calibration; `scripts/run_benchmark.py`, `data/tasks.json`, and `evaluation/*.py` are still empty.

## Exact files to inspect before continuing

- `agents/escalation_agent.py` — Mode C escalation logic, threshold checks, Groq review parsing, safe fallbacks.
- `agents/control_loop.py` — Mode B loop plus the two escalation branches (tool selection after authorisation; completion between evidence gate and loop guard) and the six decision-history escalation fields.
- `agents/hybrid_agent.py` — `EscalationAgent` construction from settings; `mode` attribute; `enable_escalation` flag.
- `config/settings.py` — `tool_confidence_threshold`, `completion_ambiguity_lower`, `completion_ambiguity_upper`.
- `scripts/demo_mode_c.py` — the three demonstration scenarios (mocked).
- `tests/test_escalation.py` — mock helpers and all Mode C scenarios.
- `scripts/run_hybrid.py` — Mode B/C CLI runner (`--no-escalation`); records the real mode per run.
- `documentations/risks.md` — confidence vs. probability distinction; calibration guidance for phases 6–8.

## Recommended next implementation task

**Phase 7 MVP (evaluation and benchmarking framework):** implement `evaluation/task_verifier.py`, `evaluation/metrics.py`, `evaluation/logger.py`, `scripts/run_benchmark.py`, and `data/tasks.json`; then calibrate the Phase 6 thresholds from recorded runs (the 2026-11-15 Mode B run had confidence 1.0 and a completion transition 0.03 → 0.75). Before that, optionally run the single controlled live Mode C smoke test described above.

## Important constraints

- Phases 1–6 are complete; do not reopen settled design (five-field contract, authorization, evidence gate, escalation advisory role) without a concrete failing case.
- `experiments/results.csv` and `experiments/experiment_logs.jsonl` contain the first real run — append, never fabricate benchmark results.
- Jev access and pricing are documented in `documentations/risks.md` (input $0.042/M tokens, output free, no per-request fee, no free trial credits).
- Phase 6 thresholds (0.60 tool confidence; 0.50–0.70 completion band) are provisional and require calibration before any research claim.