
# Phase 2: Jev Client Wrapper Architecture

## 1. Objective

Integrate TypeSafe Jev into the hybrid agent architecture
through a reusable Python client.

## 2. Design

A dedicated JevClient class abstracts the TypeSafe SDK.

Agent implementations interact with JevClient rather
than directly communicating with the SDK.

## 3. Decision Primitives

| Primitive | Application |
|---|---|
| Choice | Agent tool selection |
| Noul | Task completion detection |
| Noul | Agent loop detection |
| Score | Task progress estimation |

## 4. Batched Decision Evaluation

The evaluate_state() method submits four independent
questions against a shared agent state.

This allows the system to obtain multiple control
signals through one Jev request.

The questions are:

1. Which tool should be selected next?
2. Has the user task been completed?
3. Has the agent entered a repeated-action loop?
4. How much progress has been made?

The available tool choices are supplied dynamically.

## 5. Response Structure

JevDecisionResult contains:

| Field | Description |
|---|---|
| selected_tool | Selected tool |
| tool_probabilities | Probability distribution over tools |
| tool_confidence | Jev Choice confidence |
| completion_probability | Probability that the task is complete |
| loop_probability | Probability that the agent is in a loop |
| progress_score | Estimated task progress |
| model | Actual Jev model identifier |
| input_tokens | Input token usage |
| output_tokens | Output token usage |
| total_tokens | Total token usage |
| latency_seconds | Request latency |

## 6. Loop Prevention

Jev loop detection is treated as a probabilistic
diagnostic signal.

A separate deterministic safeguard will enforce
maximum execution steps and detect repeated actions.

## 7. Configuration

The following environment variables are used:

- TYPESAFE_API_KEY
- JEV_MODEL

The default configured model is `jev-latest`.

The resolved model identifier returned by Jev
must be recorded in experiment logs.

## 8. Experimental Considerations

Choice confidence and the probability of the selected
option are distinct measurements.

For uncertainty-aware escalation, the selected-option
probability will be evaluated separately.

For Noul, values near 0.5 indicate ambiguity.
Low probabilities should not automatically be
interpreted as low confidence.

Progress estimates are diagnostic and must not
replace independent task verification.

## 9. Next Phase

Implement the simulated customer-support tools and
their centralized registry.
