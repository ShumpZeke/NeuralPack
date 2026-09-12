# META-RESEARCH BACKLOG — architecture challenge and forward roadmap

Written 2026-09-08 by a read-only meta-research pass over the whole repository
(`npk/` 6,482 LOC, 209 benchmark modules / 26,409 LOC, 110 test files / 9,399 LOC,
38 research notes, 14 ADRs, the 3,518-line evolution log, and three real `.npk`
artifacts under `experiments/runs/packs/`).

**Status of every claim in this file.** Sections marked **MEASURED** were computed
against real artifacts and are reproducible with the script in section 3.9.
Sections marked **CODE-CERTAIN** follow directly from reading the source.
Everything else is **HYPOTHESIS** and must survive this project's existing
matched-budget, counterexample-first discipline before promotion. Nothing here is
a product claim, an accuracy result, or evidence of a differentiated advantage.
`PIVOT REQUIRED` remains the correct verdict until an experiment says otherwise.

---

## 0. HOW A FUTURE AGENT SHOULD USE THIS FILE

1. Read section 2 (what the system actually is) and section 3 (new measured
   evidence). Do not re-derive them; they cost a full pass to establish.
2. Read section 4. Those five assumptions are load-bearing and every idea below
   attacks one of them.
3. Go to section 11 (ranked backlog). Each entry carries the seven fields this
   project's process requires: what to investigate, which files, the hypothesis,
   the prototype, the benchmark, the promotion gate, and the rejection gate.
4. Obey section 10 (anti-recommendations). It lists work that looks attractive and
   is already refuted by this project's own measurements. Not doing those is worth
   as much as doing the rest.
5. Respect the sequencing DAG in section 12. Three items multiply the value of
   everything else and should land first even though they improve no headline
   metric directly.

**Discipline that must not be relaxed.** Every experiment here has been protected
by four habits that are the reason its negative results are trustworthy: frozen
plans with SHA-256, independent auditors that re-derive results from source spans,
permanent counterexample fixtures for every falsified claim, and matched budgets.
Any idea below that cannot be run under those four habits is not ready to be run.

**Idea numbering.** `A-n` high-confidence engineering, `B-n` strong experiments,
`R-n` beyond-conventional, `D-n` fundamental redesign, `X-n` explicit
anti-recommendations. Numbers are stable; append, never renumber.

---

## 1. THE ONE-PARAGRAPH SUMMARY

NeuralPack is a SQLite database of text blocks with an FTS5 BM25 index and a greedy
rank-order packer that fills a token budget. Everything else is scaffolding around
that core. The scaffolding is unusually good — the integrity layer, the encoder
identity contract, the audit harness and the failure archive are better than most
production systems. The core remains an average retrieval system, and the project
knows it: the Cycle 37 v7.1 replay retains 205/246 annotated needles at 2,048
tokens with fielded BM25 and 223/246 with the explicit raise-relation channel,
against 225/246 for the frozen rival comparator. Cycles 36-37 shipped the
multi-field BM25 and structural naming work into product format v7 and then
repaired its incremental FTS5 semantics in format v8. And the
bottleneck has already moved: the candidate pool contains the required source for
**241 of 246** questions while only **205** survive packing. The search is still
aimed at seeds. It should be aimed at allocation, at structure, and at the free
supervision the corpus already contains.

---

## 2. GROUND TRUTH: WHAT IS ACTUALLY IN THIS REPOSITORY

**CODE-CERTAIN.** There are two complete, unrelated products sharing one package.

| | Product A — the product | Product B — abandoned by the pivot |
|---|---|---|
| Entry points | `npk/pack/*`; CLI `compile/update/query/verify/stats` | `npk/{compiler,format,gateway,runtime,planner,plan,optimizer,cost,telemetry}.py`, `npk/context/*`; CLI `proxy/legacy-*/diff/benchmark/analyze/explain` |
| Thesis | Local context compiler, zero generative calls | HTTP proxy that rewrites prompts before a provider |
| Artifact | v8 block DB + external-content FTS5 + symbols + optional embeddings | v1 Gear-CDC content-addressed chunk store + FTS5 |
| Retrieval | FTS5 `bm25()` | Hand-written Python `BM25Scorer` |
| Status | Live | Dead weight, still shipped, tested, CLI-exposed |

Consequences that cost real velocity:

- Two `PackError` classes, distinguished in `npk/cli.py` by importing one as `PackV2Error`.
- Two `.npk` formats sharing one extension; `npk stats` guesses which by catching an exception.
- Three BM25 implementations: `npk/context/bm25.py`, FTS5, and the posting-list
  scorer in `benchmarks/seed_metadata.py`.
- The legacy tree remains shipped and tested for historical replay, but the
  current default query path keeps its term analysis in `npk/pack/select.py` and
  does not import `npk.context` modules. Optional semantic retrieval still loads
  the explicitly requested local encoder.
- `npk.pack.select` the public *function* shadows `npk.pack.select` the *module*.
  This has already broken one audit gate (recorded in `research/CYCLE28_SEED_ABLATION.md`).
- The research harness is **4x the size of the product**. That ratio is itself an
  architectural finding; see R-13 and RANK 2.

---

## 3. NEW MEASURED EVIDENCE

The measurements in sections 3 through 12 are the pre-cycle backlog snapshot.
They remain useful baselines and hypotheses, but current product facts and
promotion decisions are appended in section 15. In particular, format v8 has
superseded the v5 artifact description and removed the duplicated FTS body.

### 3.1 The artifact is 6.5-7.2x the source text it indexes — MEASURED

| Pack | Source text | Artifact | Ratio |
|---|---:|---:|---:|
| `cycle26-index-updates-v1/unchanged/0/project.npk` (153 RST files) | 2,109,021 B | 15,183,872 B | **7.20x** |
| `cycle11-cache/0-members-candidate/base.npk` (deterministic, 105 mixed files) | 1,192,032 B | 7,708,672 B | **6.47x** |
| same corpus, `mode=semantic` (1,701 x 384 float32) | 1,192,032 B | 11,149,312 B | 9.35x |

The vector payload is 2,612,736 B but occupies 3,440,640 B stored: **32% overhead**
from per-row BLOB storage in a b-tree.

### 3.2 Historical: every block's text was stored twice — MEASURED

`blocks.text` and FTS5's `lexical_content.c1` are byte-identical
(2,109,021 = 2,109,021 on the RST pack). `snippet()` and `highlight()` are **never
called** on the v2 `lexical` table — the only uses are in the dead v1
`npk/format.py::query_pack`. The default FTS5 content mode therefore buys nothing
and costs a full second copy of the corpus.

### 3.3 The `symbols` table is 95-99% noise and unused on the default path — MEASURED + CODE-CERTAIN

| Pack | rows | `is_def = 0` | share |
|---|---:|---:|---:|
| RST corpus | 125,160 | 124,236 | **99.3%** |
| Python corpus | 65,118 | 62,233 | 95.6% |

Top "symbols" in the RST pack: `the` (1,068), `and` (941), `that` (938), `for` (846),
`with` (769). `_extract_symbols` applies `IDENT_RE = [A-Za-z_][A-Za-z0-9_]{2,}` to
**every block regardless of language**, so English prose becomes a symbol index.
With `symbols_name` and `symbols_block` this is roughly a third of artifact bytes.

`_symbol_channel` runs only when `retrieval == "hybrid"` (`npk/pack/select.py:451`).
The default is `"lexical"`. **In the shipped default configuration about a third of
the artifact is never read.**

### 3.4 Over half the per-update global digest work is provably redundant — MEASURED

`npk/pack/integrity.py::root_from_leaves` on the RST pack takes **11.6 ms**:

```
lexical_content   6.0 ms   <-- 52%
lexical_docsize   1.8 ms
lexical_data      1.6 ms
lexical_idx       0.5 ms
everything else   1.7 ms
```

`lexical_content` **is** `blocks.text`, and `blocks` is inside `LOCAL_TABLES`, so
every byte is already covered by the per-file leaf digests. The global half of the
Merkle scheme re-hashes the whole corpus on every update to learn nothing new. The
file-leaf cache made half the integrity layer incremental and left the other half
O(N). Cycle 21's own profile agrees: one-file update = **227.64 ms** on a
590K-token corpus with scanning only 28% of it.

### 3.5 `verify` is O(corpus) with a large constant — MEASURED

`full_file_digests` over 153 files / 2.1 MB = **424.5 ms**, and `_verify_contents`
additionally re-hashes every block and re-streams every FTS table: three full
passes. At monorepo scale `verify` will not be run, which quietly voids the
artifact-acceptance story in ADR 0004.

### 3.6 The dense channel is blind to a quarter of every corpus — MEASURED

`npk/context/embedding.py` sets `max_length=256` with `truncation=True` and mean
pooling, over blocks averaging 1,848 chars. Measured with the pinned MiniLM
tokenizer on the real mixed pack:

- **25.4%** of blocks exceed the 256-token window.
- For those blocks the median fraction of the original text actually encoded is
  **0.612**; p10 = **0.276**.
- MiniLM's own `model_max_length` is **512**. The 256 is a self-imposed halving.

The blocks most likely to be truncated are the largest, i.e. the implementation
bodies. This is a mechanical, sufficient explanation for why hybrid retrieval has
never earned promotion across nine cycles: **the semantic index has been indexing
the tops of functions.**

### 3.7 The highest-value retrieval feature is empty for entire corpora — MEASURED + CODE-CERTAIN

`_split_markdown` recognizes only ATX (`#`) headings. reStructuredText uses `===`
and `---` underlines. Verified on `sqlalchemy/doc/build/core/connections.rst`:

```
markdown-style heading lines found: 0
split_source(text, "rst") -> 27 blocks, all name=None
```

The whole file becomes one block, then a blind character-window recap chops it up.
On the stored SQLAlchemy pack: **`name IS NULL` for 1,141 / 1,141 blocks (100%)**.

Cycle 28 measured that adding `name` and `path` as separate BM25 fields lifts
retention from **148 to 205 / 246** at 2,048 tokens. That +38% is *structurally
unavailable* wherever `name` is null — every `.rst`, `.txt`, `.json`, `.yaml`,
`.toml`, `.sql`, `.html`, `.css` file, **and every JavaScript, TypeScript, Go,
Rust, Java, Ruby, C, C++, C#, PHP and shell file**, because only Python has an AST
splitter. Cycle 26's poor documentation-corpus results are exactly what an
anonymous-block corpus predicts.

### 3.8 Security hardening is inverted — CODE-CERTAIN

`npk/format.py::configure_connection` (the **dead** v1 path) sets `trusted_schema=OFF`,
`enable_load_extension(False)`, `query_only=ON`, `SQLITE_DBCONFIG_DEFENSIVE`,
`setlimit(LENGTH)`, `setlimit(SQL_LENGTH)` and a progress handler.

`npk/pack/format.py::connect` (the **live** path, which opens third-party `.npk`
files) sets none of them, and `read_manifest` executes `SELECT` against an untrusted
schema *before* `validate_tracking` runs.

### 3.9 Reproduction

Run with the venv interpreter from the repository root. Opens artifacts read-only
and writes nothing.

```python
import sqlite3, pathlib, time, hashlib, sys
sys.path.insert(0, '.')
from npk.pack.integrity import root_from_leaves, cached_file_digests, _rows, _feed_rows, GLOBAL_TABLES

p = pathlib.Path("experiments/runs/packs/cycle26-index-updates-v1/unchanged/0/project.npk").resolve()
con = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
con.row_factory = sqlite3.Row
q = lambda s: con.execute(s).fetchone()[0]
print("artifact bytes", p.stat().st_size, "block chars", q("SELECT SUM(LENGTH(text)) FROM blocks"))
print("lexical_content bytes", q("SELECT SUM(LENGTH(CAST(c1 AS BLOB))) FROM lexical_content"))
print("symbols", q("SELECT COUNT(*) FROM symbols"), "refs", q("SELECT COUNT(*) FROM symbols WHERE is_def=0"))
print("name IS NULL", q("SELECT COUNT(*) FROM blocks WHERE name IS NULL"), "of", q("SELECT COUNT(*) FROM blocks"))
leaves = cached_file_digests(con)
t = time.perf_counter(); root_from_leaves(con, leaves)
print("root_from_leaves ms", round((time.perf_counter() - t) * 1000, 2))
for table in GLOBAL_TABLES:
    d = hashlib.sha256(); t = time.perf_counter()
    _feed_rows(d, _rows(con, table, "WHERE key != 'root_sha256'" if table == "manifest" else ""))
    print("   ", table, round((time.perf_counter() - t) * 1000, 2), "ms")
```

---

## 4. THE FIVE ASSUMPTIONS UNDER CHALLENGE

1. **A block is a bag of words.** It is a structured record: name, qualified path,
   signature, docstring, decorators, raised exceptions, default values, body. The
   project's own strongest measured result says so and it has not shipped.
2. **Selection is rank-then-greedily-fill.** It is a knapsack and a coverage
   problem solved by a heuristic with no guarantee. The documented failure
   `B-b8c5ec3852` — the needle at rank 10 crowded out by six near-identical
   `__exit__` methods — is a textbook diversity failure.
3. **Retrieval quality is the bottleneck.** The pool holds the answer for 241/246
   questions; 205 survive packing. The bottleneck moved to allocation two cycles ago.
4. **Integrity must hash everything derivable.** Half the update cost buys zero
   information — and a primitive exists (R-2) that makes the whole digest O(1) per
   row regardless.
5. **Labels are scarce and must be hand-made.** They are not. Docstrings, test
   names, assertions, execution traces and commit messages are free,
   machine-readable, corpus-resident supervision. This is the largest unexploited
   resource in the project and it already sits inside every compiled artifact (R-1).

---

## 5. TIER A — HIGH-CONFIDENCE IMPROVEMENTS

Measured defects or near-certain wins. Treat as engineering, not research.

### A-1 Promote multi-field BM25 (BM25F) into the artifact

- **Assumption challenged.** A block is one flat FTS5 document; `name` and `path`
  are metadata, not searchable fields.
- **Mechanism.** Replace `fts5(block_id UNINDEXED, content, ...)` with
  `fts5(body, name, path, doc, block_id UNINDEXED, tokenize="unicode61 remove_diacritics 2 tokenchars '_'")`,
  populate columns in `_write_file_blocks`, query with column weights via
  `bm25(lexical, w_body, w_name, w_path, w_doc)`.
  `benchmarks/seed_metadata.py::field_rank` is a working reference implementation
  against a sidecar. The work is moving it into `npk/pack/{format,compile,select}.py`
  with file-scoped invalidation and bumping `PACK_FORMAT_VERSION` to 6.
- **Why better.** Already measured: 148 -> **205** / 246 at 2,048 tokens; 120 -> 162
  at 512; 183 -> 229 at 8,192. Paired bootstrap over 207 question groups:
  +0.1992 [0.1460, 0.2543]. Free at query time; costs one copy of short metadata.
- **Impact HIGH. Novelty COMMON (BM25F, Robertson & Zaragoza 2004). Difficulty MEDIUM.**
- **Risks.** The sidecar is rebuilt from scratch; incremental invalidation of a
  multi-column FTS table is where the bugs live. Field weights tuned on inspected
  dev data will overfit — ship `1,1,1` (which already ties `names4`) and treat
  weight tuning as a separate held-out experiment (see R-1 for a principled way to
  tune them per corpus). **A-2 is a hard prerequisite, not a companion.**
- **Validation.** Re-run `cycle28-seed-metadata-v1` arms `body160` vs `fields`
  through the *product* selector; assert byte-identical selections to the frozen
  sidecar run. Then compile -> mutate one file -> update -> compare against a fresh
  compile over 100 random mutations.

### A-2 Structural naming for every language, not just Python

- **Assumption challenged.** Structure extraction is a Python-only luxury.
- **Mechanism.** Three tiers, no new dependencies for tiers 1-2.
  1. RST/heading-aware splitter: recognize RST section underlines and overlines
     (runs of `= - ~ ^ " # * + <` at least as long as the title, previous line
     non-blank) and directives (`.. code-block::`, `.. class::`). Set `name` to the
     **heading path**, e.g. `Connections > Engine Disposal`.
  2. Brace-language splitter: brace-depth tracking plus the existing `DEF_RE` gives
     function/class boundaries for JS/TS/Go/Rust/Java/C/C++/C#/PHP in roughly 50 lines.
  3. Optional: tree-sitter grammars behind an extra.
- **Why better.** Measured: 100% of blocks in the SQLAlchemy corpus have
  `name IS NULL`, so A-1's entire +38% is inaccessible there. Heading paths are the
  natural analogue of qualified names for prose, and they are what a user's question
  actually resembles.
- **Impact HIGH. Novelty COMMON. Difficulty MEDIUM (1-2) / HIGH (3).**
- **Risks.** RST underline false positives (tables, `---` separators). Changing block
  boundaries invalidates every frozen comparison — must be a v6 recompile with old
  boundaries retained as a control arm.
- **Validation.** Recompile the SQLAlchemy corpus; assert `name IS NULL` < 15%.
  Re-run Cycle 24's ten SQLite scenarios and Cycle 26's 202 tasks at matched caps.
  Promotion requires **no loss** on rich/jinja2/werkzeug and a gain on docs.

### A-3 Stop storing the corpus twice

- **Assumption challenged.** FTS5 needs its own copy of the text.
- **Mechanism.** `fts5(..., content='blocks', content_rowid='id')`. Deletes become
  `INSERT INTO lexical(lexical, rowid, ...) VALUES('delete', old_id, old_text)`,
  supplied from `blocks` before `_drop_file` removes them. SQLite 3.49.1 is present,
  so `contentless_delete=1` is also available if external content proves awkward.
- **Why better.** Removes 2.1 MB from a 15.2 MB artifact (~14% of file size, ~50% of
  the text payload), removes the largest term in the global digest (3.4), and cuts
  write amplification per changed file. `snippet()` is never used, so nothing is lost.
- **Impact MEDIUM-HIGH. Novelty COMMON. Difficulty MEDIUM.**
- **Risks.** External-content FTS5 fails silently and corruptly if index and content
  diverge. Mitigate by adding `INSERT INTO lexical(lexical) VALUES('integrity-check')`
  to `verify`. `GLOBAL_TABLES` must drop `lexical_content`.
- **Validation.** Compile both ways; assert identical `bm25()` rankings over 1,000
  queries; measure artifact bytes, update latency, verify latency; run the FTS5
  integrity-check after 100 random mutate/update cycles.

### A-4 Make `symbols` a definition index, and switch it on by default

- **Assumption challenged.** Indexing every identifier occurrence gives a
  high-precision seed channel.
- **Mechanism.** Restrict reference emission to code languages, and there to
  call sites (`NAME(`) rather than every bare word; or drop references entirely
  since `_symbol_channel` already ranks `SUM(is_def) DESC, COUNT(*) DESC`. Then
  **enable the definition-only symbol channel on the default lexical path**, where
  it costs one indexed lookup.
- **Why better.** Measured 99.3% / 95.6% of rows are non-definitions; the table plus
  its two indexes is roughly a third of artifact bytes and is entirely unread in the
  default configuration. Meanwhile the highest-precision available signal — exact
  identifier definition — is switched off by default.
- **Impact MEDIUM (storage) / HIGH (if the def channel helps the default path).
  Novelty COMMON. Difficulty LOW.**
- **Risks.** Enabling the channel changes every frozen ranking; it must be an arm,
  not an edit. Definition-only symbols are meaningless for prose — gate by language.
- **Validation.** Two separate experiments. (i) Prune references, assert every
  existing hybrid selection is unchanged (references only break ties), measure bytes.
  (ii) Add `symbol_defs` as a default-path channel and re-run the 246-annotation matrix.

### A-5 Remove derivable state from the global root digest

- **Assumption challenged.** Everything in the file must be hashed for the root to mean anything.
- **Mechanism.** Drop `lexical_content` from `GLOBAL_TABLES`, or make it not exist
  via A-3. Optionally hash FTS postings per segment with cached segment digests.
  **Supersedes itself if R-2 lands** — R-2 makes the whole digest incremental and is
  the better answer.
- **Why better.** Measured: 6.0 of 11.6 ms of global digest work on a 2.1 MB corpus
  spent hashing bytes already hashed by the per-file leaves. This is the term that
  scales with corpus size rather than change size, i.e. the reason the "incremental
  compiler" is not incremental. Removing it costs zero detection power for content
  changes; it costs only detection of an FTS shadow table that disagrees with
  `blocks`, which A-3 makes structurally impossible and `verify` can check directly.
- **Impact MEDIUM now, HIGH at 10x scale. Novelty UNCOMMON — the argument is the
  contribution: an integrity design that double-counts derivable state converts
  O(delta) into O(N) for no information gain. Difficulty LOW-MEDIUM.**
- **Risks.** Invalidates every existing artifact and frozen receipt. Must be a v6
  bump. ADR 0005's claim must be restated: refreshing dirty leaves still reproduces
  full recomputation, but the definition of the root changes.
- **Validation.** Stage-instrument `update_pack` on Cycle 21's 138-file / 590K-token
  corpus at 1, 2, 14 and 100 changed files, before and after. **Justify if** the
  non-scan portion of a one-file update drops >= 30%. **Reject if** any corruption
  fixture in `tests/test_pack_integrity.py` or `benchmarks/integrity_challengers.py`
  stops being detected.

### A-6 .. A-15 Smaller certain wins

| # | Finding | Change | Impact | Difficulty |
|---|---|---|---|---|
| A-6 | `_available_tokens` pulls every block's text into Python per compile/update | `SELECT COUNT(*), SUM(LENGTH(text)) FROM blocks` (measured 1.5x on 2 MB; grows with corpus). Better: maintain as a counter under the existing triggers, O(delta) | LOW-MED | LOW |
| A-7 | v2 `connect()` lacks every hardening the dead v1 path has | Add `trusted_schema=OFF`, `enable_load_extension(False)`, `query_only=ON` for readers, `SQLITE_DBCONFIG_DEFENSIVE`, `setlimit(LENGTH/SQL_LENGTH)`, progress handler — **before** the first `SELECT` on an untrusted artifact | MED (security) | LOW |
| A-8 | No `mmap_size`, `cache_size`, `page_size`, `temp_store`; a fresh connection plus `BEGIN` per query | Persistent read connection on `PackSelector`, `PRAGMA mmap_size` sized to the artifact, `page_size=8192` at create, statement reuse | MED | LOW |
| A-9 | Every channel query joins `files` and sorts the whole result for tie determinism (`ORDER BY bm25, f.path COLLATE BINARY, b.ordinal`); Cycle 8 measured this cost | Precompute `blocks.canonical_rank INTEGER` at compile; `ORDER BY bm25(lexical), b.canonical_rank`. Identical semantics, no join | MED | LOW |
| A-10 | 25.4% of blocks truncated at 256 tokens; median 61% encoded; MiniLM supports 512 | Raise `max_length` to 512 as a floor; real fix is B-8 | MED | LOW |
| A-11 | `_lexical_terms` issues a `SELECT 1 FROM lexical MATCH` probe per camel-case token per query just to ask "is this term in the corpus" | Store a vocabulary Bloom filter or sorted term array in the manifest at compile. O(1) membership, no FTS round-trip. Cycle 25 measured this probe as the thing that made splitting affordable — make it free | LOW-MED | LOW |
| A-12 | Two `.npk` formats, two `PackError`s, three BM25s, a dead HTTP proxy | Move Product B to `legacy/`, off the CLI and out of the import graph; archive its tests | MED (velocity) | MED |
| A-13 | `npk.pack.select` imports `npk.context.info_gain` for `content_terms()` | Move `content_terms` / `STOPWORDS` / `_query_terms` to `npk/pack/terms.py`. Also removes the module/function shadowing footgun that already broke one audit gate | LOW | LOW |
| A-14 | Compiler is single-threaded with row-at-a-time `INSERT` | `executemany` for blocks/symbols/assignments; parse and symbol-extract in a process pool, serialize only writes. Cycle 22 named Python parsing "a substantial floor" | MED | MED |
| A-15 | `scan_source` returns a list holding every file's full decoded text before any writing | Yield `SourceFile` lazily. At the documented 128 MB `max_source_bytes` the current design holds the whole corpus as Python `str`, 2-4x RAM after UTF-8 widening | MED at scale | LOW |

---

## 6. TIER B — STRONG EXPERIMENTAL IDEAS

### B-1 Packing is a knapsack; stop solving it greedily

- **Assumption challenged.** Fill the budget in fused-rank order, skipping misfits.
- **Mechanism.** With exact per-block token costs (already persisted by
  `benchmarks/compiled_count_index.py`) and fused RRF scores as values, run a 0/1
  knapsack DP over <= 240 candidates at budget <= 8,192 — about 2M cells, under 20 ms
  in NumPy, and exact. The join-boundary correction is bounded by `|selected|`;
  reserve it as slack and reconcile once at the end.
- **Why better.** The current loop can leave arbitrarily much budget unused: it skips
  a 900-token block at rank 3 and then admits nothing else large. Greedy-by-rank is
  not even greedy-by-density.
- **Impact MEDIUM. Novelty COMMON. Difficulty MEDIUM.**
- **Risks.** Optimizing score is not optimizing evidence; a higher total RRF score
  can retain fewer needles. Requires the exact-count index to become a product feature.
- **Validation.** Replay `cycle28-packing-v1` (8,658 selections) with knapsack as a
  14th method. **Justify if** retention rises at >= 2 of 3 caps with no overruns.
  **Reject if** flat or worse — then B-2 is the real answer and B-1 is only latency.

### B-2 Budgeted maximum coverage: the principled fix for the crowding counterexample

- **Assumption challenged.** Diversity can be approximated by round-robin grouping
  over file or method name — falsified by a permanent fixture in Cycle 28.
- **Mechanism.** Define coverage over the query's evidence atoms (content terms,
  identifier components, and with B-4 typed relations). Select `S` maximizing
  `f(S) = sum over atoms of w_a * [a covered by S]` subject to `sum cost(b) <= B`.
  `f` is monotone submodular; the cost-effective lazy greedy of Leskovec et al. gives
  a **(1 - 1/e)** approximation with a lazy priority queue.
- **Why better.** This is a mechanism for the exact documented failure: `B-b8c5ec3852`
  loses `Traceback.from_exception` because ranks 1-9 are repeated `__exit__` methods.
  Under coverage the second `__exit__` adds near-zero marginal gain and is skipped.
  Grouping failed because it changed *visit order* without changing the *objective*;
  this changes the objective, and it has a guarantee, which grouping did not — the
  project falsified grouping with a 14-character fixture precisely because it had none.
- **Impact HIGH. Novelty UNCOMMON here, standard in summarization/IR
  (Lin & Bilmes 2011). Difficulty MEDIUM.**
- **Risks.** Coverage over query terms is a proxy for coverage over answer-relevant
  facts; a block covering many terms shallowly can beat the one that implements the
  behavior. Use `alpha * relevance + (1 - alpha) * coverage` and sweep `alpha` on
  declared holdout only. Note that query-term coverage is already the project's own
  risk signal, so this closes a loop: **optimize the thing you already measure.**
- **Validation.** Methods 15-17 (`alpha` in {0, 0.5, 1}) on the frozen packing matrix.
  **Justify if** `B-b8c5ec3852` is recovered **and** aggregate retention improves at
  2,048. **Reject if** it recovers the counterexample while losing more elsewhere —
  the same trade Cycle 29 correctly refused for compaction.

### B-3 Pseudo-relevance feedback: zero-LLM query expansion

- **Assumption challenged.** The seed stage sees only the user's literal terms;
  improving it means better indexes.
- **Mechanism.** Classic RM3 / Rocchio. BM25 -> take top-k blocks (k ~ 10) -> extract
  their highest tf-idf terms not in the query -> re-issue an expanded query with
  original terms weighted higher -> fuse with the unexpanded ranking. Two FTS5
  queries instead of one. All `df` statistics are already in the index.
- **Why better.** Attacks the measured gap directly: the pool contains the needle for
  241/246 questions but only 205 survive. Field indexing changes *which* documents
  enter the pool; PRF changes *how they are ordered*, by borrowing the corpus's own
  vocabulary — exactly the semantic gap the project has been trying to close with
  encoders costing 113 s of indexing and 13 s per rerank query. PRF costs ~2 ms.
  It is one of the most consistently positive results in 30 years of IR and **appears
  nowhere in 38 research notes or 209 benchmark modules.**
- **Impact HIGH. Novelty COMMON in IR, RESEARCH-LIKE for this project. Difficulty LOW-MEDIUM.**
- **Risks.** Query drift — PRF is harmful when initial results are bad, which is the
  seed-failure case. Guard: expand only when top-1 BM25 clears a floor, and always
  keep the unexpanded ranking as a fused channel so expansion can add but not replace.
  The existing `dense_floor` is the same pattern.
- **Validation.** Arms `body160+rm3`, `fields+rm3` at all three caps on the 246
  annotations plus 15 behavior questions. Sweep `k` in {5,10,20}, `n_terms` in {10,20}
  on the 15 behavior questions only, then apply one setting to the 207. **Justify if**
  `fields+rm3` >= `fields` + 8 at 2,048. **Reject if** it wins on retrieval but loses
  >= 2 of the 15 behavior cases.

### B-4 Generalize typed structural relations beyond `raises`

- **Assumption challenged.** CRISP's `raises` lookup is an artifact of
  exception-flavoured questions.
- **Mechanism.** Walk the AST already parsed in `_split_python` and emit typed rows:
  `raises`, `catches`, `warns`, `decorated_by`, `defaults(param, literal)`, `yields`,
  `returns_literal`, `reads_config(key)`, `string_literal`, `calls`. Store as
  `relations(block_id, kind, name)` with a `(kind, name)` index. At query time detect
  the relation being asked about with a small, fixed, declared pattern table and add a
  high-precision seed channel.
- **Why better.** The largest single measured jump in the project: `crisp_shared` 206
  -> `crisp_shared_raises` **225** at 2,048, from one relation kind.
  `benchmarks/seed_metadata.py::raise_sites` already implements extraction. Exceptions
  are not special: "what is the default timeout", "what does it return when empty",
  "which decorator caches this" are the same shape with a different relation.
- **Impact HIGH. Novelty UNCOMMON. Difficulty MEDIUM-HIGH.**
- **Risks.** A syntactic `raise X` does not prove `X` executes; the same caveat applies
  to every relation. These are seeds, never behavioural proof. Python-only until A-2
  tier 3. The query->relation classifier is where overfitting will happen: keep it a
  fixed declared table, not a tuned model.
- **Validation.** Pool coverage per relation kind on the 246 annotations; then a
  `fields+relations` arm at all caps; then the 15 behavior questions. **Justify if**
  it closes >= half the residual `fields`(205) -> `crisp_shared_raises`(225) gap with
  gains spread across >= 3 kinds. **Reject if** gains are confined to exception
  questions — that is a publishable negative showing CRISP's lead is dataset-shaped.

### B-5 Certified token upper bounds without the tokenizer

- **Assumption challenged.** You either use `len // 4` (which overran the real cap in
  36 of 1,230 observations) or you need the full tokenizer.
- **Mechanism.** For BPE, the pre-tokenizer regex split is a partition of the text and
  merges only combine pieces within a cell. Therefore `|pieces|` is an exact lower
  bound and the per-cell byte sum is an exact upper bound on token count; running the
  pre-tokenizer without the merge table is far cheaper than full encoding. Store a
  per-block certified upper bound `U(b)` at compile time. Admit against `sum U(b)`;
  the result provably never overruns. Refine with the exact counter only if the
  conservative bound leaves >= 15% of budget unused.
- **Why better.** Turns budget safety from an empirical hope into a proof, at compile
  cost, with no tokenizer at query time. Strictly stronger than `CompactBoundaryCount`,
  which is exact but requires the pinned asset and its `boundary_enabled` guard.
  Composes with B-1: knapsack over certified costs yields certified-feasible optimal packing.
- **Impact MEDIUM-HIGH. Novelty RESEARCH-LIKE — the bound is elementary but is not
  used as an admission certificate anywhere in this project or its cited prior art.
  Difficulty MEDIUM.**
- **Risks.** Valid only for tokenizers whose pre-tokenizer is a true partition with no
  normalizer and no lstrip/rstrip added tokens — `benchmarks/boundary_tokenizer.py`
  already encodes exactly this guard. Loose bounds waste budget; measure the gap.
- **Validation.** For all 3,513 blocks against the pinned NIM tokenizer compute `U(b)`
  and the true count. **Justify if** median tightness <= 1.15 with zero violations over
  100k random joins. **Reject if** looser than 1.4x — the wasted budget then costs more
  retention than the overruns cost safety.

### B-6 Prefix-stable evidence emission: make the provider's cache hit

- **Assumption challenged.** Evidence order should be relevance order, and
  prompt-cache behaviour is the caller's problem.
- **Mechanism.** (a) Emit in canonical corpus order (`path`, `ordinal`) — free,
  deterministic, and arguably better for the model since related code stays adjacent.
  (b) Optional sticky packer preferring previously-sent blocks on ties, via a
  caller-supplied `previous_block_ids`. (c) Stable blocks first, volatile last, so
  the shared prefix is maximal across a session.
- **Why better.** This is the surviving part of the original NeuralPack thesis at the
  layer where it works. Providers bill cached input at 10-25% of uncached
  (`npk/cost.py` already records 1.25 vs 2.50 for gpt-4o) and cache on exact prefix
  match. An agent session over one repo issues dozens of correlated queries; today
  each gets a freshly permuted context and pays full price. Ordering is free. The
  instrument already exists: `UsageInfo.cached_tokens` is parsed, logged and audited.
  **This is the one idea with a dollar-denominated, directly observable outcome** —
  precisely the claim class the project has repeatedly had to retract.
- **Impact HIGH (economic). Novelty UNCOMMON — cache-aware layout applied to prompt
  construction. Difficulty LOW-MEDIUM.**
- **Risks.** Position effects: models weight early and late context differently, so
  corpus order may cost accuracy. Measurable, and must be measured. Provider cache
  minimums (often 1,024 tokens) mean small budgets never hit. Sticky packing adds
  cross-request state — keep it caller-supplied, never implicit.
- **Validation.** (i) Offline: replay the 246-annotation matrix with canonical
  ordering; selected *sets* are unchanged by construction, so only hashes need
  comparing. (ii) Live: a scripted 20-turn agent session over urllib3 through
  `benchmarks/repository_eval.py --live`, three arms, reporting provider `cached_tokens`.
  **Justify if** cached-token share rises >= 25 points with no drop in oracle pass rate.
  **Reject if** answer quality falls at all — a cheaper wrong answer is the failure
  mode this project spent 29 cycles eliminating.

### B-7 .. B-15 Further experimental candidates

| # | Idea | Mechanism and rationale | Impact / Novelty / Difficulty |
|---|---|---|---|
| B-7 | **Content-addressed block store** | Split into `block_text(sha256, text)` and `blocks(..., text_sha)`. `blocks_sha` already exists. Dedups license headers, `__init__.py`, vendored copies and multi-version corpora; makes the `_retain_changed_vectors` temp-table dance automatic and cross-file; makes `compiled_count_index`'s `text_sha` a first-class join. Recovers the good idea from the abandoned v1 CDC container — content addressing — at the block level where it pays, not the byte level where it measured 5-8x slower. Gate on measuring duplicate share first | MED-HIGH / COMMON / MED |
| B-8 | **Multi-vector dense retrieval** | Encode ceil(tokens/256) overlapping windows per block, score by max (ColBERT-lite). Storage ~1.35x. Every hybrid experiment across nine cycles ran against an index that could not see the second half of its largest documents (3.6). If it still loses, that is a *stronger* negative worth recording | MED-HIGH / COMMON / MED |
| B-9 | **Cost-based channel planner** | Compute term IDF at compile; classify the query (rare identifier vs prose vs relation-shaped) and pick channel weights per query — a database query optimizer for retrieval using selectivity statistics you already have. Their data shows `body160` wins `B-b8c5ec3852` where `fields` loses; a router could take both | MED / UNCOMMON / MED |
| B-10 | **Query and postings cache** | LRU keyed by `(root_sha256, normalized_terms, budget, policy)`. Agent sessions repeat queries constantly. Free correctness — the root digest is the key | MED / COMMON / LOW |
| B-11 | **Dedent and whitespace canonicalization of emitted evidence** | `textwrap.dedent` a method block to column 0, record the original indent in the span header. Whole-block dedent preserves Python semantics; BPE spends real tokens on leading indentation. Unlike Cycle 29's docstring removal, **no information is destroyed**. See R-4 for the stronger version | MED / UNCOMMON / LOW |
| B-12 | **Multi-pack federation** | Query N packs (repo + deps + docs) with merged `df` so BM25 IDF is corpus-global. Store per-pack `df` as a small mergeable table. Today one pack = one source root, which is not how a workspace is shaped — and their own best benchmark corpus is three packages pretending to be one root | MED-HIGH / UNCOMMON / HIGH |
| B-13 | **Tiny monotone learning-to-rank** | Fit a 6-10 feature linear model (BM25 per field, is_def match, relation match, block length) with **repo-level** cross-validation: train on rich+jinja2, test on werkzeug. Monotone and linear, therefore auditable. The aversion to fitting on inspected data is right; repo-level holdout is the standard answer | MED / COMMON / MED |
| B-14 | **Trained-dictionary compression of block text** | zstd dictionary trained on the corpus at compile, stored in the manifest; roughly 4-6x on many small similar blocks; decompress only the ~60 selected. Shrinks artifact, digest streaming and I/O together. "Compile once, reuse many" applied to the compressor itself | MED / UNCOMMON / MED |
| B-15 | **Sampling verifier** | `verify` is 424 ms per 2 MB and grows. Offer `verify(level='sample', k=64)`: always check root, schema and contracts; spot-check `k` random block leaves. Soundness becomes probabilistic and must be labelled so — but it makes verification affordable at a scale where today it simply will not be run | MED / UNCOMMON / LOW |

---

## 7. TIER R — BEYOND-CONVENTIONAL IDEAS

Tiers A and B are what a good engineer would eventually find. Tier R is what this
project is missing because every idea in it crosses an abstraction boundary the
codebase currently treats as a wall. Each borrows a mechanism from a field the
project has not drawn on: incremental cryptography, delta debugging, Datalog,
mining software repositories, incremental computation, branch prediction,
control theory, and self-supervised learning.

**The one-line thesis of this section:** the project keeps searching for a better
*ranking function* when its real, unexploited assets are (i) the corpus's own free
supervision, (ii) executability as a sufficiency oracle, and (iii) the fact that
its workload is a *session*, not a sequence of independent queries.

---

### R-1 The corpus is its own labelled training set — compile-time self-tuning retrieval

**Current assumption.** Retrieval labels are scarce, must be hand-authored, and are
therefore always "inspected development data" — a caveat that appears in every
single cycle report and is the reason no claim in this repository can be strong.

**Mechanism.** Every corpus already contains thousands of `(query, gold block)` pairs
in machine-readable form, and the compiler currently throws all of them away:

| Free label source | Query | Gold answer | Available from |
|---|---|---|---|
| Docstring | the docstring's first sentence | the function/class block beneath it | `ast` — already parsed in `_split_python` |
| Test name | `test_retries_on_connection_error` -> "retries on connection error" | the function under test (resolvable via the test's imports/calls) | `ast` |
| Test assertion | "what does `f(x)` return for x=..." | the implementation | `ast` + optional execution |
| Section heading | "Engine Disposal" | that RST/MD section | A-2 tier 1 |
| Commit message | "fix retry backoff off-by-one" | the changed blocks | `git log --numstat` |
| Issue/PR title | the title | the referenced blocks | out of scope for now |

At compile time, generate this probe set, hold each gold block's own docstring out
of its indexed body for the probe, rank, and compute MRR@10. That is a **per-artifact,
zero-LLM, zero-human, automatically-refreshed retrieval benchmark with thousands of
examples**, produced as a byproduct of compilation.

Then use it. At compile time, fit — per artifact — the handful of parameters the
project has been guessing at for 29 cycles:

- BM25F field weights (A-1) instead of shipping `1,1,1` and hoping.
- `alpha` in coverage packing (B-2).
- RM3 `k` and `n_terms` (B-3).
- `candidate_limit`, `MAX_BLOCK_TOKENS`, the `dense_floor`.
- Which channels are worth running at all for *this* corpus.

**Why it might be better.** Three distinct wins that compound:

1. It converts every tuning decision from "a constant a human chose once" into
   "a value fitted on this corpus", which is what profile-guided optimization does
   for compilers and what every serious search system does with click logs. This
   project has no click logs. It has docstrings, which are *better*: they are
   author-written descriptions of the exact code beneath them.
2. It is **self-supervised and sealed by construction** — the probe generator never
   sees the retrieval system's output, and no human inspected the pairs. That is a
   materially stronger epistemic position than every dataset in `benchmarks/`.
3. Cycle 29 already proved docstrings carry retrieval-relevant signal (removing them
   loses evidence) but treated them only as *content*. They are **supervision**. That
   reframing is the whole idea.

**Impact EXTREME. Novelty RESEARCH-LIKE — self-supervised retrieval probes from
docstrings exist in the code-search literature (CodeSearchNet uses docstring-code
pairs for *training*), but using them as a *per-artifact compile-time
auto-tuner shipped inside the artifact* is not something I can find prior art for.
Difficulty HIGH.**

**Risks — read these carefully, this idea fails in specific ways.**
- **Leakage.** If the docstring is indexed in the block's own body, the probe is
  trivially self-matching. The gold block must be re-indexed with its docstring
  removed for the probe, which changes the index — so build a shadow scoring pass,
  not a shadow index.
- **Distribution mismatch.** Docstring probes are descriptive; real questions are
  often behavioural ("what happens when X is empty"). Parameters tuned on descriptive
  probes may not transfer. **Mandatory control:** measure correlation between probe
  MRR and the 246 hand-annotated needle results before trusting any fitted parameter.
  If the correlation is weak, this idea is a benchmark, not a tuner — still valuable,
  but a different product.
- **Degenerate corpora.** Repos with no docstrings get no probes. Fall back to shipped
  defaults and say so in the manifest.
- **Overfitting per artifact.** Fitting 6 parameters on 4,000 probes is fine; fitting
  600 is not. Cap parameter count and use held-out probes within the corpus.

**Validation.**
1. Generate probes for rich 14.2.0 + Jinja2 3.1.6 + Werkzeug 3.1.3. Report count.
2. **Correlation gate first, before any tuning:** compute probe MRR and the 246-needle
   retention for each of the nine existing `cycle28-seed-metadata-v1` arms. Rank the
   arms by each metric. **Justify proceeding if** Spearman correlation across arms is
   >= 0.7. **Reject the whole idea if** < 0.4 — the probes would then be measuring
   something orthogonal to the thing that matters, and no amount of tuning fixes that.
3. Only if the gate passes: fit field weights on probes, evaluate on the 246
   annotations and the 15 behavior questions. **Justify if** fitted weights beat
   `1,1,1` on the annotations. **Reject if** they do not — then ship `1,1,1` and keep
   the probes purely as an artifact health metric (R-10).

---

### R-2 Incremental multiset hashing: make integrity O(1) per row, by construction

**Current assumption.** Artifact integrity requires a Merkle-style digest whose global
half must stream every row of every global table on every update (measured: 11.6 ms
on a 2.1 MB corpus, growing linearly).

**Mechanism.** Replace the ordered-stream SHA-256 over global tables with an
**incremental multiset hash** — LtHash (lattice-based, additive over Z_2^16 vectors)
or MSet-XOR-Hash (Clarke, Devadas, van Dijk, Gassend, Suh, *Incremental Multiset Hash
Functions and Their Application to Memory Integrity Checking*, ASIACRYPT 2003). The
root becomes:

```
H(DB) = SUM over rows of h(framed(row))        (in the group; LtHash uses vector addition mod 2^16)
```

Inserting a row is `H += h(row)`; deleting is `H -= h(row)`. **No re-scan. Ever.**
The existing trigger infrastructure in `npk/pack/integrity.py` already fires on every
insert/update/delete of every local table — it currently records dirty file IDs; it
would instead accumulate the group delta. Ordering-independence is a *feature* here
because the current design already sorts rows to obtain a canonical order; a multiset
hash makes that sort unnecessary too.

**Why it might be better.**
- Turns O(N)-per-update integrity into **O(delta)**, mathematically, not by cleverly
  excluding derivable state (A-5 is a workaround; this is the fix).
- Removes the canonical-ordering `ORDER BY 1,2,3,...` in `_rows`, which is a full sort
  of every table on every digest.
- Makes `verify` incrementally checkable: an external party holding a previous root
  plus a delta log can verify without re-reading the artifact.
- Enables shipping *artifact deltas* with verifiable roots (feeds D-5).
- LtHash is deployed in production (Meta's Folly `LtHash`); this is not exotic.

**Impact HIGH — and it is the difference between "incremental compiler" being a
description and a marketing claim. Novelty RESEARCH-LIKE for this codebase; the
primitive is 20 years old and unused here. Difficulty HIGH.**

**Risks.**
- **Set semantics vs multiset semantics.** A multiset hash cannot distinguish row
  *order*, only membership and multiplicity. The current digest is order-sensitive.
  For a relational artifact where every table has a primary key, order carries no
  information — but this must be argued explicitly in an ADR, not assumed.
- **Security level.** MSet-XOR-Hash is secure only under a keyed/random-oracle model;
  LtHash needs 2048-byte state for ~200-bit security. Neither authenticates a
  publisher, which the project already correctly disclaims.
- **Cross-version compatibility.** Old artifacts cannot be migrated without a full
  recompute (which is fine — that is what a v6 bump is for).
- **Silent divergence.** If a trigger misses a write path, the incremental root drifts
  and nothing notices. Mitigation is mandatory: a `verify --full` that recomputes from
  scratch and compares, plus a fuzz harness that performs 10,000 random writes and
  compares incremental vs recomputed roots after each.

**Validation.** Implement LtHash over the same `framed()` encoding. Fuzz: 10,000 random
compile/update/delete sequences, assert incremental root equals recomputed root every
time. Then stage-instrument updates on Cycle 21's corpus. **Justify if** the digest
term of update cost becomes independent of corpus size (measure at 1x, 4x, 16x corpus)
**and** the fuzz harness finds zero divergences. **Reject if** any divergence, or if
the constant factor makes small updates slower than today.

---

### R-3 Verified context minimization: delta debugging as a sufficiency oracle

**Current assumption.** Evidence sufficiency is unknowable without a model. Every
`Selection` reports `"sufficiency": "unverified"`, and the README says plainly that a
nonempty selection is not proof of sufficient evidence. This is the project's deepest
unsolved problem.

**Mechanism.** For the class of questions where the answer is *executable* — which is
exactly the class the project's own behavior benchmarks use — sufficiency is decidable:

1. Take a question with an executable oracle (`benchmarks/repository_tasks.py`,
   `sqlalchemy_oracles.py`, `library_behavior_oracles.py` already have these).
2. Run the oracle under `sys.settrace` to get the executed line set `L`.
3. Define the predicate `P(S) = "the source subset S, when assembled, still contains
   every executed line in L"` — checkable with zero model calls.
4. Run **ddmin** (Zeller & Hildebrandt, *Simplifying and Isolating Failure-Inducing
   Input*, TSE 2002) over the candidate blocks to find a **1-minimal** subset
   satisfying `P`. That subset is a *verified-sufficient* context with respect to a
   stated, checkable criterion.

Now you have, for every executable question, a ground-truth **minimal sufficient
context** and its exact token cost. That gives the project three things it has never had:

- **A denominator.** "This question needs 340 tokens; we spent 2,048 and still missed
  it" is a far sharper diagnostic than "we retained 205/246 needles."
- **An oracle for packing research.** B-1/B-2 and intra-block span selection can be scored against the minimal
  sufficient set instead of against hand-drawn annotations.
- **A rate-distortion curve** (D-4) computed from real data rather than assumed.

**Why it might be better.** The project has spent 29 cycles trying to *approximate*
sufficiency with uncalibrated risk bands and coverage heuristics. For executable
questions, sufficiency can be *decided*, and the machinery (traces, oracles, frozen
fixtures) is already built and already used manually for 15 questions. This
industrialises it.

**Impact EXTREME on research quality; MEDIUM directly on the product. Novelty
HIGHLY EXPERIMENTAL — delta debugging is standard in test-case reduction and, to my
knowledge, has not been applied to LLM context minimization with an execution-trace
predicate. Difficulty HIGH.**

**Risks.**
- **Executed lines are not sufficient context for a *model*.** A human or model may
  need the surrounding class definition or a config default that was read but not
  executed on that path. The predicate is a *lower bound* on what is needed and must
  be labelled as such. Do not claim "minimal sufficient context for answering"; claim
  "minimal context containing the executed implementation."
- **ddmin is O(n^2) worst case.** With <= 240 candidate blocks and a cheap predicate
  this is fine; with line-level granularity it is not. Do blocks first.
- **Only covers executable questions.** Descriptive and design questions get nothing.
  That is acceptable — a partial oracle is infinitely better than none.
- **Trace noise.** Framework and stdlib frames must be filtered to the package under test.

**Validation.** Apply to the 15 existing behavior questions where traces already exist.
**Justify if** minimal sufficient contexts are found for >= 12/15 and their median
token cost is < 40% of the 2,048 budget — that would prove the budget is not the
binding constraint and redirect the whole research program toward allocation.
**Reject if** minimal contexts routinely exceed the budget — then the product needs
bigger budgets or D-10 iterative retrieval, which is itself a decisive finding.

---

### R-4 Token-cost-aware rendering: peephole superoptimization against a fixed tokenizer

**Current assumption.** The rendering of a block is fixed — it is the source bytes —
and token cost is therefore a given.

**Mechanism.** The target tokenizer is fixed and *known* (the project already pins and
audits the NIM tokenizer). Many renderings of the same block are semantically
identical but tokenize differently:

- Indentation width and tabs vs spaces (BPE merges runs of spaces at specific lengths).
- Trailing whitespace, blank-line runs, and CR/LF (already normalized — extend the idea).
- Whole-block dedent to column 0 (B-11).
- Line-continuation style, quote style in some contexts.
- Comment reflow width.

For each block, at compile time, enumerate the small set of semantics-preserving
renderings and store the cheapest under the pinned tokenizer, along with the exact
transformation needed to recover the original span for provenance. This is
**peephole optimization with the tokenizer as the cost model** — the same move a
compiler backend makes when it picks between equivalent instruction sequences.

**Why it might be better.** Token budget is the binding resource, and this buys budget
with *zero* information loss — categorically different from Cycle 29's docstring
compaction, which lost evidence and was correctly rejected. Every token saved is a
token available for another block. If indentation alone is 5-15% of a Python block's
tokens (measurable in an afternoon), that is 100-300 extra tokens of real evidence at
a 2,048 cap, for free.

**Impact MEDIUM-HIGH. Novelty UNCOMMON — superoptimization is standard in compilers;
applying it to prompt rendering against a fixed BPE cost model is not something this
project or its cited prior art does. Difficulty MEDIUM.**

**Risks.**
- **Semantics.** Python indentation is semantic *within* a block; whole-block dedent is
  safe, partial re-indentation is not. Restrict to transformations with a written
  proof of equivalence, and add a permanent fixture per transformation.
- **Provenance.** The emitted text must still map to real source spans. Record the
  transformation so `span` remains meaningful, and make the renderer's output
  reversible; refuse any transformation that is not.
- **Tokenizer coupling.** The optimal rendering depends on the target tokenizer. Store
  renderings keyed by tokenizer identity, or compute at query time from a small
  precomputed table. Do not bake one provider's tokenizer into the artifact.
- **Diminishing returns.** If measurement shows < 3% savings, drop it.

**Validation.** Measure first, build second. For all 3,513 blocks, compute token count
under the pinned tokenizer for: original; dedented; blank-run-collapsed; both.
**Justify if** median savings >= 6% with zero semantic-fixture failures. **Reject if**
< 3%, or if any equivalence fixture fails.

---

### R-5 Datalog over program facts: resolve the indirection the project refuses to guess at

**Current assumption.** `npk/pack/conflict.py` states outright: *"No literal-to-path
voting: a comment, example, or unused assignment can name any variant. A future
indirection resolver must prove the binding/use chain."* The project correctly
abstains rather than heuristically guessing.

**Mechanism.** Build that resolver. Emit B-4's typed relations as **facts**, then
evaluate a small fixed Datalog program to a fixpoint:

```
value(Sym, V)        :- assign(Sym, literal(V)).
value(Sym, V)        :- assign(Sym, name(Other)), value(Other, V).
default(Fn, Param, V):- signature(Fn, Param, name(Sym)), value(Sym, V).
effective(Fn, P, V)  :- default(Fn, P, V), not overridden(Fn, P).
```

`TIMEOUT = DEFAULT_TIMEOUT`, `DEFAULT_TIMEOUT = 30` resolves to `30` **with a derivation
chain** — and the chain is exactly the set of blocks that must be in the context. The
answer to "what is the default timeout" becomes: the resolved value, plus the minimal
set of source spans that prove it.

**Why it might be better.**
- It converts a retrieval problem into a *proof* problem for the question class where
  the project keeps losing: configuration, defaults, and indirection.
- The derivation chain **is** the evidence set — minimal, complete with respect to the
  rule set, and explainable. This is R-3's verified sufficiency achieved statically,
  for a different question class.
- Code-fact Datalog is well established (Doop for points-to analysis, CodeQL). Nobody
  has used the *derivation tree* as the context-selection unit under a token budget.
- It gives `conflict.py` something better than abstention: two variants of a symbol are
  a genuine conflict only if both are *reachable* under the rules.

**Impact HIGH for configuration/default/indirection questions. Novelty
HIGHLY EXPERIMENTAL as applied. Difficulty HIGH.**

**Risks.**
- **Soundness.** Python is dynamic. `getattr`, `importlib`, decorators and metaclasses
  break static resolution — `npk/context/safety.py::DYNAMIC_INDIRECTION` already
  detects exactly these patterns. The rules must be **conservative and fail-open**:
  when dynamic indirection is present in the chain, refuse to resolve and fall back to
  ordinary retrieval. Never present a possibly-wrong resolution as fact.
- **Scope.** Module-level constants only, initially. Class attributes, inheritance and
  conditional binding each need their own rules and their own counterexamples.
- **Rule creep.** A Datalog program grows without bound if driven by benchmark failures.
  Freeze the rule set per cycle and treat additions as promotable changes with fixtures.

**Validation.** Hand-collect 30 indirection questions from rich/Jinja2/Werkzeug where
the answer requires >= 2 hops. Measure: does today's selector retrieve *all* hops?
(Prediction: rarely.) Then measure the Datalog resolver's chain. **Justify if** it
produces complete correct chains for >= 20/30 with zero incorrect resolutions.
**Reject if** any incorrect resolution is produced without an abstention — a wrong
config value stated confidently is worse than a miss, and this project's whole
epistemic stance depends on not doing that.

---

### R-6 Structure from revision history, not from grammar

**Current assumption.** Block boundaries come from syntax. `.git` is in `EXCLUDED_DIRS`,
so the compiler never looks at history at all.

**Mechanism.** Mine `git log --numstat --follow` and per-commit line ranges. Lines that
**consistently change together** belong in one block; a boundary is a point of low
co-change correlation. This is content-defined chunking where the "content" is the
edit history rather than the bytes. Cheap to compute, and it yields two artifacts:

1. **Language-agnostic block boundaries** — works for every language including ones with
   no parser, attacking the same problem as A-2 from a completely different direction.
2. **A free importance/recency prior** — churn rate, author count, recency, and
   bug-fix-commit density per block. "Which code is responsible for this behaviour"
   correlates with "which code was recently touched by a commit whose message says fix."

**Why it might be better.** Cycle 23 tested *byte*-content-defined boundaries and got a
qualified negative; Cycle 22 tested exact block reuse and got 1.02-2.13x. Both operated
on the file's current bytes. Revision correlation is a different, richer signal that
the compiler currently discards entirely — and the churn prior is a ranking feature no
channel in this system has.

**Impact MEDIUM-HIGH. Novelty RESEARCH-LIKE — mining software repositories is a whole
field (Hassan et al.); using co-change as a *chunking* signal for retrieval is not
something I can find. Difficulty HIGH.**

**Risks.**
- **Not every corpus has history.** Vendored dependencies, released tarballs and
  generated docs have none. Must degrade gracefully to A-2 boundaries.
- **History is expensive to mine** and changes on every commit, which fights the
  incremental-update story. Compute once, store in the artifact, refresh on demand.
- **Reading `.git` is a security and privacy surface** the compiler has deliberately
  avoided. Branch names, author emails and unreferenced objects must never enter the
  artifact. The existing credential screen must run over any mined text.
- **Co-change may simply not beat syntax** for retrieval. It probably loses on Python
  and may win on C, RST and JS. That per-language split would itself be a good result.

**Validation.** Mine history for the three benchmark packages. Compare four splitters
(current, A-2 structural, co-change, co-change + structural) at matched budgets on the
246 annotations. Separately, add churn/recency as a ranking feature and measure alone.
**Justify if** either wins on >= 2 caps on any language family. **Reject if** neither
beats A-2 anywhere — and record it, because "history does not help code retrieval" is
a genuinely interesting negative.

---

### R-7 Demand-driven compilation: stop compiling what nobody asks about

**Current assumption.** Compile eagerly and completely; query cheaply. Compilation is
O(corpus) and updates are O(corpus)-ish (3.4, 3.5).

**Mechanism.** Invert it, using the incremental-computation model from Adapton / Rust's
`salsa` / *Build Systems à la Carte* (Mokhov, Mitchell, Peyton Jones, ICFP 2018).
Store only file hashes and a lazy block map at compile. Parse, split, index and embed a
file **the first time a query touches it**, memoized and invalidated by content hash.
The FTS index becomes a demand-materialized view with a cheap conservative pre-filter
(a per-file trigram or Bloom sketch, which is O(bytes) and needs no parsing) deciding
which files can possibly match.

**Why it might be better.**
- In a monorepo, a session touches a tiny fraction of files. Eager compilation pays for
  100% of a corpus to serve 1%.
- Update becomes trivially incremental: invalidate the hash, discard the memo, done.
  No FTS rebuild, no digest re-stream, no `available_tokens` scan.
- It dissolves the "compile is expensive but amortized" framing that ADR 0004 has to
  defend, replacing it with "compile is nearly free and cost follows use."
- The trigram pre-filter is exactly how `ripgrep`/`codesearch` achieve fast repo-wide
  search without an inverted index — a proven design at the scale this project wants.

**Impact HIGH at monorepo scale; NEGATIVE at small scale (adds latency to first query).
Novelty UNCOMMON — standard in build systems and IDEs, absent from this design.
Difficulty EXTREME.**

**Risks.**
- **First-query latency** becomes unpredictable, which is a genuinely bad property for
  an interactive tool and directly contradicts the current design's best measured
  feature (0.68-0.99 ms warm queries).
- **BM25 needs global `df`.** Lazy indexing means `df` is unknown until everything is
  indexed. Either maintain approximate global `df` from the pre-filter sketches, or
  accept scoring drift as the index warms — both need careful measurement, and drift
  breaks the project's determinism guarantees.
- **Integrity.** A partially materialized artifact has no stable root. Would need R-2
  plus a clear separation between "source truth" (hashed) and "derived cache" (not).
- This is the highest-risk item in this section. **Do not attempt before R-2 and D-5.**

**Validation.** Build a throwaway prototype on a synthetic 10M-token monorepo. Measure:
compile time, first-query latency, warm-query latency, memory, update time, and BM25
score drift vs a fully-indexed control. **Justify if** compile drops > 10x and warm
queries stay within 2x of eager, with zero ranking drift after warm-up.
**Reject if** ranking drifts at all in a way callers can observe — determinism is a
stated product property and is worth more than the compile time.

---

### R-8 Retrieval trace cache and speculative selection

**Current assumption.** Each query is independent and starts from nothing.

**Mechanism.** Borrow the CPU trace cache / branch predictor. Maintain a small
session-local table mapping a *query shape* (sorted content terms, or a cheap
locality-sensitive sketch of them) to the selection it produced. On a new query:

1. If a near-neighbour shape exists, **speculatively** return its selection immediately
   while computing the real one.
2. Verify: run the real retrieval; if the top-K sets agree within a threshold, the
   speculation was correct and cost nothing. If not, the caller gets the corrected set.
3. Track hit rate; disable speculation if it falls below a floor.

**Why it might be better.** Agent workloads are highly repetitive over one repo:
the same file gets asked about a dozen ways in a session. Combined with B-6, a
speculative hit is *also* a prefix-cache hit at the provider, so the win compounds.
The verify step keeps it exact — this is speculation with rollback, not caching with
staleness.

**Impact MEDIUM (latency), HIGH when combined with B-6 (cost). Novelty UNCOMMON —
speculative execution applied to retrieval. Difficulty MEDIUM.**

**Risks.** Session state in a library that is currently stateless and deterministic;
must be opt-in and caller-owned. Speculation that is wrong and *acted on* before
verification is a correctness bug — only expose it where the caller can accept a
correction (streaming/agentic use), never in the synchronous `select()` contract.

**Validation.** Replay a real agent session trace (`experiments/traces.jsonl` has the
schema). Measure shape-hit rate and speculation accuracy. **Justify if** hit rate > 30%
with > 90% top-K agreement. **Reject if** accuracy < 80% — corrections would then be
the common case and the mechanism is noise.

---

### R-9 Budget as a scheduled resource across a session, not a per-query constant

**Current assumption.** The caller passes `budget_tokens` per query and the selector
spends all of it.

**Mechanism.** Treat the session's total token spend as the resource and allocate it
across queries by marginal value, in the style of DVFS or a scheduler's proportional
share. The marginal-value signal is already computed and thrown away: the **fused score
decay curve**. When RRF scores fall off a cliff after 3 blocks, spending 2,048 tokens
buys noise; when they decay slowly, more budget genuinely buys evidence. Expose
`select(query, budget_hint=..., budget_max=...)` and return the tokens actually
*worth* spending plus a `marginal_value_curve`, letting a session-level allocator
redistribute.

**Why it might be better.** Every query today spends the full budget regardless of
whether the evidence justifies it. Under-spending easy queries funds hard ones at
zero net cost. It also produces an honest artifact the product currently lacks: a
per-query statement of *how much context this question was actually worth*.

**Impact MEDIUM-HIGH (cost per session). Novelty UNCOMMON — resource scheduling
applied to context budgets. Difficulty MEDIUM.**

**Risks.** The score-decay signal is uncalibrated and may not correlate with evidence
sufficiency at all; R-3's minimal sufficient contexts are the way to check. Variable
context length across turns hurts B-6's prefix stability — these two ideas are in
direct tension and must be evaluated together, not separately.

**Validation.** Using R-3's minimal sufficient contexts, measure the correlation between
score-decay shape and true required tokens. **Justify if** Spearman > 0.5 — then build
the allocator. **Reject if** < 0.3, and record that fused-score decay does not predict
evidence need.

---

### R-10 The artifact ships its own evaluation

**Current assumption.** Retrieval quality is measured externally, by researchers, in
`benchmarks/`, and users must take the artifact on trust.

**Mechanism.** Embed R-1's self-supervised probe set inside the artifact (queries and
gold block IDs only — a few hundred KB) and make `npk verify` report retrieval health
alongside integrity:

```json
{"ok": true,
 "retrieval_health": {"probes": 4312, "mrr@10": 0.71, "recall@10": 0.83,
                      "probe_source": "docstrings+headings", "computed_utc": "..."}}
```

**Why it might be better.** It changes the product statement from "trust me" to "here
is a number, recomputable offline in seconds, on your corpus." It gives regression
detection for free: a compiler change that quietly hurts retrieval shows up as a
number moving, which is precisely the failure mode Cycle 24's `doc/build` omission
represented — silently erased source that only a hand-built corpus check caught.
And it makes every user's corpus a data point.

**Impact HIGH (product and process). Novelty RESEARCH-LIKE — self-describing artifacts
exist; artifacts that carry a recomputable measurement of their own retrieval quality
do not, as far as I can find. Difficulty MEDIUM, given R-1.**

**Risks.** A single MRR number invites exactly the over-claiming this project has spent
29 cycles retracting. It must be labelled precisely: *self-supervised descriptive
probes, not answer accuracy, not sufficiency*. If R-1's correlation gate fails, this
number is decorative and must not ship.

**Validation.** Gated entirely on R-1's correlation gate. **Justify if** probe MRR moves
in the same direction as the 246-needle retention across >= 7 of 9 known arms.
**Reject if** it does not — ship nothing rather than a misleading number.

---

### R-11 .. R-20 Further beyond-conventional candidates

| # | Idea | Mechanism and why it is non-obvious | Impact / Novelty / Difficulty |
|---|---|---|---|
| R-11 | **Context certificates** | Emit alongside the evidence a machine-checkable claim: *"this context contains all k facts of kind `default` about symbol X present in this corpus."* Checkable by re-querying the artifact. Converts `"sufficiency": "unverified"` into completeness **with respect to a declared fact class** — the only path I see to the project's holy grail that needs no model. Depends on B-4/R-5 | HIGH / HIGHLY EXPERIMENTAL / HIGH |
| R-12 | **Multi-resolution block pyramid** | Store blocks at file / definition / statement-group granularity with parent links; packing chooses the **coarsest level that fits and covers**, like mipmaps or wavelet levels. Distinct from Cycle 15's hierarchical *routing* (which picked documents then passages and failed to generalize): this picks *resolution per selected item* after ranking | MED-HIGH / UNCOMMON / HIGH |
| R-13 | **Declarative retrieval-policy IR plus automated policy search** | One YAML/JSON plan (channels, weights, fusion, expansion, packing) executed by both product and harness; then bandit or evolutionary search over the plan space, scored by R-15's sealed benchmark and R-14's fast evaluator. The project's mission is literally to "search for better variants"; that search is currently a human writing a new Python module per hypothesis (209 so far). This collapses 26,409 LOC of harness into an interpreter plus a plan corpus and makes the search automatic. **Strictly gated on R-14 and R-15 — without a sealed benchmark this is automated overfitting** | EXTREME / RESEARCH-LIKE / HIGH |
| R-14 | **Partial evaluation of the benchmark harness** | Retention is a pure function of (ranked list, cost vector, needle set, budget). For rank-order packing, retention at *every* budget is one prefix-sum; for knapsack/coverage, one DP yields every budget as a byproduct; seed lists memoize by `(query_hash, index_root)`. The matrix collapses from O(questions x policies x budgets) selector calls to O(questions x indexes). Cycle 29's first run had to be **stopped at 292/5,994** for being too slow; the counter fix already bought 34.7x. This is the next order of magnitude, and it multiplies every other idea here | EXTREME / UNCOMMON / MEDIUM |
| R-15 | **Coverage-derived sealed benchmarks from repo test suites** | Run a package's own tests under `coverage`/`settrace`. Each passing assertion yields a question, an execution-verified answer, and a needle set (the executed lines). Hold out **entire repositories**. The project already does this by hand for 15 questions; this scales it to thousands and makes it sealed by construction, dissolving the "inspected development data" caveat that limits every claim in the repository. Pairs with R-3 | EXTREME / UNCOMMON / HIGH |
| R-16 | **Anti-evidence and distractor priors** | The selector only adds. Some blocks are actively harmful: deprecated variants, test fixtures with wrong values, vendored copies, example code. `conflict.py` gestures at this and abstains. Learn a distractor prior from corpus structure (`test/`, `examples/`, `vendor/`, `_legacy/`, docstring `>>>` blocks) and validate it against R-1's probes rather than guessing weights | MED / UNCOMMON / MED |
| R-17 | **Table of contents in the prompt** | Spend ~300 of 2,048 tokens on a symbol -> `path:lines` index of the *whole corpus region* and 1,700 on evidence. Converts an unknown-unknown into a known-unknown: the model can say "I need `Traceback.from_exception`" instead of hallucinating. Zero-LLM to produce; pairs with D-10 and D-3. Cheap to test and nobody has | MED-HIGH / UNCOMMON / LOW |
| R-18 | **Speculative parallel channels with bound-based early exit** | Run channels concurrently; as soon as the fused top-K is provably stable under remaining score bounds, cancel the rest. Block-max-WAND reasoning lifted from within a channel to *across* channels. Only worth it once there are 4+ channels (A-1, A-4, B-3, B-4) | MED / UNCOMMON / MED |
| R-19 | **Corpus-conditioned stopwords and term policy** | `STOPWORDS` is a hand-written 60-word English list, and `CODE_WORDS` is a hand-written exception list to it. Both are guesses that Cycle 28 had to patch with a backtick special case. Replace with corpus-derived term utility: a term's value is its IDF *in this corpus* relative to a background corpus. Removes two magic lists and generalizes to non-English corpora, where the current list is simply wrong | MED / COMMON / LOW |
| R-20 | **Answerability sketches: invert on evidence type, not on words** | For each block precompute a sketch of *what kinds of question it can answer* — distinctive identifiers, relation kinds it participates in, literal values it defines, executed-line signature from R-15. Retrieve by matching question *shape* to block *capability* rather than by term overlap. The natural limit of B-4/R-5 and what CRISP's structural channel gestures at without naming | MED-HIGH / HIGHLY EXPERIMENTAL / HIGH |

---

## 8. TIER D — FUNDAMENTAL REDESIGN

Each of these changes what the system *is*. None should be attempted before the
cheap experiment that would kill it.

### D-1 The unit of evidence is a program fact, not a text block

- **Assumption challenged.** The atom is a contiguous span of source text and
  retrieval is document retrieval.
- **Mechanism.** Compile the repository into a fact table, not a block table:
  `fact(id, kind, subject, value, span_ref, confidence)` with
  `kind` in {defines, signature, default, raises, catches, returns, reads_config,
  calls, decorated_by, documents, asserts}. Blocks become a *rendering* of facts
  back to source spans for provenance. Retrieval ranks facts — small, structured,
  exactly matchable. Packing selects facts and materializes the minimal spans that
  carry them.
- **Why better.** Every strong signal the project has measured is a fact, not a bag of
  words: `name` (+38%), `path`, `raises` (+19). Every weak signal is lexical. The
  `assignments` / `conflict.py` machinery is a degenerate one-kind fact table (9 rows
  on a real corpus) that already proves the shape. Facts make budgets meaningful — you
  can answer "what is the default timeout" in 12 tokens instead of 400 — and they make
  sufficiency *checkable*: a question of kind `default` needs a fact of kind `default`,
  which is a testable predicate, something "did the needle survive packing" can never be.
- **Impact EXTREME. Novelty HIGHLY EXPERIMENTAL here; adjacent to code property graphs
  and semantic code search. Difficulty EXTREME.**
- **Risks.** Fact extraction is language-specific and unbounded in scope — the classic
  structured-IR trap where the schema never covers the next question. Facts lose context
  the model needs. Must be **additive**: facts as an extra channel and rendering, with
  full source blocks always available. Do B-4 first; D-1 is justified only if B-4's
  typed relations show a broad win.
- **Cheap killer experiment.** Take the 15 executable behavior questions, hand-classify
  each into a fact kind, and ask: can a fact-only context of <= 200 tokens answer them
  at the same rate as a 2,048-token block context? **Justify if** >= 10/15 at 10x less
  budget. **Reject if** < 6/15 — source text then carries something facts do not.

### D-2 Columnar, memory-mapped read path; SQLite for metadata only

- **Assumption challenged.** SQLite row storage is right for both the write path and
  the read path. ADR 0004 already concedes this is "an engineering choice, not proof."
- **Mechanism.** Two stores. `pack.db` holds metadata, manifest, integrity and FTS.
  A contiguous, dictionary-compressed arena holds block text, and a fixed-stride matrix
  holds vectors; both `mmap`ed. `blocks` rows carry `(offset, length)`. Evidence
  assembly becomes pointer arithmetic; the dense scan becomes one `np.memmap` matmul
  with **no per-query copy at all**.
- **Why better.** Measured: the dense channel does `b"".join(r["vector"] for r in rows)`
  on every query — 5.4 MB copied per query at 3,513 blocks, ~1.5 GB at 1M blocks — and
  the SQL producing those rows joins `files` and sorts the entire corpus purely for tie
  determinism. `mmap` plus fixed stride makes both free and lets the OS page cache do
  the work. This is the standard columnar transition (Arrow, Parquet, Lucene `.fdt`) and
  this workload — write-rarely, read-many, scan-heavy — is its target.
- **Impact HIGH at scale, LOW below ~100K blocks. Novelty COMMON generally, UNCOMMON
  here. Difficulty HIGH.**
- **Risks.** Two files break the single-portable-artifact property, which is a real
  product value — unless the arena is an embedded BLOB opened with `sqlite3_blob_open`
  (possible, awkward from Python). Atomic update across two files reintroduces exactly
  the failure-atomicity problem `compile_pack` solved with a rename.
- **Do not build before measuring.** Cycle 11's warm query median is 0.68-0.99 ms at
  250K tokens. **Try A-8 (`mmap_size`, persistent connection) first** — it may close
  most of the gap for one afternoon of work. Prototype at 10x and 100x the current
  largest corpus. **Justify if** dense latency drops >= 5x at 100K blocks with flat RSS.
  **Reject if** A-8 alone already closes it.

### D-3 .. D-10 Further fundamental directions

| # | Idea | Assumption challenged and mechanism | Impact / Novelty / Difficulty |
|---|---|---|---|
| D-3 | **Compile the query plan, not just the corpus** | *The selector is a fixed interpreted pipeline.* Generate a specialized query program per artifact from its own statistics: inline the term dictionary, specialize the packer to the artifact's block-size distribution, freeze channel weights chosen at compile time from R-1's probes. Partial evaluation of the retriever with respect to the corpus. Natural successor to R-13: the searched plan becomes generated code stored inside the artifact | MED-HIGH / RESEARCH-LIKE / HIGH |
| D-4 | **Rate-distortion formulation of context selection** | *"Fit the most relevant text in B tokens" is the objective.* It is not; the objective is minimizing answer distortion at a rate constraint. With R-3 supplying an executable distortion oracle, selection becomes a measurable R(D) curve per question class, and "how many tokens does this question need" becomes an empirical quantity instead of a caller's guess. `research/math/rate_distortion.md` is a 30-line stub; this makes it load-bearing | HIGH / RESEARCH-LIKE / EXTREME |
| D-5 | **LSM-structured pack: immutable base plus append-only deltas** | *An artifact is a single mutable DB updated in place.* Base pack plus ordered delta segments, merged at read, compacted in background. Updates become O(delta) **by construction** rather than by careful engineering, deltas become shippable over a network, and readers never block writers. A-5 treats the symptom; R-2 fixes the digest; **D-5 removes the disease** | HIGH / COMMON (LSM) / HIGH |
| D-6 | **Global statistics across all of a user's packs** | *Each pack is an isolated corpus.* BM25 IDF computed within one repo makes repo-specific vocabulary look rare and generic vocabulary look common — backwards for cross-repo questions. Share mergeable `df` sketches across packs; a term rare *in the world* but common *in this repo* is the most informative signal available, and today it is invisible | MED-HIGH / UNCOMMON / HIGH |
| D-7 | **Reframe the product as a prefix-stable context compiler** | *The pivot away from KV reuse killed "compile once, reuse forever."* It did not; it moved it to the token layer. The differentiator becomes: *across a session your prompts share maximal byte-identical prefixes, your provider's cache hits, and we show you the `cached_tokens` to prove it.* That is a claim verifiable with provider-reported numbers, unlike every retrieval-quality claim the project has had to retract. B-6 is the experiment; D-7 is the product | HIGH / UNCOMMON / MED |
| D-8 | **Self-hosting as a live evaluation signal** | *Evaluation needs an external corpus.* Compile NeuralPack's own evolution log, 38 research notes and 6,482 LOC into a pack and require every future research agent to use it. "Has this idea been falsified before?" becomes a retrieval query with a known answer — a continuously running benchmark whose failures are felt immediately by the researcher who caused them. Cheapest item in this table | MED / UNCOMMON / LOW |
| D-9 | **Workspace index, not repository index** | *One artifact = one source root.* Real questions span application + dependency + docs + changelog. With D-6's federated statistics and per-source-type field schemas, the pack indexes a *workspace*. Note that the project's own strongest benchmark corpus is already three packages pretending to be one root | HIGH (product) / COMMON / HIGH |
| D-10 | **Agentic retrieval as an explicitly separate mode** | *Zero generative calls is a property of the whole system.* It is a property of the *default fast path*. An opt-in mode that lets the target read spans and refine under the same total budget would recover most of the 36-block packing loss, since the pool holds the needle 241/246 times. It must be a distinct mode, with `used_generative_llm = True`, its own claims, and its own evidence. Pairs with R-17, and with exposing the pack as an MCP/tool surface so agents query spans instead of receiving a pre-packed blob | HIGH (product) / COMMON externally, prohibited-by-default here / MED |

---

## 9. WHERE THESE IDEAS CAME FROM (so a future agent can generate more)

The project's search has been deep but narrow: nine cycles of variations on
*"what is a better seed ranking?"*. Every idea above came from asking a different
question. Reuse the method.

| Field borrowed from | Question it asks | Ideas it produced |
|---|---|---|
| Compiler backends | What is derivable and therefore need not be stored or hashed? | A-3, A-5, A-6 |
| Compiler backends | What can be specialized at compile time against a known cost model? | R-4, D-3 |
| Incremental cryptography | Can the digest be a group homomorphism instead of a tree? | R-2 |
| Delta debugging / test reduction | Is there a *checkable predicate* for sufficiency? | R-3, D-4 |
| Datalog / static analysis | Can the derivation chain *be* the evidence set? | R-5, R-11 |
| Mining software repositories | What signal is in the history that is not in the bytes? | R-6 |
| Build systems / incremental computation | Why compile what nobody asks about? | R-7, D-5 |
| CPU architecture | Is the workload predictable enough to speculate on? | R-8, R-18 |
| OS scheduling / DVFS | Is the resource per-request or per-session? | R-9, B-6 |
| Self-supervised learning | Where are the free labels? | R-1, R-10, R-15 |
| Submodular optimization | Is this a coverage problem wearing a ranking costume? | B-2 |
| Classical IR (pre-neural) | What did people do before embeddings? | B-3, B-9, B-13, R-19 |
| Databases | Where is the query planner and the statistics it needs? | B-9, D-6, D-9 |
| Columnar analytics | Where is the per-query copy that should be a pointer? | D-2 |
| Provider economics | What does the customer actually pay for? | B-6, D-7 |

**Three questions that generated the highest-value ideas here, worth re-asking every cycle:**

1. *What does this system already compute and then discard?* (Fused score decay -> R-9.
   Docstrings -> R-1. Execution traces -> R-3. Git history -> R-6.)
2. *What is being recomputed that could be maintained?* (Digest -> R-2.
   `available_tokens` -> A-6. Token counts -> the existing count index.)
3. *Which claim would a customer pay for, and can it be measured directly?*
   (Cached tokens -> B-6/D-7. Everything else is currently unmeasurable.)

---

## 10. ANTI-RECOMMENDATIONS — DO NOT DO THESE

A review that only adds is worth less than one that also subtracts. Each of these is
attractive and is already refuted by this project's own measurements.

| # | Tempting idea | Why not |
|---|---|---|
| X-1 | **Custom postings format / block-max WAND replacing FTS5** | Warm query median is 0.68-0.99 ms at 250K tokens. Retrieval *latency* is not a bottleneck; retrieval *quality* is. FTS5 is a mature BM25 with column weighting already available. This would consume a quarter and improve nothing measurable |
| X-2 | **A custom binary container replacing SQLite** | ADR 0004 already reached this conclusion honestly. Transactions, crash atomicity and FTS5 are the product's real assets. Revisit only as D-2's *supplementary* mmap arena, never as a replacement |
| X-3 | **Reviving cross-model KV transfer** | `research/unsolved-problems.md` U01-U08 is the most rigorous document in the repository and it settles this. Do not reopen without new hardware or a new architecture family |
| X-4 | **More dependency-graph expansion tuning** | `Closure_D(empty) = empty` is proved, and `_build_deps` resolves a reference to *any* same-named definition repo-wide, which on real code is near-total noise. Either make resolution scope-aware — which is R-5, a different and better idea — or delete the table. Do not tune it |
| X-5 | **Larger candidate pools** | Measured directly: 60 -> 160 candidates raises pool coverage 198 -> 215 and yields **zero** selected-hit improvement. The pool is not the constraint. Stop widening it |
| X-6 | **Anything that removes source text to save tokens** | Cycle 29 falsified this twice with permanent fixtures (a docstring is runtime data; a compacted noise block can crowd out the needle). R-4 is the *only* acceptable form: strictly semantics-preserving, information-preserving rendering |
| X-7 | **A new embedding model before fixing truncation** | Cycle 14 tried a newer dense encoder and it "did not earn its cost"; Qwen3-Embedding-0.6B took 127 s to index. Section 3.6 shows the index has been truncating a quarter of every corpus the whole time. Fix the window (A-10/B-8) before concluding anything about any encoder |
| X-8 | **Calibrating the risk band into a probability** | The project removed invented probabilities once already and the removal was correct. A risk band cannot become calibrated without a labelled sufficiency oracle. Build R-3 first; only then is calibration even meaningful |
| X-9 | **Adding more benchmark modules to `benchmarks/`** | 209 modules and 26,409 LOC is already 4x the product. The next experiment should *reduce* that number via R-13/R-14, not add to it. A new one-off script is a signal that the harness needs an abstraction, not another file |
| X-10 | **Shipping BM25F field weights tuned on the 246 annotations** | Those are inspected development data. Ship `1,1,1` (which already ties `names4`) and let R-1 tune per corpus, or hold out repositories. Tuning on the benchmark you report is how the pre-audit claims got made |

---

## 11. RANKED RESEARCH BACKLOG

Ranked by impact x probability of success / implementation cost. Each entry gives the
seven fields this project's process requires.

---

### RANK 1 — R-14: Partial-evaluate the benchmark harness

1. **Investigate.** Whether the experiment matrix can be computed as prefix-sums and
   DP over one candidate list per (question, index) instead of one selector invocation
   per cell. Cycle 29's first run was **stopped at 292/5,994** for being too slow; the
   prepared-counter fix already bought 34.7x. This is the next order of magnitude.
2. **Files.** `benchmarks/packing_eval.py`, `packing_challengers.py`, `pareto_eval.py`,
   `compiled_count_index.py`, `compact_boundary_tokenizer.py`,
   `npk/pack/select.py::_select_once`.
3. **Hypothesis.** All budgets x all rank-order packing policies are derivable from one
   ranked list plus one cost vector, giving >= 20x wall-clock with bit-identical outputs.
4. **Prototype.** A vectorized evaluator plus a 1% sampled cross-check that runs the
   real `PackSelector` and asserts byte-identical context strings.
5. **Benchmark.** Re-derive the archived `cycle28-packing-v1` (8,658 selections) and
   `cycle29-source-views-v2` (5,994). Compare every record hash and total wall-clock.
6. **Justify if.** 100% of cells match archived records and wall-clock drops >= 20x.
7. **Reject if.** Any cell disagrees. A fast harness that silently diverges is worse
   than a slow one; this repository's history is a catalogue of exactly that failure.

---

### RANK 2 — A-1 + A-2: Multi-field BM25 with structural names for every language

1. **Investigate.** Why the largest measured retrieval win in the project's history
   (148 -> 205 / 246) has sat in `benchmarks/` for two cycles, and why it is
   structurally unavailable on non-Python corpora (`name IS NULL` for 100% of the
   SQLAlchemy pack).
2. **Files.** `npk/pack/format.py` (SCHEMA, `PACK_FORMAT_VERSION` -> 6),
   `npk/pack/compile.py` (`_split_markdown`, `_split_python`, `split_source`,
   `_write_file_blocks`, `TEXT_SUFFIXES`), `npk/pack/select.py` (`_lexical_channel`,
   `_lexical_terms`), `benchmarks/seed_metadata.py` (`analyzed`, `field_rank`, SCHEMA),
   `npk/pack/integrity.py` (`GLOBAL_TABLES`).
3. **Hypothesis.** Indexing `(body, name, path)` as separate FTS5 columns raises
   2,048-token retention from 148 to >= 200 / 246 in the *product* selector; and an
   RST/heading-aware plus brace-language splitter reduces `name IS NULL` from 100% to
   < 15% on the SQLAlchemy corpus, transferring that gain to documentation.
4. **Prototype.** v6 schema with a multi-column `lexical` table and file-scoped
   incremental invalidation, plus A-2 tiers 1-2. In the product path, not a sidecar.
5. **Benchmark.** Frozen `cycle28-seed-metadata-v1` at 512/2,048/8,192 through
   `PackSelector`, asserting parity with `field_rank`; then Cycle 24's 10 SQLite
   scenarios and Cycle 26's 202 tasks on the recompiled RST corpus; plus a
   compile -> mutate -> update -> fresh-compile differential over 100 mutations.
6. **Justify if.** >= 200/246 at 2,048 in-product, **and** no regression on the 15
   executable behavior questions, **and** update latency within 1.3x of current.
7. **Reject if.** In-product retention lands below 185 (the sidecar advantage would
   then be an artifact of the sidecar's own analyzer, not the fields), **or** any
   differential update diverges from a fresh compile.

---

### RANK 3 — R-1: Corpus-resident self-supervision (correlation gate first)

1. **Investigate.** Whether docstrings, headings and test names constitute a usable
   per-corpus retrieval benchmark and auto-tuner — the largest unexploited resource in
   the project, currently discarded at compile time.
2. **Files.** `npk/pack/compile.py::_split_python` (AST already available),
   `benchmarks/seed_metadata.py` (scoring), `benchmarks/repository_tasks.py` (task
   shape to imitate), `npk/pack/format.py` (where probes would be stored for R-10).
3. **Hypothesis.** Probe MRR@10 over docstring/heading probes rank-orders retrieval
   arms the same way the 246 hand-annotated needles do; if so, field weights and
   packing parameters can be fitted per corpus at compile time.
4. **Prototype.** A probe generator plus a scoring pass that excludes each gold block's
   own docstring from its scored body. **No tuning yet.**
5. **Benchmark.** Generate probes for rich + Jinja2 + Werkzeug. Score all nine existing
   `cycle28-seed-metadata-v1` arms by probe MRR and by 246-needle retention, and
   compute Spearman correlation across arms.
6. **Justify if.** Spearman >= 0.7. Then, and only then, fit field weights on probes and
   evaluate on the 246 annotations plus the 15 behavior questions; promote only if
   fitted weights beat `1,1,1`.
7. **Reject if.** Spearman < 0.4. The probes would then measure something orthogonal to
   what matters, and no amount of tuning fixes that. Record the negative — "docstring
   probes do not predict code-behavior retrieval" is worth knowing and nobody has checked.

---

### RANK 4 — B-3: Pseudo-relevance feedback

1. **Investigate.** Whether classic RM3/Rocchio expansion closes the 241-pool /
   205-selected gap at ~2 ms and zero models. Absent from 38 research notes and 209
   benchmark modules.
2. **Files.** `npk/pack/select.py` (`_lexical_terms`, `_lexical_channel`),
   `npk/context/info_gain.py` (`content_terms`, `STOPWORDS`), `benchmarks/seed_metadata.py`.
3. **Hypothesis.** Expanding with top-IDF terms from the top-10 BM25 results, fused with
   the unexpanded ranking, gains >= 8 annotations at 2,048 over `fields` alone.
4. **Prototype.** A pure function `expand(con, query, seeds) -> extra_terms` plus an
   extra fused channel. Guard: expand only when top-1 BM25 clears a floor; never replace
   the unexpanded ranking.
5. **Benchmark.** Arms `body160+rm3` and `fields+rm3` at all three caps on the 246
   annotations plus 15 behavior questions. Tune `(k, n_terms)` on the 15 behavior
   questions only; apply one setting to the 207.
6. **Justify if.** `fields+rm3` >= `fields` + 8 at 2,048 with no behavior-question loss.
7. **Reject if.** Query drift costs >= 2 behavior questions, or the gain falls inside
   the paired bootstrap interval.

---

### RANK 5 — R-3: Verified context minimization via delta debugging

1. **Investigate.** Whether sufficiency — the project's deepest unsolved problem — is
   *decidable* for the executable question class it already benchmarks.
2. **Files.** `benchmarks/repository_tasks.py`, `sqlalchemy_oracles.py`,
   `library_behavior_oracles.py`, `complete_program_controls.py`,
   `benchmarks/source_views.py` (span machinery), `experiments/oracle-envs/`.
3. **Hypothesis.** For executable questions, ddmin over candidate blocks under the
   predicate "context still contains every executed line" yields a 1-minimal
   verified-sufficient context, and its median token cost is well under the 2,048 budget.
4. **Prototype.** Trace capture (already done manually for 15 questions) plus a ddmin
   loop over blocks with the containment predicate. Filter frames to the package under test.
5. **Benchmark.** The 15 existing behavior questions. Report minimal token cost per
   question, and the ratio of minimal cost to the budget actually spent.
6. **Justify if.** Minimal sufficient contexts found for >= 12/15 with median cost < 40%
   of the 2,048 budget — that proves the budget is not the binding constraint and
   redirects the program toward allocation.
7. **Reject if.** Minimal contexts routinely exceed the budget — then the product needs
   larger budgets or D-10 iterative retrieval, which is itself decisive.

---

### RANK 6 — B-6 / D-7: Prefix-stable evidence emission

1. **Investigate.** Whether emitting evidence in canonical corpus order (free) materially
   raises provider prompt-cache hit rates across a realistic agent session, and whether
   it costs answer quality.
2. **Files.** `npk/pack/select.py::Selection.context_text` and `_select_once` emission
   order; `npk/providers/base.py::UsageInfo.cached_tokens`;
   `npk/auditor.py::_require_usage`; `benchmarks/repository_eval.py`.
3. **Hypothesis.** Canonical-order (and sticky) emission raises the provider-reported
   cached-token share by >= 25 points over a 20-turn session with no drop in executable
   oracle pass rate.
4. **Prototype.** An `order` parameter (`relevance` | `canonical`) on `context_text()`,
   plus an optional caller-supplied `previous_block_ids` for sticky tie-breaking.
   No implicit state.
5. **Benchmark.** (i) Offline: replay the 246-annotation matrix with canonical ordering;
   selected *sets* are unchanged by construction, so only hashes need comparing.
   (ii) Live: a scripted 20-turn urllib3 session through `repository_eval --live`,
   three arms, reporting `cached_tokens` and oracle pass rates.
6. **Justify if.** Cached-token share rises >= 25 points **and** oracle pass rate is unchanged.
7. **Reject if.** Oracle pass rate falls at all. Position effects are real, and a cheaper
   wrong answer is the failure this project spent 29 cycles eliminating.

---

### RANK 7 — B-4: Generalize typed structural relations

1. **Investigate.** Whether CRISP's +19-annotation `raises` advantage generalizes across
   ten relation kinds, or is an artifact of exception-flavoured questions.
2. **Files.** `benchmarks/seed_metadata.py::raise_sites` (extraction template),
   `npk/pack/compile.py::_split_python`, `npk/pack/format.py` (new `relations` table),
   `npk/pack/select.py` (new channel), `npk/pack/conflict.py::extract_assignments`
   (the existing degenerate one-kind case).
3. **Hypothesis.** `raises, catches, warns, decorated_by, defaults, returns_literal,
   reads_config, calls, yields, documents` as a typed seed channel closes >= half the
   residual `fields`(205) -> `crisp_shared_raises`(225) gap at 2,048.
4. **Prototype.** AST relation extraction at compile plus a fixed, declared
   query -> relation pattern table. No learning. Relations are seeds, never proof.
5. **Benchmark.** Pool coverage per relation kind over the 246 annotations; then a
   `fields+relations` arm at all caps; then the 15 behavior questions.
6. **Justify if.** >= 215/246 at 2,048 with gains distributed across >= 3 relation kinds.
7. **Reject if.** Gains are confined to exception questions — publish that as a negative
   establishing that CRISP's lead is dataset-shaped, which is itself a real finding.

---

### RANK 8 — A-3 + A-4 + A-5: Artifact diet and truly incremental integrity

1. **Investigate.** The measured 6.5-7.2x storage amplification, the byte-identical
   duplication of every block's text, the 99%-noise symbols table, and the
   O(N)-per-update global digest.
2. **Files.** `npk/pack/format.py` (SCHEMA, `verify`), `npk/pack/integrity.py`
   (`GLOBAL_TABLES`, `root_from_leaves`), `npk/pack/compile.py` (`_extract_symbols`,
   `_write_file_blocks`, `_drop_file`, `_available_tokens`).
3. **Hypothesis.** External-content FTS5, definition-only symbols and dropping
   `lexical_content` from the global digest cut artifact bytes >= 40% and the non-scan
   portion of a one-file update >= 30%, with **zero** change to any selection and no
   loss of corruption detection.
4. **Prototype.** v6 schema; deletes supplied from `blocks` before drop;
   `INSERT INTO lexical(lexical) VALUES('integrity-check')` added to `verify`;
   `available_tokens` maintained by trigger.
5. **Benchmark.** Cycle 21's 138-file / 590K-token corpus at 1, 2, 14 and 100 changed
   files, before and after, stage-instrumented. Every corruption fixture in
   `tests/test_pack_integrity.py` and `benchmarks/integrity_challengers.py`.
   1,000-query ranking equality.
6. **Justify if.** >= 40% bytes saved, >= 30% one-file-update improvement, all rankings
   identical, all corruption fixtures still detected.
7. **Reject if.** Any corruption fixture stops being detected, or external-content FTS5
   diverges from `blocks` under randomized mutate/update stress.

---

### RANK 9 — B-2: Submodular coverage packing

1. **Investigate.** Whether a coverage objective recovers the documented
   `B-b8c5ec3852` crowding failure that rank-order packing and grouping both lose.
2. **Files.** `npk/pack/select.py::_select_once` (admission loop),
   `benchmarks/packing_challengers.py` (reuse the existing AST adapter),
   `npk/pack/select.py::_risk` (`query_term_coverage` is already the metric).
3. **Hypothesis.** `alpha * relevance + (1 - alpha) * coverage` under cost-effective
   lazy greedy recovers `B-b8c5ec3852` and improves aggregate retention at 2,048.
4. **Prototype.** Lazy greedy over query-term and identifier-component atoms, plugged
   into the existing challenger adapter so the public exact-admission check stays
   authoritative.
5. **Benchmark.** Methods 15-17 (`alpha` in {0, 0.5, 1}) on the frozen 8,658-selection
   matrix, via RANK 1's fast evaluator.
6. **Justify if.** `B-b8c5ec3852` recovered **and** aggregate retention improves at >= 2 caps.
7. **Reject if.** It trades the counterexample for net losses elsewhere — the same trade
   Cycle 29 correctly refused.

---

### RANK 10 — A-10 + B-8: Repair the dense channel before writing it off

1. **Investigate.** Whether nine cycles of negative hybrid results were measuring a
   truncation defect rather than the limits of dense retrieval.
2. **Files.** `npk/context/embedding.py` (`max_length=256`, `DOCUMENT_CHAR_LIMIT=2000`,
   `_embed_locked` pooling), `npk/pack/compile.py::_embed_blocks`,
   `npk/pack/select.py::_embedding_channel`,
   `npk/pack/format.py::validate_encoder_identity` (the identity contract must version
   any pooling change).
3. **Hypothesis.** Windowed encoding with max-pooling raises hybrid retention above the
   lexical champion at >= 1 cap; the measured 25.4% truncation with median 61% coverage
   caused the prior negatives.
4. **Prototype.** Multi-vector `embeddings(block_id, window_ordinal, dim, vector)`;
   block score = max over windows; `pooling` bumped to `mask_mean_l2_window_max_v1`.
5. **Benchmark.** Four arms — 256 (control), 512, windowed-max, windowed-max plus
   binary-quantized rerank — on the 246 annotations and 15 behavior questions.
   Record encoding time and artifact bytes.
6. **Justify if.** Windowed-max beats the lexical champion at any cap.
7. **Reject if.** It does not — then **record it as settled**: dense retrieval refuted
   *after* the truncation defect was repaired. That retires a question the project has
   been paying for since Cycle 2.

---

### RANK 11 — R-2: Incremental multiset hashing

1. **Investigate.** Whether artifact integrity can be made O(1) per row instead of
   O(N) per update, using LtHash or MSet-XOR-Hash.
2. **Files.** `npk/pack/integrity.py` (entire module: `framed`, `_feed_rows`, `_rows`,
   `file_digest`, `root_from_leaves`, `tracking_statements`),
   `npk/pack/format.py::compute_root_digest`, ADR 0005.
3. **Hypothesis.** A group-homomorphic multiset hash maintained by the existing triggers
   makes the digest term of update cost independent of corpus size, with zero loss of
   corruption detection under a multiset-semantics argument.
4. **Prototype.** LtHash over the existing `framed()` encoding; triggers accumulate the
   group delta instead of dirty file IDs; `verify --full` recomputes from scratch.
5. **Benchmark.** Fuzz harness: 10,000 random compile/update/delete sequences, asserting
   incremental root equals recomputed root after every operation. Then stage-instrumented
   updates at 1x, 4x and 16x corpus size.
6. **Justify if.** Zero fuzz divergences **and** the digest term becomes flat in corpus size.
7. **Reject if.** Any divergence, or the constant factor makes small updates slower.

---

### RANK 12 — R-15: Coverage-derived sealed benchmarks

1. **Investigate.** Whether ground truth can be manufactured from repositories' own test
   suites, ending the "inspected development data" caveat present in every cycle report.
2. **Files.** `benchmarks/repository_tasks.py`, `repository_eval.py`, `stdlib_tasks.py`,
   `sqlalchemy_oracles.py`, `library_behavior_oracles.py`, `experiments/oracle-envs/`.
3. **Hypothesis.** Test assertion -> question, execution trace -> needle set, and
   repo-level holdout produce a benchmark that reproduces the known relative ordering of
   arms on urllib3 and scales to hundreds of repositories.
4. **Prototype.** Containerized harness: install package -> run tests under `settrace` ->
   emit (question, verified answer, needle lines) -> filter to assertions touching <= 5
   package functions -> paraphrase away the identifier.
5. **Benchmark.** urllib3 2.7.0 first, against the 15 existing hand-built questions.
   Then 20 packages with 5 held out entirely.
6. **Justify if.** Auto-questions reproduce the known arm ordering on the overlap **and**
   the no-context control passes < 40%.
7. **Reject if.** The no-context control passes > 60% — the generator is producing
   parametric-knowledge questions and the needles are decorative.

---

### RANK 13-20 — compact entries

| Rank | Item | Investigate / hypothesis | Justify if | Reject if |
|---|---|---|---|---|
| 13 | **A-7 security parity** | Why the live v2 path opening third-party `.npk` files has none of the hardening the dead v1 path has. Adding it costs < 2% latency | All hostile-artifact fixtures fail closed, latency regression < 2% | The progress handler causes spurious interrupts on large legitimate corpora (then adopt the pragmas without it) |
| 14 | **A-12 + A-13 delete Product B** | The product path depends on the legacy tree only through `content_terms`. Moving Product B to `legacy/` cuts ~2,500 LOC and removes the module/function shadowing footgun | All 1,150 tests pass, 147 mutants stay killed, `npk.pack` imports nothing outside `npk.pack` | Any archived experiment can no longer be replayed — reproducibility outranks tidiness |
| 15 | **R-13 policy IR + search** *(gated on RANK 1 + RANK 12)* | Whether the design space can be searched automatically rather than one benchmark module per hypothesis | A searched plan beats the hand-designed champion on **held-out repositories** by more than the holdout interval, and the plan is human-legible | Train/holdout gap exceeds 2x the interval width — publish that as a measurement of how badly this space overfits |
| 16 | **R-5 Datalog fact resolution** | Whether the indirection chain `conflict.py` refuses to guess can be *derived*, with the derivation tree as the evidence set | Complete correct chains for >= 20/30 hand-collected multi-hop questions with **zero** incorrect resolutions | Any incorrect resolution without abstention. A wrong config value stated confidently is worse than a miss |
| 17 | **R-4 token-cost-aware rendering** | How many tokens indentation and blank runs actually cost under the pinned tokenizer. Measure before building | Median savings >= 6% with zero semantic-fixture failures | < 3% savings, or any equivalence fixture fails |
| 18 | **R-17 table of contents in the prompt** | Whether spending ~300 of 2,048 tokens on a symbol -> `path:lines` index improves answers by converting unknown-unknowns into known-unknowns | Oracle pass rate improves at the same total budget | Pass rate drops — the 300 tokens were better spent on evidence |
| 19 | **R-6 structure from revision history** | Whether co-change correlation gives usable language-agnostic boundaries and a churn ranking prior; `.git` is currently in `EXCLUDED_DIRS` | Co-change or churn wins at >= 2 caps on any language family | Neither beats A-2 anywhere — record "history does not help code retrieval" as a negative |
| 20 | **D-8 self-hosting** | Compile the repo's own log, notes and source into a pack and require research agents to query it. Cheapest item in the whole document | The pack answers "has this been falsified before?" for >= 8/10 hand-written probes | It does not — which is itself a retrieval indictment worth recording |

---

## 12. SEQUENCING — WHAT UNBLOCKS WHAT

```
                    RANK 1  R-14 fast evaluator  ──────────┐
                       │                                    │
                       ├──────> RANK 9  B-2 coverage packing │
                       ├──────> RANK 7  B-4 relations        │
                       └──────> RANK 15 R-13 policy search <─┤
                                                             │
RANK 2  A-1+A-2 fields + names ──┬──> RANK 7  B-4 relations  │
                                 ├──> RANK 4  B-3 PRF        │
                                 └──> RANK 3  R-1 probes ────┤
                                            │                │
                                            ├──> R-10 self-evaluating artifact
                                            └──> R-13 tuning targets
                                                             │
RANK 12 R-15 sealed benchmarks ──────────────────────────────┘  (gates R-13)
   │
   └──> RANK 5  R-3 verified minimization ──> D-4 rate-distortion
                                          └──> calibration (X-8 becomes possible)

RANK 8  A-3+A-4+A-5 artifact diet ──> RANK 11 R-2 multiset hash ──> D-5 LSM ──> R-7 lazy compile

RANK 6  B-6 prefix-stable ──> D-7 product reframing        (independent, ship early)
RANK 10 A-10+B-8 encoder repair                            (independent, settles a 9-cycle question)
RANK 13 A-7 security                                        (independent, do it this week)
```

**Three rules for the next agent.**

1. **RANK 1 first, even though it improves no headline metric.** It changes the cost
   denominator of every subsequent experiment. RANK 2 can proceed in parallel because
   it is pure engineering with a pre-measured payoff.
2. **RANK 12 gates every strong *claim*.** Without it, RANKs 3-11 can produce
   improvements but not evidence. This project has spent 29 cycles learning that
   difference the expensive way.
3. **Never promote on inspected development data.** Every ranking above is written so
   that a promotion gate uses either a held-out repository, an executable oracle, or a
   byte-identical differential. If an experiment cannot be gated that way, run it as a
   diagnostic and say so in the log — exactly as the existing cycles do.

**Suggested first cycle (cycle 30).** RANK 13 (one day) + RANK 1 (one week) +
RANK 2 (one week, parallel) + RANK 3's correlation gate only (two days, kills or
unlocks the single highest-ceiling idea in this document for almost no cost).
That is a cycle whose *worst* outcome is a 20x faster harness, a shipped +38%
retrieval feature, a hardened reader, and a decisive answer about self-supervision.

---

## 13. OPEN QUESTIONS I COULD NOT RESOLVE

Recorded honestly rather than papered over. Each is cheap to settle.

1. **RST block-kind anomaly.** The stored pack
   `experiments/runs/packs/cycle26-index-updates-v1/unchanged/0/project.npk` contains
   1,141 blocks all of `kind='chunk'` with `~2,048` chars each — the signature of
   `_split_lines(window=60)`. But running the *current* `split_source(text, "rst")` on
   the same source file yields 27 blocks of `kind='section'`, and `npk/pack/compile.py`
   hashes identically to the code recorded in that run's `results.json`. Either the base
   pack predates the run that used it, or a benchmark harness compiled it by another
   path. **The `name IS NULL` finding (3.7) is unaffected and independently reproduced
   from current code** — but the kind discrepancy should be explained before anyone
   trusts stored packs as evidence of current compiler behaviour. Ten minutes with
   `experiments/runs/packs/cycle26-index-updates-v1/execution-sources.json` should settle it.
2. **Stray WAL sidecars.** `experiments/runs/packs/self.npk-wal` and `self.npk-shm`
   exist, while the README states that ordinary reads leave no WAL sidecars and
   `compile_pack` refuses to publish over active sidecars. Probably a leftover from an
   interrupted run, but it contradicts a documented property and should be explained.
3. **Where the remaining ~164 ms of a one-file update goes.** Cycle 21 measured 227.64 ms
   with scanning at 28%. My measurements account for roughly 16 ms
   (`root_from_leaves` 11.6 + `_available_tokens` 4.4) on a comparable corpus. The
   remainder is presumably FTS5 delete/insert plus `journal_mode=DELETE` fsync behaviour
   on Windows — but it is unmeasured, and it is the single largest unexplained cost in
   the product. **Stage-instrument it before optimizing anything in RANK 8.**
4. **Whether `blocks_sha` duplicate share justifies B-7.** One query over every pack in
   `experiments/runs/packs/` answers it: `SELECT COUNT(*), COUNT(DISTINCT sha256) FROM blocks`.
   I did not run it across all packs.
5. **Whether the 32% embedding-storage overhead is b-tree page slack or blob framing.**
   `dbstat` is not compiled into this SQLite build, so the breakdown is inferred rather
   than measured. Rebuild SQLite with `SQLITE_ENABLE_DBSTAT_VTAB` or use
   `sqlite3_analyzer` to settle it.

---

## 14. MAINTAINING THIS FILE

- Append; do not renumber. Idea IDs (`A-n`, `B-n`, `R-n`, `D-n`, `X-n`) are referenced
  by rank entries and by the DAG.
- When an idea is tested, add a one-line verdict under it — **PROMOTED**, **REJECTED**
  (with the counterexample or the number that killed it), or **DEFERRED** (with what
  would revive it) — and cross-reference the cycle report. A rejected idea with a
  recorded reason is more valuable than an untested one, and this repository is already
  unusually good at that.
- When a measurement in section 3 is superseded, replace the number and note the date.
  Stale measured numbers are worse than none.
- If an idea here turns out to be already falsified by an earlier cycle I missed, move
  it to section 10 with the citation. That is a correction, not a failure of the file.

---

*Produced by a read-only meta-research pass, 2026-09-08. No product claim in this file
has been validated. Every promotion gate above is deliberately harder than the
evidence that would make an author want to promote.*

---

## 15. CYCLE 37 MEASURED VERDICT (SUPERSEDES CURRENT-STATE NOTES ABOVE)

This section records the implementation pass that followed the 2026-09-08
read-only backlog review. The older sections remain useful historical hypotheses,
but their statements that multi-field BM25 and structural relation work were
unshipped are obsolete. The detailed record is [CYCLE37_ALPHAEVOLVE.md](research/CYCLE37_ALPHAEVOLVE.md).

### Discovered and fixed

The v7 contentless-delete FTS5 design passed SQLite's internal integrity check
but changed BM25 document-frequency normalization after a changed block was
deleted and reinserted. A clean rebuild and an incremental update therefore
returned different rankings on the same logical corpus. The counterexample was
reproduced on SQLite 3.53.1 before the format was promoted. Format v8 now uses
external-content FTS5 with source-aware deletion of the exact normalized fields;
the authoritative block body is stored once, and `blocks.path` stores only the
normalized path metadata needed by the external table.

Full verification also now builds a rollback-only temporary contentless index
from `blocks` and `files` and compares FTS5 instance postings, document lengths,
and configuration metadata. This catches a self-consistent but source-inconsistent
posting tree or document-statistics table after an attacker rewrites its
self-declared root. The check is deliberately part of artifact acceptance, not
query-time selection.

### Measured promotions and rejections

| Candidate | Measurement | Verdict |
|---|---|---|
| v8 external-content FTS5 | 15 update/rebuild query probes had equal payloads and BM25 scores; logical tables were equal; source-parity verification rejected resealed bogus postings and document lengths | **PROMOTED** |
| A4 definition-only symbols | 84,312 symbols to 5,871; symbol storage 5,120,000 B to 446,464 B; pack 9,662,464 B to 4,988,928 B; all 207 field-only selections stayed exact | **PROMOTED** |
| B1 knapsack allocation | At 512/2,048/8,192 tokens, fields retention 162/205/229 fell to 28/108/203; fields-plus-relations 175/223/239 fell to 42/131/219 | **REJECTED** |
| B2 coverage weighting | Candidate coverage dropped versus the fielded control on the measured budgets and did not recover target B-b8c5ec3852 | **REJECTED** |
| A7/A8 SQLite read pragmas | 1,440 paired exact queries; median delta -0.00745 ms, p95 tied; no large speedup claim | **KEPT as cheap defaults; no headline claim** |
| page-size and canonical-rank variants | Page size saved 0.66% bytes but slowed queries; canonical rank added 0.0879 ms median | **REJECTED** |

The v8 final audit used 153 files and 3,513 initial blocks. A no-op strict
update scanned 153 files, skipped all 153, preserved bytes, and took 93.3 ms.
A one-file update indexed one file, skipped 152, hashed one integrity leaf, and
took 203.1 ms. A fresh rebuild of the changed source produced 3,514 blocks.
The updated and fresh artifacts had equal logical tables and query payloads;
their raw bytes differed because incremental SQLite history and row IDs are
allowed to differ. The default runtime made zero generative calls.

The final contract mutation run killed 159/159 mutants with no harness errors.
The full-suite gate after the v8 implementation is 1,227 passed and 22 explicit
symlink skips. These results verify the tested contracts and update semantics;
they do not establish answer accuracy or a differentiated retrieval advantage.

### Next highest-value hypothesis

The next experiment should measure an allocation policy on a genuinely held-out
repository with an executable answer oracle, while preserving the current fielded
BM25 and conservative relation seeds as baselines. B1 and B2 show that adding a
more elaborate score objective can destroy coverage even when seed ranking looks
better. Any new allocator must therefore report candidate coverage, retained
source coverage, exact context identity, latency, and memory together, and must
survive adversarial queries that reward one long block or many short distractors.

---

## 16. CYCLE 38 MEASURED VERDICT (TARGET-MODEL AND HYBRID FOLLOW-UP)

Cycle 38 used the explicitly authorized NIM credential only in the opt-in answer
evaluator and kept the compiler/runtime zero-generative. The detailed record is
[CYCLE38_MODEL_AND_HYBRID_EVAL.md](research/CYCLE38_MODEL_AND_HYBRID_EVAL.md),
with the machine-readable measurements in
[cycle38-model-hybrid-eval-v1.json](experiments/results/cycle38-model-hybrid-eval-v1.json).

### Discovered, tested, and discarded

The current 12-task urllib3 behavior oracle now has a complete 48-call Llama NIM
run. All calls transported successfully. At 2,000 selected tokens, definition/member
BM25 retained all required spans on 5/12 tasks and produced 3/12 exact answers;
the body-window arm retained all required spans on 2/12 and produced 0/12 exact
answers. No-context and full-context controls also produced 0/12 exact answers,
so this run does not establish a retrieval answer-quality winner.

Disabling the default `raises` relation seed produced 4/12 exact answers and
62.5% required-span coverage in the same model protocol, versus 3/12 and 58.33%
with relations enabled. The older 246-question replay measured the opposite
retrieval ordering, 223/246 versus 205/246 at 2,048 tokens. The default is therefore
unchanged pending a multi-repository paired study.

The optional MiniLM hybrid arm reached 53.47% required-span coverage at 2,000
tokens versus 58.33% for member BM25, while its 657-row pack took 15.26 seconds
to compile, occupied 2,486,272 bytes versus 1,138,688 bytes, and had a 5.80 ms
median selection versus 3.32 ms. At 4,000 tokens it reached 77.78% and 8/12
all-span tasks versus 76.39% and 7/12, which is not enough to promote it as a
default. Candidate limits from 30 through 480 produced identical coverage and
5/12 all-span tasks; the higher limits only increased latency. Both challengers
are discarded as default changes.

NIM model canaries also exposed protocol limits: four Nemotron calls exhausted the
384-token output ceiling without acceptable JSON, and a four-call DeepSeek canary
timed out on three arms. Those results are retained as evaluator diagnostics and
are excluded from retrieval comparisons.

The next experiment is a three-repository paired study with a stable structured
output model, fixed timeouts, both relation settings, and the current hybrid arm.
It must report exact answer outcomes, retained source spans, candidate coverage,
selected tokens, latency, memory, provider usage, and zero-generative behavior
together before changing a runtime default.
