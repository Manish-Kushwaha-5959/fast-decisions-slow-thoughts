# Reproducibility

Everything needed to reproduce the recorded experiments, with the
mocked/live distinction made explicit.

## 1. Environment requirements

- Python 3.11+ (developed on Windows 11; the code is platform-independent).
- `pip install -r requirements.txt` (unpinned): `typesafe-sdk`, `groq`,
  `python-dotenv`, `streamlit`, `pandas`, `numpy`, `plotly`, `pytest`.
- Optional: `streamlit` for the dashboard, `pytest` for the suite.

## 2. Required configuration

Copy `.env.example` to `.env` and fill in keys.

- **Mocked runs:** no keys required.
- **Live runs:** `GROQ_API_KEY` and `TYPESAFE_API_KEY` are required; the
  clients validate them at construction time.
- Mode C thresholds come from `.env` (defaults 0.60 / 0.50 / 0.70) and are
  provisional until calibrated (see EXPERIMENTS.md §7).

`.env` is gitignored; never commit keys or local environment files.

## 3. Reproduce the test suite

```bash
python -m pytest tests/ -v
```

Expected: **144 passed** (mocked only; no live API, no keys). This was the
verified state of the working tree on 2026-11-16.

## 4. Reproduce the benchmark

### 4.1 Mocked (offline, free)

```bash
# default output: experiments/benchmark_results.{csv,jsonl}
python scripts/run_benchmark.py --mode all --repetitions 1

# clean single-version output directory
python scripts/run_benchmark.py --mode all --repetitions 1 \
    --output experiments/demo_mocked

# custom task file (same schema as data/tasks.json)
python scripts/run_benchmark.py --mode A --tasks data/tasks.json

# threshold analysis over recorded Mode C decisions
python scripts/run_benchmark.py --threshold-analysis
```

### 4.2 Live (opt-in, real cost)

```bash
python scripts/run_benchmark.py --mode A --live --max-live-runs 3 --yes
```

The runner enforces the budget: `--live` requires `--max-live-runs >= 1`
and `--yes`; it aborts before contacting any API otherwise. Without these
flags, execution is always mocked.

### 4.3 Single-task CLIs (live)

```bash
python scripts/run_baseline.py --task "Check the current VPN service status."
python scripts/run_hybrid.py --task "Check the current VPN service status."
python scripts/demo_mode_c.py        # mocked, offline, free
```

## 5. Recorded output locations

| Path | How produced | Execution type |
|---|---|---|
| `experiments/benchmark_results.{csv,jsonl}` | `run_benchmark.py` (default `--output`) | mocked (note: mixes two code versions — see below) |
| `experiments/demo_mocked/` | `run_benchmark.py --output experiments/demo_mocked` | mocked, clean single version (30 rows) |
| `experiments/results.csv` + `experiments/experiment_logs.jsonl` | `run_hybrid.py` | live (first recorded Mode B run, 2026-11-15) |

All files are append-only; do not hand-edit history.

## 6. What is recorded vs not recorded

- **Recorded (in-repo):** one live Mode B run (2026-11-15, success, 3729
  combined tokens, 5.92 s — `experiments/results.csv`); one clean mocked
  campaign (`demo_mocked/`); the Phase 7 mocked benchmark rows.
- **Not recorded:** any live benchmark campaign, live Mode A/C rows,
  calibration data near the escalation thresholds. Do not fabricate them;
  run the commands above to generate new data with a fresh `--output`
  directory.

## 7. Mocked vs live execution

| | Mocked | Live |
|---|---|---|
| Clients | `FakeLLMClient` / `FakeJevClient` (scripted, deterministic) | `GroqLLMClient` / `JevClient` |
| Cost / network | None / offline | Real tokens / real APIs |
| Opt-in | default | `--live` + budget + `--yes` |
| `execution_type` field | `mocked` | `live` |
| What it validates | Pipeline, verification, mode comparison | API behaviour, real cost/latency |

The dashboard and the benchmark never mix the two in one comparison; a
live row can be identified by its `execution_type`.

## 8. External API dependencies and limitations

- **Groq** — model default `openai/gpt-oss-120b` (`settings.py`);
  `.env.example` ships `llama-3.3-70b-versatile` (the model that was
  decommissioned during Phase 1 — see git history). Live runs need a valid
  key; rate limits and timeouts surface as `GroqClientError`.
- **TypeSafe Jev** — model default `jev-latest` (resolves to `jev-1.14.0`);
  live runs need `TYPESAFE_API_KEY`. `JevClient` has **no request timeout**
  (unlike Groq's `GROQ_TIMEOUT`); a hung Jev call blocks the loop.
- The three tools are simulated locally; no external service is contacted
  by tools.
- Known gaps (no unit coverage for API clients, escalation branches not yet
  exercised live, thresholds uncalibrated) are listed in EXPERIMENTS.md §7.
