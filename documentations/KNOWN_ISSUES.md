# Known Issues

Ordered by severity. All line numbers refer to the working tree as of 2026-11-15 (uncommitted Phase 5 state).

## 🟢 1. Hybrid test suite is green (21/21) — contract fixed

- **Resolved:** The five-field `task_specification` contract is now consistent across `prompts.py`, `hybrid_agent.py`, and `control_loop.py`. Mocks emit valid specs; 21/21 hybrid tests pass (41/41 total).
- **Remaining risk:** the contract is only enforced by unit tests with mocks; no live planner run has yet produced a real five-field spec.

## 🔴 2. `allowed_tools` restriction is silently discarded

- **Where:** `agents/control_loop.py` lines 219–227 compute a filtered `available_tools` from `task_specification["allowed_tools"]`, but line 251 overwrites it with `available_tools = self.registry.get_tool_descriptions()` (all tools) before the loop.
- **Impact:** Jev can select tools the planner did not authorise, and the `invalid_jev_tool_selection` guard validates against the full registry rather than the allowed subset. The planner's authorisation is effectively unenforced.
- **Related safety gap:** the explicit-user-authorization regex for `create_support_ticket` in `agents/hybrid_agent.py` only guards the planner's `allowed_tools` list. Because of this bug, a ticket could still be executed via a Jev selection without that check ever running.
- **Fix:** delete line 251 (or re-apply the filter), and decide whether `selected_tool not in allowed_tools` should terminate.

## 🟠 3. Required-tools / evidence logic is dead code

- **Where:** `agents/control_loop.py` — `_has_valid_evidence()` and `_get_fulfilled_required_tools()` are implemented; `state["fulfilled_required_tools"]` is initialized to `[]` but never updated; `consecutive_no_progress` is initialized but never used.
- **Impact:** The intended "Jev completion + all required tools produced valid evidence" completion rule is not enforced. `_get_fulfilled_required_tools` is never called.
- **Fix:** either call `_get_fulfilled_required_tools(required_tools, tool_history)` before accepting `jev_detected_completion`, or remove the dead helpers and the `required_tools` plumbing.

## 🟠 4. No benchmark or experiment data exists

- **Where:** `experiments/results.csv` (0 bytes), `experiments/experiment_logs.jsonl` (0 bytes), `data/tasks.json` (0 bytes), `scripts/run_benchmark.py` (0 bytes).
- **Impact:** The research questions (token/latency/success comparison A vs B) cannot be answered yet. Historical "20/20" and "35/35" claims are not reproducible.
- **Fix:** Phase 7 — implement task verification, metrics aggregation, cost model, and a task set.

## 🟠 5. Phase 6/8 modules are empty placeholders

- `agents/escalation_agent.py` (0 bytes) — no Mode C / escalation logic.
- `app.py` (0 bytes) — no Streamlit dashboard.
- `evaluation/logger.py`, `evaluation/metrics.py`, `evaluation/task_verifier.py` (0 bytes) — no logging/metrics/verification.
- `tests/test_jev_client.py` (0 bytes) — no Jev client unit tests.

## 🟡 6. Loop-detection heuristic is strict and unvalidated

- **Where:** `agents/control_loop.py` lines ~319–330.
- **What:** Termination requires `loop_probability >= 0.70` AND `len(tool_calls) >= 2` AND `progress_score/5.0 <= 0.20`. This fixes the historical "premature loop termination" complaint but is based on an assumed 0–5 progress scale.
- **Impact:** If Jev's Score returns a different scale, `has_negligible_progress` misbehaves silently. No live data validates the threshold.

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

- `except (ToolExecutionError, Exception)` in `control_loop.py` (~line 430) is redundant (`Exception` subsumes it).
- The `for … else: maximum_iterations_reached` clause in `ControlLoop.run` is effectively unreachable — the inner `if len(result.tool_calls) >= self.max_iterations: break` always fires first.
- `_parse_json` is duplicated between `control_loop.py` and `hybrid_agent.py` (near-identical); `_parse_action` in `baseline_agent.py` is a third variant.
- `ControlLoop.run` evaluates Jev `max_iterations + 1` times (extra post-final-call evaluation is intentional and tested, but undocumented in the code comment).
- README status checklist is stale (all post-Phase-1 items unchecked despite phases 1–4 being complete).

## 🔒 11. Secret hygiene

- A real `.env` exists on disk (gitignored) and `.claude/settings.json` holds a plaintext OpenRouter token (`.claude/` is gitignored). Neither is committed, but avoid copying either into new files, logs, or this documentation.