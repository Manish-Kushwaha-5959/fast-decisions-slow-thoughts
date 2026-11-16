# Development

How to set up, test and extend the project. For research methodology see
[EXPERIMENTS.md](EXPERIMENTS.md); for the system design see
[ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Prerequisites

- Python 3.11+
- pip
- A virtual environment is recommended (`venv/` is gitignored).

## 2. Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows; use source venv/bin/activate on Unix
pip install -r requirements.txt
```

`requirements.txt` (unpinned):

| Package | Used for |
|---|---|
| `typesafe-sdk` | Jev / TypeSafe System One API client. |
| `groq` | Groq LLM API client. |
| `python-dotenv` | `.env` loading. |
| `streamlit`, `pandas`, `numpy`, `plotly` | Research dashboard. |
| `pytest` | Test runner. |

## 3. Configuration

Copy `.env.example` to `.env` and fill in keys. `.env` is gitignored and
must never be committed.

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY` | (required for live runs) | Groq API key. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model ID. Note `.env.example` ships `llama-3.3-70b-versatile`; `settings.py` defaults to `openai/gpt-oss-120b`. |
| `GROQ_TEMPERATURE` | `0.2` | Sampling temperature. |
| `GROQ_MAX_COMPLETION_TOKENS` | `1024` | Max completion tokens. |
| `GROQ_TIMEOUT` | `60` | Request timeout (seconds). |
| `TYPESAFE_API_KEY` | (required for live runs) | TypeSafe/Jev API key. |
| `JEV_MODEL` | `jev-latest` | Jev model (resolves to `jev-1.14.0` at the API). |
| `TOOL_CONFIDENCE_THRESHOLD` | `0.60` | Mode C tool-selection escalation threshold (provisional). |
| `COMPLETION_AMBIGUITY_LOWER` / `_UPPER` | `0.50` / `0.70` | Mode C completion ambiguity band (provisional). |

No API keys are needed for mocked execution, the benchmark or the test
suite.

## 4. Directory structure

```
hybrid_agent_mvp/
├── app.py                  Streamlit dashboard (presentation layer)
├── requirements.txt        Dependencies (unpinned)
├── .env.example            Configuration template
├── agents/
│   ├── baseline_agent.py   Mode A
│   ├── control_loop.py     Mode B/C execution loop
│   ├── escalation_agent.py Mode C uncertainty detection + advisory review
│   ├── hybrid_agent.py     Mode B/C orchestrator
│   └── prompts.py          Prompt builders
├── config/settings.py      .env loading + validation (frozen Settings)
├── models/
│   ├── llm_client.py       GroqLLMClient
│   └── jev_client.py       JevClient (TypeSafe SDK)
├── tools/
│   ├── registry.py         ToolRegistry + build_default_registry()
│   ├── knowledge_base.py   search_knowledge_base
│   ├── service_status.py   check_service_status
│   └── ticket_manager.py   create_support_ticket / TicketManager
├── evaluation/
│   ├── logger.py           ExperimentLogger (append-only CSV+JSONL)
│   ├── metrics.py          extract_run_metrics / summarize_runs
│   └── task_verifier.py    TaskVerifier (independent verification)
├── scripts/
│   ├── run_baseline.py     CLI: Mode A
│   ├── run_hybrid.py       CLI: Mode B/C (appends to experiments/)
│   ├── run_benchmark.py    BenchmarkRunner + CLI + threshold analysis
│   ├── demo_mode_c.py      Mocked Mode C demonstration
│   ├── smoke_test_mode_c.py  Live Mode C smoke test (bounded)
│   ├── smoke_test_jev.py   Live Jev smoke test
│   ├── test_groq.py        Live Groq connection test
│   └── test_jev_client.py  Live Jev client test
├── tests/                  144 mocked tests (no live API)
├── data/
│   ├── knowledge_base.json Static support articles
│   └── tasks.json          10 benchmark tasks with verification rules
├── experiments/            Recorded outputs (append-only)
└── docs/                   ARCHITECTURE / EXPERIMENTS / DEVELOPMENT / REPRODUCIBILITY
```

## 5. Running the application

```bash
streamlit run app.py        # dashboard at http://localhost:8501
```

The dashboard reads recorded benchmark data (falling back to
`experiments/demo_mocked/` when the main files are empty) and lets an
evaluator execute tasks through the real agents. The Agent Playground
defaults to mocked execution; live API execution is opt-in via the
"Live API" radio button and requires valid keys in `.env`.

Single-task CLIs (live APIs, require keys):

```bash
python scripts/run_baseline.py --task "..." --max-iterations 5
python scripts/run_hybrid.py --task "..." --max-iterations 5 [--no-escalation]
```

`scripts/run_hybrid.py` appends every run to
`experiments/results.csv` and `experiments/experiment_logs.jsonl`.

## 6. Testing

```bash
python -m pytest tests/ -v
```

All 144 tests are mocked; none touches a live API. Coverage by file
(as of 2026-11-16):

| File | Tests |
|---|---|
| `tests/test_agents.py` | 7 (baseline) |
| `tests/test_hybrid_agent.py` | 32 (hybrid) |
| `tests/test_tools.py` | 13 (tool/registry) |
| `tests/test_escalation.py` | 25 (Mode C escalation) |
| `tests/test_phase7.py` | 67 (evaluation/benchmark) |

`tests/test_jev_client.py` is intentionally empty — the Jev client has no
unit coverage (see EXPERIMENTS.md §7).

## 7. Development workflow

1. Keep the five-field `task_specification` contract consistent across
   `prompts.py`, `hybrid_agent.py` and `control_loop.py`.
2. Do not weaken the safeguards: `allowed_tools` enforcement, the ticket
   authorisation guard and the evidence gate are invariants.
3. Never fabricate benchmark rows; append only, and prefer
   `--output experiments/<name>` per campaign.
4. Run `python -m pytest tests/ -v` before committing; the mocked suite
   must stay green without any API key.
5. Keep mocked and live execution distinguishable (`execution_type`).

## 8. Adding tools or modifying agent components

- Add the tool function under `tools/`, register it in
  `build_default_registry()` (`tools/registry.py`), and add its schema to
  `data/tasks.json` categories as needed.
- `ControlLoop._has_valid_evidence` and the verifier's local copy define
  what counts as valid evidence per tool; update **both** deliberately and
  keep them independent.
- `data/tasks.json` tasks are validated by `validate_tasks()`; invalid
  datasets are rejected rather than silently run.
- Mode C thresholds are read from `config/settings.py` at construction
  time; keep them configurable and provisional until calibrated.
