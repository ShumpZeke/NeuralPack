"""NPK-Bench: an externally authored, held-out benchmark for context selection.

Why this exists
---------------
Earlier cycles evaluated NeuralPack on questions its own developers wrote and
inspected (the 246 annotated CRISP needles, 12-15 behavior oracles). Those data
are not in this repository snapshot, and inspected development questions are a
weak basis for promotion decisions. NPK-Bench instead uses SWE-bench issue
reports: real users wrote the query, and real maintainers' fixes define which
source must be found. Nothing in the query was produced by, or tuned against,
NeuralPack.

Task: given the issue text and a repository at the issue's base commit, select
at most ``B`` context tokens. Score whether the selected source spans contain
the locations that the reference fix edits. This measures localization evidence
at a fixed budget, not answer or patch correctness.

Splits (fixed before any NeuralPack result was observed):

* ``dev``      -- SWE-bench Lite test (300 tasks). All tuning happens here.
* ``dev-fast`` -- a deterministic, repository-stratified 100-task subset of dev.
* ``heldout``  -- SWE-bench Verified minus Lite (407 tasks). Used only to
  confirm a promotion decision. Never used for tuning or error analysis.
  (Spent on E016b by H001; later confirmations use ``heldout-b``.)
* ``heldout-b`` -- SWE-bench test minus Verified minus Lite, a fixed
  repository-stratified sample of 400 (``heldout-b-all``: all of them).
  Declared 2026-09-26 before any result on it; confirmation only.
  (Spent on E016c by HB01.)
* ``heldout-c`` -- a fixed stratified 400 of ``heldout-b-all`` minus ``heldout-b``,
  declared 2026-09-26 for the next confirmation. (Spent on E031 by HC01.)
* ``heldout-d`` -- a fixed stratified 400 of ``heldout-b-all`` minus ``heldout-b``
  and ``heldout-c`` (785 remain), declared 2026-09-27 before any result on it;
  confirmation only. (Spent on E039 by HD01.)
* ``heldout-e`` -- the rest of ``heldout-b-all`` (not in ``heldout-b``, ``-c`` or ``-d``),
  declared 2026-09-27 before any result on it; confirmation only.
* ``poly-dev`` / ``poly-heldout`` -- the Java, JavaScript and TypeScript issues of the
  SWE-PolyBench 500-issue verified subset (MIT), minus microsoft/vscode, angular/angular
  and google/guava; split per repository by a fixed hash, about 60% for developing
  non-Python handling and 40% for confirmation only. Declared 2026-09-27 before any
  result on them. (``poly-heldout`` spent on E047 by PH01.)
* ``poly-dev-b`` -- the full SWE-PolyBench's Java/JS/TS issues outside that 500-issue
  subset (disjoint from ``poly-dev`` and ``poly-heldout``), same repository exclusions,
  at most 80 per repository by a fixed hash (371 issues). Declared 2026-09-27 before any
  result on it; development only, for screening with more power than ``poly-dev``.
* ``gym-dev`` / ``gym-heldout`` -- SWE-Gym (MIT; 11 Python repositories SWE-bench does not
  use: pandas, MONAI, moto, mypy, dvc, dask, modin, pydantic, conan, hydra, bokeh). Per
  repository in a fixed hash order, the first 30 issues are ``gym-dev`` (screening Python
  changes with more power than ``dev``) and the next 30 ``gym-heldout`` (confirmation only).
  Declared 2026-09-27 before any result on them. (``gym-heldout`` spent on E052 by GH01.)
  ``gym-heldout-b`` (254) and ``gym-heldout-c`` (197) are the next two runs of 30 per
  repository in the same order (bokeh has none left); confirmation only, declared later on
  2026-09-27 before any result on them.
* ``poly-heldout-b`` -- the rest of the full SWE-PolyBench's Java/JS/TS issues (outside the
  500-issue subset and ``poly-dev-b``), same exclusions, at most 80 per repository by a
  fresh fixed hash. Declared 2026-09-27 before any result on it; confirmation only.
  ``poly-heldout-c`` (246: material-ui, svelte, serverless, prettier) is the next 80 per
  repository in the same order; confirmation only, declared before any result on it.
* ``ood-multi`` -- SWE-bench Multilingual (300 issues, 41 non-Python repositories);
  ``ood-multi-sample``: at most 3 per repository, measurement only;
  ``ood-multi-dev``: the other 186, for developing non-Python handling.

Targets (one selection is scored against all of them; see ``data.TARGETS``):
``fix`` (lines the reference fix edits), ``tests`` (existing test-file lines the
reference test patch edits; 99% of dev tasks) and ``docs`` (topical prose the
upstream change edited, ``DOCS_VERSION``; 8.7% of dev tasks).

Decision rule (declared 2026-09-26, before any docs-3 result was observed).
For a candidate change, compute paired per-budget differences on dev (or
dev-fast) for each target, and the utility

    U(B) = d_fix(B) + 0.99 * d_tests(B) + 0.087 * d_docs(B)

with each target weighted by how often it exists among dev tasks. Promote only
if some budget shows a significant gain (paired bootstrap CI excluding zero) on
the target the change addresses, U(B) >= 0 at every budget, and no target loses
significantly at a budget where U(B) is not clearly positive. Then confirm
once on ``heldout``. Changes to shared machinery must also hold on the
conversation-memory workload (``memory-dev``).

Data never enters the git repository: parquet files are downloaded from pinned
HuggingFace revisions and checked against SHA-256 digests; source trees are
exported from pinned git commits into ``NPK_BENCH_HOME`` (default ``~/npk-data``).
"""
