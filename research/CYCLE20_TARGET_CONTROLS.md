# Cycle 20: distinguish retrieval and answering limitations

The eight cycle 18 behavior questions are known. Cycle 19's additional manuals
did not improve their completed Nemotron comparisons. This diagnostic keeps
the questions and executable answer labels unchanged.

**CONJECTURE:** part of the measured error comes from the target configuration
even when relevant source has been supplied. Better retrieval alone may leave
that error unchanged. The diagnostic cannot establish true evidence sufficiency.

The frozen plan uses three inputs per question:

- Original BM25 selection at an 8,192 chars/4 evidence-token cap.
- No source, as an explicit knowledge control.
- Privileged source: whole definitions named by the experiment author, plus
  selected relevant helper declarations. These are literal source excerpts,
  460–3,970 estimated tokens, not a new automatic retriever.

Source comes from the already pinned CPython 3.12.10 commit. All required code
spans occur in the privileged excerpts; that is a coverage diagnostic, not a
proof that all external or C-accelerated semantics are present. Granularity
differs from BM25 windows, so this is not a retrieval-efficiency ratio.

Two target configurations use exactly the same questions and input text:

| Setting | Direct | Reasoning |
| --- | --- | --- |
| Model | `nvidia/nemotron-3-super-120b-a12b` | same |
| Temperature / top-p | 1 / 0.95 | same |
| `enable_thinking` | false | true |
| Maximum output tokens | 2,048 | 16,384 |
| Socket timeout | 90 seconds | 180 seconds |

The [NVIDIA model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
documents the sampling settings and thinking switch; its
[API example](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/build)
uses thinking with a 16,384 output cap. Checked September 7, 2026.
This experiment changes the output allowance and timeout as well as thinking.
It measures a combined configuration and cannot isolate the flag's causal effect.

The direct plan imports 16 exact terminal parent records as REPLAY, including
failed outcomes, and schedules eight new LIVE answers. The reasoning plan
schedules 24 new LIVE answers. No unmeasured remote optimization is hidden in
either plan; each new request is one call to the final answering model.

Frozen identities:

- Direct plan: `8e227389f2dce1432fc94a247fb00ccb3f25a6a7965a2822b5aabc8352262b44`.
- Reasoning plan: `9dc87f6fd27c37fb3fc00937f537c6667f6178e2076c7c0dbd6dfab188baf996`.
- Preparation sources: `4fc872a7a7e5ec79cc303136b457ee8c37622235ac6d69df3a654fafea1b7173`.

Before LIVE execution, source reconstruction, request identity and replay
accounting passed with zero new API calls. The response audit retains invalid
JSON separately from valid JSON that fails the executable task criterion.
Transport failures remain missing. Comparison checks reject mismatched questions,
evidence or caps, and reject duplicate or missing task cells. New mutation
tripwires attack evidence matching and the classification of missing responses.

**PROVED UNDER ASSUMPTIONS:** aggregate answer pass rate alone cannot identify
the contribution of missing evidence. See
[the short non-identifiability proof](math/TARGET_RETRIEVAL_IDENTIFIABILITY.md).

The raw experiment is at
`experiments/runs/packs/cycle20-target-controls-v1`. Final outcomes will be
reported only after the frozen requests reach terminal states. Any improvement
here justifies a next experiment; it does not promote privileged source as a
deployable algorithm or establish a differentiated context optimizer.
