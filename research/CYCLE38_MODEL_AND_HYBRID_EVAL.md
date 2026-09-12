# Cycle 38: target-model validation and hybrid retrieval

Date: 2026-09-11

Cycle 37 finished the v8 storage pivot and proved incremental versus clean-build
parity, but it deliberately stopped short of claiming answer accuracy. Cycle 38
used the explicitly authorized local NIM credential to close part of that gap and
tested the two remaining runtime questions: whether the relation seed should stay
enabled by default on a behavior oracle, and whether the optional local encoder
earns its storage and query cost.

The complete machine-readable record is
[`cycle38-model-hybrid-eval-v1.json`](../experiments/results/cycle38-model-hybrid-eval-v1.json).
The raw NIM run is
[`cycle38-repository-live-v1/results.json`](../experiments/runs/cycle38-repository-live-v1/results.json);
the optional hybrid run is
[`cycle38-repository-semantic-v1/results.json`](../experiments/runs/cycle38-repository-semantic-v1/results.json).
No credential value is stored in these reports.

## Observe

The current repository evaluator contains 12 executable urllib3 2.7.0 behavior
questions with exact JSON answers and required source spans. At a 2,000-token
selection budget, the current member-index arm retained every required span on
5/12 tasks and covered 58.33% of required span groups. The body-window arm retained
every required span on 2/12 tasks and covered 34.72%.

The existing selector enables the conservative `raises` relation channel by
default. On this oracle, a local paired challenger with that channel disabled
covered 62.5% of required span groups and retained every required span on 5/12
tasks. This conflicts with the larger frozen Cycle 37 replay, where the relation
channel raised retention from 205/246 to 223/246 at 2,048 tokens. The two corpora
therefore do not justify changing the default from a 12-task result.

## Hypothesize

1. A stronger answer model would turn source coverage differences into a useful
   answer-quality measurement if its output protocol and latency were stable.
2. Disabling relation seeds might reduce distractors on the urllib3 oracle, even
   though the relation arm won the older 246-question replay.
3. A local MiniLM hybrid arm might recover low-scoring neighboring evidence, but it
   must earn its compilation, artifact-size, and query-time costs.
4. Raising the candidate limit might expose required blocks currently hidden below
   the top-ranked pool without changing the greedy budget policy.

## Measure

The primary live run used `meta/llama-3.2-11b-vision-instruct`, temperature 0,
384 output tokens, and 48 sequential calls: 12 tasks across no-context,
full-context, body-window, and member-index arms. Every request had successful
transport. Exact grading required valid JSON with the task's exact expected types
and values.

| Live arm | Parseable responses | Exact answers | Exact rate | Total provider tokens |
|---|---:|---:|---:|---:|
| No context | 1/12 | 0/12 | 0% | 3,110 |
| Full context | 0/12 | 0/12 | 0% | 985,569 |
| Body-window BM25 | 11/12 | 0/12 | 0% | 17,124 |
| Definition/member BM25 | 11/12 | 3/12 | 25% | 20,315 |

The three exact member-arm answers were `retry_after_eligibility`,
`server_delay_cap`, and `redirect_header_scope`. The result is evidence that the
member arm can produce useful context for this model, but it is not a promoted
answer-quality advantage because the controls were protocol-limited and the sample
is a single developer-known task set.

The relation-disabled member challenger used the same Llama configuration for 12
additional calls. It produced 4/12 exact answers and 11/12 parseable responses;
the successful tasks were `post_error_categories`, `retry_after_eligibility`,
`server_delay_cap`, and `redirect_header_scope`. This small result does not settle
the conflict with the broader Cycle 37 replay, so the default relation setting is
unchanged.

The offline local-encoder run compiled 657 member blocks with the pinned
`sentence-transformers/all-MiniLM-L6-v2` revision in 15.26 seconds. At 2,000
tokens, hybrid coverage was 53.47% with 2/12 all-span tasks and a 5.80 ms median
selection time; member BM25 was 58.33% with 5/12 all-span tasks and a 3.32 ms
median. At 4,000 tokens, hybrid reached 77.78% and 8/12 all-span tasks versus
76.39% and 7/12 for member BM25. The hybrid artifact was 2,486,272 bytes versus
1,138,688 bytes for member BM25. The hybrid arm remains an explicit option because
its advantage appears only at the larger measured budget and is not yet tied to
answer accuracy.

Candidate limits of 30, 60, 120, 240, and 480 produced the same 58.33% retained
span coverage and 5/12 all-span tasks for member BM25 at 2,000 tokens; higher
limits increased median local selection time from about 2.72 ms to 5.63 ms. This
challenger is discarded.

The NIM model canaries also exposed evaluator constraints. Four Nemotron calls
all exhausted the 384-token ceiling without grader-acceptable JSON. A four-call
DeepSeek canary produced one valid full-context answer and timed out on the three
shorter arms. Those canaries are not retrieval comparisons.

## Attack and decision

The live answers show why source coverage and answer accuracy must remain separate
metrics. Full context used roughly 986K provider tokens across the controls but
produced no parseable exact answers under the chosen output cap, while the compact
member arm produced three exact answers. That is a useful observation about this
model and protocol, not proof that the compiler preserves or improves answers.

The relation channel remains enabled by default because the older 246-question
replay is the broader measured retrieval comparison. The new oracle is retained as
a counterexample and requires a multi-repository paired study before a default
change. The local encoder remains available only through explicit hybrid selection;
it did not earn promotion at the primary 2,000-token budget. Candidate-limit
inflation is discarded.

The default product path still makes zero generative calls. NIM is used only by the
opt-in answer evaluator, and all live responses record transport status, raw usage,
request identity, source hashes, and exact grading outcomes.

## Next highest-value hypothesis

Run the same paired answer protocol on at least three independently selected
repositories, with a stable structured-output-capable model and a fixed timeout
budget. Compare body-window, member BM25, relation-disabled member BM25, relation-
enabled member BM25, and hybrid arms using exact answers, required-span coverage,
candidate coverage, selected tokens, latency, memory, and provider usage together.
Only then decide whether relation seeds belong in the default or whether the
runtime should expose a conservative corpus-aware policy. Any allocator change
must beat the fixed member BM25 baseline on held-out answer outcomes while
preserving v8 source parity and zero-generative default behavior.
