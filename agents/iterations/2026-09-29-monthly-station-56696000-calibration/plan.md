# Monthly calibration of station 56696000 — plan

**Status:** implemented and verified; see [`outcome.md`](outcome.md). The user changed the window to five calendar
years. Live Hydro observations end at 2023-12-31, so the selected calibration
window is 2019-01-01 through 2023-12-31. The user then changed the calibration
frequency from daily to monthly; the unfinished daily refinement was stopped.

## Objective and background

Calibrate CN3S for station **56696000 (MARIO DE CARVALHO)** at a monthly step over
**2019-01-01 through 2023-12-31**. Save the calibration configuration, parameters,
modeled discharge, and train/test quality, and create an executed development notebook
in [`nbs/dev/`](../../../nbs/dev/). The notebook should let a reader inspect the
result from a fresh kernel and saved outputs.

The one-station workflow was introduced in the
[station calibration outcome](../2026-09-29-station-calibration-workflow/outcome.md).
The [basin overview outcome](../2026-09-29-basin-overview-telemetric-stations/outcome.md)
added the current telemetric station loader and watershed assignment. The
[initial notebook](../../../nbs/01-Initial_Tests.ipynb) is an exploratory sketch,
not an end-to-end calibration example. Current package behavior is in
[`workflow.py`](../../../src/cn3s/workflow.py),
[`optim.py`](../../../src/cn3s/optim.py), and
[`model.py`](../../../src/cn3s/model.py).

## Agreed requirements and boundaries

1. Use the telemetric record keyed by textual `ESTCODIGOADICIONAL == "56696000"`,
   after the established RHN/responsible/status filters, and its assigned BHO
   2017 5k watershed. Fetch **MERGE monthly rainfall** and use the authenticated
   **Hydro daily discharge**, aggregated to monthly means; do not substitute
   synthetic observations.
2. Prepare monthly inputs for the inclusive 2019–2023 window and calibrate monthly CN3S
   for that station. The station's summed upstream `nuareacont` area is the model
   area, as in the existing workflow.
3. Persist calibration settings and the final fitted parameters, training and
   held-out quality metrics, optimizer history, and modeled series in the station's
   folder. The development notebook must display the configuration, data coverage,
   quality scores, and an observed-versus-simulated discharge plot, with outputs
   saved after a fresh-kernel run.
4. Focus on one station. Coupling every calibration to `BasinOverview`, basin-wide
   quality maps, a further daily refinement, and other stations are out of scope.

The user first selected daily calibration, shortened the window to five years,
then changed the frequency to monthly. They asked for live sources and an executed result, and offered
to enter Azure authentication when execution reaches Hydro. We first prepared
2021–2025 under a stated assumption; the authenticated Hydro record contains
complete daily values only through 2023. We selected 2019–2023 to provide five
observed calibration years. The first daily fit (10 generations, no polishing)
had training NSE -0.060 and held-out NSE 0.384. A planned polished daily run was
stopped when the user changed frequency. The optimizer budget
and exact plot layout are implementation choices; they were not supplied as requirements.

## Current behavior and gap

- `StationCalibrationWorkflow.prepare_station()` can assign an upstream watershed,
  fetch MERGE monthly rain, fetch Hydro daily discharge, aggregate it to monthly
  means, and save the inputs.
  `calibrate_station()` saves `summary.json`, `history.parquet`, and `modeled.parquet`.
  The summary has `params`, `rain_period`, `objective`, `train_ratio`,
  `warmup_steps`, `train_nse`, `test_nse`, and an input revision. It does not yet
  persist every effective optimizer option or the chosen ACT bound. The notebook
  should make the full run configuration inspectable and durable.
- The telemetric source has two rows with station key 56696000; the RHN row is
  `ESTCODIGO=193142390`, has `ESTSTATUS=0`, and is present in the saved Doce
  overview. `Stations.assign_cobacia()` supplies the required watershed reference.
  This source has no `AreaDrenagem` or `RIO`; a one-station calibration does not
  require either. The workflow will save `area_station_km2` as null.
- `/data/CN3S/stations/56696000/` now contains 2019–2023 daily MERGE and
  authenticated Hydro discharge, plus the first daily calibration. The local
  `mergedownloader` lacked the imports expected by the original workflow;
  its current `open_file` API is now used for both daily and monthly rainfall.
- **Monthly ACT:** observed monthly discharge is indexed at month starts, while
  nonzero `act` moves simulated dates by days. Set `max_act=0` for this monthly
  run so every modeled month aligns to the corresponding observed month.

## Proposed design and data flow

1. Construct `Hydrography` from the two BHO GeoParquets, then `Stations` from
   `/data/CN3S/Estacoes_Telemetricas.parquet`, call `assign_cobacia()`, and verify
   station 56696000 is uniquely assigned. Pass it to `StationCalibrationWorkflow`.
   This uses existing station infrastructure without requiring `BasinOverview`.
2. Repair `MergeRainSource` against the installed downloader API, preserving its
   injectable `RainSource.fetch(area, start, end, frequency)` interface and current
   cache location. The first annual daily-cube preparation was killed by memory pressure
   after saving 2021 and 2022 rain. Seven-day cubes still retained too much memory
   in the downloader's file cache; clipping each full daily grid also caused
   sustained memory growth. Select the watershed's raster window before clipping
   each source file, clear the file cache after each value, and cover both
   daily and monthly adapter paths with a focused offline test.
3. Prepare `("M",)` rainfall and discharge for the selected window. Keep the
   existing `stations/56696000/` storage contract and source provenance.
   Inspect monthly coverage, missing observations, and overlap before optimization.
   If the live record is too sparse, record the limitation and discuss any scope
   change before claiming calibration quality.
4. Fit with `PlainNSE`, three warmup steps, and an 80/20 chronological split unless
   data inspection motivates an explicit documented adjustment. Use a fixed random
   seed and a bounded, stated optimizer budget; inspect convergence, paired counts,
   and finite training/test NSE. Record effective optimizer settings, ACT bound,
   split date, and paired sample counts with the saved summary, using a backward
   compatible summary extension.
5. Add `nbs/dev/02-2026-09-29-monthly-station-56696000-calibration.ipynb` with the
   existing autoreload convention. It should show selected station/watershed,
   source data coverage, fit settings and saved parameters, quality metrics,
   observed and modeled discharge with a visible train/test boundary, and paths to
   persisted artifacts. Keep reusable behavior in package modules, not notebook
   helpers. Update `nbs/dev/README.md` and project documentation if behavior changes.

Affected files are likely `src/cn3s/workflow.py`, `src/cn3s/optim.py`, focused workflow tests, the new
development notebook, `nbs/dev/README.md`, and possibly `README.md`. The saved
station assets live under `/data/CN3S/stations/56696000/`, outside the repository.
Existing station folders and calibration summaries must remain readable.

## Implementation sequence

1. Check station assignment and installed MERGE API details without changing data.
2. Fix the MERGE adapter and add focused coverage for the compatibility gap.
3. Run live preparation and validate rainfall/discharge coverage and provenance.
4. Extend the saved calibration summary only as needed to capture effective settings;
   preserve the station name when the optimizer rebuilds parameter objects;
   fit station 56696000 with a reproducible seed and assess the held-out result.
5. Write and execute the notebook from a fresh kernel, save its outputs, and inspect
   its tables and plot. Document the result and any limits in `outcome.md`.

## Validation and acceptance criteria

- Focused pytest, targeted Ruff, and mypy checks pass for changed Python code.
- The prepared rain has one valid value for every requested month, or any source
  coverage gap is surfaced clearly. Hydro observations are genuine live records;
  the overlap and train/test sample counts are reported.
- Station `summary.json` contains the chosen configuration, fitted parameters,
  input revision, and finite train/test quality where the source data support it;
  `history.parquet` and `modeled.parquet` are readable and correspond to that run.
- The new notebook executes without error from a fresh kernel and saves real
  numerical output and a quality plot for 56696000. The saved notebook and
  `outcome.md` state the actual NSE, date coverage, convergence status, and any
  limits; no check or live result is reported as passed before it runs.

## Open decisions, assumptions, and risks

- **Azure access:** Hydro initialization may request interactive device-code login.
  Live credentials are outside the repository. If access fails, the requested live
  result cannot be replaced silently with synthetic or historical data.
- **MERGE API:** The installed downloader differs from the current import path.
  Its monthly return shape and availability over 2019–2023 need validation with
  real requests. The raw monthly MERGE cache contains the proposed years.
- **Optimizer cost:** A five-year monthly run is shorter than the daily run, but
  Select and report a feasible budget, seed, convergence status, and resulting
  quality rather than imply that optimizer termination proves a good calibration.
  The monthly notebook will use `max_act=0`, seed 42, up to 60 generations,
  population size 8, and SciPy polishing; report its actual convergence and NSE.
- **Source identity:** The telemetric key 56696000 is assumed to be the Hydro
  `EstacaoCodigo` used for discharge lookup. Verify from the live query result.
