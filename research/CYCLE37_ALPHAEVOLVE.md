# Cycle 37: AlphaEvolve loop for the portable pack

Date: 2026-09-11

Status: format v8 and compiler 8.0 promoted after reproduction, counterexamples,
full regression testing, and mutation testing. The retrieval advantage remains
unproven. The default runtime remains deterministic and zero-generative-LLM.

This cycle started from `META_RESEARCH_BACKLOG.md`, which identified four high
value engineering ideas that were still described as plans: fielded BM25,
structural names, removing the duplicated FTS body, and definition-only symbols.
It also proposed allocation, coverage, cache, page-size, and canonical-rank
challengers. The loop was run as:

```text
OBSERVE -> HYPOTHESIZE -> IMPLEMENT -> TEST -> ATTACK -> MEASURE -> KEEP/DISCARD
```

## Observe

The current Product A is under `npk/pack/*` and exposes `compile`, `update`,
`query`, `verify`, and `stats`. The legacy proxy and context tree remains for
historical replay, but the public compiled artifact is the pack product. The
pre-cycle product already had the strongest measured fielded retrieval result
available in the repository, but its update path had not been audited against
FTS5 ranking stability.

The decisive observation came from a minimal SQLite probe. Format v7 used a
contentless-delete FTS5 table. Deleting and reinserting a changed document kept
the posting tree internally valid, yet changed BM25 document-frequency
normalization. On SQLite 3.53.1, the same query produced a fresh-build score near
`-0.000001` and an incrementally updated score near `-0.397`; the selected order
also changed. This is a correctness failure for an incremental context compiler,
even though ordinary FTS5 integrity checks passed.

The backlog also contained an allocation warning: at 2,048 tokens, the candidate
pool could contain the required source for 241/246 questions while only 205
survived packing. That made allocation a better research target than another
unmeasured seed feature.

## Hypothesize

1. External-content FTS5 can keep the body authoritative in `blocks`, avoid a
   second stored body, and preserve BM25 statistics if updates delete the exact
   normalized fields originally indexed.
2. A source-derived FTS check can detect a posting tree or document-statistics
   metadata that is internally valid but no longer represents the authoritative
   block rows.
3. Definition-only symbols can remove large reference noise while preserving the
   field-search behavior that actually earned the retrieval gain.
4. More elaborate packing and coverage objectives may recover the remaining
   budget failures, but they must be judged by retained source coverage and exact
   evidence identity together with latency and memory.

## Implement

Format v8 (`npk/pack/format.py`) now uses external-content FTS5:

```sql
CREATE VIRTUAL TABLE lexical USING fts5(
    text, name, path,
    content='blocks', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2 tokenchars '_'"
)
```

`blocks.text` remains the exact emitted evidence. `blocks.path` stores only the
normalized path field required by the external-content table. The compiler keeps
normalized body, name, and path values in index postings, and the updater removes
those exact old values before deleting a file's blocks. The block row ID remains
the FTS row ID. The format version and integrity digest domain were bumped so old
artifacts cannot enter the v8 update path silently.

Full verification now performs two distinct checks. The existing FTS5 maintenance
command checks the segment tree, document lengths, and internal pages. When the
ordinary content checks are clean, a rollback-only temporary contentless FTS5
index is built from normalized values derived from `blocks` and `files`. The
actual and expected `fts5vocab(..., 'instance')` streams are compared by
`(term, document, column, offset)`, followed by document-length and configuration
metadata comparisons. This catches a resealed but source-inconsistent posting
tree or document-statistics table. It runs during artifact acceptance and is
outside query-time selection.

The already measured A4 symbol change is now part of the current product path:
definition and structural-name symbols are retained, while transient references
are used to build dependency edges and are not persisted as symbol rows. This is
why the fielded index can stay small without losing code definitions.

## Test and attack

The new counterexamples became permanent tests:

- `tests/test_fielded_relations.py::test_incremental_bm25_scores_match_a_clean_rebuild`
  compares exact BM25 score rows after an update against a fresh rebuild.
- `tests/test_pack_integrity.py::test_resealed_fts_postings_must_match_authoritative_blocks`
  rewrites a posting, reseals its self-declared root, and requires verification to
  reject it.
- `tests/test_pack_integrity.py::test_resealed_fts_document_lengths_must_match_authoritative_blocks`
  rewrites FTS5 document-length metadata, reseals the root, and requires the
  source-derived verifier to reject it.
- `tests/test_incremental_integrity.py::test_full_verifier_does_not_trust_a_cleared_dirty_journal`
  spies on full leaf recomputation so a cached-verification mutant cannot survive.
- Direct `blocks.name`, FTS5 document-length, file reparenting, and file-path mutations are classified
  according to whether their source-derived FTS metadata is still valid.

The full mutation population was rerun after the source-parity change and after
the verifier test was strengthened. A previous run exposed the surviving
`cached_verification` mutant; it was rejected as invalid evidence, the test was
strengthened, and the complete run was repeated.

## Measurements

| Area | Before | After | Decision |
|---|---:|---:|---|
| Fielded BM25 retention at 512/2,048/8,192 tokens | body baseline 148/205/225 in the earlier replay | fields 162/205/229; fields plus relations 175/223/239 | Keep the field and conservative relation channels; this is retrieval evidence, not answer accuracy |
| Persisted symbols on the frozen Python corpus | 84,312 rows; 5,120,000 B symbol storage | 5,871 rows; 446,464 B symbol storage | Promote definition-only symbols |
| Deterministic pack size on that corpus | v7 definition-only 4,988,928 B | v8 initial 5,066,752 B | Accept the 1.56% format overhead for correct incremental FTS semantics |
| No-op strict update, 153 files | full scan and no prior v8 evidence | 153 scanned, 153 skipped, bytes unchanged, 93.3 ms | Keep hash-based no-op behavior |
| One-file strict update, 153 files | whole rebuild was the comparison baseline | 1 file indexed, 152 skipped, 1 integrity leaf hashed, 203.1 ms | Keep incremental update; compare logical state to rebuild |
| Updated versus fresh changed source | v7 ranking could drift after delete/reinsert | v8 logical tables, BM25 scores, and 15 query payload probes equal | Promote v8 |
| Full verification on the 3,513-block frozen code pack | about 0.018 s without source parity | about 0.68 s with posting, document-length, and configuration parity in the refreshed local median run | Keep the safety check; run verification at artifact acceptance |
| Full test gate | prior v8 run: 1,226 passed, 22 skipped | 1,227 passed, 22 skipped in 176.17 s | Promote tested product state |
| Contract mutation gate | 159 mutants, with one verifier test able to miss cached recomputation | 159/159 assertion-killed, no harness errors | Promote only after the rerun |
| Default runtime model calls | zero-generative path | 0 across the 15 final audit probes | Preserve the default |

The final audit report is [`cycle37-final-audit-v5/report.json`](../experiments/results/cycle37-final-audit-v5/report.json). It records the 153-file compile,
no-op update, one-file update, fresh rebuild, logical-table comparison, query
payload comparison, and zero generative calls. The raw updated and fresh SQLite
bytes differ because incremental history and row IDs need not match; semantic
parity is the promotion criterion.

The final mutation report is [`cycle37-contract-mutations-v7.json`](../experiments/results/cycle37-contract-mutations-v7.json), and the full JUnit gate is
[`cycle37-full-v8-final.xml`](../experiments/results/cycle37-full-v8-final.xml).

## Challengers kept or discarded

The following challengers were measured against the fielded control and were not
promoted:

- B1 knapsack scoring reduced retention from 162/205/229 to 28/108/203 at the
  three measured budgets; with relations it reduced 175/223/239 to 42/131/219.
- B2 coverage weighting lost candidate coverage on the measured cases and did not
  recover the target `B-b8c5ec3852` case.
- A9 canonical-rank ordering added 0.0879 ms median and did not earn its semantic
  tradeoff; source path and ordinal tie ordering remains explicit.
- The 8 KiB page-size candidate saved 0.66% of bytes but slowed the measured
  queries.
- The cache-pragmas candidate was retained only as cheap connection defaults:
  1,440 paired exact queries had median delta -0.00745 ms and tied p95, so the
  earlier large speedup claim was discarded.

These rejections are part of the result. They prevent the project from promoting
an allocator or storage setting because it wins one narrow benchmark while losing
coverage or adding cost elsewhere.

## Reproduction

Run from the repository root with the project runtime on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = '.;.venv\Lib\site-packages'
$py = 'C:\Users\vardh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $py -m pytest tests/ -q -p no:cacheprovider `
  --basetemp=experiments\runs\tests\cycle37-full-v8-final-r2 `
  --junitxml=experiments\results\cycle37-full-v8-final.xml

& $py -m benchmarks.contract_mutations `
  --output experiments\results\cycle37-contract-mutations-v7.json
```

The final-artifact script in `.tmp/cycle37_final_audit.py` is deterministic and
local; choose a new output directory in that script before repeating it because
it refuses to overwrite an existing audit directory. The source-parity regression
can be isolated with:

```powershell
& $py -m pytest -q -p no:cacheprovider `
  tests/test_pack_integrity.py::test_resealed_fts_postings_must_match_authoritative_blocks `
  tests/test_fielded_relations.py::test_incremental_bm25_scores_match_a_clean_rebuild
```

## Next highest-value hypothesis

The next cycle should test allocation on a genuinely held-out repository with an
executable answer oracle. The v8 index and conservative relation seeds should be
the fixed baseline. A challenger must report candidate coverage, retained source
coverage, exact context identity, verification status, latency, and memory. The
first adversarial fixtures should include one long high-score distractor, many
short partial matches, repeated identifiers across files, and a query whose only
correct evidence is a low-score neighboring block. If an allocator cannot improve
those cases without losing exact source coverage or exceeding a fixed latency
budget, discard it and keep the simpler greedy packer.
