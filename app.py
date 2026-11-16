"""
Streamlit research dashboard for "Fast Decisions, Slow Thoughts".

A hybrid LLM + System One (Jev) architecture for cost-efficient AI agents.

Design principles
-----------------
- Presentation layer only: every metric is computed by the project's
  evaluation modules (``evaluation/metrics.py``,
  ``evaluation/economic_metrics.py``) or read from recorded experiment
  data. Nothing is reimplemented or hardcoded here.
- Mocked and live execution are kept strictly separate; the dashboard
  never merges them in one comparison.
- Missing values render as "N/A" and are excluded from charts; nothing
  is fabricated as zero.
- No execution happens on page load; live API calls are opt-in per click.

Sections
--------
Overview · Experiment Comparison · Cost Analysis · Performance Analysis ·
Run Experiment · Experiment History · Architecture
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to path (app.py is at the project root)
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import project modules
from agents.baseline_agent import BaselineAgent  # noqa: E402
from agents.hybrid_agent import HybridAgent  # noqa: E402
from config.pricing import get_pricing_config  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402
from models.llm_client import GroqLLMClient  # noqa: E402
from models.jev_client import JevClient  # noqa: E402

# Verification outcome constants
VERIFIED = "verified"
FAILED = "failed"
UNVERIFIABLE = "unverifiable"

MODES = ["A", "B", "C"]
MODE_NAMES = {
    "A": "LLM-only",
    "B": "LLM + Jev",
    "C": "Hybrid + escalation",
}

# ── Design tokens ────────────────────────────────────────────
# Categorical slots from the dataviz reference palette (validated
# adjacent + all-pairs for the first three slots, light mode).
C_COLORS = {
    "A": "#2a78d6",   # blue   — slot 1
    "B": "#eb6834",   # orange — slot 2
    "C": "#1baf7a",   # aqua   — slot 3
}
STATUS_COLORS = {
    "verified": "#1baf7a",
    "failed": "#e34948",
    "unverifiable": "#8a8a8a",
}

# Typography / layout
PLOT_HEIGHT = 320
PLOT_TEMPLATE = "plotly_white"

TASK_OPTIONS = [
    "Check the current VPN service status.",
    "Is the internet service working right now?",
    "Why did my payment portal transaction fail?",
    "How do I reset my account password?",
    "My Wi-Fi keeps dropping. What troubleshooting steps should I try first?",
    "Check whether the payment portal is available.",
    "Please create a support ticket for this issue: I cannot log in to my account even though my password is correct. Priority medium.",
    "The VPN is down and I have an urgent deadline. Please create a high priority support ticket for the VPN outage.",
    "Check whether the VPN is working, and if it is degraded or down, find the troubleshooting article for VPN access problems.",
    "Find the troubleshooting steps for slow system performance, then create a low priority support ticket about the slow performance issue.",
]


# ═══════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════

def load_benchmark_data() -> list[dict]:
    """Load benchmark results from CSV and JSONL, joined by run_id.

    Sources, in order:
    - ``experiments/benchmark_results.*`` — historical (pre-Phase 11)
      rows plus any live rows appended by the canonical live logger.
    - ``experiments/post_phase11_mocked/`` — the fresh post-Phase 11
      mocked benchmark; included so the dashboard can show the new
      cost-annotated records alongside the historical ones.

    Rows from the second source are tagged ``dataset = "post_phase11"``
    so historical and fresh records stay distinguishable. Falls back to
    ``experiments/demo_mocked/`` only when the main CSV is absent or
    empty, so the dashboard keeps working on a fresh clone. Mocked and
    live records are never filtered out here — the pages apply that
    separation themselves.
    """
    csv_path = PROJECT_ROOT / "experiments" / "benchmark_results.csv"
    jsonl_path = PROJECT_ROOT / "experiments" / "benchmark_results.jsonl"
    demo_dir = PROJECT_ROOT / "experiments" / "demo_mocked"
    fresh_dir = PROJECT_ROOT / "experiments" / "post_phase11_mocked"

    def _read_csv(path):
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as file:
            return [dict(row) for row in csv.DictReader(file)]

    def _read_jsonl(path):
        records = []
        if not path.exists():
            return records
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _join(rows, jsonl_records):
        by_id = {rec.get("run_id"): rec for rec in jsonl_records}
        merged = []
        for row in rows:
            record = dict(row)
            jr = by_id.get(record.get("run_id", ""))
            if jr:
                record["verification"] = jr.get("verification", {})
                record["raw_execution"] = jr.get("raw_execution", {})
            merged.append(record)
        return merged

    all_records = _join(_read_csv(csv_path), _read_jsonl(jsonl_path))

    fresh_csv = fresh_dir / "benchmark_results.csv"
    fresh_jsonl = fresh_dir / "benchmark_results.jsonl"
    if fresh_csv.exists():
        fresh = _join(_read_csv(fresh_csv), _read_jsonl(fresh_jsonl))
        for record in fresh:
            record.setdefault("dataset", "post_phase11")
        all_records.extend(fresh)

    # Fallback for a fresh clone with no main results yet.
    if not all_records and demo_dir.exists():
        demo_csv = demo_dir / "benchmark_results.csv"
        if demo_csv.exists():
            with open(demo_csv, "r", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    row["execution_type"] = "mocked"
                    all_records.append(row)

    return all_records


def load_live_runs() -> list[dict]:
    """Load recorded live runs.

    The canonical live destination is ``experiments/benchmark_results.*``
    (rows with ``execution_type == "live"``, written by the Phase 11+
    logger with cost fields). The legacy Phase 5/6 file
    ``experiments/results.csv`` is also loaded for completeness and
    normalised to the benchmark schema; its pre-Phase 11 rows carry no
    cost fields, which stay missing rather than zero.
    """
    live_rows: list[dict] = []

    # Canonical live rows from the benchmark logger.
    for record in load_benchmark_data():
        if str(record.get("execution_type", "")).lower() == "live":
            live_rows.append(record)

    # Legacy live rows (Phase 5/6 schema).
    live_path = PROJECT_ROOT / "experiments" / "results.csv"
    if live_path.exists():
        with open(live_path, "r", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                live_rows.append({
                    "timestamp": row.get("timestamp"),
                    "run_id": row.get("run_id", ""),
                    "mode": row.get("mode"),
                    "task_id": row.get("task"),
                    "execution_type": "live",
                    "outcome": (
                        "verified" if row.get("success") in
                        ("True", "true", "1") else "unverifiable"
                    ),
                    "iterations": row.get("iterations"),
                    "llm_input_tokens": row.get("llm_input_tokens"),
                    "llm_output_tokens": row.get("llm_output_tokens"),
                    "llm_total_tokens": row.get("llm_total_tokens"),
                    "jev_input_tokens": row.get("jev_input_tokens"),
                    "jev_output_tokens": row.get("jev_output_tokens"),
                    "jev_total_tokens": row.get("jev_total_tokens"),
                    "combined_tokens": row.get("combined_tokens"),
                    "llm_latency_seconds": row.get("llm_latency_seconds"),
                    "jev_latency_seconds": row.get("jev_latency_seconds"),
                    "tool_latency_seconds": row.get("tool_latency_seconds"),
                    "total_latency_seconds": row.get("total_latency_seconds"),
                    "termination_reason": row.get("termination_reason"),
                    "agent_reported_success": row.get("success"),
                    "dataset": "legacy_live",
                })

    return live_rows


# ═══════════════════════════════════════════════════════════════
# Metric helpers — thin wrappers over the evaluation modules
# ═══════════════════════════════════════════════════════════════

def _safe_float(value: Any) -> Optional[float]:
    """Parse a CSV value to float; None when missing/invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Parse a CSV value to int; None when missing/invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def get_mode_success_rates(records: list[dict]) -> dict:
    """Per-mode verified / agent-reported success counts."""
    modes = {
        m: {"verified_succ": 0, "verified_fail": 0, "unverifiable": 0,
            "agent_succ": 0, "run_count": 0}
        for m in MODES
    }
    for record in records:
        mode = record.get("mode", "")
        if mode not in modes:
            continue
        modes[mode]["run_count"] += 1

        verification = record.get("verification", {})
        outcome = verification.get("outcome", "") if isinstance(verification, dict) else ""
        if outcome == VERIFIED:
            modes[mode]["verified_succ"] += 1
        elif outcome == FAILED:
            modes[mode]["verified_fail"] += 1
        else:
            modes[mode]["unverifiable"] += 1

        if str(record.get("agent_reported_success", "")).lower() == "true":
            modes[mode]["agent_succ"] += 1
    return modes


def get_latency_data(records: list[dict]) -> dict:
    """Per-mode list of total latency values (seconds)."""
    latencies = {m: [] for m in MODES}
    for record in records:
        mode = record.get("mode", "")
        if mode not in latencies:
            continue
        latency = _safe_float(record.get("total_latency_seconds"))
        if latency is not None:
            latencies[mode].append(latency)
    return latencies


def get_token_data(records: list[dict]) -> dict:
    """Per-mode token lists (Groq / Jev / combined)."""
    tokens = {
        m: {"llm_total": [], "jev_total": [], "combined": []}
        for m in MODES
    }
    for record in records:
        mode = record.get("mode", "")
        if mode not in tokens:
            continue
        try:
            tokens[mode]["llm_total"].append(
                float(record.get("llm_total_tokens", 0) or 0)
            )
            tokens[mode]["jev_total"].append(
                float(record.get("jev_total_tokens", 0) or 0)
            )
            tokens[mode]["combined"].append(
                float(record.get("combined_tokens", 0) or 0)
            )
        except (ValueError, TypeError):
            pass
    return tokens


def get_escalation_data(records: list[dict]) -> dict:
    """Per-mode escalation counts from the CSV columns."""
    escalations = {
        m: {"count": 0, "tool_selection": 0, "completion": 0, "succeeded": 0}
        for m in MODES
    }
    for record in records:
        mode = record.get("mode", "")
        if mode not in escalations:
            continue
        count = _safe_int(record.get("escalation_count")) or 0
        tool_sel = _safe_int(record.get("tool_selection_escalations")) or 0
        completion = _safe_int(record.get("completion_escalations")) or 0
        succeeded = _safe_int(record.get("escalation_succeeded_count")) or 0
        escalations[mode]["count"] += count
        escalations[mode]["tool_selection"] += tool_sel
        escalations[mode]["completion"] += completion
        escalations[mode]["succeeded"] += succeeded
    return escalations


def get_cost_data(records: list[dict]) -> dict:
    """Per-mode economic cost data (Phase 11).

    Cost fields exist only in rows written by Phase 11+ code. Historical
    rows carry no cost columns, so every figure stays missing rather than
    fabricated as zero.
    """
    costs = {
        m: {"runs": 0, "groq_estimated": 0.0, "jev_estimated": 0.0,
            "total_estimated": 0.0, "groq_actual": None, "jev_actual": None,
            "total_actual": None, "pricing_version": None,
            "has_cost_data": False, "usage_methods": set()}
        for m in MODES
    }
    for record in records:
        mode = record.get("mode", "")
        if mode not in costs:
            continue
        costs[mode]["runs"] += 1

        estimated = _safe_float(record.get("total_estimated_cost"))
        if estimated is not None:
            costs[mode]["has_cost_data"] = True
            costs[mode]["total_estimated"] += estimated
            costs[mode]["groq_estimated"] += (
                _safe_float(record.get("groq_estimated_cost")) or 0.0
            )
            costs[mode]["jev_estimated"] += (
                _safe_float(record.get("jev_estimated_cost")) or 0.0
            )

            # Actual expenditure is only summed from measured values;
            # missing actuals stay None (never a fabricated 0.0).
            groq_act = _safe_float(record.get("groq_actual_cost"))
            jev_act = _safe_float(record.get("jev_actual_cost"))
            total_act = _safe_float(record.get("total_actual_cost"))
            if groq_act is not None:
                costs[mode]["groq_actual"] = (
                    (costs[mode]["groq_actual"] or 0.0) + groq_act
                )
            if jev_act is not None:
                costs[mode]["jev_actual"] = (
                    (costs[mode]["jev_actual"] or 0.0) + jev_act
                )
            if total_act is not None:
                costs[mode]["total_actual"] = (
                    (costs[mode]["total_actual"] or 0.0) + total_act
                )

            version = record.get("pricing_version")
            if version:
                costs[mode]["pricing_version"] = version

        method = record.get("usage_measurement_method")
        if method:
            costs[mode]["usage_methods"].add(method)
    return costs


def compute_mode_aggregates(records: list[dict]) -> dict:
    """Compute the full per-mode aggregate table used across pages.

    Returns {mode: {...}} with success rates, latency stats, token means,
    escalation counts and cost aggregates. Missing values stay None.
    """
    mode_stats = get_mode_success_rates(records)
    latencies = get_latency_data(records)
    tokens = get_token_data(records)
    escalations = get_escalation_data(records)
    costs = get_cost_data(records)

    from statistics import median

    aggregates: dict[str, dict] = {}
    for mode in MODES:
        stats = mode_stats[mode]
        lats = latencies.get(mode, [])
        combined = tokens.get(mode, {}).get("combined", [])
        llm = tokens.get(mode, {}).get("llm_total", [])
        jev = tokens.get(mode, {}).get("jev_total", [])
        cost = costs[mode]

        aggregates[mode] = {
            "runs": stats["run_count"],
            "verified_successes": stats["verified_succ"],
            "verified_failures": stats["verified_fail"],
            "unverifiable": stats["unverifiable"],
            "agent_reported_successes": stats["agent_succ"],
            "verified_success_rate": (
                stats["verified_succ"] / stats["run_count"]
                if stats["run_count"] else None
            ),
            "agent_reported_success_rate": (
                stats["agent_succ"] / stats["run_count"]
                if stats["run_count"] else None
            ),
            "latency_mean": sum(lats) / len(lats) if lats else None,
            "latency_median": median(lats) if lats else None,
            "latency_min": min(lats) if lats else None,
            "latency_max": max(lats) if lats else None,
            "combined_tokens_mean": (
                sum(combined) / len(combined) if combined else None
            ),
            "llm_tokens_mean": sum(llm) / len(llm) if llm else None,
            "jev_tokens_mean": sum(jev) / len(jev) if jev else None,
            "combined_tokens_total": sum(combined) if combined else None,
            "escalation_count": escalations[mode]["count"],
            "tool_selection_escalations": escalations[mode]["tool_selection"],
            "completion_escalations": escalations[mode]["completion"],
            "escalation_succeeded": escalations[mode]["succeeded"],
            "has_cost_data": cost["has_cost_data"],
            "groq_estimated_cost": cost["groq_estimated"] if cost["has_cost_data"] else None,
            "jev_estimated_cost": cost["jev_estimated"] if cost["has_cost_data"] else None,
            "total_estimated_cost": cost["total_estimated"] if cost["has_cost_data"] else None,
            "groq_actual_cost": cost["groq_actual"] if cost["has_cost_data"] else None,
            "total_actual_cost": cost["total_actual"] if cost["has_cost_data"] else None,
            "avg_cost_per_task": (
                cost["total_estimated"] / cost["runs"]
                if cost["has_cost_data"] and cost["runs"] else None
            ),
            "pricing_version": cost["pricing_version"],
            "usage_methods": sorted(cost["usage_methods"]) if cost["usage_methods"] else None,
        }
    return aggregates


# ═══════════════════════════════════════════════════════════════
# Shared UI primitives
# ═══════════════════════════════════════════════════════════════

def render_section_header(title: str, subtitle: str = "") -> None:
    """Render a clean section header without decorative icons."""
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)


def render_data_source_banner(records: list[dict]) -> None:
    """Show how many mocked/live records the current view is based on."""
    mocked = sum(
        1 for r in records
        if str(r.get("execution_type", "")).lower() == "mocked"
    )
    live = sum(
        1 for r in records
        if str(r.get("execution_type", "")).lower() == "live"
    )
    st.info(
        f"**Data source:** `experiments/benchmark_results.csv` + `.jsonl` — "
        f"{len(records)} runs ({mocked} mocked, {live} live). "
        "Mocked and live runs are never mixed in one comparison."
    )


def render_na(value: Any, fmt: str = "{:.3f}") -> str:
    """Format a number, or render 'N/A' when the value is missing."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return fmt.format(value)
    return str(value)


def configure_plotly_chart(fig: go.Figure, title: str) -> None:
    """Apply the dashboard's shared chart styling."""
    fig.update_layout(
        template=PLOT_TEMPLATE,
        title=dict(text=title, font=dict(size=14), x=0.5),
        height=PLOT_HEIGHT,
        margin=dict(l=40, r=20, t=48, b=40),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(size=12),
    )


def render_cost_disclaimer() -> None:
    """Standard cost-labelling disclaimer (Phase 11)."""
    st.caption(
        "Estimated equivalent cost applies reference paid pricing to recorded "
        "tokens; it is not actual billing. Actual expenditure is tracked "
        "separately (Groq free tier = $0; Jev actual must come from its billing "
        "route). Historical rows predating cost tracking show no cost figures."
    )


# ═══════════════════════════════════════════════════════════════
# Page: Overview
# ═══════════════════════════════════════════════════════════════

def render_overview(records: list[dict], aggregates: dict) -> None:
    st.markdown(
        "## Fast Decisions, Slow Thoughts",
        unsafe_allow_html=False,
    )
    st.markdown(
        "**A hybrid LLM + System One (Jev) architecture for cost-efficient "
        "AI agents** — an experimental research prototype for a final-year "
        "project."
    )

    render_section_header(
        "Research objective",
        "Does splitting control decisions between a fast specialised model "
        "(Jev) and a slower reasoning model (Groq) produce cheaper, more "
        "reliable agents than LLM-only execution?",
    )

    # Execution modes
    render_section_header("Execution modes")
    mode_cols = st.columns(3)
    for idx, mode in enumerate(MODES):
        with mode_cols[idx]:
            st.markdown(f"**Mode {mode} — {MODE_NAMES[mode]}**")
    st.caption(
        "Mode A: Groq controls every decision. "
        "Mode B: Jev selects tools, detects completion and loops; Groq plans "
        "and writes arguments. Mode C: as B, with advisory Groq review of "
        "uncertain Jev decisions."
    )

    # Key benchmark statistics
    render_section_header(
        "Benchmark statistics",
        "Recorded runs in `experiments/benchmark_results.*` (mocked and live "
        "shown separately).",
    )
    mocked = [r for r in records if str(r.get("execution_type")).lower() == "mocked"]
    live = [r for r in records if str(r.get("execution_type")).lower() == "live"]

    stat_cols = st.columns(4)
    with stat_cols[0]:
        st.metric("Recorded runs", len(records))
    with stat_cols[1]:
        st.metric("Mocked runs", len(mocked))
    with stat_cols[2]:
        st.metric("Live runs", len(live))
    with stat_cols[3]:
        verified = sum(
            1 for r in records
            if isinstance(r.get("verification"), dict)
            and r["verification"].get("outcome") == VERIFIED
        )
        rate = verified / len(records) * 100 if records else None
        st.metric("Verified success", render_na(rate, "{:.1f}%"))

    # Per-mode headline metrics (mocked only, for comparability)
    render_section_header(
        "Mocked benchmark headline metrics",
        "Clean single-version dataset `experiments/demo_mocked/` — 10 tasks × "
        "3 modes. See Experiment Comparison for the full table.",
    )
    demo_records = _load_demo_mocked()
    if demo_records:
        demo_agg = compute_mode_aggregates(demo_records)
        cols = st.columns(3)
        for idx, mode in enumerate(MODES):
            agg = demo_agg[mode]
            with cols[idx]:
                st.markdown(f"**Mode {mode}** — {MODE_NAMES[mode]}")
                st.metric(
                    "Verified success",
                    render_na(
                        agg["verified_success_rate"], "{:.0%}"
                    ) if agg["verified_success_rate"] is not None else "N/A",
                    f"{agg['verified_successes']}/{agg['runs']} runs",
                )
                st.metric(
                    "Mean latency",
                    render_na(agg["latency_mean"], "{:.4f} s"),
                )
                st.metric(
                    "Mean combined tokens",
                    render_na(agg["combined_tokens_mean"], "{:.1f}"),
                )
    else:
        st.info(
            "No mocked benchmark data found. Run "
            "`python scripts/run_benchmark.py --mode all --output experiments/demo_mocked` "
            "to generate it."
        )

    # Economic cost summary (only when data exists)
    cost_agg = {m: aggregates[m] for m in MODES if aggregates[m]["has_cost_data"]}
    if cost_agg:
        render_section_header(
            "Economic cost summary (estimated equivalent cost)",
            "Phase 11 accounting. Available only for runs written by "
            "cost-annotated code.",
        )
        cost_rows = []
        for mode in MODES:
            agg = aggregates[mode]
            if not agg["has_cost_data"]:
                continue
            cost_rows.append({
                "Mode": f"Mode {mode}",
                "Runs": agg["runs"],
                "Groq est. (USD)": f"{agg['groq_estimated_cost']:.6f}",
                "Jev est. (USD)": f"{agg['jev_estimated_cost']:.6f}",
                "Total est. (USD)": f"{agg['total_estimated_cost']:.6f}",
                "Avg/task (USD)": render_na(agg["avg_cost_per_task"], "{:.6f}"),
            })
        if cost_rows:
            st.dataframe(pd.DataFrame(cost_rows), hide_index=True, width="stretch")
            render_cost_disclaimer()
    else:
        with st.expander("Economic cost data", expanded=False):
            st.markdown(
                "No recorded run in `experiments/benchmark_results.*` carries "
                "Phase 11 cost fields — every stored row predates cost "
                "tracking. Cost figures are therefore **unavailable** for the "
                "historical dataset rather than being shown as $0.00. "
                "A fresh mocked run produces cost-annotated rows; see the "
                "Cost Analysis section."
            )

    render_data_source_banner(records)


def _load_demo_mocked() -> list[dict]:
    """Load the clean single-version mocked dataset if present."""
    demo_csv = PROJECT_ROOT / "experiments" / "demo_mocked" / "benchmark_results.csv"
    if not demo_csv.exists():
        return []
    with open(demo_csv, "r", encoding="utf-8") as file:
        return [dict(row) for row in csv.DictReader(file)]


# ═══════════════════════════════════════════════════════════════
# Page: Experiment Comparison
# ═══════════════════════════════════════════════════════════════

def render_experiment_comparison(records: list[dict]) -> None:
    st.markdown("## Experiment Comparison")
    st.markdown(
        "Modes A, B and C compared on the same 10-task dataset with the same "
        "deterministic verification criteria. Use the filters to separate "
        "mocked from live execution."
    )

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        mode_filter = st.radio(
            "Mode", ["All", "A", "B", "C"], index=0, horizontal=True,
            help="Filter benchmark results by execution mode.",
        )
    with col2:
        exec_type = st.radio(
            "Execution type", ["All", "Mocked", "Live"], index=0, horizontal=True,
            help="Filter by execution type (mocked or live).",
        )
    with col3:
        dataset_filter = st.selectbox(
            "Dataset",
            ["All", "Historical mocked", "Post-Phase 11 mocked"],
            index=0,
            help="Separate the historical benchmark rows from the fresh "
                 "post-Phase 11 cost-annotated rows. Live rows are "
                 "selected via Execution type.",
        )

    def _dataset_match(record):
        is_fresh = record.get("dataset") == "post_phase11"
        if dataset_filter == "Historical mocked":
            return not is_fresh
        if dataset_filter == "Post-Phase 11 mocked":
            return is_fresh
        return True

    filtered = records
    if mode_filter != "All":
        filtered = [r for r in filtered if r.get("mode") == mode_filter]
    if exec_type != "All":
        filtered = [
            r for r in filtered
            if str(r.get("execution_type", "")).lower() == exec_type.lower()
        ]
    filtered = [r for r in filtered if _dataset_match(r)]

    if not filtered:
        st.info("No records match the selected filters.")
        return

    render_data_source_banner(filtered)

    aggregates = compute_mode_aggregates(filtered)

    # Success rates
    render_section_header("Success rate")
    success_rows = []
    for mode in MODES:
        agg = aggregates[mode]
        if agg["runs"] == 0:
            continue
        success_rows.append({
            "Mode": f"Mode {mode}",
            "Verified success rate (%)": (
                agg["verified_success_rate"] * 100
                if agg["verified_success_rate"] is not None else None
            ),
            "Agent-reported rate (%)": (
                agg["agent_reported_success_rate"] * 100
                if agg["agent_reported_success_rate"] is not None else None
            ),
            "Verified / total": f"{agg['verified_successes']}/{agg['runs']}",
        })
    if success_rows:
        st.dataframe(
            pd.DataFrame(success_rows).round(1), hide_index=True,
            width="stretch",
        )
        fig = px.bar(
            success_rows, x="Mode",
            y=["Verified success rate (%)", "Agent-reported rate (%)"],
            color_discrete_sequence=[C_COLORS["A"], "#8a8a8a"],
            title="Verified vs agent-reported success rate",
            labels={"value": "Rate (%)", "variable": "Metric"},
            text_auto=True,
        )
        configure_plotly_chart(fig, "Verified vs agent-reported success rate")
        st.plotly_chart(fig, width="stretch")

    # Latency
    render_section_header("Latency")
    latency_rows = []
    for mode in MODES:
        agg = aggregates[mode]
        if agg["latency_mean"] is None:
            continue
        latency_rows.append({
            "Mode": f"Mode {mode}",
            "Mean (s)": agg["latency_mean"],
            "Median (s)": agg["latency_median"],
            "Min (s)": agg["latency_min"],
            "Max (s)": agg["latency_max"],
        })
    if latency_rows:
        st.dataframe(
            pd.DataFrame(latency_rows).round(4), hide_index=True,
            width="stretch",
        )
        fig = px.bar(
            latency_rows, x="Mode", y="Mean (s)",
            color="Mode", color_discrete_map=C_COLORS,
            title="Mean total latency by mode (seconds)",
            labels={"Mean (s)": "Mean latency (s)"},
            text_auto=".4f",
        )
        configure_plotly_chart(fig, "Mean total latency by mode (seconds)")
        fig.update_traces(showlegend=False)
        st.plotly_chart(fig, width="stretch")

    # Token consumption
    render_section_header("Token consumption")
    token_rows = []
    for mode in MODES:
        agg = aggregates[mode]
        if agg["combined_tokens_mean"] is None:
            continue
        token_rows.append({
            "Mode": f"Mode {mode}",
            "Groq tokens/run": agg["llm_tokens_mean"],
            "Jev tokens/run": agg["jev_tokens_mean"],
            "Combined/run": agg["combined_tokens_mean"],
        })
    if token_rows:
        st.dataframe(
            pd.DataFrame(token_rows).round(1), hide_index=True,
            width="stretch",
        )
        fig = px.bar(
            token_rows, x="Mode",
            y=["Groq tokens/run", "Jev tokens/run"],
            color_discrete_sequence=[C_COLORS["A"], C_COLORS["C"]],
            title="Provider-distinguishable token usage per run",
            labels={"value": "Tokens per run", "variable": "Provider"},
            text_auto=".0f",
        )
        configure_plotly_chart(fig, "Provider-distinguishable token usage per run")
        st.plotly_chart(fig, width="stretch")

    # Tool usage
    render_section_header("Tool usage and escalations")
    tool_rows = []
    for mode in MODES:
        agg = aggregates[mode]
        if agg["runs"] == 0:
            continue
        tool_rows.append({
            "Mode": f"Mode {mode}",
            "Runs": agg["runs"],
            "Escalations": agg["escalation_count"],
            "Tool-selection esc.": agg["tool_selection_escalations"],
            "Completion esc.": agg["completion_escalations"],
            "Esc. succeeded": agg["escalation_succeeded"],
        })
    if tool_rows:
        st.dataframe(pd.DataFrame(tool_rows), hide_index=True, width="stretch")

    # Escalation frequency chart
    esc_rows = [
        {"Mode": f"Mode {mode}", "Escalation frequency": aggregates[mode]["escalation_count"] / aggregates[mode]["runs"] * 100}
        for mode in MODES if aggregates[mode]["runs"] > 0
    ]
    if esc_rows:
        fig = px.bar(
            esc_rows, x="Mode", y="Escalation frequency",
            color="Mode", color_discrete_map=C_COLORS,
            title="Escalation frequency by mode (% of runs)",
            labels={"Escalation frequency": "Escalations per run (%)"},
            text_auto=".1f",
        )
        configure_plotly_chart(fig, "Escalation frequency by mode (% of runs)")
        fig.update_traces(showlegend=False)
        st.plotly_chart(fig, width="stretch")

    # Economic cost comparison
    cost_rows = [
        {"Mode": f"Mode {mode}", **{
            "Groq est. (USD)": aggregates[mode]["groq_estimated_cost"],
            "Jev est. (USD)": aggregates[mode]["jev_estimated_cost"],
            "Total est. (USD)": aggregates[mode]["total_estimated_cost"],
            "Avg/task (USD)": aggregates[mode]["avg_cost_per_task"],
        }}
        for mode in MODES if aggregates[mode]["has_cost_data"]
    ]
    if cost_rows:
        render_section_header("Economic cost comparison")
        st.dataframe(pd.DataFrame(cost_rows).round(6), hide_index=True, width="stretch")
        render_cost_disclaimer()
    else:
        with st.expander("Economic cost data", expanded=False):
            st.markdown(
                "No cost fields in the filtered records. Historical rows "
                "predate Phase 11 cost tracking; new mocked runs produce "
                "cost-annotated rows."
            )


# ═══════════════════════════════════════════════════════════════
# Page: Cost Analysis
# ═══════════════════════════════════════════════════════════════

def render_cost_analysis(records: list[dict]) -> None:
    st.markdown("## Cost Analysis")
    st.markdown(
        "Phase 11 economic accounting. Pricing lives in `config/pricing.py` "
        "(version `2026-11-16-v1`): Groq GPT-OSS 120B $0.15 / $0.60 per 1M "
        "input/output tokens; Jev 1.14.0 $0.042 / $0.00. Estimated equivalent "
        "cost applies reference pricing to recorded tokens — it is not "
        "actual billing."
    )

    costs = get_cost_data(records)
    cost_modes = [m for m in MODES if costs[m]["has_cost_data"]]

    if not cost_modes:
        st.warning(
            "No cost fields in the filtered records. Every stored benchmark "
            "row predates Phase 11 cost tracking, so historical cost data is "
            "unavailable rather than zero."
        )
        # Show what a fresh mocked run would produce (computed, not fabricated)
        render_fresh_run_cost_preview()
        return

    render_section_header("Per-mode cost summary")
    rows = []
    for mode in cost_modes:
        c = costs[mode]
        rows.append({
            "Mode": f"Mode {mode}",
            "Runs": c["runs"],
            "Groq est. (USD)": round(c["groq_estimated"], 6),
            "Jev est. (USD)": round(c["jev_estimated"], 6),
            "Total est. (USD)": round(c["total_estimated"], 6),
            "Groq actual (USD)": render_na(c["groq_actual"], "{:.6f}"),
            "Jev actual (USD)": render_na(c["jev_actual"], "{:.6f}"),
            "Total actual (USD)": render_na(c["total_actual"], "{:.6f}"),
            "Avg/task (USD)": round(c["total_estimated"] / c["runs"], 6) if c["runs"] else None,
            "Pricing version": c["pricing_version"] or "N/A",
            "Usage method": ", ".join(sorted(c["usage_methods"])) or "N/A",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    render_cost_disclaimer()

    render_section_header("Cost contribution share")
    share_rows = []
    for mode in cost_modes:
        c = costs[mode]
        if c["total_estimated"] > 0:
            share_rows.append({
                "Mode": f"Mode {mode}",
                "Groq share (%)": c["groq_estimated"] / c["total_estimated"] * 100,
                "Jev share (%)": c["jev_estimated"] / c["total_estimated"] * 100,
            })
    if share_rows:
        st.dataframe(pd.DataFrame(share_rows).round(1), hide_index=True, width="stretch")
        fig = px.bar(
            share_rows, x="Mode",
            y=["Groq share (%)", "Jev share (%)"],
            color_discrete_sequence=[C_COLORS["A"], C_COLORS["C"]],
            title="Estimated cost contribution by provider",
            labels={"value": "Share of estimated cost (%)", "variable": "Provider"},
            text_auto=".1f",
        )
        configure_plotly_chart(fig, "Estimated cost contribution by provider")
        st.plotly_chart(fig, width="stretch")

    render_section_header("Cost per task")
    per_task_rows = []
    for mode in cost_modes:
        c = costs[mode]
        if c["runs"]:
            per_task_rows.append({
                "Mode": f"Mode {mode}",
                "Avg cost/task (USD)": c["total_estimated"] / c["runs"],
                "Runs": c["runs"],
            })
    if per_task_rows:
        st.dataframe(pd.DataFrame(per_task_rows).round(6), hide_index=True, width="stretch")

    # Actual expenditure status
    render_section_header("Actual expenditure status")
    st.markdown(
        "- **Groq actual:** $0 for mocked runs by construction (free-tier "
        "assumption in the synthetic clients). Live runs record actual "
        "billing only where the provider exposes it."
        "- **Jev actual:** unavailable — the applicable billing route has "
        "not been established. The implementation does not invent one."
    )


def render_fresh_run_cost_preview() -> None:
    """Show cost figures computed from a fresh mocked run, clearly labelled."""
    with st.expander("What a fresh mocked run would record", expanded=False):
        st.markdown(
            "A new mocked run through the current code produces cost-annotated "
            "rows. The figures below are computed live from the recorded token "
            "counts of `experiments/demo_mocked/` using the Phase 11 pricing "
            "config — they are **estimated equivalent cost**, not billing."
        )
        demo = _load_demo_mocked()
        if not demo:
            st.info("No `demo_mocked/` dataset available.")
            return
        # Recompute from tokens exactly as economic_metrics.py does
        pricing = get_pricing_config()
        groq_p = pricing.get_pricing_for_provider("groq")
        jev_p = pricing.get_pricing_for_provider("jev")
        rows = []
        for mode in MODES:
            sub = [r for r in demo if r["mode"] == mode]
            if not sub:
                continue
            gi = sum(int(r["llm_input_tokens"] or 0) for r in sub)
            go_ = sum(int(r["llm_output_tokens"] or 0) for r in sub)
            ji = sum(int(r["jev_input_tokens"] or 0) for r in sub)
            jo = sum(int(r["jev_output_tokens"] or 0) for r in sub)
            groq_cost = groq_p.calculate_cost(gi, go_)
            jev_cost = jev_p.calculate_cost(ji, jo)
            rows.append({
                "Mode": f"Mode {mode}",
                "Groq input tokens": gi,
                "Groq output tokens": go_,
                "Jev input tokens": ji or None,
                "Jev output tokens": jo or None,
                "Groq est. (USD)": round(groq_cost, 6),
                "Jev est. (USD)": round(jev_cost, 6),
                "Total est. (USD)": round(groq_cost + jev_cost, 6),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ═══════════════════════════════════════════════════════════════
# Page: Performance Analysis
# ═══════════════════════════════════════════════════════════════

def render_performance_analysis(records: list[dict]) -> None:
    st.markdown("## Performance Analysis")
    st.markdown(
        "Distributions and per-task behaviour. Mocked and live records are "
        "shown separately where both exist."
    )

    mocked = [r for r in records if str(r.get("execution_type")).lower() == "mocked"]
    live = [r for r in records if str(r.get("execution_type")).lower() == "live"]

    if mocked:
        render_section_header("Latency distribution (mocked)")
        lat_df = pd.DataFrame([
            {"Mode": f"Mode {r['mode']}", "Total latency (s)": float(r["total_latency_seconds"])}
            for r in mocked if _safe_float(r.get("total_latency_seconds")) is not None
        ])
        if not lat_df.empty:
            fig = px.box(
                lat_df, x="Mode", y="Total latency (s)", color="Mode",
                color_discrete_map=C_COLORS, points="all",
                title="Latency distribution by mode (mocked)",
            )
            configure_plotly_chart(fig, "Latency distribution by mode (mocked)")
            fig.update_traces(showlegend=False)
            st.plotly_chart(fig, width="stretch")

        render_section_header("Token usage distribution (mocked)")
        token_choice = st.radio(
            "Token metric", ["Combined", "Groq (LLM)", "Jev"],
            horizontal=True, key="perf_token_metric",
            help="Combined is the only summed figure; provider buckets are never merged.",
        )
        key_map = {"Combined": "combined_tokens", "Groq (LLM)": "llm_total_tokens", "Jev": "jev_total_tokens"}
        tok_df = pd.DataFrame([
            {"Mode": f"Mode {r['mode']}", "Tokens": float(r[key_map[token_choice]] or 0)}
            for r in mocked
        ])
        fig = px.box(
            tok_df, x="Mode", y="Tokens", color="Mode",
            color_discrete_map=C_COLORS, points="all",
            title=f"Token distribution by mode ({token_choice})",
        )
        configure_plotly_chart(fig, f"Token distribution by mode ({token_choice})")
        fig.update_traces(showlegend=False)
        st.plotly_chart(fig, width="stretch")

        render_section_header("Iterations and tool calls (mocked)")
        iter_rows = []
        for mode in MODES:
            sub = [r for r in mocked if r["mode"] == mode]
            if not sub:
                continue
            iters = [_safe_int(r.get("iterations")) or 0 for r in sub]
            calls = [_safe_int(r.get("tool_calls")) or 0 for r in sub]
            iter_rows.append({
                "Mode": f"Mode {mode}",
                "Mean iterations": sum(iters) / len(iters),
                "Mean tool calls": sum(calls) / len(calls),
                "Tool failures": sum(_safe_int(r.get("tool_execution_failures")) or 0 for r in sub),
            })
        if iter_rows:
            st.dataframe(pd.DataFrame(iter_rows).round(2), hide_index=True, width="stretch")

        # Per-task table
        render_section_header("Per-task results (mocked)")
        task_rows = []
        for r in mocked[:50]:
            verification = r.get("verification", {})
            task_rows.append({
                "Mode": r.get("mode"),
                "Task": r.get("task_id"),
                "Outcome": verification.get("outcome") if isinstance(verification, dict) else "N/A",
                "Agent reported": r.get("agent_reported_success"),
                "Iterations": r.get("iterations"),
                "Termination": r.get("termination_reason"),
            })
        if task_rows:
            st.dataframe(pd.DataFrame(task_rows), hide_index=True, width="stretch")
    else:
        st.info("No mocked records in the current filter.")

    if live:
        render_section_header("Live records")
        live_rows = []
        for r in live:
            live_rows.append({
                "Mode": r.get("mode"),
                "Task": r.get("task", r.get("task_id")),
                "Success": r.get("success"),
                "Combined tokens": r.get("combined_tokens"),
                "Total latency (s)": r.get("total_latency_seconds"),
                "Termination": r.get("termination_reason"),
            })
        st.dataframe(pd.DataFrame(live_rows), hide_index=True, width="stretch")
        st.caption(
            "Live records carry real provider-reported usage. Only one live "
            "run exists in the repository; no comparison is possible."
        )


# ═══════════════════════════════════════════════════════════════
# Page: Run Experiment (Agent Playground)
# ═══════════════════════════════════════════════════════════════

def render_run_experiment() -> None:
    st.markdown("## Run Experiment")
    st.markdown(
        "Execute a single task in any mode. **Mocked execution is the safe "
        "default**; live execution requires an explicit opt-in and makes real "
        "API calls."
    )

    task = st.text_area(
        "Task",
        value=st.session_state.get("playground_task", TASK_OPTIONS[0]),
        height=100,
        help="Enter a customer-support task for the agent to execute.",
    )
    col1, col2 = st.columns(2)
    with col1:
        mode = st.selectbox(
            "Mode", MODES,
            index=MODES.index(st.session_state.get("playground_mode", "A")),
            help="A: LLM-only, B: LLM + Jev hybrid, C: Hybrid with escalation",
        )
    with col2:
        max_iterations = st.number_input(
            "Max iterations", min_value=1, max_value=10, value=5, step=1,
            help="Maximum number of control-loop iterations.",
        )
    st.session_state.playground_mode = mode
    st.session_state.playground_task = task

    col3, col4 = st.columns(2)
    with col3:
        execution_type = st.radio(
            "Execution type",
            ["Mocked (safe, offline)", "Live API (opt-in)"],
            index=0, horizontal=True,
            help="Mocked uses deterministic fake clients. Live uses real "
                 "Groq/Jev APIs and requires valid API keys.",
        )
    with col4:
        st.markdown("**Budget note**")
        st.caption(
            "Live execution is bounded by the playground's single-task "
            "scope. Use `scripts/run_benchmark.py --live --max-live-runs N "
            "--yes` for a budgeted campaign."
        )

    is_live = "Live" in execution_type
    if is_live:
        st.warning(
            "You are about to call the **live Groq and/or Jev APIs**. This "
            "incurs real token cost. Execution only happens when you press "
            "the button below."
        )

    if st.button("Execute task", type="primary", width="stretch"):
        if not task.strip():
            st.error("Enter a task before executing.")
            return
        with st.spinner("Executing agent..."):
            try:
                if is_live:
                    result = _run_live_agent(task.strip(), mode, int(max_iterations))
                else:
                    result = _run_mocked_agent(task.strip(), mode, int(max_iterations))
                st.session_state.execution_result = result
            except Exception as exc:  # noqa: BLE001 — surface, never crash
                st.session_state.execution_result = {
                    "task": task.strip(),
                    "final_response": f"Error: {exc}",
                    "success": False,
                    "iterations": 0,
                    "tool_calls": [],
                    "decision_history": [],
                    "llm_input_tokens": 0, "llm_output_tokens": 0,
                    "llm_total_tokens": 0, "llm_latency_seconds": 0.0,
                    "jev_input_tokens": 0, "jev_output_tokens": 0,
                    "jev_total_tokens": 0, "jev_latency_seconds": 0.0,
                    "tool_latency_seconds": 0.0, "total_latency_seconds": 0.0,
                    "termination_reason": "execution_error",
                    "mode": mode,
                    "execution_type": "live" if is_live else "mocked",
                    "task_specification": {},
                }
                st.error(f"Execution failed: {exc}")

    if st.session_state.get("execution_result"):
        _render_execution_result(st.session_state.execution_result)


def _render_execution_result(result: dict) -> None:
    """Render one execution outcome with metrics and decision trace."""
    mode = result.get("mode", "A")
    exec_type = result.get("execution_type", "mocked")

    st.markdown("### Agent response")
    final_response = result.get("final_response", "")
    if final_response and "Error:" in final_response:
        st.error(final_response)
    elif final_response:
        st.success(final_response)
    else:
        st.info("No response generated.")

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Iterations", result.get("iterations", 0))
    with c2:
        st.metric("Tool calls", len(result.get("tool_calls", [])))
    with c3:
        combined = (result.get("llm_total_tokens", 0) or 0) + (result.get("jev_total_tokens", 0) or 0)
        st.metric("Combined tokens", combined)
    with c4:
        st.metric("Total latency (s)", render_na(result.get("total_latency_seconds", 0.0), "{:.3f}"))

    # Provider-distinguishable token breakdown
    render_section_header("Provider token usage")
    tok_cols = st.columns(3)
    with tok_cols[0]:
        st.markdown("**Groq (LLM)**")
        st.write(f"Input: {result.get('llm_input_tokens', 0)}")
        st.write(f"Output: {result.get('llm_output_tokens', 0)}")
        st.write(f"Total: {result.get('llm_total_tokens', 0)}")
    with tok_cols[1]:
        st.markdown("**Jev**")
        jev_in = result.get("jev_input_tokens")
        st.write(f"Input: {jev_in if jev_in is not None else 'N/A'}")
        st.write(f"Output: {result.get('jev_output_tokens', 0)}")
        st.write(f"Total: {result.get('jev_total_tokens', 0)}")
    with tok_cols[2]:
        st.markdown("**Latency**")
        st.write(f"LLM: {result.get('llm_latency_seconds', 0):.3f} s")
        st.write(f"Jev: {result.get('jev_latency_seconds', 0):.3f} s")
        st.write(f"Tool: {result.get('tool_latency_seconds', 0):.4f} s")

    st.caption(f"Mode: {mode} · Execution type: {exec_type} · Termination: {result.get('termination_reason', '—')}")

    # Decision history
    with st.expander("Decision history (Jev decisions)", expanded=False):
        history = result.get("decision_history", [])
        if history:
            rows = []
            for entry in history:
                rows.append({
                    "Iteration": entry.get("iteration", "?"),
                    "Selected tool": entry.get("selected_tool", "?"),
                    "Escalated": "Yes" if entry.get("escalated") else "No",
                    "Tool confidence": render_na(entry.get("tool_confidence"), "{:.2f}"),
                    "Completion prob": render_na(entry.get("completion_probability"), "{:.2f}"),
                    "Loop prob": render_na(entry.get("loop_probability"), "{:.2f}"),
                    "Progress": entry.get("progress_score", "?"),
                    "Groq recommendation": entry.get("groq_recommendation", "—"),
                    "Final decision": entry.get("final_decision", "—"),
                    "Esc. succeeded": (
                        "Yes" if entry.get("escalation_succeeded") else
                        ("No" if entry.get("escalation_succeeded") is False else "—")
                    ),
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("No decision history available (Mode A has no Jev decisions).")

    # Tool execution results
    render_section_header("Tool execution results")
    tool_calls = result.get("tool_calls", [])
    if tool_calls:
        rows = []
        for call in tool_calls:
            res = call.get("result", {})
            rows.append({
                "Iteration": call.get("iteration", "?"),
                "Tool": call.get("tool_name", "?"),
                "Arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                "Status": call.get("execution_status", "?"),
                "Latency (s)": call.get("latency_seconds", "?"),
                "Result summary": _summarize_tool_result(res),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No tool calls were executed for this task.")

    with st.expander("Raw execution record (JSON)", expanded=False):
        st.json(result)


def _summarize_tool_result(result: Any) -> str:
    """Create a safe, readable summary of a tool result."""
    if not isinstance(result, dict):
        return str(result)[:200]
    if "error" in result:
        return f"Error: {result['error']}"
    if "status" in result and "message" in result:
        return (
            f"{result.get('service', '?')}: {result.get('status', '?')} — "
            f"{result.get('message', '?')[:80]}"
        )
    if "ticket_id" in result:
        return f"Ticket {result.get('ticket_id')} created (priority: {result.get('priority', '?')})"
    if "results" in result:
        return f"{result.get('result_count', 0)} knowledge-base results"
    return json.dumps(result, ensure_ascii=False)[:200]


def _infer_expected_tools(task: str) -> list[str]:
    """Infer which registered tools a free-text task needs.

    Uses simple keyword matching over the task text. This is only used
    to script the mocked clients; it never affects live execution.
    """
    lowered = task.lower()
    tools = []
    if any(word in lowered for word in ("status", "working", "down", "outage", "degraded", "available")):
        tools.append("check_service_status")
    if any(word in lowered for word in ("reset", "password", "troubleshoot", "troubleshooting", "how do i", "article", "steps", "faq", "guide", "slow", "dropping")):
        tools.append("search_knowledge_base")
    if any(word in lowered for word in ("ticket", "create", "raise", "open", "file", "submit", "log a")):
        tools.append("create_support_ticket")
    if not tools:
        tools.append("search_knowledge_base")
    return tools


def _run_mocked_agent(task: str, mode: str, max_iterations: int) -> dict:
    """Run an agent with deterministic fake clients (safe, offline).

    Reuses the benchmark's FakeLLMClient/FakeJevClient and scripted
    responses so the playground produces real execution records without
    contacting any live API.
    """
    from scripts.run_benchmark import (
        FakeLLMClient, FakeJevClient,
        _baseline_responses, _hybrid_responses, _jev_sequence,
    )

    benchmark_task = {
        "id": "playground_task",
        "description": task,
        "expected_outcome": "The requested information was retrieved.",
        "expected_tools": _infer_expected_tools(task),
    }
    registry = build_default_registry()

    if mode == "A":
        agent = BaselineAgent(
            llm_client=FakeLLMClient(_baseline_responses(benchmark_task)),
            registry=registry,
            max_iterations=max_iterations,
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        return {
            "task": task,
            "final_response": result.final_response,
            "success": result.success,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
            "decision_history": [],
            "llm_input_tokens": result.llm_input_tokens,
            "llm_output_tokens": result.llm_output_tokens,
            "llm_total_tokens": result.llm_total_tokens,
            "llm_latency_seconds": result.llm_latency_seconds,
            "jev_input_tokens": 0, "jev_output_tokens": 0,
            "jev_total_tokens": 0, "jev_latency_seconds": 0.0,
            "tool_latency_seconds": result.tool_latency_seconds,
            "total_latency_seconds": result.total_latency_seconds,
            "termination_reason": result.termination_reason,
            "mode": "A",
            "execution_type": "mocked",
            "task_specification": {},
        }

    agent = HybridAgent(
        llm_client=FakeLLMClient(_hybrid_responses(benchmark_task)),
        jev_client=FakeJevClient(_jev_sequence(benchmark_task)),
        registry=registry,
        max_iterations=max_iterations,
        enable_escalation=(mode == "C"),
    )
    try:
        result = agent.run(task)
    finally:
        agent.close()
    return {
        "task": task,
        "final_response": result.final_response,
        "success": result.success,
        "iterations": result.iterations,
        "tool_calls": result.tool_calls,
        "decision_history": result.decision_history,
        "llm_input_tokens": result.llm_input_tokens,
        "llm_output_tokens": result.llm_output_tokens,
        "llm_total_tokens": result.llm_total_tokens,
        "llm_latency_seconds": result.llm_latency_seconds,
        "jev_input_tokens": result.jev_input_tokens,
        "jev_output_tokens": result.jev_output_tokens,
        "jev_total_tokens": result.jev_total_tokens,
        "jev_latency_seconds": result.jev_latency_seconds,
        "tool_latency_seconds": result.tool_latency_seconds,
        "total_latency_seconds": result.total_latency_seconds,
        "termination_reason": result.termination_reason,
        "mode": mode,
        "execution_type": "mocked",
        "task_specification": result.task_specification,
    }


def _run_live_agent(task: str, mode: str, max_iterations: int) -> dict:
    """Run an agent against the real Groq/Jev APIs (opt-in only).

    Requires valid GROQ_API_KEY / TYPESAFE_API_KEY in .env. Errors are
    surfaced to the user without crashing the dashboard.
    """
    registry = build_default_registry()

    if mode == "A":
        agent = BaselineAgent(
            llm_client=GroqLLMClient(),
            registry=registry,
            max_iterations=max_iterations,
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        return {
            "task": task,
            "final_response": result.final_response,
            "success": result.success,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
            "decision_history": [],
            "llm_input_tokens": result.llm_input_tokens,
            "llm_output_tokens": result.llm_output_tokens,
            "llm_total_tokens": result.llm_total_tokens,
            "llm_latency_seconds": result.llm_latency_seconds,
            "jev_input_tokens": 0, "jev_output_tokens": 0,
            "jev_total_tokens": 0, "jev_latency_seconds": 0.0,
            "tool_latency_seconds": result.tool_latency_seconds,
            "total_latency_seconds": result.total_latency_seconds,
            "termination_reason": result.termination_reason,
            "mode": "A",
            "execution_type": "live",
            "task_specification": {},
        }

    agent = HybridAgent(
        llm_client=GroqLLMClient(),
        jev_client=JevClient(),
        registry=registry,
        max_iterations=max_iterations,
        enable_escalation=(mode == "C"),
    )
    try:
        result = agent.run(task)
    finally:
        agent.close()
    return {
        "task": task,
        "final_response": result.final_response,
        "success": result.success,
        "iterations": result.iterations,
        "tool_calls": result.tool_calls,
        "decision_history": result.decision_history,
        "llm_input_tokens": result.llm_input_tokens,
        "llm_output_tokens": result.llm_output_tokens,
        "llm_total_tokens": result.llm_total_tokens,
        "llm_latency_seconds": result.llm_latency_seconds,
        "jev_input_tokens": result.jev_input_tokens,
        "jev_output_tokens": result.jev_output_tokens,
        "jev_total_tokens": result.jev_total_tokens,
        "jev_latency_seconds": result.jev_latency_seconds,
        "tool_latency_seconds": result.tool_latency_seconds,
        "total_latency_seconds": result.total_latency_seconds,
        "termination_reason": result.termination_reason,
        "mode": mode,
        "execution_type": "live",
        "task_specification": result.task_specification,
    }


# ═══════════════════════════════════════════════════════════════
# Page: Experiment History
# ═══════════════════════════════════════════════════════════════

def render_experiment_history() -> None:
    st.markdown("## Experiment History")
    st.markdown(
        "Append-only recorded experiments. Original benchmark records are "
        "never modified to make the display look cleaner."
    )

    records = load_benchmark_data()
    live_records = load_live_runs()

    # Source selector
    source = st.radio(
        "Record source",
        [
            "Benchmark results (benchmark_results.*)",
            "Live runs (results.csv + benchmark live rows)",
        ],
        horizontal=True,
        help="Benchmark results are the main dataset (historical mocked plus "
             "any live rows the canonical logger appended); the live source "
             "adds the legacy Phase 5/6 live Mode B run.",
    )

    if source.startswith("Live"):
        if not live_records:
            st.info("No live run recorded yet.")
            return
        st.caption(
            f"{len(live_records)} live run(s) recorded. Canonical live rows "
            "carry Phase 11 cost fields; the legacy `results.csv` row is "
            "pre-Phase 11 and shows cost fields as N/A (unavailable, not $0)."
        )
        rows = []
        for r in live_records:
            rows.append({
                "Timestamp": r.get("timestamp"),
                "Mode": r.get("mode"),
                "Task": r.get("task_id") or r.get("task"),
                "Exec type": r.get("execution_type", "live"),
                "Dataset": r.get("dataset", "canonical_live"),
                "Success": r.get("agent_reported_success") or r.get("success"),
                "Outcome": (
                    r.get("outcome")
                    if r.get("outcome")
                    else ("verified" if str(r.get("success")).lower()
                          in ("true", "1") else "unverifiable")
                ),
                "Termination": r.get("termination_reason"),
                "Iterations": r.get("iterations"),
                "Combined tokens": r.get("combined_tokens"),
                "Total latency (s)": r.get("total_latency_seconds"),
                "Usage method": r.get("usage_measurement_method"),
                "Pricing version": r.get("pricing_version"),
                "Groq est. cost": _safe_float(r.get("groq_estimated_cost")),
                "Total est. cost": _safe_float(r.get("total_estimated_cost")),
                "Groq actual": _safe_float(r.get("groq_actual_cost")),
                "Total actual": _safe_float(r.get("total_actual_cost")),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        return

    # Benchmark history with filters
    col1, col2 = st.columns(2)
    with col1:
        mode_filter = st.selectbox("Mode", ["All", "A", "B", "C"], index=0)
    with col2:
        exec_filter = st.selectbox("Execution type", ["All", "mocked", "live"], index=0)

    filtered = records
    if mode_filter != "All":
        filtered = [r for r in filtered if r.get("mode") == mode_filter]
    if exec_filter != "All":
        filtered = [
            r for r in filtered
            if str(r.get("execution_type", "")).lower() == exec_filter.lower()
        ]

    st.caption(
        f"Showing {len(filtered)} of {len(records)} benchmark records "
        f"(`experiments/benchmark_results.*` historical + "
        f"`experiments/post_phase11_mocked/` fresh)."
    )

    if not filtered:
        st.info("No records match the selected filters.")
        return

    # Distinguish historical vs newly generated
    st.markdown(
        "**Record origin:** rows without cost fields are historical "
        "(pre-Phase 11); rows with cost fields were written by the current "
        "cost-annotated code. Both are shown with their own labels."
    )

    rows = []
    for r in filtered[:100]:
        verification = r.get("verification", {})
        outcome = verification.get("outcome") if isinstance(verification, dict) else None
        has_cost = _safe_float(r.get("total_estimated_cost")) is not None
        rows.append({
            "Timestamp": r.get("timestamp", "")[:19],
            "Run ID": r.get("run_id", ""),
            "Mode": r.get("mode"),
            "Task": r.get("task_id"),
            "Dataset": r.get("dataset", "historical"),
            "Exec type": r.get("execution_type"),
            "Outcome": outcome or "N/A",
            "Agent reported": r.get("agent_reported_success"),
            "Iterations": r.get("iterations"),
            "Combined tokens": r.get("combined_tokens"),
            "Latency (s)": r.get("total_latency_seconds"),
            "Escalations": r.get("escalation_count"),
            "Cost data": "Yes" if has_cost else "No (historical)",
            "Usage method": r.get("usage_measurement_method"),
            "Pricing version": r.get("pricing_version"),
            "Total est. cost": _safe_float(r.get("total_estimated_cost")),
            "Total actual": _safe_float(r.get("total_actual_cost")),
            "Termination": r.get("termination_reason"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Showing the first 100 matching records. The underlying files are append-only.")


# ═══════════════════════════════════════════════════════════════
# Page: Architecture
# ═══════════════════════════════════════════════════════════════

def render_architecture() -> None:
    st.markdown("## Architecture")
    st.markdown(
        "System One (Jev) makes fast control decisions; System Two (Groq) "
        "provides reasoning, planning and advisory review."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**System One — Jev (fast, cost-efficient)**")
        st.markdown(
            "- Role: tool selection, completion detection, loop detection, progress\n"
            "- Model: TypeSafe API (`jev-1.14.0`)\n"
            "- Key metrics: `tool_confidence`, `completion_probability`, `loop_probability`, `progress_score`"
        )
        st.caption("Thresholds (provisional): tool confidence ≤ 0.60 → escalation; completion prob in [0.50, 0.70) → escalation.")
    with col2:
        st.markdown("**System Two — Groq (slow, comprehensive)**")
        st.markdown(
            "- Role: planning, tool arguments, final response, uncertainty review\n"
            "- Model: `openai/gpt-oss-120b`\n"
            "- Key metrics: `llm_input_tokens`, `llm_output_tokens`, `llm_total_tokens`"
        )
        st.caption("Groq always retains final authority; Jev escalates uncertain decisions (Mode C).")

    st.divider()

    st.markdown("**Three experimental modes**")
    mode_cols = st.columns(3)
    with mode_cols[0]:
        st.markdown("**Mode A — LLM-only**")
        st.markdown(
            "- Groq controls everything: planning, tool selection, arguments, completion, loop detection\n"
            "- No Jev involvement\n"
            "- Baseline for comparison"
        )
    with mode_cols[1]:
        st.markdown("**Mode B — LLM + Jev hybrid**")
        st.markdown(
            "- Groq plans, generates arguments, writes the final response\n"
            "- Jev controls tool selection, completion, loop detection, progress\n"
            "- Evidence-gated completion"
        )
    with mode_cols[2]:
        st.markdown("**Mode C — Hybrid with escalation**")
        st.markdown(
            "- Jev stays the fast controller\n"
            "- Uncertain decisions escalated to Groq (advisory only)\n"
            "- Every safeguard preserved: allowed tools, evidence gate, ticket authorisation"
        )

    st.divider()
    st.markdown(
        "**Safeguards.** Allowed-tools filtering applies for the whole run; "
        "`create_support_ticket` requires explicit user authorisation; "
        "completion requires valid execution evidence from every required "
        "tool; deterministic guards block repeated identical calls, loops "
        "and runaway iterations. Every termination path produces a "
        "machine-readable `termination_reason`."
    )
    st.markdown(
        "**Data handling.** Mocked and live execution are recorded "
        "separately via `execution_type` and never merged in one "
        "comparison. Missing metrics render as N/A; nothing is invented."
    )


# ═══════════════════════════════════════════════════════════════
# App entry point
# ═══════════════════════════════════════════════════════════════

PAGES = [
    "Overview",
    "Experiment Comparison",
    "Cost Analysis",
    "Performance Analysis",
    "Run Experiment",
    "Experiment History",
    "Architecture",
]


def init_session_state() -> None:
    """Initialize session state variables."""
    if "execution_result" not in st.session_state:
        st.session_state.execution_result = None
    if "execution_pending" not in st.session_state:
        st.session_state.execution_pending = False
    if "playground_task" not in st.session_state:
        st.session_state.playground_task = TASK_OPTIONS[0]
    if "playground_mode" not in st.session_state:
        st.session_state.playground_mode = "A"
    if "benchmark_loaded" not in st.session_state:
        st.session_state.benchmark_loaded = False
    if "benchmark_data" not in st.session_state:
        st.session_state.benchmark_data = None


def main() -> None:
    st.set_page_config(
        page_title="Fast Decisions, Slow Thoughts — Research Dashboard",
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()

    # Header
    st.title("Fast Decisions, Slow Thoughts")
    st.caption(
        "Hybrid LLM + System One (Jev) architecture for cost-efficient AI "
        "agents — final-year research project dashboard."
    )

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", PAGES, index=0)

    st.sidebar.divider()

    # Live-run safety note
    st.sidebar.caption(
        "Mocked execution is the default everywhere. Live API calls happen "
        "only on explicit opt-in, per task."
    )

    # Load benchmark data once for data-driven pages
    if page in (
        "Overview", "Experiment Comparison", "Cost Analysis",
        "Performance Analysis", "Experiment History",
    ):
        if not st.session_state.benchmark_loaded:
            st.session_state.benchmark_data = load_benchmark_data()
            st.session_state.benchmark_loaded = True
        records = st.session_state.benchmark_data
        aggregates = compute_mode_aggregates(records)

    if page == "Overview":
        render_overview(records, aggregates)
    elif page == "Experiment Comparison":
        render_experiment_comparison(records)
    elif page == "Cost Analysis":
        render_cost_analysis(records)
    elif page == "Performance Analysis":
        render_performance_analysis(records)
    elif page == "Run Experiment":
        render_run_experiment()
    elif page == "Experiment History":
        render_experiment_history()
    elif page == "Architecture":
        render_architecture()


if __name__ == "__main__":
    main()
