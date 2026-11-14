# Phase 3: Customer-Support Tools and Shared Registry

## 1. Objective

The objective of Phase 3 is to implement a set of deterministic, local customer-support tools and a common registry that can be accessed by all three agent configurations:

- Mode A: LLM-only
- Mode B: LLM + Jev
- Mode C: Hybrid with uncertainty escalation

All modes must use identical tool implementations and execution interfaces.

## 2. Implemented Tools

### 2.1 Knowledge Base Search

Function: `search_knowledge_base(query)`

- Reads support articles from `data/knowledge_base.json`.
- Uses token normalization and keyword overlap for retrieval.
- Ranks results by matching-token ratio.
- Returns up to three matching articles.
- Uses deterministic sorting to make repeated searches reproducible.

This is a basic lexical retrieval implementation, not embedding-based semantic search.

### 2.2 Service Status

Function: `check_service_status(service)`

- Uses a fixed local dictionary of simulated service states.
- Supports internet, Wi-Fi, VPN, email, payment portal, and student portal.
- Supports a small set of service aliases.
- Returns `unknown` for services not in the dataset.
- Identifies the result source as `local_simulation`.

No real infrastructure or external monitoring service is queried.

### 2.3 Support Ticket Creation

Function: `create_support_ticket(issue, priority)`

- Creates simulated tickets in memory.
- Accepts low, medium, and high priorities.
- Generates sequential ticket IDs.
- Returns the created ticket details.
- Does not connect to a real ticketing platform.
- Tickets are cleared when the application process restarts.

A reset operation is provided so that independent experiment episodes can start with a clean ticket state.

## 3. Shared Tool Registry

File: `tools/registry.py`

The registry centralizes tool definitions and execution.

It provides:

- `get_tool_names()` — returns registered tool names.
- `get_tool_descriptions()` — provides tool descriptions for Jev.
- `get_llm_tool_schemas()` — provides OpenAI-compatible function schemas for the Groq LLM.
- `get_tool(name)` — retrieves a tool definition.
- `execute(name, arguments)` — validates arguments and executes a tool.
- `reset_state()` — resets simulated mutable ticket state before an independent experiment episode.

The registry ensures that all agent modes share the same tool names, descriptions, argument schemas, and Python functions.

## 4. Experiment Design Considerations

Using a shared registry is important for a fair comparison between the three agent configurations.

The following must remain constant:

- Tool implementations.
- Tool descriptions.
- Tool argument schemas.
- Tool execution behavior.
- Simulated knowledge base.
- Simulated service-status dataset.
- Ticket creation behavior.
- Task inputs and experiment limits.

Only the agent's decision-making strategy should change between modes.

The ticket manager should be reset before each independent benchmark episode so that ticket IDs and stored state do not depend on the order in which modes are evaluated.

## 5. Testing

Focused tests are provided in `tests/test_tools.py`.

They cover:

- Knowledge base retrieval.
- Empty query validation.
- Service-status lookup and aliases.
- Unknown service handling.
- Ticket creation and priority validation.
- Registry tool listing and execution.
- Missing arguments and unknown tool handling.
- LLM schema and Jev description consistency.
- Ticket-state reset.

## 6. Limitations

The tools are deliberately simulated:

1. Knowledge retrieval uses keyword matching rather than semantic embeddings.
2. Service status is static and does not represent live infrastructure.
3. Support tickets are stored only in memory.
4. Ticket IDs are sequential and reset with the simulated state.

These limitations are acceptable for the initial MVP because the primary research objective is to compare decision-making strategies, not to develop a production customer-support platform.

## 7. Completion Criteria

Phase 3 can be marked complete once:

- All three tools are implemented.
- The shared registry exposes the three tools.
- Jev descriptions and LLM schemas use identical tool names.
- All focused tests pass.
- Ticket state can be reset between independent experiment episodes.
- The implementation is documented.

## 8. Next Phase

Phase 4 will implement the common agent control loop and the LLM-only baseline. This will establish the reference implementation against which the Jev-assisted configurations can be compared.