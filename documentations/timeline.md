Two-day implementation schedule
Target: working presentation MVP
Day 1 — Build the actual agent
1. Step 1 — Verify API access (first 1–2 hours)
   - Create or sign in to your TypeSafe account.
   - Generate an API key.
   - Check whether you have usable credits.
   - Run a Choice, Noul, and Score request.
   - Confirm that the API returns answers and usage information.
   Deliverable: a working Jev API connection.
2. Step 2 — Set up the project (30–45 minutes)
   - Create the Python environment.
   - Install dependencies.
   - Configure API keys.
   - Create the initial project structure.
   Deliverable: a runnable project with configuration.
3. Step 3 — Build the tools (1 hour)
   
   Implement three tools:
   - search_knowledge_base(query)
   - check_service_status(service)
   - create_support_ticket(issue, priority)
   Deliverable: three working Python functions.
4. Step 4 — Implement Mode A (1–2 hours)
   
   Create the LLM-only agent:
   - Generate a plan.
   - Select a tool.
   - Generate tool arguments.
   - Execute the tool.
   - Decide whether the task is complete.
   Deliverable: working baseline agent.
5. Step 5 — Implement Mode B (1–2 hours)
   
   Replace the LLM's tool-selection and completion decisions with Jev.
   - Use Choice for tool selection.
   - Use Noul for completion detection.
   - Keep LLM planning and argument generation unchanged.
   Deliverable: working LLM + Jev hybrid agent.
Day 2 — Add research functionality and presentation UI
1. Step 6 — Implement Mode C (1–2 hours)
   
   Add uncertainty-aware escalation.
   
   Initial experimental rules:
   - Choice: escalate if the probability of the selected tool is below 0.60.
   - Noul: escalate if the probability of task completion is between 0.30 and 0.70.
   These are starting thresholds, not validated optimal values. Keep them configurable.
2. Step 7 — Add experiment logging (1 hour)
   
   Record:
   - Selected tool and decision-maker.
   - Jev probabilities and confidence.
   - LLM and Jev token usage, where available.
   - API-call and total execution latency.
   - Escalation count.
   - Task success or failure.
   Calculate estimated API cost from actual usage and the providers' current prices.
3. Step 8 — Build Streamlit dashboard (1–2 hours)
   
   The user should be able to:
   - Enter a task.
   - Select Mode A, B, or C.
   - Execute the agent.
   - Inspect the reasoning/decision trace.
   - Compare results across modes.
4. Step 9 — Test and prepare presentation (1–2 hours)
   - Run the same 5–10 example tasks through all three modes.
   - Fix major failures.
   - Capture screenshots.
   - Prepare an architecture diagram and a preliminary results table.
   Label the results as preliminary MVP observations, not statistically conclusive research findings.