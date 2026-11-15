# Phase Progress

Eight-phase roadmap. Statuses below are **verified against the working tree and test suite on 2026-11-15**, not historical estimates.

Legend: ✅ Complete · ⚠️ Implemented but broken/unvalidated · ❌ Not started

| Phase | Description | Verified status |
|---|---|---|
| 1 | Groq LLM Client Integration | ✅ Complete (live-API validated) |
| 2 | Jev Integration | ✅ Complete (live-API validated; no unit tests) |
| 3 | Tool Development and Registry | ✅ Complete (13/13 tool tests pass) |
| 4 | LLM-Only Baseline Agent | ✅ Complete (7/7 baseline tests pass) |
| 5 | Hybrid LLM + Jev Agent Integration | ⚠️ Implemented, **13/14 hybrid tests fail** |
| 6 | Uncertainty Detection and Escalation | ❌ Not started (`agents/escalation_agent.py` is 0 bytes) |
| 7 | Evaluation and Benchmarking Framework | ❌ Not started (`evaluation/*.py`, `scripts/run_benchmark.py`, `data/tasks.json`, `experiments/*` all 0 bytes) |
| 8 | Streamlit Dashboard and Final Validation | ❌ Not started (`app.py` is 0 bytes) |

**Working tree state:** 4 files modified but uncommitted (`agents/control_loop.py`, `agents/hybrid_agent.py`, `agents/prompts.py`, `tests/test_hybrid_agent.py`), plus 2 stray `.bak` files. Commit `96dd81a` is "phase 5 almost complete"; the uncommitted diff is the actual Phase 5 work-in-progress.

---

## Phase 1 — Groq LLM Client Integration ✅

**Objective:** reusable Groq client for all three modes.

- Implemented: `models/llm_client.py` (`GroqLLMClient`, `LLMResponse`, `GroqClientError`), `config/settings.py`, `scripts/test_groq.py`.
- Model: migrated from `llama-3.3-70b-versatile` (HTTP 404, decommissioned 2026-08-16) to `openai/gpt-oss-120b` (see `documentations/02_groq_model_migration.md`).
- Validation: live-API test passed — 107 in / 296 out / 403 total tokens, 2.4508 s latency (`documentations/03_groq_client_validation.md`).
- Tests: none in pytest suite (no unit tests for `GroqLLMClient`; only live scripts).
- Remaining: none blocking.

## Phase 2 — Jev Integration ✅

**Objective:** reusable TypeSafe/Jev client.

- Implemented: `models/jev_client.py` (`JevClient.evaluate_state`, `JevDecisionResult`, `JevClientError`), `scripts/test_jev_client.py`, `scripts/smoke_test_jev.py`.
- One batched `system_one()` request with 4 questions: `Choice(next_tool)`, `Noul(task_complete)`, `Noul(loop_detected)`, `Score(progress)`.
- Validation: live-API test passed — selected tool `service_status`, probs {knowledge_search: 0.15, service_status: 0.85, create_ticket: 0.00}, confidence 0.77, completion 0.03, loop 0.03, progress 0.05; 535/92/627 tokens, 1.6806 s, model `jev-1.14.0` (`documentations/05_jev_client_validation.md`).
- Tests: `tests/test_jev_client.py` is **empty** — no unit coverage.
- Remaining: none blocking.

## Phase 3 — Tool Development and Registry ✅

**Objective:** deterministic simulated tools + shared registry for all modes.

- Implemented: `tools/registry.py` (`ToolRegistry`, `ToolDefinition`, `build_default_registry`), `tools/knowledge_base.py`, `tools/service_status.py`, `tools/ticket_manager.py`, `data/knowledge_base.json`.
- 3 tools: `search_knowledge_base` (lexical token-overlap, top 3), `check_service_status` (fixed dict + aliases), `create_support_ticket` (in-memory, sequential IDs).
- Validation: `tests/test_tools.py` **13/13 pass** (retrieval, aliases, unknown service, ticket validation, registry execution/argument validation/schema consistency/reset).
- Remaining: none.

## Phase 4 — LLM-Only Baseline Agent ✅

**Objective:** Mode A reference agent.

- Implemented: `agents/baseline_agent.py` (`BaselineAgent`, `AgentRunResult`), prompt builders `build_baseline_system_prompt` / `build_initial_user_message` in `agents/prompts.py`, `scripts/run_baseline.py`.
- Groq controls planning, tool selection, arguments, continuation, completion. Max 5 iterations; JSON-fence tolerant parser.
- Validation: `tests/test_agents.py` **7/7 pass** (final response, tool-then-final, tool error handling, iteration limit, invalid JSON, empty task, invalid limit). All mocked (`FakeLLMClient`) — no network.
- Remaining: none.

## Phase 5 — Hybrid LLM + Jev Agent Integration ⚠️ BROKEN

**Objective:** Groq plans + generates arguments + final response; Jev selects tools, detects completion/loops, estimates progress.

- Implemented (uncommitted, on top of `96dd81a`):
  - `agents/hybrid_agent.py`: `HybridAgent`, `HybridAgentRunResult` (now includes `decision_history`, `task_specification`), 3-phase `run()`, `_validate_task_specification()` (exact field set, type checks, `allowed_tools ⊆ registry`, duplicate check, **explicit-user-authorization regex for `create_support_ticket`**).
  - `agents/control_loop.py`: `ControlLoop`, `ControlLoopResult`; Jev-controlled loop with completion threshold 0.70, loop threshold 0.70 + ≥2 tool calls + progress ≤ 0.20, `max_identical_calls=2` signature guard, `decision_history` recording, `_has_valid_evidence`, `_get_fulfilled_required_tools`.
  - `agents/prompts.py`: `build_hybrid_planning_prompt(task, available_tools)` now returns `plan` + `task_specification`; `build_hybrid_argument_prompt`; `build_hybrid_final_prompt`.
- **Verified result: 13 of 14 hybrid tests FAIL** (`tests/test_hybrid_agent.py`). Root cause: mocks still return the old plan-only JSON (`{"plan": ...}`), while the code now requires a full `task_specification` → every run dies at `planning_error` before Jev is called. See KNOWN_ISSUES.md #1.
- Also unvalidated in live runs: no `scripts/run_hybrid.py` execution result is recorded anywhere; `experiments/` is empty.
- Remaining before this phase can be called complete:
  1. Update test mocks to emit valid `task_specification` payloads.
  2. Fix `control_loop.py:251` (allowed-tools filter overwritten by full registry).
  3. Wire `_get_fulfilled_required_tools` into the completion decision or remove it.
  4. At least one live end-to-end Mode B run with recorded metrics.

## Phase 6 — Uncertainty Detection and Escalation ❌

- `agents/escalation_agent.py` exists but is **0 bytes**.
- Design intent (from `documentations/risks.md` / `timeline.md`): escalate Choice decisions when selected-tool probability < 0.60; escalate Noul completion when probability in [0.30, 0.70]; thresholds configurable.
- No code, no tests. Not started.

## Phase 7 — Evaluation and Benchmarking Framework ❌

- `evaluation/logger.py`, `evaluation/metrics.py`, `evaluation/task_verifier.py` all **0 bytes**.
- `scripts/run_benchmark.py` **0 bytes**; `data/tasks.json` **0 bytes**; `experiments/results.csv` and `experiments/experiment_logs.jsonl` **0 bytes**.
- No task verification, no metrics aggregation, no cost model, no benchmark runs. Not started.

## Phase 8 — Streamlit Dashboard and Final Validation ❌

- `app.py` is **0 bytes**. `streamlit`/`pandas`/`numpy` are in `requirements.txt` but unused.
- No dashboard, no cross-mode comparison UI. Not started.

---

## Discrepancies vs. historical claims

- README status checklist is stale (says "Tool environment / baseline / hybrid / escalation / dashboard" all unchecked) — contradicts phases 1–4 being complete.
- Historical "20/20" and "35/35 passing" claims are **both outdated**. Current suite has **35 tests: 22 pass, 13 fail**.
- `documentations/01–06` are phase-level design/validation notes; they describe intended behavior, some of which (e.g. `required_tools`, evidence-based completion) is only partially implemented.