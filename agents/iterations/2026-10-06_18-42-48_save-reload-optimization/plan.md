# Save and reload optimization results

## Objective
Plan a simple workflow to save a completed optimization, include descriptive metadata and complete history metrics, and reload calibrated parameters independently of precipitation/observations or the optimizer. Implementation authorized by the user; implemented and verified in this iteration.

## Proposed approach
Use one readable JSON file with three keys: params, metadata, history. No new classes, persistence framework, or dependencies.

- params: complete CN3SParams values and bounds, including basin name/area, warmup_steps, and integer ACT. Store the actual final model parameters, including a polished solution when present.
- metadata: saved timestamp with timezone; objective name and relevant settings (e.g. quantiles, weights, discharge_floor; reference-derived thresholds/scales if a fixed discharge reference was used); free parameter names; model frequency and ACT units; train_ratio and cutoff date; solver settings such as actual x0, seed, maxiter, popsize, tol, and polish; actual completed generations, evaluation count, termination/interruption status, and final train/test objective and NSE. Keep metadata descriptive rather than trying to deserialize arbitrary custom objective code. Persist resolved solver settings at run start because optimize(**kwargs) currently discards them after the call.
- history: scalar records including step, complete calibration values, four metrics, and a stage identifying initial, generation, or final. Omit the Python params object column; existing scalar parameter columns already suffice for historical reconstruction with saved basin descriptors.

## Recalibration with another objective
User approved the single-file save/load workflow and excluded a parameters-only export. Loading CN3SParams into a new model/optimizer with a different objective is supported by the proposed workflow: the current parameter values supply the new run's default x0; keep the same forcings, frequency, and training cutoff for controlled comparisons. Save this second calibration to a separate JSON.

SciPy differential_evolution x0 seeds one member of the initial population, whose other members cover the allowed bounds. This is a fresh global search rather than a local refinement centered on x0. Bad individual candidates at the beginning are expected. For deterministic, finite scoring on the same rows and objective, with a feasible x0 and no extra constraints, the generation-best training loss should not be worse than the same objective evaluated at x0. Scores from different objectives are not directly comparable.

For a focused second-stage refinement, reuse existing APIs: select only the parameters to adjust, keep ACT fixed if desired, and narrow those parameters' bounds around the loaded solution. Example half-width: 10% of each original bound interval, clipped to the original interval. This example width is an experimental choice, not a universal scientific rule. A custom nearby init population is another existing SciPy option, but initial proximity alone does not restrict later exploration. Do not add a local-solver mode in this iteration; a genuine local method for continuous parameters with fixed ACT can be discussed separately if needed. SciPy polish=True refines the same objective supplied to that run, rather than switching objectives automatically.

Record an initial row when x0 is supplied/defaulted: full parameters reconstructed from that x0, training loss before search, and test/NSE metrics filled during finalization. This makes the starting score visible, supports comparison under the new objective, and does not count as a generation. With x0=None, omit the seeded initial row. Actual generation counts continue to come from solver iterations/completed callbacks, not history length.

Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html

Polishing clarification: inspected installed SciPy 1.18.1. After DE, polish=True starts a local L-BFGS-B minimization from the final population's best candidate, using the same objective and bounds. Additional explicit constraints select trust-constr. ACT is fixed at its DE-selected integer value; all-integer searches skip polishing. The local result replaces the DE solution only when its loss is lower, local minimization reports success, and parameters stay within bounds. Extra polishing evaluations are included in result.nfev but are not new DE generations/callback records. The current optimizer catches KeyboardInterrupt before SciPy returns; that recovery path restores the last completed generation without running polishing. This supports retaining a separate final row in the planned save workflow. No code changes.

## Metric population and finalization
Callbacks continue to record training loss without an extra simulation. Each run records an initial row when x0 is supplied and preserves a final parameter snapshot at exit. A distinct final row holds all four metrics, including the polished solution when available. Initial/final rows do not count as solver generations.

Following the user's implementation instruction, history completion is explicit and lazy: populate_history() evaluates only incomplete rows once, fills test objective and train/test NSE, and restores/re-evaluates the final solution. save() calls it automatically before writing. This also supports saving existing in-memory runs without repeating calibration. Repeated saves do not append duplicate final rows.

Test scores report performance without guiding the search. Numerical nonfinite/unavailable scores remain explicit in memory and become standard JSON null values in the artifact. SciPy nfev records solver evaluations, excluding the additional reporting simulations.

## Minimal API
- CN3SOptimizer.save(path): explicitly write the current run artifact after optimization; no automatic output paths or saving during optimization. Require a finalized run so saved params/summary correspond to the saved optimization, rather than a model altered later by plot_step or manual exploration. Keep a final params snapshot with final metrics at exit and save that snapshot.
- CN3SParams.from_file(path): read the params envelope from the saved optimization JSON, convert bounds lists back to tuples, and construct CN3SParams. No optimizer/model reconstruction or schema migration framework.
- Reload history manually from the JSON scalar records into pandas if needed. No CN3SOptimizer.load API required for the requested scope.

## Scope and verification
Modify params.py and optim.py only, unless an affected notebook example is requested. Temporary checks: parameter/bounds/int-ACT round trip; save/load into a fresh optimizer with a different objective; initial x0 row and best-loss comparison under that objective; partial optimization and final row; polished final versus last generation; zero-generation and interrupted runs; filled four metrics on all history rows; model remains at final parameters after replay; save stays tied to final result after later history exploration; true generations versus appended history row count; objective settings metadata and x0 settings; valid standard JSON with unavailable scores; standalone parameter load without input data. No formal suite or new dependency.

## Session findings
- add_history writes callback records with test_objective/train_nse/test_nse all None when df=None.
- evaluate_step already fills all four metrics but mutates model state to the requested historical step.
- optimize finally restores the final solution but currently discards that run's DataFrame and does not write final metrics/history.
- SciPy polishing can make final result.x differ from the last callback, so saving history.iloc[-1] alone is insufficient today.
- The user changed default ACT bounds to (0, 5) after the refactor; leave those current values untouched.

## Implementation session record
- Added CN3SParams.from_file(path), requiring station/basin name and drainage area from the saved params envelope rather than using defaults. It restores all values, bounds as tuples, warmup_steps, and integer ACT. No parameters-only export was added.
- Added populate_history() and save(path). Save completes scalar history, exports one JSON with params/metadata/history, creates destination parents, and leaves the model at the preserved final calibration. History records include stage=initial/generation/final; object params columns are excluded from JSON.
- Run metadata captures actual x0, selected names/bounds/integrality, relevant solver defaults/overrides, frequency/ACT units, cutoff, termination status, iteration count, and solver evaluation count. Save includes objective name/settings (plus reference thresholds/scales for ExtremeFlowBlend), final metrics, and a timezone-aware America/Sao_Paulo timestamp. Execution objects/custom code are described rather than serialized as executable code.
- Existing in-memory runs can be saved after autoreload, without another optimizer run. For those runs, metadata unavailable from the previous implementation is not invented. Scalar/name/area data remain complete. Normal, zero-generation, and interrupted runs are supported; failed runs are rejected.
- Representative temporary checks passed: real optimization and parameter/name/area/bounds round trip; identical discharge after reload; all four history metrics filled; initial/final stages and correct generation counts; repeated save without duplicate final rows; saving after inspecting earlier history; existing pre-save in-memory runs; loading and recalibrating with another objective; polished solution distinct from callback; interruption; standard JSON null scores; missing name/area rejected.
- The first numerical round-trip comparison encountered the model results' existing object dtype; converting comparison inputs to float arrays verified equal discharge without modifying the model.
- Ruff lint/format, diff whitespace checks, and targeted strict mypy passed. Installed mypy warns about the existing unsupported strict_equality_for_none option. No formal suite, new dependencies, unrelated notebook changes, or model-equation changes were introduced.

## Proposed method-call examples
Implemented API examples:

```python
from cn3s import CN3S, CN3SParams

optim.optimize(maxiter=100)
optim.save("results/porto_uruacu_optimization.json")  # fills missing history metrics

# Quick future use: no optimizer or calibration inputs needed.
params = CN3SParams.from_file("results/porto_uruacu_optimization.json")
model = CN3S(params, freq="M")  # frequency is also recorded in run metadata

# Focused second calibration using another objective (proposed file API).
from cn3s import CN3SOptimizer, Objectives

FREE_PARAMS = ("k1", "k2")
for name in FREE_PARAMS:
    lower, upper = params.bounds[name]
    center = getattr(params, name)
    half_width = 0.1 * (upper - lower)
    params.bounds[name] = (max(lower, center - half_width), min(upper, center + half_width))

refinement = CN3SOptimizer(
    prec=prec,
    observed_q=observed_q,
    model=CN3S(params, freq="M"),
    optimize_params=FREE_PARAMS,
    objective=Objectives.ExtremeFlowBlend,
)
refinement.optimize(maxiter=30)  # x0 defaults to the loaded k1/k2 values; ACT stays fixed
refinement.save("results/porto_uruacu_refinement.json")

# Optional history inspection.
import json
from pathlib import Path
import pandas as pd

run = json.loads(Path("results/porto_uruacu_optimization.json").read_text())
history = pd.DataFrame(run["history"]).set_index("step")
metadata = run["metadata"]
```
