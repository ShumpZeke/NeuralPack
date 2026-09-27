# Current architecture (as found at the start of the autonomous research loop)

Snapshot: commit `6b90748`, 2026-09-26. Written before any change in this loop, from
reading the code, running the tests, and profiling a real Django compile. Later
changes are recorded in [EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md), not here.

## 1. What NeuralPack is today

A **local context compiler for code/doc repositories**. It turns a source tree into a
SQLite artifact (`.npk`) and, per question, selects source passages that fit a token
budget, with provenance. It makes zero generative-model calls. The answering model is
the caller's.

```text
source tree ──scan──▶ files ──split──▶ blocks ──index──▶ project.npk (SQLite v8)
                                                            │
query ──analyze──▶ terms ──FTS5 bm25 top-60──┐              │
      └─raise-intent──▶ relation sites ──────┴─RRF──▶ greedy fill to budget ──▶ Selection
```

There are two products in one package. Only the first is live:

| | Product A (live) | Product B (legacy, abandoned by the pivot) |
|---|---|---|
| Code | `npk/pack/*` (3,300 LOC) | `npk/*.py`, `npk/context/*`, `npk/providers/*` (4,138 LOC) |
| Thesis | compile once, select per query | HTTP proxy rewriting prompts before a provider |
| CLI | `compile`, `update`, `query`, `verify`, `stats` | `proxy`, `legacy-*`, `diff`, `benchmark`, `analyze`, `explain` |

The research harness is `benchmarks/` (231 modules, 29,348 LOC — 9x the live product),
and `tests/` (122 modules). 1,219 tests pass on Linux/Python 3.12 after one Linux-only
test-harness fix; one test needs an evidence file absent from this snapshot.

## 2. Compile pipeline (`npk/pack/compile.py`)

1. **Scan** (`scan_source`): walk the tree, skip excluded directory names, credential-like
   filenames and unknown suffixes (31 known text suffixes). Read bytes, check the stat
   identity did not change during the read. **Abort the whole build** on any file that is
   > 2 MiB, contains NUL, is not UTF-8, or matches one of five credential regexes.
2. **Split** (`split_source`) into blocks by language:
   - Python: AST top-level `def`/`class` (a whole class is one block unless the
     experimental `python_members` option splits methods), plus runs of uncovered module
     lines. Unparseable files fall back to 60-line windows.
   - Markdown ATX headings; reStructuredText heading/directive structure; a regex/brace
     splitter for C-family/Go/Rust/JS/TS/PHP; everything else (including `.txt`) is cut
     into 60-line windows with no name.
   - Any block over 1,200 estimated tokens (4,800 chars) is re-cut into equal line windows.
3. **Index** per block: `blocks` row (exact text, span, `tokens = len//4`), external-content
   FTS5 row over analyzed body/name/path (identifier pieces added: `send_robust` →
   `send_robust send robust`), definition-only `symbols`, Python `raises` relations
   (second full AST parse + walk), constant `assignments` hashes, optional `deps`,
   optional MiniLM `embeddings`.
4. **Seal**: per-file SHA-256 integrity leaves maintained by triggers; a root digest over
   schema, global tables and leaves. Build in a temp dir, publish by rename.

`update_pack` re-scans, re-indexes only files whose SHA-256 changed (optionally trusting
mtime/size with `--quick`), deletes exact FTS postings for removed blocks, and reseals.

## 3. Query pipeline (`npk/pack/select.py`)

1. Analyze the query exactly like indexed fields; drop function words and 1-char terms;
   **deduplicate terms** (query-term frequency is discarded).
2. FTS5 `MATCH "t1" OR "t2" OR ...`, ordered by `bm25(lexical,1,1,1)`, top 60
   (`candidate_limit`). A one-word query prefers exact whole-word matches.
3. If the query says "raise(s) X" (and no negation), add literal raise sites of `X`.
4. Reciprocal-rank fusion (k=60) of the channels.
5. **Greedy fill**: walk the fused order, add each whole block that still fits the
   budget, skip the rest. Budget = `floor(chars/4)` including separators, or an exact
   local tokenizer if supplied.
6. If nothing is selected: widen to 240 candidates; otherwise report `fallback_required`.
7. Optional (off by default): dependency expansion, conflict deletion, hybrid
   symbol/embedding channels.

Output: evidence list with path, line span, kind, name, score, channels; an
**uncalibrated** risk band from query-term coverage; `used_generative_llm=False`.

## 4. Where time goes (measured, Django @ `965d2d9`, 3,164 files, 16,372 blocks)

| Stage | Time | Share |
|---|---:|---:|
| `analyzed_text` (pure-Python term analysis for FTS fields) | 12.8 s | 30% |
| `_python_raise_sites` (a **second** `ast.parse` + full `ast.walk` per Python file) | 11.9 s | 28% |
| `split_source` (first AST parse, splitting, symbols) | 7.2 s | 17% |
| `scan_source` | 3.5 s | 8% |
| `_seal` (integrity leaves + root) | 2.6 s | 6% |
| SQLite inserts and remainder | ~5 s | 11% |
| **Total compile** (under cProfile) | **43.2 s** | |

Artifact: 45.7 MB. A typical long-issue query takes 57-71 ms on this pack.

## 5. Assumptions the architecture makes

1. A **block is the unit of evidence** and is emitted whole. Selection never shows part of
   a block, and never shows a cheaper view (signature, outline) of a block.
2. **Rank order is packing order.** Greedy fill with skip; no notion of redundancy,
   diversity, or file structure.
3. **The query is short and keyword-like.** All query words are OR-ed with equal weight
   after stopword removal; repeated words count once.
4. **All files are equally likely to be relevant.** Tests, docs, changelogs and source
   compete purely on BM25.
5. **Fail closed on unusual input.** One binary/non-UTF-8/oversized/credential-like file
   aborts the whole build.
6. **Integrity and exact provenance are first-class.** (This part is strong: exact spans,
   Merkle-sealed artifacts, update/rebuild parity, source-derived FTS verification.)

## 6. What the existing benchmarks measure, and their weaknesses

- The headline 246-question CRISP needle replay (`benchmarks/rival_*`, `seed_metadata*`)
  and most frozen studies depend on `experiments/runs/*`, which is **not in this
  snapshot**; they cannot be reproduced here.
- The questions were written and inspected by the developers (explicitly "inspected
  development data"), measured one repository at a time, and many are narrow lookups.
- The executable urllib3/click oracles are strong but tiny (12-15 tasks).
- There was no benchmark on large, heterogeneous repositories with externally authored
  queries, and no held-out split that promotion decisions were forbidden to see.

NPK-Bench (`benchmarks/npkbench/`) was built in this loop to close that gap; see
[BASELINE.md](BASELINE.md).

## 7. What changed since the snapshot (current product, kept by experiments)

The sections above describe the product as found. These changes were kept, each on
NPK-Bench evidence recorded in [EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md):

```text
source tree ──scan──▶ files ──split──▶ blocks ──index──▶ project.npk (SQLite v8)
  (unindexable never-indexed files are skipped and listed in manifest skipped_sources)
                                                            │
query ──strip issue-form scaffolding (E031)
      ──analyze──▶ terms ──FTS5 bm25 top-60───────────┐     │
      ├─raise-intent──▶ relation sites ───────────────┤     │
      └─named code entities──▶ defining blocks ───────┴─RRF─▶ greedy fill ──▶ Selection
                                  (if the top block alone exceeds the budget,
                                   its most query-relevant member spans are emitted)
```

- **Compile (E001):** one cached AST parse per Python file and a statement-only walk for
  raise sites; 1.49x faster Django compiles, logically identical artifacts.
- **Ingestion (E004):** a never-indexed file that is not indexable text (oversize, NUL,
  non-UTF-8, credential-shaped, link outside the root) is skipped and reported in
  `stats.skipped_sources` and the manifest instead of aborting the build (46 of 103
  benchmark snapshots could not be compiled before). An already-indexed file that becomes
  unindexable still aborts `update_pack`; `strict=True` / `--strict` restores abort-on-any.
- **Updates (E014):** string-prefix path handling in `scan_source`; one-file Django
  updates 1.5-2.5x faster. Remaining cost (profiled): scan with per-file `realpath`
  (kept deliberately: every file is resolved before it is read) and the global
  integrity digest, computed before and after the update.
- **Definition channel (E002, `enable_definitions`, `--no-definitions`):** identifiers the
  query names (dotted parts, called names, backticked words, snake/camel-case words) are
  resolved against the definition-only `symbols` table; each name votes for its defining
  blocks with weight `1/log2(1+n)`, names with more than 10 definitions are ignored.
  Held-out: fix-target recall +5.7 to +10.3 points at 1K-16K; tests target -2.4 to -4.5.
- **Top-block trimming (E005c, `enable_trim`, `--no-trim`):** when the best-ranked Python
  block alone exceeds the budget, its member spans (methods/statement runs rebuilt from
  the file) are ranked by file-local BM25 and admitted as `trimmed` evidence instead of
  skipping the block. +13.9 / +7.3 points at 512 / 1K tokens; identical at 2K and above.
- **Context map (E017, opt-in `map_share`, `--map-share`):** the evidence is selected within
  `(1 - share)` of the budget and `Selection.locations` lists further ranked places
  (`path:start-end kind name`, Python classes as members) until the reserved tokens are
  spent. Held-out: located fix recall +7 to +13 points over full text.
- **Test mate (E016b/E016c; default from 2048 tokens, `enable_test_mate` True/False and
  `--test-mate always|never` override):** after fusion, the best
  lexical block of the test file whose path mirrors the top implementation file is placed
  right after that block. The lexical ranking is fetched once to depth 1000 and reused for
  the mate lookup; parsed test paths are cached per artifact snapshot. Always-on on
  held-out: tests +1.1 to +4.5 points, fix -0.3 to -1.4 (even trade at 1K). Gated at 2K
  and above on the fresh heldout-b: tests +2.3 to +6.0, fix -0.4 to -1.1.
- **Issue-form cleaning (E031, `enable_query_cleaning`, `--raw-query`):** before any channel
  runs, HTML comments, checklist lines (`- [x] ...`) and heading lines of at most six words
  (markdown `#` or bold-only) are removed from the query; the first line is always kept,
  a query that would become empty is used as given, and `Selection.query` stays the
  caller's text. Template words ("steps to reproduce", "expected behavior") otherwise
  pull CONTRIBUTING guides, READMEs and changelogs above code. Fresh heldout-c (HC01, 400
  issues): fix +0.7/+0.9/+1.2 points at 4K/8K/16K and tests +0.4 (1K) and +1.4 (16K), all
  significant; no significant loss at any budget.
