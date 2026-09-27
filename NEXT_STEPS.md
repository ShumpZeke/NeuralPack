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

- Contract mutations: 169 mutants. The 168 at 3b5f9f5 (159 at the base commit plus 9 added
  in this loop for source-policy skips, the definition channel, top-block trimming and the
  test mate) are all killed (`experiments/npkbench/contract-mutations-3b5f9f5.json`; commit
  8eb6b27 misstates the added count as 13); `test_mate_gate_ignored` (E016c) was killed when
  added. Add a mutant for every new guard or ranking rule.

- Decide on `dev`/`dev-fast`; confirm once on `heldout`; never tune on `heldout`.
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

Where the product stands (held-out, 407 issues): fix-site recall 0.230/0.303/0.385/0.472/0.569
at 1K-16K with the default budget-gated test mate (0.230/0.309/0.399/0.475/0.575 without it),
1.6-2.1x a standard BM25-over-chunks RAG baseline (B001/B002), confirmed on six unseen
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
   confirmed E016c (HB01); `heldout-c` is spent on E031 (HC01). 785 issues of
   `heldout-b-all` remain unused (271 Django, 127 SymPy, 91 scikit-learn, ...); declare a
   `heldout-d` from them in `data.split` and its criteria in this file before the next
   confirmation.
6. **E034 (in progress): weight the issue title's terms in the lexical channel.** The
   channel deduplicates query terms, so the title (the author's own summary) counts no more
   than a traceback or template word. Prototype `prototypes/title_weight.py` repeats title
   terms in the FTS5 MATCH (bm25 sums repeated phrases); the x1 control reproduces the
   product on 90/90 cached selections. Screen on dev-fast, then dev; held-out only if dev
   passes the rule.

Measured non-opportunities (do not re-run without a new idea): vendored code (`deps/`, `vendor/`, `third_party/`: no gold hunk in 2,360 across dev, held-out and multilingual dev; only 0.2-1.2% of selected lines at 2K, so demoting it cannot pay for the scope change); a traceback-frame channel
(the 7 dev-fast tasks whose traceback names a gold file already score 0.86-0.93 from 1K);
module-path mentions (the product already selects the named gold file at 2K in 15 of 20
cases); an error-message phrase channel (3 of 103 issues quote a message found verbatim in
a gold file); git co-change history for the test mate (the test file that most often
changed with the top implementation file in the 3,000 commits before the base is a gold
test file in 35/103 dev-fast issues, vs 36 for path mirroring and 49 for mirror plus lexical
rank; 52 vs 50 when given the true fix file), so it does not justify adding history to packs;
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
(fix +8 to +15 points on the measurement sample) and the definition channel helps, but
absolute recall is about half of Python's (0.164 vs 0.303 at 2K). Diagnosis on
`ood-multi-dev` only: the loss is ranking, not packing (fix sites rank at median 112-401;
window trimming for non-Python blocks, E030, changed nothing). C/C++, JS/TS and Rust are
weakest (3-4% of gold hunks selected at 2K). JS issues' budgets go to CONTRIBUTING.md,
README.md and changelogs, a symptom of issue-template words; E031 (strip template
headings, checklists and HTML comments from the query) is positive but not yet
significant on multilingual dev; on the full Python dev split (E031b) it passed the rule
narrowly and is being confirmed on `heldout-c` (HC01). Two structural ideas were tried on
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
