# Group 1 outcome

Implemented on 2026-09-30: phases A, B and C plus the requested manual parameter
interface. [Group plan](plan.md) · [parent roadmap](../plan.md).

## Delivered

- **Immutable calibration runs.** `CalibrationStore` writes unique timestamp/UUID
  run folders with summary, history, full simulated dates, rainfall/discharge/metadata
  snapshots, watershed when available, source/version provenance and artifact hashes.
  Files are staged before committing; latest moves only for completed calibrations.
  Explicit selection stays stable. Failed attempts and callback-best recovery are
  separate JSON records. Existing flat legacy calibrations remain untouched and
  load as `legacy`; direct file readers must use the store for new runs.
- **Offline evaluation.** `CalibrationEvaluation` reads saved results, checks bundle
  integrity and identity, reports actual coverage and original/recomputed scores,
  and provides rainfall/discharge, scatter, residual, duration, seasonality and
  optimizer-history plots. NSE, original KGE/components, RMSE, MAE, signed bias and
  calendar-weighted volume bias have explicit undefined-value reasons. Baselines use
  training monthly climatology and prior-calendar-day persistence. Comparisons use
  common pairs; D/M comparison aggregates complete daily months and checks observed
  values agree. No fitting is needed to evaluate a persisted run.
- **Parameter playground.** `ModelPlayground` provides plain Python `run`, `reset`,
  `comparison`, and explicit `save` methods, plus lazy ipywidgets controls. Run performs
  one simulation in a fresh model instance. Reference forcing, area and split stay
  fixed; editable parameters include initial storage, CN, alpha/beta, recession/
  recharge parameters, daily ACT and antecedent length. Monthly ACT remains zero.
  Parameter edits disable Save until a successful Run. Changing the displayed period
  redraws without simulation. Manual saves are labeled child runs with parent summary
  fingerprint/reference parameters and cannot change latest or selected calibration.
- **Observable calibration.** Evolution, bounded local refinement, final simulation,
  scoring and artifact writes are reported separately. Settings, timings, termination,
  evaluation counts and pre/post refinement objectives are stored. Local refinement
  holds integer ACT fixed and has a hard evaluation cap. Exhausting it keeps the DE
  solution. Final-best simulation runs once, and scoring uses that same result.
  Interrupts after a completed generation recover callback-best into an explicitly
  interrupted run without replacing a complete calibration.
- **Notebook 04.** [04-evaluation.ipynb](../../../../nbs/dev/04-evaluation.ipynb)
  is a thin, offline entry point with one configuration cell. It is saved with executed
  daily evaluation outputs for station 56610000 and the parameter controls. Run all
  cells to activate the controls in a live kernel. Use the run table to select an
  explicit saved ID; default `latest` also supports legacy results.
- **Notebook 03 and guides.** Notebook 03 now performs one configured fit, exposes
  run labeling/refinement budgets, and clears obsolete outputs. Its prior source and
  outputs are preserved in [03-calibration-before-group1.ipynb](03-calibration-before-group1.ipynb).
  README and the development notebook guide document the new artifact/API contracts.
  `pip install -e ".[notebook]"` installs the optional widget/kernel dependencies.

Implementation modules:
[artifacts.py](../../../../src/cn3s/artifacts.py),
[evaluation.py](../../../../src/cn3s/evaluation.py),
[playground.py](../../../../src/cn3s/playground.py),
[optim.py](../../../../src/cn3s/optim.py),
[workflow.py](../../../../src/cn3s/workflow.py),
[metrics.py](../../../../src/cn3s/metrics.py).

## Verification

- `python -m pytest -q -p no:cacheprovider tests`: **42 passed in 18.56 seconds**.
  Covers run coexistence, explicit selection, failed writes, hash corruption,
  refresh-safe snapshots and watershed provenance, manual-run isolation, ACT rainfall
  dates, undefined metrics, leap-February volume weighting, complete-month comparison,
  persistence gaps, widget Run/Reset, no optimizer/provider construction, final
  simulation reuse, interruption recovery and hard refinement limits.
- Ruff checks passed on `src/cn3s` and the three changed/new test modules. Strict
  `mypy src/cn3s` passed on nine source files. `git diff --check` passed.
- Notebook 04 executed all **16 code cells** in a fresh kernel against saved daily
  inputs. A separate monthly configuration also executed successfully; its execution
  artifact is in `/tmp`, not a second repository notebook. No live provider was used.
- AST checks confirmed notebooks 03/04 contain no loops, conditionals, assertions or
  comprehensions in code cells; orchestration/plotting remain in package classes.
- Real full-record parameter replay for 56610000 reproduced saved NSE at both
  frequencies: daily **0.6466167593**, monthly **0.8317401674**. The current daily fit
  differs from the earlier parent-plan inventory; validation used the current saved
  summary and verified replay against that exact reference.
- Reducing K1 by 10% produced distinct trial curves/scores. The edited daily simulation
  took **4.47 seconds** and the monthly simulation **0.27 seconds** on this environment.
  These measure individual simulations, not a general performance guarantee.
- SHA-256 checks before/after those trials confirmed the real station's existing
  calibration artifacts were unchanged. No production calibration was rerun or saved.
- Daily/monthly trial hydrographs and daily scatter were rendered and visually
  inspected. Rain falls from an inverted upper axis; flow and rainfall units are
  labeled and the saved reference/trial can be distinguished.
- A real 40-day, two-worker SciPy DE/refinement smoke run exercised multiprocessing
  and phase reporting. SciPy's native `maxfun=30` initially allowed 120 evaluations;
  that observation prompted the explicit hard-cap implementation and regression test.
  Repeating the real smoke run after the fix used exactly **30 local evaluations**
  (32 DE evaluations), reported the budget stop and retained the DE solution. Local
  refinement took 1.28 seconds in that small diagnostic.

## Decisions, compatibility and remaining limits

- Legacy results are preserved in place instead of physically migrated. New snapshots
  remain evaluable after data refresh. Legacy replay requires matching current inputs;
  stale legacy paired results remain inspectable but do not borrow newer forcing.
- CalibrationStore is the contract for new artifact paths. Existing workflow report
  calls still resolve latest and reject stale current inputs; explicit-ID evaluation
  supports historical snapshots. Quality maps honor explicit selected runs, otherwise
  latest, and still require matching current input revisions.
- The optional polishing phase now uses an explicit L-BFGS-B budget rather than the
  old unbounded SciPy default. This can change final fitted values when a budget is
  exhausted. It is recorded in settings/diagnostics; no older fit is silently replaced.
- Recovery is callback-best restart, not exact DE population/RNG continuation. Before
  the first completed generation there is no best callback to recover. Hard process
  termination may leave a running attempt record; a second interrupt during final
  simulation propagates. Interrupted local searches retain the completed DE solution.
- Saved scoring is separate from recomputed evaluation. Legacy monthly inputs lack
  immutable daily-coverage information, which is labeled in coverage output. The
  underlying monthly aggregation/physics and constant-series optimizer behavior were
  not redesigned in Group 1; the new evaluator reports undefined NSE/KGE explicitly.
- A full daily simulation still takes seconds. The model recurrence and equations
  are unchanged; the numerical-kernel optimization and scientific audit remain Phase D.
- Notebook widget controls require a live kernel/frontend with ipywidgets support.
  Button callbacks were exercised programmatically, and notebook outputs were executed;
  no browser-based frontend automation was performed. Plain Python methods provide
  the same simulation/comparison behavior without widgets.
- Forecast providers, state continuation, independent skill benchmarks and ungauged
  transfer are not implemented here. Phases D–H remain unassigned to future groups.
  Repeated manual tuning on test dates is exploratory validation, not independent
  evidence of forecasting skill.
