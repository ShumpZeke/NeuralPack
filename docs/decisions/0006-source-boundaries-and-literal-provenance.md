# Source boundaries and literal provenance

Status: accepted for compiler 5.2, artifact format 5.

## Reproduced failures

Eligible source could contain recognized credential strings, NUL content could
be silently skipped or stored depending on its offset, and a file changed during
reading could be published with inconsistent text and metadata. SQLite URI
delimiters in a literal filename could select a plausible sibling artifact.
Updating an absent pack could create an empty database before failing.

Independent reconstruction found another failure: Python `str.splitlines()`
treats Unicode separators and form feeds as line breaks. In source strings these
are data. Splitting them could change the text and disagree with Python AST line
numbers. Recapping also dropped terminal blank lines while retaining them in
reported spans. A valid self-recorded checksum did not reject impossible spans.

On the pinned Click collection, the old default build had three blocks that
failed literal reconstruction. The repaired build has zero, with no missing
nonblank source lines. Chunk window sizing also changes, so cross-version
selection equality is not assumed. Incremental and fresh builds must still agree.
These are **EMPIRICAL** observations, not general evidence-sufficiency claims.

## Decision

- Fail compilation/update on recognized credential patterns in eligible source
  or source paths. Report a category and sanitized path; never echo the value.
  Do not redact source or silently omit the matching file. Known excluded paths
  remain excluded. This limited screen does not detect all possible secrets.
- Reject NUL anywhere in eligible text. Retain explicit UTF-8 and size rules.
- Resolve each eligible file inside the source root and compare file identity,
  size and timestamps before and after reading. This detects ordinary changes
  during a read, not an atomic repository snapshot or every metadata-preserving
  malicious race.
- URI-encode literal artifact paths. Open existing writable packs with SQLite
  `mode=rw`; only unpublished compilation may use `mode=rwc`.
- Normalize CR/LF line endings, preserve other characters within physical lines,
  and derive capped end positions from the actual included line slice.
- Full verification independently checks positive integer spans and line counts,
  in addition to hashes and SQLite integrity. This establishes internal geometry,
  not correspondence to an unavailable external source. Acceptance of an
  untrusted publisher still needs independent trust in its root/source.

The source screen's OpenAI pattern requires the literal `sk-`. Skipping that
regex when the literal is absent avoids its expensive word-boundary scan while
retaining the current recognition policy. Generated boundary cases and a
matched public-source experiment compare against the original regexes. Broader
per-pattern prefilters were slower and were discarded. New patterns must be
reviewed against the prefilter; it is not a generic theorem about future regexes.

## Consequences and evidence

Existing artifacts must be rebuilt before updates under different compiler
rules. Earlier format-5 artifacts with impossible spans can fail stronger
verification. Default retrieval remains BM25, and no generative model is called
by compilation or selection. None of these repairs establishes differentiated
answer quality.

Checks add source-scan cost. The record includes both the initial slower screen
and the narrower optimization, small and large source profiles, machine-load
observations, and exact source snapshots. Do not generalize one timing to all
repositories. The optional encoders and graph machinery remain experiments.

Evidence: `tests/test_source_boundary.py`, `tests/test_pack_paths.py`,
`tests/test_source_lines.py`, `tests/test_source_screen_equivalence.py`,
`tests/test_identifier_report.py`, and `experiments/results/cycle12-*`.

The initial cycle-12 coverage reports are explicitly withdrawn for promotion.
Their namespace correction did not repair their source-span defect. Fresh LOCAL
reports reconstruct every saved selection from pinned source before LIVE plans
can be prepared. Source-span coverage remains separate from answer correctness.
