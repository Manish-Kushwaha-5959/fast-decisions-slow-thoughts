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
| `agents/prompts.py` | Prompt builders: baseline, hybrid planning, hybrid argument, hybrid final. |
| `agents/baseline_agent.py` | Mode A — LLM controls everything. |
| `agents/control_loop.py` | Mode B execution loop — Jev controls selection/completion/loop/progress. |
| `agents/hybrid_agent.py` | Mode B orchestrator — planning → control loop → final response. |
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
- `build_hybrid_planning_prompt(task, available_tools)` returns a JSON object with `plan` and `task_specification`.
- `_validate_task_specification()` enforces exact fields `{objective, required_outcomes, allowed_tools, completion_criteria}`, valid types, `allowed_tools ⊆ registered tools`, no duplicates, and **explicit user authorization regex** for `create_support_ticket`.
- Failure → `termination_reason = "planning_error"`, no Jev call.

### Phase 2 — Control Loop (`ControlLoop.run`)
Per iteration (max `max_iterations+1` evaluations):
1. **Jev** `evaluate_state(state, available_tools)` → decision; appended to `decision_history` and `progress_history`.
2. If `completion_probability >= 0.70` → stop `jev_detected_completion` (success).
3. **Loop guard:** requires `loop_probability >= 0.70` **AND** ≥2 completed tool calls **AND** normalized progress ≤ 0.20 → stop `jev_detected_loop`.
4. If `len(tool_calls) >= max_iterations` → stop `maximum_iterations_reached`.
5. Validate `selected_tool ∈ available_tools` (full registry) → else `invalid_jev_tool_selection`.
6. **Groq** generates arguments only (`build_hybrid_argument_prompt`), parsed to `{"arguments": {...}}` → else `argument_generation_error`.
7. Deterministic repeat guard: identical `(tool, args)` signature blocked after `max_identical_calls=2` → `repeated_tool_call`.
8. `registry.execute(selected_tool, arguments)`; record call + latency; append to history.
9. After loop: if not stopped, `maximum_iterations_reached`.

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

| Decision | Mode A (baseline) | Mode B (hybrid) |
|---|---|---|
| Planning | Groq | Groq |
| Tool selection | Groq | **Jev** (Choice) |
| Argument generation | Groq | Groq |
| Completion detection | Groq (`action=final`) | **Jev** (Noul) |
| Loop detection | Prompt text only | **Jev** (Noul) + deterministic guard |
| Progress estimation | None | **Jev** (Score) |
| Final response | Groq | Groq |

## 7. Error Handling Summary

- `GroqClientError`: rate limit, connection, API status, unexpected.
- `JevClientError`: any Jev SDK exception.
- `ToolExecutionError`: unknown tool, non-dict args, missing/unexpected args, tool function exception.
- Agent-level: `planning_error`, `argument_generation_error`, `jev_error`, `invalid_jev_tool_selection`, `repeated_tool_call`, `invalid_llm_response`, `maximum_iterations_reached`, `no_tool_execution_required`.