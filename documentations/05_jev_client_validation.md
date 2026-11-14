# Jev Client Integration and Validation

## 1. Objective

Validate the custom Jev client wrapper using the TypeSafe SDK and confirm that it can retrieve structured System One decisions for the hybrid agent architecture.

## 2. Test Configuration

| Parameter | Value |
|---|---|
| Provider | TypeSafe |
| Configured model | `jev-latest` |
| Actual model returned | `jev-1.14.0` |
| Decision primitives | Choice, Noul, Score |
| Questions per request | 4 |

## 3. Test Results

The test successfully returned the following outputs:

| Decision | Result |
|---|---|
| Selected tool | `service_status` |
| Tool probabilities | knowledge_search: 0.15; service_status: 0.85; create_ticket: 0.00 |
| Choice confidence | 0.77 |
| Completion probability | 0.03 |
| Loop probability | 0.03 |
| Progress score | 0.05 |

## 4. API Metadata

| Metric | Observed value |
|---|---:|
| Input tokens | 535 |
| Output tokens | 92 |
| Total tokens | 627 |
| Latency | 1.6806 seconds |
| Actual model | `jev-1.14.0` |

## 5. Validation Outcome

**Status: PASSED**

The integration test confirms that:

- The TypeSafe SDK successfully connects to the Jev service.
- The client submits all four structured decision questions in a single request.
- Choice, Noul, and Score outputs are retrieved successfully.
- Tool-selection probabilities and confidence are accessible.
- Model version, token usage, and request latency are captured.

## 6. Limitations

This test validates API integration and output retrieval only. It does not establish decision accuracy, probability calibration, loop-detection reliability, or task-completion accuracy. These properties require evaluation across a larger set of controlled tasks.

## 7. Next Step

Proceed to Phase 3: implement the simulated customer-support tools and a common tool registry for all three agent modes.