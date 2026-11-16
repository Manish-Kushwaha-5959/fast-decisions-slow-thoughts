# Experiments

This document describes the research questions, the three experimental
modes, the benchmarking methodology and the evaluation metrics as they
are implemented. It deliberately avoids results claims: recorded data lives
under `experiments/` and is described in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## 1. Research questions

1. Does Jev-assisted tool selection reduce token consumption and latency
   compared with LLM-only selection (Mode A vs Mode B)?
2. Does Jev-assisted completion/loop detection improve task success rate
   and reduce wasted tool calls (Mode A vs Mode B)?
3. Does uncertainty-aware escalation (Mode C) improve success at an
   acceptable additional cost (Mode B vs Mode C)?
4. Is Jev's reported confidence calibrated to empirical correctness?

Questions 1–2 are answerable offline with the mocked benchmark; question 3
requires recorded escalation events; question 4 remains **unmeasured** —
see §7.

## 2. Experimental modes

| Mode | Name | Planning | Tool selection | Arguments | Completion | Loop detection | Progress |
|---|---|---|---|---|---|---|---|
| A | LLM-only | Groq | Groq | Groq | Groq (`action=final`) | prompt text only | none |
| B | LLM + Jev | Groq | **Jev** (Choice) | Groq | **Jev** (Noul) | **Jev** (Noul) + deterministic guard | **Jev** (Score) |
| C | Hybrid with escalation | Groq | **Jev**; Groq reviews when uncertain (advisory) | Groq | **Jev**; Groq reviews ambiguous probabilities (advisory, evidence-gated) | as B | as B |

In Mode C Groq's review is advisory: the controller keeps final authority,
and the allowed-tools restriction, the ticket authorisation guard and the
evidence-based completion gate can never be bypassed by a recommendation.

## 3. Methodology

### 3.1 Dataset

`data/tasks.json` — dataset `hybrid_agent_benchmark_v1`, 10 tasks in 4
categories, each with `expected_tools` and a `verification` block:

| Category | Tasks |
|---|---|
| `knowledge_retrieval` | `kb_password_reset`, `kb_wifi_troubleshooting`, `kb_payment_failure` |
| `service_status` | `status_vpn`, `status_internet`, `status_payment_portal` |
| `ticket_creation` | `ticket_login_issue`, `ticket_vpn_outage` |
| `multi_step` | `multi_status_and_knowledge`, `multi_knowledge_and_ticket` |

All tasks are answerable with the three registered local tools
(`search_knowledge_base`, `check_service_status`, `create_support_ticket`).
The tools are simulated: no external service is contacted.

### 3.2 Execution paths

- **mocked (default):** deterministic `FakeLLMClient` / `FakeJevClient`
  with scripted responses, so the whole benchmark runs offline at no cost.
  The same task definitions and the same deterministic verification
  criteria are used for every mode, so mocked results are comparable
  across modes.
- **live (opt-in):** real Groq/Jev APIs. Requires `--live`, a positive
  `--max-live-runs` budget and `--yes` confirmation; the runner aborts
  before contacting any API otherwise.

Mocked and live records are never merged: every record carries
`execution_type`, and the dashboard filters on it.

### 3.3 Benchmark procedure

```bash
# mocked comparison of all three modes (default, free)
python scripts/run_benchmark.py --mode all

# one mode, two repetitions, small output
python scripts/run_benchmark.py --mode B --repetitions 2 --quiet

# live run with an explicit budget of three executions
python scripts/run_benchmark.py --mode A --live --max-live-runs 3 --yes

# threshold analysis over the recorded data
python scripts/run_benchmark.py --threshold-analysis
```

For each `(mode, task, repetition)` the runner executes the agent,
extracts metrics, verifies the outcome independently and appends the
record. A task that errors is recorded as `unverifiable` so one failure
cannot abort the benchmark.

### 3.4 Independent verification

`TaskVerifier` recomputes the outcome from deterministic evidence only —
executed tool calls and their structural results, the final response text
and the task's declared verification rules. It never trusts the agent's
self-reported `success`. Outcomes:

- `verified` — every applicable check passed;
- `failed` — at least one check failed;
- `unverifiable` — evidence insufficient (missing execution record, no
  verification rules, no tool history, or a run that errored).

The verifier's evidence predicates are implemented locally, deliberately
not importing `ControlLoop._has_valid_evidence`, so verification stays
independent of agent internals.

## 4. Evaluation metrics

Per run, provider-distinguishable (Groq and Jev are never merged into one
provider's bucket):

| Metric | Meaning |
|---|---|
| `llm_input_tokens` / `llm_output_tokens` / `llm_total_tokens` | Groq token usage per run. |
| `jev_input_tokens` / `jev_output_tokens` / `jev_total_tokens` | Jev token usage (Modes B/C only; stays `None` for Mode A, never fabricated as 0). |
| `combined_tokens` | The only summed figure, computed once from provider totals. |
| `llm_latency_seconds` / `jev_latency_seconds` | API-side latency per provider. |
| `tool_latency_seconds` / `total_latency_seconds` | Local tool execution time; end-to-end run time. |
| `iterations` / `tool_calls` / `tool_execution_failures` | Effort and reliability of execution. |
| `escalation_count` / `tool_selection_escalations` / `completion_escalations` / `escalation_succeeded_count` | Mode C escalation behaviour, read from `decision_history` (one escalation = one decision review, not one provider request). |
| `escalation_frequency` | Escalation events per control-loop iteration, aggregated per mode. |
| `success` vs verified outcome | `agent_reported_success` is kept separate from the independent verification (`verified` / `failed` / `unverifiable`). |
| `termination_reason` | Machine-readable reason the run stopped (see ARCHITECTURE.md §9). |
| `decision_history` | Full Jev decision trace incl. probabilities, confidence, progress score and escalation fields. |

Per-mode aggregation (`MetricSummary`) reports verified/failed/unverifiable
counts, both success rates, provider token totals, mean latency, mean
iterations, tool-call counts and escalation counts. Missing values stay
`None`.

### 4.1 Economic cost metrics (Phase 11)

Every run also records estimated economic cost. The fields are stored
alongside the token metrics in `experiments/benchmark_results.{csv,jsonl}`
and are computed by `evaluation/economic_metrics.py` from the
provider-reported token usage already captured in the run record.

| Field | Meaning |
|---|---|
| `groq_estimated_cost` | Estimated cost of Groq usage at reference paid pricing (USD). |
| `jev_estimated_cost` | Estimated cost of Jev usage at reference paid pricing (USD). |
| `total_estimated_cost` | Sum of the two estimated costs for the run. |
| `groq_actual_cost` | Actual amount charged to the Groq account, when known. Free-tier calls are `$0`. |
| `jev_actual_cost` | Actual amount charged for Jev usage, when known. Not assumed free merely because Groq is. |
| `total_actual_cost` | Sum of the two actual costs. |
| `usage_measurement_method` | `actual` (provider-reported usage), `estimated` (tokenizer proxy), or `mocked` (synthetic clients). |
| `pricing_version` / `pricing_date` | Which pricing table produced the cost figures. |

Aggregate metrics per mode (`EconomicMetricsSummary`): total estimated
cost, average cost per task, median cost per task, cost by mode, Groq and
Jev cost contribution shares, cost per successful task, and cost per
failed task where meaningful.

**Actual expenditure vs estimated equivalent cost.** These are separate
fields and are never merged:

- *Actual expenditure* is the amount charged to the account, where known.
  Groq free-tier calls have actual expenditure of `$0`. Jev is not
  assumed free merely because Groq is free; its actual cost must come
  from the Jev billing route, not from token arithmetic.
- *Estimated equivalent cost* applies the reference paid pricing below
  to the recorded token consumption. It represents the estimated
  economic cost of equivalent usage, not actual billing.

**Pricing configuration** lives in `config/pricing.py` and is not
hardcoded elsewhere. Reference defaults:

| Model | Input (USD/1M tokens) | Output (USD/1M tokens) | Source |
|---|---|---|---|
| Groq GPT-OSS 120B | $0.15 | $0.60 | https://console.groq.com/docs/models |
| Jev 1.14.0 | $0.042 | $0.00 | https://vercel.com/ai-gateway/models/jev-1.14.0 |

**Historical compatibility.** Pre-existing benchmark rows carry no cost
fields; they remain missing (`None` / empty), never invented. Pricing
changes create a new `pricing_version` rather than rewriting history.

**Mode-aware accounting.** Mode A includes only the services it actually
invokes (Groq). Mode B accounts for its actual Jev and Groq usage. Mode C
accounts for Jev usage plus Groq advisory escalation reviews. Tokens are
never double-counted: each call's usage is accumulated once into the run
record.

## 5. Data collection and logging

`ExperimentLogger` appends every run to CSV (flat metrics) and JSONL
(verification detail + raw execution) — append-only, never edited.
Default location: `experiments/benchmark_results.{csv,jsonl}`; use
`--output experiments/<name>` to keep runs separate. Each record carries
`timestamp`, `run_id`, `mode`, `task_id`, `execution_type`, `repetition`,
`outcome`, metrics and `error` (if any).

Recorded outputs currently in the repository:

| Path | Content |
|---|---|
| `experiments/benchmark_results.{csv,jsonl}` | Phase 7 benchmark rows (mocked; note: mixes two code versions of the fake-client constants — see §7). |
| `experiments/demo_mocked/` | Clean single-version mocked benchmark output. |
| `experiments/results.csv` + `experiments/experiment_logs.jsonl` | First live Mode B run (2026-11-15), written by `scripts/run_hybrid.py`. |

## 6. Result interpretation considerations

- **Verification is not self-report.** Only the verified outcome counts;
  `agent_reported_success` is recorded but reported separately.
- **Provider buckets are never merged.** Groq and Jev tokens are reported
  separately; `combined` is the only summed figure.
- **Missing ≠ zero.** Absent metrics (e.g. Jev tokens in Mode A) stay
  `None` and are excluded from aggregates.
- **Mocked ≠ live.** Mocked rows use deterministic fake clients; they
  validate the pipeline, not API behaviour or cost. Never compare mocked
  and live rows as equivalent.
- **Small samples.** The dataset is 10 tasks; observations are illustrative,
  not statistically conclusive.
- **No fabricated claims.** Do not invent rows, statistics or reductions;
  the dashboard and scripts report only what the records contain.

## 7. Experimental limitations

- **Calibration data gap:** the mocked dataset never exercises escalation
  (all scripted Jev confidences are 0.95), so `--threshold-analysis`
  reports this explicitly as a data gap, not as evidence that the
  provisional defaults are correct.
- **Provisional thresholds:** Mode C defaults (`tool_confidence_threshold`
  0.60; completion band `[0.50, 0.70)`) come from the phase specification,
  not from measurement. Only one live Jev data point exists (confidence
  1.0; completion 0.03 → 0.75), so the band may escalate too often or too
  rarely in practice. Calibration requires live observations near the
  thresholds. The advisor's methodology notes on confidence vs.
  probability, calibration analyses and fair-comparison controls are
  preserved in `documentations/risks.md`.
- **Mixed mocked data:** the first 30 rows of `experiments/benchmark_results.*`
  were written by older fake-client constants (10/5/15 tokens, 0.2 s
  latencies); later rows use the current constants (20/10/30, 0.3 s). Use
  `experiments/demo_mocked/` for a clean single-version run, or
  `--output` per campaign. Do not hand-edit history.
- **No unit coverage for the API clients:** `GroqLLMClient` and
  `JevClient` are exercised only by live scripts that cost money;
  `tests/test_jev_client.py` is empty.
- **Live escalation unexercised:** the recorded live Mode C run succeeded
  end-to-end but Jev was fully confident both times, so the escalation
  branches have not fired against real API responses.
- **Loop-detection heuristic strictness:** termination requires
  `loop_probability >= 0.70` AND ≥ 2 tool calls AND normalised progress
  ≤ 0.20; the 0–5 progress scale is assumed, not verified.
- **Actual expenditure not available in mocked runs:** `groq_actual_cost`
  and `jev_actual_cost` are `$0` for mocked rows by construction. Live
  runs record actual billing only where the provider exposes it; otherwise
  the field stays missing rather than being estimated.
- **Jev pricing route must be verified:** the Jev input price assumes the
  Vercel AI Gateway `jev-1.14.0` route. Before relying on Jev cost
  figures, confirm the configured `JEV_MODEL` and endpoint match that
  pricing route; a different route may have different pricing.
- **Escalation advisory cost is estimated:** Mode C advisory Groq reviews
  are costed with a conservative token estimate unless the escalation
  response carries provider-reported usage.

## 8. Research-scope note

The system is an experimental prototype. Any performance statement must
cite recorded rows with their `execution_type`; claims about cost or
latency require live data, which has not yet been collected at scale.
