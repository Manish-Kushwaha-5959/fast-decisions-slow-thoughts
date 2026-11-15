# Known Issues

Ordered by severity. All line numbers refer to the working tree as of 2026-11-16 (uncommitted Phase 5 state, post live validation).

## 🟢 1. Hybrid test suite is green (32/32) — contract fixed, live-validated

- **Resolved:** The five-field `task_specification` contract is now consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`. Mocks emit valid specs; 32/32 hybrid tests pass (52/52 total).
- **Live-validated 2026-11-15:** the real planner produced a valid five-field spec in the recorded Mode B run (`experiments/experiment_logs.jsonl`), with `allowed_tools=["check_service_status"]` and `required_tools=["check_service_status"]`.

## 🟢 2. `allowed_tools` restriction was silently discarded — fixed, live-validated

- **Resolved:** the full-registry overwrite (former `control_loop.py` line 251) is removed. `available_tools` is the registry filtered through `allowed_tools` for the whole run; Jev only sees allowed tools, `selected_tool ∉ available_tools` → `unauthorized_jev_tool_selection`, an unregistered name inside `allowed_tools` → `unauthorized_tool_configuration`, and execution runs only through `registry.execute` on the selected tool. The `create_support_ticket` explicit-user-authorization guard in `hybrid_agent.py` is unchanged and covered by tests.
- **Live-validated 2026-11-15:** the real run executed only the authorised `check_service_status`; no unauthorised tool was selected or executed.

## 🟢 3. Required-tools / evidence gate is now wired (was dead code)

- **Resolved:** `_required_tools_fulfilled` calls `_get_fulfilled_required_tools` before accepting `jev_detected_completion`; `state["fulfilled_required_tools"]` is recomputed every iteration; Jev completion without full evidence stops with `required_tools_not_fulfilled` (success stays `False`). Failed executions and malformed evidence never count.
- **Remaining:** `consecutive_no_progress` is still initialised but never used (pre-existing, harmless).

## 🟠 4. No benchmark or experiment data exists — first run recorded

- **Where:** `experiments/results.csv` and `experiments/experiment_logs.jsonl` now hold the single 2026-11-15 Mode B run (success, 3729 combined tokens, 5.92 s); `scripts/run_hybrid.py` appends each run to both files. `data/tasks.json` (0 bytes) and `scripts/run_benchmark.py` (0 bytes) remain empty.
- **Impact:** The research questions (token/latency/success comparison A vs B) still cannot be answered from one run. Historical "20/20" and "35/35" claims are not reproducible.
- **Fix:** Phase 7 — implement task verification, metrics aggregation, cost model, and a task set.

## 🟠 5. Phase 6/8 modules are empty placeholders

- `agents/escalation_agent.py` (0 bytes) — no Mode C / escalation logic.
- `app.py` (0 bytes) — no Streamlit dashboard.
- `evaluation/logger.py`, `evaluation/metrics.py`, `evaluation/task_verifier.py` (0 bytes) — no logging/metrics/verification.
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

## 🔒 11. Secret hygiene

- A real `.env` exists on disk (gitignored) and `.claude/settings.json` holds a plaintext OpenRouter token (`.claude/` is gitignored). Neither is committed, but avoid copying either into new files, logs, or this documentation.