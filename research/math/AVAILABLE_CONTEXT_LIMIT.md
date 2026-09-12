# A limit imposed by missing external behavior

Status of the statement below: **PROVED UNDER ASSUMPTIONS**.
The Click illustration is **EMPIRICAL**, not a claim about all package failures.

## Statement

Assume two execution environments expose identical available context `C`, query
`Q` and target metadata `M` to a deterministic selector. Suppose the correct
answers in those environments differ because of external behavior absent from
those inputs. An answering procedure whose only inputs are that selected
context, query and metadata, and whose behavior is fixed across the two
environments, cannot be correct in both environments.

## Proof

Identical selector inputs produce identical selected evidence. The answering
procedure therefore also receives identical inputs and produces the same answer
in each environment. The assumed correct answers differ, so that single output
cannot equal both. This proves the statement under the stated deterministic,
fixed-information assumptions. It makes no claim about a model's probabilities,
computational complexity, or an optimum context size.

The claim does not apply if a tool, runtime observation, external source, model
metadata or another input distinguishes the environments. It also does not imply
that a model cannot know a particular external library from training. It rules
out a universal guarantee from the available inputs under the assumptions above.

## Concrete diagnostic

**EMPIRICAL:** Click 8.5.0's `NoSuchOption` constructor calls
`difflib.get_close_matches`. Python 3.12.10 returns no matches for the frozen
`--bad` question's `--good` and `--zoom`/`--alpha` candidates, using the default
cutoff of 0.6. The Click-only compiled collection and narrow source controls do
not contain that standard-library implementation. A regression fixture swaps the
external matcher while retaining the exact Click source and original question;
the required answer changes. This is a constructed alternate environment, not a
claim that the normal installed library is defective or was changed on disk.

See `experiments/results/cycle13-external-dependency-counterexample.json` and
`tests/test_evidence_diagnostics.py`. The authoritative audits remain unchanged.

## Architectural consequence

The existing **PROVED** finite-graph result `Closure_D(empty) = empty` describes
failed seed retrieval. The statement here concerns a separate limit: retrieving
within a fixed collection cannot supply absent environmental information.

**CONJECTURE:** explicit detection and acquisition of relevant external
dependency evidence can improve some failures. Test it against baselines given
the same expanded collection and token budgets. A privileged trace control is
not such a deployable algorithm, and a nonempty selection or full package source
is not by itself a proof of sufficiency.
