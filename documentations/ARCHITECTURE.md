# Architecture

## 1. Module Responsibilities

| Module | Responsibility |
|---|---|
| `config/settings.py` | Reads `.env` into a frozen `Settings` dataclass; validates API keys. |
| `models/llm_client.py` | `GroqLLMClient` — Groq chat completions, token/latency capture, typed errors. |
| `models/jev_client.py` | `JevClient` — one `system_one()` request returning a `JevDecisionResult`. |
| `tools/registry.py` | `ToolRegistry` — tool definitions, schema export, argument validation, execution, reset. |
| `tools/knowledge_base.py` | `search_knowledge_base` — lexical retrieval over `data/knowledge_base.json`. |
| `tools/service_status.py` | `check_service_status` — fixed simulated service-status lookup. |
| `tools/ticket_manager.py` | `TicketManager` — in-memory ticket creation, reset. |
| `agents/prompts.py` | Prompt builders: baseline, hybrid planning, hybrid argument, hybrid final, escalation review (tool + completion). |
| `agents/baseline_agent.py` | Mode A — LLM controls everything. |
| `agents/control_loop.py` | Mode B/C execution loop — Jev controls selection/completion/loop/progress; Mode C escalates uncertain decisions to Groq. |
| `agents/escalation_agent.py` | Mode C escalation reviewer — decides when Jev is uncertain and asks Groq for an advisory review. |
| `agents/hybrid_agent.py` | Mode B/C orchestrator — planning → control loop → final response; constructs the EscalationAgent (Mode C) or runs pure Mode B. |
| `evaluation/logger.py` | **EMPTY placeholder.** |
| `evaluation/metrics.py` | **EMPTY placeholder.** |
| `evaluation/task_verifier.py` | **EMPTY placeholder.** |
| `agents/escalation_agent.py` | **EMPTY placeholder (Phase 6).** |
| `app.py` | **EMPTY placeholder (Phase 8 dashboard).** |
| `scripts/run_baseline.py` | CLI entry for Mode A. |
| `scripts/run_hybrid.py` | CLI entry for Mode B. |
| `scripts/run_benchmark.py` | **EMPTY placeholder (Phase 7).** |
| `data/tasks.json` | **EMPTY placeholder (benchmark tasks).** |

## 2. Data Structures

- `LLMResponse` — content, model, token counts, latency, finish_reason, request_id.
- `JevDecisionResult` — `selected_tool`, `tool_probabilities`, `tool_confidence`, `completion_probability`, `loop_probability`, `progress_score`, `model`, token counts, latency.
- `ToolDefinition` (frozen dataclass) — `name`, `description`, `function`, `parameters` (JSON schema); `to_llm_schema()`.
- `AgentRunResult` (baseline) — task, final_response, success, iterations, tool_calls, LLM tokens/latency, termination_reason.
- `HybridAgentRunResult` (hybrid) — adds `decision_history`, `task_specification`, Jev tokens/latency.
- `ControlLoopResult` — success, final_response, iterations, tool_calls, decision_history, Jev + LLM tokens/latency, tool latency, termination_reason.
- `EscalationOutcome` — decision_type, escalated, reason, recommendation, succeeded, final_decision, error, token/latency usage.
- `EscalationAgent` — threshold checks (`tool_selection_required`, `completion_required`) and Groq review calls (`escalate_tool_selection`, `escalate_completion`).

## 3. Baseline Execution Flow (Mode A)

```
run(task)
  registry.reset_state()
  build system prompt (tool schemas + max_iterations) + initial user msg
  for iteration in range(max_iterations):
      llm.generate(messages)                       # one Groq call per step
      parse action JSON:
        - "final"     -> set final_response, success, stop ("llm_decided_complete")
        - "tool_call" -> registry.execute(tool_name, arguments)  (Groq-chosen)
                          append assistant + tool-result messages
        - invalid     -> nudge model, continue
  if loop ends without "final": "maximum_iterations_reached"
```

Groq decides: plan, tool, arguments, continuation, completion. Errors: `invalid_llm_response`, `maximum_iterations_reached`.

## 4. Hybrid Execution Flow (Mode B)

**`HybridAgent.run(task)`** orchestrates three phases:

### Phase 1 — Planning (Groq)
- `build_hybrid_planning_prompt(task, available_tools)` returns a JSON object with `plan` and a five-field `task_specification`: `objective`, `required_outcomes`, `allowed_tools`, `required_tools`, `completion_criteria`.
- `_validate_task_specification()` enforces exact five fields, valid types, `required_tools ⊆ allowed_tools`, `allowed_tools ⊆ registered tools`, no duplicates in `allowed_tools`, and **explicit user authorization regex** for `create_support_ticket`.
- `required_tools` may be empty (no mandatory tool); `allowed_tools` must be non-empty.
- Failure → `termination_reason = "planning_error"`, no Jev call.

### Phase 2 — Control Loop (`ControlLoop.run`)
The loop receives only the planner-authorised tools: `available_tools` is the registry filtered through `task_specification["allowed_tools"]` for the **entire** run (the full registry is never restored). An allowed tool missing from the registry terminates immediately with `unauthorized_tool_configuration`.

Per iteration (max `max_iterations+1` evaluations):
1. **Jev** `evaluate_state(state, available_tools)` → decision; appended to `decision_history` and `progress_history`.
2. **Evidence-gated completion:** recompute `fulfilled_required_tools` from `tool_history`. Stop with success `jev_detected_completion` only when `completion_probability >= 0.70` **AND** every tool in `required_tools` has valid evidence. If Jev confirms completion but evidence is incomplete → stop `required_tools_not_fulfilled` (not success). An empty `required_tools` imposes no evidence requirement.
3. **Loop guard:** requires `loop_probability >= 0.70` **AND** ≥2 completed tool calls **AND** normalized progress ≤ 0.20 → stop `jev_detected_loop`.
4. If `len(tool_calls) >= max_iterations` → stop `maximum_iterations_reached`.
5. Validate `selected_tool ∈ available_tools` (the **allowed subset**) → else `unauthorized_jev_tool_selection`.
6. **Groq** generates arguments only (`build_hybrid_argument_prompt`), parsed to `{"arguments": {...}}` → else `argument_generation_error`.
7. Deterministic repeat guard: identical `(tool, args)` signature blocked after `max_identical_calls=2` → `repeated_tool_call`.
8. `registry.execute(selected_tool, arguments)` (the only execution path, so unauthorised tools cannot run); record call + latency; append to history.
9. After loop: if not stopped, `maximum_iterations_reached`.

**Evidence rules** (`_has_valid_evidence`): execution status must be `"success"`, the result a dict without `"error"`, plus per-tool structural checks — `check_service_status` needs `status ∈ {operational, degraded, outage}` and `source == "local_simulation"`; `search_knowledge_base` needs a non-empty `results` list and `result_count > 0`; `create_support_ticket` needs a non-empty `ticket_id`, `status == "created"` and `simulation is True`; unknown tools fall back to truthiness. Failed or malformed executions never count as fulfilled.

### Mode C — Uncertainty Detection and Escalation (Phase 6)

Mode C wraps the Mode B loop with an advisory `EscalationAgent`. When present (`enable_escalation=True`, the default), uncertain Jev decisions are sent to Groq for review. Groq advises; the controller keeps final authority. Every Phase 5 safeguard remains in force: `allowed_tools` is enforced on the tool actually executed, the `create_support_ticket` authorisation guard is unchanged, and the evidence gate can never be bypassed by a Groq recommendation.

**Escalation triggers (configurable via `config/settings.py`):**
- Tool selection: selected-tool probability (or Choice confidence when the probability map lacks the pick) ≤ `tool_confidence_threshold` (default 0.60, `TOOL_CONFIDENCE_THRESHOLD`).
- Task completion: completion probability inside the ambiguous band `[completion_ambiguity_lower, completion_ambiguity_upper)` (default 0.50–0.70, `COMPLETION_AMBIGUITY_LOWER`/`COMPLETION_AMBIGUITY_UPPER`).

**Execution flow per uncertain decision:**
1. **Tool-selection escalation** — after Jev's pick is validated against `available_tools`, Groq reviews the task, specification, authorised tools, Jev's proposal, and history, returning `{"selected_tool", "reasoning"}`. An authorised recommendation replaces the pick; an unauthorised/malformed/failed response falls back to Jev's already-authorised selection. Arguments are still generated by Groq and execution still runs only through `registry.execute`.
2. **Completion escalation** — before the loop guard, Groq reviews the objective, required outcomes, criteria, and execution history, returning `{"task_complete", "reasoning"}`. Completion is accepted (`groq_confirmed_completion`) only when Groq succeeded **and** recommended True **and** every required tool has valid evidence; otherwise execution continues. A failed/malformed escalation never marks the task complete.

**Decision history** entries carry six extra keys on every iteration (`decision_type`, `escalated`, `escalation_reason`, `groq_recommendation`, `final_decision`, `escalation_succeeded`), populated only when an escalation occurred; the Phase 5 field layout is unchanged. Escalation Groq usage is accumulated into the run's LLM token/latency metrics.

**Safe fallback:** an unauthorised recommendation, malformed JSON, or a Groq API failure is recorded in `decision_history` (with `escalation_succeeded: false`) and the run continues on Jev's authorised decision. Escalation never authorises execution of an unregistered or disallowed tool.

**Threshold caveat:** the defaults are provisional starting points chosen from the phase specification, not calibrated measurements; they require empirical calibration (see `documentations/risks.md` and Phase 7).

### Phase 3 — Final Response (Groq)
- `jev_error` → hard-coded failure message (no Groq call).
- Else `build_hybrid_final_prompt` → JSON `{"response": "..."}`; failure appends `_final_response_error` to termination reason.
- `success = loop_result.success AND final_response non-empty`.

## 5. Component Interaction Diagram (text)

```
                  ┌──────────────────────────┐
   user task ──►  │  HybridAgent.run()        │
                  │  Phase 1: Groq (planning) │──► task_specification
                  └───────────┬──────────────┘
                              ▼
                  ┌──────────────────────────┐
                  │  ControlLoop.run()        │
                  │  loop:                    │
                  │   Jev.evaluate_state()    │──► Jev API (system_one)
                  │   [Mode C] uncertain?     │──► EscalationAgent ──► Groq API (advisory)
                  │   Groq.generate(args)     │──► Groq API
                  │   registry.execute(tool)  │──► local tools
                  └───────────┬──────────────┘
                              ▼
                  ┌──────────────────────────┐
                  │  Groq (final response)    │
                  └───────────┬──────────────┘
                              ▼
                     HybridAgentRunResult
```

## 6. Control Responsibility Matrix

| Decision | Mode A (baseline) | Mode B (hybrid) | Mode C (escalation) |
|---|---|---|---|
| Planning | Groq | Groq | Groq |
| Tool selection | Groq | **Jev** (Choice) | **Jev**; Groq reviews when uncertain (advisory) |
| Argument generation | Groq | Groq | Groq |
| Completion detection | Groq (`action=final`) | **Jev** (Noul) | **Jev**; Groq reviews ambiguous probabilities (advisory, evidence-gated) |
| Loop detection | Prompt text only | **Jev** (Noul) + deterministic guard | Same as Mode B |
| Progress estimation | None | **Jev** (Score) | Same as Mode B |
| Final response | Groq | Groq | Groq |

## 7. Error Handling Summary

- `GroqClientError`: rate limit, connection, API status, unexpected.
- `JevClientError`: any Jev SDK exception.
- `ToolExecutionError`: unknown tool, non-dict args, missing/unexpected args, tool function exception.
- Agent-level: `planning_error`, `argument_generation_error`, `jev_error`, `unauthorized_jev_tool_selection`, `unauthorized_tool_configuration`, `required_tools_not_fulfilled`, `repeated_tool_call`, `invalid_llm_response`, `maximum_iterations_reached`, `no_tool_execution_required`.
- Mode C adds one termination reason: `groq_confirmed_completion` (Groq confirmed an ambiguous completion that the evidence gate also satisfied). Escalation failures never add a termination reason — they fall back to the Mode B path.