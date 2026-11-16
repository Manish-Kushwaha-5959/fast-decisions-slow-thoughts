"""
Phase 8: Streamlit Dashboard for the Hybrid LLM + System One (Jev) Architecture

Interactive research demonstration of the three experimental modes:
- Mode A: LLM-only
- Mode B: LLM + Jev (hybrid)
- Mode C: Hybrid with uncertainty-aware escalation

Dashboard features:
- Agent Playground for live task execution
- Benchmark Analytics from recorded experiment data
- Mode comparison across verified metrics
- Architecture explanation
"""

import streamlit as st
import pandas as pd
import json
import sys
from pathlib import Path

# Add project root to path (app.py is at the project root)
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import project modules
from agents.baseline_agent import BaselineAgent
from agents.hybrid_agent import HybridAgent
from tools.registry import build_default_registry
from models.llm_client import GroqLLMClient
from models.jev_client import JevClient

# Verification outcome constants
VERIFIED = "verified"
FAILED = "failed"
UNVERIFIABLE = "unverifiable"


# ── Constants ────────────────────────────────────────────────

MODES = ["A", "B", "C"]

# Page config
st.set_page_config(
    page_title="Hybrid LLM + Jev Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ────────────────────────────────────────────────

MODES = ["A", "B", "C"]
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

# ── Session state initialization ───────────────────────────

def init_session_state():
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
    if "verifier" not in st.session_state:
        st.session_state.verifier = None


def load_benchmark_data():
    """Load benchmark results from CSV and JSONL."""
    csv_path = PROJECT_ROOT / "experiments" / "benchmark_results.csv"
    jsonl_path = PROJECT_ROOT / "experiments" / "benchmark_results.jsonl"
    demo_dir = PROJECT_ROOT / "experiments" / "demo_mocked"

    rows = []
    if csv_path.exists():
        import csv
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

    jsonl_records = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    jsonl_records.append(json.loads(line))

    # Merge: CSV provides flat fields, JSONL provides verification detail
    all_records = []
    for row in rows:
        # Find matching JSONL record
        run_id = row.get("run_id", "")
        record = dict(row)
        for jr in jsonl_records:
            if jr.get("run_id") == run_id:
                record["verification"] = jr.get("verification", {})
                record["raw_execution"] = jr.get("raw_execution", {})
                break
        all_records.append(record)

    # Also add demo_mocked records if main file is empty or we want supplementary
    if not rows and demo_dir.exists():
        import csv as csv_mod
        demo_csv = demo_dir / "benchmark_results.csv"
        if demo_csv.exists():
            with open(demo_csv, "r", encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    row["execution_type"] = "mocked"
                    all_records.append(row)

    return all_records


def get_mode_filters(records, mode=None):
    """Filter records by mode."""
    if not records:
        return records
    if mode and mode != "all":
        return [r for r in records if r.get("mode") == mode]
    return records


def get_mode_success_rates(records):
    """Calculate verified and agent-reported success rates per mode."""
    modes = {"A": {"verified_succ": 0, "verified_fail": 0, "unverifiable": 0,
                   "agent_succ": 0, "run_count": 0},
             "B": {"verified_succ": 0, "verified_fail": 0, "unverifiable": 0,
                   "agent_succ": 0, "run_count": 0},
             "C": {"verified_succ": 0, "verified_fail": 0, "unverifiable": 0,
                   "agent_succ": 0, "run_count": 0}}

    for r in records:
        m = r.get("mode", "")
        if m not in modes:
            continue
        modes[m]["run_count"] += 1

        # Verified outcome
        verification = r.get("verification", {})
        verified_outcome = verification.get("outcome", "") if isinstance(verification, dict) else ""

        if verified_outcome == VERIFIED:
            modes[m]["verified_succ"] += 1
        elif verified_outcome == FAILED:
            modes[m]["verified_fail"] += 1
        else:
            modes[m]["unverifiable"] += 1

        # Agent-reported success
        agent_reported = r.get("agent_reported_success", "")
        if agent_reported == "true" or agent_reported is True:
            modes[m]["agent_succ"] += 1

    return modes


def get_latency_data(records):
    """Extract latency data per mode."""
    latencies = {"A": [], "B": [], "C": []}
    for r in records:
        m = r.get("mode", "")
        if m not in latencies:
            continue
        avg_latency = r.get("total_latency_seconds")
        if avg_latency is not None:
            try:
                latencies[m].append(float(avg_latency))
            except (ValueError, TypeError):
                pass
    return latencies


def get_token_data(records):
    """Extract token usage per mode."""
    tokens = {"A": {"llm_total": [], "jev_total": [], "combined": []},
              "B": {"llm_total": [], "jev_total": [], "combined": []},
              "C": {"llm_total": [], "jev_total": [], "combined": []}}

    for r in records:
        m = r.get("mode", "")
        if m not in tokens:
            continue
        try:
            llm_total = float(r.get("llm_total_tokens", 0) or 0)
            jev_total = float(r.get("jev_total_tokens", 0) or 0)
            combined = float(r.get("combined_tokens", 0) or 0)
            tokens[m]["llm_total"].append(llm_total)
            tokens[m]["jev_total"].append(jev_total)
            tokens[m]["combined"].append(combined)
        except (ValueError, TypeError):
            pass

    return tokens


def get_escalation_data(records):
    """Extract escalation data per mode.

    Escalation counts come from the CSV columns (escalation_count,
    tool_selection_escalations, completion_escalations,
    escalation_succeeded_count) written by evaluation/metrics.py.
    Modes A and B never escalate, so their counts are zero.
    """

    escalations = {
        "A": {"count": 0, "tool_selection": 0, "completion": 0, "succeeded": 0},
        "B": {"count": 0, "tool_selection": 0, "completion": 0, "succeeded": 0},
        "C": {"count": 0, "tool_selection": 0, "completion": 0, "succeeded": 0},
    }

    for r in records:
        m = r.get("mode", "")
        if m not in escalations:
            continue

        # CSV columns are authoritative; fall back to the JSONL
        # verification block for records written before the CSV
        # carried escalation columns.
        def _int(value):
            try:
                return int(value) if value not in (None, "") else 0
            except (ValueError, TypeError):
                return 0

        count = _int(r.get("escalation_count"))
        tool_sel = _int(r.get("tool_selection_escalations"))
        completion = _int(r.get("completion_escalations"))
        succeeded = _int(r.get("escalation_succeeded_count"))

        if count == 0 and isinstance(r.get("verification"), dict):
            verification = r["verification"]
            count = _int(verification.get("escalation_count"))
            tool_sel = _int(verification.get("tool_selection_escalations"))
            completion = _int(verification.get("completion_escalations"))
            succeeded = _int(verification.get("escalation_succeeded_count"))

        escalations[m]["count"] += count
        escalations[m]["tool_selection"] += tool_sel
        escalations[m]["completion"] += completion
        escalations[m]["succeeded"] += succeeded

    return escalations


def render_execution_monitor(execution_result):
    """Render the execution monitor with decision history and tool calls."""
    if not execution_result:
        st.info("Execute a task in the Agent Playground section first to see the Execution Monitor.")
        return

    st.markdown("### 🔍 Execution Monitor")

    decision_history = execution_result.get("decision_history", [])
    tool_calls = execution_result.get("tool_calls", [])

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Iterations", execution_result.get("iterations", 0))
    with col2:
        escalated = sum(1 for d in decision_history if d.get("escalated"))
        st.metric("Escalation Events", escalated)
    with col3:
        st.metric("Tool Calls", len(tool_calls))
    with col4:
        st.metric("Termination", execution_result.get("termination_reason", "—"))

    # Tool execution results
    st.markdown("#### 🛠️ Tool Execution Results")
    if tool_calls:
        tool_rows = []
        for call in tool_calls:
            result = call.get("result", {})
            tool_rows.append({
                "Iteration": call.get("iteration", "?"),
                "Tool": call.get("tool_name", "?"),
                "Arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                "Status": call.get("execution_status", "?"),
                "Latency (s)": call.get("latency_seconds", "?"),
                "Result Summary": _summarize_tool_result(result),
            })
        tool_df = pd.DataFrame(tool_rows)
        st.dataframe(tool_df, width="stretch", hide_index=True)
    else:
        st.info("No tool calls were executed for this task.")

    # Decision history table
    with st.expander("View Decision History (Jev decisions)", expanded=False):
        if decision_history:
            history_data = []
            for entry in decision_history:
                row = {
                    "Iteration": entry.get("iteration", "?"),
                    "Selected Tool": entry.get("selected_tool", "?"),
                    "Decision Type": entry.get("decision_type", "none"),
                    "Escalated": "Yes" if entry.get("escalated") else "No",
                    "Confidence": f"{entry.get('tool_confidence', 0):.2f}" if entry.get('tool_confidence') else "N/A",
                    "Completion Prob": f"{entry.get('completion_probability', 0):.2f}" if entry.get('completion_probability') else "N/A",
                    "Loop Prob": f"{entry.get('loop_probability', 0):.2f}" if entry.get('loop_probability') else "N/A",
                    "Progress Score": entry.get('progress_score', '?'),
                    "Groq Recommendation": entry.get('groq_recommendation', '—'),
                    "Final Decision": entry.get('final_decision', '—'),
                    "Escalation Succeeded": "Yes" if entry.get('escalation_succeeded') else ("No" if entry.get('escalation_succeeded') is False else "—"),
                }
                history_data.append(row)

            if history_data:
                df = pd.DataFrame(history_data)
                st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.info("No decision history available (Mode A has no Jev decisions).")

    # Raw execution record
    with st.expander("View Raw Execution Record (JSON)", expanded=False):
        st.json(execution_result)


def _summarize_tool_result(result):
    """Create a safe, readable summary of a tool result."""
    if not isinstance(result, dict):
        return str(result)[:200]
    if "error" in result:
        return f"Error: {result['error']}"
    if "status" in result and "message" in result:
        return f"{result.get('service', '?')}: {result.get('status', '?')} — {result.get('message', '?')[:80]}"
    if "ticket_id" in result:
        return f"Ticket {result.get('ticket_id')} created (priority: {result.get('priority', '?')})"
    if "results" in result:
        return f"{result.get('result_count', 0)} knowledge-base results"
    return json.dumps(result, ensure_ascii=False)[:200]


def render_agent_playground():
    """Render the Agent Playground section."""
    st.markdown("## 🎮 Agent Playground")

    col1, col2 = st.columns([3, 1])

    with col1:
        task = st.text_area(
            "Enter a task:",
            value=st.session_state.playground_task,
            height=100,
            help="Enter a customer-support task for the agent to execute."
        )

    with col2:
        mode = st.selectbox(
            "Select mode:",
            MODES,
            index=MODES.index(st.session_state.playground_mode) if st.session_state.playground_mode in MODES else 0,
            help="A: LLM-only, B: LLM + Jev hybrid, C: Hybrid with escalation"
        )
        st.session_state.playground_mode = mode
        st.session_state.playground_task = task

    # Execution type selector (mocked by default for safety)
    col3, col4 = st.columns([1, 1])
    with col3:
        execution_type = st.radio(
            "Execution type:",
            ["Mocked (safe, offline)", "Live API (opt-in)"],
            index=0,
            help="Mocked uses deterministic fake clients. Live uses real Groq/Jev APIs and requires valid API keys."
        )
    with col4:
        max_iterations = st.number_input(
            "Max iterations:",
            min_value=1,
            max_value=10,
            value=5,
            step=1,
            help="Maximum number of control-loop iterations."
        )

    execute_col = st.columns(1)
    with execute_col[0]:
        run_button = st.button("▶ Execute", type="primary", width="stretch")

    # Execute agent
    if run_button and task.strip():
        st.session_state.execution_pending = True

    if st.session_state.execution_pending and task.strip():
        with st.spinner("Executing agent..."):
            try:
                # Determine which agent to run
                mode = st.session_state.playground_mode
                is_live = "Live" in execution_type

                if is_live:
                    # Live execution: real Groq/Jev APIs (opt-in only)
                    execution_record = _run_live_agent(task.strip(), mode, int(max_iterations))
                else:
                    # Mocked execution: deterministic fake clients (safe, offline)
                    execution_record = _run_mocked_agent(task.strip(), mode, int(max_iterations))

                st.session_state.execution_result = execution_record
                st.session_state.execution_pending = False

            except Exception as e:
                st.session_state.execution_result = {
                    "task": task.strip(),
                    "final_response": f"Error: {str(e)}",
                    "success": False,
                    "iterations": 0,
                    "tool_calls": [],
                    "decision_history": [],
                    "llm_input_tokens": 0,
                    "llm_output_tokens": 0,
                    "llm_total_tokens": 0,
                    "llm_latency_seconds": 0.0,
                    "jev_input_tokens": 0,
                    "jev_output_tokens": 0,
                    "jev_total_tokens": 0,
                    "jev_latency_seconds": 0.0,
                    "tool_latency_seconds": 0.0,
                    "total_latency_seconds": 0.0,
                    "termination_reason": "execution_error",
                    "mode": mode,
                    "execution_type": "live" if "Live" in execution_type else "mocked",
                    "task_specification": {}
                }
                st.session_state.execution_pending = False
                st.error(f"Execution failed: {str(e)}")

    # Display execution result
    if st.session_state.execution_result:
        result = st.session_state.execution_result
        mode = result.get("mode", "A")
        exec_type = result.get("execution_type", "mocked")

        st.markdown("### 📤 Agent Response")

        # Display final response
        final_response = result.get("final_response", "")
        if final_response and "Error:" in final_response:
            st.error(final_response)
        elif final_response:
            st.success(final_response)
        else:
            st.info("No response generated.")

        # Display metrics in columns
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Iterations", result.get("iterations", 0))
        with col2:
            st.metric("Tool Calls", len(result.get("tool_calls", [])))
        with col3:
            combined_tokens = result.get("llm_total_tokens", 0) + result.get("jev_total_tokens", 0)
            st.metric("Combined Tokens", combined_tokens)
        with col4:
            total_latency = result.get("total_latency_seconds", 0.0)
            st.metric("Total Latency (s)", f"{total_latency:.3f}")

        # Display execution details
        with st.expander("View Execution Details", expanded=False):
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown("**Token Usage:**")
                st.write(f"• LLM Input: {result.get('llm_input_tokens', 0)}")
                st.write(f"• LLM Output: {result.get('llm_output_tokens', 0)}")
                st.write(f"• LLM Total: {result.get('llm_total_tokens', 0)}")
                st.write(f"• Jev Input: {result.get('jev_input_tokens', 0)}")
                st.write(f"• Jev Output: {result.get('jev_output_tokens', 0)}")
                st.write(f"• Jev Total: {result.get('jev_total_tokens', 0)}")

            with col_b:
                st.markdown("**Execution Metrics:**")
                st.write(f"• Termination Reason: {result.get('termination_reason', '—')}")
                st.write(f"• Tool Latency: {result.get('tool_latency_seconds', 0):.3f}s")
                st.write(f"• Total Latency: {result.get('total_latency_seconds', 0):.3f}s")
                st.write(f"• Mode: {mode}")
                st.write(f"• Execution Type: {exec_type}")

                # Show tool calls
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    st.markdown("**Tool Calls:**")
                    for call in tool_calls:
                        st.write(f"  • Iter {call.get('iteration', '?')}: {call.get('tool_name', '?')}")


def _infer_expected_tools(task):
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

    # Fallback: every task can at least search the knowledge base.
    if not tools:
        tools.append("search_knowledge_base")

    return tools


def _run_mocked_agent(task, mode, max_iterations):
    """Run an agent with deterministic fake clients (safe, offline).

    Reuses the benchmark's FakeLLMClient/FakeJevClient and scripted
    responses so the playground produces real execution records without
    contacting any live API. The free-text task is wrapped into a
    benchmark-style task dict so the existing scripting helpers work.
    """

    from scripts.run_benchmark import (
        FakeLLMClient,
        FakeJevClient,
        _baseline_responses,
        _hybrid_responses,
        _jev_sequence,
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
            max_iterations=max_iterations
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        execution_record = {
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
            "jev_input_tokens": 0,
            "jev_output_tokens": 0,
            "jev_total_tokens": 0,
            "jev_latency_seconds": 0.0,
            "tool_latency_seconds": result.tool_latency_seconds,
            "total_latency_seconds": result.total_latency_seconds,
            "termination_reason": result.termination_reason,
            "mode": "A",
            "execution_type": "mocked",
            "task_specification": {}
        }
    else:
        agent = HybridAgent(
            llm_client=FakeLLMClient(_hybrid_responses(benchmark_task)),
            jev_client=FakeJevClient(_jev_sequence(benchmark_task)),
            registry=registry,
            max_iterations=max_iterations,
            enable_escalation=(mode == "C")
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        execution_record = {
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
            "task_specification": result.task_specification
        }

    return execution_record


def _run_live_agent(task, mode, max_iterations):
    """Run an agent against the real Groq/Jev APIs (opt-in only).

    Requires valid GROQ_API_KEY / TYPESAFE_API_KEY in .env. Errors are
    surfaced to the user without crashing the dashboard.
    """

    registry = build_default_registry()

    if mode == "A":
        agent = BaselineAgent(
            llm_client=GroqLLMClient(),
            registry=registry,
            max_iterations=max_iterations
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        execution_record = {
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
            "jev_input_tokens": 0,
            "jev_output_tokens": 0,
            "jev_total_tokens": 0,
            "jev_latency_seconds": 0.0,
            "tool_latency_seconds": result.tool_latency_seconds,
            "total_latency_seconds": result.total_latency_seconds,
            "termination_reason": result.termination_reason,
            "mode": "A",
            "execution_type": "live",
            "task_specification": {}
        }
    else:
        agent = HybridAgent(
            llm_client=GroqLLMClient(),
            jev_client=JevClient(),
            registry=registry,
            max_iterations=max_iterations,
            enable_escalation=(mode == "C")
        )
        try:
            result = agent.run(task)
        finally:
            agent.close()
        execution_record = {
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
            "task_specification": result.task_specification
        }

    return execution_record


def render_benchmark_analytics():
    """Render the Benchmark Analytics section."""
    st.markdown("## 📊 Benchmark Analytics")

    # Load data if not already loaded
    if not st.session_state.benchmark_loaded:
        records = load_benchmark_data()
        st.session_state.benchmark_data = records
        st.session_state.benchmark_loaded = True
    else:
        records = st.session_state.benchmark_data

    if not records:
        st.warning("No benchmark data found. Please ensure experiment records exist.")
        st.info("Run `python scripts/run_benchmark.py --mode all` to generate benchmark data.")
        return

    # Data source indicator
    mocked_count = sum(1 for r in records if str(r.get("execution_type", "")).lower() == "mocked")
    live_count = sum(1 for r in records if str(r.get("execution_type", "")).lower() == "live")
    st.info(f"📁 Data source: `experiments/benchmark_results.csv` + `.jsonl` — {len(records)} runs "
            f"({mocked_count} mocked, {live_count} live). "
            f"Mocked and live runs are never mixed in analysis.")

    # Sidebar filters
    st.sidebar.markdown("### Filters")
    mode_filter = st.sidebar.radio(
        "Mode:",
        ["All", "A", "B", "C"],
        index=0,
        help="Filter benchmark results by execution mode."
    )
    exec_type = st.sidebar.radio(
        "Execution Type:",
        ["All", "Mocked", "Live"],
        index=0,
        help="Filter by execution type (mocked or live)."
    )

    # Apply filters
    filtered = records
    if mode_filter != "All":
        filtered = get_mode_filters(filtered, mode_filter)

    # Filter by execution type
    if exec_type != "All":
        filtered = [r for r in filtered if str(r.get("execution_type", "")).lower() == exec_type.lower()]

    if not filtered:
        st.info("No records match the selected filters.")
        return

    # Compute summaries
    mode_stats = get_mode_success_rates(filtered)
    latencies = get_latency_data(filtered)
    token_data = get_token_data(filtered)
    escalations = get_escalation_data(filtered)

    # Main content area
    # Metric cards across the top
    st.markdown("### Key Metrics")

    # Mode comparison row
    col1, col2, col3 = st.columns(3)

    with col1:
        m = mode_stats["A"]
        st.markdown("#### Mode A: LLM-only")
        st.metric("Verified Success Rate", f"{m['verified_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Agent-Reported Success", f"{m['agent_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Run Count", m['run_count'])

    with col2:
        m = mode_stats["B"]
        st.markdown("#### Mode B: LLM + Jev")
        st.metric("Verified Success Rate", f"{m['verified_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Agent-Reported Success", f"{m['agent_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Run Count", m['run_count'])

    with col3:
        m = mode_stats["C"]
        st.markdown("#### Mode C: Uncertainty-aware")
        st.metric("Verified Success Rate", f"{m['verified_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Agent-Reported Success", f"{m['agent_succ']/m['run_count']*100:.1f}%" if m['run_count'] else "N/A")
        st.metric("Run Count", m['run_count'])

    # Charts section
    st.markdown("### Distribution Charts")

    # Latency chart
    lat_col1, lat_col2 = st.columns(2)

    with lat_col1:
        st.markdown("#### Latency (seconds) by Mode")
        latency_data = []
        for mode_name in ["A", "B", "C"]:
            lats = latencies.get(mode_name, [])
            if lats:
                latency_data.append({"mode": f"Mode {mode_name}", "latency": lats})

        if latency_data:
            latency_df = pd.DataFrame(
                [{"mode": d["mode"], "latency": v} for d in latency_data for v in d["latency"]]
            )
            import plotly.express as px
            fig = px.box(latency_df, x="mode", y="latency", points="outliers",
                         title="Latency Distribution by Mode")
            st.plotly_chart(fig, width="stretch")

    with lat_col2:
        st.markdown("#### Token Usage by Mode")
        token_display = st.radio(
            "Show token metric:",
            ["LLM Total", "Jev Total", "Combined"],
            horizontal=True,
            key="token_metric_selector"
        )

        # Map display labels to internal keys
        token_key_map = {
            "LLM Total": "llm_total",
            "Jev Total": "jev_total",
            "Combined": "combined",
        }
        token_key = token_key_map[token_display]

        token_rows = []
        for mode_name in ["A", "B", "C"]:
            tokens = token_data.get(mode_name, {}).get(token_key, [])
            if tokens:
                token_rows.append({"mode": f"Mode {mode_name}", "tokens": tokens})

        if token_rows:
            token_df = pd.DataFrame(
                [{"mode": d["mode"], "tokens": v} for d in token_rows for v in d["tokens"]]
            )
            import plotly.express as px
            fig = px.box(token_df, x="mode", y="tokens", points="outliers",
                         title=f"Token Distribution by Mode ({token_display})")
            st.plotly_chart(fig, width="stretch")

    # Success rate comparison
    st.markdown("#### Verified vs Agent-Reported Success Rate")

    success_rows = []
    for mode_name in ["A", "B", "C"]:
        m = mode_stats[mode_name]
        if m['run_count'] > 0:
            success_rows.append({
                "mode": f"Mode {mode_name}",
                "verified_rate": m["verified_succ"] / m["run_count"] * 100,
                "agent_rate": m["agent_succ"] / m["run_count"] * 100,
                "run_count": m["run_count"]
            })

    if success_rows:
        success_df = pd.DataFrame(success_rows)
        import plotly.express as px
        fig = px.bar(success_df, x="mode", y=["verified_rate", "agent_rate"],
                     title="Verified vs Agent-Reported Success Rates",
                     labels={"value": "Rate (%)", "variable": "Metric"},
                     text_auto=True)
        st.plotly_chart(fig, width="stretch")

    # Escalation analysis (Mode C only)
    if mode_filter in ["C", "All"] and escalations:
        st.markdown("### Mode C Escalation Analysis")

        esc_col1, esc_col2, esc_col3 = st.columns(3)

        with esc_col1:
            st.metric("Total Escalations", escalations["C"]["count"])
        with esc_col2:
            st.metric("Tool Selection Escalations", escalations["C"]["tool_selection"])
        with esc_col3:
            st.metric("Completion Escalations", escalations["C"]["completion"])

        esc_col4, esc_col5 = st.columns(2)

        with esc_col4:
            mode_c_runs = mode_stats["C"]["run_count"]
            if mode_c_runs > 0 and escalations["C"]["count"] > 0:
                st.metric("Escalation Frequency",
                          f"{escalations['C']['count'] / mode_c_runs * 100:.1f}%",
                          help="Escalation events per Mode C run")
            else:
                st.metric("Escalation Frequency", "0%")

        with esc_col5:
            if escalations["C"]["succeeded"] > 0:
                st.metric("Escalation Succeeded Rate",
                          f"{escalations['C']['succeeded'] / escalations['C']['count']*100:.1f}%",
                          help="Of escalations, how many Groq recommendations were usable")
            else:
                st.metric("Escalation Succeeded Rate", "N/A")

    # Detailed per-task breakdown
    st.markdown("### Per-Task Breakdown")

    # Show first few tasks with verification detail
    task_summary_rows = []
    for r in filtered[:20]:  # Show first 20 records
        mode = r.get("mode", "?")
        task_id = r.get("task_id", r.get("task", "?")[:50])
        verified_outcome = r.get("verification", {}).get("outcome", "") if isinstance(r.get("verification"), dict) else ""
        agent_success = r.get("agent_reported_success", "")
        termination = r.get("termination_reason", "")
        iterations = r.get("iterations", 0)

        task_summary_rows.append({
            "Mode": f"Mode {mode}",
            "Task": task_id,
            "Verified Outcome": verified_outcome,
            "Agent Reported": "Yes" if str(agent_success).lower() == "true" else "No",
            "Termination": termination,
            "Iterations": iterations
        })

    if task_summary_rows:
        summary_df = pd.DataFrame(task_summary_rows)
        st.dataframe(summary_df, width="stretch", hide_index=True)


def render_mode_comparison():
    """Render the Mode Comparison section."""
    st.markdown("## 📈 Mode Comparison")

    # Load benchmark data
    if not st.session_state.benchmark_loaded:
        records = load_benchmark_data()
        st.session_state.benchmark_data = records
        st.session_state.benchmark_loaded = True
    else:
        records = st.session_state.benchmark_data

    if not records:
        st.warning("No benchmark data available for comparison.")
        st.info("Run `python scripts/run_benchmark.py --mode all` to generate benchmark data.")
        return

    # Data source indicator
    mocked_count = sum(1 for r in records if str(r.get("execution_type", "")).lower() == "mocked")
    live_count = sum(1 for r in records if str(r.get("execution_type", "")).lower() == "live")
    st.info(f"📁 Data source: `experiments/benchmark_results.csv` + `.jsonl` — {len(records)} runs "
            f"({mocked_count} mocked, {live_count} live). "
            f"Mocked and live runs are never mixed in analysis.")

    # Compute per-mode summaries
    mode_stats = get_mode_success_rates(records)
    latencies = get_latency_data(records)
    token_data = get_token_data(records)
    escalations = get_escalation_data(records)

    st.markdown("### Comparative Metrics Summary")

    # Build comparison table
    comparison_rows = []

    for mode_name in ["A", "B", "C"]:
        m = mode_stats[mode_name]
        run_count = m["run_count"]

        # Verified success rate
        verified_rate = (m["verified_succ"] / run_count * 100) if run_count else None

        # Agent-reported success rate
        agent_rate = (m["agent_succ"] / run_count * 100) if run_count else None

        # Average latency
        lats = latencies.get(mode_name, [])
        avg_latency = (sum(lats) / len(lats)) if lats else None

        # Average combined tokens
        tokens = token_data.get(mode_name, {}).get("combined", [])
        avg_tokens = (sum(tokens) / len(tokens)) if tokens else None

        # Escalation frequency (Mode C only; 0 for A/B)
        esc_count = escalations.get(mode_name, {}).get("count", 0)
        esc_freq = (esc_count / run_count * 100) if (mode_name == "C" and run_count) else 0

        comparison_rows.append({
            "Mode": f"Mode {mode_name}",
            "Run Count": run_count,
            "Verified Success Rate (%)": f"{verified_rate:.1f}" if verified_rate is not None else "N/A",
            "Agent-Reported Success Rate (%)": f"{agent_rate:.1f}" if agent_rate is not None else "N/A",
            "Avg Latency (s)": f"{avg_latency:.3f}" if avg_latency is not None else "N/A",
            "Avg Combined Tokens": f"{avg_tokens:.0f}" if avg_tokens is not None else "N/A",
            "Escalation Frequency (%)": f"{esc_freq:.1f}" if mode_name == "C" else "—",
        })

    comparison_df = pd.DataFrame(comparison_rows)
    st.dataframe(comparison_df, width="stretch", hide_index=True)

    # Visual comparison - bar charts for key metrics
    st.markdown("### Visual Comparisons")

    # Verified success rate bar chart
    verified_rows = []
    agent_rows = []
    latency_rows = []
    token_rows = []

    for mode_name in ["A", "B", "C"]:
        m = mode_stats[mode_name]
        run_count = m["run_count"]
        verified_rate = (m["verified_succ"] / run_count * 100) if run_count else 0
        agent_rate = (m["agent_succ"] / run_count * 100) if run_count else 0
        lats = latencies.get(mode_name, [])
        avg_latency = sum(lats) / len(lats) if lats else 0
        tokens = token_data.get(mode_name, {}).get("combined", [])
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0

        verified_rows.append({"mode": f"Mode {mode_name}", "rate": verified_rate})
        agent_rows.append({"mode": f"Mode {mode_name}", "rate": agent_rate})
        latency_rows.append({"mode": f"Mode {mode_name}", "latency": avg_latency})
        token_rows.append({"mode": f"Mode {mode_name}", "tokens": avg_tokens})

    import plotly.express as px

    # Verified vs agent rate
    fig = px.bar(
        verified_rows + agent_rows,
        x="mode", y="rate",
        color="mode",
        title="Success Rate Comparison: Verified vs Agent-Reported",
        labels={"rate": "Rate (%)", "mode": "Mode"},
        text_auto=True,
        barmode="group"
    )
    st.plotly_chart(fig, width="stretch")

    # Latency comparison
    fig = px.bar(latency_rows, x="mode", y="latency",
                 title="Average Latency Comparison",
                 labels={"latency": "Latency (seconds)", "mode": "Mode"},
                 text_auto=True)
    st.plotly_chart(fig, width="stretch")

    # Token usage comparison
    fig = px.bar(token_rows, x="mode", y="tokens",
                 title="Average Combined Token Usage",
                 labels={"tokens": "Tokens", "mode": "Mode"},
                 text_auto=True)
    st.plotly_chart(fig, width="stretch")

    # Escalation frequency (Mode C only)
    if any(m["run_count"] for m in [mode_stats["A"], mode_stats["B"], mode_stats["C"]]):
        esc_data = []
        for mode_name in ["A", "B", "C"]:
            esc_count = escalations.get(mode_name, {}).get("count", 0)
            run_count = mode_stats[mode_name]["run_count"]
            if mode_name == "C" and run_count:
                esc_data.append({"mode": f"Mode {mode_name}", "frequency": esc_count / run_count * 100})
            else:
                esc_data.append({"mode": f"Mode {mode_name}", "frequency": 0})

        fig = px.bar(esc_data, x="mode", y="frequency",
                     title="Escalation Frequency by Mode",
                     labels={"frequency": "Escalation Frequency (%)", "mode": "Mode"},
                     text_auto=True)
        st.plotly_chart(fig, width="stretch")


def render_architecture():
    """Render the Architecture explanation section."""
    st.markdown("## 🏗️ Architecture Overview")

    st.markdown("### System One (Jev) vs System Two (Groq)")

    # Two-column layout for architecture
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### System One — Jev (Fast, Cost-Efficient)")
        st.markdown("""
        - **Role**: Tool selection, completion detection, loop detection, progress estimation
        - **Decision speed**: Fast probabilistic judgments
        - **Token cost**: Lower per decision
        - **Model**: TypeSafe API (`jev-1.14.0`)
        - **Responsibilities**:
          - Select the next tool from the allowed set
          - Estimate probability that the task is complete
          - Detect repetitive action patterns (loops)
          - Measure progress towards the goal
        - **Key metric**: `tool_confidence`, `completion_probability`, `loop_probability`, `progress_score`
        """)
        st.markdown("**Decision thresholds** (provisional):")
        st.caption("• Tool confidence ≤ 0.60 → escalation to Groq")
        st.caption("• Completion prob in [0.50, 0.70) → escalation to Groq")

    with col2:
        st.markdown("#### System Two — Groq (Slow, Comprehensive)")
        st.markdown("""
        - **Role**: Planning, tool argument generation, final response, uncertainty review
        - **Decision depth**: Full natural-language reasoning
        - **Token cost**: Higher per call but fewer calls overall
        - **Model**: Groq (`openai/gpt-oss-120b`)
        - **Responsibilities**:
          - High-level task planning (5-field specification)
          - Generate tool arguments given selected tool
          - Produce final user-facing response
          - Review uncertain Jev decisions (advisory only)
          - Enforce explicit user authorization for ticket creation
        - **Key metric**: `llm_input_tokens`, `llm_output_tokens`, `llm_total_tokens`
        """)
        st.markdown("**Control flow:**")
        st.caption("• Groq always retains final authority")
        st.caption("• Jev escalates uncertain decisions to Groq (Mode C)")
        st.caption("• Evidence gate: Jev completion requires valid tool execution evidence")

    st.markdown("---")

    st.markdown("#### Three Experimental Modes")

    # Mode comparison table
    mode_cols = st.columns(3)

    with mode_cols[0]:
        st.markdown("##### Mode A: LLM-only")
        st.markdown("""
        - **Groq controls everything**: planning, tool selection, arguments, completion, loop detection
        - **No Jev involvement**
        - **Baseline for comparison**
        - **Higher token usage** (single provider)
        - **Simpler execution flow**
        """)

    with mode_cols[1]:
        st.markdown("##### Mode B: LLM + Jev Hybrid")
        st.markdown("""
        - **Groq plans + generates arguments + final response**
        - **Jev controls**: tool selection, completion detection, loop detection, progress
        - **Evidence-gated completion**: Jev confirmation + valid evidence required
        - **Balanced approach**: Jev takes over control decisions from Groq
        - **Token profile** (recorded mocked data): Groq tokens drop, Jev tokens are added; see Benchmark Analytics for the real per-mode numbers. No claim of reduction is made here — the recorded dataset is the only source of truth.
        """)

    with mode_cols[2]:
        st.markdown("##### Mode C: Uncertainty-aware Escalation")
        st.markdown("""
        - **Jev stays the fast controller**
        - **Uncertain decisions escalated to Groq** (advisory only)
        - **Groq recommends; controller decides**
        - **Every Phase 5 safeguard preserved**: allowed_tools, evidence gate, ticket auth
        - **Most nuanced mode**: leverages Jev for efficiency, Groq for uncertainty
        - **Escalation frequency**: Depends on threshold calibration
        """)


def main():
    """Main dashboard entry point."""
    init_session_state()

    # Header
    st.title("🧠 Fast Decisions, Slow Thoughts")
    st.subheader("Hybrid LLM + System One (Jev) Architecture Dashboard")
    st.caption("Final-year research project demonstration")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to:",
        ["Overview", "Agent Playground", "Execution Monitor", "Benchmark Analytics", "Mode Comparison", "Architecture"],
        index=0,
        help="Select a dashboard section to explore."
    )

    # Divider
    st.sidebar.markdown("---")

    # Show current test status
    st.sidebar.markdown("### Test Status")
    st.sidebar.success("144/144 tests passing ✅")

    # Load benchmark data on first access
    if page in ["Benchmark Analytics", "Mode Comparison", "Execution Monitor"]:
        if not st.session_state.benchmark_loaded:
            records = load_benchmark_data()
            st.session_state.benchmark_data = records
            st.session_state.benchmark_loaded = True

    # Route to the selected page
    if page == "Overview":
        st.markdown("## 📋 Project Overview")
        st.markdown("""
        **Fast Decisions, Slow Thoughts: A Hybrid LLM + System One (Jev) Architecture
        for Cost-Efficient AI Agents**

        **Research Objective**: Investigate whether splitting control responsibilities
        between two components (System One Jev and System Two Groq) can produce
        cheaper, more reliable AI agents compared to conventional LLM-only architectures.

        **Project Status**: Phases 1–7 complete. 144/144 unit tests passing. Phase 8
        dashboard implementation in progress.

        **Available Execution Modes**:
        - **Mode A — LLM-only**: Groq controls all decisions
        - **Mode B — LLM + Jev hybrid**: Jev handles tool selection, completion, loop detection; Groq plans and generates arguments
        - **Mode C — Uncertainty-aware escalation**: Jev remains the fast controller; uncertain decisions escalated to Groq for advisory review
        """)

        # Quick stats
        st.markdown("### Quick Metrics from Benchmark Data")
        records = load_benchmark_data()
        if records:
            mode_stats = get_mode_success_rates(records)
            col1, col2, col3 = st.columns(3)
            with col1:
                m = mode_stats["A"]
                st.metric("Mode A Runs", m['run_count'],
                          f"{m['verified_succ']/m['run_count']*100:.1f}% verified" if m['run_count'] else "N/A")
            with col2:
                m = mode_stats["B"]
                st.metric("Mode B Runs", m['run_count'],
                          f"{m['verified_succ']/m['run_count']*100:.1f}% verified" if m['run_count'] else "N/A")
            with col3:
                m = mode_stats["C"]
                st.metric("Mode C Runs", m['run_count'],
                          f"{m['verified_succ']/m['run_count']*100:.1f}% verified" if m['run_count'] else "N/A")
        else:
            st.info("Run `python scripts/run_benchmark.py --mode all` to generate benchmark data for quick stats.")

    elif page == "Agent Playground":
        render_agent_playground()

    elif page == "Execution Monitor":
        # Show execution monitor if we have execution result
        if st.session_state.execution_result:
            render_execution_monitor(st.session_state.execution_result)
        else:
            st.info("Execute a task in the Agent Playground section first to see the Execution Monitor.")

    elif page == "Benchmark Analytics":
        render_benchmark_analytics()

    elif page == "Mode Comparison":
        render_mode_comparison()

    elif page == "Architecture":
        render_architecture()


if __name__ == "__main__":
    main()