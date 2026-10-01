# NeuralPack

NeuralPack prepares a searchable local copy of a codebase or document collection.
For each question, it picks source passages to send to your chosen AI.

```text
Your source files → compile once → project.npk
                                      ↓
Your question → local search → selected passages → your chosen AI answers
```

The compiler and default runtime use **zero generative LLM calls** and require
no API key. The final answering model belongs to your application.

## Current evidence: NPK-Bench (2026-09-27)

Measured on [NPK-Bench](benchmarks/npkbench/__init__.py), which was built for this
purpose. Queries are real SWE-bench issue reports, which NeuralPack's developers
neither wrote nor tuned against. The score is whether the selected context contains
the lines the maintainers' fix edited ("hunk recall"). Decisions were made on SWE-bench
Lite and confirmed once on a **held-out** split (SWE-bench Verified minus Lite,
407 issues). Details: [BASELINE.md](BASELINE.md) and the
[experiment log](experiments/npkbench/EXPERIMENTS.md).

| Held-out, fix locations found (hunk recall) | 1K | 2K | 4K | 8K | 16K |
|---|---:|---:|---:|---:|---:|
| Standard RAG baseline: BM25 over 60-line chunks (identifier-split) | 0.101 | 0.149 | 0.217 | 0.267 | 0.321 |
| NeuralPack before this loop's retrieval changes | 0.136 | 0.206 | 0.302 | 0.393 | 0.490 |
| Code-first ranking (definition channel, top-block trimming, test mate from 2K) | 0.230 | 0.303 | 0.385 | 0.472 | 0.569 |
| **Current default** (+ issue-form cleaning, title and repetition weighting, test-file conventions, URL cleaning, release notes last) | **0.258** | **0.349** | **0.465** | **0.580** | **0.644** |
| Current default, regression-test sites found (tests target) | 0.088 | 0.184 | 0.266 | 0.353 | 0.451 |

The query-handling changes of the last row were decided on other fresh splits (heldout-c,
heldout-d). On this split they add +2.3 / +4.3 / +6.8 / +9.9 / +7.0 points of fix sites
and +3.0 to +12.0 points of regression-test sites, all significant (run R002). The later
changes were each confirmed on their own fresh split and cost nothing significant here:
test-file conventions and environment-dump cleaning (E047, E052; run R004) leave fix recall
unchanged and add +0.1 to +0.6 points of regression-test sites (not significant), and URL
cleaning with release notes last (E053, E054) add +0.5 to +0.9 points of fix sites
(significant at 4K) and -0.1 to +2.3 points of regression-test sites (significant at 4K, 8K
and 16K) over run R004. The table shows run R006, the current default.

- **Against a standard RAG pipeline** (same files, budgets and gold; BM25 over fixed
  60-line chunks, filled in score order): NeuralPack finds 2.0-2.6x as many fix sites on
  held-out (significant at every budget) and 1.5-2.2x as many regression-test sites
  (significant from 2K). The baseline still finds somewhat more of the documentation
  maintainers edit at 2K-8K (at 2K: 0.31 vs 0.22; 33 of 407 held-out issues edit docs),
  but the gap is no longer significant at any budget; before the query-handling changes
  it was 0.31 vs 0.17 at 2K. Documentation remains the weakest target.
- **Beyond Python** (SWE-bench Multilingual sample: 114 issues in 41 Rust, Ruby, Java,
  Go, C/C++, PHP and JS/TS repositories, never used for decisions): fix-site recall is
  0.198 / 0.253 / 0.304 / 0.364 / 0.455 at 1K-16K, 1.9-3.1x a BM25 baseline over
  1,000-character chunks, and regression-test recall 0.079 / 0.122 / 0.185 / 0.269 / 0.317,
  2.4-3.0x the baseline (every gap significant; run R005, with E047 and E052). The
  query handling (issue-form cleaning and title/repetition weighting) matters most here:
  it adds +8.9 to +13.5 fix points (0.164 -> 0.260 at 2K; run R003). Absolute recall is
  still about three quarters of Python's; C/C++ and JS/TS were weakest before these
  changes. On SWE-PolyBench's Java, JavaScript and TypeScript issues (`poly-dev`, 199
  issues in 12 repositories, measured before any tuning on it; run P001) fix recall is
  0.195 / 0.244 / 0.319 / 0.404 / 0.476, 1.6-2.2x B002, and the query handling adds +6.0
  to +8.9 fix points (all significant).
- **Definition channel** (default): code identifiers named in the query
  (`Signal.send_robust()`, `django.core.exceptions.ValidationError`) resolve to their
  defining blocks. On the held-out split it adds +5.7 to +10.3 points at every
  budget (2K: +0.103, 95% CI [+0.071, +0.136]), and file recall at 2K rises from 0.350
  to 0.538. **Tradeoff:** recall of where maintainers put regression tests falls 2.4
  to 4.5 points, and recall of the documentation they edited falls about 10 points at
  2-4K (33 held-out issues edit docs). Weighted by how often each target exists, the net
  effect is clearly positive. Pass `enable_definitions=False` to disable it.
- **Top-block trimming** (default): if the best candidate alone exceeds the budget,
  NeuralPack emits its most relevant methods (exact source lines with their own spans)
  instead of dropping it. On dev this adds +13.9 / +7.3 points at 512 / 1K tokens;
  held-out confirms +3.8 points at 1K, and selections are identical at 2K and above.
  Pass `enable_trim=False` to disable it.
- **Test mate** (default from a 2K budget; `enable_test_mate=True/False` or
  `--test-mate always|never` override it): places the best query-matching block of the
  test file that mirrors the top implementation file (`pkg/mod.py` ->
  `tests/.../test_mod.py`) right after it. On a fresh held-out split (heldout-b, 400
  issues) it finds +5.7 / +6.0 / +3.7 / +2.3 points more regression-test sites at
  2K-16K (all significant) for 0.4-1.1 points of fix sites. Below 2K the trade was even
  on held-out, so it stays off there. Test files are recognized by each language's
  convention: Python, Jest (`Button.test.js`, `__tests__/`), JUnit/PHPUnit/NUnit
  (`FooTest`, `TestFoo`, `FooIT`), Go (`_test.go`), gtest and RSpec. A CamelCase test
  class mirrors its subject (`ServiceConfigTest.java` -> `ServiceConfig.java`). On the
  JS/TS/Java held-out split (poly-heldout, 133 issues) this finds +1.8 / +0.9 / +1.6 /
  +1.5 points more regression-test sites at 2K-16K at no fix cost (E047, PH01).
- **Issue-form cleaning** (default; `enable_query_cleaning=False` or `--raw-query` turn
  it off): issue templates wrap the reporter's words in headings ("Steps to reproduce",
  "Expected behavior"), checklists and HTML-comment instructions, and those words match
  CONTRIBUTING guides and changelogs better than code. Short headings (up to six words),
  checklist lines and HTML comments are removed before retrieval; the first line (the
  issue title) is always kept, and the selection reports the caller's query unchanged.
  On a fresh held-out split (heldout-c, 400 issues) fix sites rise +0.7 / +0.9 / +1.2
  points at 4K / 8K / 16K and regression-test sites +0.4 at 1K and +1.4 at 16K (all
  significant), with no significant loss at any budget. On the multilingual development
  split the effect was mixed (fix -0.3 to +1.4 points). Environment dumps are removed
  too: `show_versions()`, `version_info()` or `doctor` output (blocks of `package: version`
  lines, mostly version numbers) otherwise pulls the project's version-printing module
  to the top. On a fresh held-out split of 300 SWE-Gym issues (10 Python repositories
  SWE-bench does not use) this adds +0.5 / +1.4 / +1.0 fix points at 1K-4K and +1.1 to
  +1.6 regression-test points at 2K-16K (significant; E052, GH01). URLs keep only their
  informative parts: image links and GitHub attachments are dropped, a link to a source file
  keeps its repository path, and other links keep their path words, because scheme, host and
  GitHub words otherwise match READMEs, docs and CI files. On 320 fresh JS/TS issues
  (poly-heldout-b) this adds +1.8 to +3.3 fix points at every budget and +1.1 to +2.2
  regression-test points from 2K (all significant; E053, PHB01).
- **Release notes last** (default; `demote_release_notes=False` or
  `--no-release-notes-last` turn it off): changelogs, release notes, "what's new" pages and
  release blog posts describe past changes in an issue's own words, so they rank high, but a
  fix adds a new entry rather than editing the old one. They are placed after every other
  candidate. On poly-heldout-b this adds +1.2 to +1.7 fix points and +0.4 to +0.6
  regression-test points at 2K-8K; together with the URL rule, +1.6 to +3.6 fix points and
  +1.1 to +2.6 regression-test points at every budget (all significant; E054, PHB01).
- **Title and repetition weighting** (default; `title_weight=1, tf_cap=1` or
  `--title-weight 1 --tf-cap 1` turn it off): in a multi-line query, the terms of the first
  line (an issue's title, the reporter's one-line summary) count three times in lexical
  retrieval, and a term the reporter repeats counts up to three times (1 + log2 of its
  count). Without it, every distinct word counts once, so words from reproduction code,
  tracebacks and environment details match unrelated code and prose as strongly as the
  topic. On a fresh held-out split (heldout-d, 401 issues) fix sites rise +1.4 / +2.9 / +3.2
  / +4.6 points at 2K / 4K / 8K / 16K and regression-test sites +2.8 to +12.2 points at every
  budget (all significant; no significant loss). The title part alone gained +6.5 to +8.2
  fix points at 4K-16K on the non-Python development split. Single-line queries, including
  chat-memory questions, are unchanged. Cost: FTS5 scores every repeated term again, so
  lexical ranking takes about twice as long; median selection time rises about 55% (70 -> 109
  ms at 4K on heldout-d, four parallel workers) and the 95th percentile about 1.9x.
- **Long queries:** a query keeps its first 512 distinct search terms (backticked literals
  always kept). Issues rarely have more than a few hundred (p99 300-470), but a pasted log can
  have thousands; on Django a 20,000-identifier query now takes about 4 s instead of 114 s.
  Shorter queries are unaffected.
- **Robust ingestion:** as received, 46 of 103 benchmark snapshots failed to compile
  because a single binary, non-UTF-8, or credential-like file aborted the build (for
  example, every Django snapshot). Files that were never indexed are now skipped and
  listed in `skipped_sources`. An *indexed* file that becomes unindexable still aborts
  an update, and `--strict` restores the old behavior.
- **Speed:** compiles are 1.5× faster with logically identical artifacts. A one-file
  update of Django takes 0.8 s (was 1.2 s), and a no-op update takes 0.4 s (was 1.0 s).
- **Context map** (opt-in, `select(map_share=0.25)` / `--map-share 0.25`): a quarter of
  the budget lists further ranked places (`path:start-end kind name`) without their text.
  For callers that can open files, a 25% map at 2K locates as many fix sites as full text
  does at 4K. Held-out: located fix recall +9.6 / +12.3 / +13.0 / +11.4 / +7.2 points at
  1K-16K over the default's full text, and regression-test sites +5 to +8 (all
  significant). It is not the default because full-text recall drops 3-5 points.
- **Conversation memory** (LongMemEval-S, about 120K-token chat histories): 1K tokens of
  selected context keep 69% of evidence turns and 87% of evidence sessions. Against a
  standard RAG baseline (BM25 over ~1,000-character chunks), turn-level blocks lead by 21
  and 14 points at 256 and 512 tokens and tie from 1K to 4K. For chat
  histories read with 4K tokens or more, compile with `--mode semantic` and query with
  `--retrieval hybrid` (local MiniLM encoder). On 370 held-out questions, evidence
  recall rises from 0.840 to 0.881 at 4K and from 0.871 to 0.931 at 8K (significant;
  preferences and multi-session questions gain most). At 2K and below it is neutral.
  Compiles become much slower (about 45 s instead of 0.2 s per history on one CPU
  thread). The same dense signal does not pay off for code at small budgets.
- Rejected with recorded evidence: path/role priors (they win only by ignoring tests
  or documentation; demoting documentation costs 14-40 points of documentation recall),
  budget portfolios, learned re-ranking over the existing channels, file aggregation,
  callee expansion, coarse-to-fine emission, a documentation channel (trades code
  recall for docs), reST sectioning of `.txt` docs, query segmentation, import-aware
  entity extraction, time windows for chat memory, and diversity/density packing for
  conversations.

This measures localization evidence, not answer or patch correctness.

## Evidence status before 2026-09-26: PIVOT REQUIRED

NeuralPack is a working local compiler and retrieval runtime. A differentiated
advantage over strong retrieval alternatives is **not established**. Previous
claims of 100% answer accuracy, guaranteed savings and graph superiority are
retracted. Older reports are historical diagnostics, not proof of the current
product. The original independent audits and [evolution record](EVOLUTION_LOG.md)
document those failures and the subsequent repairs.

The strongest reproduced rival comparison still uses a frozen CRISP version. The
Cycle 37 v7.1 replay retains 162/246, 205/246, and 229/246 annotated source needles
at 512, 2,048, and 8,192 tokens with fielded BM25; adding the explicit raise-relation
channel reaches 175/246, 223/246, and 239/246. The older body-only 148/246 and CRISP
225/246 figures remain historical comparator measurements. These are inspected
code-retrieval questions, **not answer accuracy**. See the [v7 replay](experiments/results/cycle37-product-v7-fields-v2/results.json)
and the [seed comparison](research/CYCLE28_SEED_ABLATION.md). CRISP has since changed;
its [newly captured source](research/CYCLE28_CURRENT_RIVAL_CONTRACTS.md) requires a
separate evaluation.

Cycle 37 promotes artifact format 8 and compiler 8.0. It replaces the duplicated
FTS5 body with an external-content index over authoritative block rows, keeps
normalized identifier and path search fields, and performs source-aware posting
deletes during incremental updates. A clean rebuild and an incremental update now
have equal logical tables, BM25 scores, and query payloads after a one-file change;
the updated file can be larger because SQLite retains incremental page history.
Older v7 and earlier packs must be recompiled before they can be updated.

The paragraphs below summarize earlier cycles and retain their original evidence;
Cycle 37 measurements and the current promotion decision are recorded in the
[Cycle 37 research record](research/CYCLE37_ALPHAEVOLVE.md).

Recent experiments reject extra complexity: all tested grouping and lexical
fusion variants lose more annotated evidence than they gain. The complete
[packing audit](research/CYCLE28_PACKING_CHALLENGERS.md) checks 8,658 selections
and publishes matched-budget curves. A [five-setting search-penalty sweep](research/CYCLE28_LENGTH_NORMALIZATION.md)
independently audits all 3,996 results. A change fixes one missed traceback method
but loses evidence elsewhere; no general parameter change is promoted.
Graph expansion remains experimental.

The [compact-source trial](research/CYCLE29_SOURCE_VIEWS.md) audits 5,994 new
local selections. Removing docstrings raises the field-search source score
from 205 to 211 at 2,048 tokens, but loses a behavior case's implementation
evidence. Frozen CRISP remains ahead. Automatic compaction is rejected; the
default still preserves full selected blocks. No new answer-quality claim follows.

The [batched index deletion update](research/CYCLE30_UPDATE_BATCHING.md) fixes a
parameter-limit crash under constrained SQLite environments (`too many SQL variables`)
and replaces repeated per-file FTS index scans with a single joined deletion pass.
On a 1,000-file modular corpus, isolated index cleanup work dropped from 1,037,807 to
62,637 SQLite progress ticks (a 16.57x reduction) and wall time from 1,284 to 217 ms.
An independent audit verified 10,702,770 FTS5 postings and 300 3-way query comparisons
against fresh rebuilds with byte-exact payload and span identity. The default
compiler and query runtime make zero generative model calls.

The [runtime hardening update](research/CYCLE31_RUNTIME_HARDENING.md) hardens SQLite
connections (`trusted_schema=OFF`, `enable_load_extension(False)`, `query_only=ON` for readers),
eliminates legacy module imports during queries (0 `npk.context` modules loaded),
replaces memory-heavy string counting with SQL aggregation (1.39x faster, 0 string allocations),
and adds context management (`with PackSelector(...) as selector:`) for sub-millisecond query
throughput (up to 4.6-18x faster on tight query loops). Traversal order is canonically sorted.

The [symbol index cleanliness update](research/CYCLE32_SYMBOL_INDEX_CLEANLINESS.md) eliminates
51,616 noise rows (46.0% of symbol rows) by filtering language keywords, stopwords, and prose
bare-words from `symbols`. Artifact disk size dropped by 21.1% (from 13.86 MB to 10.94 MB on Click)
and freed nearly 3 MB of database B-tree storage while preserving 100% of code definitions (4,376/4,376).
Hybrid symbol retrieval now ranks actual code implementations over changelog entries.

The [batched file insertion update](research/CYCLE33_BATCHED_FILE_INSERTS.md) batches secondary
table DML (`lexical`, `symbols`, `assignments`) per file rather than per block, cutting 350 ms off
compilation (1.24x speedup in block indexing) and reducing database call overhead by 13x while
preserving exact row and content parity. FTS5 tie-breaking fidelity is strictly preserved.

The [stat-fingerprinted update](research/CYCLE34_STAT_FINGERPRINT_UPDATES.md) adds optional
fast scanning (`update_pack(..., quick=True)`, `npk update --quick`) using stored `mtime_ns` and `size`
fingerprints to skip reading and hashing untouched files. Scanning latency on 1,000 files dropped from
1,235 ms to 702 ms (1.76x speedup, saving 530+ ms per update) while producing byte-identical Merkle
roots. Strict cryptographic content-hash scanning remains the secure default (`quick=False`).

The [query caching and canonical ordering update](research/CYCLE35_QUERY_CACHE_AND_CANONICAL_ORDERING.md)
adds in-memory LRU query result caching to `PackSelector` (keyed on `root_sha256` for instant cache
invalidation upon artifact update), achieving up to 800x faster repeated queries (0.004 ms),
and introduces `context_text(order="canonical")` to emit evidence in contiguous file-path order for
maximizing prompt prefix-cache hits across multi-turn agent sessions.

The current optional NIM answer validation is recorded in the [Cycle 38 model and
hybrid evaluation](research/CYCLE38_MODEL_AND_HYBRID_EVAL.md). On a 12-task
urllib3 behavior oracle, the configured Llama arm produced 3/12 exact answers
with definition/member retrieval at a 2,000-token budget, versus 0/12 for the
body-window arm and both no-context and full-context controls. Member retrieval
retained every required span on 5/12 tasks. This is a model-and-corpus diagnostic, not a
general answer-quality winner; historical missing results remain N/A. Real local
embeddings and a cross-encoder have also been measured; the reranker costs about
13 seconds per query without an established answer benefit. No target model is
called during default context selection.

An experimental [compiled counting cache](research/CYCLE28_PERSISTED_COUNT_CACHE.md)
persists in SQLite and updates changed records. [Loading only candidate records](research/CYCLE28_LAZY_COUNTS.md)
preserves all measured selections and reduces fresh SQLAlchemy request time from
859 to 743 ms against eager cache loading, excluding initial compilation and
interpreter startup. Warm 2K time is slightly worse, 73 to 75 ms. The workload has
2.34 million available compiled-block tokens per request; retained count-record
objects fall from 12.79 to 1.19 MB, excluding SQLite/backend memory. This remains
an optional research prototype; format integration and an answer-quality advantage
are still open.

Historical canonical checks include the Cycle 29 and Cycle 35 reports below. The
current Cycle 37 gate is **1,227 tests passing, 22 symlink tests explicitly skipped,
and 159/159 contract mutants assertion-killed** after adding source-derived FTS5
posting, document-length, and configuration verification. Reports are
`cycle37-full-v8-final.xml` and `cycle37-contract-mutations-v7.json` in
`experiments/results/`. This verifies tested
contracts; it does not prove relevance, evidence sufficiency, or a breakthrough.

A [complete-program diagnostic](research/CYCLE28_COMPLETE_PROGRAM_CONTROLS.md)
finds two wrong answers even when every source line and input is supplied.
The target's thinking setting passes8/8 cases against direct mode's6/8, with
more output tokens and higher latency. This is a small target-model diagnostic,
not a NeuralPack retrieval improvement. The experiment's audit also now rejects
Boolean/number substitutions in frozen records.

The [shared response/replay audit](research/CYCLE28_SHARED_RECORD_IDENTITY.md)
now rejects equivalent-looking records with changed JSON types. A new local
audit checks381 saved record files with no changed grades and no new API calls.

The [transport-recovery pass](research/CYCLE28_REFERENCE_EVIDENCE.md)
preserves all original attempts and recovers35 missing answers through49 explicit
retries of known transport failures. NeuralPack BM25 now passes5/15 tasks;
native CRISP passes7 with one answer missing. CRISP wins this frozen comparison
even if its missing answer fails; this is not a broad independent validation.
A separate compact, manually seeded reference arm passes4 with two missing and
cannot reach CRISP's known total. Smaller context alone does not establish a win.
Default optimization makes no generative calls.

## Use it

```bash
pip install -e .
npk compile ./my-repo project.npk --mode deterministic
npk query project.npk "Why is retry behavior wrong?" --budget 1500 --show-text
npk update project.npk ./my-repo
npk verify project.npk
```

```python
from npk.pack import PackSelector

query = "Why is retry behavior wrong?"
selection = PackSelector("project.npk").select(query, budget_tokens=1500)
if selection.seed_failed or not selection.evidence:
    # Obtain more evidence, explicitly enlarge the budget, use full context if
    # it fits, or return an explicit retrieval failure before calling a model.
    raise RuntimeError("More context is required before answering")

# target_llm is supplied by your application. NeuralPack never calls it.
response = target_llm(query=query, context=selection.context_text())
```

Opt-in modes, each measured on NPK-Bench (see "Current evidence" above):

```bash
# Callers that can open files: 25% of the budget lists further ranked places
# (path:start-end kind name) in "locations", without their text.
npk query project.npk "Why is retry behavior wrong?" --budget 2000 --map-share 0.25
# Test mate: the mirroring test file's best block follows the top implementation
# block. Default "auto" places it from a 2048-token budget; "always" or "never" override.
npk query project.npk "Why is retry behavior wrong?" --budget 1500 --test-mate always
# Chat histories and other prose: local embeddings plus hybrid retrieval.
npk compile ./chats chats.npk --mode semantic
npk query chats.npk "Which book did I finish a week ago?" --retrieval hybrid
```

Results include source paths and line spans, text, ranking scores, the original
query, estimated tokens, uncalibrated risk indicators, and fallback reasons.
A nonempty selection is **not proof of sufficient evidence**. Applications must
keep system instructions and the original question outside retrieved source text.

Without a tokenizer, budgets use `floor(characters / 4)` with a minimum of one
for nonempty text and are explicitly reported as estimates. A target-model name
alone does not select or download its tokenizer.

Use an explicit local tokenizer when you need a true context-token cap:

```bash
pip install -e '.[tokenizers]'
npk query project.npk "Why is retry behavior wrong?" --budget 1500 --tokenizer-json ./tokenizer.json --show-text
```

```python
from npk.pack import LocalTokenizer, PackSelector

# Download/obtain the matching tokenizer asset separately. Query never does so.
counter = LocalTokenizer("tokenizer.json")
selector = PackSelector("project.npk", tokenizer=counter)
selection = selector.select(query, budget_tokens=1500)
```

This counts the actual assembled context with the supplied tokenizer JSON,
including default separators. Saved padding and truncation settings are disabled;
random BPE dropout is rejected. Both modes exclude the original query,
system instructions and caller formatting; budget those separately. The caller
must verify that the asset matches the target model. Exact selected counts are
never divided by the artifact's character-based corpus estimate: exact mode
returns `available_tokens: null`, a separate `available_tokens_estimate`, and
`reduction_pct: null`. Empty selection reports `status: fallback_required`.
Neither exact counting nor a nonempty selection proves sufficient evidence.

Keep the tokenizer instance to reuse exact counts. Its in-memory cache uses a
4 MiB text-plus-entry allowance and a 4,096-entry ceiling. Separate CLI processes
do not share it. Pass `cache_bytes=0` to disable it, or use `clear_cache()` to
release retained counts. New-query counting can be substantially slower than an
immediate repeat; tokenizer construction is an additional first-use cost.

## Artifact and runtime

`.npk` is a versioned SQLite database containing source hashes, file metadata,
blocks with provenance, FTS5 lexical search, symbol indexes and optional local
embedding/dependency indexes. It does not store provider-specific LLM state.

Format 8 uses external-content FTS5. The authoritative source text remains in
`blocks.text`; normalized search text, names, and paths are maintained in the
FTS index without a second stored copy of every block body. Incremental deletes
remove the exact normalized fields that were indexed, and full verification
compares posting instances, document lengths, and configuration against a
temporary source-derived index. This keeps BM25 normalization stable after
updates and makes a self-consistent but source-inconsistent posting tree or
document-statistics table fail verification.

Deterministic mode needs no model. **BM25 lexical search is the default.**
To experiment with a local encoder, compile with `--mode semantic` and query with
`--retrieval hybrid` (Python: `PackSelector(path, retrieval="hybrid")`).
Runtime encoder loading is offline, uses safetensors, and disables remote model
code. Download weights separately. The default encoder is pinned to the
[recorded MiniLM revision](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41).
Each encoder instance owns its model and cache; cached tensor data is limited
to 16 MiB and 64 entries. Failed loads remain local to that instance; start a
new process or create a fresh backend after installing previously missing weights.

Semantic packs record the encoder ID, revision, truncation length, pooling rule
and document character limit. Hybrid queries reject incompatible identities even
when vector dimensions match. Existing semantic packs without this contract must
be recompiled for hybrid queries; lexical queries remain available. This assumes
a trusted local model cache and installed libraries; a revision label does not
authenticate external weight bytes.

Initial compilation without available weights produces a usable lexical artifact
and reports `embedding_status: unavailable`. Updating an existing semantic index
with missing or incompatible weights rolls back the source update. After a
previously unembedded build, a source-changing update with an available encoder
indexes all source blocks so the artifact cannot contain an unexplained partial
index. No-change updates still do no work; recompile to add embeddings without
source changes.
Dependencies and conflict filtering remain experimental and disabled by default;
neither has demonstrated a general advantage in the corrected public-runtime
comparison. Source order alone never establishes that an earlier fact is obsolete.

The compiler also leaves the dependency index out by default. Use `compile --deps`
to build it experimentally. Updates preserve that setting; `update --deps` and
`update --no-deps` change it explicitly. An unchanged-source update returns
without rewriting the artifact or recomputing its integrity digest.

Python compilation optionally supports `--python-members` to split classes at
method boundaries while retaining their other source lines and provenance.
Updates preserve this setting. It remains experimental: the first real-code
coverage comparison helped at small budgets, but not consistently at larger ones.
It is still ordinary BM25 over different chunks, not a new retrieval algorithm.

Updates skip parsing unchanged files using content hashes. Scanning still reads
the source tree, and dependency rebuilding can do work across the repository.
An artifact made with different compiler rules must be recompiled before update.
This is not a claim of constant-time updates.

Semantic updates reuse vectors when both the original text and its hash match
under the same checked encoder identity. Source paths and spans are regenerated,
so a rename or line shift cannot preserve stale provenance. Reuse is temporary
within the update transaction. Compile/update statistics distinguish
`encoder_rows_requested` from `embedding_rows_reused`; `embedded` counts all
vector rows written, including reused rows. These are local encoder operations,
not generative API calls. The encoder must still be available and compatible.

Equal retrieval scores are ordered by source path and block position rather
than mutable database IDs. This prevents a file update alone from changing which
equal-scoring passages survive a candidate limit. The ordering has a measured
query-time cost; see cycle 8 in the evolution log.

Recompilation builds in a temporary directory and replaces the previous artifact
only after success. Invalid source paths and failed builds preserve the prior
artifact. SQLite rollback journals keep ordinary reads free of WAL sidecars.
Applications must serialize writes; this does not guarantee power-loss recovery.

An unreadable source file or directory aborts compilation/update. A temporary
access failure must not be interpreted as a deletion. Eligible text must be valid
UTF-8 and no larger than 2 MiB per file; unsupported input fails explicitly and
preserves an existing artifact. NUL bytes anywhere in eligible text now abort
the build. Empty files and excluded paths remain outside the searchable text.
Resolved file paths must stay inside the source root, and metadata is checked
before and after reading each file. This detects ordinary changes during a read;
it does not provide an atomic snapshot of a concurrently changing repository.

Known credential filenames are excluded. Recognized credential patterns in
eligible source or paths abort compilation/update without publishing a partial
artifact or echoing the matched value. This limited pattern screen cannot find
all secrets; artifacts should be built from reviewed source. Broad secret-free
artifact claims are withdrawn.

Compiler 8.0 preserves Unicode separators as source data and fixes capped blocks
whose reported spans previously included a line missing from their text. CR/LF
line endings are normalized to LF; text within a physical line is preserved.
Recompile packs built by earlier compiler rules before updating. Literal `#`
and percent characters in artifact filenames are supported; updating a missing
pack fails explicitly without creating an empty database.

**Artifact format 8 requires rebuilding older packs, including version 7.**
Changed updates refresh file hashes recorded by transactional tracking triggers;
unchanged file hashes are reused. Full verification independently hashes actual
text, metadata, provenance, symbols, dependency/embedding data and FTS index
storage, checks SQLite structure, block hashes and internal span line counts, and
for an otherwise valid v8 artifact compares every FTS5 term/document/column/offset
posting plus document-length and configuration metadata against fields derived from
`blocks` and `files`. The span check cannot
prove correspondence to an unavailable original source. Corruption returns
`ok: false`. Verification scans the artifact; run it when accepting a pack, rather
than on every query. The v8 source-parity check adds about 0.68 seconds on the
3,513-block frozen code pack used in Cycle 37; the fast selector does not repeat
full verification.
CLI queries requiring fallback and failed verification return nonzero exit codes.
Cached update preflight assumes a valid accepted base; verify externally obtained
or restored artifacts before updating. Cached sealing cannot replace full
verification. See [ADR 0005](docs/decisions/0005-incremental-integrity-and-read-snapshots.md).
Queries use a consistent database snapshot. Long readers can delay updates;
busy timeouts remain explicit failures that callers must handle.

A digest stored inside a pack does not authenticate its publisher. Python callers
can supply `verify(path, expected_root=trusted_digest)` to compare with a root
obtained independently from a trusted source.

## Reproduce the current diagnostics

```bash
python -m benchmarks.compiled_validation --output experiments/results/local-check.json
python -m benchmarks.compiled_validation --mode semantic --output experiments/results/local-semantic.json
python -m benchmarks.compiled_scale --output experiments/results/local-scale.json
python -m benchmarks.embedding_update --champion 857bc1f --output experiments/results/local-update.json.gz
python -m pytest tests/ -q
```

Semantic evaluation requires the local encoder weights; benchmark workers run
with model downloads disabled. Reports include task-level source provenance,
available and selected context estimates, budget checks, and source hashes.

For the curated urllib3 2.7.0 behavior tasks, install the experiments extra and run:

```bash
python -m benchmarks.repository_eval --output experiments/runs/repository-local
# Optional local embedding challenger; weights must already be available:
python -m benchmarks.repository_eval --output experiments/runs/repository-semantic --semantic
# Explicit answer-model validation, using the configured NIM credential:
python -m benchmarks.repository_eval --output experiments/runs/repository-live --semantic --live
# Explicit newer answering-model configuration; selection remains local:
python -m benchmarks.repository_eval --output experiments/runs/repository-deepseek --semantic --live --model deepseek-ai/deepseek-v4-flash-0731 --reasoning-effort none --max-output-tokens 2048
# Local cross-encoder baseline, using separately installed cached weights:
python -m benchmarks.repository_rerank --output experiments/runs/repository-rerank
```

The default evaluator is LOCAL. The `--live` experiment makes one answering call
per uncached task/arm, including no-context and full-context controls. It never
uses a generative model for selection or grading. Exact responses, provider token
usage, executable library answers, code hashes and source hashes are recorded.
`--replay` reuses exact cached requests without making calls. These developer-known
questions are not a sealed independent evaluation.

**PROVED UNDER ASSUMPTIONS:** for dependency reachability with no external seed
injection, `Closure_D(∅) = ∅`. Graph traversal cannot repair failed retrieval.
This negative result motivates stronger retrieval and explicit fallback; it is
not a correctness guarantee for selected evidence.

## License

MIT. Copyright (c) 2026 NeuralPack contributors.
