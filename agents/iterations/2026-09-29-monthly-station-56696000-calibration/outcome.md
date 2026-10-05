# Monthly station 56696000 calibration — outcome

## Result

The [development notebook](02-2026-09-29-monthly-station-56696000-calibration.ipynb)
was executed from a fresh kernel and saved with its station table, input coverage,
calibration configuration, fitted parameters, quality table, and observed-versus-modeled
monthly discharge plot. It calibrates station **56696000 (MARIO DE CARVALHO)** over
**2019-01-01 through 2023-12-31**. The live Hydro record ends at 2023-12-31; this
window provides five complete calendar years of observed discharge.

The prepared inputs have **60 monthly MERGE rainfall values and 60 monthly mean Hydro
discharge values**, with no missing months. The upstream `nuareacont` area is
**5,296.857 km²**. Monthly MERGE rainfall matches the sums of prepared daily MERGE
rainfall to within `4.65e-6` mm in each month. The Hydro observations were obtained
through the user's Azure device-code sign-in. MERGE source files were read from the
local raw cache where available; no synthetic observations were used.

The persisted monthly calibration in
`/data/CN3S/stations/56696000/calibration/M/` uses Plain NSE, a chronological 80/20
split, three warmup months, `act=0`, seed 42, up to 60 differential-evolution
generations, population size 8, and SciPy polishing. The split is **2023-01-01**.
The summary and modeled series agree on **45 training** and **12 held-out test**
months after warmup. Independent NSE recomputation from `modeled.parquet` matches
the summary:

| Period | NSE | Paired months |
| --- | ---: | ---: |
| Training | 0.940 | 45 |
| Held-out 2023 | -0.379 | 12 |

SciPy returned a final solution, but `converged` is **false** because it reached
the stated generation limit. The held-out score is poor: the plotted simulated
peak around the split is earlier and larger than the observed peak. The saved
quality score should be read as evidence of limited transfer to 2023, rather than
as a successful validation. The fitted parameter vector, ACT bound, optimizer
options, split date, input revision, and counts are in `summary.json`; 60 generation
records are in `history.parquet`, and 57 paired modeled months are in
`modeled.parquet`.

## Implementation

- `MergeRainSource` now uses the installed `mergedownloader` API. It reads one day
  or month at a time, crops the source raster to the upstream watershed bounds
  before clipping, and clears the downloader's file cache after each value.
  This fixed the import mismatch and the memory growth encountered with annual
  daily cubes. A focused offline test exercises both frequencies; real cached
  MERGE days and months were also read successfully.
- `StationCalibrationWorkflow.calibrate_station()` now saves the effective
  optimizer options, ACT bound, split date, and paired train/test counts. The
  optimizer retains the station name when rebuilding its parameter object.
- The notebook uses `max_act=0` because the current model shifts nonzero ACT by
  days even at monthly frequency, which breaks alignment with month-start Hydro
  discharge. Broader monthly ACT semantics remain a separate model decision.

## Verification

| Check | Result |
| --- | --- |
| Full pytest suite | 16 passed |
| Targeted Ruff and Ruff format check on changed Python files | Passed |
| Strict mypy on `src/cn3s` | Passed, 6 source files |
| Fresh-kernel monthly development notebook | All 5 code cells completed without error; saved tables and plot inspected |
| Saved asset checks | Monthly revision matches metadata; train/test dates are disjoint; saved NSE matches independent recomputation |

## Scope changes and remaining limits

The user first chose daily calibration and later changed the request to monthly.
An initial daily fit remains in `calibration/D/` with training NSE -0.060 and
test NSE 0.384. An in-progress polished daily rerun was stopped when the request
changed. The final development notebook and this outcome describe the monthly
run. The tentative 2021–2025 window was replaced with 2019–2023 after the live
Hydro query showed that 2024–2025 observations were unavailable. Preparation
files for those tentative years were removed from the station folder.

This run does not couple calibration to `BasinOverview` or evaluate other
stations. It does not establish a general interpretation for nonzero monthly
ACT. The 2023 held-out score is negative, so the fitted monthly parameters
should not be treated as validated for forecasting without further review.
