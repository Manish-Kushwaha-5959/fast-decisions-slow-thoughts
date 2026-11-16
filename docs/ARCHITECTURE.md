# Architecture

This document describes the system as implemented in the working tree.
Line-free module descriptions take precedence over historical notes; the
source code is the source of truth.

## 1. Overview

The project implements three experimental agent configurations that share
one tool registry and one benchmark dataset:

| Mode | Name | Who decides what |
|---|---|---|
| **A** | LLM-only | Groq LLM controls planning, tool selection, argument generation, completion detection and continuation. |
| **B** | LLM + Jev | Groq plans, generates tool arguments and writes the final response. Jev (TypeSafe System One model) selects the tool, detects completion and loops, and estimates progress. |
| **C** | Hybrid with uncertainty-aware escalation | Mode B plus: when Jev's tool-selection confidence or completion probability is uncertain, Groq reviews the decision **in an advisory role**. The controller keeps final authority and every safeguard still applies. |

Jev is a fast, specialised decision model; Groq is the slower, more
expensive reasoning model. The research question is whether moving
*control* decisions to Jev reduces cost and latency while keeping task
execution reliable.

## 2. Component responsibilities

| Module | Responsibility |
|---|---|
| `config/settings.py` | Loads `.env` into a frozen `Settings` dataclass; exposes API-key validators and the Mode C escalation thresholds. |
| `models/llm_client.py` | `GroqLLMClient` — Groq chat completions with token/latency capture and typed errors (`GroqClientError`). |
| `models/jev_client.py` | `JevClient` — one `system_one()` request per evaluation returning `JevDecisionResult` (Choice/Noul/Score primitives); `JevClientError` wraps SDK failures. |
| `tools/registry.py` | `ToolRegistry` — tool definitions, LLM schema export, argument validation, execution, state reset; `build_default_registry()`. |
| `tools/knowledge_base.py` | `search_knowledge_base(query)` — lexical token-overlap retrieval over `data/knowledge_base.json`. |
| `tools/service_status.py` | `check_service_status(service)` — fixed simulated status lookup. |
| `tools/ticket_manager.py` | `create_support_ticket(issue, priority)` — in-memory ticket creation (sequential IDs, reset between runs). |
| `agents/prompts.py` | All prompt builders: baseline, hybrid planning, hybrid argument, hybrid final, escalation review (tool + completion). |
| `agents/baseline_agent.py` | Mode A. `BaselineAgent.run()`; Groq controls everything. |
| `agents/control_loop.py` | Mode B/C execution loop. Jev controls selection/completion/loop/progress; Mode C escalates uncertain decisions to Groq. |
| `agents/escalation_agent.py` | Mode C. Threshold checks (`tool_selection_required`, `completion_required`) and advisory Groq reviews (`escalate_tool_selection`, `escalate_completion`). |
| `agents/hybrid_agent.py` | Mode B/C orchestrator: planning → control loop → final response; builds the `EscalationAgent` when escalation is enabled. |
| `evaluation/logger.py` | Append-only CSV + JSONL experiment logger; every record carries `execution_type` (`mocked`/`live`). |
| `evaluation/metrics.py` | Provider-distinguishable metric extraction (`extract_run_metrics`) and per-mode aggregation (`summarize_runs`). Missing values stay `None`, never invented. |
| `evaluation/task_verifier.py` | Independent outcome verification (`TaskVerifier.verify`); never trusts the agent's self-reported `success`. Also `load_tasks`/`validate_tasks`. |
| `app.py` | Streamlit research dashboard (presentation layer only). |

## 3. Agent execution flow

### 3.1 Mode A — `BaselineAgent.run(task)`

```
registry.reset_state()
build system prompt (tool schemas + max_iterations) + initial user message
for iteration in range(max_iterations):
    llm.generate(messages)                          # one Groq call per step
    parse action JSON:
        "final"     -> set final_response, success, stop ("llm_decided_complete")
        "tool_call" -> registry.execute(tool_name, arguments)   # Groq-chosen
                        append assistant + tool-result messages
        invalid     -> nudge model, continue
if the loop ends without "final": "maximum_iterations_reached"
```

### 3.2 Modes B/C — `HybridAgent.run(task)`

**Phase 1 — Planning (Groq).** `build_hybrid_planning_prompt` returns a
plan plus a five-field `task_specification`:
`objective`, `required_outcomes`, `allowed_tools`, `required_tools`,
`completion_criteria`. `_validate_task_specification()` enforces exact
fields, valid types, `required_tools ⊆ allowed_tools`,
`allowed_tools ⊆ registered tools`, no duplicates, and an explicit
user-authorisation regex for `create_support_ticket` (a state-changing
action). Failure → `termination_reason = "planning_error"`, no Jev call.

**Phase 2 — Control loop (`ControlLoop.run`).** The loop sees only the
planner-authorised tools: `available_tools` is the registry filtered
through `allowed_tools` for the entire run. An allowed tool missing from
the registry stops the run with `unauthorized_tool_configuration`.

Per iteration (up to `max_iterations + 1` Jev evaluations):

1. Jev `evaluate_state(state, available_tools)` → decision; appended to
   `decision_history` and `progress_history`.
2. **Evidence-gated completion:** stop with success
   `jev_detected_completion` only when `completion_probability >= 0.70`
   **and** every tool in `required_tools` produced valid evidence.
   Jev confirming completion without full evidence stops with
   `required_tools_not_fulfilled` (success stays `False`). An empty
   `required_tools` list imposes no evidence requirement.
3. **Loop guard:** fires only when `loop_probability >= 0.70` **and** at
   least 2 tool calls completed **and** normalised progress ≤ 0.20 →
   `jev_detected_loop`.
4. `len(tool_calls) >= max_iterations` → `maximum_iterations_reached`.
5. `selected_tool` must be in `available_tools` (the allowed subset),
   else `unauthorized_jev_tool_selection`.
6. Groq generates **arguments only** for Jev's selected tool; the tool
   itself cannot be changed by Groq → parse failure gives
   `argument_generation_error`.
7. Deterministic repeat guard: an identical `(tool, arguments)` signature
   is blocked after `max_identical_calls = 2` → `repeated_tool_call`.
8. `registry.execute(selected_tool, arguments)` — the only execution
   path, so an unauthorised tool can never run.

**Phase 3 — Final response (Groq).** `jev_error` short-circuits to a
hard-coded failure message (no Groq call). Otherwise
`build_hybrid_final_prompt` → `{"response": "..."}`; failure appends
`_final_response_error` to the termination reason. `success =
loop_result.success AND final_response non-empty`.

## 4. Jev and LLM integration

- **Jev** receives the full agent state (user request, plan, task
  specification, required/allowed tools, fulfilled tools, iteration,
  tool history, latest result, progress history) plus the available tool
  set, and returns one decision containing: `selected_tool`,
  `tool_probabilities`, `tool_confidence`, `completion_probability`,
  `loop_probability`, `progress_score`, model name, token counts and
  latency.
- **Groq** is used for planning, argument generation, final response
  generation and (Mode C) advisory reviews. Its responses are parsed as
  JSON with Markdown-fence tolerance.
- Neither client validates API keys at import time — validation happens
  in the client constructors, so tests with fake clients run without any
  keys.

## 5. Uncertainty detection and escalation (Mode C)

`EscalationAgent` wraps the Mode B loop. Triggers (configurable in
`config/settings.py`):

- **Tool selection:** selected-tool probability (or Choice confidence
  when the probability map lacks the pick) ≤
  `tool_confidence_threshold` (default `0.60`,
  `TOOL_CONFIDENCE_THRESHOLD`).
- **Task completion:** completion probability inside the ambiguous band
  `[completion_ambiguity_lower, completion_ambiguity_upper)` (default
  `[0.50, 0.70)`, `COMPLETION_AMBIGUITY_LOWER` /
  `COMPLETION_AMBIGUITY_UPPER`).

Flow per uncertain decision:

1. **Tool-selection escalation** — after Jev's pick is validated against
   `available_tools`, Groq reviews task, specification, authorised tools,
   Jev's proposal and history, returning `{"selected_tool", "reasoning"}`.
   An authorised recommendation replaces the pick; an unauthorised,
   malformed or failed response falls back to Jev's already-authorised
   selection.
2. **Completion escalation** — Groq reviews objective, required outcomes,
   criteria and execution history, returning `{"task_complete", ...}`.
   Completion is accepted (`groq_confirmed_completion`) only when Groq
   succeeded **and** recommended `True` **and** every required tool has
   valid evidence.

Every escalation outcome is recorded in `decision_history` with six extra
keys (`decision_type`, `escalated`, `escalation_reason`,
`groq_recommendation`, `final_decision`, `escalation_succeeded`), present
on every entry so the history format stays uniform. Escalation Groq usage
is accumulated into the run's LLM token/latency metrics. **A failed
escalation never marks a task complete and never authorises an
unauthorised tool.**

## 6. Safety mechanisms and execution safeguards

- `allowed_tools` filtering is applied for the whole run; Jev never sees
  unauthorised tools, and execution only ever goes through
  `registry.execute`.
- `create_support_ticket` requires an explicit user request (regex check
  in the planner validation), independent of the planner's judgement.
- The evidence gate: completion requires valid structural evidence from
  every required tool. Jev's probability alone never establishes success.
- Deterministic guards against repeated identical calls, runaway loops
  and excessive iterations.
- Every termination path produces a machine-readable
  `termination_reason`; the benchmark never invents missing metrics.
- Mocked and live execution are recorded separately via
  `execution_type` and never merged in comparisons.

## 7. Evaluation and benchmarking architecture

`scripts/run_benchmark.py` defines `BenchmarkRunner`, which executes the
dataset (`data/tasks.json`, 10 tasks across knowledge retrieval, service
status, ticket creation and multi-step categories) in each mode. Two
execution paths:

- **mocked (default)** — deterministic `FakeLLMClient` / `FakeJevClient`
  with scripted responses; offline, free, used by the test suite.
- **live (opt-in)** — real APIs, gated behind `--live`, a positive
  `--max-live-runs` budget and `--yes` confirmation.

Each run is verified independently by `TaskVerifier` (outcome
`verified` / `failed` / `unverifiable`) and appended through
`ExperimentLogger` to `experiments/benchmark_results.{csv,jsonl}`.

## 8. Streamlit dashboard architecture

`app.py` is a presentation layer only; it does not reimplement agent or
evaluation logic.

```
app.py (presentation)
  ├── load_benchmark_data() ──► experiments/benchmark_results.{csv,jsonl}
  │                             (falls back to experiments/demo_mocked/)
  ├── _run_mocked_agent()  ──► scripts/run_benchmark.py (FakeLLMClient/FakeJevClient)
  ├── _run_live_agent()    ──► agents/{baseline_agent,hybrid_agent}.py ──► models/{llm,jev}_client.py
  └── render_*()           ──► six sidebar pages: Overview, Agent Playground,
                               Execution Monitor, Benchmark Analytics,
                               Mode Comparison, Architecture
```

- No execution happens on page load; the playground defaults to mocked
  execution and live execution is opt-in per click.
- CSV rows are joined to JSONL records by `run_id` so charts get both
  flat metrics and verification/raw-execution detail.
- Missing metrics render as "N/A" or are excluded; nothing is fabricated.
- API keys and env values are never displayed.

## 9. Error handling summary

- `GroqClientError`: rate limit, connection, API status, unexpected.
- `JevClientError`: any Jev SDK exception.
- `ToolExecutionError`: unknown tool, non-dict args, missing/unexpected
  args, tool function exception.
- Agent termination reasons: `planning_error`,
  `argument_generation_error`, `jev_error`,
  `unauthorized_jev_tool_selection`, `unauthorized_tool_configuration`,
  `required_tools_not_fulfilled`, `repeated_tool_call`,
  `invalid_llm_response`, `maximum_iterations_reached`,
  `no_tool_execution_required`, plus the success and escalation
  reasons above.
