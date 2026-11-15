# Codebase Map

## Repository Structure

```
hybrid_agent_mvp/
├── agents/
│   ├── baseline_agent.py       Mode A agent
│   ├── control_loop.py         Mode B/C execution loop (Jev-controlled + escalation)
│   ├── hybrid_agent.py         Mode B/C orchestrator (EscalationAgent wiring)
│   ├── escalation_agent.py     Mode C uncertainty detection + Groq review (Phase 6)
│   ├── prompts.py              all system/user prompt builders (incl. escalation)
│   ├── control_loop.py.bak     uncommitted backup (329 lines)
│   └── hybrid_agent.py.bak     uncommitted backup (287 lines)
├── config/
│   └── settings.py             env loading + validation (frozen dataclass)
├── data/
│   ├── knowledge_base.json     static support articles (lexical search)
│   └── tasks.json              *** 0 bytes — benchmark tasks placeholder ***
├── documentations/             phase design/validation notes (01–06 + risks/timeline/order)
├── evaluation/
│   ├── logger.py               *** 0 bytes ***
│   ├── metrics.py              *** 0 bytes ***
│   └── task_verifier.py        *** 0 bytes ***
├── experiments/
│   ├── results.csv             first live Mode B run recorded 2026-11-15
│   └── experiment_logs.jsonl   first live Mode B run recorded 2026-11-15
├── models/
│   ├── llm_client.py           GroqLLMClient
│   └── jev_client.py           JevClient (TypeSafe SDK)
├── scripts/
│   ├── run_baseline.py         CLI for Mode A
│   ├── run_hybrid.py           CLI for Mode B
│   ├── run_benchmark.py        *** 0 bytes — Phase 7 placeholder ***
│   ├── smoke_test_jev.py       live Jev smoke test (hard-coded state)
│   ├── test_groq.py            live Groq connection test
│   └── test_jev_client.py      live Jev client test
├── tests/
│   ├── test_agents.py          7 baseline tests (mocked)
│   ├── test_hybrid_agent.py    32 hybrid tests (mocked)
│   ├── test_tools.py           13 tool/registry tests
│   └── test_jev_client.py      *** 0 bytes ***
├── app.py                      *** 0 bytes — Phase 8 dashboard placeholder ***
├── requirements.txt
├── README.md
└── .env.example
```

`venv/`, `PROJECT_CONTEXT.txt`, `SELECTED_CODE_CONTEXT.txt`, `export_*.py` are local artifacts and gitignored (except they appear on disk).

## Important Files and Responsibilities

| File | Key symbols |
|---|---|
| `config/settings.py` | `Settings` (frozen), `Settings.from_env()`, `validate_groq()`, `validate_typesafe()`, module-level `settings` |
| `models/llm_client.py` | `LLMResponse`, `GroqClientError`, `GroqLLMClient.generate()`, `.generate_text()`, `.close()` |
| `models/jev_client.py` | `JevDecisionResult`, `JevClientError`, `JevClient.evaluate_state()` |
| `tools/registry.py` | `ToolExecutionError`, `ToolDefinition.to_llm_schema()`, `ToolRegistry.{get_tool_names,get_tool_descriptions,get_llm_tool_schemas,get_tool,execute,reset_state}`, `build_default_registry()` |
| `tools/knowledge_base.py` | `search_knowledge_base()`, `_tokenize()`, `_load_knowledge_base()` |
| `tools/service_status.py` | `SERVICE_STATUS`, `SERVICE_ALIASES`, `check_service_status()` |
| `tools/ticket_manager.py` | `TicketManager`, module `ticket_manager`, `create_support_ticket()`, `reset_simulated_tickets()` |
| `agents/prompts.py` | `build_baseline_system_prompt()`, `build_initial_user_message()`, `build_hybrid_planning_prompt()`, `build_hybrid_argument_prompt()`, `build_hybrid_final_prompt()` |
| `agents/baseline_agent.py` | `AgentRunResult`, `BaselineAgent.run()`, `_parse_action()` |
| `agents/control_loop.py` | `ControlLoopResult`, `ControlLoop.run()`, `_parse_json()`, `_normalise_probability()`, `_call_signature()`, `_has_valid_evidence()`, `_get_fulfilled_required_tools()`; Mode C escalation branches + decision-history escalation fields |
| `agents/hybrid_agent.py` | `HybridAgentRunResult`, `HybridAgent.run()`, `_parse_json()`, `_validate_task_specification()`; `EscalationAgent` construction + `mode` attribute |
| `agents/escalation_agent.py` | `EscalationAgent` (`tool_selection_required`, `completion_required`, `escalate_tool_selection`, `escalate_completion`), `EscalationOutcome`, default thresholds |

## Module Dependency Graph

```
scripts/run_baseline.py ──► agents/baseline_agent.py ──► models/llm_client.py ──► config/settings.py
                                                   └──► tools/registry.py ──► tools/{knowledge_base,service_status,ticket_manager}.py
                                                   └──► agents/prompts.py

scripts/run_hybrid.py ───► agents/hybrid_agent.py ──► agents/control_loop.py ──► models/{llm,jev}_client.py
                                                   │                        └──► tools/registry.py
                                                   └──► models/llm_client.py
                                                   └──► agents/prompts.py

tests/* ──► agents/*, tools/*  (inject FakeLLMClient / FakeJevClient)
```

No circular imports. `config.settings` is imported at module load by both clients; it does **not** validate keys at import time (validation is in `GroqLLMClient.__init__` / `JevClient.__init__`), so tests with fakes run without API keys.

## Main Execution Entry Points

- **Mode A:** `python scripts/run_baseline.py --task "..." [--max-iterations N]`
- **Mode B:** `python scripts/run_hybrid.py --task "..." [--max-iterations N]`
- **Tests:** `python -m pytest tests/ -v`
- **Live checks:** `python scripts/test_groq.py`, `python scripts/test_jev_client.py`, `python scripts/smoke_test_jev.py`

## Environment / Dependencies

`requirements.txt` (unpinned): `typesafe-sdk`, `python-dotenv`, `streamlit`, `pandas`, `numpy`, `pytest`, `groq`.

`.env.example` keys: `GROQ_API_KEY`, `GROQ_MODEL`, `TYPESAFE_API_KEY`, `GROQ_TEMPERATURE`, `GROQ_MAX_COMPLETION_TOKENS`, `GROQ_TIMEOUT`. `JEV_MODEL` is read by settings but absent from `.env.example` (defaults to `jev-latest`).