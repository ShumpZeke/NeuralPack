# Next steps (handoff for the next agent)

Kept current during the autonomous research loop. Start here, then read
[BASELINE.md](BASELINE.md) and [experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## How to resume in five minutes

```bash
uv venv --python /usr/bin/python3.12 .venv && . .venv/bin/activate
uv pip install -e '.[dev,tokenizers]' numpy==2.2.6 psutil==7.0.0 urllib3==2.7.0 click==8.5.0 \
    tiktoken==0.12.0 safetensors==0.6.2 pyarrow transformers==4.57.6
uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest tests/ -q -p no:cacheprovider      # 1248 pass, 20 skip; one test needs a file not in this snapshot
export NPK_BENCH_HOME=~/npk-data                     # datasets, clones, packs (never committed)
python -m benchmarks.npkbench.run --split dev-fast --targets tests,docs --arms npk_default,npk_nodefs \
    --workers 4 --out experiments/npkbench/runs/<id>
python -m benchmarks.npkbench.report --compare RUN_A:ARM RUN_B:ARM   # paired bootstrap
```

First runs clone the 12 SWE-bench repositories (blobless, ~2 GB) and build packs
(~15 s each for Django). Use `--ephemeral-packs` on `heldout` (407 tasks) unless you
have ~20 GB free. Record every experiment with `benchmarks.npkbench.expdb.append`.

## Evidence discipline that must not be relaxed

- Decide on `dev`/`dev-fast`; confirm once on `heldout`; never tune on `heldout`.
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

In flight at the time of writing (run directories under `experiments/npkbench/runs/`;
worktree branches `exp/e019-rst-text`, `exp/e018-doc-entities` are local only):

1. **E012 dense re-ranking** of the product's top-100 pool (MiniLM, bge-small), all targets,
   and **M004** the same on conversation memory (21 of 191 memory evidence turns at 2K are
   never retrieved lexically: vocabulary mismatch). If dense wins, the product path is
   compile-time vectors reused by block hash, not query-time encoding.
2. **E019 reST in `.txt`:** Django writes its documentation as reST in `.txt`, which the
   compiler cut into 60-line windows. Splitting by sections gives named, topical blocks
   (settings.txt: 223 sections instead of 60 windows). Judge on docs *and* code targets.
3. **E018 documentation channel:** reST object directives (`.. method::`, `.. setting::`,
   `.. class::` ...) become `documents` symbols; a second definition-style channel resolves
   named entities to the prose that documents them. Aims to recover the definition
   channel's docs cost (E015: -9 points at 1K) without demoting anything.
4. **E016 test-mate** (tests-target recovery by path convention) and **E017 context map**
   (budget share for a location map; scored by `~loc` rows).
5. **Held-out confirmation of E005c** (`E005h-trim-heldout`, queued last).
6. **Update latency on large repositories:** the global digest still rehashes FTS storage.

## Things that were tried and must not be repeated without a new idea

See the rejected entries in EXPERIMENTS.md: file aggregation (E003), coarse→fine
emission for every large block (E005), role priors (E006), portfolios (E008), callee
expansion (E009), learned re-ranking over existing channels (E011), sibling collapse
(E013), diversity/density/paragraph units for conversations (M001-M003).
