# Cycle 28: shared record identity

Overall verdict remains **PIVOT REQUIRED**. This is an audit repair with no new
model calls and no retrieval promotion. The preceding complete-program controls
identified Python's native equality as unsafe for identity checks on frozen JSON
records. The same issue was present in the shared response and replay validators.

EMPIRICAL counterexamples: eleven new regression cases fail before repair.
The validators accept an integer token count changed to a float, a one-token
count changed to `true`, a nested zero changed to `false`, replay outcomes and
attempt counts with changed types, and a parent ledger whose types differ from
its raw response. Recovery-plan checks also accept changed answer/count types,
`true` as the policy version, and floating-point HTTP status codes.

The repair compares audit identity through JSON serialization that preserves
types and rejects non-finite or non-JSON data. Recovery policy versions must be
integers. Affected checks cover reported versus raw usage, original versus replay
records, parent ledger versus response bytes, shared request/settings identity,
and frozen recovery plans. Answer grading retains its existing numerical
equivalence rule: an audit record's exact identity and a task's acceptable
numerical answer are different contracts.

The focused response/recovery suite passes60 tests after repair. The full suite
passes1,140 tests with two explicit symlink skips. All144 mutations are caught
by assertion failures, including the three original critical mutants. Three
new mutations restore native equality for usage, replay, and plan checks.
Full testing and mutation testing use separate processes and identical351
source-file hashes. Both processes finish successfully.

EMPIRICAL re-audit:381 record files across six explicitly listed run directories
pass the stronger checks with zero grade changes. They cover233 unique payloads
and282 historical API attempts, including the one allowed retry pass. There are
197 successful LIVE response records and99 replay records. These counts are not
correct-task counts and do not describe the entire project's history.

| Re-audited run | Historical new API attempts in that run | Successful LIVE responses | Replays |
| --- | ---: | ---: | ---: |
| Original library stage | 148 | 99 | 0 |
| Its transport-recovery pass | 49 | 35 | 99 |
| Manual reference diagnostic | 24 | 19 | 0 |
| Existing low-effort library profile | 45 | 28 | 0 |
| Complete programs, direct | 8 | 8 | 0 |
| Complete programs, thinking | 8 | 8 | 0 |

Every ledger, response, request hash, and source-context hash is checked. Replay
origins are reconstructed. Recovery eligibility and all recorded answer grades
are rechecked against the frozen plans and prior reports. The original files
are not changed. The result is saved in
`experiments/results/cycle28-shared-record-reaudit.json`.

EMPIRICAL audit overhead: twelve paired, alternating warm measurements over the
same197 valid LIVE records give median batch times0.144 ms before and1.156 ms
after. This adds about1.012 ms per197-record audit. It is slower, and the
additional type check is retained for correctness. The measurement covers
`validate_response`, not replay file I/O, full report generation, product query
latency, or model inference. No dollar or runtime speed improvement is claimed.

KEEP strict audit identity and the eleven counterexamples. DISCARD native Python
equality as a proof of unchanged JSON records. The new checks change no recorded
answer outcome: CRISP still has7 known correct answers versus NeuralPack BM25's
complete5 on the frozen15-task library test. The complete-program target control
still has6/8 direct versus8/8 thinking, with higher output usage and latency for
thinking. Neither result establishes NeuralPack superiority.

NEXT: extend repository evaluation using the same target settings, explicit
executable input harnesses, complete-source controls, and matched retrieval
budgets. Continue pursuing stronger seeds; the default compiler/runtime must
remain independent of generative models. The broader research goal is active.
