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

Data never enters the git repository: parquet files are downloaded from pinned
HuggingFace revisions and checked against SHA-256 digests; source trees are
exported from pinned git commits into ``NPK_BENCH_HOME`` (default ``~/npk-data``).
"""
