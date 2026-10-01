"""Coverage of gold edit locations by selected source spans."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Task

Span = Tuple[str, int, int]


def score(task: Task, spans: Sequence[Span]) -> Dict[str, float]:
    hunks = task.hunks
    found = [h.found_by(spans) for h in hunks]
    files = task.files
    files_found = sum(any(path == f for path, _lo, _hi in spans) for f in files)
    gold_lines = [(h.path, x) for h in hunks for x in h.lines()]
    lines_found = sum(any(p == path and lo <= x <= hi for p, lo, hi in spans)
                      for path, x in gold_lines)
    return {
        "hunks": len(hunks), "hunks_found": sum(found),
        "hunk_recall": sum(found) / len(hunks) if hunks else math.nan,
        "all_found": float(all(found)) if hunks else math.nan,
        "files": len(files), "files_found": files_found,
        "file_recall": files_found / len(files) if files else math.nan,
        "line_recall": lines_found / len(gold_lines) if gold_lines else math.nan,
    }


def tokens_to_find(task: Task, ranking: Sequence[Tuple[str, int, int, int]]) -> Dict[str, Optional[int]]:
    """Rank-order cost to first cover each gold hunk and all of them.

    ``ranking`` holds (path, start, end, tokens). Cost counts every block that
    precedes the covering block in rank order: this is the budget a rank-order
    packer needs, independent of any particular budget grid.
    """
    remaining = {i: h for i, h in enumerate(task.hunks)}
    first: Dict[int, int] = {}
    cost = 0
    first_rank: Optional[int] = None
    for rank, (path, lo, hi, tokens) in enumerate(ranking):
        cost += tokens
        for i, hunk in list(remaining.items()):
            if hunk.found_by([(path, lo, hi)]):
                first[i] = cost
                del remaining[i]
                if first_rank is None:
                    first_rank = rank
        if not remaining:
            break
    return {
        "first_rank": first_rank,
        "tokens_to_first": min(first.values()) if first else None,
        "tokens_to_all": max(first.values()) if not remaining and first else None,
    }


def bootstrap_diff(a: List[float], b: List[float], *, resamples: int = 4000,
                   seed: int = 20260926) -> Tuple[float, float, float]:
    """Paired bootstrap of mean(b - a): (mean, 2.5%, 97.5%)."""
    import random

    pairs = [(x, y) for x, y in zip(a, b) if not (math.isnan(x) or math.isnan(y))]
    if not pairs:
        return math.nan, math.nan, math.nan
    diffs = [y - x for x, y in pairs]
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return sum(diffs) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
