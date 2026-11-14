Risk 1: Is Jev actually accessible, and can you afford to use it?
Partially verified – action required
This is the first thing I would investigate before writing the agent.
What I found
Current Jev service status
Operational
November 13, 2026

99.943%
Reported API uptime on the official status page

The status page currently reports all services online.

It also records a system-overload incident on October 30, 2026, which affected the US East API endpoint for 1 hour and 15 minutes. 
status.typesafe.ai


Live TypeSafe status page

The official Quickstart instructs developers to create an API key through the TypeSafe console and use the TYPESAFE_API_KEY environment variable. 
TypeSafe


My research also found reports that public signup has reopened, but I could not independently complete a new account registration or obtain an API key. Therefore, I would classify signup access as not yet verified for your account.
Current pricing
Jev API input pricing
$0.042
Per 1 million input tokens
Item	Price
Input tokens	$0.042 / 1M
Output tokens	Free
Per-request fee	None
Minimum fee	None
Free trial credits	None for new accounts

Official pricing information, last updated November 3, 2026. 
TypeSafe Help Center


This is actually encouraging from a research-budget perspective.

Jev's input-token pricing is very low. However, don't assume that the entire hybrid architecture will be inexpensive until you account for the LLM calls it still requires.
What I want you to do
Before starting the main implementation:
1. Visit TypeSafe Console.
2. Try registering or signing in.
3. Check whether you can create an API key.
4. Check the available balance and billing requirements.
5. Run a basic Choice, Score and Noul request.
6. Record the model version, token usage, response time and API response.
My recommendation
Keep Jev as your primary research model for now, but make API access a Week 1 go/no-go checkpoint.

If access is unavailable, investigate an alternative before changing your research hypothesis.

One more consideration: Jev is accessed through a managed API; its model weights are not publicly released in the documentation I reviewed. You should not plan on self-hosting Jev locally. 
TypeSafe+1


Risk 2: Is Jev's confidence reliable enough for escalation?
Research design needs modification
This is the most important technical correction I found.

Your proposal assumes that Jev provides confidence values that can be used as escalation thresholds.

That is broadly correct, but there is a subtle distinction that your original proposal does not explain sufficiently.

Jev's confidence and the probability that its decision is correct are not necessarily the same thing.

I checked TypeSafe's current official confidence documentation.

It explicitly distinguishes these concepts. 
TypeSafe+1

Understand the difference
Suppose Jev is selecting one of four tools.

It returns this probability distribution:
Tool	Probability
Search	0.70
Calculator	0.20
Database	0.05
Respond	0.05

The selected option is Search.

Its top-option probability is 0.70.

But Jev's Choice confidence is calculated using a different formula:
\[
C = \frac{p_{\max}-1/n}{1-1/n}
\]

Where:
- \(p_{\max}\) = highest option probability.
- \(n\) = number of available options.
In this example:
\[
C = \frac{0.70-0.25}{1-0.25}=0.60
\]

So you have:
- Top-option probability = 0.70.
- Jev confidence = 0.60.
Neither number should automatically be interpreted as a guarantee of 70% or 60% correctness.
What should you use for escalation?
I recommend changing your original design slightly.
Decision primitive	What to threshold
Choice – Tool selection	Probability of the selected tool
Noul – Completion detection	Probability that the task is complete
Noul – Loop detection	Probability that the agent is looping
Score – Progress evaluation	Probability of the relevant progress level, or confidence if measuring uncertainty

For Choice, TypeSafe itself recommends inspecting the probability of the selected option rather than automatically relying on its confidence value. For Noul, the returned value is already the yes-probability. 
TypeSafe

My proposed escalation architecture
Instead of using one universal confidence threshold, I would introduce decision-specific thresholds.

For example:
Decision	Example threshold
Tool selection	0.80
Task completion	0.90
Loop detection	0.85

These are initial experimental settings, not established optimal values.

Why different thresholds?

Because the consequences of a wrong decision differ.
- Choosing the wrong search tool might waste one execution step.
- Incorrectly declaring a task complete might cause the agent to return an incomplete answer.
- Missing a loop might result in repeated tool calls and unnecessary expense.
Your experiments should establish which thresholds work best.
An additional research development
I also found a relevant 2026 preprint:

What Confidence Routing Is Actually Doing: Auditing Routing, Calibration, and Commitment in Multi-Agent Deliberation.

It investigates whether reported confidence actually reflects correctness and whether confidence-based routing works reliably.

One reported experiment found that a model's mean stated confidence was 79%, while its accuracy was only 52%. This is a different model and experimental setting, so those numbers cannot be transferred to Jev. However, the study demonstrates why confidence calibration needs to be measured rather than assumed. 
arXiv


This is a preprint, not a peer-reviewed validation of Jev.
Read the 2026 confidence-routing studyWhat I recommend adding to your research
Add three separate analyses:
1. Confidence calibration: Does Jev's confidence correspond to empirical correctness?
2. Decision discrimination: Can its scores distinguish correct decisions from incorrect decisions?
3. Selective escalation: Does escalating uncertain decisions actually improve task success at an acceptable cost?
This is stronger than merely testing five thresholds.
My recommendation
Keep RQ3, but refine it to explicitly distinguish confidence, probability and correctness.

This will make your research methodology more rigorous.

Risk 3: Will your experiments provide a fair comparison?
Methodology needs strengthening
This is where I would make some important modifications to your experimental methodology.

Your original proposal is correct in principle: compare A, B and C using the same benchmark.

But there are some things that could make your results misleading if you don't control them.
A. Benchmark selection needs to be finalized
Your proposal originally suggested tau-bench or a custom benchmark.

Now that τ-bench 2.0 is available, I would reconsider the benchmark decision.
Updated benchmark options
Option 1: τ-bench 2.0
Recommended for exploration









sierra.ai


- Realistic multi-step tool-use tasks.
- Airline, retail and other structured domains.
- Simulated users and tool environments.
- Updated evaluation and grading infrastructure.
Limitation: Integration and configuration may consume a significant part of your nine-week development period.

Source: official τ-bench release notes. 
GitHub+1


τ-bench GitHub repository

Option 2: Custom controlled benchmark
My recommendation for your core experiment
- 30–50 carefully designed tasks.
- Fixed set of tools.
- Automatic task verification.
- Easy collection of decision-level traces.
- Easier comparison between architectures.
This is the fallback option already included in your proposal.

My recommendation is to build the custom benchmark as your primary experimental environment, unless you can successfully run a small τ-bench pilot during the first week.

You could use τ-bench as an additional external validation experiment if time permits.

Why do I prefer a custom benchmark here?

Because your research is specifically about the agent's internal control decisions, not simply its ability to complete complex customer-service conversations.

You need to observe and evaluate every decision.
B. Make the comparison experimentally fair
I would enforce the following controls:
Experimental variable	What must remain consistent
User tasks	Exactly the same task set
Main LLM	Same model and version
LLM prompts	Same planning and generation instructions
Tools	Same tools and implementations
Tool outputs	Same environment and data
Execution limits	Same maximum steps and timeout
Sampling	Same generation settings
Verification	Same task success criteria

For every task, run A, B and C under comparable conditions.

Use paired task identifiers and repeated runs.

For example:
Experimental execution
Task 001 – Population calculation

A

LLM-only
Run 1–3

B

Hybrid
Run 1–3

C

Escalation
Run 1–3


Repeat for every benchmark task, with controlled execution settings.

With 40 tasks and three runs per variant, you will have:
\[
40 \times 3 \times 3 = 360
\]

task executions.

That is a reasonable starting experimental workload.

Use paired comparisons, confidence intervals and appropriate statistical tests rather than comparing only three aggregate percentages.
C. Your gold control decisions need improvement
Your original proposal says that you will derive gold decisions from successful LLM-only traces.

There is a problem with that approach.

Suppose both Search and Database Lookup could successfully retrieve the required information.

If your reference trace says Search, Jev selecting Database Lookup should not automatically be considered incorrect.

There may be multiple valid decisions.

I recommend using:
- Valid-action sets rather than always requiring one exact tool.
- Deterministic verification of task completion.
- An explicit operational definition of an agent loop.
- Manual verification of ambiguous decisions.
For loop detection, for example, you could define a loop as repeated equivalent actions that produce no meaningful change in the environment state.

This is much more defensible than simply asking an LLM judge whether the agent is looping.
D. One important inconsistency in your original architecture
I noticed something in your proposal that I would correct before implementation.

Your Variant B delegates tool selection and completion detection to Jev.

Your Week 5 description of Variant C additionally mentions implementing loop detection.

This creates a potential experimental confound: if C introduces a new delegated decision type as well as escalation, you won't know which change caused an improvement or degradation.

My recommendation:

Keep the delegated decision types identical in B and C.
Decision	A	B	C
Tool selection	LLM	Jev	Jev + fallback
Completion check	LLM	Jev	Jev + fallback
Loop detection	LLM	Jev	Jev + fallback
Complex reasoning	LLM	LLM	LLM
Content generation	LLM	LLM	LLM

Now the only major architectural difference between B and C is the escalation mechanism.

That makes your experiment much cleaner.
E. One more architectural issue: Who generates tool arguments?
You need to clearly separate three responsibilities:
1. Planning: What needs to be accomplished?
2. Tool selection: Which tool should execute next?
3. Argument generation: What inputs should be passed to that tool?
My recommended hybrid approach is:
- LLM generates the high-level plan.
- Jev selects the next tool from the available tools.
- LLM generates the arguments for the selected tool when necessary.
- The tool executes.
- Jev evaluates the updated state.
This distinction is important because Jev is not a text-generation model. It cannot be expected to generate arbitrary tool arguments or the final natural-language answer.

Also, your baseline should use the same planning strategy, with the LLM selecting the tool and generating its arguments.

That gives you a meaningful comparison of the control-decision mechanism.

Risk 4: Are you measuring the actual cost and latency savings?
Measurement methodology needs expansion
This is the last of the four major risks, and it directly affects your main research claim.

Your proposal says that you will measure:
- Number of LLM calls.
- Total tokens.
- Cost per task.
- Mean latency.
- P95 latency.
That's a good foundation.

However, I would expand the measurement pipeline.
A. Cost calculation
Your hybrid architecture has two model providers.

Therefore:
\[
C_{\text{total}} =
C_{\text{LLM}} + C_{\text{Jev}}
\]

For the LLM:
\[
C_{\text{LLM}} =
\frac{T_{in}}{10^6}P_{in}
+
\frac{T_{out}}{10^6}P_{out}
\]

For Jev, using the current published pricing:
\[
C_{\text{Jev}} =
\frac{T_{\text{Jev-in}}}{10^6}
\times 0.042
\]

Where the token quantities are actual measured usage and the prices are in USD per million tokens.

You must use the selected LLM provider's actual pricing at experiment time. Don't hardcode a price from today's search results into a future experiment.

Also include failed calls, retries and additional escalation calls in your accounting.
B. Latency calculation
This is another important distinction.

Suppose Jev responds in 100 ms, but then the agent requires an LLM call that takes 1.5 seconds.

Your hybrid system did not complete the decision in 100 ms.

You need to measure the complete execution time.
\[
T_{\text{total}} =
T_{\text{planning}}
+
T_{\text{decision}}
+
T_{\text{tool}}
+
T_{\text{generation}}
+
T_{\text{overhead}}
\]

This is a simplified representation of the workflow; actual timings depend on which operations run sequentially or in parallel.

Record:
Measurement	Purpose
LLM API latency	Main model response time
Jev API latency	Decision-model response time
Tool latency	Execution time of tools
Total task latency	Actual user-perceived completion time
P50 latency	Typical performance
P95 latency	Slow-tail performance

C. Take advantage of Jev's parallel questions
This is another reason the new API documentation matters.

Jev can evaluate multiple independent questions in parallel within one request. 
TypeSafe+1


For example, given the same agent-state snapshot, you can ask:
- Is the task complete?
- Is the agent looping?
- How much progress has been made?
You could receive all three answers in a single API request.

This may reduce network overhead compared with making three independent calls.

However, don't parallelize decisions that depend on one another. For example, you shouldn't execute a selected tool until you have established that the task isn't already complete.
D. Add cost per successful task
I would add one more metric:
\[
Cost_{\text{successful task}} =
\frac{\text{Total experiment cost}}
{\text{Number of successfully completed tasks}}
\]

This is particularly useful.

Imagine:
- Agent A costs $0.05 per task and succeeds 95% of the time.
- Agent B costs $0.02 per task but succeeds 60% of the time.
Looking at cost per attempt alone could make B look attractive.

But cost per successful task provides a different perspective.

You should report both.
My recommendation
Build a centralized experiment logger from the beginning. Every model call, tool execution, retry, escalation and task outcome should be recorded.

Do not wait until Week 6 to start collecting data.