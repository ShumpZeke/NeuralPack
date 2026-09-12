# Measured input-token and answer-quality curves

**FALSIFIED — the claimed established optimum.** The previous illustration and
claim that NeuralPack operated at an exact Pareto knee lacked an enumerated
frontier or valid quality experiment. The invented zero-error region and
numerical curve are removed.

**EMPIRICAL — replacement measurement.** Freeze tasks and source, sweep explicit
budgets for each method, and record actual provider input tokens and whole-task
success. Plot observed points. Connecting lines guide the eye; they are not
evidence about untested budgets. Full and no-context controls help assess
grounding and model knowledge but are not matched-budget retrieval competitors.

Missing answers stay in the full planned-task table. A comparison restricted to
tasks completed by every method/budget must name that common cohort and its
size. It does not establish missing-task quality. Undefined retention is never
replaced with perfect retention.

**PROVED UNDER ASSUMPTIONS — finite nondominance.** For finitely many measured
points with input cost x and success score y, discard p if another q satisfies
`x_q <= x_p` and `y_q >= y_p`, with at least one strict inequality. The remaining
points are nondominated in that measured set by definition. This is not global
optimality, a minimum context or a knee. It excludes unmeasured compute, output
cost and other objectives unless explicitly included.

**CONJECTURE — broader tradeoff.** More context may help in some workloads and
distract in others. Monotonic quality, linear latency and a zero-distortion
threshold must each be measured, not assumed.

See [EVOLUTION_LOG.md](../../EVOLUTION_LOG.md) for current evidence and limits.
