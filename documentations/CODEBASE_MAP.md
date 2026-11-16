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
│   └── tasks.json              10 benchmark tasks (4 categories) with verification rules
├── documentations/             phase design/validation notes (01–06 + risks/timeline/order)
├── evaluation/
│   ├── logger.py               append-only CSV+JSONL experiment logger
│   ├── metrics.py              provider-distinguishable metric extraction + aggregation
│   └── task_verifier.py        independent outcome verification + task loading/validation
├── experiments/
│   ├── results.csv             first live Mode B run recorded 2026-11-15
│   ├── experiment_logs.jsonl   first live Mode B run recorded 2026-11-15
│   ├── benchmark_results.csv   Phase 7 benchmark rows (mocked demo + earlier stale rows)
│   ├── benchmark_results.jsonl Phase 7 benchmark full records (verification + raw execution)
│   └── demo_mocked/            clean single-version mocked benchmark output
├── models/
│   ├── llm_client.py           GroqLLMClient
│   └── jev_client.py           JevClient (TypeSafe SDK)
├── scripts/
│   ├── run_baseline.py         CLI for Mode A
│   ├── run_hybrid.py           CLI for Mode B
│   ├── run_benchmark.py        Phase 7 BenchmarkRunner + CLI + threshold analysis
│   ├── demo_mode_c.py          mocked Mode C demonstration
│   ├── smoke_test_jev.py       live Jev smoke test (hard-coded state)
│   ├── test_groq.py            live Groq connection test
│   └── test_jev_client.py      live Jev client test
├── tests/
│   ├── test_agents.py          7 baseline tests (mocked)
│   ├── test_hybrid_agent.py    32 hybrid tests (mocked)
│   ├── test_tools.py           13 tool/registry tests
│   ├── test_escalation.py      25 Mode C escalation tests (mocked)
│   ├── test_phase7.py          67 Phase 7 evaluation/benchmark tests
│   └── test_jev_client.py      *** 0 bytes — no Jev client unit tests ***
├── app.py                      Phase 8 Streamlit dashboard (6 sections)
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
| `evaluation/logger.py` | `ExperimentLogger.log()`, `CSV_FIELDS`, `count_records()`, `read_csv()` |
| `evaluation/metrics.py` | `extract_run_metrics()`, `summarize_runs()`, `MetricSummary` |
| `evaluation/task_verifier.py` | `TaskVerifier.verify()`, `_has_valid_evidence()`, `load_tasks()`, `validate_tasks()`, `VerificationResult`, `CheckResult` |
| `scripts/run_benchmark.py` | `BenchmarkRunner`, `FakeLLMClient`, `FakeJevClient`, `_confirm_live()` (safety gate), `print_summary()`, `print_threshold_analysis()` |
| `app.py` | Phase 8 dashboard. `load_benchmark_data()`, `get_mode_success_rates()`, `get_latency_data()`, `get_token_data()`, `get_escalation_data()`, `_run_mocked_agent()`, `_run_live_agent()`, `render_agent_playground()`, `render_execution_monitor()`, `render_benchmark_analytics()`, `render_mode_comparison()`, `render_architecture()` |

## Module Dependency Graph

```
scripts/run_baseline.py ──► agents/baseline_agent.py ──► models/llm_client.py ──► config/settings.py
                                                   └──► tools/registry.py ──► tools/{knowledge_base,service_status,ticket_manager}.py
                                                   └──► agents/prompts.py

scripts/run_hybrid.py ───► agents/hybrid_agent.py ──► agents/control_loop.py ──► models/{llm,jev}_client.py
                                                   │                        └──► tools/registry.py
                                                   └──► models/llm_client.py
                                                   └──► agents/prompts.py

scripts/run_benchmark.py ──► agents/{baseline_agent,hybrid_agent}.py ──► models/{llm,jev}_client.py
                            └──► evaluation/{logger,metrics,task_verifier}.py ──► tools/registry.py

app.py (dashboard) ──► scripts/run_benchmark.py (mocked path) ──► agents/*
                  ├──► evaluation/logger.py (reads benchmark_results.csv/.jsonl)
                  └──► agents/{baseline_agent,hybrid_agent}.py (live path, opt-in)

tests/* ──► agents/*, tools/*, evaluation/*, scripts/run_benchmark.py  (inject FakeLLMClient / FakeJevClient)
```

No circular imports. `config.settings` is imported at module load by both clients; it does **not** validate keys at import time (validation is in `GroqLLMClient.__init__` / `JevClient.__init__`), so tests with fakes run without API keys. The dashboard's mocked path (`_run_mocked_agent`) also needs no keys.

## Main Execution Entry Points

- **Dashboard:** `streamlit run app.py` (opens at `http://localhost:8501`)
- **Mode A:** `python scripts/run_baseline.py --task "..." [--max-iterations N]`
- **Mode B:** `python scripts/run_hybrid.py --task "..." [--max-iterations N]`
- **Benchmark (mocked):** `python scripts/run_benchmark.py --mode all --repetitions 1 --output experiments/demo_mocked`
- **Tests:** `python -m pytest tests/ -v`
- **Live checks:** `python scripts/test_groq.py`, `python scripts/test_jev_client.py`, `python scripts/smoke_test_jev.py`

## Environment / Dependencies

`requirements.txt` (unpinned): `typesafe-sdk`, `python-dotenv`, `streamlit`, `pandas`, `numpy`, `pytest`, `groq`.

`.env.example` keys: `GROQ_API_KEY`, `GROQ_MODEL`, `TYPESAFE_API_KEY`, `GROQ_TEMPERATURE`, `GROQ_MAX_COMPLETION_TOKENS`, `GROQ_TIMEOUT`. `JEV_MODEL` is read by settings but absent from `.env.example` (defaults to `jev-latest`).