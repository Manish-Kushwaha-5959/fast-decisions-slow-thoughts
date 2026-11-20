# Research Improvement Plan — Fast Decisions, Slow Thoughts

**Status:** Investigation complete. This document is a plan only. No source
code, experiment data, or existing documentation was modified to produce it.
Implementation awaits approval.

**Purpose:** Give a future session enough verified detail to implement the
selected task without repeating this investigation.

---

## 0. The Plan in One Screen

- **Single most important research problem:** Mode C's uncertainty-based
  escalation — the project's distinguishing contribution — has never been
  observed to fire on real data, and the completion-first control-flow
  ordering in `agents/control_loop.py` structurally prevents it from firing
  when a low-confidence tool selection coincides with a completion signal.
- **Selected improvement:** Make Mode C escalation *observable and
  experimentally measurable* — add an opt-in control-flow ordering that
  evaluates tool-selection uncertainty before the completion break, then run a
  small, budgeted live experiment that captures real escalation events with
  provider-reported usage.
- **Why selected:** It targets the highest-value evidence gap (zero live
  escalations), is a targeted change rather than a rewrite, is achievable in
  three days, and produces a measurable, verifiable research finding.
- **Expected three-day deliverable:** One opt-in code path plus new unit
  tests, and a small set of live Mode C records containing genuine
  escalation events (`escalation_count > 0`) with measured advisory cost,
  latency and outcome — or a documented, well-designed negative result if no
  escalation is observed.

---

## 1. Executive Summary

The system implements three agent modes (A LLM-only, B LLM+Jev, C hybrid with
escalation) over one tool registry, one 10-task dataset, independent
verification and append-only logging. The pipeline is correct and runs
end-to-end against real Groq and Jev APIs. The central research claim — that
splitting fast control (Jev) from slow reasoning (Groq) with
*uncertainty-aware escalation* is viable — currently rests on a pipeline that
**works** but whose escalation mechanism has **never been exercised outside a
deterministic mocked unit test**.

The investigation found three things that matter:

1. **A confirmed control-flow property (not yet called a defect):** the
   completion break fires before the tool-selection escalation check. When a
   low-confidence tool choice coincides with a high completion signal and
   fulfilled tools, the loop terminates without escalating. This is observed in
   real data.
2. **A missing-evidence gap:** 0 escalations across 10 live Mode C runs (and 0
   in every mocked benchmark run, which is expected because the fake clients
   script confidence to 0.95).
3. **A documentation/data-integrity discrepancy:** `docs/FINDINGS.md` states
   the first live campaign had 14 rows with the Mode C
   `multi_knowledge_and_ticket` run absent; the actual CSV/JSONL contain 15
   rows in each campaign with all five tasks present.

The recommended task converts gap (2) into measured evidence by making the
escalation path reachable through an opt-in ordering, without changing default
behaviour.

---

## 2. Current Project State

### 2.1 Architecture (as implemented)

| Mode | File | Who decides what |
|---|---|---|
| A — LLM-only | `agents/baseline_agent.py` (`BaselineAgent.run`) | Groq does planning (implicit), tool selection, arguments, completion (`action=final`). |
| B — LLM + Jev | `agents/control_loop.py` (`ControlLoop.run`) + `agents/hybrid_agent.py` | Groq plans + writes arguments + final response; Jev selects tool, detects completion/loop, estimates progress. |
| C — Hybrid escalation | same as B + `agents/escalation_agent.py` (`EscalationAgent`) | As B; uncertain Jev decisions get an advisory Groq review; controller keeps final authority. |

Shared components: `tools/registry.py`, `evaluation/task_verifier.py`
(`TaskVerifier`), `evaluation/metrics.py`, `evaluation/economic_metrics.py`,
`evaluation/logger.py` (`ExperimentLogger`), `config/settings.py`,
`config/pricing.py`.

### 2.2 Escalation triggers (Mode C)

- **Tool selection:** selected-tool probability (or `Choice` confidence
  fallback) ≤ `TOOL_CONFIDENCE_THRESHOLD` (default 0.60).
- **Completion:** completion probability in
  `[COMPLETION_AMBIGUITY_LOWER, COMPLETION_AMBIGUITY_UPPER)` = `[0.50, 0.70)`.

Implemented in `agents/escalation_agent.py`
(`tool_selection_required`, `completion_required`, `escalate_tool_selection`,
`escalate_completion`). Thresholds are provisional defaults from
`config/settings.py` (`Settings.from_env`).

### 2.3 Recorded evidence (verified against the files, not the prose)

| Dataset | Path | Rows | Type |
|---|---|---|---|
| Clean historical mocked | `experiments/demo_mocked/` | 30 | mocked |
| Historical mixed mocked | `experiments/benchmark_results.*` (first 60) | 60 | mocked |
| Fresh post-Phase 11 mocked | `experiments/post_phase11_mocked/` | 30 | mocked |
| Live (appended) | `experiments/benchmark_results.*` | 30 | live |
| First historical live (Mode B) | `experiments/results.csv` + `experiments/experiment_logs.jsonl` | 1 | live |

Totals: 120 mocked + 31 live. The 30 fresh live rows are **two complete
15-run campaigns** of `scripts/run_live_validation.py`.

---

## 3. Architecture Investigation

### 3.1 Control-flow ordering (`agents/control_loop.py`)

Within one control-loop iteration (after `self.jev.evaluate_state(...)` and
recording the decision into `result.decision_history`), the ordering is:

1. **Completion (breaks the loop):** lines **384–391** —
   `if completion_probability >= self.completion_threshold and
   required_tools_fulfilled:` → `success = True`,
   `termination_reason = "jev_detected_completion"`, `break`.
2. Completion-but-no-evidence stop: lines **393–405** →
   `required_tools_not_fulfilled`.
3. **Mode C ambiguous-completion escalation:** lines **412–460**
   (`completion_required` → `escalate_completion`).
4. Loop guard: lines **465–483**.
5. Max-iterations guard: lines **485–492**.
6. Unauthorized-tool guard: lines **496–505**.
7. **Mode C tool-selection escalation:** lines **511–547**
   (`tool_selection_required` → `escalate_tool_selection`).

**Consequence:** any iteration where the completion break (line 385) fires
exits before line 511. The tool-selection escalation branch is therefore
unreachable whenever completion is detected *and* required tools are
fulfilled — regardless of tool confidence. This is observed in live data
(§4.3). Whether the ordering is *intended* is a design question; it is
reported here as observed behaviour, not as a proven defect.

### 3.2 Does the architecture reduce expensive Groq calls?

**No — as implemented, it increases them.** Mode A performs one Groq call per
iteration (selection + arguments + completion in one JSON action). Modes B/C
perform a planning Groq call, then *one Groq argument call per iteration*,
then a final-response Groq call — and add Jev calls on top. The live data
confirms this direction: second-campaign Groq tokens were A 8,177 vs B 18,236
vs C 15,634 (all Mode-A/B/C runs identical task sets). This is an important
framing constraint: the current split does **not** offload argument generation
(the expensive reasoning step) to Jev. This is a design/experimental-design
limitation, not a defect, and it bounds what the cost finding can claim.

### 3.3 Escalation usage capture

Live escalation usage **is** captured: `EscalationAgent._usage` reads
`response.input_tokens/output_tokens/total_tokens/latency_seconds`, and
`ControlLoop._record_escalation_usage` accumulates them into
`result.llm_*`. The 10-input/5-output token placeholder in
`evaluation/economic_metrics.py::_calculate_escalation_cost` applies only to
**mocked** escalation responses; a live escalation will already carry
provider-reported usage. No code change is needed to measure live escalation
cost — only to make escalation *reachable* and observed.

### 3.4 Mode A HTTP 400 failures (fair-comparison risk, not the selected task)

Two tasks — `kb_password_reset` and `multi_knowledge_and_ticket` — fail
identically in both campaigns with `GroqClientError: ... HTTP 400 ...
json_validate_failed` (`failed_generation: ""`). These are recorded verbatim,
not retried, and classified `unverifiable`. They are task-specific
provider rejections of the Mode A structured-output prompt
(`agents/baseline_agent.py` + `build_baseline_system_prompt` in
`agents/prompts.py` with `response_format={"type": "json_object"}`), not an
architecture failure. They reduce the live Mode A sample to 3/5 per campaign.
This is worth a separate future task but is **not** the highest-value one.

---

## 4. Experimental Evidence Audit

### 4.1 Live row count (verified against data)

`experiments/benchmark_results.jsonl` contains **exactly 30** rows with
`execution_type == "live"`, split into two campaigns by timestamp:

- Campaign 1: `2026-11-16 17:46:30 – 17:50:17` — **15 rows** (5 A, 5 B, 5 C).
- Campaign 2: `2026-11-16 17:52:53 – 17:56:42` — **15 rows** (5 A, 5 B, 5 C).

Each campaign covers the same 5 tasks
(`kb_password_reset`, `status_vpn`, `ticket_login_issue`,
`multi_status_and_knowledge`, `multi_knowledge_and_ticket`) across all modes.

### 4.2 Documentation discrepancy (confirmed)

`docs/FINDINGS.md` states: *"an earlier one at 17:46–17:49 (14 rows; its Mode C
`multi_knowledge_and_ticket` run is absent)"* and *"the reported one at
17:52–17:56 (15 rows)"*. Interpreting the two figures as 14 + 15 = 29 does not
match the stated total of 30, and the raw data contradicts both the "14 rows"
and "absent" claims:

- The first campaign contains **15** rows, not 14.
- The first campaign's Mode C `multi_knowledge_and_ticket` run **is present**
  (run `C-multi_knowledge_and_ticket-01-live-171bd8`, timestamp
  `17:50:17`).

**Conclusion:** the "14 rows / run absent" sentence in `docs/FINDINGS.md` is
incorrect. The correct statement is two complete 15-run campaigns (30 fresh
live rows), each with all five tasks × three modes. This is a
documentation-correction item, not a missing-record item. It should be fixed
when documentation is next edited (out of scope for this plan's code task).

### 4.3 Mode C live escalation behaviour (verified)

All 10 live Mode C runs have `escalation_count = 0`. Decision histories show:

| Run | Iteration | tool_confidence | completion_probability | escalated | Termination |
|---|---|---|---|---|---|
| `C-multi_knowledge_and_ticket-01-live-171bd8` | 3 | 0.42 (≤ 0.60) | 0.75 (≥ 0.70) | False | `jev_detected_completion` |
| `C-multi_knowledge_and_ticket-01-live-633857` | 3 | 0.20 (≤ 0.60) | 0.75 (≥ 0.70) | False | `jev_detected_completion` |

The same pattern appears in Mode B `multi_knowledge_and_ticket` rows
(confidences 0.28 / 0.36, completions 0.72 / 0.73), but Mode B has no
escalation path. Two other Mode C runs terminated via `repeated_tool_call`
(`kb_password_reset`) with confident (1.0) tool selections and low completion.

**Finding (observed, not manipulated):** tool-selection uncertainty occurred
at or below threshold in 2/10 live Mode C runs, but completion-first ordering
terminated both before the escalation check ran. The escalation branch's live
firing remains unmeasured.

### 4.4 Mocked escalation behaviour

`scripts/run_benchmark.py::_jev_sequence` scripts every Mode C run with
`tool_confidence=0.95` and completion 0.0 or 0.95 — both outside the triggers.
So mocked benchmark escalation is 0 **by construction**, not by evidence. The
branch is validated only by `tests/test_escalation.py::TestModeCEscalationBranch`
(scripted 0.30 confidence → escalation fires → `escalation_succeeded = True`)
and the equivalent class in `tests/test_logging_economic.py`.

### 4.5 Documentation inconsistency (test count)

`docs/FINDINGS.md` §10 says "201 mocked unit tests passing";
`docs/REPRODUCIBILITY.md` §3 says "Expected: **144 passed**". One of these is
stale. This must be reconciled before any acceptance criterion that cites a
test count (see §12). Do not trust either figure blindly — record the actual
count after implementation.

---

## 5. Confirmed Issues and Research Gaps

Classified per the working rules:

**Confirmed implementation property (not labelled a defect; design question):**
- Completion-first ordering in `agents/control_loop.py` (lines 384–391)
  short-circuits the tool-selection escalation branch (lines 511–547) when
  completion is signalled with evidence. Observed live (§4.3). The *behaviour*
  is confirmed; whether it is *intended* is unresolved by the code.

**Missing experimental evidence (the primary gap):**
- No live escalation event has ever been recorded. Escalation frequency,
  advisory cost, latency overhead and effect on outcomes are unmeasured on
  real data.

**Experimental-design weaknesses:**
- Mocked Mode C confidence is scripted at 0.95 → escalation never exercised.
- Live sample is n = 5 per mode per campaign; no confidence intervals.
- The architecture does not reduce Groq calls (§3.2), so the cost-efficiency
  hypothesis is not exercised by the current design.

**Confirmed documentation/data-integrity issues (corrections, not code):**
- `docs/FINDINGS.md` "14 rows / Mode C run absent" contradicts the data
  (§4.2).
- Test-count inconsistency: 201 (FINDINGS) vs 144 (REPRODUCIBILITY) (§4.5).

**Potential future research opportunities (out of scope here):**
- Mode A HTTP 400 prompt-rejection investigation (§3.4).
- Jev confidence calibration against decision correctness.
- Reducing Groq calls by moving argument generation to Jev.

---

## 6. Prioritised Research Opportunities

| # | Opportunity | Value | Effort | In 3 days? |
|---|---|---|---|---|
| 1 | **Make Mode C escalation observable and measurable** (opt-in ordering + live experiment) | Very high — closes the flagship evidence gap | Medium | **Yes** |
| 2 | Fix Mode A HTTP 400 prompt rejections for a fairer live comparison | Medium — improves fairness; task-specific | Low–Medium | Yes, but lower research yield |
| 3 | Jev confidence calibration against decision correctness | High — answers RQ4 | High (needs per-decision ground truth) | No |
| 4 | Reduce Groq calls (Jev generates arguments) | High — tests cost hypothesis | Very high (architecture change) | No |
| 5 | Reconcile documentation + test-count inconsistencies | Low (hygiene) | Very low | Yes (fold in) |

Opportunity 1 has the greatest research value relative to effort and is the
only one that both (a) makes the core contribution measurable and (b) fits the
three-day window without an architectural rewrite. It is selected.

---

## 7. Selected Priority Task

**Task name:** *Observable Mode C escalation experiment.*

**Goal:** Demonstrate and measure real Mode C uncertainty escalation by:

1. Adding a documented, **opt-in** control-flow ordering
   (`escalate_before_completion`, default `False`) so that a low-confidence
   tool selection can trigger the Groq advisory review even when a completion
   signal is present; and
2. Running a small, budgeted live campaign with that ordering enabled to
   capture genuine escalation events, provider-reported advisory cost,
   latency, and their effect on verified outcomes.

**Non-goals:** no change to default Mode B/C behaviour; no change to the
evidence gate or allowed-tools rules; no rewrite of the agent architecture; no
edit of historical records; no retries.

**Valid outcomes:** either escalation fires and is measured, or it does not —
in which case the experiment is reported as a designed negative result with
the conditions under which no escalation occurred.

---

## 8. Technical Implementation Plan

### 8.1 Files to modify

| File | Change |
|---|---|
| `agents/control_loop.py` | Add `escalate_before_completion: bool = False` to `ControlLoop.__init__`. When `True` **and** `self.escalation_agent is not None`, evaluate `tool_selection_required(decision)` and, if triggered, run `escalate_tool_selection(...)` **before** the completion break; record escalation fields; then fall through to the existing completion logic (with the escalated selection preserved). Default path must be byte-for-byte identical to today. |
| `agents/hybrid_agent.py` | Add `escalate_before_completion: bool = False` to `HybridAgent.__init__`; pass it to `ControlLoop(...)`. |
| `scripts/run_live_validation.py` | Add `--escalate-before-completion` flag; when set, construct Mode C agents with the ordering enabled and stamp an experiment label/notes so the records are distinguishable from default-order runs. |
| `tests/test_escalation.py` | Add `TestEscalationBeforeCompletion` class (see §9). |

**Do not** modify: `evaluation/*`, `config/*`, `tools/*`, `agents/escalation_agent.py`,
`agents/baseline_agent.py`, existing data under `experiments/`.

### 8.2 Safe reordering design (must preserve the evidence gate)

When `escalate_before_completion=True` and the tool-selection trigger fires:

1. Run `escalate_tool_selection` (advisory only) and record
   `decision_type="tool_selection"`, `escalated=True`,
   `groq_recommendation`, `final_decision`, `escalation_succeeded` on
   `result.decision_history[-1]`.
2. Adopt Groq's recommendation **only if** it is an authorised tool (the
   existing `EscalationAgent` already guarantees this); otherwise retain Jev's
   authorised pick.
3. **Then** evaluate the completion break exactly as today. Completion still
   requires `completion_probability ≥ threshold` **and** every required tool
   has valid evidence. Escalation must never mark a task complete or authorise
   an unlisted tool.
4. Note: if completion fires immediately after an escalation, record that the
   escalated selection was *advisory and unused* (the loop completed before
   executing it). This distinction must be visible in analysis so we do not
   overstate escalation impact.

### 8.3 Prerequisites

- Working live credentials in `.env` (`GROQ_API_KEY`, `TYPESAFE_API_KEY`).
  (The prior campaigns were executed in an environment where this is
  permitted; confirm before the live phase.)
- Baseline test run must be green **before** changes:
  `python -m pytest tests/ -q` — record the actual pass count (do not assume
  144 or 201; see §4.5).

---

## 9. Three-Day Execution Schedule

### Day 1 — Investigation and preparation
- Re-read `agents/control_loop.py`, `agents/escalation_agent.py`,
  `agents/hybrid_agent.py`, `tests/test_escalation.py`.
- Record the current green baseline: `python -m pytest tests/ -q` (capture the
  exact pass/fail count).
- Confirm `.env` has live keys and `verify_jev_pricing_route(settings.jev_model)`
  returns compatible.
- Design the exact diff for `ControlLoop.__init__`/`run` (opt-in branch) and
  write the new test skeletons (do not run live yet).
- **Deliverable:** written diff plan + baseline test count.

### Day 2 — Implementation and validation (mocked only, free)
- Implement `escalate_before_completion` in `control_loop.py` and thread it
  through `hybrid_agent.py`.
- Add `--escalate-before-completion` to `scripts/run_live_validation.py`
  (dry behaviour: flag only changes agent construction; still requires `--yes`
  and respects `--max-live-runs`).
- Add tests:
  - `test_escalation_before_completion_triggers_on_low_confidence_with_completion`
    (scripted tc=0.30, cp=0.95, required tool fulfilled → escalation fires;
    completion still verified; assert `escalated=True` on the low-confidence
    iteration).
  - `test_escalation_before_completion_respects_evidence_gate`
    (scripted tc=0.30, cp=0.95, required tool **not** fulfilled → no false
    completion).
  - `test_escalation_before_completion_unauthorised_recommendation_rejected`
    (Groq returns a non-allowed tool → falls back to Jev's authorised pick).
  - `test_default_order_unchanged` (parameter omitted → identical decision
    history to current behaviour for the same script).
- Run the full suite: `python -m pytest tests/ -q`. All pre-existing tests must
  pass; new tests must pass.
- Run the mocked benchmark to confirm no regression:
  `python scripts/run_benchmark.py --mode all --repetitions 1 --output experiments/phase14_mocked_check`
  (fresh output dir; do not append to canonical files during validation).
- **Deliverable:** green suite + one mocked confirmation run in a scratch dir.

### Day 3 — Experimentation and evidence (live, budgeted)
- Execute the controlled live campaign with the opt-in ordering:
  `python scripts/run_live_validation.py --escalate-before-completion --max-live-runs 15 --yes`
  (5 tasks × 3 modes; only Mode C differs behaviourally from the prior
  campaign).
- Verify the output:
  - `python scripts/run_benchmark.py --threshold-analysis` over the new rows
    (or a small read-only script) to summarise escalations.
  - Inspect `experiments/benchmark_results.jsonl` for the new live rows:
    confirm `escalation_count`, `escalation_succeeded_count`, advisory
    token/latency/cost, and `decision_history` escalation fields.
- **Deliverable:** a written mini-findings note in a scratch file (not
  `docs/FINDINGS.md`) reporting: number of live escalations, their trigger
  conditions, advisory cost/latency, and outcome impact — or a documented
  negative result.

---

## 10. Live Experiment Protocol

- **Script:** `scripts/run_live_validation.py` (reuse — do not create a new
  harness).
- **Tasks:** the existing `DEFAULT_TASK_IDS` (5 representative tasks). The
  `multi_knowledge_and_ticket` task is the most likely to produce a
  low-confidence tool selection (observed 0.42 / 0.20 live).
- **Modes:** A, B, C (only C runs with `escalate_before_completion=True`).
- **Runs:** 15 total (5 tasks × 3 modes × 1 repetition), hard-capped at
  `--max-live-runs 15`.
- **Flags:** `--yes` (mandatory confirmation), `--max-live-runs 15`,
  `--escalate-before-completion`.
- **No retries:** a failed provider call is recorded as failed/unverifiable and
  the campaign continues (existing behaviour).
- **Isolation of evidence:** new rows append to the canonical
  `experiments/benchmark_results.{csv,jsonl}` with
  `execution_type="live"`. To distinguish this campaign from the two prior
  default-order campaigns, either (a) run into a fresh `--output` directory if
  the script supports it, or (b) record the campaign start/end timestamps and
  filter by them in analysis. Do **not** edit prior rows.
- **Budget:** estimated equivalent cost is on the order of the prior campaign
  (~$0.005–0.015 total at reference pricing; Jev dominates B/C token volume).
  Actual expenditure remains unmeasured (`None`) unless a billing source is
  supplied — do not write `$0`.

**Pre-flight:** confirm `verify_jev_pricing_route(settings.jev_model)` is
compatible and that both API keys validate, so the campaign does not abort
mid-run.

---

## 11. Evaluation Metrics

Collect and report, per the existing logger schema:

- **Escalation frequency:** `escalation_count`, `tool_selection_escalations`,
  `completion_escalations`, `escalation_frequency` (per iteration and per run).
- **Escalation success:** `escalation_succeeded_count` / `escalation_count`.
- **Advisory overhead:** the Groq tokens and latency attributable to
  escalation reviews (already folded into `llm_*`; isolate by summing per-run
  deltas against the default-order baseline, or by reading
  `decision_history` usage where recorded).
- **Outcome effect:** verified success rate for runs that escalated vs runs
  that did not; whether Groq's recommendation differed from Jev's pick.
- **Cost:** estimated Groq/Jev/total cost with escalation included
  (provider-reported on live rows).
- **Latency:** total and per-provider latency for escalated vs non-escalated
  runs.

Explicitly distinguish: **measured** (live, provider-reported) vs
**estimated/placeholder** (mocked) values, and **advisory-and-used** vs
**advisory-and-unused** escalations (§8.2 step 4).

---

## 12. Acceptance Criteria

**Functional**
1. Default behaviour (`escalate_before_completion=False`) is unchanged — same
   termination reasons and decision history for identical scripted inputs.
2. With the flag enabled, a low-confidence tool selection with a completion
   signal triggers `escalate_tool_selection` and records the escalation fields.
3. The evidence gate and allowed-tools restriction are never bypassed; an
   escalation never completes a task without evidence and never authorises an
   unlisted tool.
4. Groq's advisory usage is accumulated once into the run's `llm_*` metrics.

**Testing**
1. `python -m pytest tests/ -q` passes; no pre-existing test is weakened or
   removed.
2. New tests in §9 cover the four cases listed.
3. The mocked benchmark produces deterministic, verified outcomes with the
   default flag.

**Experimental**
1. The live campaign completes within the 15-run budget with no retries.
2. Either ≥ 1 real escalation is captured with full fields, **or** the
   negative result is documented with the conditions (confidences/completions)
   under which no escalation occurred.
3. New rows are appended with `execution_type="live"` and Phase 11 cost fields.

**Data integrity**
1. CSV and JSONL remain consistent (same `run_id`, same field values).
2. Prior records are unmodified; the new campaign is identifiable by timestamp
   or output directory.
3. `decision_history` on escalated entries carries `decision_type`,
   `escalated`, `escalation_reason`, `groq_recommendation`, `final_decision`,
   `escalation_succeeded`.

**Research evidence**
1. A quantified statement of escalation frequency, advisory cost/latency, and
   outcome effect (or a rigorous negative result).
2. Clear separation of measured vs estimated figures.

**Documentation**
1. A short methodology note added wherever the implementer is authorised to
   write (scratch/analysis file until a documentation pass is approved).
2. The `docs/FINDINGS.md` "14 rows" discrepancy and the test-count
   inconsistency (§4.2, §4.5) are flagged for correction — not silently
   rewritten.

---

## 13. Expected Research Contribution

**Able to demonstrate after completion:**
- That Mode C's advisory escalation can be exercised against real APIs, with
  provider-reported cost and latency — closing the "escalation unmeasured"
  gap.
- A measured relation between Jev's tool-selection confidence and the
  escalation trigger, on real Jev outputs.
- The cost/latency overhead of escalation and whether it changes verified
  outcomes.

**Still cannot claim:**
- That the hybrid architecture is cheaper, faster or more reliable than
  Mode A (the live sample is small and the design still increases Groq calls;
  §3.2).
- That the provisional thresholds (0.60 / [0.50, 0.70)) are calibrated.
- That actual billing matches estimated cost (no billing source measured).

---

## 14. Risks and Contingency Plan

| Risk | Likelihood | Contingency |
|---|---|---|
| Live Jev is confidently 1.0 again → no escalation fires | Medium–High | Report as a designed negative result; record the confidence distribution; recommend threshold lowering or harder tasks as a follow-up (do not fake escalation). |
| Opt-in reordering accidentally changes default behaviour | Low | Guard with `test_default_order_unchanged`; keep the flag default `False`; diff decision histories. |
| Evidence gate regression | Low | Explicit tests for unauthorised recommendation and missing-evidence completion (§9). |
| Live keys unavailable / rate-limited | Medium | Do Day 2 fully mocked; if live is blocked, deliver code+tests and the mocked analysis, and document the live gap (as the project did previously). |
| Advisory recommendation always equals Jev's pick → low analytical value | Medium | Report honestly; the measurement of overhead and trigger rate is still a finding. |
| Test-count/campaign-count docs conflict confuses acceptance | Medium | Record actual counts during Day 1/2; cite measured numbers, not the stale doc numbers. |

---

## 15. What Must Not Be Changed

- `evaluation/*` (logger, metrics, verifier, economic metrics).
- `config/pricing.py`, `config/settings.py` thresholds.
- `tools/*`, `agents/baseline_agent.py`, `agents/escalation_agent.py`.
- Any file under `experiments/` that already exists (no editing/rewriting
  history; new rows are append-only, new campaigns go to a fresh output dir if
  possible).
- Default Mode B/C behaviour (the new flag defaults to `False`).
- Retry behaviour (no automatic retries that could distort benchmarking).

---

## 16. Final Checklist

- [ ] Baseline test run recorded (exact pass count, not the stale 144/201).
- [ ] `escalate_before_completion` added to `ControlLoop` and threaded through
      `HybridAgent`, default `False`.
- [ ] `--escalate-before-completion` added to `run_live_validation.py`.
- [ ] Four new tests added and passing; full suite green.
- [ ] Default-order regression test proves unchanged decision history.
- [ ] Mocked confirmation run done in a scratch output dir (no canonical
      pollution).
- [ ] Live campaign executed within 15-run budget, no retries.
- [ ] New live rows verified in CSV and JSONL with escalation fields and
      Phase 11 cost fields.
- [ ] Escalation frequency / cost / latency / outcome analysed, measured vs
      estimated clearly separated.
- [ ] Negative result documented honestly if no escalation fired.
- [ ] `docs/FINDINGS.md` "14 rows" error and the 144-vs-201 test-count
      inconsistency flagged for correction.
- [ ] No architectural rewrite; no historical data edited; no unnecessary scope.

---

*Every quantitative statement above is traceable to the named file, function or
recorded row; unavailable figures are labelled unavailable rather than
estimated. Mocked and live evidence are kept strictly separate.*
