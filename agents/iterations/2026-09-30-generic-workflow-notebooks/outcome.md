# Generic basin, preparation, and calibration notebooks — outcome

## Changes

- Replaced the dated notebooks in `nbs/dev` with three reusable notebooks:
  [`01-basin-overview.ipynb`](../../../nbs/dev/01-basin-overview.ipynb),
  [`02-data-preparation.ipynb`](../../../nbs/dev/02-data-preparation.ipynb), and
  [`03-calibration.ipynb`](../../../nbs/dev/03-calibration.ipynb). Each has one
  configuration cell. The dated notebooks, including their user edits and saved
  outputs, are preserved in their matching historical iteration folders.
- Added the thin-notebook rule to [`AGENTS.md`](../../../AGENTS.md). Basin figure
  creation and station selection, preparation coverage, calibration settings,
  parameter and quality tables, artifact validation, and discharge plotting now
  live in package classes.
- `HydroDischargeSource` now borrows an explicitly supplied `Hydrology` instance.
  The preparation notebook constructs one `Hydrography`, one `Stations`, and one
  `Hydrology` and passes them to the workflow. The workflow never constructs or
  closes the borrowed Hydro client.
- `StationCalibrationWorkflow.from_prepared()` creates a saved-data-only workflow
  with no source clients or station network. The calibration notebook uses it to
  read prepared inputs and write a new fit without Azure or MERGE access.
- Monthly simulation requires `act=0`. Monthly optimization searches seven
  parameters and rejects a nonzero monthly `max_act`; daily ACT remains an
  optimizable lag in days. Historical summaries remain readable. The generic
  monthly notebook sets `max_act=0`.
- Updated [`README.md`](../../../README.md) and
  [`nbs/dev/README.md`](../../../nbs/dev/README.md) for the new sequence and
  client ownership. Historical outcome links now point to the archived notebooks.

## Verification

- `pytest -q tests` passed: 20 tests, including saved-only calibration,
  explicit Hydro client injection, and daily/monthly ACT behavior.
- Targeted Ruff checks on changed Python files passed. `mypy src/cn3s` passed.
  `git diff --check` passed. A broader Ruff scan found pre-existing errors in
  `src/hydrography/hydrography.py` and `src/hydrography/otto.py`; those files were
  outside this iteration.
- The basin overview notebook executed from a fresh kernel with no error and
  saved its summary, table, and map. The calibration notebook executed from a
  fresh kernel using saved 66010000 inputs with no error and saved its report
  tables and observed-versus-modeled figure. The figure was inspected and its
  train/test split line corrected and regenerated from the same saved fit.
- The new monthly fit covers prepared rain from 2000-01-01 through 2026-08-01.
  It saved 249 paired training steps and 63 held-out steps, `act=0`, training NSE
  **0.5834**, and held-out NSE **0.7393**. SciPy reported `converged=false`
  within the notebook's 10-generation budget. The result is an executed example,
  not a claim of an optimal or converged calibration.

## Remaining limitations and departures

- The preparation notebook reached its explicit `Hydrology()` construction
  and displayed an Azure device code. Authentication was not completed during
  the live attempt, so the waiting run was interrupted and its partial/error
  outputs were cleared. Its source adapters and preparation path have offline
  fake-provider tests; a fresh live MERGE/Hydro refresh remains to be run with
  the user's login.
- The new fit overwrote the prior current calibration artifacts for station
  66010000 under `/data/CN3S/stations/66010000/calibration/M/`. The prior dated
  notebook and its outputs remain archived. The new fit has lower NSE than the
  prior saved summary, which had held-out NSE about 0.777, and did not converge
  within the shorter notebook budget.
- The generic notebook uses a smaller optimizer budget and one worker than the
  user-edited dated notebook so that a fresh run is practical. The effective
  settings are saved in the calibration summary and visible in the notebook.
