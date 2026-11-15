# Known Issues

Ordered by severity. All line numbers refer to the working tree as of 2026-11-16 (Phase 7 complete, 144/144 tests pass).

## 🟢 1. Hybrid test suite is green (32/32) — contract fixed, live-validated

- **Resolved:** The five-field `task_specification` contract is now consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`. Mocks emit valid specs; 32/32 hybrid tests pass (52/52 total).
- **Live-validated 2026-11-15:** the real planner produced a valid five-field spec in the recorded Mode B run (`experiments/experiment_logs.jsonl`), with `allowed_tools=["check_service_status"]` and `required_tools=["check_service_status"]`.

## 🟢 2. `allowed_tools` restriction was silently discarded — fixed, live-validated

- **Resolved:** the full-registry overwrite (former `control_loop.py` line 251) is removed. `available_tools` is the registry filtered through `allowed_tools` for the whole run; Jev only sees allowed tools, `selected_tool ∉ available_tools` → `unauthorized_jev_tool_selection`, an unregistered name inside `allowed_tools` → `unauthorized_tool_configuration`, and execution runs only through `registry.execute` on the selected tool. The `create_support_ticket` explicit-user-authorization guard in `hybrid_agent.py` is unchanged and covered by tests.
- **Live-validated 2026-11-15:** the real run executed only the authorised `check_service_status`; no unauthorised tool was selected or executed.

## 🟢 3. Required-tools / evidence gate is now wired (was dead code)

- **Resolved:** `_required_tools_fulfilled` calls `_get_fulfilled_required_tools` before accepting `jev_detected_completion`; `state["fulfilled_required_tools"]` is recomputed every iteration; Jev completion without full evidence stops with `required_tools_not_fulfilled` (success stays `False`). Failed executions and malformed evidence never count.
- **Remaining:** `consecutive_no_progress` is still initialised but never used (pre-existing, harmless).

## 🟢 4. Phase 7 benchmark framework implemented and tested — resolved 2026-11-16

- `evaluation/task_verifier.py`, `evaluation/metrics.py`, `evaluation/logger.py`, `data/tasks.json` (10 tasks), and `scripts/run_benchmark.py` are implemented; 67/67 Phase 7 tests pass; full suite 144/144.
- The research questions (token/latency/success comparison A vs B vs C) are now answerable offline via the mocked benchmark; see `PHASE_PROGRESS.md`.
- Historical "20/20" and "35/35" claims remain non-reproducible (pre-Phase-1 history); not re-litigated here.

## 🟠 5. Phase 7 done; Phase 8 module still an empty placeholder

- `agents/escalation_agent.py` is implemented (Mode C escalation, 25/25 tests pass).
- `app.py` (0 bytes) — no Streamlit dashboard.
- `evaluation/*.py` and `scripts/run_benchmark.py` are now implemented (Phase 7).
- `tests/test_jev_client.py` (0 bytes) — no Jev client unit tests.

## 🟡 6. Loop-detection heuristic is strict and partially live-observed

- **Where:** `agents/control_loop.py` loop-guard block (~lines 385–405).
- **What:** Termination requires `loop_probability >= 0.70` AND `len(tool_calls) >= 2` AND `progress_score/5.0 <= 0.20`. This fixes the historical "premature loop termination" complaint but is based on an assumed 0–5 progress scale.
- **Live observation (2026-11-15):** Jev returned progress 0.02 → 3.39 and loop probability 0.04 → 0.82 on a healthy run; the guard correctly did not fire because the progress condition failed. One healthy-run data point is not threshold validation.
- **Impact:** If Jev's Score returns a different scale, `has_negligible_progress` misbehaves silently.

## 🟡 7. No unit coverage for the two API clients

- `GroqLLMClient` and `JevClient` are exercised only by live scripts (`scripts/test_groq.py`, `scripts/test_jev_client.py`, `scripts/smoke_test_jev.py`) that hit real APIs, require keys, and cost money.
- `tests/test_jev_client.py` is empty.
- **Fix:** add mocked unit tests for response parsing, error mapping, and token/latency capture.

## 🟡 8. Live smoke scripts don't match registry tool names

- `scripts/smoke_test_jev.py` and `scripts/test_jev_client.py` use `knowledge_search` / `service_status` / `create_ticket`.
- The registry exposes `search_knowledge_base` / `check_service_status` / `create_support_ticket`.
- **Impact:** the smoke tests validate the raw Jev SDK, not the registry's choice set. `smoke_test_jev.py` also hard-codes model `jev-1.14.0` while `settings.py` defaults to `jev-latest`.

## 🟡 9. No timeout on Jev requests

- `JevClient.evaluate_state()` opens `TypeSafeClient(model=...)` with no timeout (unlike Groq's `groq_timeout`). A hung Jev call would block the loop indefinitely.

## 🟢 10. Minor code-quality items

- `except (ToolExecutionError, Exception)` in `control_loop.py` (~line 505) is redundant (`Exception` subsumes it).
- The `for … else: maximum_iterations_reached` clause in `ControlLoop.run` is effectively unreachable — the inner `if len(result.tool_calls) >= self.max_iterations: break` always fires first.
- `_parse_json` is duplicated between `control_loop.py` and `hybrid_agent.py` (near-identical); `_parse_action` in `baseline_agent.py` is a third variant.
- `ControlLoop.run` evaluates Jev `max_iterations + 1` times (extra post-final-call evaluation is intentional and tested, but undocumented in the code comment).
- `scripts/run_baseline.py` has the same pre-existing `ModuleNotFoundError: No module named 'agents'` defect that was fixed in `scripts/run_hybrid.py` (cwd not on `sys.path`); left untouched per the no-unrelated-refactor constraint of the Phase 5 live-validation task.
- README status checklist is stale (all post-Phase-1 items unchecked despite phases 1–5 being complete).

## 🟡 12. `experiments/benchmark_results.*` mixes two code versions

- **Where:** `experiments/benchmark_results.csv` / `.jsonl` (untracked).
- **What:** the first 30 rows were written by the previous session's older `FakeLLMClient` constants (10/5/15 → 30 LLM tokens for Mode A) and 0.2 s latencies; rows written after the Phase 7 recovery use the current constants (20/10/30) and 0.3 s latencies. Both are mocked data, so no live cost is involved, but mixing them in one file would skew any token/latency analysis.
- **Impact:** minor — only affects the shared default output files, not `experiments/demo_mocked/` (clean single-version run) or the Phase 5/6 files.
- **Fix:** use `--output experiments/<name>` per run (now functional — the flag was dead code before the recovery), or clear the stale rows before the next benchmark run. Do not hand-edit history.

## 🟡 13. Mode C escalation thresholds are provisional, not calibrated

- **Where:** `config/settings.py` (`tool_confidence_threshold` 0.60, `completion_ambiguity_lower` 0.50, `completion_ambiguity_upper` 0.70); consumed by `agents/escalation_agent.py`.
- **What:** The defaults follow the Phase 6 specification's provisional values, not empirical measurement. Only one live Jev data point exists (confidence 1.0; completion 0.03 → 0.75), so the band may escalate too often or too rarely in practice.
- **Impact:** Escalation frequency — and therefore token cost — cannot be judged until the thresholds are calibrated against recorded runs.
- **Fix:** Phase 7 benchmarking should measure escalation rate, success, and cost across thresholds before these are treated as tuned values.

## 🟡 13. Mode C escalation path has not yet fired against the live APIs

- **Where:** `scripts/smoke_test_mode_c.py` (one controlled live run, 2026-11-16).
- **What:** The live Mode C run succeeded end-to-end (`success=true`, `jev_detected_completion`, 2 Jev calls, 1916 Groq tokens, 4.04 s), but Jev was fully confident both times (tool confidence 1.0; completion 0.89), so the escalation branches were not exercised against real API responses.
- **Impact:** Live Jev confidence/probability distributions may not cross the provisional thresholds, so a live run might never trigger escalation; the escalation code paths remain mocked-test-verified only.
- **Fix:** when a benchmark task naturally produces a low-confidence or ambiguous Jev response (Phase 7), confirm the escalation path end-to-end; do not spend repeated live calls forcing it.

## 🔒 11. Secret hygiene

- A real `.env` exists on disk (gitignored) and `.claude/settings.json` holds a plaintext OpenRouter token (`.claude/` is gitignored). Neither is committed, but avoid copying either into new files, logs, or this documentation.