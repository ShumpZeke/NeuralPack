# Cycle 25: preserve case boundaries without diluting known identifiers

**EMPIRICAL.** Inspection found that the shared query tokenizer lowercased words
before attempting to identify camel-case boundaries. `retryBackoffMillis`,
`HTTPStatusCode` and `expireOnCommit` each became one term. The compiled default
therefore missed underscore-named source queried using camel-case spellings.
The original query itself was preserved; this was a seed-generation failure.

## Competing repairs

The frozen LOCAL comparison used the same pinned SQLAlchemy corpus and verified
2,048-character artifacts as cycle 24. Sixteen underscore names and sixteen
compound names were sampled by a declared SHA-256 ordering before retrieval.
Each had a native query, alternate spelling and a prefixed question. Some names
are examples, document anchors or inflected SQL words, not public API symbols.
This is an identifier-presence diagnostic, not answer accuracy.

Four methods used identical provenance-aware assembly and 1,024/4,096-token caps:
the previous lexical tokenizer, unconditional case splitting, vocabulary-checked
splitting, and the actual local MiniLM hybrid. Three shuffled sweeps produced
2,304 observations across 768 unique cells. Every context was reconstructed from
literal source spans; repeated cells selected the same bytes. The hybrid's
declared similarity floor remained unchanged; actual embedding-channel use is
recorded, so fallback lexical cells are visible.

| Underscore source queried with camel spelling | Previous lexical | Split every compound | Check vocabulary first | Local hybrid |
| --- | ---: | ---: | ---: | ---: |
| Bare alias, 1,024 cap | 0/16 | 14/16 | 14/16 | 3/16 |
| Bare alias, 4,096 cap | 0/16 | 16/16 | 15/16 | 6/16 |
| Prefixed alias, 1,024 cap | 0/16 | 11/16 | 11/16 | 1/16 |
| Prefixed alias, 4,096 cap | 0/16 | 14/16 | 14/16 | 2/16 |

Correctly spelled underscore queries were unchanged by either repair: 15/16 at
1K and 16/16 at 4K. Known compound queries retained 14/16 and 16/16 with all three
lexical methods, but unconditional splitting expanded the posting lists: median
query time at 4K rose from 1.13 ms to 17.46 ms. The vocabulary check took 1.12 ms
on that slice, preserving the previous selections. This avoids a challenger
regression; it is not a 15× speedup over the existing product.

Vocabulary-checked bare aliases took median 8.92 and 18.27 ms at the two caps,
versus 0.87 and 0.85 ms for the previous method's mostly failed searches. The
extra time performs retrieval that the old tokenizer could not perform. It must
not be called a latency improvement over an empty result.

## Attacks and retained limitations

The vocabulary rule gives up one 4K alternate-spelling hit and two 1K prefixed
compound hits relative to unconditional splitting. In particular, the corpus
already contains `someotherobject` in `orm/session_events.rst`, line 388. That
literal blocks expansion of `someOtherObject` toward `some_other_object`.
Presence somewhere in the corpus does not establish the user's intended alias.
A permanent two-file counterexample preserves this limitation and verifies that
risk remains explicitly uncalibrated.

An implementation attack also found that deduplicating by the lowercase spelling
too early suppresses later case information: `expireoncommit expireOnCommit`.
Processing distinct original spellings repairs that defect. A regression also
covers two different case boundaries with the same folded spelling. Whole query
bytes, original terms, source spans, budget and per-request isolation survive.

The production repair examines original ASCII programming-identifier boundaries,
keeps whole terms, and adds component terms only when the folded compound is
absent from the artifact's lexical vocabulary. Known compounds retain their
existing lexical query. Unicode words remain intact; no universal language
segmentation claim is made. The older optional in-memory tokenizer is unchanged;
its misleading camel-case comment is corrected. No flag, model dependency,
artifact schema or generative optimizer is added.

The implemented runtime reproduced all **192** vocabulary-challenger selections.
All **40** shared-BM25 selections from the prior ten behavior questions and four
budgets were byte-identical. These are equivalence checks, not new LIVE answers.

## Scale profile after implementation

Six new deterministic artifacts use complete public-source files, accumulated in
ascending size/path order. The same default splitter is used at every scale.
Twelve queries per artifact, two term-generation methods and three shuffled
trials produce 432 timed requests. Verification and compilation are outside
query timing. No agent tests, archive compression, LIVE IO or other CPU benchmark
overlapped. Host load was uncontrolled.

| Available estimated tokens | Initial compile ms | Repaired alias median ms | Repaired long behavior-query median ms |
| ---: | ---: | ---: | ---: |
| 2,035 | 152.56 | 0.69 | 3.19 |
| 25,779 | 317.72 | 0.94 | 4.75 |
| 50,747 | 277.25 | 1.00 | 5.35 |
| 102,998 | 501.55 | 1.29 | 8.48 |
| 256,861 | 1,013.34 | 1.74 | 10.71 |
| 527,662 | 1,576.14 | 2.35 | 13.68 |

These are scale-dependent LOCAL observations, with one initial build each.
The larger profile's previous native-query median was 2.21 ms versus 2.23 ms
after repair; long queries were 13.91 versus 13.68 ms, within the limits of this
uncontrolled profile. Nonempty source selection is not proof that the context
answers a question. The profile's default splitter differs from the fixed-width
research artifacts, so their timings are not a before/after speedup comparison.

Final acceptance: **775 tests passed, two skipped; all 65 mutation tripwires
were killed**, including the three original critical failures and both new
spelling-erasure and vocabulary-bypass attacks. The production query path still
uses zero generative LLM calls and works with existing artifact schemas.

**Decision: keep the narrow vocabulary-checked spelling repair. PIVOT REQUIRED
still applies to claims of broadly superior answer quality.** Neither
unconditional splitting nor mandatory embeddings earns promotion. No LIVE calls
were made this cycle. The next hypothesis is whether source-aware identifier
normalization can recover alternate spellings in both directions while exposing
collisions, without slowing existing exact-name lookups. Benchmark that against
the repaired lexical baseline before adding any compiled index.
