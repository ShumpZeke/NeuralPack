# Synthetic context corpus v1

This first corpus is a reproducible **synthetic diagnostic**, not a benchmark of real repositories or general model quality. It contains 28 tasks: seven related context variants in each of four categories. No external datasets, personal conversations, credentials, or third-party code are included. Code files are invented source-text fixtures. The one code modification task checks an exact one-line answer; it does not establish executable code correctness.

| Category | Probe content |
| --- | --- |
| `code` | Synthetic files, import/call chains, configuration, numeric near misses, a one-line modification |
| `document` | Rare archive key, manual registry with three-hop reasoning, negation, numeric precision, amendment |
| `conversation` | Timestamped preference changes, tool result, explicit approval, stale/deleted facts |
| `mixed` | Code, issue record, a tool registry, untrusted quoted instruction, strict summary and tool-intent JSON |

Each category has `base`, `exact_repeat`, `prefix_overlap`, `append`, `local_edit`, `delete`, and `reorder`. The repeat reproduces the complete base context and query. A prefix-overlap task replaces part of the final block; append extends the full original context. An edit changes an interior fact or quoted text; deletion removes a relevant fact/permission. Reorder permutes complete blocks, retaining their multiset. These are controlled diagnostics, not estimates of real workload frequencies.

Instructions appear at the beginning, middle, end, and multiple positions. Tasks cover exact needle retrieval, negation, nearby numbers, cross-file/multi-hop lookup, missing facts, chronological updates, output formatting, and read-only tool constraints. The quoted malicious issue text tests preservation of an explicit user-level data/instruction boundary. **No actual tool is called; no claim of system-role adherence or security robustness follows from this text-only test.**

## API and runner integration

```python
from benchmarks.corpus import make_tasks, corpus_manifest, render_prompt
from benchmarks.quality import evaluate, summarize

tasks = make_tasks(seed=1729, padding_blocks=8)
manifest = corpus_manifest(tasks)  # persist with the run; includes exact ground truth
results = []
for task in tasks:
    prompt = render_prompt(task)
    response = model_generate(prompt)  # implement in a model runner
    results.append(evaluate(task, response))
summary = summarize(results)
```

`Task` has `id`, `category`, `context`, `query`, `expected`, `check_kind`, and `metadata`. It is a dataclass and can be serialized with `dataclasses.asdict`. `make_tasks` uses only the Python standard library. `render_prompt` includes only context and query. `expected_response` exists for evaluator unit tests; never give it or the `expected` field to a model.

The example uses a plain-text prompt. An instruction model runner should use its native fixed chat template and record that template plus any system prompt. Submit only the model's newly generated assistant content to `evaluate`, excluding the input prompt, assistant prefix, or echoed conversation. Do not silently clean up markdown, extract a JSON fragment, lowercase answers, or rewrite generated tool output before scoring.

For valid speed comparisons, use identical rendered prompts, tokenizer/model revisions, generation parameters, output budgets, and execution settings in all methods. Measure the complete prompt's token count with that tokenizer. Padding controls source length, **not** token length, and changes the generated corpus fingerprint. Do not truncate to a target token count: doing so can delete the answer or instruction. Increase/decrease `padding_blocks`, record its value and the actual token counts. A changed seed or padding count defines a new corpus; it is not an interchangeable repeat of a run.

The variant metadata records byte overlap with the category's base context. This is **not** a proof of token-prefix or KV compatibility: chat templates, concatenation boundaries, tokenization, position, and earlier context matter. A cache runner must compute its reusable prefix from the actual input token IDs and validate model/runtime identity. On local edit/delete/reorder, do not reuse a downstream causal KV suffix merely because a source block is textually identical.

Run base before each candidate variant when measuring reuse from that base. The returned ordering is a manifest ordering, not permission to treat the preceding variant as the cache parent. Explicitly restore/recreate the base cache for each pair. Keep request order and cache conditions in raw results; a base-to-variant controlled comparison and a rolling conversation experiment are different workloads.

## Evaluation and limits

`evaluate(task, response)` returns `task_id`, `category`, `check_kind`, `passed`, `score` (0 or 1), `format_passed`, `content_passed`, and `reason`. Text answers allow outer whitespace only. JSON and serialized tool intents allow key ordering/whitespace but require the exact declared nested keys, types and values. Duplicate keys, markdown/prose wrappers, nearby numerical values, extra keys, and nonstandard JSON constants fail. Integer `7` is distinct from `7.0`, `true`, and `"7"`. Numeric-string precision is exact. For exact text, content and format are inseparable and their flags equal the overall result. For JSON, `format_passed` means matching key/type structure; `content_passed` requires the complete exact value match.

Report every task's raw answer and score alongside aggregate/category accuracy. A perfect reference-answer unit test is evaluator validation, **not measured model accuracy**. Compare each candidate against raw prefill with paired pass/fail transitions; do not hide regressions behind average accuracy. Add longer contexts, realistic repositories/documents, varied paraphrases, true system-message conflicts, actual tool-call handling, real code tests, and held-out data before claiming broad quality preservation. Twenty-eight highly correlated probes are insufficient for a reliable population-level confidence claim.

Run the independent evaluator/integrity checks from the repository root:

```powershell
python -m unittest discover -s tests -p test_corpus.py -v
```

The tests establish deterministic generation, honest overlap/edit relationships, strict failure cases, and ground-truth serializer consistency. They do not execute an LLM or measure inference latency. Model runs should persist `corpus_manifest(tasks)` together with configuration, git revision, hardware, raw generations, timing records, and full per-task scores.
