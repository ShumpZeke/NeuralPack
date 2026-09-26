# Next steps (handoff for the next agent)

Kept current during the autonomous research loop. Start here, then read
[BASELINE.md](BASELINE.md) and [experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## How to resume in five minutes

```bash
uv venv --python /usr/bin/python3.12 .venv && . .venv/bin/activate
uv pip install -e '.[dev,tokenizers]' numpy==2.2.6 psutil==7.0.0 urllib3==2.7.0 click==8.5.0 \
    tiktoken==0.12.0 safetensors==0.6.2 pyarrow transformers==4.57.6
uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest tests/ -q -p no:cacheprovider      # 1238 pass, 28 skip; one test needs a file not in this snapshot
export NPK_BENCH_HOME=~/npk-data                     # datasets, clones, packs (never committed)
python -m benchmarks.npkbench.run --split dev-fast --targets tests --arms npk_default,npk_nodefs \
    --workers 4 --out experiments/npkbench/runs/<id>
python -m benchmarks.npkbench.report --compare RUN_A:ARM RUN_B:ARM   # paired bootstrap
```

First runs clone the 12 SWE-bench repositories (blobless, ~2 GB) and build packs
(~15 s each for Django). Use `--ephemeral-packs` on `heldout` (407 tasks) unless you
have ~20 GB free. Record every experiment with `benchmarks.npkbench.expdb.append`.

## Evidence discipline that must not be relaxed

- Decide on `dev`/`dev-fast`; confirm once on `heldout`; never tune on `heldout`.
- Always score **both targets** (`--targets tests`): a change that wins the fix target by
  ignoring tests is gaming (E006, E011 were caught this way).
- NPK-Bench has **no documentation target**; any documentation demotion is
  unfalsifiable here (E008). Build a docs target before revisiting.
- Performance changes must be proven output-identical with
  `benchmarks.npkbench.equivalence` and timed with `benchmarks.npkbench.compile_timing`
  (profilers overstate pure-Python call overhead; E001b).

## Strongest remaining hypotheses (ranked)

1. **Dense similarity as a new evidence channel (E012, in progress).** Re-ranking the
   product's top-100 pool; content-addressed vector cache. Headroom is large (gold is
   first for 36% of issues, in the top-100 for 79%). If it wins on both targets, the
   product path is compile-time vectors with reuse by block hash (already supported by
   `update_pack`), not query-time encoding.
2. **A documentation target** for NPK-Bench (e.g. Django upstream commits that touch
   `docs/` alongside code), so documentation demotion (the largest unvalidated effect,
   +2-4 points on both code targets) can be judged honestly.
3. **Conversation memory (LongMemEval):** the weak types are multi-session aggregation
   and implicit preferences. Diversity (M001), density ordering (M002) and paragraph
   units (M003) failed; next candidates are temporal metadata use and dense similarity.
4. **Held-out confirmation of E005c** (top-block trimming) alongside E002.
5. **Update latency on large repositories** (measure a one-file Django update; the
   global digest still rehashes FTS storage).

## Things that were tried and must not be repeated without a new idea

See the rejected entries in EXPERIMENTS.md: file aggregation (E003), coarse→fine
emission for every large block (E005), role priors (E006), portfolios (E008), callee
expansion (E009), learned re-ranking over existing channels (E011), sibling collapse
(E013), diversity/density/paragraph units for conversations (M001-M003).
