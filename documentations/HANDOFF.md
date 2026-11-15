# Handoff

## Current development state

- **Phases 1–6 complete and verified** (see `PHASE_PROGRESS.md`).
- **Phase 7 complete and unit-tested (recovered 2026-11-16):** the evaluation/benchmarking framework is implemented and passing — independent task verification, provider-distinguishable metrics, append-only experiment logging, a 10-task dataset, and a benchmark runner comparing Modes A/B/C offline. 67/67 Phase 7 tests pass; full suite **144/144**.
- **Phase 8 not started** (`app.py` is 0 bytes).
- Working tree is uncommitted: Phase 7 files (`evaluation/*.py`, `scripts/run_benchmark.py`, `data/tasks.json`, `tests/test_phase7.py`) plus `experiments/benchmark_results.{csv,jsonl}` (mocked demo rows; mixed with earlier stale smoke rows from the previous session's older fake constants — see `KNOWN_ISSUES.md`), `README.md`, and `documentations/*.md` modified.

## Verified test results (2026-11-16)

```
144 tests: 144 passed, 0 failed
  tests/test_agents.py        7/7   PASSED
  tests/test_hybrid_agent.py 32/32 PASSED
  tests/test_tools.py        13/13 PASSED
  tests/test_escalation.py   25/25 PASSED
  tests/test_phase7.py       67/67 PASSED  ← Phase 7 (new)
```

All tests are **mocked**; no test touches a live API. The benchmark runner defaults to mocked execution; `--live` requires `--max-live-runs >= 1` and `--yes` and aborts otherwise.

## Current working components

- `GroqLLMClient` (models/llm_client.py) — live-tested, 107/296/403 tokens, 2.45 s.
- `JevClient` (models/jev_client.py) — live-tested, model `jev-1.14.0`, 535/92/627 tokens, 1.68 s.
- `ToolRegistry` + 3 tools — 13/13 tests.
- `BaselineAgent` (Mode A) — 7/7 tests.
- `ControlLoop` + `HybridAgent` — authorization-enforced, evidence-gated completion; Mode B/C; live Mode B run succeeded 2026-11-15.
- `EscalationAgent` (agents/escalation_agent.py) — Mode C advisory escalation; 25/25 tests pass.
- **Phase 7:** `evaluation/task_verifier.py` (independent verification; verified/failed/unverifiable), `evaluation/metrics.py` (provider-distinguishable token/latency/escalation aggregation), `evaluation/logger.py` (append-only CSV+JSONL), `data/tasks.json` (10 tasks, 4 categories), `scripts/run_benchmark.py` (BenchmarkRunner + CLI + threshold analysis).

## Immediate next development priorities

1. **Implement Phase 8** (Streamlit dashboard + final validation) — `app.py` is 0 bytes; `streamlit`/`pandas`/`numpy` are in requirements but unused. The dashboard should read `experiments/benchmark_results.csv`/`.jsonl`.
2. **Optionally run one controlled live benchmark** (small `--mode A --max-live-runs 1` budget) to record a genuine `execution_type: "live"` row; do not spend repeated calls.
3. **Calibration data gap:** the mocked dataset never exercises escalation (all Jev confidences are 0.95); the threshold analysis reports this explicitly. Real calibration requires live data near the provisional thresholds (0.60 tool confidence; 0.50–0.70 completion band).

## Exact files to inspect before continuing

- `evaluation/task_verifier.py` — `TaskVerifier.verify`, `_has_valid_evidence` (local copy, deliberately independent of `ControlLoop`), `load_tasks`/`validate_tasks`.
- `evaluation/metrics.py` — `extract_run_metrics`, `summarize_runs`, `MetricSummary`.
- `evaluation/logger.py` — `ExperimentLogger.log`, `CSV_FIELDS`.
- `scripts/run_benchmark.py` — `BenchmarkRunner`, `FakeLLMClient`/`FakeJevClient`, `_confirm_live` (safety gate), `print_summary`, `print_threshold_analysis`, `--output` handling.
- `data/tasks.json` — 10 tasks; each has `expected_tools` + `verification` block.
- `tests/test_phase7.py` — 67 tests; note `BASE_TASK` is a shared module-level fixture (deep-copy before mutating nested fields).
- `documentations/risks.md` — confidence vs. probability distinction; calibration guidance.

## Recommended next implementation task

**Phase 8 MVP (Streamlit dashboard + final validation):** build `app.py` over the recorded benchmark data — mode comparison (success rate, tokens, latency, escalations), per-task verification detail, and the live-vs-mocked distinction. Then final validation: full suite, one small live smoke, and a README status refresh. Do not fabricate experiment rows.

## Important constraints

- Phases 1–7 are complete; do not reopen settled design (five-field contract, authorization, evidence gate, escalation advisory role, independent verification) without a concrete failing case.
- `experiments/results.csv` + `experiment_logs.jsonl` hold the first real Mode B run; `experiments/benchmark_results.*` hold Phase 7 mocked demo rows — append, never fabricate benchmark results.
- Jev access and pricing are documented in `documentations/risks.md` (input $0.042/M tokens, output free, no per-request fee, no free trial credits).
- Phase 6 thresholds (0.60 tool confidence; 0.50–0.70 completion band) are provisional and require calibration before any research claim.

## Phase 7 recovery notes (2026-11-16)

Recovered from a partially complete Phase 7. Root causes fixed:
1. `tests/test_phase7.py` mutated the shared `BASE_TASK` fixture through a shallow copy (`dict(BASE_TASK)` shares nested `verification`), poisoning `write_tasks()` → 11 errors + 1 failure. Fixed with `copy.deepcopy` in `test_required_outside_expected_is_rejected`.
2. `test_unregistered_expected_tool_is_rejected` expected the word "unregistered"/"invalid" in the validator message; `evaluation/task_verifier.py` message now includes "unregistered tool name was found".
3. `test_summarize_partial_metrics_not_invented` expected `combined_tokens is None` when only one provider has metrics; the documented design (combined falls back to the available provider total) is correct — test now asserts the real value.
4. `test_failed_run_is_recorded_not_raised`: a crashed agent run was classified `failed` because the runner's error record lacked an `error` marker; `run_task` now sets `execution["error"]` so the verifier returns `unverifiable`.
5. `test_mocked_path_uses_fake_clients` asserted a stale fake-token constant (150); the current `FakeLLMClient` emits 15/call → 30 for a two-call Mode A run.
6. `--output` CLI flag was dead code; it now routes CSV/JSONL to the chosen directory (default remains `experiments/`).
