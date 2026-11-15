# Handoff

## Current development state

- **Phases 1–4 complete and verified** (live-API validated for phases 1–2; unit-tested for phases 3–4).
- **Phase 5 implemented and unit-tested:** the five-field `task_specification` contract is now consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`; **21/21 hybrid tests pass** (41/41 total). Two known bugs remain deliberately unfixed: the allowed-tools filter overwrite at `control_loop.py:251`, and the dead `_get_fulfilled_required_tools` evidence gate.
- **Phases 6–8 not started** (`escalation_agent.py`, `evaluation/*.py`, `scripts/run_benchmark.py`, `data/tasks.json`, `experiments/*`, `app.py` are all 0 bytes).
- Working tree is uncommitted: `control_loop.py`, `hybrid_agent.py`, `prompts.py`, `test_hybrid_agent.py` modified; `control_loop.py.bak`, `hybrid_agent.py.bak` are stray backups.

## Verified test results (2026-11-15)

```
41 tests: 41 passed, 0 failed
  tests/test_agents.py       7/7   PASSED
  tests/test_hybrid_agent.py 21/21 PASSED  ← five-field contract + original scenarios
  tests/test_tools.py        13/13 PASSED
```

All tests are **mocked** (`FakeLLMClient`, `FakeJevClient`); no test touches a live API. The only live validations are the hand-run scripts in `documentations/03` and `documentations/05`.

## Current working components

- `GroqLLMClient` (models/llm_client.py) — live-tested, 107/296/403 tokens, 2.45 s.
- `JevClient` (models/jev_client.py) — live-tested, model `jev-1.14.0`, 535/92/627 tokens, 1.68 s.
- `ToolRegistry` + 3 tools — 13/13 tests.
- `BaselineAgent` (Mode A) — 7/7 tests.
- `ControlLoop` + `HybridAgent` — code present, but the test suite is red.

## Immediate next development priorities

1. **Fix `control_loop.py:251`** — the allowed-tools filter is overwritten by the full registry. This is a real authorisation bug, not just a test artifact.
2. **Wire or remove `_get_fulfilled_required_tools`** — currently dead code that was meant to gate completion on evidence.
3. **Run one live end-to-end Mode B task** (`python scripts/run_hybrid.py --task "..."`) and record the result in `experiments/`.
4. **Implement Phase 7** (task verification, metrics, benchmark) before Phase 6, since escalation needs a working evaluation baseline.

## Exact files to inspect before continuing

- `agents/control_loop.py` — loop logic, allowed-tools bug, dead evidence helpers.
- `agents/hybrid_agent.py` — planning + task-spec validation + final response.
- `agents/prompts.py` — planning/argument/final prompt builders.
- `tests/test_hybrid_agent.py` — mock helpers (`FakeLLMClient`, `FakeJevClient`, `make_jev_decision`, `plan_response`, `arguments_response`, `final_response`).
- `documentations/risks.md` — the original risk analysis (Jev access, confidence vs. probability, benchmark fairness, gold-decision methodology) that still shapes phases 6–8.
- `documentations/06_support_tools_and_registry.md` — Phase 3 design notes (tool fairness controls, reset semantics).

## Recommended next implementation task

**Update `tests/test_hybrid_agent.py` to emit valid `task_specification` payloads, then re-run the suite.** Once green, the next concrete work item is `agents/escalation_agent.py` (Phase 6), reusing `JevDecisionResult` fields: escalate `Choice` when `tool_confidence`/selected-tool probability is below a configurable threshold, escalate `Noul(task_complete)` when the probability is in the ambiguous band, and record every escalation in `HybridAgentRunResult.decision_history`.

## Important constraints

- Do not modify source code or tests in this session (documentation task only). The above are recommendations for the next session.
- `experiments/results.csv` and `experiments/experiment_logs.jsonl` are empty — do not fabricate benchmark results; run real experiments.
- Jev access and pricing are documented in `documentations/risks.md` (input $0.042/M tokens, output free, no per-request fee, no free trial credits).