# Next steps (handoff for the next agent)

Kept current during the autonomous research loop. Start here, then read
[BASELINE.md](BASELINE.md) and [experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## How to resume in five minutes

```bash
uv venv --python /usr/bin/python3.12 .venv && . .venv/bin/activate
uv pip install -e '.[dev,tokenizers]' numpy==2.2.6 psutil==7.0.0 urllib3==2.7.0 click==8.5.0 \
    tiktoken==0.12.0 safetensors==0.6.2 pyarrow transformers==4.57.6
uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest tests/ -q -p no:cacheprovider      # 1322 pass, 20 skip; tests/test_click_tasks.py (2 tests) needs a file not in this snapshot
export NPK_BENCH_HOME=~/npk-data                     # datasets, clones, packs (never committed)
python -m benchmarks.npkbench.run --split dev-fast --targets tests,docs --arms npk_default,npk_nodefs \
    --workers 4 --out experiments/npkbench/runs/<id>
python -m benchmarks.npkbench.report --compare RUN_A:ARM RUN_B:ARM   # paired bootstrap
python -m benchmarks.npkbench.report --judge RUN BASE_ARM CANDIDATE_ARM --targets tests,docs  # decision rule
python -m benchmarks.npkbench.report --judge-runs BASE_RUN:ARM CAND_RUN:ARM --targets tests   # across runs
```

Unused confirmation splits, declared on 2026-09-27 before any result on them: `gym-heldout-c`
(Python, 197; SWE-Gym, the next run of 30 per repository after `gym-heldout-b`) and `poly-heldout-c`
(JS/TS, 246). Spent: `gym-heldout` on E052 (GH01), `poly-heldout-b` on E053/E054 (PHB01), `heldout-e` on
E055b (HE01, failed) and `gym-heldout-b` on E058d (failed). Larger screening splits: `gym-dev` (Python,
326) and `poly-dev-b` (Java/JS/TS, 371; no longer an independent screen for suffix coverage after E058).
Declare each confirmation's criteria here before its run.

Queue many runs with `benchmarks/npkbench/queue_runner.sh` (a line per run in
`$NPK_BENCH_HOME/queue.txt`: `WORKDIR|ENV|ARGS`, see the script's header; start it with
`(nohup sh benchmarks/npkbench/queue_runner.sh >> $NPK_BENCH_HOME/queue.log 2>&1 &)`). The
container is parked while the session is idle (a wake-up finds `uptime` of minutes: the files are
back, the processes are not), so runs only progress while a session is active: restart the runner
at every wake-up and keep working or polling (`sleep` in bounded steps) while it runs. A run
interrupted that way resumes from `<out>.partial/journal.jsonl` (one fsynced line per finished
task) when the split, task list, arms, budgets, targets, loaded modules, interpreter and a digest
of the product, harness and loaded arm sources are unchanged, and is discarded (with the reason
printed) otherwise or under `--fresh`; tasks that recorded an error are run again. Partials made
by a harness without journals restart from scratch. The summary of a resumed run carries `resumes`
and `config.json` a `resumes` log (`tests/test_run_resume.py`).

First runs clone the 12 SWE-bench repositories (blobless, ~2 GB) and build packs
(~15 s each for Django). Use `--ephemeral-packs` on `heldout` (407 tasks) unless you
have ~20 GB free. Record every experiment with `benchmarks.npkbench.expdb.append`.

## Evidence discipline that must not be relaxed

- Contract mutations: 199 mutants, all killed at 81dc3a9
  (`experiments/npkbench/contract-mutations-81dc3a9.json`, with E059's five added to the
  194/194 at a81e2c6, which had E053's five, E054's two and E056's three on top of the
  184/184 at 4293b7f; before that 181/181 at 7cca1f3, 178/178 at
  c66ccca and 168/168 in `contract-mutations-3b5f9f5.json`, whose commit message misstates
  the added count as 13). Add a mutant for every new guard or ranking rule.

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
   `gym-heldout` (E052, GH01), `poly-heldout-b` (E053/E054, PHB01), `heldout-e` (E055b, HE01,
   failed). Unused: `gym-heldout-b` (Python, 254),
   `gym-heldout-c` (Python, 197) and `poly-heldout-c` (JS/TS, 246). Declare criteria here
   before any run on them.
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

### PHB01 outcome: E053 and E054 promoted together (poly-heldout-b now spent)

Both arms and the combination pass on `poly-heldout-b` (320 issues; control identical
1,600/1,600). E053: fix +1.83 / +2.50 / +3.30 / +2.63 / +2.74 at 1K-16K (all significant), tests
+2.22 / +1.77 / +1.10 / +2.13 at 2K-16K (significant), mean utility +4.14. E054: fix +1.18 /
+1.30 / +1.71 and tests +0.48 / +0.43 / +0.63 at 2K-8K (significant), mean +1.41. `e053_e054`:
fix +1.56 to +3.62 and tests +1.08 to +2.56, every cell significant, mean +4.72. The default on
`poly-heldout-b` finds 0.162 / 0.214 / 0.318 / 0.418 / 0.484 of fix hunks; with both changes
0.177 / 0.238 / 0.354 / 0.454 / 0.515. By repository (80 issues each), `e053_e054` gains fix
recall at every budget in material-ui (+1.2 to +5.8 points), prettier (+0.9 to +4.7) and svelte
(+2.0 to +5.1); serverless is flat (-0.8 / -1.7 at 1K / 2K, then +0.3 to +1.5) because the URL
rule changes only 2 of its 80 queries (one lost issue each at 1K and 2K: a nodejs.org docs link
and a short-link), so the gain is not one repository's. The product forms (local branch
`exp/e053-e054`) merged after they reproduced the prototypes' selections.

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

### E055b gym-dev outcome: candidate; HE01 runs on heldout-e (written before HE01 runs)

On `gym-dev` (326; control identical 1,630/1,630) `e055_frames_2k` passes the standard rule: fix
+0.61 / +0.66 / +0.48 / +0.41 at 2K-16K (significant at 4K), tests +0.10 / -0.21 at 8K / 16K
(not significant), utility >= 0 everywhere (mean +0.41); 1K is the default's by construction.
The ungated arms also pass here (`e055_frames` mean +0.57, `e055_frames3` +1.04) but are out by
their dev results. Per the plan, HE01 runs once on `heldout-e` (384 issues) with arms
`npk_default`, `e055_control` (must equal `npk_default`) and `e055_frames_2k`, targets fix and
tests; E055b is promoted only if it meets the standard rule there (utility `d_fix + 0.99 d_tests`
>= 0 at every budget, a significant fix or tests gain at one or more budgets, no significant loss
at any budget). HE01 runs on the current default, which now includes E053 and E054.

### HE01 outcome: E055b rejected (heldout-e now spent)

E055b did not replicate on `heldout-e` (384 fresh Python issues; control identical 1,920/1,920, 172
selections change): fix +0.00 / +0.32 / +0.06 / +0.30 / -0.04 at 1K-16K and tests +0.00 / -0.13 /
-0.18 / -0.18 / -0.39, none significant, utility -0.12 at 4K and -0.43 at 16K (mean -0.05). Its
dev and gym-dev gains (+1.5 at 4K on dev, +0.6 on gym-dev) came from splits on which the
opportunity had been measured and the channel shaped, which is why the plan reserved a fresh
split; the gate worked. The product form (branch `exp/e055p`) is not merged; its patch is saved in
`experiments/npkbench/runs/HE01-heldout-e/e055b-product.patch`. Traceback frames are not pursued
further (the existing lexical and definition channels already see the frame names; the extra
ranked blocks displace about as many sites as they add). The default on `heldout-e` (current
product, E053 + E054): fix 0.214 / 0.296 / 0.397 / 0.475 / 0.560, tests 0.110 / 0.212 / 0.278 /
0.357 / 0.437 at 1K-16K, a further fresh Python measurement of the default (SWE-bench full).

### E056 merged (latency; no recall change by construction)

Long weighted lexical queries (above 128 phrases) are scored one weight class at a time. The
product form selects identically to the default on all 1,500 dev and 1,630 gym-dev selections
(runs `E056p-lexical-split-dev` / `-gymdev`, each compared with the default's rows from the
preceding run on the same compiler) and on 586 of 586 offline rankings. Gym-dev median selection
time 99 -> 75 ms, p99 1.7 s -> 0.5 s. Two things to keep in mind: the VM restarts on idle gaps
(each restart killed the queue runner; restart it per the check-in prompt; a run now resumes
from its journal, see the queue paragraph above), and timing in runs made under concurrent load is indicative only (the
14.9 s outlier in the gym-dev run was a cold first call under contention; isolated, the same
selection takes 0.45 s against 1.9 s before E056).

### E057 outcome: rejected on both screens (gym-heldout-b stays unused)

Removing install and home-directory path prefixes from queries (61 of 300 dev and 57 of 326
gym-dev queries change; 114 of 1,500 and 133 of 1,630 selections) moves almost nothing: on `dev`
fix +0.00 / +0.33 / +0.00 / -0.17 / +0.00 and tests +0.34 / +0.00 / +0.00 / +0.51 / +0.34 at
1K-16K, none significant (mean utility +0.27); on `gym-dev` fix +0.00 everywhere and tests +0.10 /
+0.00 / +0.04 / -0.21 / +0.26, utility -0.21 at 8K (mean +0.04). The prefix words are common in
code and prose alike (low BM25 weight), so unlike template headings (E031), environment dumps
(E052) and link scaffolding (E053), which share vocabulary with docs and boilerplate files, they
do not pull a particular wrong file to the top. Do not retry without a new idea. Pasted
CLI output and logs without tracebacks were measured as well and are not worth a screen: only 21 of
300 dev, 20 of 326 gym-dev and 7 of 371 poly-dev-b queries have 20% or more of their terms on such
lines (median share 0.3-0.4), against 18-19% of queries changed by E057 for no effect. The
query-noise ideas that worked share a signature (the noise matches one wrong, non-code file
class); the remaining classes do not.

### Side condition SC01 for E053/E054 (declared before its result)

E053 and E054 were confirmed on JS/TS and screened on Python, but they are now the default for every
language, and SWE-bench Multilingual's Go, Rust, PHP, Ruby, C/C++ and Java repositories were not part
of any screen. SC01 runs the default on `ood-multi-dev` (186 issues, targets fix and tests) before
(worktree `np-e056p`, which has E056 but neither E053 nor E054; E056 selects identically) and after
the merge (current tree), compared with `report --judge-runs`. Action rule, declared now: if the
merged changes show a significant fix or tests loss at any budget, or utility below zero at any
budget, split the result by language and restrict the offending change (E054 to its prose file
types already; E053 to the hosts or languages where it loses) and re-run SC01; otherwise record it
as the side condition and keep both. R007 (`ood-multi-sample`, measurement only) is the
independent check of the same effect on 114 other multilingual issues.

### SC01 outcome: E053 + E054 are safe on the other languages (both stay)

On `ood-multi-dev` (186 issues) the merged default beats the pre-merge tree: fix +0.78 / +1.29 /
+1.22 / +1.66 / +1.33 points at 1K-16K (significant at 2K-8K), tests +0.29 / +0.88 / +0.29 / +0.00 /
-1.17 (not significant), utility >= 0 at every budget (mean +1.31); 452 of 930 selections change. No
language loses fix recall (PHP +3.2 to +4.3, Go up to +3.9, Rust up to +5.9, JS/TS up to +4.4, Ruby up
to +2.2, C/C++ +3.9 at 4K, Java unchanged); the one lost cell is a single changelog-only issue at 16K,
which E054 demotes by design. The declared action rule did not trigger. R006 (heldout, Python) and R007
(ood-multi-sample, 114 issues) agree: no loss, README tables refreshed.

### E053 + E054 merged

The combined product form reproduces the combined prototype (`e053_e054`) on all 1,475
selections of 295 cached packs (dev-fast, dev, gym-dev, poly-dev, poly-dev-b, ood-multi-dev,
five budgets each) and is the default since commit `042f8fa`. README and CURRENT_ARCHITECTURE
describe both; the README tables are re-measured as R006 (`heldout`) and R007
(`ood-multi-sample`).

### Pre-declared plan for E057 (install and home paths; written before any E057 result)

E057 (`e057_paths`, prototype `install_paths.py`) removes path prefixes that describe the
reporter's environment from the retrieval query, after the other cleaning and on every line but
the title: a prefix ending in `site-packages/` or `dist-packages/`, then a Python installation
prefix (`.../lib/python3.8/`), then a home-directory prefix (`/Users/<name>/`, `/home/<name>/`,
`C:\Users\<name>\`); package-relative paths such as `pandas/core/frame.py` stay. It changes 61
of 300 `dev` and 57 of 326 `gym-dev` queries (6 of 371 on `poly-dev-b`), where the prefix words
(`site`, `packages`, `lib`, `python3`, `local`, `usr`, `home`, `venv`, `envs`, user names) are a
median 10-11% of the analyzed terms and are repeated per traceback frame. It is screened on top
of the default that includes E053 and E054, on `dev` (fix, tests, docs) and `gym-dev` (fix,
tests), with the standard rule; it is a candidate if it passes on one screen and has utility
>= 0 at every budget and no significant loss on the other. A candidate is confirmed once on
`gym-heldout-b` (254 SWE-Gym issues) against `npk_default`, targets fix and tests, with the
standard rule; otherwise it is rejected and `gym-heldout-b` stays unused.

### Candidate idea (measured, not declared): quoted repository code as a channel

Issues often paste code; some of it is the project's own code, quoted where the reporter found
the problem. Lines inside code fences (at least 25 non-space characters, prompts and traceback
lines excluded) found verbatim in 1-3 source files at the base commit: `dev` 57 of 141 issues
with code quote repository code, 21 of them at a fix site (25 fix hunks; the default covers 16
at 1K and 2K, 22 at 4K); `gym-dev` 93 of 230, 30 at a fix site (41 hunks; 18 / 27 / 32 covered
at 1K / 2K / 4K). A channel ranking the blocks that contain such lines could recover some of
the missed sites but would add blocks for the ~60% of quoting issues whose quote is not at a
the missed sites but would add blocks for the ~60% of quoting issues whose quote is not at a
fix site (precision is lower than the traceback frames', whose channel did not replicate on
heldout-e, E055b); not declared, and unlikely to survive the same fresh-split test.

### D2 (2026-10-01, diagnostic only): term proximity adds nothing to BM25

BM25 scores query terms independently, so a block where several distinct query terms occur close
together might deserve a boost. On the 238 cached-pack tasks (dev-fast, gym-dev, poly-dev,
poly-dev-b, ood-multi-dev) whose lexical top 200 holds a gold block, ranking the candidates by the
largest number of distinct query terms inside a window of 24 or 60 analyzed tokens puts the first
gold block at median rank 22 / 20 against 9 for the lexical order (top 10: 93 / 92 against 123),
and RRF of the two orders is worse than the lexical order alone (better in 63 / 75 tasks, worse in
123 / 118). No channel is built. Data and script: `experiments/npkbench/diagnostics/D2-*`.

### D3 (2026-10-01, diagnostic only): file-level support adds nothing to block-level BM25

Do blocks of files with many lexical candidates deserve a boost? On the same 238 cached-pack tasks as
D2, ordering the lexical top 200 by file support (the sum of 1/(60+rank) over the file's
candidates) puts the first gold block at median rank 47 against 9 for the lexical order (top 10: 44
against 123); grouping files by their best candidate (file-first) is slightly worse (top 10: 104,
median 14), and RRF of either order with the lexical one is no better than the lexical order alone
(file-first: top 3 77 against 71, top 10 117 against 123, mean reciprocal rank 0.292 against 0.293;
better in 74 tasks, worse in 96). No channel is built. Data and script:
`experiments/npkbench/diagnostics/D3-*`.

### Coverage ceilings and the pre-declared plan for E058 (written 2026-10-01 before any E058 result)

Everything so far changed ranking. A different limit is what the scanner never indexes: it keeps a
whitelist of suffixes, skips any directory named `env`, `venv`, `dist`, `secrets` (and every dot
directory), and skips file names containing `credential` or `secret`. Gold hunks in files the
default scan cannot see are unfindable at any rank. Measured on the benchmark data (fix target, share
of hunks): dev and every SWE-bench held-out split 0%; gym-dev 0.5% (Cython `.pyx` 9, `env/` 1);
poly-dev 1.5%, poly-dev-b 1.7% (`.lock` 24), poly-heldout 4.1% (`.xml` 59), poly-heldout-b 1.9%
(`.lock` 17, credential-named source files such as serverless' 8); ood-multi-dev 4.0% (yacc `.y` 14 in
three jq issues, `env/` 7 in coreutils, `.neon`, `.feature`, `.l`, `.grammar`) and ood-multi-sample
2.8%. The tests target is hit much harder: Jest snapshots (`.snap`) are 37-58% of the test hunks of
poly-dev-b, poly-heldout and poly-heldout-b (prettier dominates), mypy's data-driven `.test` files
5.5% of gym-dev's and 17% of gym-heldout's, Redis' `.tcl` 14 and C++ `.cc` tests 9 hunks in
ood-multi-dev. So JS/TS test recall is capped near 42-62% of hunks before any ranking, and the numbers
in this repository for those splits understate real retrieval quality. Across the 66 benchmark
repositories the scanner skips 3,978 `.snap`, 2,046 `.mjs`, 605 `.test`, 402 `.tcl`, 90 `.pyx`
files, among others; a directory named `env` (coreutils' `src/uu/env/`) drops a real source tree
without a trace in `skipped_sources`.

E058 indexes the authored source and test types with evidence, and keeps `env`/`venv` directories
unless they are virtualenvs (`pyvenv.cfg` or an `activate` script). Prototype: the compile option
`suffix_profile` in worktree `np-e058` (a different fingerprint per profile, so one run compares them
as arms). Arms: `e058_core` (C++ `.cc .cxx .hh .hxx .ipp .inl`, `.mjs .cjs .mts .cts`, `.vue .svelte`,
Cython `.pyx .pxd .pxi`, yacc/lex `.y .l`, `.tcl`, `.proto`, plus the `env`/`venv` rule),
`e058_core_test` (adds `.test`) and `e058_core_test_snap` (adds `.snap`), against `npk_default` of the
same tree. The credential-name rule is not touched: it is a security policy for the maintainers (a
source file called `credentials.js` is dropped today; the content scan would still catch recognized
key formats), recorded here as an open policy question. `e058_core_test_snap` is informational and
not promotable: whether committed snapshots belong in a context pack is a product decision, the
effect cannot be confirmed on a fresh prettier-heavy split (poly-heldout-c has 6 prettier issues), and
a tests gain driven by it would be exactly the artifact the benchmark must not reward; its results
are reported with and without `.snap` hunks.
Screens (targets fix and tests; docs on dev-fast): `gym-dev`, `ood-multi-dev`, `poly-dev-b` and
`dev-fast` (sanity). `e058_core` or `e058_core_test` is a candidate if it passes the standard rule on
at least one of the first three screens and has utility >= 0 at every budget and no significant loss
on the others and on dev-fast; with two candidates, the higher mean utility over the three screens
goes on (ties: `e058_core`). The candidate is confirmed once on `gym-heldout-b` (Python: mypy
`.test`, pandas `.pyx`) and once on `poly-heldout-c` (JS/TS: `.mjs .cjs .vue .svelte`), each against
`npk_default`, targets fix and tests, and is promoted only if utility is >= 0 at every budget on both,
neither shows a significant loss, and at least one shows a significant fix or tests gain. The
multilingual-only suffixes (`.cc .cxx .hh .hxx .ipp .inl .y .l .tcl`) have no fresh split;
`ood-multi-sample` is the guard (measurement, as R005/R007): a significant fix or tests loss at any
budget drops those suffixes and amends the README's "never used for decisions" sentence. If no variant
is a candidate, nothing is merged and the three unused splits stay unused. The coverage numbers above
stay in the documentation either way.

### E058 multilingual screen and E058b (declared before E058b's results and before the gym-dev and poly-dev-b results)

On `ood-multi-dev` (186 issues; `dev-fast` was identical in 510 of 515 selections, recall unchanged)
`e058_core` lifts regression-test recall by +3.8 / +4.5 / +5.7 / +6.6 / +6.9 points at 1K-16K (all
significant) and `e058_core_test` by up to +7.5, but fix recall moves -1.1 / -0.8 / -0.9 / -1.3 /
-1.4 (the 16K cell is significant by its unrounded bound, upper limit -0.00), so by the declared rule
neither passes this screen (utility +2.7 to +6.0, mean +4.4 / +4.6; the snapshot arm also loses fix
at 8K and 16K). By repository the picture separates cleanly: fmt (8 issues, C++ tests in `.cc`)
gains +50 to +62 test points with no fix change; prometheus (`.test`) +10 to +20 test points
at 2K-16K; coreutils (`env/`) +6.3 fix points; jq (`.y`) +0.7 to +0.9; and all of the fix loss
is redis (9 issues: fix -28 to -29 points at 8K-16K, three issues lose every fix hunk at 16K)
where its Tcl test windows now outrank the C implementation, while redis tests gain +17 to +64 points.
That is the transfer the rule exists to catch, and Tcl is left out unless it passes on its own.
E058b adds the arms `e058_notcl` and `e058_notcl_test` (the same two profiles without `.tcl`),
screened on `ood-multi-dev` only (no Python or JS split contains Tcl files). The candidate set is
`e058_core`, `e058_core_test`, `e058_notcl`, `e058_notcl_test`; the rule of the E058 plan applies to
all of them unchanged on every screen (gym-dev and poly-dev-b results for the first two are still
pending), and among candidates the highest mean utility over the screens wins, ties going to the
fewest suffixes. The confirmation splits and the multilingual guard stay as declared.

### E058 state (2026-10-01, written while poly-dev-b runs)

Screens done (worktree `np-e058`, branch `exp/e058`, commit `2bb5cb1`; do not edit its compiler sources
while runs are pending there, the harness flags a changed fingerprint): `dev-fast` (identical in 510 of
515 selections, no recall change), `ood-multi-dev` (`e058_core`/`e058_core_test` fail on redis' Tcl, see
above), `E058b-coverage-multidev` (`e058_notcl`: tests +2.3 to +2.9 significant at every budget, fix
-0.06 to +0.55, mean utility +2.79, passes; `e058_notcl_test`: tests +2.3 to +3.5 significant, fix
-0.06 to +0.44, mean +3.05, passes) and `E058-coverage-gymdev` (`e058_core_test`: tests +0.3 / +0.3 /
+0.9 / +0.9 / +2.2, significant at 2K, 4K, 16K, fix -0.9 to +0.5 not significant, mean +0.79, passes;
`e058_core` alone neutral, so the gain is mypy's `.test` files). No gym-dev or poly-dev-b tree
contains a `.tcl` file, so `e058_notcl_test` equals `e058_core_test` there. `E058-coverage-polydevb` has since
finished and the candidate fails it: see the next section. The plan below is kept as declared. If `e058_notcl_test` has
utility >= 0 at every budget and no significant loss there, it is the candidate (highest mean utility)
and the next steps, all declared above, are: (1) runs `E058-confirm-gymheldoutb` (split
`gym-heldout-b`) and `E058-confirm-polyheldoutc` (split `poly-heldout-c`), arms `npk_default` and
`e058_notcl_test` in worktree `np-e058`, targets fix and tests; (2) guard run on `ood-multi-sample`
with the same two arms; (3) judge with `report --judge` and the declared promotion rule; (4) only then
cherry-pick the product form (worktree `np-e058p`, branch `exp/e058p`, commit `5e41c87`: suffixes baked
into `TEXT_SUFFIXES`, env/venv virtualenv detection, `tests/test_source_coverage.py`, eight mutants all
killed) onto the PR branch, prove default selections equal the prototype arm's on the screens, refresh
the mutation evidence and the README/architecture text. If poly-dev-b shows a significant loss or
negative utility for the JS/TS part, drop the offending suffixes by a newly declared variant instead
of promoting. The snapshot arm is reported with and without `.snap` hunks (`snap_split.py` logic) and
is never promoted.

### E058 poly-dev-b result: the declared candidate fails; E058c declared (2026-10-01, before any E058c run)

`E058-coverage-polydevb` (371 issues, tests and fix; run in worktree `np-e058r`, same compiler sources
as `np-e058`). `e058_core` and `e058_core_test` select identically here (no `.test` or `.tcl` files) and
fail the rule: fix -0.13 / -0.02 / -0.20 / -0.25 / -0.73 points at 1K-16K (significant losses at 8K,
upper bound -0.02, and 16K, [-1.32, -0.26]), tests -0.56 / +0.16 / -0.03 / -0.06 / -0.39 (nothing
significant), utility -0.69 / +0.13 / -0.23 / -0.31 / -1.12 (mean -0.44). So `e058_notcl_test`, which
equals `e058_core_test` here, is not a candidate and nothing is promoted as declared. The informational
snapshot arm shows the usual transfer: tests +0.11 / +1.09 / +1.29 / +2.06 / +2.50 (significant from 2K) for
fix -0.73 / -0.78 / -1.19 / -1.54 / -0.66 (significant at 2K-8K), mean utility +0.42; split by hunk class
(`experiments/npkbench/diagnostics/E058-snap-split.*`) it finds 0.05-0.30 of the 646 `.snap` hunks of 42
issues (0 without it) and loses 0.3-1.1 points on the 1,105 other test hunks. It stays out.

Where the loss comes from (selection diff of `e058_core_test` against the default, script
`experiments/npkbench/diagnostics/E058-suffix-attribution.py`): the newly selected spans are almost all `.svelte` (104 / 186 / 305 /
504 / 544 spans at 1K-16K; every one in sveltejs/svelte, 67 issues, whose repository holds thousands of
`.svelte` test fixtures) and `.vue` (26-75; prettier's fixtures, 66 issues), with no fix-site hunk among
them; the 9 issues that lose fix recall at 16K (-2.71 in total, none gains) have `.svelte` blocks among
their added spans in 7. Every other new suffix adds at most 10 spans per budget. The benchmark has no
repository that authors application code in single-file components, so their benefit is untested here
and their cost is measured.

E058c, declared now: the profile `core_nosfc_test` = `core_notcl_test` without `.vue` and `.svelte`,
i.e. C++ `.cc .cxx .hh .hxx .ipp .inl`, `.mjs .cjs .mts .cts`, Cython `.pyx .pxd .pxi`, yacc/lex `.y .l`,
`.proto` and `.test`, plus the env/venv rule; arm `e058_c`. No `.tcl` (E058b), no single-file components
(this result), no `.snap` (policy and transfer). Facts checked before the declaration (git ls-tree of every
task's base commit): `dev-fast`, `heldout`, `gym-dev` and `gym-heldout-b` contain no `.vue`, `.svelte` or `.tcl`
file, so `e058_c` selects there exactly as `e058_notcl_test` and the earlier results on `dev-fast`
(identical in 510 of 515 selections, no recall change) and `gym-dev` (`e058_core_test` passes, mean utility
+0.79) are its results; a 20-issue `gym-dev` re-run checks the identity. Files with the removed suffixes
exist in `ood-multi-dev` (bat, vuejs/core, babel: 7 issues), `poly-dev-b` (svelte 67, prettier 66, tailwindcss 1),
`poly-heldout-c` (svelte 66, prettier 6) and `ood-multi-sample` (bat, vuejs/core, babel: 7 issues).
Screens to run, arm `e058_c` against the default arm of the earlier run (`report --judge-runs`):
`E058c-coverage-polydevb` and `E058c-coverage-multidev`. It is a candidate iff on both screens utility is >= 0
at every budget and there is no significant loss (the standard-rule pass was established on `gym-dev`).
Then, as declared for E058 and unchanged: `E058c-confirm-gymheldoutb` (split `gym-heldout-b`) and
`E058c-confirm-polyheldoutc` (split `poly-heldout-c`), arms `npk_default` and `e058_c`, targets fix and tests,
promotion only if utility >= 0 at every budget on both, no significant loss on either and at least one
significant fix or tests gain; and the guard `E058c-guard-multisample` on `ood-multi-sample` (arms
`npk_default`, `e058_c`, and the chunk baselines on both kinds of pack, `b002_bm25_chars1000_split` and
`b003_bm25_chars1000_split_e058c`): a significant fix or tests loss at any budget drops the multilingual-only
suffixes (`.cc .cxx .hh .hxx .ipp .inl .y .l`). poly-dev-b is no longer an independent screen for this
variant (the suffixes were removed because of it); the fresh confirmations are. If a screen fails, nothing
is merged and `gym-heldout-c` stays unused either way.

### E058c result and E058d declared (2026-10-01, before any E058d run)

E058c (profile `core_nosfc_test`, arm `e058_c`): a 20-issue gym-dev re-run selects exactly as
`e058_core_test` (195 of 195 cells, `E058c-identity-gymdev20`). `ood-multi-dev` passes: tests +2.34 /
+2.63 / +3.22 / +3.22 / +3.51 (significant at every budget), fix +0.00 / +0.44 / -0.02 / +0.03 / +0.07,
utility +2.32 / +3.05 / +3.17 / +3.22 / +3.54 (mean +3.06). `poly-dev-b` does not: utility +0.02 / -0.05
/ +0.00 / +0.00 / -0.42 (mean -0.09; fix -0.07 and tests -0.35 at 16K, which is one issue's test hunk, CI
[-1.06, +0.00]; no significant loss), negative at 2K and 16K, so by the declared rule E058c is not a
candidate. Nothing is promoted. What the screens say about each suffix group, summed over the five
budgets, as gold hunks covered by newly selected spans (`E058-suffix-attribution.py` on every screen):
`.test` 48 test hunks (mypy 43, prometheus 5), C++ `.cc` 23 test hunks (fmt), yacc `.y` 10 fix hunks (jq);
Cython 26 spans, protobuf 21, JS/TS modules (`.mjs .cjs .cts`) 120 spans and `.vue`/`.svelte` 1,930 spans
cover no fix hunk anywhere (the svelte fixtures cover 12 test hunks at a large cost, above). The JS/TS
module, Cython and protobuf suffixes therefore have no measured benefit on any screen and a small measured
cost on the only JS/TS screen. Principle from here on: a suffix group is indexed only if its newly
selected spans covered gold on some screen and the group shows no measured loss; the rest stay a
documented, untested coverage gap (an application written in `.mjs` or `.vue` has no indexed source today).

E058d, declared now: the profile `core_min_test` = C++ `.cc .cxx .hh .hxx .ipp .inl`, yacc/lex `.y .l` and
`.test`, plus the env/venv rule; arm `e058_d`. This is a pure subset of E058c and of every earlier candidate,
chosen by the principle above. It is a post-hoc choice on screens that already informed three variants, so
the screens are no longer independent evidence for it (poly-dev-b in particular); the fresh confirmations
are, and they keep the rule as declared. Trees containing files of the kept suffixes (git ls-tree of every
base commit): `dev-fast` astropy `.l` (2 issues), `gym-dev` mypy (30), `ood-multi-dev` fmt, jq, prometheus,
php-cs-fixer, coreutils, micropython (8 + 11 + 21 issues carry `.cc`, `.y`/`.l`, `.test`), `poly-dev-b`
coder/code-server `.cc` (2), `gym-heldout-b` mypy (30), `poly-heldout-c` none, `ood-multi-sample` fmt, jq,
prometheus and `.test` repositories, `heldout` astropy `.l` (18) and `.cxx` (4). Elsewhere `e058_d`
selects exactly as the default (the env/venv rule apart, which the screens include).
Screens, arm `e058_d` against the default arm of the earlier run of the same split (`report --judge-runs`):
`E058d-coverage-devfast` (targets tests and docs), `E058d-coverage-multidev`, `E058d-coverage-gymdev`
and `E058d-coverage-polydevb`. E058d is a candidate iff on all four utility is >= 0 at every budget and
there is no significant loss, and it passes the standard rule on at least one. Then, unchanged from E058:
`E058d-confirm-gymheldoutb` and `E058d-confirm-polyheldoutc` (arms `npk_default` and `e058_d`, targets fix
and tests; promotion only if utility >= 0 at every budget on both, no significant loss on either and at
least one significant fix or tests gain; `poly-heldout-c` holds none of the kept suffixes, so it can only
show that nothing else changes) and the guard `E058d-guard-multisample` on `ood-multi-sample` (arms
`npk_default`, `e058_d`, `b002_bm25_chars1000_split` and `b003_bm25_chars1000_split_e058d` on the same
packs): a significant fix or tests loss at any budget drops the multilingual-only suffixes. After
promotion the README's SWE-bench table is re-measured (`heldout` has astropy `.l`/`.cxx` files).
If a screen fails, nothing is merged; `gym-heldout-c` stays unused either way.

### E058d screens passed; the poly-heldout-c confirmation is replaced by an identity proof (2026-10-01, before the confirmation runs)

Screens (arm `e058_d` against the default arm of the earlier run of each split; all four runs have
`errors: 0` and stable fingerprints): `E058d-coverage-gymdev` passes (tests +0.13 / +0.30 / +0.91 / +0.98 /
+2.21, significant at 2K, 4K and 16K; fix -0.11 / -0.18 / +0.15 / +0.50 / -0.94, none significant; utility
+0.02 / +0.11 / +1.06 / +1.47 / +1.25, mean +0.78); `E058d-coverage-multidev` passes (tests +2.34 / +2.63 /
+3.22 / +3.22 / +3.51, significant at every budget; fix +0.00 / +0.44 / +0.06 / +0.03 / +0.10; utility mean
+3.08); `E058d-coverage-devfast` is identical to the default in every cell (utility 0 at every budget; the
`.l` files of astropy do not reach a selection); `E058d-coverage-polydevb` is identical but for one `.java`
span without gold (utility 0.00 at every budget). So `e058_d` meets the declared candidate rule.

The confirmation on `poly-heldout-c` is not run. Every file the profile adds or the env/venv rule
unlocks would have to exist in a base tree of the split for the profile to change a pack, and none does:
`git ls-tree` of the 246 base commits holds no `.cc .cxx .hh .hxx .ipp .inl .y .l .test` file and no
directory named `env` or `venv` (script `experiments/npkbench/diagnostics/E058-inventory.py`). The scan is
then identical, the packs and selections are identical, and the declared conditions (utility >= 0 at
every budget, no significant loss) hold with equality; running it would only spend a fresh JS/TS split on
a certain zero. It stays unused. The confirmation that can show a change is `gym-heldout-b` (mypy's 30
issues carry `.cc` and `.test` files; conan, hydra and mypy's typeshed carry `env`/`venv` directories in 45
issues): run `E058d-confirm-gymheldoutb`, arms `npk_default` and `e058_d`, targets fix and tests. Promotion
needs utility >= 0 at every budget there, no significant loss, and a significant fix or tests gain. The
guard `E058d-guard-multisample` runs as declared above.

### E058 outcome: rejected as a whole (2026-10-01)

`E058d-confirm-gymheldoutb` (254 fresh issues, arms `npk_default` and `e058_d`) fails the declared
promotion rule. Regression-test recall rises +0.96 / +1.35 / +2.26 / +2.27 / +3.02 points at 1K-16K
(significant at every budget) but fix recall falls -0.63 / -1.01 / -0.19 / -0.76 / -0.56, significantly at
2K, 8K and 16K (utility +0.32 / +0.33 / +2.04 / +1.49 / +2.43, mean +1.32, so the loss is what fails it).
All of it is mypy: 15 of its 30 issues change (fix -5.3 / -8.6 / -1.6 / -6.4 / -4.7 points, tests +8.3 /
+11.8 / +19.6 / +19.8 / +26.2) and the other 224 issues select exactly as the default, including conan and
hydra, whose `env` directories the profile unlocks. Every issue that loses fix recall at 8K has `.test`
spans among its added ones (6 of 6; 5 of 5 at 16K): mypy's data-driven `check-*.test` files hold its
regression tests and also match issue text well enough to displace the fix blocks, the same transfer
between targets as in the other rejected experiments. The gym-dev screen had shown it only as a
non-significant fix change (-0.9 to +0.5); the fresh split caught it, as in E055b.
The multilingual guard `E058d-guard-multisample` (114 issues, same arms plus the chunk baselines on both kinds
of pack) shows no significant effect either way: tests +0.47 / +0.00 / +1.42 / +1.89 / +1.89, fix -0.05 /
-0.05 / +0.00 / -0.44 / -0.14 (all intervals reach zero), recall 0.202 / 0.258 / 0.312 / 0.367 / 0.466 against
0.202 / 0.258 / 0.312 / 0.372 / 0.468 for the default; the baseline gains at most 0.1 point from the new
files, so the README's ratios are unchanged. Nothing from E058 enters the default scan except what E059
below carries. The three confirmation splits: `gym-heldout-b` is spent on E058d; `poly-heldout-c` and
`gym-heldout-c` stay unused.

What E058 established, for whoever decides these product questions (none changes a default):
mypy-style data-driven test files (`.test`) trade fix for test recall (+1 to +3 tests, -0.2 to -1.0
fix on fresh issues; a candidate for a caller-declared option, not a default); the C++ `.cc` family and
yacc/lex files recover test and fix hunks in fmt and jq (multilingual dev) with no measured cost, but
fresh multilingual issues are too few to confirm it; single-file components (`.vue`, `.svelte`) cost fix
recall where component fixtures abound (sveltejs/svelte, prettier: -0.7 points at 16K on 371 issues);
Tcl moves Redis' fix sites out of reach; Jest snapshots move recall from other test hunks to snapshot
hunks (the 646 snapshot hunks of poly-dev-b: 0.05-0.30 found with them, 0 without; the 1,105 other test
hunks lose 0.3-1.1 points); ES-module JS, Cython and protobuf files covered no gold on any screen. An
application written only in those types has no indexed source today, and the compile output does not say
so: reporting the counts of unindexed files by suffix (and by skipped directory name) in the compile
stats, plus a caller-declared include list, would make the gap visible without touching a default.
The credential-name rule (a file called `credentials.js` is dropped) is untouched, as before.

### E059 (declared 2026-10-01, before any E059 run): keep real source directories named env or venv

One part of E058 is a correctness fix rather than a ranking change: the scan skips every directory named
`env`, `venv`, `dist` or `secrets`, so a source package called `env` (conan's `conan/tools/env`, hydra's
`conf/hydra/env`, coreutils' `src/uu/env`, nushell's `nu-command/src/env`, trino's `.../launcher/env`) vanishes
from the pack without a trace. The change: `env` and `venv` are skipped only when they are virtualenvs (a
`pyvenv.cfg`, `bin/activate` or `Scripts/activate` inside); the suffix whitelist is unchanged (profile
`env_only`, arm `e059_env`). It changes packs only where such a directory exists (inventory of the base
commits: `gym-dev` 75 issues, `gym-heldout-b` 45, `poly-dev-b` 12, `ood-multi-dev` 11, `ood-multi-sample` 12;
`dev-fast`, `heldout`, `poly-heldout-c` none), so the evidence is gathered on those issues only (arm `e059_env`
on the affected repositories of each split, `--repos`; the other tasks are identical by construction) and
compared with the default arm of the earlier run of the same split (`report --judge-runs`, which pairs the
tasks present in both). Standard, declared as such: this is a harm check on a bug fix, in the class of E004
and E056, not a gain test on ranking, so there is no significant-gain requirement. Accepted iff on every one
of the five splits utility is >= 0 at every budget and there is no significant loss on any target, and at
least one repository recovers fix or tests hunks it could not reach (coreutils in `ood-multi-dev` did in the
E058 arms: fix +6.3 points on its issues). The fresh-split condition is met by `gym-heldout-b` (45 issues
that were not used for any decision before E058d) and `ood-multi-sample`. If any split fails, nothing is
merged. After acceptance the product form is `_excluded_dir` (worktree `np-e058p`), proved equal to
`e059_env` on these issues, with its four mutants, and the README/architecture text records the change.

### E059 result: accepted (2026-10-01)

The harm check (arm `e059_env` on the affected repositories of each split, `report --judge`/`--judge-runs`
against the default arm of the earlier run; script and output `experiments/npkbench/diagnostics/E059-harm-check.*`)
passes on all five splits: utility >= 0 at every budget and no significant loss everywhere. The rule
changes selections in very few issues, all of them gains: `gym-dev` conan, 2 of 30 issues, fix +3.67 /
+3.33 / +3.33 points at 4K / 8K / 16K (split level +1.22 / +1.11 / +1.11, intervals reach zero; its
`conan/tools/env/` package was invisible); `ood-multi-dev` coreutils, 1 of 2 issues, fix +6.25 points from 4K
(split level +1.14, `src/uu/env/`). Everything else is exactly equal to the default: `gym-heldout-b` (conan,
hydra, mypy's typeshed `venv`: 51 issues), `poly-dev-b` (dubbo, code-server, trino: 33), `ood-multi-sample`
(ruff, axios, nushell, coreutils: 12). The change is therefore a bug fix with no measured cost and two
recovered fix hunks, accepted under the standard declared for it (a harm check, no significant-gain
requirement). Product form: `_excluded_dir` (`npk/pack/compile.py`), `tests/test_source_directories.py`,
five mutants, and the selection-equality proof below.

### D4 and the declared E060 plan: the ends of the test mate's file (2026-10-01, before any E060 run)

Regression-test recall is the weakest target and mostly a within-file problem: on the 405 held-out
issues of R006 the correct test *file* is reached for 58% of issues at 4K but a test *hunk* for 27%
(fix: 68% against 47%), and the median cost to the first test hunk is 12.4K tokens against 3.7K for fix.
D4 (`experiments/npkbench/diagnostics/D4-test-mate.*`, 278 cached-pack tasks with test gold from
dev-fast, gym-dev, poly-dev, poly-dev-b and ood-multi-dev) looks at the test mate: its block is small
(median 191 tokens, p90 904, never above 1,449) and fits the budget from 2K, so size is not the
limit. The mate's file is a gold test file in 28% of tasks (77 of 278) and the mate block covers a gold
hunk in 11% of tasks, 40% of the cases where the file is right. In the 46 tasks where the file is
right and the block wrong, the covering block is the last block of the file in 15 (33%; last two 37%,
last three 43%) and the first block in 8 (17%): relative position by quintile 13 / 6 / 4 / 6 / 17.
Regression tests are appended at the end of a test file and their imports edited at the top, which no
ranking over query terms can see. A tail block and a head block of the mate's file could therefore
recover up to 5.4% and 2.9% of tasks' test hunks at the price of two small blocks of budget.

E060 prototype (`benchmarks/npkbench/prototypes/mate_ends.py`; selection-time only, no compile change):
right after the test mate, place the last block of the mate's file (`tail`) and optionally its first
block (`head`) from a budget threshold, everything else as the product. Arms: `e060_control` (threshold
never reached: must equal `npk_default` on every selection), `e060_tail_2k`, `e060_tail_4k`,
`e060_tail_8k` and `e060_headtail_4k`. Screens (targets fix and tests; docs on dev): `dev` (300),
`gym-dev` (326), `poly-dev-b` (371) and `ood-multi-dev` (186). An arm is a candidate iff on every screen
utility is >= 0 at every budget and there is no significant loss, and it passes the standard rule on at
least one screen; among candidates the highest mean utility over the four screens wins (ties: the
higher threshold, then fewer blocks). Confirmation, once each and declared now: `gym-heldout-c` (Python,
197) and `poly-heldout-c` (JS/TS, 246), arms `npk_default` and the candidate, targets fix and tests;
promotion iff utility >= 0 at every budget on both, no significant loss on either, and a significant
fix or tests gain on at least one. If no arm is a candidate nothing is merged and both splits stay unused.

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
