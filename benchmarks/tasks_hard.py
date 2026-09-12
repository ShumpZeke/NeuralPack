"""Hard evaluation tasks and real large-context corpora.

The audited suites were dominated by exact-identifier lookup: the query named the
symbol, so a grep would score as well as anything. Those tasks cannot separate
retrieval methods. This module builds families that can.

Each family targets a specific failure mode identified in the audit:

``semantic_gap``       query vocabulary never appears in the answer block
``multi_hop``          answer reachable only through an N-step import chain
``dynamic_indirection``control flow hidden behind getattr / importlib
``config_indirection`` value resolved through a config lookup layer
``symbol_collision``   same identifier defined in several modules
``multi_fact``         several separate facts all required
``distractor``         high-similarity blocks that look right and are not
``negative_constraint``a superseded value that must NOT be reported
``version_conflict``   several versions present; only one is active

Corpora come in two flavours:

* **synthetic** -- generated, fully controlled, gold answers known by construction;
* **real** -- assembled from open-source Python on this machine (torch,
  transformers, numpy, sympy, networkx), so "100K tokens of context" means 100K
  tokens of genuine third-party code rather than one snippet repeated.

Tasks are split into ``dev`` and ``sealed`` by a hash of the task id, so tuning
on dev cannot leak into the sealed set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import random
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from npk.context.analyzer import estimate_tokens

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = REPO_ROOT / ".venv" / "Lib" / "site-packages"

#: Distinct business domains, one per task instance within a family. Mixed-corpus
#: evaluation compiles many tasks into ONE artifact, so two tasks sharing a query
#: with different answers makes both unanswerable. Scoping by domain keeps every
#: query self-identifying while preserving each family's difficulty -- in
#: particular the semantic-gap families still never name their target symbol.
TASK_DOMAINS = (
    "billing", "search", "auth", "shipping", "telemetry", "payments",
    "inventory", "routing", "reporting", "ingestion", "scheduling", "archival",
)


def domain_for(idx: int) -> str:
    return TASK_DOMAINS[idx % len(TASK_DOMAINS)]


#: Real open-source packages used to build large contexts.
REAL_CORPUS_PACKAGES = ("torch", "transformers", "numpy", "sympy", "networkx", "jinja2", "urllib3")


@dataclass
class HardTask:
    id: str
    family: str
    query: str
    context: str
    gold: List[str]                       # every string must be present to answer
    forbidden: List[str] = field(default_factory=list)   # must NOT be reported
    required_blocks: List[str] = field(default_factory=list)
    hops: int = 0
    split: str = "dev"
    corpus_source: str = "synthetic"

    @property
    def context_tokens(self) -> int:
        return estimate_tokens(self.context)

    def messages(self, system: str = "You are a precise technical AI answering questions.") -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{self.context}\n\nQUESTION: {self.query}"},
        ]


def assign_split(task_id: str, sealed_fraction: float = 0.5) -> str:
    """Deterministic dev/sealed split by id hash (no leakage across runs)."""
    h = int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "sealed" if h < sealed_fraction else "dev"


# ---------------------------------------------------------------------------
# Filler / distractor generation
# ---------------------------------------------------------------------------

def _synthetic_filler(n: int, theme: str, seed: int = 0) -> List[str]:
    rng = random.Random(seed)
    out = []
    for k in range(n):
        out.append(
            f"```File: {theme}_module_{k:04d}.py\n"
            f"import logging\n\n"
            f"logger = logging.getLogger(__name__)\n\n"
            f"class {theme.title()}Handler{k:04d}:\n"
            f"    RETRY_BUDGET = {rng.randint(1, 9)}\n"
            f"    POLL_INTERVAL = {rng.randint(10, 99)}\n\n"
            f"    def process_{theme}_{k:04d}(self, payload: dict) -> dict:\n"
            f"        if not payload.get('valid'):\n"
            f"            logger.warning('invalid payload')\n"
            f"            return {{'error': 'invalid', 'code': 400}}\n"
            f"        return {{'status': 'ok'}}\n```"
        )
    return out


def _iter_real_files(packages: Sequence[str] = REAL_CORPUS_PACKAGES) -> Iterable[Path]:
    for pkg in packages:
        root = SITE_PACKAGES / pkg
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                if 500 < path.stat().st_size < 40_000:
                    yield path
            except OSError:
                continue


def real_corpus_blocks(target_tokens: int, seed: int = 0,
                       packages: Sequence[str] = REAL_CORPUS_PACKAGES) -> List[str]:
    """Assemble genuine third-party source until *target_tokens* is reached."""
    files = list(_iter_real_files(packages))
    if not files:
        return _synthetic_filler(max(1, target_tokens // 90), "fallback", seed)
    rng = random.Random(seed)
    rng.shuffle(files)

    blocks: List[str] = []
    total = 0
    for path in files:
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(SITE_PACKAGES).as_posix()
        block = f"```File: {rel}\n{body}\n```"
        tok = estimate_tokens(block)
        if tok > target_tokens:
            continue
        blocks.append(block)
        total += tok
        if total >= target_tokens:
            break
    return blocks


def corpus_stats(blocks: Sequence[str]) -> Dict[str, Any]:
    return {
        "blocks": len(blocks),
        "corpus_tokens": sum(estimate_tokens(b) for b in blocks),
    }


# ---------------------------------------------------------------------------
# Task families
# ---------------------------------------------------------------------------

def make_semantic_gap(idx: int, filler: List[str]) -> HardTask:
    """Query vocabulary shares no token with the answer block.

    The domain scopes the question so it stays answerable in a mixed corpus,
    while the target symbol (MAX_PARALLEL_WORKERS) is still never named -- the
    semantic gap is preserved.
    """
    dom = domain_for(idx)
    value = 3700 + idx
    needle = f"```File: {dom}/worker_limits.py\nMAX_PARALLEL_WORKERS = {value}\n```"
    ctx = "\n\n".join(filler[: len(filler) // 2] + [needle] + filler[len(filler) // 2:])
    return HardTask(
        id=f"semantic_gap_{idx:03d}", family="semantic_gap",
        query=f"How many jobs can the {dom} pipeline run at the same time?",
        context=ctx, gold=[str(value)], required_blocks=[f"{dom}/worker_limits.py"],
    )


def make_multi_hop(idx: int, hops: int, filler: List[str]) -> HardTask:
    """Answer reachable only by following an N-step import chain.

    Every symbol in the chain is namespaced by domain AND hop count, so two
    instances never collide in a mixed corpus.
    """
    dom = domain_for(idx)
    tag = f"{dom}{hops}"
    value = 60000 + idx + hops * 1000
    parts = [
        f"```File: {tag}/entry_point.py\nfrom {tag}_stage_1 import {tag}_stage_1_value\n\n"
        f"def resolve_{tag}_surcharge():\n    return {tag}_stage_1_value()\n```"
    ]
    for h in range(1, hops):
        parts.append(
            f"```File: {tag}/stage_{h}.py\nfrom {tag}_stage_{h+1} import {tag}_stage_{h+1}_value\n\n"
            f"def {tag}_stage_{h}_value():\n    return {tag}_stage_{h+1}_value()\n```"
        )
    parts.append(
        f"```File: {tag}/stage_{hops}.py\n"
        f"def {tag}_stage_{hops}_value():\n    return {value}\n```")
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"multi_hop_{hops}_{idx:03d}", family="multi_hop",
        query=f"What integer does resolve_{tag}_surcharge ultimately produce?",
        context=ctx, gold=[str(value)],
        required_blocks=[f"{tag}/stage_{hops}.py"], hops=hops,
    )


def make_dynamic_indirection(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    value = 1200 + idx
    parts = [
        f"```File: {dom}/policy_loader.py\nimport importlib\n\n"
        f"ACTIVE_POLICY = \"aggressive\"\n\n"
        f"def get_{dom}_retry_budget():\n"
        f"    mod = importlib.import_module('{dom}.policies.' + ACTIVE_POLICY)\n"
        f"    return getattr(mod, 'RETRY_BUDGET')\n```",
        f"```File: {dom}/policies/aggressive.py\nRETRY_BUDGET = {value}\n```",
        f"```File: {dom}/policies/conservative.py\nRETRY_BUDGET = 1\n```",
    ]
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"dynamic_indirection_{idx:03d}", family="dynamic_indirection",
        query=f"What retry budget value does get_{dom}_retry_budget actually return?",
        context=ctx, gold=[str(value)], forbidden=["RETRY_BUDGET = 1\n"],
        required_blocks=[f"{dom}/policies/aggressive.py"], hops=2,
    )


def make_config_indirection(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    value = 8800 + idx
    parts = [
        f"```File: {dom}/settings_resolver.py\nfrom {dom}_config import CONFIG\n\n"
        f"def effective_upload_cap():\n    return CONFIG['limits']['upload_cap_kb']\n```",
        f"```File: {dom}/{dom}_config.py\nCONFIG = {{\n    'limits': {{'upload_cap_kb': {value}}},\n}}\n```",
    ]
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"config_indirection_{idx:03d}", family="config_indirection",
        query=f"What is the effective upload cap in kilobytes for the {dom} service?",
        context=ctx, gold=[str(value)],
        required_blocks=[f"{dom}/{dom}_config.py"], hops=1,
    )


def make_symbol_collision(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    other = domain_for(idx + 1)
    third = domain_for(idx + 2)
    right, wrong = 5100 + idx, 9100 + idx
    parts = [
        f"```File: svc{idx:03d}/{dom}/limits.py\nREQUEST_TIMEOUT = {right}\n```",
        f"```File: svc{idx:03d}/{other}/limits.py\nREQUEST_TIMEOUT = {wrong}\n```",
        f"```File: svc{idx:03d}/{third}/limits.py\nREQUEST_TIMEOUT = {wrong + 1}\n```",
    ]
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"symbol_collision_{idx:03d}", family="symbol_collision",
        query=f"What is REQUEST_TIMEOUT in svc{idx:03d} {dom} specifically?",
        context=ctx, gold=[str(right)], forbidden=[str(wrong)],
        required_blocks=[f"svc{idx:03d}/{dom}/limits.py"],
    )


def make_multi_fact(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    a, b, c = 200 + idx, 300 + idx, 400 + idx
    parts = [
        f"```File: {dom}/pricing/base.py\n{dom.upper()}_BASE_FEE_CENTS = {a}\n```",
        f"```File: {dom}/pricing/surcharge.py\n{dom.upper()}_SURCHARGE_CENTS = {b}\n```",
        f"```File: {dom}/pricing/tax.py\n{dom.upper()}_TAX_CENTS = {c}\n```",
    ]
    ctx = "\n\n".join(parts + filler)
    U = dom.upper()
    return HardTask(
        id=f"multi_fact_{idx:03d}", family="multi_fact",
        query=f"What are {U}_BASE_FEE_CENTS, {U}_SURCHARGE_CENTS and {U}_TAX_CENTS?",
        context=ctx, gold=[str(a), str(b), str(c)],
        required_blocks=[f"{dom}/pricing/base.py", f"{dom}/pricing/surcharge.py",
                         f"{dom}/pricing/tax.py"],
    )


def make_distractor(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    U = dom.upper()
    value = 7300 + idx
    parts = [f"```File: {dom}/real_handler.py\n{U}_CONNECTION_POOL_SIZE = {value}\n```"]
    parts += [
        f"```File: {dom}/doc_note_{j}.py\n"
        f"# {U}_CONNECTION_POOL_SIZE is documented in the operations runbook.\n"
        f"# See the connection pool size guidance for the pool sizing policy.\n"
        f"POOL_DOC_{j} = 'connection pool size guidance'\n```"
        for j in range(12)
    ]
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"distractor_{idx:03d}", family="distractor",
        query=f"What is the {U}_CONNECTION_POOL_SIZE value?",
        context=ctx, gold=[str(value)], required_blocks=[f"{dom}/real_handler.py"],
    )


def make_negative_constraint(idx: int, filler: List[str]) -> HardTask:
    old, new = f"us-east-{idx}", f"eu-central-{idx}"
    turns = [f"User: Reviewing section {i} of run {idx:03d}.\nAssistant: Section {i} of run {idx:03d} looks fine." for i in range(25)]
    convo = (
        "\n".join(turns[:12])
        + f"\nUser: Set the deployment region to {old}.\nAssistant: Region set to {old}.\n"
        + "\n".join(turns[12:])
        + f"\nUser: Correction - we must deploy to {new}; ignore the earlier region.\n"
        f"Assistant: Understood, the region is now {new}.\n"
        "User: Confirm the final region."
    )
    return HardTask(
        id=f"negative_constraint_{idx:03d}", family="negative_constraint",
        query=f"What is the FINAL deployment region for configuration run {idx:03d}?",
        context=convo, gold=[new], forbidden=[f"Region set to {old}"],
        required_blocks=[new],
    )


def make_version_conflict(idx: int, filler: List[str]) -> HardTask:
    dom = domain_for(idx)
    U = dom.upper()
    active = f"2.{idx}.0"
    current, legacy = 512 + idx, 64 + idx
    parts = [
        f"```File: {dom}/CHANGELOG.md\n## {active} (current)\n"
        f"Raised {U}_BATCH_SIZE to {current}.\n\n"
        f"## 1.{idx}.0 (deprecated)\n{U}_BATCH_SIZE was {legacy}.\n```",
        f"```File: {dom}/version.py\n__version__ = \"{active}\"\n{U}_BATCH_SIZE = {current}\n```",
        f"```File: {dom}/legacy/version.py\n__version__ = \"1.{idx}.0\"\n"
        f"{U}_BATCH_SIZE = {legacy}\n```",
    ]
    ctx = "\n\n".join(parts + filler)
    return HardTask(
        id=f"version_conflict_{idx:03d}", family="version_conflict",
        query=f"What is {U}_BATCH_SIZE in the current (non-deprecated) version?",
        context=ctx, gold=[str(current)], forbidden=[f"{U}_BATCH_SIZE = {legacy}"],
        required_blocks=[f"{dom}/version.py"],
    )


FAMILY_BUILDERS = {
    "semantic_gap": lambda i, f: make_semantic_gap(i, f),
    "multi_hop_2": lambda i, f: make_multi_hop(i, 2, f),
    "multi_hop_4": lambda i, f: make_multi_hop(i, 4, f),
    "multi_hop_7": lambda i, f: make_multi_hop(i, 7, f),
    "dynamic_indirection": lambda i, f: make_dynamic_indirection(i, f),
    "config_indirection": lambda i, f: make_config_indirection(i, f),
    "symbol_collision": lambda i, f: make_symbol_collision(i, f),
    "multi_fact": lambda i, f: make_multi_fact(i, f),
    "distractor": lambda i, f: make_distractor(i, f),
    "negative_constraint": lambda i, f: make_negative_constraint(i, f),
    "version_conflict": lambda i, f: make_version_conflict(i, f),
}


def build_task_suite(
    per_family: int = 4,
    filler_tokens: int = 4_000,
    corpus: str = "synthetic",
    seed: int = 20260906,
    families: Optional[Sequence[str]] = None,
) -> List[HardTask]:
    """Build the hard suite.

    :param corpus: ``synthetic`` or ``real`` (genuine third-party source).
    :param filler_tokens: approximate distractor volume per task, which sets the
        per-task context size. Reported PER TASK, never summed.
    """
    names = list(families or FAMILY_BUILDERS)
    tasks: List[HardTask] = []
    for fam_i, fam in enumerate(names):
        for i in range(per_family):
            task_seed = seed + fam_i * 1000 + i
            if corpus == "real":
                filler = real_corpus_blocks(filler_tokens, seed=task_seed)
                source = "real"
            else:
                filler = _synthetic_filler(max(1, filler_tokens // 90), fam, seed=task_seed)
                source = "synthetic"
            task = FAMILY_BUILDERS[fam](i, filler)
            task.split = assign_split(task.id)
            task.corpus_source = source
            tasks.append(task)
    return tasks


def suite_report(tasks: Sequence[HardTask]) -> Dict[str, Any]:
    """Per-task context accounting. Never report cumulative totals as sizes."""
    sizes = sorted(t.context_tokens for t in tasks)
    by_family: Dict[str, Dict[str, Any]] = {}
    for t in tasks:
        entry = by_family.setdefault(t.family, {"n": 0, "min": 1 << 30, "max": 0})
        entry["n"] += 1
        entry["min"] = min(entry["min"], t.context_tokens)
        entry["max"] = max(entry["max"], t.context_tokens)
    return {
        "n_tasks": len(tasks),
        "context_tokens_per_task": {
            "min": sizes[0] if sizes else 0,
            "median": sizes[len(sizes) // 2] if sizes else 0,
            "max": sizes[-1] if sizes else 0,
        },
        "splits": {s: sum(1 for t in tasks if t.split == s) for s in ("dev", "sealed")},
        "by_family": by_family,
    }


def find_ambiguous_tasks(tasks: Sequence[HardTask]) -> Dict[str, List[str]]:
    """Queries shared by tasks with DIFFERENT gold answers.

    Such a task is unanswerable once several tasks are compiled into one
    artifact: the question does not identify which answer is wanted, so the
    metric measures luck rather than retrieval. Cycle 1 found 13 of 18 sealed
    tasks in this state, which invalidated the mixed-corpus numbers.
    """
    by_query: Dict[str, Dict[str, List[str]]] = {}
    for t in tasks:
        by_query.setdefault(t.query, {}).setdefault(tuple(t.gold), []).append(t.id)  # type: ignore[arg-type]
    return {
        query: [tid for ids in golds.values() for tid in ids]
        for query, golds in by_query.items() if len(golds) > 1
    }


def assert_unambiguous(tasks: Sequence[HardTask]) -> None:
    """Raise if any task in *tasks* cannot be answered from its query alone."""
    bad = find_ambiguous_tasks(tasks)
    if bad:
        detail = "; ".join(f"{q!r} -> {ids}" for q, ids in list(bad.items())[:5])
        raise ValueError(
            f"{len(bad)} query/answer collisions make these tasks unanswerable "
            f"in a mixed corpus: {detail}")
