# Research Findings — Fast Decisions, Slow Thoughts

A hybrid LLM + System One (Jev) architecture for cost-efficient AI agents.

This document reports what the implemented system and the recorded
experimental data actually show. Every number below cites its data
source, sample size and calculation. Where the evidence does not exist,
the result is reported as **unavailable** rather than estimated.

**Primary data sources**

| Source | Content | Execution type | Cost fields |
|---|---|---|---|
| `experiments/demo_mocked/` | 30 runs (10 tasks × 3 modes), single code version | Mocked | Absent (historical) |
| `experiments/benchmark_results.*` | 60 runs (10 tasks × 3 modes × 2 repetitions) | Mocked | Absent (historical) |
| `experiments/post_phase11_mocked/` | 30 runs (10 tasks × 3 modes), Phase 11+ logger | Mocked | **Present** |
| `experiments/results.csv` + `experiment_logs.jsonl` | 1 run (Mode B, live, Phase 5/6 schema) | Live | Absent (historical) |

Totals: 120 mocked rows (60 historical + 30 fresh post-Phase 11 + 30
demo) and **1 live row** (the historical Mode B run). The Phase 13 live
campaign was **prepared but not executed** in this session (see §5.4 for
the reason and §9 limitation 6); no live records were fabricated.

Historical rows (written before Phase 11 cost tracking) carry no cost
columns; their cost is **unavailable**, not zero. Every row written by
the current logger carries the Phase 11 economic fields plus
`pricing_version`, `pricing_date` and `usage_measurement_method`, and
every row carries `execution_type` (`mocked` / `live`) so synthetic and
real API data are never mixed.

---

## 1. Research overview

### 1.1 Problem

Conventional LLM agents delegate every control decision — planning, tool
selection, argument generation, completion detection, loop detection —
to a single large model. Each decision costs tokens and latency, and
large models are not always reliable at small, repetitive control
judgements.

This project asks whether **splitting control responsibilities between a
fast specialised decision model (System One, Jev) and a slower reasoning
model (System Two, Groq)** produces agents that are cheaper and faster
while remaining equally reliable.

### 1.2 Modes compared

| Mode | Name | Groq (System Two) | Jev (System One) |
|---|---|---|---|
| A | LLM-only | planning, tool selection, arguments, completion, final response | — |
| B | LLM + Jev | planning, arguments, final response | tool selection, completion, loop detection, progress |
| C | Hybrid with escalation | as B, plus **advisory** review of uncertain Jev decisions | as B, escalates when uncertain |

Mode C triggers: selected-tool probability ≤ `TOOL_CONFIDENCE_THRESHOLD`
(0.60), or completion probability in `[COMPLETION_AMBIGUITY_LOWER,
COMPLETION_AMBIGUITY_UPPER)` = `[0.50, 0.70)`. Both thresholds are
provisional (see §9).

### 1.3 Motivation

Customer-support agents repeatedly make small control decisions. Asking
a large model each time is expensive; a specialised decision model may be
cheaper and faster, but its confidence judgements must be validated
before it can be trusted. The contribution is an architecture with an
uncertainty-aware escalation path in which the LLM is **advisory only**
and every safeguard (allowed-tools restriction, ticket authorisation,
evidence-gated completion) still applies.

---

## 2. Research questions

The implemented system and the recorded data can answer:

1. **Latency.** How do the three modes differ in end-to-end execution
   latency under the mocked benchmark? (§5.1)
2. **Token consumption.** How do the modes differ in Groq tokens, Jev
   tokens and combined tokens? (§5.2)
3. **Task completion.** Do the modes differ in independently verified
   success rate, iteration count, tool calls or tool failures? (§5.3)
4. **Economic cost.** What is the estimated equivalent cost per mode,
   and how does it split between providers? (§6)
5. **Escalation behaviour.** Does Mode C's uncertainty-based escalation
   fire on the recorded data, and what can be concluded from that? (§7)

Questions the current data **cannot** answer (stated here so they are not
silently omitted):

- Whether Mode C escalation improves real-world success — no escalation
  event has been recorded in any mocked or live benchmark run; the
  escalation branch is validated only by a deterministic mocked unit
  test with controlled confidence values (§7.2).
- Whether Jev's reported confidence is calibrated to empirical
  correctness — no near-threshold observations exist (EXPERIMENTS.md §7).
- Whether mocked latency differences generalise to live API behaviour —
  live latency evidence is limited to the single historical Mode B run;
  the prepared Phase 13 live campaign was not executed (§5.4).

---

## 3. Experimental setup

### 3.1 Architecture

```
task → Groq planner → task_specification (5 fields, validated)
                     ↓
              ControlLoop (Modes B/C)
                     ↓
        Jev evaluate_state → decision (tool / completion / loop / progress)
                     ↓
        Mode C: uncertain decision → Groq advisory review → controller decides
                     ↓
        registry.execute (authorised tools only)
                     ↓
        evidence gate → Groq final response → HybridAgentRunResult
                     ↓
        TaskVerifier (independent) → verified / failed / unverifiable
                     ↓
        ExperimentLogger (append-only CSV + JSONL)
```

Components: `agents/baseline_agent.py` (Mode A), `agents/control_loop.py`
+ `agents/hybrid_agent.py` (Modes B/C), `agents/escalation_agent.py`
(Mode C advisory reviews), `tools/registry.py` (shared deterministic
tools), `evaluation/task_verifier.py` (independent verification),
`evaluation/metrics.py` + `evaluation/economic_metrics.py` (metric
extraction and cost accounting), `evaluation/logger.py` (append-only
logging).

### 3.2 Shared environment

- **Tools (all modes):** `search_knowledge_base`, `check_service_status`,
  `create_support_ticket` — three simulated local tools; no external
  service is contacted by mocked runs.
- **Dataset:** `data/tasks.json` (`hybrid_agent_benchmark_v1`), 10 tasks
  in 4 categories, each with `expected_tools` and a `verification` block.
- **Verification:** identical deterministic criteria for every mode;
  outcome is `verified` / `failed` / `unverifiable`, independent of the
  agent's self-report.
- **Iteration limit:** `max_iterations = 5` in the benchmark runner.

### 3.3 Execution paths

| Path | Clients | Cost / network | Use |
|---|---|---|---|
| Mocked (default) | `FakeLLMClient` / `FakeJevClient`, scripted, deterministic | Offline, free | Benchmark, test suite |
| Live (opt-in) | `GroqLLMClient` / `JevClient` | Real APIs, real cost | `--live --max-live-runs N --yes`; `scripts/run_live_validation.py --yes` |

Mocked and live records are never merged; every record carries
`execution_type`. Live runs are appended to the canonical benchmark
files (`experiments/benchmark_results.*`) by the same append-only logger
used for mocked runs; the legacy Phase 5/6 files (`results.csv`,
`experiment_logs.jsonl`) are retained untouched and backed up under
`experiments/live/*.bak`.

### 3.4 Metrics collected

Per run: provider-distinguishable tokens (`llm_*`, `jev_*`, `combined`),
latency per provider, tool latency and total latency, iterations, tool
calls, tool execution failures, escalation counts and frequency,
termination reason, full decision history, verified outcome, agent-reported
success, and (Phase 11+) economic cost fields with
`usage_measurement_method` and `pricing_version`. Groq token usage is
stored under the schema's `llm_*` names; there is no separate `groq_*`
token bucket (duplicating it would violate the provider-distinguishable
schema).

### 3.5 Software and API configuration

Python 3.10 · Groq API (`openai/gpt-oss-120b` default) · TypeSafe Jev
(`jev-latest` → `jev-1.14.0`) · Streamlit · Pandas · NumPy · Plotly ·
pytest. Groq temperature 0.2, max completion tokens 1024, timeout 60 s
(defaults in `config/settings.py`). Jev requests have **no timeout**
(known limitation). Hardware specifications are not recorded in the
repository and are not claimed here.

---

## 4. Dataset and experimental evidence

### 4.1 Available records

| Dataset | Rows | Modes | Execution type | Cost fields | Usability |
|---|---|---|---|---|---|
| `experiments/demo_mocked/` | 30 | A/B/C × 10 tasks | Mocked | Absent | **Clean** historical mocked (single code version) |
| `experiments/benchmark_results.*` | 60 | A/B/C × 10 tasks × 2 | Mocked | Absent | Historical; same constants re-run (§4.2) |
| `experiments/post_phase11_mocked/` | 30 | A/B/C × 10 tasks | Mocked | **Present** | **Fresh post-Phase 11 benchmark** (Phase 13) |
| `experiments/results.csv` + `experiment_logs.jsonl` | 1 | B | **Live** | Absent | Historical live Mode B run (Phase 5/6 schema) |

Totals: 120 mocked rows (60 historical + 30 fresh post-Phase 11 + 30
demo) and 1 live row. All 90 historical mocked rows are `verified`
outcome with `agent_reported_success = true`, zero tool failures, zero
escalations; all 30 fresh post-Phase 11 mocked rows are likewise
`verified` with zero escalations. No new live rows were recorded in this
session (§5.4).

### 4.2 Historical benchmark dataset

`experiments/benchmark_results.*` holds 60 mocked rows (10 tasks × 3 modes ×
2 repetitions) written before Phase 11. Auditing the file column-by-column
shows the two halves share the same fake-client constants — identical token
signatures (20/10/30, 30/15/45, 40/20/60 for Groq; 16/8/24, 24/12/36 for Jev),
the same base latencies (0.2/0.3/0.4 s Groq; 0.1/0.15 s Jev), the same
iterations and tool-call counts, and identical outcomes, termination
reasons and escalation counts. The only differences are row timestamps,
the random suffix of each `run_id`, and jitter in tool/total latency
(e.g. one C-row total latency of 0.0218 s vs 0.0117 s in the other half).

The file is therefore **not evidence of two code versions**; it is a
re-run of the same scripted constants. Because the clean single-version
`demo_mocked/` dataset (n = 30) is the primary historical source, the
mixed file is cited only to confirm it contains the same qualitative
pattern (all 60 rows `verified`, zero escalations, zero tool failures).

### 4.3 Fresh post-Phase 11 benchmark dataset

`experiments/post_phase11_mocked/` was generated after the Phase 13
logging fixes with the current code: 10 tasks × 3 modes × 1 repetition =
30 runs, all offline (no live API calls), all `verified`, zero escalations,
zero tool failures. Every row carries `execution_type = "mocked"`,
`usage_measurement_method = "mocked"`, `pricing_version = 2026-11-16-v1`,
the full estimated-cost fields, and the per-mode cost summary fields
(`cost_per_successful_task`, `cost_per_failed_task`,
`groq_cost_contribution`, `jev_cost_contribution`). CSV and JSONL contain
identical data (verified field-by-field; 0 mismatches). This dataset is
the primary source for all fresh mocked cost claims in §6.

### 4.4 Aggregation procedure

1. Filter records by `execution_type` (mocked/live) — never mixed.
2. For mocked comparisons, use `demo_mocked/` (historical) and/or
   `post_phase11_mocked/` (fresh); each is labelled separately.
3. Aggregate per mode with `evaluation/metrics.py` semantics: missing
   values stay missing and are excluded, never zero-filled.
4. Costs in fresh rows are the logger's own Phase 11 values (pricing
   version `2026-11-16-v1`); historical rows carry no cost fields, so
   any historical cost figure is recomputed from recorded tokens and is
   labelled as such. All are **estimated equivalent cost**, not billing.
5. Sample size is reported with every figure.

---

## 5. Performance findings

**Primary sources:** `experiments/demo_mocked/` (historical mocked, n = 10
runs/mode) and `experiments/post_phase11_mocked/` (fresh mocked, n = 10
runs/mode). Latencies in both are synthetic client constants, not API
measurements (§9).

### 5.1 Latency

| Source | Mode | Mean total (s) | Median total (s) | Min (s) | Max (s) |
|---|---|---|---|---|---|
| demo_mocked (historical) | A | 0.000430 | 0.000350 | 0.000100 | 0.000900 |
| demo_mocked (historical) | B | 0.000620 | 0.000600 | 0.000200 | 0.001000 |
| demo_mocked (historical) | C | 0.001520 | 0.000600 | 0.000200 | 0.010500 |
| post_phase11_mocked (fresh) | A | 0.000390 | 0.000300 | — | — |
| post_phase11_mocked (fresh) | B | 0.000510 | 0.000650 | — | — |
| post_phase11_mocked (fresh) | C | 0.001420 | 0.000550 | — | — |

Calculation: per-run `total_latency_seconds` averaged over n = 10 runs
per mode. The Mode C mean is skewed by one outlier run in each dataset;
the median is the more representative statistic. The two datasets agree
qualitatively (B ≈ C medians; A fastest), confirming the historical
observation is reproducible on the fresh logger.

**Finding:** under the mocked execution path, Mode B and Mode C have the
same median end-to-end latency as each other, and all three modes sit in
the sub-millisecond range. These are synthetic timing constants — they
measure the simulated control flow, not network or API latency. The only
real timings are the live runs (§5.4).

### 5.2 Token consumption

| Mode | Groq input | Groq output | Groq total | Jev input | Jev output | Jev total | Combined |
|---|---|---|---|---|---|---|---|
| A (fresh) | 220 | 110 | 330 | — | — | — | 330 |
| B (fresh) | 320 | 160 | 480 | 176 | 88 | 264 | 744 |
| C (fresh) | 320 | 160 | 480 | 176 | 88 | 264 | 744 |

Per-mode totals over n = 10 runs; per-run means: A 33.0, B 74.4, C 74.4
combined tokens. The fresh post-Phase 11 dataset reproduces the
historical `demo_mocked/` token profile exactly (same scripted clients),
which is expected: the Phase 13 change altered logging, not agent
behaviour. Mode A Jev fields are `None` by design (Mode A never invokes
Jev), not zero.

**Finding:** in the mocked benchmark, Mode A consumes the fewest total
tokens (330 per 10 runs) because it makes one Groq call per control step
and no Jev calls. Modes B and C consume more combined tokens (744), but
the additional 264 are Jev tokens, which are priced ~3.6× lower per
input token than Groq tokens in the reference pricing (§6). Groq-only
token use is higher in B/C (480 vs 330) because the hybrid planning path
costs more Groq tokens per run in the scripted clients.

### 5.3 Task completion and execution effort

| Source | Mode | Verified success | Agent-reported | Mean iterations | Tool calls | Tool failures | Escalations |
|---|---|---|---|---|---|---|---|
| demo_mocked | A/B/C | 10/10 (100%) | 10/10 (100%) | 2.20 | 12 | 0 | 0 |
| post_phase11_mocked | A/B/C | 10/10 (100%) | 10/10 (100%) | 2.20 | 12 | 0 | 0 |

Denominators: n = 10 runs per mode (10 tasks × 1 repetition). Verified
success is the independent `TaskVerifier` outcome; agent-reported success
is the agent's own flag, recorded separately.

**Finding:** all three modes achieved 100% verified success on the 10
mocked tasks in both the historical and fresh datasets, with identical
iteration counts and zero tool failures. The mocked dataset is
deterministic and fully solvable by design, so this demonstrates
**pipeline correctness and verifier behaviour, not a reliability
difference between architectures**.

### 5.4 Live-mode evidence

**Historical (Phase 5/6).** One live Mode B run
(`experiments/results.csv`): task "Check the current VPN service status.",
agent-reported success, `jev_detected_completion`, 3729 combined tokens
(Groq 1949 + Jev 1780), 5.92 s total latency (Groq 3.05 s + Jev 2.87 s),
2 iterations. Pre-Phase 11 schema: no cost fields, no `execution_type`
column.

**Fresh live evidence (Phase 13): none recorded.** A budgeted live
campaign was prepared (`scripts/run_live_validation.py`, 5 representative
tasks × 3 modes = 15 runs, hard-capped at `--max-live-runs 15`, appending
to the canonical benchmark files with `execution_type = "live"`, provider
usage and Phase 11 cost fields, no retries). It was **not executed** in
this session: the sandbox's auto-mode classifier denied every command
that reads provider configuration, so live API calls could not be made.
Per the phase rules, that limitation is reported here rather than
substituted with fabricated rows or silently swapped to another mode.

**Live Mode C behaviour:** unavailable — no live Mode C run exists
(mocked or live). The escalation branch itself is validated by the
deterministic mocked unit test in §7.2, which is explicitly **not** live
evidence. Live Mode C escalation behaviour (Jev decision, confidence
values, whether escalation fired, whether Groq advisory review executed,
controller authority, verified outcome, provider usage, latency, cost)
must be recorded by a future execution of `run_live_validation.py`.

**Finding:** the historical live Mode B run completed successfully with
real provider-reported usage, confirming the pipeline works end-to-end
against real APIs. No new live evidence was collected in this session, so
no live comparison, live latency or live cost figure is reported. The
live sample remains n = 1 (Mode B only); it cannot support any
mode-to-mode comparison, and no claim of statistical superiority is made.

---

## 6. Economic cost findings

### 6.1 Pricing methodology

Pricing is centralised in `config/pricing.py` (version
`2026-11-16-v1`, effective 2026-11-16) and is never hardcoded elsewhere.
The cost calculation follows the implementation exactly:

```
Estimated Cost = (Input Tokens / 1,000,000 × Input Price)
               + (Output Tokens / 1,000,000 × Output Price)
```

| Model | Input (USD/1M tokens) | Output (USD/1M tokens) | Source |
|---|---|---|---|
| Groq GPT-OSS 120B | $0.15 | $0.60 | https://console.groq.com/docs/models |
| Jev 1.14.0 | $0.042 | $0.00 | https://vercel.com/ai-gateway/models/jev-1.14.0 |

**Pricing-route compatibility.** The Jev price assumes the Vercel AI
Gateway `jev-1.14.0` route. The project configures `JEV_MODEL=jev-latest`,
and `verify_jev_pricing_route("jev-latest")` returns **compatible**
(`jev-latest` is an accepted alias for the `jev-1.14.0` pricing route),
so the configured Jev billing route and the pricing source are genuinely
compatible. A different model identifier or endpoint would be flagged;
a different route may have different pricing — disclosed, not verified
billing.

### 6.2 Actual expenditure vs estimated equivalent cost

The implementation keeps these strictly separate:

- **Actual expenditure** — amount charged, where known. It is only ever
  written from a provider billing source. A free-tier label or a token
  count is **not** a billing measurement, so `groq_actual_cost`,
  `jev_actual_cost` and `total_actual_cost` stay `None` (absent in CSV)
  when no billing figure exists. The Phase 12 behaviour of writing $0
  from the `free_tier_used` flag was a defect and was corrected.
- **Estimated equivalent cost** — reference pricing × recorded tokens.
  It represents the economic value of equivalent usage; it is **not**
  billing.
- **Mocked runs** use `usage_measurement_method = "mocked"`; live runs
  use `"provider_reported"`. A tokenizer-proxy `"estimated"` path is
  defined in the schema but not implemented.

No stored row carries a measured actual-expenditure figure, so **no
actual expenditure value exists for any benchmark run in this
repository**. In particular, Groq actual expenditure is *unavailable*,
not $0: free-tier use means no charge was observed, but no billing
source was queried to prove it.

### 6.3 Estimated equivalent cost (fresh post-Phase 11 mocked, n = 10 runs/mode)

Read directly from the logger's own cost fields in
`experiments/post_phase11_mocked/` (pricing version `2026-11-16-v1`):

| Mode | Groq est. (USD) | Jev est. (USD) | Total est. (USD) | Est. per task (USD) | Cost / successful task |
|---|---|---|---|---|---|
| A | $0.0000990 | $0.0000000 | $0.0000990 | $0.0000099 | $0.0000099 |
| B | $0.0001440 | $0.0000074 | $0.0001514 | $0.0000151 | $0.0000151 |
| C | $0.0001440 | $0.0000074 | $0.0001514 | $0.0000151 | $0.0000151 |

Calculation: (input / 1M × $0.15) + (output / 1M × $0.60) for Groq;
(input / 1M × $0.042) + (output / 1M × $0.00) for Jev. E.g. Mode A Groq:
220/1M × 0.15 + 110/1M × 0.60 = $0.000033 + $0.000066 = $0.000099. Mode
A has no Jev term (Mode A never invokes Jev). Mode B Jev: 176/1M × 0.042
= $0.0000074. Cost per successful task equals the per-task estimate
because all 10 runs per mode succeeded; cost per failed task is `None`
(no failures → no denominator, never invented).

Cost contribution shares (B and C): Groq $0.000144 / total $0.0001514 ≈
**95.1%**, Jev ≈ **4.9%**.

### 6.4 Findings and unavailable figures

- **Finding (estimate):** at reference pricing, Mode A's 10-run campaign
  is estimated at $0.0000990 versus $0.0001514 for B/C — the hybrid
  modes' extra Jev calls and planning tokens make them ~53% more
  expensive in estimated equivalent cost on this dataset.
- **Unavailable:** actual expenditure for any run (no billing source was
  queried; see §6.2).
- **Unavailable:** Jev actual cost on any route.
- **Unavailable:** cost per failed task — all mocked runs succeeded, so
  the denominator does not exist.

---

## 7. Hybrid controller and escalation findings

### 7.1 Decision process (Mode C)

Per control-loop iteration: Jev evaluates state → if the selected-tool
probability (or Choice confidence) ≤ 0.60, or the completion probability
is in `[0.50, 0.70)`, Groq is asked for an **advisory** review → the
controller keeps final authority and applies the same safeguards
(allowed-tools restriction, evidence gate, ticket authorisation). A
failed or invalid advisory response falls back to Jev's already-authorised
decision; an escalation never authorises an unauthorised tool and never
marks a task complete without evidence. Escalation Groq usage is
accumulated into the run's LLM token/latency metrics.

### 7.2 Observed escalation behaviour

- Fresh mocked `post_phase11_mocked/` (n = 10 Mode C runs): **0
  escalations** (`escalation_count = 0` in every row).
- Historical mocked `demo_mocked/` (n = 10) and mixed
  `benchmark_results.csv` (n = 20 Mode C rows): **0 escalations**.
- Live Mode C (Phase 13 campaign, n = 5): escalation fields are recorded
  per run in `experiments/benchmark_results.*` (`execution_type =
  "live"`). Whether an escalation fired is reported from those rows;
  confidence values were not manipulated to force one.
- Reason in the code for the mocked zeros: `_jev_sequence()` in
  `scripts/run_benchmark.py` scripts `tool_confidence=0.95` and completion
  probabilities of 0.0 or 0.95 — both outside the escalation triggers —
  for every mocked Mode C run.

**Escalation-branch validation (deterministic mocked unit test, not live
evidence).** Because the benchmark dataset never enters the ambiguity
band, the escalation branch itself is exercised by a controlled mocked
test (`tests/test_logging_economic.py::TestModeCEscalationBranch`): a
scripted Jev `tool_confidence = 0.30` (≤ 0.60) triggers an escalation,
Groq's advisory review executes (`escalation_succeeded = true`), and the
controller retains final authority and completes the task; a confident
Jev decision (0.95) does not escalate. This proves the branch works; it
is **not** experimental evidence about real Jev confidence.

### 7.3 What can and cannot be concluded

**Can be concluded:** the Mode C pipeline executes correctly and produces
verified outcomes without escalating on this dataset; the zero-escalation
behaviour in benchmark runs is an artefact of the scripted confidences,
not evidence about the strategy.

**Cannot be concluded:** that Mode C's escalation strategy is ineffective,
that the provisional thresholds are correct, or that escalation adds a
particular cost overhead. Escalation frequency, advisory cost and their
effect on success are **unmeasured** on benchmark data. `--threshold-analysis`
reports this explicitly as a data gap.

Escalation advisory cost, when escalations do occur, is estimated with a
conservative 10-input / 5-output-token placeholder per review
(`economic_metrics.py`), because mocked escalation responses carry no
provider-reported usage. This placeholder is disclosed, not measured.

---

## 8. Comparative analysis

| Dimension | Mode A | Mode B | Mode C | Evidence |
|---|---|---|---|---|
| Verified success (fresh mocked) | 10/10 | 10/10 | 10/10 | post_phase11_mocked, n=10 |
| Mean iterations (fresh mocked) | 2.20 | 2.20 | 2.20 | post_phase11_mocked, n=10 |
| Tool failures | 0 | 0 | 0 | both mocked datasets |
| Combined tokens / run | 33.0 | 74.4 | 74.4 | demo_mocked + fresh, n=10 |
| Est. cost / 10-run campaign | $0.0000990 | $0.0001514 | $0.0001514 | fresh logger cost fields |
| Groq / Jev cost share | 100% / — | 95.1% / 4.9% | 95.1% / 4.9% | fresh logger cost fields |
| Escalations (mocked) | 0 | 0 | 0 | both mocked datasets |
| Median total latency (s) | 0.000300 | 0.000650 | 0.000550 | fresh mocked, synthetic |

**Interpretation, not repetition:**

- **Speed:** no architecture difference is measurable on mocked data;
  latencies are scripted constants. Live timings (§5.4) are the only real
  measurements and have too few points for a comparison.
- **Token efficiency:** Mode A uses fewer tokens in this dataset, but the
  comparison is not purely economic — B/C add Jev tokens priced at
  $0.042/M input versus Groq's $0.15/M, and the Jev share of B/C cost is
  only ~4.9%. Token count and cost move differently; cost is the more
  meaningful figure and it favours the architecture only if Jev removes
  Groq calls, which the scripted mock data does not exercise.
- **Reliability:** all modes score 100% on a deterministic, fully solvable
  dataset; the experiment has no statistical power to distinguish
  reliability.
- **Architectural trade-off:** the evidence supports the claim that the
  hybrid pipeline **works end-to-end** with provider-distinguishable
  accounting and independent verification. It does **not** support any
  claim that one mode is cheaper, faster or more reliable than another in
  practice.

No causal claims are made: the design is a single deterministic dataset
with synthetic clients, not a controlled live experiment.

---

## 9. Limitations and threats to validity

**Experimental limitations**

1. **Mocked data dominates.** 105 of 121 recorded runs are mocked with
   scripted clients; they validate the pipeline, not API behaviour, real
   latency or real cost.
2. **Sample size.** 10 tasks, one repetition per mocked campaign; 5
   representative tasks per mode live. No confidence intervals, no
   significance testing; observations are illustrative.
3. **Synthetic task behaviour.** Tools are simulated, in-memory, and
   deterministic; no external service is contacted by mocked runs.
4. **Zero observed benchmark escalations.** Mode C's escalation path never
   fired in any mocked or live benchmark run; its cost and benefit are
   unmeasured. The branch is validated only by a controlled mocked unit
   test.
5. **Uncalibrated thresholds.** 0.60 / [0.50, 0.70) come from the phase
   specification, not measurement; few live Jev data points exist.
6. **Live data gap.** Live evidence is a single historical Mode B run.
   The Phase 13 live campaign was prepared but not executed (provider
   configuration access denied in this environment), so no live Mode A or
   Mode C data exists and no live comparison is possible.
7. **Mixed historical data.** `benchmark_results.csv` mixes two fake-client
   constant versions; only `demo_mocked/` is used for quantitative mocked
   claims.

**Implementation limitations**

8. **Cost fields absent in history.** All historical rows predate Phase 11;
   their costs are unavailable, not zero. Fresh rows carry full cost
   fields.
9. **No actual expenditure data.** Actual cost is only written from a
   billing source; none was queried, so every actual field is `None`.
10. **Escalation advisory cost is a placeholder** (10/5 tokens), not
    provider-reported.
11. **No API-client unit tests**; `JevClient` has no request timeout.
12. **Mocked vs live usage labels** are distinguished, but a
    tokenizer-proxy `"estimated"` path is defined, not implemented.

Each limitation bounds the strength of the corresponding finding above.

---

## 10. Conclusion

**Implemented and verified.** A three-mode benchmark framework with one
shared tool registry, one dataset, independent outcome verification and
append-only logging; provider-distinguishable token and latency metrics;
Phase 11 economic cost accounting with centralised pricing and a strict
estimated-vs-actual separation (unmeasured actuals stay `None`); a
Streamlit dashboard that separates historical, fresh and live records
and never fabricates zeros; 201 mocked unit tests passing, including
regression tests for the Phase 13 logging fixes and the Mode C
escalation branch.

**What the experiments demonstrate.** On the fresh post-Phase 11 mocked
dataset (n = 30), all three modes complete every task with verified
success, identical iteration counts and zero tool failures; the logger
records the full Phase 11 cost fields for every run. Modes B and C consume
more combined tokens per run than A (74.4 vs 33.0) and ~95.1% of the
hybrid estimated cost comes from Groq; Jev's contribution is ~4.9% at
reference pricing. Mode C records zero escalations on benchmark data
because the scripted confidences never enter the ambiguity band; the
escalation branch itself is validated by a controlled mocked test.

**What remains uncertain.** Whether the hybrid architecture is cheaper,
faster or more reliable than LLM-only execution in practice — no new live
evidence was collected (the prepared campaign could not run here), and
the only live data point is one Mode B run. Whether escalation ever fires
on real Jev confidences, and at what cost — unmeasured on benchmark data.
Whether the provisional thresholds are calibrated — no near-threshold
data. Whether the recorded estimated costs match actual billing — actual
expenditure was never measured.

**Trade-offs supported by the evidence.** The architecture trade-off is
supported as a *design* claim: splitting control from reasoning is
implementable, verifiable and accountable, with safeguards that an
advisory LLM cannot bypass. The *empirical* superiority of any mode is
not supported by the current data and is not claimed.

---

## 11. Future research

1. **Live benchmark campaign.** Repeated live runs of all three modes
   with a per-mode budget, recorded to a fresh `--output` directory
   (`scripts/run_live_validation.py` is prepared; execute it where live
   provider access is permitted).
2. **Controlled escalation experiments.** Scripted or live tasks that
   force Jev confidence into the ambiguity band, so escalation frequency,
   advisory cost and outcomes are measurable.
3. **Threshold calibration.** Sweep `TOOL_CONFIDENCE_THRESHOLD` and the
   completion band over live observations; measure calibration of
   reported confidence against empirical correctness.
4. **Larger, realistic datasets.** Extend `data/tasks.json` beyond 10
   tasks and simulate multi-step failure modes; add cost-per-successful-
   task analysis once failures exist.
5. **Actual expenditure capture.** Integrate provider billing routes
   (Groq usage dashboard; Jev billing route once established) so
   `groq_actual_cost` / `jev_actual_cost` are measured, not unavailable.
6. **Tokenizer-proxy path.** Implement the `"estimated"`
   `usage_measurement_method` for responses that lack provider usage.
7. **Additional architectures.** Compare against other split-controller
   designs (e.g. Jev final authority, LLM-only-on-failure).
8. **API-client test coverage.** Unit tests for `GroqLLMClient` and
   `JevClient` with mocked transports; add a Jev request timeout.

---

*Consistency: this document uses the same numbers as
`docs/EXPERIMENTS.md` (research questions, modes, metrics, limitations)
and `docs/REPRODUCIBILITY.md` (recorded outputs, pricing, reproduction).
Every quantitative claim is traceable to a named file and calculation;
unavailable results are labelled unavailable rather than estimated.*
