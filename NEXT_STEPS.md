# Next steps (handoff for the next agent)

Kept current during the autonomous research loop. Start here, then read
[BASELINE.md](BASELINE.md) and [experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## How to resume in five minutes

```bash
uv venv --python /usr/bin/python3.12 .venv && . .venv/bin/activate
uv pip install -e '.[dev,tokenizers]' numpy==2.2.6 psutil==7.0.0 urllib3==2.7.0 click==8.5.0 \
    tiktoken==0.12.0 safetensors==0.6.2 pyarrow transformers==4.57.6
uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest tests/ -q -p no:cacheprovider      # 1282 pass, 28 skip; one test needs a file not in this snapshot
export NPK_BENCH_HOME=~/npk-data                     # datasets, clones, packs (never committed)
python -m benchmarks.npkbench.run --split dev-fast --targets tests,docs --arms npk_default,npk_nodefs \
    --workers 4 --out experiments/npkbench/runs/<id>
python -m benchmarks.npkbench.report --compare RUN_A:ARM RUN_B:ARM   # paired bootstrap
python -m benchmarks.npkbench.report --judge RUN BASE_ARM CANDIDATE_ARM --targets tests,docs  # decision rule
python -m benchmarks.npkbench.report --judge-runs BASE_RUN:ARM CAND_RUN:ARM --targets tests   # across runs
```

Unused confirmation splits: `heldout-e` (Python, 384; reserved by the declared E055 plan),
`poly-heldout-b` (JS/TS, 320; reserved by the declared E053/E054 plan), and, declared later on
2026-09-27 before any result on them, `gym-heldout-b` (Python, 254), `gym-heldout-c` (Python,
197; both SWE-Gym, the next runs of 30 per repository after `gym-heldout`) and `poly-heldout-c`
(JS/TS, 246);
`gym-heldout` was spent on E052 (GH01). Larger screening splits: `gym-dev` (Python, 326) and
`poly-dev-b` (Java/JS/TS, 371). Declare each confirmation's criteria here before its run.

First runs clone the 12 SWE-bench repositories (blobless, ~2 GB) and build packs
(~15 s each for Django). Use `--ephemeral-packs` on `heldout` (407 tasks) unless you
have ~20 GB free. Record every experiment with `benchmarks.npkbench.expdb.append`.

## Evidence discipline that must not be relaxed

- Contract mutations: 184 mutants, all killed at 4293b7f
  (`experiments/npkbench/contract-mutations-4293b7f.json`, with E047's and E052's three each;
  before that 181/181 at 7cca1f3, 178/178 at c66ccca and 168/168 in
  `contract-mutations-3b5f9f5.json`, whose commit message misstates the added count as 13).
  Add a mutant for every new guard or ranking rule.

- Decide on `dev`/`dev-fast`; confirm once on `heldout`; never tune on `heldout`.
- Small dev-fast effects have not replicated: E035, E036 and E044 each looked good on the
  103 dev-fast issues (utility +1 to +3 points) and then failed on held-out or on the 197
  dev issues outside dev-fast. Screen small-effect ideas on the full dev split and require
  the 197 fresh dev issues to agree before spending a held-out split.
- Judge significance from unrounded bootstrap bounds (`report.paired` now returns a
  `significant` field): E036's tests loss on heldout-d had an upper bound of -0.00004, which
  rounds to 0.0.
- Apply the declared decision rule in `benchmarks/npkbench/__init__.py`: frequency-weighted
  utility `U = d_fix + 0.99 d_tests + 0.087 d_docs` must be >= 0 at every budget, with a
  significant gain on the target the change addresses.
- Always score **all three targets** (`--targets tests,docs`): a change that wins the fix
  target by ignoring tests or documentation is gaming (E006, E011 were caught this way;
  documentation demotion collapses the docs target, E015).
- The docs target is `docs-3` (`benchmarks/npkbench/data.py`, `DOCS_VERSION`): topical
  prose pages edited by the upstream change (commit or PR) that reproduces the reference patch. It is
  small (about 30 dev tasks, mostly Django), so read its paired bootstrap, not the means.
  The docs-1 gold (E015) and docs-2 (integration merges) had construction errors; do not use them.
- Performance changes must be proven output-identical with
  `benchmarks.npkbench.equivalence` and timed with `benchmarks.npkbench.compile_timing`
  (profilers overstate pure-Python call overhead; E001b).
- Compiler experiments run from a separate git worktree (`git worktree add`), never by
  editing the main tree while queued runs are pending: the pack fingerprint is the
  compiler source of the tree the harness runs from.

## Strongest remaining hypotheses (ranked)

State at the time of writing. The queue runner (`~/npk-data/queue_runner_v2.sh`, reading
`~/npk-data/queue.txt`, one `WORKDIR|ENV|ARGS` line per run) executes runs in order;
runs stage into `<out>.partial` (git-ignored) and appear only when complete. Failure
markers live in `~/npk-data/failed/`. Worktree branches `exp/*` are local only; each
rejected experiment's patch is saved in its run directory.

Where the product stands (held-out SWE-bench Verified, 407 issues, run R004): fix-site recall
0.254/0.343/0.456/0.572/0.638 at 1K-16K and regression-test recall 0.090/0.183/0.257/0.344/0.428,
2.0-2.5x (fix) and 1.5-2.1x (tests) a standard BM25-over-chunks RAG baseline (B001); the
documentation gap to that baseline is no longer significant. Before E031/E039 the product
scored 0.230/0.303/0.385/0.472/0.569 (fix). Multilingual sample (R005): fix 0.198-0.455,
1.9-3.1x B002. SWE-PolyBench Java/JS/TS (P001): fix 0.195-0.476. SWE-Gym Python (gym-heldout,
GH01 default arm): fix 0.142-0.479; pandas and mypy are the weakest repositories (about 0.05
at 2K) and neither dense re-ranking (D1) nor qualified-name resolution helps them. Default
since this session: E047 (test-file conventions beyond Python) and E052 (environment dumps
stripped from queries). Opt-in modes: context map (E017), semantic/hybrid for chat histories
read with 4K tokens or more (M006, MH01).

1. **Documentation retrieval is the main weakness, and it is the definition channel's
   known tradeoff.** Chunk-BM25 baselines find more of the documentation maintainers edit
   (held-out at 2K: 0.31-0.38 vs 0.17). Without the definition channel the product is
   already at baseline level (0.29), so the gap is code-first ranking, not unit size:
   smaller documentation units did not help (E019), and documentation votes cost code
   recall (E018b). Under the declared utility (docs weight 0.087) the current trade is
   the best found. A new idea must raise docs without moving code blocks down: for
   example, filling budget that code cannot use (remainders too small for the next code
   block) with the best small documentation units.
2. **Done: the budget-gated test mate is the default (E016c, confirmed by HB01 on
   heldout-b).** Tests +2.3 to +6.0 points at 2K-16K for 0.4-1.1 fix points; 1K unchanged.
3. **Done: semantic/hybrid chat memory is recommended at 4K+ (MH01 on memory-heldout,
   +4.2 at 4K, +6.0 at 8K; neutral at 2K and below).**
4. **bge-small as the semantic encoder** (M004 pool fusion was +3.3 points over MiniLM hybrid
   at 4K on memory-dev): needs CLS pooling and a query prefix in `npk/context/embedding.py`
   and a new encoder identity; for code it passed the rule only barely (E012b) at a large
   compile cost.
5. **Held-out split hygiene:** spent: `heldout` (E002, E005c, E016b, E017), `heldout-b` (E016c,
   HB01), `heldout-c` (E031, HC01), `heldout-d` (E039, HD01), `poly-heldout` (E047, PH01),
   `gym-heldout` (E052, GH01). Unused: `heldout-e` (Python, 384; reserved by the declared E055
   plan), `poly-heldout-b` (JS/TS, 320; reserved by the declared E053/E054 plan),
   `gym-heldout-b` (Python, 254), `gym-heldout-c` (Python, 197) and `poly-heldout-c` (JS/TS,
   246). Declare criteria here before any run on them.
8. **Done: very long queries are capped (E043).** Distinct lexical terms per issue: median
   62-82, p99 300-466, up to 4,164. A query now keeps its first 512 distinct terms (backticked
   literals always kept): synthetic Django queries of 1,000 / 20,000 identifiers take 2.2 / 4.1
   s instead of 8.4 / 114 s; on the ten benchmark issues above the cap (split `long-queries`,
   heldout-e excluded) latency falls from 1.2 s to 0.74 s median and recall does not change
   significantly (43 of 50 issue-budgets identical). The remaining growth is in the
   definition channel and text analysis.
7. **Where ranking still fails (E039 default, dev-fast, full fused ranking):** the first gold
   block is ranked first in 38 of 103 issues, in the top 3 in 45, top 10 in 59, top 50 in 78;
   in 24 issues no candidate covers a gold hunk at all (the gold block is outside every
   channel's top 60, and a larger candidate limit did not help, E026). The top block is in a
   gold file for 57 issues. Candidates that are not the fix but outrank it are mostly other
   code (15) or other blocks of the right file (16); tests (8) and docs (2) are rare. Of the
   24 issues without a gold block in the pool, 16 have the gold *file* in the pool (another of
   its blocks ranked) and 8 miss the file entirely (vocabulary gap: likely needs semantic
   retrieval). A file-local second stage (rank the top files' own blocks by file-local BM25,
   as trimming ranks members) could reach the first group, but the budget is almost always
   full (about 40 tokens left at 16K), so such blocks must displace low-ranked pool blocks,
   which is how file aggregation (E003) failed. Measured since: ranking each such gold file's
   own blocks by file-local BM25 with the weighted query puts the gold block in the local
   top 2 for only 1 of 16 issues (top 5 for 4), so the second stage has little to find; the
   gold regions share little vocabulary with the issue (non-opportunity).
6. **Done: E039 title and repetition weighting is the default (HD01 on heldout-d).** Fix
   +1.4 to +4.6 points at 2K-16K and tests +2.8 to +12.2 at every budget, all significant.
   E034 (title x4 alone) also passed; E035 (mate file choice) and E036 (top-file header)
   failed on held-out (E036 on a significant tests loss of 0.7 points at 2K despite
   significant fix gains, so a header variant gated to 4K+ is a candidate for a fresh split).
   Next: re-measure the README table with the new default on `heldout` (measurement only)
   and the non-Python sample (`ood-multi-sample`); 384 issues of `heldout-b-all` remain
   unused for a `heldout-e`.

Measured non-opportunities (do not re-run without a new idea): vendored code (`deps/`, `vendor/`, `third_party/`: no gold hunk in 2,360 across dev, held-out and multilingual dev; only 0.2-1.2% of selected lines at 2K, so demoting it cannot pay for the scope change); a traceback-frame channel
(the 7 dev-fast tasks whose traceback names a gold file already score 0.86-0.93 from 1K);
module-path mentions (the product already selects the named gold file at 2K in 15 of 20
cases); an error-message phrase channel (3 of 103 issues quote a message found verbatim in
a gold file; re-measured 2026-09-27 on the larger screens: of issues quoting an exception message
without a traceback, the message's raise site (a verbatim fragment found in 1-3 files) holds a fix
hunk in 1 of 20 on gym-dev and 1 of 32 on dev); Java and JavaScript stack-trace frames (20 of 371
poly-dev-b, 10 of 199 poly-dev and 3 of 186 ood-multi-dev issues carry any, and they name a fix
file in 6, 6 and 2, so E055 stays Python-only); change history as a fix-location prior (dev-fast: for the 42 issues
whose first fix block ranks 2-50, the fix file has more commits among the 500 before the base
than the median block above it in 24, and re-ranking the top 50 by churn tier helps 21 and
hurts 18, median rank 7.5 -> 11); git co-change history for the test mate (the test file that most often
changed with the top implementation file in the 3,000 commits before the base is a gold
test file in 35/103 dev-fast issues, vs 36 for path mirroring and 49 for mirror plus lexical
rank; 52 vs 50 when given the true fix file), so it does not justify adding history to packs;
promoting the top file's next block right after the top block at small budgets (simulated
on the E039 default, dev-fast: it would lift a gold block to rank 1 in 7 issues but push a
gold block from another file down in about 10); qualified `Class.member` resolution by intersecting the class's blocks with the member's
definitions (dev-fast: 24 issues name such pairs, 14 resolve to 1-3 blocks, 8 gold hunks sit in
them, and the default already finds all 8 at 1K); translated documentation copies (7-8% of
material-ui's budget on poly-dev-b, 2 gold hunks); repository boilerplate (LICENSE, AUTHORS,
CODE_OF_CONDUCT, SECURITY, CONTRIBUTING, `.github/`: at most 0.2% of 2K lines on any split) and
lockfiles (never selected; 24 poly-dev-b fix hunks are dependency bumps in them); compositional name matches (a definition such as `_print_Product` whose name parts all occur
in the issue and include a code name it mentions: 13 of 153 dev-fast fix hunks covered, 6 of
them missed at 4K, about 13 candidate blocks per issue, so at most a few hunks);
skipping per-file `realpath` in scans (a test pins resolution-before-read,
which matters for Windows reparse points; saving ~0.3 s per Django update).

## Non-Python development set: SWE-PolyBench (added 2026-09-27)

`poly-dev` (199 issues) and `poly-heldout` (133) are the Java, JavaScript and TypeScript
issues of SWE-PolyBench's verified 500 (MIT), minus microsoft/vscode, angular/angular and
google/guava, split per repository by a fixed hash (declared before any result, commit
3d0466d). Twelve repositories (material-ui, svelte, trino, rocketmq, serverless, prettier,
gson, dubbo, tailwindcss, three.js, code-server, apollo); blobless clones add 0.3 GB. Their
fix patches often include changesets and docs (about a quarter of first gold files are not
code), as SWE-bench Multilingual's do. Develop JS/TS/Java handling on `poly-dev`, declare
criteria here, then confirm once on `poly-heldout`.

P001 (the reference before any tuning on `poly-dev`): fix recall 0.195 / 0.244 / 0.319 /
0.404 / 0.476 at 1K-16K and regression tests 0.113 / 0.185 / 0.276 / 0.378 / 0.418. The
query handling passes the declared rule on these languages too (fix +6.0 to +8.9 points,
tests +3.1 to +11.0, all significant, against `npk_query_baseline`), and the default is
1.6-2.2x B002 on fix. By language at 2K / 16K: Java (74 issues) 0.262 / 0.486, JavaScript
(75) 0.218 / 0.440, TypeScript (50) 0.258 / 0.514. JavaScript is the weakest; about a
quarter of first gold files are changesets or docs, which the code channels cannot rank.
E046 (E032's member and modifier-prefixed definitions, scoped to JS/TS/Java at compile
time) failed the rule on `poly-dev`: fix +2.5 / +1.4 / +0.6 points at 1K / 4K / 8K
(significant), mostly Java, but regression tests -0.3 / -0.9 at 4K / 8K (significant) and
utility below zero at 8K and 16K. The likely cause is the test mate, which cannot pair
Java's `FooTest.java` with `Foo.java` (E047): re-screen E046 on top of E047 if E047 is kept.

E047 (running): `TEST_PATH` knows only Python's test conventions, so colocated JS/TS tests
(`Button.test.js`, `__tests__/`) count as implementation files and get no mate, and Java's
mate ties among every test of the package. Offline, on P001's 2K selections, the mate file
is a gold test file for 24 of 173 tests-target issues now and 51 with the JS/TS/Java
conventions (Java 16 -> 26, JavaScript 6 -> 12, TypeScript 2 -> 13). Arms: `e047_paths`
(polyglot test-path patterns), `e047_affix` (+ CamelCase test affixes stripped for
mirroring), `e047_strict` (+ a mate must share the module or package name). Screened on
`poly-dev` (decision), `ood-multi-dev` (other languages) and `dev-fast` (Python selections
should not move).

## Pre-declared plan for poly-dev-b and poly-heldout (written before any result on either)

Three JS/TS/Java candidates came out of `poly-dev` with real but small effects, and each
missed the every-budget utility condition by a hair there (199 issues; one or two issues
decide 8K/16K):

* E047 `e047_strict`: test-file conventions (Jest/JUnit/Go/gtest/RSpec paths, CamelCase test
  affixes, a mate must share the module or package name). Tests +2.45 at 2K (significant),
  utility -0.22 at 8K.
* E048: only a brace type's header fragment defines its name (compile time), with
  E049 `e049_members_e047`: qualified member references (`Type#member`, `Type::member`,
  `Type.member`) resolve method blocks, plus E047. Tests +3.11 at 2K (significant), fix
  +1.49 at 1K, mean utility +1.03, utility -0.03 at 16K (one issue).

`poly-dev-b` (371 issues, disjoint from `poly-dev` and `poly-heldout`, declared in
`data.py` with this plan) screens them with more power. Arms: C1 = `e047_strict` on the
current compiler; C2 = `e049_members_e047` on the E048 compiler (worktree `exp/e048`);
each against `npk_default` on the current compiler, targets fix and tests. The standard
rule applies: utility `d_fix + 0.99 d_tests` >= 0 at every budget, a significant fix or
tests gain at one or more budgets, no significant loss at any budget. If neither passes,
both are recorded as rejected and `poly-heldout` stays unused. If one passes, it (or, if
both pass, the one with the higher mean utility on `poly-dev-b`) is run once on
`poly-heldout` (PH01) against `npk_default` and promoted only if it meets the same rule
there; for C2 the product change is the E048 compiler change plus E049 and E047 in
`select.py`. Python is untouched by construction apart from JS/TS/Java files inside Python
repositories (dev-fast: one Django issue's mate changes, no recall change), so no Python
held-out split is spent; dev-fast equivalence is re-checked for the product form. E048 also
changes Go, Rust, C/C++, C# and PHP packs: its `ood-multi-dev` screen (queued, no result yet)
is a side condition for C2. If it shows a significant loss on either target at any budget,
E048 is restricted at compile time to JavaScript, TypeScript and Java before promotion.

### poly-dev-b outcome and PH01 (written before PH01 runs)

C1 (`e047_strict`) passes on `poly-dev-b`: tests +2.28 / +2.72 / +2.01 / +0.90 at 2K-16K
(all significant), no significant fix change, utility >= 0 everywhere (mean +1.50). C2 (E048
compiler + `e049_members_e047`) fails: fix -1.11 / -0.71 at 4K / 8K (significant), utility
-0.47 at 1K; the E048 compiler alone is negative at every budget (mean -0.60). Per the plan,
PH01 runs C1 once on `poly-heldout` (133 issues): arms `npk_default` and `e047_strict` on the
current compiler, targets fix and tests; E047 is promoted only if utility
`d_fix + 0.99 d_tests` >= 0 at every budget, fix or tests gains significantly at one or more
budgets, and no target loses significantly at any budget. The product form (worktree
`exp/e047p`) must reproduce `e047_strict` exactly on `dev-fast` and `poly-dev` before it is
merged. E048's multilingual screen is dropped (C2 failed).

### PH01 outcome: E047 promoted (poly-heldout now spent)

E047 passed on `poly-heldout`: tests +1.82 / +0.90 / +1.62 / +1.53 at 2K-16K (significant
at 2K, 8K, 16K), fix +0.02 to +0.14, utility >= 0 everywhere (mean +1.23). The product form
reproduces the prototype exactly (dev-fast 515/515, poly-dev 995/995) and is the default.
The next JS/TS confirmation split is declared (before any result on it): `poly-heldout-b`,
320 issues (80 each from material-ui, prettier, serverless and svelte) from the full
SWE-PolyBench outside the verified 500 and `poly-dev-b`. It has no Java issues; Java work
must confirm on a set built elsewhere (e.g. Multi-SWE-bench).

## Pre-declared selection for E050 and HE01 (written before any E050 result)

E050 (fit-or-trim for lower-ranked Python classes; arms `e050_first1_k2`, `e050_first3_k1`,
`e050_all_k1`, control `e050_control`) runs on the full `dev` split (300). Its idea came from
a dev-fast diagnostic, so the 197 dev issues outside dev-fast are the fair screen. A variant
is a candidate only if it passes the standard rule on the full split (utility
`d_fix + 0.99 d_tests + 0.087 d_docs` >= 0 at every budget, a significant fix or tests gain,
no significant loss) and has utility >= 0 at every budget on the 197. The candidate with the
highest mean utility on the 197 runs once on `heldout-e` (HE01, 384 issues, the last unused
Python split) against `npk_default`, targets fix and tests, and is promoted only if it meets
the standard rule there. If no variant is a candidate, `heldout-e` stays unused.

### E050 outcome and E050b on gym-dev (written before any gym-dev result)

No E050 variant met the selection above: the 2K fix gain (+3.1 to +3.3 on the full split,
+3.5 to +3.7 on the fair 197, significant) came with utility below zero at 1K (tests -1.3 on
the 197: trimmed members displace other top blocks when the budget holds three or four) and
at 16K (one docs issue). `heldout-e` stays unused. E050b gates the trimming of lower-ranked
blocks at 2K, as the test mate is gated (`e050b_first3_k1_2k`: first three non-fitting
classes, one member each, from 2K; 1K is the product's by construction). It is screened on
`gym-dev` (326 SWE-Gym issues from 11 Python repositories SWE-bench does not use; declared in
`data.py` with this plan), targets fix and tests, against `npk_default`, with the standard
rule. If it passes, it runs once on `heldout-e` (HE01) with the same rule on fix and tests;
otherwise it is rejected and `heldout-e` stays unused. The ungated `e050_first3_k1` runs
alongside for information only.

### E050b outcome (gym-dev): rejected; `heldout-e` still unused

On `gym-dev` the 2K-gated trimming gains fix +1.35 at 2K (significant) but loses tests -1.75
at 2K (significant) and -0.87 at 8K: the trimmed members displace test blocks on these
repositories. The default's first measurement on `gym-dev` (11 Python repositories SWE-bench
does not use): fix 0.176 / 0.227 / 0.315 / 0.392 / 0.485 and tests 0.053 / 0.133 / 0.177 /
0.282 / 0.339 at 1K-16K, well below SWE-bench dev; pandas (0.061 at 2K) and mypy (0.046) are
the weakest, both large codebases with many near-identical names. `gym-dev` is now the
larger Python screening split; `gym-heldout` (300) and `heldout-e` (384) are unused.

### Pre-declared plan for E052 (environment dumps; written before any E052 result)

E052 (`e052_env`, prototype `env_dump.py`) removes environment/version dumps from the
retrieval query (blocks of `key: value` lines with at least three version numbers or
`None` values making up at least half of their key-value lines). It changes 70 of 326
`gym-dev` queries (pydantic 23, pandas 18, bokeh 14, ...), 15 of 300 `dev` queries
(scikit-learn 10), 7 of 199 `poly-dev` and 1 of 186 `ood-multi-dev`. The idea came from
`gym-dev` selections (pandas' `_print_versions.py` ranked first for 8 of 30 pandas issues),
so `gym-dev` is not a fair screen. It is screened on `gym-dev` and `dev` (standard rule on
fix and tests; neither may show a significant loss) and, if it passes on `gym-dev`,
confirmed once on `gym-heldout` (GH01, 300 issues) against `npk_default` with the standard
rule on fix and tests. If it fails either screen, it is rejected and `gym-heldout` stays
unused.

### gym-dev observations (open problems, measured 2026-09-27)

- **Large codebases are the weakest Python case.** pandas finds 0.061 of fix hunks at 2K
  (0.113 excluding its release-note hunks) and mypy 0.046: every file shares the domain
  vocabulary (Series, dtype, TypeInfo), so lexical ranking cannot separate them. This needs
  a new kind of evidence (call structure from the named entities, or code-aware semantics),
  not more lexical tuning.
- **mypy specifics** (30 issues): at 2K, docs take 29% of selected lines, vendored typeshed
  stubs 12% (never gold), and 67 of 72 regression-test gold hunks sit in `test-data/unit/*.test`,
  which no test-file convention covers (the test mate never fires). Go's `testdata/` is the
  one language-level convention of this kind; anything broader would be repository fitting.
- **Cython is not indexed** (`.pyx`, `.pxd`): 9 of 1,905 gym-dev fix hunks, 4 issues. Low
  priority.
- **pandas release notes**: nearly every pandas fix adds a `doc/source/whatsnew` entry, which
  the fix target counts; retrieving "the newest release-note file" would be benchmark-shaped
  rather than useful context, so it is not pursued.

### GH01 outcome: E052 promoted (gym-heldout now spent)

E052 passed on `gym-heldout`: fix +0.51 / +1.44 / +0.96 at 1K-4K (significant), tests +1.09 to
+1.55 at 2K-16K (significant), utility >= 0 everywhere (mean +1.92). The product form cleans
every screened query exactly as the prototype and reproduces its selections (dev-fast
515/515, gym-dev 1630/1630); it is the default, inside `enable_query_cleaning`. Remaining
unused confirmation splits: `heldout-e` (Python, 384) and `poly-heldout-b` (JS/TS, 320).

### Pre-declared plan for E053 (URLs in queries; written before any E053 result)

E053 (`e053_urls`, prototype `url_clean.py`) rewrites URLs in the retrieval query: image links
and GitHub attachments dropped, GitHub `blob`/`tree`/`raw` links reduced to the repository path,
other GitHub links dropped, other URLs reduced to path and fragment words. SWE-bench Lite
removed issues with links (dev has none), so it is screened on `gym-dev` (151 of 326 issues
have URLs) and `poly-dev-b` (URL-rich JS/TS/Java), both unused for this idea, with the standard
rule on fix and tests. It is a candidate if it passes on one screen with no significant loss on
the other. A candidate that passes on `poly-dev-b` is confirmed once on `poly-heldout-b` (320);
otherwise one that passes only on `gym-dev` is confirmed once on `heldout-e`. Only one
confirmation run is made; if E053 is not a candidate, both splits stay unused.

### Pre-declared plan for E054 (release notes last; written before any E054 result)

E054 (`e054_notes_last`, prototype `release_notes.py`) moves blocks of historical release-note
prose files (CHANGELOG, CHANGES, HISTORY, NEWS, release notes, whatsnew, blog and releases
paths; prose extensions only) behind all other candidates. At 2K they take 9.2% of selected
lines on `poly-dev-b`, 2.4% on `gym-dev`, 3.0% on `ood-multi-dev`; of 5,193 fix hunks on those
splits 74 are release-note entries and the default finds 2 of them; the docs target already
excludes release notes. It is screened on `poly-dev-b` and `gym-dev` in the same runs as E053
(control `e054_control` must equal `npk_default`), with the standard rule on fix and tests; it
is a candidate if it passes on `poly-dev-b` with no significant loss on `gym-dev`. If E053
and E054 are both `poly-heldout-b` candidates, one confirmation run carries both arms against
`npk_default` and each is promoted only if its own arm meets the standard rule there.
Translated docs (7-8% of material-ui's budget, 2 gold hunks) were measured and not pursued.

### poly-dev-b outcome for E053/E054 and PHB01 (written before PHB01 runs)

Both pass on `poly-dev-b` (371 issues; the E054 control reproduces `npk_default` on all 1,855
selections). E053 (`e053_urls`): fix +0.68 / +0.90 / +0.83 / +2.01 / +1.49 at 1K-16K
(significant at 2K, 8K, 16K), tests +0.39 to +1.02 (none significant), utility >= 0 everywhere
(mean +1.82); on `gym-dev` it changes nothing significantly (mean utility +0.39), so it is a
candidate. E054 (`e054_notes_last`): tests +0.65 / +0.56 / +1.32 at 1K-4K and fix +1.13 at 4K
(all significant), fix -0.13 at 16K (not significant), utility >= 0 everywhere (mean +1.38); it
passed on `gym-dev`, so it is a candidate. Per the plan, PHB01 runs once on `poly-heldout-b`
(320 issues: material-ui, prettier, serverless, svelte) with arms `npk_default`, `e053_urls`,
`e054_notes_last` and `e054_control` (which must equal `npk_default`), targets fix and tests;
each change is promoted only if its own arm meets the standard rule there (utility
`d_fix + 0.99 d_tests` >= 0 at every budget, a significant fix or tests gain at one or more
budgets, no significant loss at any budget). Added before the run, following HD01: the run
also carries `e053_e054` (both changes, prototype `urls_notes.py`); if both arms pass, they are
combined in the product only if `e053_e054` meets the same rule in the same run, and otherwise
only the arm with the higher mean utility is promoted. A product form must reproduce its
prototype's selections before it is merged (E054's is ready on local branch `exp/e054p`).

### Pre-declared plan for E055 (traceback frames; written before any E055 result)

E055 (prototype `traceback_frames.py`) adds a channel ranking the blocks that define the
functions named by the issue's traceback frames (CPython, IPython 7 and 8, and pytest
formats), innermost frame first, fused by RRF like the other channels. A frame's path is
resolved to a pack file by its longest path suffix (after `site-packages/`), its function to
that file's defining blocks (the frame's line chooses among same-named definitions; a
`<module>` or comprehension frame takes the block containing its line); frames outside the
repository resolve to nothing. Arms: `e055_frames` (every resolved frame), `e055_frames3`
(the three innermost resolved frames), control `e055_control` (must equal `npk_default`).
Only issues with a traceback can change (dev 64 of 300, gym-dev 49 of 326; query cleaning
keeps every frame). The opportunity was measured on both screening splits (a frame's own
function holds a fix hunk in 38 dev and 32 gym-dev issues; the default covers 29 of those 45
hunks at 1K and 27 at 2K on dev, 20 of 57 and 32 on gym-dev), so neither screen is fresh and
`heldout-e` is the guard. Screens: `dev` (fix, tests, docs) and `gym-dev` (fix, tests), with
the standard rule. A variant is a candidate if it passes the rule on at least one screen and
has utility >= 0 at every budget and no significant loss on the other; if both variants are
candidates, the one with the higher mean utility over the ten screen cells goes on. The
candidate runs once on `heldout-e` (HE01, 384 issues, the last unused Python split) against
`npk_default`, targets fix and tests, and is promoted only if it meets the standard rule
there (utility `d_fix + 0.99 d_tests` >= 0 at every budget, a significant fix or tests gain at
one or more budgets, no significant loss at any budget). If no variant is a candidate,
`heldout-e` stays unused. The product form puts the channel first in the fusion order, as the
prototype's hybrid slot does, and must reproduce the prototype's selections on both screens.

### E055 dev outcome (rejected) and E055b (declared after it, before any gym-dev result)

On `dev` (control identical to `npk_default` on all 1,500 selections), `e055_frames` gains fix
+1.50 at 4K (significant) and +0.28 / +1.00 / +0.67 at 2K / 8K / 16K but loses 0.22 at 1K
(utility -0.22, not significant), and `e055_frames3` loses fix 1.06 at 1K and tests 0.84 at 4K
(significant). Under the declared plan neither can be a candidate whatever `gym-dev` shows
(each would need utility >= 0 at every budget on `dev`), so E055 is rejected. The 1K loss is
the familiar small-budget displacement (the test mate is gated at 2K for this reason; E050b).
E055b (`e055_frames_2k`: every resolved frame, fused only from 2K; 1K is the default's by
construction) is declared now: its dev cells equal `e055_frames`' from 2K (utility +0.03 /
+1.00 / +1.42 / +0.50) and were seen before it was defined, so they are not evidence.
`gym-dev` is its screen (the queued E055 run, which now also carries `e055_frames_2k`): E055b is
a candidate if it passes the standard rule there on fix and tests. A candidate runs once on
`heldout-e` (HE01) against `npk_default`, targets fix and tests, with the standard rule;
otherwise `heldout-e` stays unused.

## Semantic evidence for code: what has been measured

Dense and neural evidence has not helped code retrieval on this benchmark so far: equal-weight
dense fusion (E012) loses fix recall at 1-2K; a bge-small channel (E012b) passes the rule only
barely at a large compile or query cost; static Model2Vec vectors (E038) lose fix recall; and
web-passage cross-encoders reordering the top 10 (E045) lose 8-16 fix points at 1K-4K because
they prefer prose-like tests and docs over implementation code. The 8 dev-fast issues whose
gold file is entirely missing from the pool (vocabulary gap) still need semantic evidence; a
code-trained encoder or reranker is the remaining option, and it must be cheap enough to
run on CPU at compile or query time.

D1 (2026-09-27, diagnostic only) tried that option where lexical ranking is weakest: a
code-trained bi-encoder (Alibaba-NLP/gte-modernbert-base, Apache-2.0, pinned revision
e7f32e3c, safetensors, CoIR 79.3; CLS pooling, 192-token inputs) re-ranked the lexical top 300
for 20 gym-dev pandas and mypy issues. Of the 16 whose gold is in that pool, the dense order
puts the gold higher than lexical ranking in 5 and lower in 11 (top-60: lexical 12, dense 9,
RRF of both 10); RRF moves one of the four deep-tail gold blocks into the top 60. The
embedding matches issue prose to docstrings and tests as readily as to the internal code a
fix edits, so a dense channel is not built. Data and script:
`experiments/npkbench/diagnostics/D1-*`.

## Open policy question for the maintainers

The top-file module header (E036/E042) consistently finds about 2 more fix sites per 100
issues from 2K-4K up (significant on held-out and dev), but its tokens displace a test
block, costing about 0.7-1.2 regression-test points at one budget (significant). Its
utility is positive (+1 to +3 points), yet the declared rule forbids any significant loss, so
it is not shipped. If fix sites should count more than the rule's 1 : 0.99 fix/tests weights
say, or the rule should accept losses where utility is clearly positive (as E016c's
criteria did), the header becomes a candidate; that is a policy decision, not a tuning one.

## Things that were tried and must not be repeated without a new idea

See the rejected entries in EXPERIMENTS.md: file aggregation (E003), coarse->fine
emission for every large block (E005), role priors (E006; docs-3 shows -14 to -40 docs
points), portfolios (E008), callee expansion (E009), learned re-ranking over existing
channels (E011), equal-weight dense fusion for code (E012), sibling collapse (E013),
reST sectioning of `.txt` docs (E019), a documentation channel (E018/E018b: trades code
for docs), diversity/density/paragraph units for conversations (M001-M003).

## Pre-declared criteria for H001 (written before its results)

- E016b test mate is promoted if, on held-out: the tests gain is significant at one or
  more budgets, utility `d_fix + 0.99 d_tests + 0.087 d_docs` is >= 0 at every budget
  (point estimates), and fix recall has no significant loss at a budget where utility is
  not clearly positive. The merge is prepared on local branch `merge/e016b`.
- E005c trimming stays if utility (trim vs notrim) is >= 0 at every budget on held-out.
- E017 context map: located recall must exceed full-text recall significantly on held-out.

## Pre-declared criteria for HB01 (heldout-b; written before its results)

HB01 runs `npk_default` (product), `npk_mate` (test mate on) and `npk_nodefs` (no definition
channel, no trimming) on `heldout-b` (400 fresh issues), targets fix and tests.
- E016c budget-gated test mate (off below 2K, on at 2K and above; the 1K cell is the
  product's by construction): promoted to default if utility `d_fix + 0.99 d_tests` is
  >= 0 at every budget, the tests gain is significant at one or more budgets, and fix recall
  has no significant loss at a budget where utility is not clearly positive. Motivated by
  H001's 1K result, so it must not be confirmed on `heldout`.
- E002+E005c replication: the product's fix recall must exceed `npk_nodefs`
  significantly at 1K-4K.

## Non-Python code (OM01, OMD01, E030)

On SWE-bench Multilingual (41 repositories), NeuralPack beats both chunk-BM25 baselines
and the definition channel helps. The query handling (E031 + E039) added +8.9 to +13.5 fix
points on the measurement sample (R003: 0.198/0.260/0.301/0.364/0.455 at 1K-16K; 0.164 at 2K
before), so absolute recall is now about three quarters of Python's (0.260 vs 0.346 at 2K).
By language at 2K (R003, issues grouped by the extension of most gold files): Java 0.44 (11
issues), Go 0.42 (13), PHP 0.38 (10), Rust 0.29 (18), Ruby 0.22 (16), JS/TS 0.18 (18), C/C++
0.14 (15), and 0.11 for 13 issues whose fix patch mostly edits changelogs or docs
(`CHANGES.txt`, `CHANGELOG.md`; the multilingual reference patches include them). C/C++ and
JS/TS remain the weakest code languages. The diagnosis below predates those changes. Diagnosis on
`ood-multi-dev` only: the loss is ranking, not packing (fix sites rank at median 112-401;
window trimming for non-Python blocks, E030, changed nothing). C/C++, JS/TS and Rust are
weakest (3-4% of gold hunks selected at 2K). JS issues' budgets go to CONTRIBUTING.md,
README.md and changelogs, a symptom of issue-template words; E031 (strip template
headings, checklists and HTML comments from the query) is positive but not yet
significant on multilingual dev; on the full Python dev split (E031b) it passed the rule
narrowly, and the fresh `heldout-c` confirmed it (HC01), so it is now the default
(`enable_query_cleaning`, `--raw-query`). Two structural ideas were tried on
`ood-multi-dev` and rejected: definition symbols for bare members and modifier-prefixed
declarations (E032: JS/TS +4.3 and Java +1.5 at 2K, Rust -4.8, Python unchanged) and a Ruby
`def ... end` splitter (E033: tests +20 at 8K but fix -10.9 at 16K on 28 issues). Both need
more issues per language than `ood-multi-dev` has to tune without fitting noise; per-language
work should wait for a larger non-Python dev set (for example the Multi-SWE-bench or
SWE-PolyBench issues outside the measurement sample).

## Pre-declared criteria for HC01 (heldout-c; written before its results)

HC01 runs `npk_default` and `e031_clean` (E031: issue-template headings, checklists and HTML
comments removed from the query; title and content lines kept) on `heldout-c` (400 unused
issues), targets fix and tests. E031 is promoted into the product's query handling only if
utility `d_fix + 0.99 d_tests` is >= 0 at every budget, fix or tests gains significantly at
one or more budgets, and no target loses significantly at any budget. Dev evidence (E031b,
300 issues): utility +1.0/+0.7/+1.6/+2.5/+0.4 points, tests +1.1 at 4K (significant), no
significant losses.

**Outcome (2026-09-27): passed; E031 is the default.** heldout-c: fix +0.7/+0.9/+1.2 points
at 4K/8K/16K and tests +0.4 (1K) / +1.4 (16K), all significant; utility
+0.25/+0.54/+1.26/+1.86/+2.57; no significant loss. `npk_rawquery` is the previous product.

## Pre-declared criteria for HD01 (heldout-d; written 2026-09-27 before its run and before the full-dev results of E034/E035/E036/E039)

Candidate selection on the full dev split (run `E034-E035-E036-dev`, 300 issues, all arms
against the current product with E031 cleaning):
- E034 title weighting: x3 or x4, whichever has the higher mean utility over the five budgets
  on the full dev split (ties go to x3, the smaller change). It goes to heldout-d if it passes
  the declared dev rule (utility `d_fix + 0.99 d_tests + 0.087 d_docs` >= 0 at every budget and
  a significant gain on fix or tests).
- E035 (mate file choice), E036 (top-file header) and the E039 + title combination go to
  heldout-d only if they pass the same dev rule on the full dev split; E035 and E036 must also
  keep utility >= 0 at every budget on the 197 dev issues outside dev-fast, where their rules
  were not designed.

HD01 runs `npk_default` and the selected candidate arms on `heldout-d` (401 unused issues),
targets fix and tests. A candidate is promoted only if, against `npk_default`: utility
`d_fix + 0.99 d_tests` is >= 0 at every budget, fix or tests gains significantly at one or
more budgets, and no target loses significantly at any budget. If two or more candidates
pass, an arm combining them must pass the same criteria in the same run before they are
combined in the product; otherwise only the candidate with the higher mean utility is promoted.

**Dev outcome (2026-09-27, run `E034-E035-E036-dev`; the declared rule applied mechanically):**
every arm passes the dev rule on the full dev split. Mean utility over the five budgets:
E034 x4 11.2 > x3 10.2, so **x4** is the E034 candidate. On the 197 issues outside dev-fast,
`e035_fused` falls to -0.14 at 8K and `e036_header2` to -0.3 at 4K (tests -1.6 at 8K,
significant), so the candidates are **`e035_mirror_any`** (0/+2.4/+1.2/+0.8/0) and
**`e036_header`** (+0.9/+0.9/+0.3/+0.4/+3.6). **E039 (cap 3 + title x3)** passes and goes too.
HD01 also runs the combinations of these candidates (`prototypes/combo.py`), so that whichever
subset passes has its combination measured in the same run.

**HD01 outcome (2026-09-27): E039 promoted.** Passing: E034 x4 (mean utility 9.54) and E039
(9.99); failing: E035 (significant fix loss at 4K) and E036 (significant tests loss at 2K).
The two passing candidates are alternatives with no arm combining them, so by the rule
above only E039 (higher mean utility) is promoted.

## Pre-declared criteria for HE01 (heldout-e; written 2026-09-27 before E042's dev run)

E042 re-tests the top-file header (E036) on top of the E039 default in two forms: placed
only from 4K (`e042_header_from4k`; on heldout-d E036's fix gains at 4K-16K came without a
tests loss there) and placed at every budget with a tighter cap of `budget // 16`
(`e042_header_cap16`). On the full dev split (`E042-header-dev`), a variant is a candidate if
it passes the declared dev rule (utility >= 0 at every budget, a significant fix or tests
gain, no significant loss); if both are candidates, the one with the higher mean utility over
the five budgets goes to heldout-e. HE01 runs `npk_default` and that candidate on `heldout-e`
(384 unused issues), targets fix and tests, and promotes it only if utility
`d_fix + 0.99 d_tests` >= 0 at every budget, fix or tests gains significantly at one or more
budgets, and no target loses significantly at any budget (unrounded bootstrap bounds).

**HE01 re-declared for E044 (2026-09-27, before E044's full-dev run; E042 failed its dev rule,
so heldout-e is still unused).** E044 places a second test mate (for the second-ranked
implementation file) from 8K (`e044_second_mate_8k`) or from 4K (`e044_second_mate_4k`). On the
full dev split (`E044-second-mate-dev`), a variant is a candidate if it passes the dev rule
(utility >= 0 at every budget, a significant fix or tests gain, no significant loss, unrounded
bounds); if both are, the one with the higher mean utility over the five budgets goes to
heldout-e. HE01 runs `npk_default` and that candidate on `heldout-e` (384 unused issues),
targets fix and tests, and promotes it only if utility `d_fix + 0.99 d_tests` >= 0 at every
budget, fix or tests gains significantly at one or more budgets, and no target loses
significantly at any budget.

**E044 outcome (2026-09-27): not sent to heldout-e.** On the full dev split the from-8K second
mate passes only narrowly (mean utility 0.08), and on the 197 dev issues outside dev-fast its
utility is negative (-0.9 / -0.7 at 8K / 16K). The declared plan would have run HE01; it was
deliberately skipped (a skipped confirmation can only prevent a promotion), so `heldout-e`
(384 issues) is still unused.
