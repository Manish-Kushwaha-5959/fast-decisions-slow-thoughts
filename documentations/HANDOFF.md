# Handoff

## Current development state

- **Phases 1–4 complete and verified** (live-API validated for phases 1–2; unit-tested for phases 3–4).
- **Phase 5 complete, unit-tested, and live-validated:** the five-field `task_specification` contract is consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`; the planner's `allowed_tools` restriction is enforced throughout execution; completion is evidence-gated on every required tool producing valid evidence; **32/32 hybrid tests pass** (52/52 total). One live Mode B run succeeded end-to-end (2026-11-15, `success=true`, `jev_detected_completion`, 3729 combined tokens, 5.92 s; recorded in `experiments/results.csv` + `experiment_logs.jsonl`).
- **Phases 6–8 not started** (`escalation_agent.py`, `evaluation/*.py`, `scripts/run_benchmark.py`, `data/tasks.json`, `app.py` are 0 bytes).
- Working tree is uncommitted: `agents/control_loop.py`, `agents/hybrid_agent.py`, `agents/prompts.py`, `tests/test_hybrid_agent.py`, `scripts/run_hybrid.py`, `documentations/*.md` modified; `experiments/results.csv` and `experiments/experiment_logs.jsonl` now contain the first real run; `control_loop.py.bak`, `hybrid_agent.py.bak` are stray backups.

## Verified test results (2026-11-15)

```
52 tests: 52 passed, 0 failed
  tests/test_agents.py       7/7   PASSED
  tests/test_hybrid_agent.py 32/32 PASSED  ← five-field contract + authorization + evidence-gated completion
  tests/test_tools.py        13/13 PASSED
```

All tests are **mocked** (`FakeLLMClient`, `FakeJevClient`); no test touches a live API. Live validation is the single recorded Mode B run in `experiments/`.

## Current working components

- `GroqLLMClient` (models/llm_client.py) — live-tested, 107/296/403 tokens, 2.45 s.
- `JevClient` (models/jev_client.py) — live-tested, model `jev-1.14.0`, 535/92/627 tokens, 1.68 s.
- `ToolRegistry` + 3 tools — 13/13 tests.
- `BaselineAgent` (Mode A) — 7/7 tests.
- `ControlLoop` + `HybridAgent` — authorization-enforced, evidence-gated completion; 32/32 tests pass; live Mode B run succeeded 2026-11-15.

## Immediate next development priorities

1. **Implement Phase 6** (`agents/escalation_agent.py`) — Mode C uncertainty-aware escalation, reusing `JevDecisionResult` fields: escalate `Choice` when `tool_confidence`/selected-tool probability is below a configurable threshold, escalate `Noul(task_complete)` in the ambiguous band, and record every escalation in `HybridAgentRunResult.decision_history`.
2. **Implement Phase 7** (task verification, metrics, benchmark) before relying on cross-mode comparisons; `scripts/run_benchmark.py`, `data/tasks.json`, and `evaluation/*.py` are still empty.

## Exact files to inspect before continuing

- `agents/control_loop.py` — loop logic, allowed-tools enforcement, evidence-gated completion (`_required_tools_fulfilled`, `_has_valid_evidence`, `_get_fulfilled_required_tools`).
- `scripts/run_hybrid.py` — Mode B CLI runner; inserts project root on `sys.path` and appends each run to `experiments/`.
- `agents/hybrid_agent.py` — planning + task-spec validation (incl. `create_support_ticket` guard) + final response.
- `agents/prompts.py` — planning/argument/final prompt builders.
- `tests/test_hybrid_agent.py` — mock helpers (`FakeLLMClient`, `FakeJevClient`, `make_jev_decision`, `plan_response`, `arguments_response`, `final_response`) and the authorization / evidence-gate scenarios.
- `documentations/risks.md` — the original risk analysis (Jev access, confidence vs. probability, benchmark fairness, gold-decision methodology) that still shapes phases 6–8.
- `documentations/06_support_tools_and_registry.md` — Phase 3 design notes (tool fairness controls, reset semantics).

## Recommended next implementation task

**Implement Phase 6** (`agents/escalation_agent.py`, Mode C): escalate `Choice` decisions when `tool_confidence`/selected-tool probability is below a configurable threshold, escalate `Noul(task_complete)` when its probability is in the ambiguous band, and record every escalation in `HybridAgentRunResult.decision_history`. Reuse the live Jev observations from `experiments/experiment_logs.jsonl` to calibrate the thresholds (e.g. the 2026-11-15 run had confidence 1.0 and an ambiguous completion band transition 0.03 → 0.75). After that, Phase 7 (task verification, metrics aggregation, cost model, benchmark) — `scripts/run_benchmark.py`, `data/tasks.json`, and `evaluation/*.py` are still empty.

## Important constraints

- Phases 1–5 are complete; do not reopen settled design (five-field contract, authorization, evidence gate) without a concrete failing case.
- `experiments/results.csv` and `experiments/experiment_logs.jsonl` now contain the first real run — append, never fabricate benchmark results.
- Jev access and pricing are documented in `documentations/risks.md` (input $0.042/M tokens, output free, no per-request fee, no free trial credits).