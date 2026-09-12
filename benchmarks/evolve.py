"""Legacy internal-selector parameter sweep; not public product validation.

Historical metrics from this harness used damaged source materialization and
counted arbitrary gold substrings as success while penalizing all distractor
text. Its correlated templates and inspected split do not justify significance
or promotion claims. Use benchmarks.compiled_validation for public-runtime
paired diagnostics. This remains only an experimental parameter probe.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import statistics
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from benchmarks.compiled_corpus import build_corpus
from benchmarks.tasks_hard import HardTask, assert_unambiguous, build_task_suite
from npk.pack import MODE_DETERMINISTIC, compile_pack
from npk.pack.format import load_blocks, open_pack
from npk.pack.select import (
    RRF_K, _embedding_channel, _expand_dependencies, _lexical_channel, _symbol_channel,
)


@dataclass(frozen=True)
class Config:
    """One point in the selector's configuration space."""

    name: str
    seed_fraction: float = 1.0
    expansion_depth: int = 2
    candidate_limit: int = 60
    use_embeddings: bool = False
    expand: bool = True
    resolve_conflicts: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Outcome:
    """Per-task result, kept so comparisons can be paired."""

    task_id: str
    family: str
    hit: bool
    tokens: int
    latency_ms: float


def evaluate(tasks: Sequence[HardTask], pack: Path, cfg: Config,
             budget: int) -> List[Outcome]:
    out: List[Outcome] = []
    with open_pack(pack) as con:
        from npk.pack.format import read_manifest
        manifest = read_manifest(con)
        for t in tasks:
            t0 = time.perf_counter()
            ranks: Dict[str, List[int]] = {}
            s = _symbol_channel(con, t.query, cfg.candidate_limit)
            if s:
                ranks["symbol"] = s
            l = _lexical_channel(con, t.query, cfg.candidate_limit)
            if l:
                ranks["lexical"] = l
            if cfg.use_embeddings:
                e, top = _embedding_channel(con, t.query, cfg.candidate_limit, manifest)
                if e and (top is None or top >= 0.35):
                    ranks["embedding"] = e

            if not ranks:
                out.append(Outcome(t.id, t.family, False, 0,
                                   (time.perf_counter() - t0) * 1000))
                continue

            fused: Dict[int, float] = {}
            for order in ranks.values():
                for rank, bid in enumerate(order):
                    fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank)
            ordered = sorted(fused, key=lambda b: -fused[b])
            blocks = {b.id: b for b in load_blocks(con, ordered)}

            seed_budget = int(budget * cfg.seed_fraction)
            chosen, used = [], 0
            for bid in ordered:
                blk = blocks.get(bid)
                if blk and used + blk.tokens <= seed_budget:
                    chosen.append(bid)
                    used += blk.tokens

            if cfg.expand and chosen:
                extra = _expand_dependencies(con, chosen, cfg.expansion_depth,
                                             cfg.candidate_limit * 4)
                for blk in load_blocks(con, [i for i in extra if i not in set(chosen)]):
                    if used + blk.tokens <= budget:
                        chosen.append(blk.id)
                        used += blk.tokens

            if cfg.resolve_conflicts:
                from npk.pack.conflict import resolve_value_conflicts
                sel_blocks = {b.id: b for b in load_blocks(con, chosen)}
                paths = {bid: blk.path for bid, blk in sel_blocks.items()}
                rank_of = {bid: i for i, bid in enumerate(ordered)}
                drop = set()
                if cfg.resolve_conflicts:
                    d, _ = resolve_value_conflicts(con, chosen, paths, t.query, rank_of)
                    drop |= d
                if drop:
                    chosen = [b for b in chosen if b not in drop]
                    used = sum(sel_blocks[b].tokens for b in chosen if b in sel_blocks)

            text = " ".join(b.text for b in load_blocks(con, chosen))
            hit = all(g in text for g in t.gold) and not any(f in text for f in t.forbidden)
            out.append(Outcome(t.id, t.family, hit, used,
                               (time.perf_counter() - t0) * 1000))
    return out


def paired_bootstrap(champion: Sequence[Outcome], challenger: Sequence[Outcome],
                     iterations: int = 10_000, seed: int = 12345) -> Dict[str, Any]:
    """Bootstrap CI on the PAIRED difference in hit rate.

    Pairing removes task-difficulty variance, which is the dominant term at
    small n. A challenger is only promotable when the interval excludes zero.
    """
    by_id = {o.task_id: o for o in champion}
    pairs = [(by_id[o.task_id].hit, o.hit) for o in challenger if o.task_id in by_id]
    if not pairs:
        return {"n": 0, "delta_pct": 0.0, "ci95": (0.0, 0.0), "significant": False}

    n = len(pairs)
    observed = 100.0 * sum(b - a for a, b in pairs) / n

    rng = random.Random(seed)
    deltas = []
    for _ in range(iterations):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        deltas.append(100.0 * sum(b - a for a, b in sample) / n)
    deltas.sort()
    lo = deltas[int(0.025 * iterations)]
    hi = deltas[int(0.975 * iterations)]

    # McNemar-style discordant counts: the only pairs carrying information.
    only_challenger = sum(1 for a, b in pairs if b and not a)
    only_champion = sum(1 for a, b in pairs if a and not b)

    return {
        "n": n,
        "delta_pct": round(observed, 2),
        "ci95": (round(lo, 2), round(hi, 2)),
        "significant": (lo > 0.0 or hi < 0.0),
        "challenger_only_wins": only_challenger,
        "champion_only_wins": only_champion,
    }


def summarize(outcomes: Sequence[Outcome]) -> Dict[str, Any]:
    n = len(outcomes)
    by_family: Dict[str, List[Outcome]] = {}
    for o in outcomes:
        by_family.setdefault(o.family, []).append(o)
    return {
        "n": n,
        "recall_pct": round(100.0 * sum(o.hit for o in outcomes) / n, 1) if n else 0.0,
        "mean_tokens": round(statistics.mean(o.tokens for o in outcomes), 1) if n else 0,
        "median_latency_ms": round(statistics.median(o.latency_ms for o in outcomes), 2) if n else 0,
        "by_family_recall_pct": {
            fam: round(100.0 * sum(o.hit for o in group) / len(group), 1)
            for fam, group in sorted(by_family.items())
        },
    }


def build_arena(split: str, per_family: int, filler_tokens: int,
                mode: str = MODE_DETERMINISTIC) -> Tuple[List[HardTask], Path, Any]:
    tasks = [t for t in build_task_suite(per_family=per_family,
                                         filler_tokens=filler_tokens, corpus="real")
             if split == "all" or t.split == split]
    assert_unambiguous(tasks)
    tmp = Path(tempfile.mkdtemp(prefix="npk-evolve-"))
    pack = tmp / "arena.npk"
    stats = compile_pack(build_corpus(tmp, tasks), pack, mode=mode)
    return tasks, pack, stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=8)
    ap.add_argument("--filler-tokens", type=int, default=15000)
    ap.add_argument("--split", choices=("dev", "sealed", "all"), default="dev")
    ap.add_argument("--budgets", type=int, nargs="*", default=[800, 1500, 3000])
    ap.add_argument("--run-id", default="evolve-cycle1")
    ap.add_argument("--mode", choices=("deterministic", "semantic"), default="deterministic")
    args = ap.parse_args(argv)

    tasks, pack, stats = build_arena(args.split, args.per_family, args.filler_tokens,
                                     mode=args.mode)
    print(f"arena: {len(tasks)} tasks ({args.split}) | mode={args.mode} | "
          f"{stats.files_indexed} files, {stats.blocks} blocks, {stats.deps} edges, "
          f"{stats.embedded} embedded | pack {pack.stat().st_size/1e6:.1f} MB "
          f"| compile {stats.seconds:.1f}s")

    champion = Config("champion_cycle1", resolve_conflicts=True)
    challengers = [
        # Fair test of expansion: at frac=1.0 the seed stage eats the whole
        # budget, so "no expansion" is a no-op BY CONSTRUCTION. Compare only
        # where there is budget left for expansion to use.
        Config("frac0.8_expand", seed_fraction=0.8, resolve_conflicts=True, expand=True),
        Config("frac0.8_NO_expand", seed_fraction=0.8, resolve_conflicts=True, expand=False),
        Config("frac0.6_expand", seed_fraction=0.6, resolve_conflicts=True, expand=True),
        Config("frac0.6_NO_expand", seed_fraction=0.6, resolve_conflicts=True, expand=False),
        Config("no_conflict_resolution", resolve_conflicts=False),
        Config("embeddings", resolve_conflicts=True, use_embeddings=True),
        Config("embeddings+frac0.8", resolve_conflicts=True, use_embeddings=True,
               seed_fraction=0.8),
        Config("embeddings_no_expand", resolve_conflicts=True, use_embeddings=True,
               expand=False),
    ]

    results: Dict[str, Any] = {"run_id": args.run_id, "tasks": len(tasks),
                              "split": args.split, "budgets": {}}

    for budget in args.budgets:
        champ = evaluate(tasks, pack, champion, budget)
        champ_sum = summarize(champ)
        print(f"\n--- budget {budget} | champion recall {champ_sum['recall_pct']}% "
              f"({champ_sum['mean_tokens']:.0f} tok) ---")
        print(f"{'challenger':>18}{'recall%':>10}{'delta':>8}{'95% CI':>18}{'signif':>8}")

        rows = []
        for cfg in challengers:
            chal = evaluate(tasks, pack, cfg, budget)
            s = summarize(chal)
            cmp = paired_bootstrap(champ, chal)
            flag = "YES" if cmp["significant"] else "no"
            print(f"{cfg.name:>18}{s['recall_pct']:>9.1f}%{cmp['delta_pct']:>+8.1f}"
                  f"{str(cmp['ci95']):>18}{flag:>8}")
            rows.append({"config": cfg.as_dict(), "summary": s, "vs_champion": cmp})

        results["budgets"][str(budget)] = {
            "champion": {"config": champion.as_dict(), "summary": champ_sum},
            "challengers": rows,
        }

    out = Path("experiments/results") / f"{args.run_id}-{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nartifact: {out}")
    print("A challenger is promotable only when its 95% CI excludes zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
