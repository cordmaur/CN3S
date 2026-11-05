# Simplify optimizer and parameter selection

## Objective
Discuss a local refactor that reduces optimizer indirection and allows any subset of calibration parameters to be optimized while all remaining parameter values stay fixed. Implementation authorized by the user and completed in this iteration.

## Recommended approach
- Move CN3SParams to src/cn3s/params.py; preserve its dataclass and ordinary numeric parameter values. Update model.py, optim.py, and package re-exports. Keep public `from cn3s import CN3S, CN3SParams` working.
- Put an instance bounds dictionary on CN3SParams using dataclass field(default_factory=...). Include all eight calibration parameters, including act=(0, 30), in the existing canonical order. Each instance gets its own dictionary. Bounds are calibration search choices, not scientific validity limits; preserve current ranges. Area, name, and warmup_steps remain descriptors outside this dictionary. Avoid new parameter wrapper classes or configuration frameworks.
- Add `optimize_params: tuple[str, ...] | None = None` to CN3SOptimizer. None means all calibration names in bounds order; an explicit tuple names only the free parameters. All other values come from the initial CN3SParams. Prefer this to separate fixed-value dictionaries that duplicate values already in params, or bounds containing mixed tuple/None entries.
- Replace max_act with params.bounds['act'] changes. Derive candidate vectors, bounds, and integrality from the same selected-name sequence; act remains integer when selected, with days for daily runs and calendar months for monthly runs, matching the existing model behavior. Names must exist in the known calibration fields, be unique, and include at least one free parameter; reject invalid selections briefly.
- At the start of each optimize() call, snapshot the current model.params, including a copied bounds dictionary, and build the selected bounds/integrality vectors from that snapshot. This lets a second run start from the currently calibrated state. Reconstruct each candidate with dataclasses.replace(initial_params, **updates). Preserve fixed values and descriptors rather than rebuilding from CN3SParams defaults. Convert act explicitly to int when it is free.
- Default SciPy x0 to the selected values in the run's CN3SParams snapshot, in exactly optimize_params order. Construct it once before any candidate evaluation mutates model.params. Reuse this same snapshot for fixed values throughout the run. Pass the default through optimize()'s existing defaults dictionary; explicit optimize(x0=[...]) overrides it via de_kwargs, and explicit x0=None requests SciPy's ordinary population initialization without injecting the current parameter state. No new x0 constructor argument is needed.
- Check that a supplied/default x0 has one value per selected parameter, is finite and within selected bounds, and has integer ACT when ACT is selected. Raise a clear error rather than silently clipping or changing the researcher's starting values. Fixed parameters are not included in x0 and need not lie within unused search bounds.
- Add only a small `_params_from_vector` helper if useful: callback, model execution, and history all need exactly the same free-vector interpretation. Retain `_run_model` because it represents a visible scientific workflow.
- Remove `_validate_and_assign_inputs`; retain the small necessary train_ratio check inline in __init__. Drop max_act validation alongside max_act.
- Remove `_resolve_objective`; accept Objective instances directly with the existing default. Custom functions remain possible via Objective(fn). Remove string lookup and automatic callable wrapping; identify/update repository call sites that depend on them.
- Remove `_persist_model`, a one-call wrapper. Merge `_nse_on_subset` into `_nse` if it still only forwards arguments. Keep train/test subset selection as one shared operation and avoid unrelated workflow changes.
- Store complete CN3SParams snapshots and full calibration columns in history, even when candidate vectors are partial. History replay and plotting should run those full snapshots directly, not interpret full history vectors as free vectors. Retain a short column-based recovery path only if existing saved histories require it. Reuse evaluation results for plots where possible while preserving simulated dates without observations.
- Exclude bounds metadata from parameter plot labels. Update or remove the positional from_vector/as_list utilities based on existing call sites; do not add a parallel generalized vector API without a need.

## Implementation scope
Primary files: params.py (new), model.py (move/import and bounds-label exclusion), optim.py (refactor), __init__.py (re-export). Update only affected notebook imports/calls when removing max_act or string objectives. No new dependencies, new class hierarchy, or formal test suite.

## Verification
Temporary checks: all eight free parameters; exactly three free with five fixed; integer ACT free and fixed; independent instance bounds; preserved basin name/area/warmup and baseline values across repeated candidates; correct aligned bounds/vector/integrality/x0 order; default x0 from the current state at each run; explicit x0 override and x0=None; invalid initial guesses; full history replay; callback/finalization and interruption retaining the best recorded candidate; invalid/empty selections. Run appropriate Ruff/type checks and a representative small calibration. Preserve chronological state propagation. Inspect existing notebook saved histories before removing old import/vector paths.

## Findings and discussion
There are currently eight optimizable parameters (r0, cn_i, alfa, beta, k0, k1, k2, act), despite the dataclass description saying six. Fixed eight-element reconstruction occurs in model runs, history, evaluation, and plotting. Candidate reconstruction currently preserves area/warmup but resets name. Plot labels iterate every dataclass field, so bounds need explicit exclusion. Current finalization restores the returned solution, while interrupt handling does not visibly restore the last callback candidate; check this while preserving the intended behavior. Do not broaden into scientific equation changes.

Discussion update: use current CN3SParams as the default x0 source, with a fresh snapshot at the start of each optimize() call. This also clarifies repeated runs: updated model parameters seed the next run, while fixed values stay unchanged throughout a given run. SciPy x0 seeds one member of the differential-evolution population; it does not initialize the entire population around that point or guarantee local search. Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html#scipy.optimize.differential_evolution

The central choice is selection style. Recommended: optimize_params explicitly lists free parameters and omitted names retain their current values. Alternative: bounds entries use None for fixed parameters, which shortens constructor arguments but mixes search limits with selection state. Discuss before implementing.

## Session record
- Moved CN3SParams and its legacy full-vector helpers to params.py. Kept helpers because the scratch notebook and column-based history loading still use them. Added independent per-instance bounds, including ACT, and excluded bounds from parameter plot labels.
- Removed _validate_and_assign_inputs, _resolve_objective, _nse_on_subset, and _persist_model. Objective selection now uses instances directly, with Objective(fn) for custom functions. Necessary checks remain inline.
- Implemented optimize_params, dynamic free vectors/bounds/integrality, per-run snapshots, current-state x0 defaults, explicit x0 overrides, and x0=None. Fixed parameters and basin descriptors are preserved by dataclasses.replace. ACT stays an integer and uses the model's existing frequency-specific units.
- History stores complete snapshots. Replay works independently of the current free selection, including older column-only records and parameter pickles from cn3s.model lacking bounds. The old module import stays available for saved pickle resolution.
- Model results retain dates without observations, while scoring uses paired discharges. plot_step reuses the evaluation run. Finalization restores the returned solution or last completed generation after interruption; before the first completed generation it restores the run's starting snapshot.
- Migrated nine max_act notebook cells across five notebooks to model.params.bounds['act']; changed only affected source arrays and preserved outputs/metadata. Notebook cells parse. Pre-existing missing freq arguments in older Daily notebooks were not broadened into this refactor.
- Representative temporary checks passed for three free/five fixed parameters, all eight free parameters, ACT-only optimization, non-canonical parameter order, independent bounds, descriptor preservation, repeated-run x0 defaults, explicit override/None, invalid selections/guesses, full/legacy history replay, old pickles, single-run plotting, and interruption recovery. Actual daily, monthly, and two-worker continuous/integer calibrations passed.
- Ruff lint/format and diff whitespace checks passed. Strict mypy passed for params.py and optim.py. The full package reports one pre-existing model.py date-offset assignment error; the installed mypy also warns about an existing unsupported strict_equality_for_none configuration option. Neither unrelated issue was changed.
- An initial parallel check invoked from stdin failed under the environment's forkserver start method; it was stopped and repeated successfully from a guarded temporary script. No formal test suite or dependencies were added. Temporary verification scripts were removed.

- ACT integrality follow-up: confirmed the mask is derived from optimize_params and passed explicitly to SciPy. Raw-vector checks with ACT first, middle, last, and omitted cover search and polishing, rather than relying on the parameter conversion's rounding. Found installed SciPy 1.18.1 could emit integer 0 outside requested fractional ACT bounds (0.2, 3.8). Normalize selected ACT limits to (ceil(lower), floor(upper)) and reject intervals containing no integer before calling SciPy. This preserves requested permissible integers and uses SciPy integrality throughout. No formal tests added. Reference: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html

## Proposed method-call examples
Implemented API examples:

```python
from cn3s import CN3S, CN3SOptimizer, CN3SParams, Objective, Objectives

params = CN3SParams(area=34334.0, alfa=0.2, beta=0.002, act=0)
params.bounds["act"] = (0, 15)
params.bounds["cn_i"] = (1, 100)
model = CN3S(params, freq="M")

optim = CN3SOptimizer(
    prec=prec,
    observed_q=observed_q,
    model=model,
    optimize_params=("cn_i", "k1", "k2"),
    objective=Objectives.ExtremeFlowBlend,
)
# Automatically uses current [cn_i, k1, k2] from model.params as x0.
optim.optimize(maxiter=100)

# Alternatively, provide the selected values explicitly, in the same order.
optim.optimize(x0=[7.35, 0.316, 0.305], maxiter=100)

# Explicitly opt out of seeding with the current parameter values.
optim.optimize(x0=None, maxiter=100)

# Optimize all eight with the same parameter-owned bounds:
optim_all = CN3SOptimizer(prec=prec, observed_q=observed_q, model=model)

# Explicit custom objective adapter (no automatic resolution):
custom = Objective(my_objective)
```
