# Handoff

## Current development state

- **Phases 1–8 complete and verified** (see `PHASE_PROGRESS.md`).
- **Phase 8 complete (2026-11-16):** `app.py` Streamlit dashboard implemented and validated — six sidebar sections (Overview, Agent Playground, Execution Monitor, Benchmark Analytics, Mode Comparison, Architecture). It reads the recorded benchmark data and reuses the real agent interfaces for execution. Full suite **144/144** still passing.
- Working tree is uncommitted: Phase 8 files (`app.py`, `README.md`, `documentations/*.md`) plus the Phase 7 files from the previous session.

## Verified test results (2026-11-16)

```
144 tests: 144 passed, 0 failed
  tests/test_agents.py        7/7   PASSED
  tests/test_hybrid_agent.py 32/32 PASSED
  tests/test_tools.py        13/13 PASSED
  tests/test_escalation.py   25/25 PASSED
  tests/test_phase7.py       67/67 PASSED
```

All tests are **mocked**; no test touches a live API. The dashboard itself is validated manually (Streamlit `AppTest` + server start), not by the pytest suite.

## Dashboard launch

```bash
streamlit run app.py
# opens http://localhost:8501
```

Dependencies already in `requirements.txt` (`streamlit`, `pandas`, `numpy`) plus `plotly` (installed manually; add to `requirements.txt` if you want it pinned).

## Current working components

- `GroqLLMClient` (models/llm_client.py) — live-tested, 107/296/403 tokens, 2.45 s.
- `JevClient` (models/jev_client.py) — live-tested, model `jev-1.14.0`, 535/92/627 tokens, 1.68 s.
- `ToolRegistry` + 3 tools — 13/13 tests.
- `BaselineAgent` (Mode A) — 7/7 tests.
- `ControlLoop` + `HybridAgent` — authorization-enforced, evidence-gated completion; Mode B/C; live Mode B run succeeded 2026-11-15.
- `EscalationAgent` (agents/escalation_agent.py) — Mode C advisory escalation; 25/25 tests pass.
- **Phase 7:** `evaluation/task_verifier.py`, `evaluation/metrics.py`, `evaluation/logger.py`, `data/tasks.json`, `scripts/run_benchmark.py`.
- **Phase 8:** `app.py` dashboard. Agent Playground defaults to mocked execution (reuses `FakeLLMClient`/`FakeJevClient` + scripted responses from `scripts/run_benchmark.py`); live API is opt-in via a radio button. Benchmark Analytics / Mode Comparison read `experiments/benchmark_results.{csv,jsonl}` (fallback `experiments/demo_mocked/`).

## Immediate next development priorities

1. **Optional: add pytest coverage for `app.py`** helpers (`load_benchmark_data`, `get_mode_*`, `_infer_expected_tools`, `_summarize_tool_result`) so the dashboard is regression-tested. Not done in Phase 8 to keep the change presentation-only.
2. **Optional: run one controlled live benchmark** (small `--mode A --max-live-runs 1` budget) to record a genuine `execution_type: "live"` row; the dashboard currently only shows mocked rows.
3. **Calibration data gap:** the mocked dataset never exercises escalation (all Jev confidences are 0.95); the threshold analysis reports this explicitly. Real calibration requires live data near the provisional thresholds (0.60 tool confidence; 0.50–0.70 completion band).

## Exact files to inspect before continuing

- `app.py` — dashboard entry point; `load_benchmark_data()`, `get_mode_success_rates()`, `get_latency_data()`, `get_token_data()`, `get_escalation_data()`, `_infer_expected_tools()`, `_run_mocked_agent()`, `_run_live_agent()`, `render_*()`, `main()`.
- `evaluation/task_verifier.py` — `TaskVerifier.verify`, `_has_valid_evidence` (local copy, deliberately independent of `ControlLoop`), `load_tasks`/`validate_tasks`.
- `evaluation/metrics.py` — `extract_run_metrics`, `summarize_runs`, `MetricSummary`.
- `evaluation/logger.py` — `ExperimentLogger.log`, `CSV_FIELDS`.
- `scripts/run_benchmark.py` — `BenchmarkRunner`, `FakeLLMClient`/`FakeJevClient`, `_confirm_live` (safety gate), `print_summary`, `print_threshold_analysis`, `--output` handling.
- `data/tasks.json` — 10 tasks; each has `expected_tools` + `verification` block.
- `tests/test_phase7.py` — 67 tests; note `BASE_TASK` is a shared module-level fixture (deep-copy before mutating nested fields).
- `documentations/risks.md` — confidence vs. probability distinction; calibration guidance.

## Recommended next implementation task

**Presentation polish or live-data collection.** The dashboard is functional and data-accurate. If more is wanted: (a) add dashboard unit tests, (b) record a small live benchmark row so the dashboard can show a real `execution_type: "live"` sample, or (c) add per-task verification detail to the Mode Comparison page. Do not fabricate experiment rows.

## Important constraints

- Phases 1–8 are complete; do not reopen settled design (five-field contract, authorization, evidence gate, escalation advisory role, independent verification) without a concrete failing case.
- `experiments/results.csv` + `experiment_logs.jsonl` hold the first real Mode B run; `experiments/benchmark_results.*` hold Phase 7 mocked demo rows — append, never fabricate benchmark results.
- Jev access and pricing are documented in `documentations/risks.md` (input $0.042/M tokens, output free, no per-request fee, no free trial credits).
- Phase 6 thresholds (0.60 tool confidence; 0.50–0.70 completion band) are provisional and require calibration before any research claim.
- The dashboard must keep mocked and live runs separate and must never display API keys or env values.

## Phase 8 implementation notes (2026-11-16)

Design decisions made while building `app.py`:

1. **Presentation-only layer.** `app.py` imports the real agents and the benchmark's fake clients; it does not duplicate agent/evaluation logic. Mocked playground runs call `_run_mocked_agent()`, which wraps `FakeLLMClient`/`FakeJevClient` + the scripted-response helpers from `scripts/run_benchmark.py`.
2. **Path resolution.** `PROJECT_ROOT = Path(__file__).resolve().parent` (app.py sits at the repo root). An earlier `parents[1]` resolved to the wrong directory and loaded 0 records — fixed.
3. **Data join.** CSV rows are joined to JSONL records by `run_id` so charts get both flat metrics and `verification`/`raw_execution` detail. Escalation counts come from CSV columns first, falling back to the JSONL verification block.
4. **No fabricated claims.** An earlier draft stated "25%+ token reduction vs Mode A" — the recorded mocked data shows the opposite (Mode A 33 combined tokens vs B/C 74), so the claim was removed. The dashboard reports only what the records contain.
5. **Safety.** No execution on page load; live mode is opt-in; `execution_type` is recorded per run; mocked and live are never compared as equivalent.
6. **Validation:** `streamlit run app.py` starts; all six sidebar pages render without exceptions (Streamlit `AppTest`); mocked playground execution succeeds for Modes A/B/C; full pytest suite unchanged at 144/144.

## Phase 7 recovery notes (2026-11-16)

Recovered from a partially complete Phase 7. Root causes fixed:
1. `tests/test_phase7.py` mutated the shared `BASE_TASK` fixture through a shallow copy (`dict(BASE_TASK)` shares nested `verification`), poisoning `write_tasks()` → 11 errors + 1 failure. Fixed with `copy.deepcopy` in `test_required_outside_expected_is_rejected`.
2. `test_unregistered_expected_tool_is_rejected` expected the word "unregistered"/"invalid" in the validator message; `evaluation/task_verifier.py` message now includes "unregistered tool name was found".
3. `test_summarize_partial_metrics_not_invented` expected `combined_tokens is None` when only one provider has metrics; the documented design (combined falls back to the available provider total) is correct — test now asserts the real value.
4. `test_failed_run_is_recorded_not_raised` asserted a crashed agent run was classified `failed` because the runner's error record lacked an `error` marker; `run_task` now sets `execution["error"]` so the verifier returns `unverifiable`.
5. `test_mocked_path_uses_fake_clients` asserted a stale fake-token constant (150); the current `FakeLLMClient` emits 15/call → 30 for a two-call Mode A run.
6. `--output` CLI flag was dead code; it now routes CSV/JSONL to the chosen directory (default remains `experiments/`).
