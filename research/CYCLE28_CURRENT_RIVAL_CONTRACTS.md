# Current rival source and local model-loader contract

Status: source capture and a MOCK contract counterexample, not a new retrieval
comparison. Verdict remains PIVOT REQUIRED. All observations below are EMPIRICAL.

The CRISP directory has changed since the frozen retrieval comparison. Its
current source advertises inheritance lookup, embedding-based refusal and query
speed improvements. Those claims have not been reproduced here. The current
directory is not a Git repository, so file hashes identify the captured version.

`cycle28-crisp-current-source-v2` contains 11 files, 133,920 bytes. Its snapshot
manifest SHA-256 is
`ac218827026c7279695721127283c92d9214d93ebd18eaf6ab9257928ea7f38e`.
Existing matched-budget studies continue to use their older frozen source;
they are not presented as results for this newer version. The rival README's
NeuralPack comparison refers to commit `8ec1214`, which predates the current
worktree and tests.

The optional encoder's `available()` method calls both `from_pretrained`
loaders with only the model ID. Its identity advertises a fixed model revision,
but neither loader receives that revision, `local_files_only`, or an explicit
remote-code policy. The method sets offline environment flags with `setdefault`;
pre-existing values of `0` stay `0`.

`cycle28-rival-loader-counterexample-v1/reproduce.py` executes that captured
loader against synthetic loader spies, with socket connections blocked. The
saved report confirms two calls with empty keyword arguments and unchanged
ambient online flags. It makes **zero real model loads, zero network calls and
zero generative calls**. This proves the missing explicit loader contract. It
does not prove that the installed cache has different weights, that a real
network request occurred, or that retrieval is worse. The rival source is left
unchanged.

NeuralPack's existing local backend already supplies the pinned revision,
`local_files_only=True`, `trust_remote_code=False` and safetensors-only model
loading. It checks the returned model revision against an explicit request.
Three additional test cases cover ambient online settings, a cache that happens
to contain the desired revision even when a caller forgets to pin it, and a
loaded revision that differs from the requested one. Nine targeted tests pass.
Two new mutants remove the revision pin or bypass explicit offline loading;
both are caught by assertion failures. The full canonical suite passes 993
tests with two explicit symlink skips; all 105 mutants are killed. The reports
are `cycle28-loader-canonical-full.xml` and
`cycle28-loader-canonical-mutations.json`, bound to 328 current Python sources.

Keep these regression checks. Do not turn a rival's optional-loader weakness
into an answer-quality or performance victory. The next comparison must run
the newer captured source under explicit deterministic and local-model settings,
measure those settings separately, and retain missing-model behavior in scope.
