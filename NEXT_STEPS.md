# Next steps (handoff for the next agent)

Kept current during the autonomous research loop. Start here, then read
[BASELINE.md](BASELINE.md) and [experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## How to resume in five minutes

```bash
uv venv --python /usr/bin/python3.12 .venv && . .venv/bin/activate
uv pip install -e '.[dev,tokenizers]' numpy==2.2.6 psutil==7.0.0 urllib3==2.7.0 click==8.5.0 \
    tiktoken==0.12.0 safetensors==0.6.2 pyarrow transformers==4.57.6
uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest tests/ -q -p no:cacheprovider      # 1261 pass, 20 skip; one test needs a file not in this snapshot
export NPK_BENCH_HOME=~/npk-data                     # datasets, clones, packs (never committed)
python -m benchmarks.npkbench.run --split dev-fast --targets tests,docs --arms npk_default,npk_nodefs \
    --workers 4 --out experiments/npkbench/runs/<id>
python -m benchmarks.npkbench.report --compare RUN_A:ARM RUN_B:ARM   # paired bootstrap
```

First runs clone the 12 SWE-bench repositories (blobless, ~2 GB) and build packs
(~15 s each for Django). Use `--ephemeral-packs` on `heldout` (407 tasks) unless you
have ~20 GB free. Record every experiment with `benchmarks.npkbench.expdb.append`.

## Evidence discipline that must not be relaxed

- Contract mutations: 176 mutants. The 168 at 3b5f9f5 (159 at the base commit plus 9 added
  in this loop for source-policy skips, the definition channel, top-block trimming and the
  test mate) are all killed (`experiments/npkbench/contract-mutations-3b5f9f5.json`; commit
  8eb6b27 misstates the added count as 13); `test_mate_gate_ignored` (E016c), the three
  query-cleaning mutants (E031) and the four weighting mutants (E039) were killed when added
  (176 in total). Add a mutant for every new guard or ranking rule.

- Decide on `dev`/`dev-fast`; confirm once on `heldout`; never tune on `heldout`.
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

Where the product stands (held-out, 407 issues, run R002): fix-site recall
0.254/0.346/0.452/0.571/0.638 at 1K-16K and regression-test recall 0.089/0.180/0.252/0.338/0.423,
2.0-2.5x (fix) and 1.5-2.1x (tests) a standard BM25-over-chunks RAG baseline (B001); the
documentation gap to that baseline is no longer significant. Before E031/E039 the product
scored 0.230/0.303/0.385/0.472/0.569 (fix). Code-first ranking was confirmed on six unseen
repositories (O001). Opt-in modes: context map (E017), semantic/hybrid for chat histories
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
5. **Held-out split hygiene:** `heldout` confirmed E002, E005c, E016b and E017; `heldout-b`
   confirmed E016c (HB01); `heldout-c` is spent on E031 (HC01, passed). `heldout-d` (401 issues, a fixed
   stratified sample of the 785 unused issues of `heldout-b-all`) was declared on
   2026-09-27 before any result on it; declare the criteria in this file before running it.
8. **Open engineering item: very long queries.** Distinct lexical terms per issue: median
   62-82, p99 300-466, but up to 4,164 (pydata__xarray-5662, 57K characters) and 1,506 on the
   multilingual split. `bm25()` cost grows with terms and matching rows, and E039's repeats
   multiply it: synthetic Django queries of 1,000 / 20,000 random identifiers take 3.2 / 34 s
   unweighted and 8.4 / 114 s weighted (4K budget); the real 4,164-term xarray issue takes
   1.5 s unweighted and 2.0 s weighted. A cap of about 512 distinct terms (keeping title terms
   and terms by first occurrence) would bound the worst case and changes only 2 dev, 0
   held-out, 7 heldout-b-all and 2 multilingual queries; evaluate it as a robustness change
   (identical selections below the cap, recall on the capped queries, latency bound).
7. **Where ranking still fails (E039 default, dev-fast, full fused ranking):** the first gold
   block is ranked first in 38 of 103 issues, in the top 3 in 45, top 10 in 59, top 50 in 78;
   in 24 issues no candidate covers a gold hunk at all (the gold block is outside every
   channel's top 60, and a larger candidate limit did not help, E026). The top block is in a
   gold file for 57 issues. Candidates that are not the fix but outrank it are mostly other
   code (15) or other blocks of the right file (16); tests (8) and docs (2) are rare.
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
a gold file); git co-change history for the test mate (the test file that most often
changed with the top implementation file in the 3,000 commits before the base is a gold
test file in 35/103 dev-fast issues, vs 36 for path mirroring and 49 for mirror plus lexical
rank; 52 vs 50 when given the true fix file), so it does not justify adding history to packs;
promoting the top file's next block right after the top block at small budgets (simulated
on the E039 default, dev-fast: it would lift a gold block to rank 1 in 7 issues but push a
gold block from another file down in about 10); compositional name matches (a definition such as `_print_Product` whose name parts all occur
in the issue and include a code name it mentions: 13 of 153 dev-fast fix hunks covered, 6 of
them missed at 4K, about 13 candidate blocks per issue, so at most a few hunks);
skipping per-file `realpath` in scans (a test pins resolution-before-read,
which matters for Windows reparse points; saving ~0.3 s per Django update).

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
The diagnosis below predates those changes. Diagnosis on
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
