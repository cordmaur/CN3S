# Group 1 — calibration records, evaluation, and parameter experiments

Status: implemented; see [outcome](outcome.md). Parent: [research and roadmap](../plan.md).

## Agreed scope

Implement phases A, B and C from the parent plan, plus an interactive offline model
playground in `nbs/dev/04-evaluation.ipynb`. Load the current calibration, display its
evaluation, let the user edit parameters and explicitly run one simulation, and show
the resulting charts and metrics alongside the saved reference. No optimization is
required for experimentation. Continue the already-recorded iteration in this group.

## Design decisions

- Add `CalibrationStore`: immutable UUID/timestamp run folders with input snapshots,
  hashes, provenance, atomic completion and latest/selected pointers. Preserve legacy
  three-file directories in place and expose them as `legacy`; no destructive migration.
  Failed attempts and callback-best recovery are labeled separately from complete fits.
- Add `CalibrationEvaluation`: strict artifact loading, coverage/metrics/baselines,
  rainfall hydrograph, scatter/residual/duration/seasonal/history charts, and explicit
  common-date run comparisons, including D-to-monthly aggregation.
- Add `ModelPlayground`: editable numeric widgets, Run and Reset buttons, reference/
  trial comparison and explicit optional saving as a manual experiment with parent
  provenance. Edits never automatically run the daily model. Keep the reference split,
  forcing, area and observations fixed. Monthly ACT remains zero. Validate parameter
  values before running; isolate each trial in a new model instance. A plain Python
  `run(parameters)` interface works without notebook widgets.
- Use the existing model equations and recurrence for Group 1. A daily simulation
  may still take seconds, but avoids thousands of optimizer evaluations. Scientific
  changes and the numerical-kernel rewrite remain Phase D.
- Split evolution and optional bounded local refinement so phase messages and timings
  are observable with installed SciPy 1.16. Preserve integral ACT, final-best semantics,
  existing default polish behavior and reproducible solver settings. Run the final
  solution once. Recover callback-best on interruption; do not claim exact DE resume.
- The notebook uses one configuration cell and class methods only, with the existing
  autoreload convention. Default to the prepared station 56610000 daily example.
  Widgets use an optional `notebook` dependency extra; package imports stay offline.

## Implementation sequence

1. Store and legacy loading; immutable snapshot/provenance and failure behavior.
2. Optimizer phase instrumentation/recovery and workflow integration, including quality
   maps and backward-compatible latest-summary methods.
3. Metrics and offline evaluation; separate reference/trial comparison masks.
4. Parameter playground and notebook; keep notebook 03 to one configured fit.
5. Focused tests and static checks, execute notebook 04 offline against saved data,
   exercise daily/monthly trial simulations and inspect plotted output.
6. Update guides and group outcome with measured validation and remaining limits.

## Acceptance

- Repeated same-station/frequency fits coexist; selection remains stable. Failed and
  interrupted attempts never replace a successful latest/selected calibration.
- New snapshots remain evaluable after preparation refresh. Legacy results load without
  writes; stale legacy inputs block replay but can still display saved results.
- Evaluation reproduces ordinary saved NSE and handles undefined/empty metrics, missing
  observations, actual coverage, ACT rain alignment, monthly interval durations and
  baseline masks correctly. Forecasting claims are not inferred from fit metrics.
- Notebook 04 executes without optimizer or external provider construction. Changing
  a parameter and pressing Run updates metrics and hydrograph/scatter; resetting restores
  saved values/results. Saved reference files remain byte-identical. Manual experiments
  are distinct runs and never silently become the selected calibration.
- Finalization reuses one final simulation; logs/timings/evaluation counts expose local
  refinement. Positive daily ACT remains integral. Callback-best can be recovered after
  interruption with accurate status and provenance.
- Focused pytest, nonmutating Ruff and strict mypy pass; verify fresh-kernel notebook
  execution and daily/monthly plot rendering. Record any limits in outcome.md.

## Risks and compatibility

Existing callers without a run ID continue to read latest fits and reject stale inputs;
historical evaluation uses explicit IDs and snapshots. Legacy flat files are retained
but new fits are written only into run folders, so direct artifact-path consumers must
use the store. Current notebooks/user edits are preserved except the agreed notebook-03
single-fit cleanup. Selecting repeatedly on held-out results makes them validation data;
the playground will label manual trials as exploratory. No forecasting, regionalization,
equation changes or mass recalibration belongs to this group.

## Decisions recorded during implementation

- Preserve existing legacy three-file directories in place rather than copy/move them.
  New artifacts use the run store exclusively; direct legacy path consumers must use
  `CalibrationStore`. Selected stays explicit; saving manual runs never changes it.
- Recovery records live in `attempts/<run_id>.json`, separate from immutable run bundles.
  A recovered interruption with a completed generation has its own saved run.
- A real SciPy refinement smoke test exceeded `maxfun=30` with 120 calls. Enforce
  `polish_maxfun` in the objective wrapper as a hard model-evaluation limit; when
  reached, retain the DE solution and record the budget stop. This changes refinement
  from the old unbounded SciPy default, with explicit settings and diagnostics.
- Keep watershed bytes from the loaded reference when saving manual runs, so later
  preparation refreshes cannot substitute a different geometry. Hash the parent
  summary and record reference parameters, including for mutable legacy references.
- Use optional ipywidgets numeric fields with an explicit Run action. Display-period
  changes only redraw; editing parameters disables Save until a successful Run.
- Preserve notebook 03 before its single-fit cleanup in this group folder. Notebook
  04 is saved with executed daily outputs; its monthly execution was checked separately.
