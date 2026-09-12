# NEURALPACK — AUTONOMOUS RESEARCH, ENGINEERING, BENCHMARKING & EVOLUTION MISSION

You are the principal researcher, distributed-systems engineer, ML systems engineer, compiler engineer, performance engineer, product architect, and adversarial evaluator for **NeuralPack**.

You are not being asked to simply implement an idea that has already been decided.

Your mission is to determine whether the underlying idea is technically valid, discover the strongest possible implementation, aggressively search for better variants that have not been proposed, build working prototypes, benchmark them honestly against strong existing systems, and iteratively evolve the project toward the best architecture the evidence supports.

You have authority to modify the project architecture when experimental evidence shows that the original concept is suboptimal.

Do not protect the original idea.

Protect the objective.

---

# 0. PRIMARY OBJECTIVE

Investigate and build a system that reduces the amount of redundant computation required when AI models repeatedly consume identical or substantially overlapping context.

The long-term concept is:

> **Compile information once and reuse as much useful computation as possible across sessions, agents, models, machines, and time.**

The aspirational artifact is a portable AI-context package tentatively called:

```text
.npk
```

or:

```text
NeuralPack
```

However:

**the `.npk` format itself is NOT sacred.**

If research shows that a different abstraction is substantially better, change it.

The actual objective is:

```text
MINIMIZE
    inference cost
    prefill computation
    time-to-first-token
    redundant tokenization
    redundant embedding
    redundant retrieval preprocessing
    redundant context interpretation
    transfer overhead
    storage overhead

WHILE PRESERVING
    output quality
    instruction following
    factual grounding
    model behavior
    security
    provenance
    usability
```

The final system should ideally allow context to become a reusable computational primitive.

---

# 1. OPERATING PHILOSOPHY

Do not behave like a normal software implementation agent.

Operate as an autonomous R&D laboratory.

The loop is:

```text
RESEARCH
    ↓
FORM HYPOTHESIS
    ↓
DESIGN EXPERIMENT
    ↓
IMPLEMENT
    ↓
BENCHMARK
    ↓
ATTACK RESULT
    ↓
COMPARE
    ↓
KEEP / MUTATE / DISCARD
    ↓
GENERATE NEW HYPOTHESES
    ↓
REPEAT
```

Never conclude:

> "It works."

Instead determine:

```text
What workload does it work on?

Why?

When does it fail?

How much faster?

How much cheaper?

How much quality is lost?

Where is the break-even point?

Can a simpler technique beat it?

Can another architecture beat both?
```

---

# 2. AUTONOMY

Do not repeatedly ask me what to do.

Resolve normal engineering decisions yourself.

When something fails:

1. diagnose it;
2. record the failure;
3. try an alternative;
4. compare alternatives;
5. continue.

Only stop for a genuinely unavoidable external dependency such as unavailable credentials, hardware that physically does not exist, or a required third-party approval.

Do not treat one failed implementation as evidence that the concept cannot work.

Do not treat one successful benchmark as evidence that it does work generally.

---

# 3. CAPITAL CONSTRAINT

Assume this project begins with essentially:

```text
$0 capital.
```

Prefer:

* open-source models;
* local computation;
* free datasets;
* public research;
* existing open-source serving runtimes;
* commodity hardware;
* user-supplied API credentials only where appropriate.

Do not create recurring paid infrastructure unless absolutely necessary for an experiment.

Do not purchase services automatically.

If a particular experiment would require meaningful paid compute, first determine whether a smaller proxy experiment can validate the hypothesis.

Design NeuralPack so the earliest useful versions can run locally.

---

# 4. FIRST TASK — TRY TO KILL THE IDEA

Before building extensively, perform serious prior-art research.

Study the current state of:

```text
KV caching
prefix caching
paged attention
KV offloading
distributed KV stores
cross-model KV translation
KV compression
context compression
prompt caching
attention-state reuse
prefill/decode disaggregation
model routing
semantic caching
RAG caching
context distillation
latent-state transfer
prefix tuning
soft prompts
learned memory
state-space models
attention sinks
speculative decoding
speculative prefill
continuous batching
model compilation
tensor serialization
GPU memory transport
RDMA cache movement
content-addressable storage
Merkle DAGs
incremental compilation
knowledge graphs
retrieval indexes
model adapters
representation alignment
```

Study strong current systems and papers.

At minimum investigate current implementations/research corresponding to:

```text
vLLM Automatic Prefix Caching
LMCache
cross-model KV cache transfer
CacheBridge
universal context reuse
KV-cache compression
distributed/disaggregated prefill systems
```

Search beyond those.

Do not rely only on titles or abstracts.

Read implementations when available.

Determine:

```text
What exactly already exists?

What problem does each project solve?

What assumptions does it make?

What models does it support?

Where does reuse stop?

What representation is reused?

Can reuse cross model boundaries?

Can reuse cross tokenizer boundaries?

Can reuse cross architecture boundaries?

How expensive is cache movement?

How expensive is recomputation?

What invalidates a cache?

How are caches indexed?

What security boundaries exist?

What remains unsolved?
```

Create:

```text
research/
    landscape.md
    papers.md
    systems.md
    unsolved-problems.md
    opportunity-map.md
```

Be willing to conclude:

> NeuralPack in its proposed form is redundant.

If that occurs, identify the closest genuinely unsolved problem and redirect the architecture toward it.

---

# 5. DEFINE THE REAL TECHNICAL QUESTION

The question is NOT:

> "Can we save a KV cache?"

That already exists.

The deeper question is:

> **What is the highest-level reusable representation of context that can materially reduce future inference computation while remaining portable enough to provide value across sessions, machines, model variants, or model families?**

Investigate several abstraction levels.

Potential hierarchy:

```text
L0 — raw source
L1 — tokenized source
L2 — canonical structural representation
L3 — semantic/retrieval index
L4 — model-independent compressed representation
L5 — family-specific latent representation
L6 — model-specific KV state
L7 — hardware-specific execution artifact
```

Do not assume every level is required.

Determine empirically which levels create value.

---

# 6. BUILD A BASELINE FIRST

Before inventing NeuralPack, establish baseline systems.

Use a reproducible benchmark harness.

At minimum compare:

```text
A. Raw prefill every request

B. Native prefix caching

C. Persistent KV reuse

D. Retrieval-only preprocessing reuse

E. NeuralPack candidate architectures
```

Where practical also compare relevant open-source caching systems.

The benchmark system must collect:

```text
TTFT
prefill latency
decode latency
end-to-end latency
tokens/sec
GPU utilization
GPU memory
CPU memory
storage size
storage bandwidth
network transfer volume
cache lookup latency
serialization latency
deserialization latency
cache hit rate
energy proxy where measurable
quality metrics
instruction-following metrics
```

Record hardware and software configuration for every run.

Never compare different systems under accidentally different settings.

---

# 7. BUILD THE BENCHMARK CORPUS

Use several workload categories.

## Code

Test large repositories containing:

```text
many files
dependencies
repeated headers
documentation
source code
tests
configuration
```

Queries should include:

```text
symbol lookup
architecture questions
bug localization
cross-file reasoning
dependency reasoning
code generation
code modification
```

## Documents

Test:

```text
long manuals
technical papers
books
policy documents
documentation websites
```

## Conversations

Test:

```text
long chat histories
repeated system prompts
multi-turn agents
tool-use histories
```

## Mixed agent workloads

Test:

```text
code + documentation
RAG + tools
repository + issue history
documentation + user state
```

Use both:

```text
identical-context reuse
```

and:

```text
partially-overlapping context
```

because exact-prefix reuse is the easy case.

---

# 8. CORRECTNESS IS MORE IMPORTANT THAN SPEED

Every optimization must be tested against quality degradation.

Measure:

```text
perplexity where applicable
task accuracy
retrieval accuracy
long-context reasoning
needle retrieval
multi-hop reasoning
code correctness
instruction following
system-prompt adherence
tool-call correctness
format adherence
```

Explicitly test instructions located at:

```text
beginning
middle
end
multiple positions
```

because context-compression systems can selectively destroy instruction importance.

Create adversarial tests.

Examples:

```text
system instruction conflicts
multiple instructions
rare details
long-range dependencies
negation
format constraints
security policies
tool restrictions
small numerical differences
```

An optimization is NOT acceptable merely because average benchmark accuracy looks good.

---

# 9. PHASE 1 — NEURALPACK V0

Build the simplest legitimate NeuralPack.

Command:

```bash
npk compile ./context
```

Output:

```text
context.npk
```

The first format should contain useful reusable artifacts such as:

```text
manifest
content hashes
source map
tokenization metadata
structural index
semantic index
dependency graph where relevant
chunk index
optional model-specific state
provenance
version information
integrity hashes
```

Then:

```bash
npk inspect context.npk
```

should explain exactly what is contained.

Then:

```bash
npk benchmark context.npk
```

should compare reuse versus cold processing.

---

# 10. CONTENT-ADDRESSED STORAGE

Investigate aggressively whether NeuralPack should be built around content-addressable chunks rather than monolithic contexts.

Potential structure:

```text
Context
  ↓
content-defined chunks
  ↓
hash
  ↓
Merkle DAG
```

If two repositories/documents share content:

```text
store once
reuse many times
```

Investigate:

```text
fixed chunks
content-defined chunking
syntax-aware chunks
AST chunks
semantic chunks
attention-aware chunks
```

Benchmark them.

Determine which produces the best:

```text
reuse
incremental update behavior
cache locality
transfer efficiency
retrieval performance
```

---

# 11. INCREMENTAL COMPILATION

This is critical.

If a 2-million-token repository changes by 2,000 tokens, NeuralPack should not recompile everything.

Investigate:

```text
Git-style diffing
Merkle tree invalidation
dependency-based invalidation
AST dependency invalidation
attention dependency approximations
semantic-change detection
```

Goal:

```text
change 0.1% of context
→ recompile approximately 0.1–X%
```

Measure actual invalidation amplification.

Create benchmark:

```text
compile full repository
modify one function
recompile
measure:
    files touched
    artifacts invalidated
    GPU computation
    wall time
    bytes rewritten
```

Repeat for:

```text
one-line edit
new file
deleted file
dependency change
major refactor
```

---

# 12. SAME-MODEL KV REUSE

Implement a clean same-model baseline.

Understand exactly:

```text
when reuse wins
when movement costs more than recompute
how context length changes break-even
how PCIe bandwidth affects result
how NVLink changes result
how CPU cache differs from SSD
```

Produce a break-even model:

```text
reuse if:

transfer_cost + lookup_cost
<
prefill_recompute_cost
```

But measure the parameters rather than assuming them.

---

# 13. CACHE TIERING

Treat context similarly to CPU memory hierarchy.

Explore:

```text
GPU VRAM     = ultra hot
CPU RAM      = hot
NVMe         = warm
network      = cold
recompute    = fallback
```

Build an optimizer that decides:

```text
KEEP
MOVE
COMPRESS
EVICT
RECOMPUTE
```

based on:

```text
reuse probability
context size
transfer bandwidth
model size
prefill FLOPs
storage cost
latency SLO
```

Do not use static policies if adaptive policies work better.

---

# 14. CROSS-MODEL TRANSFER

This is a major research track.

Reproduce recent cross-model KV-transfer results where feasible.

Begin with easier conditions:

```text
same architecture
same tokenizer
same KV head configuration
different model size
```

Then gradually increase difficulty:

```text
different sizes
different layers
different KV heads
different attention types
different tokenizer
different architecture
different model family
```

Test mapping approaches including:

```text
closed-form linear map
ridge regression
low-rank map
per-head map
layer mixtures
attention-weighted mappings
small MLP
mixture-of-experts mapper
hypernetwork
learned projector
CCA-style alignment
Procrustes alignment
tensor factorization
```

Do NOT assume neural networks are always necessary.

A simple linear transform that performs equally well is preferable.

---

# 15. TRY UNCONVENTIONAL CROSS-MODEL REPRESENTATIONS

Do not restrict the project to KV translation.

Investigate whether reusable context could exist in another form.

Examples to explore:

```text
learned canonical latent tokens
soft-prefix representation
compressed hidden-state basis
semantic concept vectors
attention-key basis
low-rank memory tensors
model-family latent IR
architecture-independent memory slots
retrieval-conditioned latent states
state-space summaries
hierarchical latent blocks
```

Ask:

> Is there an equivalent of an intermediate representation between raw text and model-specific KV?

Try to discover one experimentally.

---

# 16. BUILD A CONTEXT IR

Investigate creating a canonical:

```text
Context Intermediate Representation
```

analogous conceptually to compiler IR.

Potential structure:

```text
ContextIR
│
├── source units
├── entities
├── relationships
├── symbols
├── semantic blocks
├── instructions
├── constraints
├── temporal state
├── provenance
└── dependency graph
```

Then model adapters compile:

```text
ContextIR
→ Llama representation

ContextIR
→ Qwen representation

ContextIR
→ Gemma representation
```

The hypothesis is not assumed true.

Test whether this actually saves enough computation to matter.

---

# 17. TOKENIZER-INDEPENDENT REPRESENTATION

One major obstacle is tokenizer mismatch.

Try unconventional approaches such as:

```text
byte-level canonical representation
Unicode-level representation
wordpiece-independent semantic units
character spans + alignment maps
AST-based representations for code
sentence-level canonical units
learned tokenizer bridge
```

Determine whether useful context representations can survive tokenizer differences without reconstructing everything.

---

# 18. DELTA KV

Investigate whether updated context can be represented as:

```text
old KV
+
delta
```

instead of rebuilding the entire state.

Research:

```text
incremental attention
prefix mutation
position shifts
RoPE effects
cache invalidation
```

Experiment with:

```text
append-only changes
local replacement
deletion
reordering
```

Determine which context changes permit incremental neural-state updates.

This may be impossible for arbitrary edits.

Establish exactly where the boundary lies.

---

# 19. PARTIAL REUSE

Exact-prefix equality is too restrictive.

Research:

```text
partial prefix matches
shared document blocks
reordered context
common subtrees
common code modules
shared system prompts
shared documentation
```

Build a reuse planner that can answer:

```text
Which parts of this request have already been computed?
```

Potential structure:

```text
Request
 ↓
Context DAG
 ↓
find reusable blocks
 ↓
reuse valid state
 ↓
compute missing state
```

---

# 20. SPECULATIVE CONTEXT TRANSLATION

Explore whether translation can happen speculatively.

Example:

```text
router predicts likely target model
↓
start translating context before target is selected
```

or:

```text
cheap model begins
↓
translator prepares context for larger model
↓
escalation becomes inexpensive
```

Benchmark whether speculation saves enough latency to justify wasted work.

---

# 21. LAZY COMPILATION

Do not necessarily compile everything ahead of time.

Test JIT context compilation:

```text
first request
↓
compile only used blocks
↓
future requests reuse them
```

Compare:

```text
AOT compilation
vs
JIT compilation
vs
hybrid
```

Measure:

```text
startup cost
long-run cost
storage
cache pollution
```

---

# 22. AUTO-SELECT REPRESENTATION

The system should eventually choose automatically among:

```text
raw text
retrieval
semantic index
prefix cache
persistent KV
compressed KV
cross-model translated KV
canonical latent representation
recompute
```

Create a cost model.

Inputs:

```text
model
hardware
context length
expected reuse
network bandwidth
storage tier
quality requirement
latency requirement
available artifacts
```

Output:

```text
lowest-cost valid execution strategy
```

This optimizer may become more important than the `.npk` file itself.

---

# 23. EVOLUTIONARY R&D LOOP

Implement an explicit open-ended evolution loop for algorithms.

Maintain:

```text
research/evolution/
```

Each candidate has a genome/configuration describing choices such as:

```text
chunking
compression
layer mapping
source-layer selection
rank
quantization
cache tier
transfer strategy
mapper architecture
context IR representation
```

For every generation:

```text
1. retain champions
2. mutate promising candidates
3. cross over compatible ideas
4. introduce random unconventional candidates
5. benchmark all candidates
6. calculate Pareto frontier
7. archive results
8. analyze failures
9. generate next hypotheses
```

Never optimize only one metric.

Maintain a multi-objective frontier over:

```text
quality
TTFT
throughput
storage
transfer cost
compile time
memory
generality
```

Do not collapse everything into a single score unless necessary.

Preserve Pareto-optimal candidates.

---

# 24. NOVELTY ENGINE

Periodically stop implementation and ask:

> What assumptions are we unconsciously inheriting from existing LLM infrastructure?

Generate unconventional hypotheses.

Examples:

```text
Could context caches be shared peer-to-peer?

Could models request only certain semantic regions?

Could cache units be deduplicated globally?

Could attention patterns determine chunk boundaries?

Could reusable context live in a learned universal latent space?

Could model adapters be generated dynamically from architecture metadata?

Could context representations be progressively decoded?

Could cache state be multicast like CDN objects?

Could models negotiate a context representation?

Could retrieval return neural state rather than text?

Could commonly used libraries ship official compiled AI contexts?

Could Git commits contain context deltas?

Could package managers distribute precompiled context?

Could operating systems expose AI context pages?

Could a CDN optimize neural context placement?

Could caches use error-correcting or approximate representations?

Could query-specific KV be synthesized from reusable basis vectors?

Could multiple contexts share a low-rank dictionary?

Could frequently reused attention states be represented as learned primitives?
```

Do not assume these ideas are good.

Prototype cheap tests and kill them quickly if they fail.

---

# 25. SEARCH FOR MATHEMATICAL STRUCTURE

Do not treat KV tensors as opaque blobs.

Analyze:

```text
rank
spectra
correlation
layer similarity
head similarity
cross-model alignment
temporal redundancy
token redundancy
semantic redundancy
low-dimensional manifolds
```

Try:

```text
SVD
PCA
random projections
tensor decomposition
product quantization
vector quantization
low-rank factorization
sparse coding
dictionary learning
```

Determine whether repeated context states occupy substantially lower-dimensional structure than raw tensor size suggests.

---

# 26. CROSS-CONTEXT DEDUPLICATION

Investigate whether different texts produce reusable overlapping neural computation.

Examples:

```text
two versions of documentation
forked repositories
different branches
same library embedded in many repos
common license files
common dependencies
repeated system prompts
```

Create benchmark datasets containing controlled overlap.

Measure:

```text
raw byte overlap
token overlap
semantic overlap
KV similarity
potential compute reuse
```

This could become one of NeuralPack's strongest advantages.

---

# 27. SECURITY MODEL

Context caches may contain extremely sensitive information.

Build security into the architecture from the start.

Consider:

```text
tenant isolation
encryption at rest
encryption in transit
cache poisoning
cross-user leakage
hash inference attacks
prompt leakage
malicious NeuralPacks
serialization exploits
unauthorized cache reuse
signed provenance
revocation
```

Never allow one user's private neural state to become available to another user.

Public sharing must be explicit.

Use safe serialization.

Avoid arbitrary executable payloads in `.npk`.

---

# 28. PROVENANCE

Every artifact should know where it came from.

Potential manifest:

```text
source_hash
source_uri
compiler_version
model_id
model_hash
tokenizer_hash
architecture
quantization
creation_time
parent_pack
signature
license
```

If source changes, determine what is invalid.

Never silently reuse stale context when correctness depends on the updated source.

---

# 29. COMPATIBILITY FINGERPRINT

Develop a deterministic model compatibility identifier containing relevant factors such as:

```text
architecture
layers
KV heads
head dimensions
RoPE config
tokenizer
model weights hash
quantization
runtime version
```

Use it to determine:

```text
direct reuse
translation possible
recompile required
```

---

# 30. NEURALPACK FORMAT

Only after experiments justify requirements should the file format stabilize.

Potential sections:

```text
HEADER
MANIFEST
SOURCE MAP
CONTENT DAG
SEMANTIC INDEX
MODEL ARTIFACTS
MAPPERS
CACHE BLOCKS
DELTA DATA
SIGNATURES
CHECKSUMS
```

Requirements:

```text
streamable
versioned
partially loadable
content addressed
incrementally updateable
safe to parse
memory-map friendly
extensible
```

Do not prematurely standardize.

---

# 31. CLI

Target eventually:

```bash
npk compile ./repo

npk inspect repo.npk

npk benchmark repo.npk

npk verify repo.npk

npk diff old.npk new.npk

npk update repo.npk ./repo

npk serve repo.npk

npk run repo.npk

npk convert --target qwen repo.npk

npk stats repo.npk
```

CLI output should expose actual measurements, not marketing language.

---

# 32. API

Design a minimal runtime API.

Conceptually:

```python
ctx = neuralpack.load("repo.npk")

result = model.generate(
    context=ctx,
    prompt="Explain the authentication architecture."
)
```

But adapt the interface to what available runtimes can realistically support.

Do not pretend proprietary APIs permit direct KV injection if they do not.

---

# 33. HARDWARE DISCOVERY

At startup, inspect available hardware.

Record:

```text
CPU
RAM
GPU
VRAM
CUDA/ROCm
driver
disk
OS
```

Choose experiments appropriate to the machine.

If large models do not fit:

```text
use smaller models
use quantized models
reduce context
use synthetic benchmarks
validate algorithmic behavior first
```

Do not let lack of giant GPUs stop basic research.

---

# 34. START SMALL

Initial recommended model families should be small enough for rapid iteration.

Test initially on model sizes such as:

```text
0.5B
1B
3B
7B
```

when practical.

Only scale experiments when smaller experiments show evidence worth scaling.

---

# 35. NO BENCHMARK THEATER

Never cherry-pick.

For every major result include:

```text
median
p50
p95
variance
number of trials
hardware
warm/cold cache
context length
output length
batch size
model config
```

A result like:

> 8× faster

is meaningless unless precisely defined.

Report:

> 8× faster prefill under X conditions.

Do not conflate:

```text
TTFT
prefill speed
decode speed
throughput
total latency
```

---

# 36. BREAK-EVEN ANALYSIS

For every cache/transfer method determine:

```text
when is loading cheaper than recomputing?
```

Create graphs over:

```text
context length
network speed
PCIe speed
disk speed
model size
cache compression
reuse frequency
```

NeuralPack should sometimes deliberately choose:

> recompute

when that is cheaper.

That is a feature.

---

# 37. AUTOMATED EXPERIMENT SYSTEM

Every experiment should be reproducible from config.

Example:

```yaml
experiment:
  model_source: qwen-small
  model_target: qwen-large
  context_length: 16384
  representation: kv
  mapper: ridge
  compression: fp8
  source_layers: auto
  target_layers: all
```

Store:

```text
configuration
git commit
metrics
logs
plots
artifacts
conclusion
```

Never rely on undocumented terminal history.

---

# 38. FAILURE ARCHIVE

Create:

```text
research/failures/
```

Record failed hypotheses.

Each entry:

```text
hypothesis
implementation
expected result
actual result
why it likely failed
whether worth revisiting
```

Do not repeatedly rediscover failed ideas.

Negative results are valuable.

---

# 39. CHAMPION / CHALLENGER SYSTEM

Maintain:

```text
CHAMPION
```

the best current architecture.

Every new idea is a:

```text
CHALLENGER
```

It replaces the champion only if it provides meaningful improvement on the Pareto frontier.

Avoid architecture churn based on intuition.

---

# 40. QUALITY GATES

Before any candidate becomes part of the main runtime it must pass:

```text
unit tests
integration tests
reproducibility tests
quality tests
instruction-following tests
long-context tests
security tests
corruption tests
performance benchmarks
```

One impressive microbenchmark is not enough.

---

# 41. FUZZ TEST THE FORMAT

Generate malformed `.npk` files.

Test:

```text
truncation
corruption
invalid sizes
duplicate blocks
hash mismatches
malicious metadata
huge values
unexpected versions
```

Parser must fail safely.

---

# 42. TEST CACHE INVALIDATION AGGRESSIVELY

Cache correctness bugs are dangerous.

Modify:

```text
system prompt
user context
one token
tokenizer
quantization
model weights
RoPE config
runtime
source document
```

Ensure NeuralPack correctly determines whether reuse remains valid.

---

# 43. COMPARE WITH RAG

Do not assume neural-state reuse always beats retrieval.

For many workloads:

```text
RAG may be cheaper.
```

Benchmark:

```text
full context prefill
prefix cache
NeuralPack
RAG
hybrid RAG + NeuralPack
```

Determine workload regimes.

The ultimate product may be a planner that chooses between them.

---

# 44. HYBRID ARCHITECTURES

Test combinations.

Example:

```text
static instructions → KV cache
large docs → retrieval
frequently accessed docs → compiled state
rare docs → raw/RAG
model switch → translated state
```

The best solution is likely hybrid.

---

# 45. PRODUCT QUESTION

Continuously ask:

> What is the smallest capability that is so useful developers would install this today?

Possibilities:

```text
persistent repository context
instant long-document startup
cross-agent context reuse
cross-model handoff
incremental repository compilation
context CDN
cache optimizer
```

Do not wait for the universal vision before shipping a useful tool.

---

# 46. ZERO-CAPITAL PRODUCT PATH

Aim for:

```text
PHASE A
open-source local runtime

PHASE B
developer adoption

PHASE C
hosted registry

PHASE D
distributed context cache

PHASE E
enterprise private context infrastructure

PHASE F
cross-model universal context network
```

Hosted infrastructure should come only after local usefulness is demonstrated.

---

# 47. POTENTIAL BUSINESS MOAT

Do not rely on:

```text
"We use AI."
```

Potential defensibility could come from:

```text
context format ecosystem
model adapters
translation matrices
benchmark corpus
context optimizer
large compatibility database
distributed cache network
public package registry
developer integrations
performance data
```

But technical merit comes first.

---

# 48. GO/NO-GO CRITERIA

Set explicit kill criteria.

For example, if after serious experimentation:

```text
reuse saves <10%
or
quality degradation > acceptable threshold
or
cache transfer is usually slower than recomputation
or
existing tools already dominate every useful workload
```

do not hide this.

Pivot.

Potential pivots:

```text
incremental context compiler
context optimizer
distributed KV CDN
model handoff system
context package registry
repository precompiler
cross-model adapter toolkit
```

The objective is discovering the strongest technology, not preserving branding.

---

# 49. RESEARCH JOURNAL

Maintain:

```text
RESEARCH_LOG.md
```

After meaningful experiments append:

```text
DATE

QUESTION

HYPOTHESIS

EXPERIMENT

RESULT

INTERPRETATION

NEXT EXPERIMENT
```

Keep it concise enough to remain usable.

---

# 50. DECISION LOG

For major architecture decisions:

```text
docs/decisions/
```

Use ADR-style documents:

```text
decision
alternatives
evidence
reason
reversal conditions
```

---

# 51. REQUIRED FINAL REPOSITORY

Target:

```text
neuralpack/
│
├── README.md
├── LICENSE
├── pyproject.toml / package config
│
├── npk/
│   ├── compiler/
│   ├── runtime/
│   ├── format/
│   ├── storage/
│   ├── cache/
│   ├── adapters/
│   ├── translation/
│   ├── optimizer/
│   └── security/
│
├── benchmarks/
│   ├── cold_prefill/
│   ├── prefix_cache/
│   ├── persistent_kv/
│   ├── incremental/
│   ├── cross_model/
│   └── quality/
│
├── experiments/
│
├── research/
│   ├── landscape.md
│   ├── papers.md
│   ├── failures/
│   └── evolution/
│
├── docs/
│
└── tests/
```

Adapt this when evidence supports a better organization.

---

# 52. README STANDARD

README must eventually answer:

```text
What problem does NeuralPack solve?

What does it currently support?

What does it NOT support?

How does it compare with prefix caching?

How does it compare with LMCache?

How does it compare with RAG?

What benchmarks have actually been measured?

How do I reproduce those benchmarks?

What hardware is required?
```

Do not exaggerate.

---

# 53. FIRST EXPERIMENT SEQUENCE

Unless research reveals a better sequence:

### Experiment 1

Measure cold prefill on one small model across:

```text
1K
4K
16K
32K+
```

contexts.

### Experiment 2

Enable normal prefix caching.

Measure improvement.

### Experiment 3

Persist/reload reusable KV state.

Measure:

```text
serialization
disk storage
load
TTFT
```

### Experiment 4

Add compression/quantization.

Plot:

```text
size
transfer time
quality
```

### Experiment 5

Incremental source changes.

Determine reuse possible after:

```text
append
edit
delete
```

### Experiment 6

Same-family model transfer.

Attempt simple linear mappings before complicated networks.

### Experiment 7

Compare:

```text
native target prefill
translated KV
RAG
```

### Experiment 8

Run instruction-following stress tests.

### Experiment 9

Implement first context planner.

### Experiment 10

Allow evolutionary search to mutate major architecture parameters.

---

# 54. IMPROVEMENT GENERATION LOOP

Every major milestone must trigger:

```text
What did we assume?

What surprised us?

What became the new bottleneck?

What technique from another field could apply?
```

Search outside LLM research.

Investigate ideas from:

```text
compilers
CDNs
databases
operating systems
CPU caches
distributed filesystems
incremental build systems
video codecs
information theory
network routing
deduplication
virtual memory
database query optimizers
JIT runtimes
content-addressable storage
signal compression
distributed consensus
```

Cross-domain borrowing is explicitly encouraged.

---

# 55. ASK WEIRD QUESTIONS

Periodically generate questions that sound unreasonable.

For example:

```text
What if KV caches were torrentable?

What if popular open-source repositories shipped precompiled neural states?

What if context behaved like memory pages?

What if context blocks had globally unique hashes?

What if a model could request missing context lazily?

What if caches were layered like Docker images?

What if Git commits could contain neural-state deltas?

What if inference providers accepted signed context references instead of tokens?

What if one larger model could compile context for many smaller models?

What if neural state could be decomposed into reusable semantic libraries?

What if common knowledge could be loaded once per machine?

What if parts of an attention cache could be shared across unrelated prompts?
```

Most will fail.

That's fine.

The goal is discovering the few that don't.

---

# 56. DO NOT GET TRAPPED BY THE CURRENT TRANSFORMER

The ultimate system may eventually need to support:

```text
Transformers
MoE models
Mamba/SSM models
hybrid architectures
multimodal models
```

Do not hard-code the conceptual architecture around one specific attention implementation unnecessarily.

However, optimize the initial prototype for one tractable architecture.

---

# 57. MULTIMODAL FUTURE TRACK

After text context is working, investigate:

```text
image embeddings
vision token caches
audio representations
video context
multimodal KV
```

Do not implement this prematurely.

Record design implications now.

---

# 58. OBSERVABILITY

Every runtime decision should be explainable.

Example:

```text
NeuralPack chose persistent KV reuse.

Reason:
context = 22,410 tokens
cache available = local NVMe
estimated load = 71ms
estimated recompute = 413ms
compatibility = exact
```

Users should understand where savings come from.

---

# 59. MEASURE TRUE SAVINGS

Display:

```text
prefill FLOPs avoided
GPU milliseconds avoided
bytes transferred
cache hit rate
estimated compute cost avoided
```

Separate measured values from estimates.

Label estimates clearly.

---

# 60. REPRODUCIBILITY

Every published performance claim must map to:

```text
benchmark config
commit hash
hardware
command
raw results
```

Anyone should be able to reproduce it.

---

# 61. TEST AGAINST YOURSELF

Attempt to disprove every major conclusion.

If NeuralPack appears 5× faster:

try:

```text
faster baseline settings
better prefix caching
better batching
different context length
different hardware
different prompts
cold cache
warm cache
```

Do not build a company around a misconfigured baseline.

---

# 62. ENGINEERING QUALITY

Production-quality fundamentals still apply:

```text
type safety
tests
linting
error handling
structured logs
resource cleanup
deterministic configs
clear interfaces
documentation
```

Research code that cannot be reproduced is not useful.

---

# 63. MACHINE SAFETY

You may install legitimate development dependencies and modify files inside the project workspace.

Do not:

```text
exfiltrate credentials
extract browser cookies
weaken host security
disable security software
purchase services
delete unrelated user files
modify unrelated projects
publish private data
```

Keep experiments scoped to the project.

---

# 64. CONTINUOUS WORK RULE

Do not stop after creating scaffolding.

Continue through:

```text
research
implementation
execution
measurement
failure analysis
iteration
```

A generated codebase that has never actually been run is not completion.

---

# 65. DEFINITION OF AN EXPERIMENT

An experiment is complete only when:

```text
code runs
data exists
metrics were collected
baseline comparison exists
result was interpreted
next decision was made
```

---

# 66. DEFINITION OF MVP SUCCESS

A legitimate early success would be something like:

> On a clearly defined repeated-long-context workload, NeuralPack reduces measured prefill/TTFT substantially compared with a correctly configured baseline while maintaining essentially equivalent task quality, and the result is reproducible.

Do NOT preselect the required percentage.

Let experiments determine whether the improvement is meaningful.

---

# 67. LONG-TERM NORTH STAR

If the research succeeds, aim toward:

```text
RAW INFORMATION
      ↓
NEURALPACK COMPILER
      ↓
PORTABLE CONTEXT
      ↓
CONTEXT OPTIMIZER
      ↓
┌───────────────┬───────────────┐
│               │               │
local model    cloud model    agent
│               │               │
└───────────────┴───────────────┘
        ↓
MINIMAL REDUNDANT COMPUTATION
```

The dream is that information becomes:

```text
compiled once
incrementally updated
cryptographically identified
efficiently distributed
selectively translated
reused wherever valid
```

---

# 68. FINAL PRINCIPLE

Do not build what I described merely because I described it.

Discover what SHOULD exist.

If the best system ultimately looks very different from NeuralPack, that is success.

The project exists to answer:

> **How much of the computation performed when an AI repeatedly reads context is fundamentally redundant, and what is the strongest practical architecture for eliminating that redundancy?**

Approach that question without loyalty to conventional techniques.

Read everything relevant.

Reproduce strong work.

Attack assumptions.

Borrow techniques from unrelated fields.

Create unconventional experiments.

Measure everything.

Preserve failures.

Evolve promising approaches.

Discard weak ones.

And keep iterating until you have either:

1. a genuinely compelling, reproducibly superior context-reuse system; or
2. strong evidence that a different adjacent problem is a better target, followed by a pivot toward that target.

The goal is not to make NeuralPack look successful.

The goal is to discover something actually valuable.
Also, um... also when you're making everything, right, document, document everything in an Obsidian vault. Name it, um... name it Neural Pack. And yeah, document everything that you're doing, everything, every action, every discovery, and yeah.