# Station calibration workflow — 2026-09-29

## What was implemented

`StationCalibrationWorkflow` connects the existing in-memory `Stations` and `Hydrography`
objects to the MERGE rainfall downloader, Hydro daily discharge, and `CN3SOptimizer`.
It prepares one station at a time and can calibrate daily (`D`) or monthly (`M`) data.
The class is exported from `cn3s` and accepts injectable rainfall and discharge providers
for offline tests or alternative data access.

```python
from cn3s import StationCalibrationWorkflow

workflow = StationCalibrationWorkflow(stations)
metadata = workflow.prepare_station(
    56920000, "2000-01-01", "2025-12-31", ("D", "M")
)
monthly = workflow.calibrate_station(56920000, "M")
workflow.plot_quality(ax, "RIO DOCE", "M")
```

Preparing a station creates its upstream watershed using the existing Otto selection.
`Stations.create_upstream` now attaches `area_nuareacont_km2`, the sum of the selected
watersheds' `nuareacont` values. Metadata also keeps the station's reported
`AreaDrenagem` for comparison. CN3S calibration uses the summed `nuareacont` area;
no area is derived from projected polygon geometry.

## Data flow and storage

The default root is `/data/CN3S`, configurable through `data_root`. Each station has
a stable folder at `stations/<station_code>/`:

```text
watershed.parquet
metadata.json
rain/daily/<year>.parquet
rain/monthly.parquet
discharge/daily.parquet
discharge/monthly.parquet
calibration/<D-or-M>/summary.json
calibration/<D-or-M>/history.parquet
calibration/<D-or-M>/modeled.parquet
```

Daily MERGE data is requested in annual chunks limited to the requested date window.
Monthly MERGE data is fetched directly, including partial boundary months. Rain is
stored as `prec`, indexed by calendar day or month start. Hydro is fetched once as
daily `Vazao`; monthly discharge is its month-start mean. The existing raw MERGE cache
remains at `/data/CN3S/downloads`. Legacy `/data/CN3S/basins` files are untouched.
Loading prepared rain checks that every requested day or month is present before
calibration begins.

Exact-window preparation reuses saved inputs. A changed date window, watershed
version, or contribution area requires `refresh=True`. Refreshed inputs receive a new
revision; old calibration summaries remain on disk but are shown as uncalibrated on
the quality map until calibrated again.

## Calibration and map decisions

`calibrate_station` composes `CN3SOptimizer` with Plain NSE by default. Other existing
optimizer objectives can be supplied. A run uses one caller-selected warmup length
(default 3), an 80/20 chronological train/test split, and one explicitly selected
frequency. The optimizer's cutoff was corrected so no date occurs in both periods.
The saved summary evaluates SciPy's final best parameter vector, not an earlier
callback row. Its held-out test NSE determines the map color. The map filters the
station `RIO` column, labels station codes, and shows stations lacking a current
finite test NSE in gray.

The default optimizer budget is 100 iterations with one worker. The caller may pass
SciPy differential-evolution options through `optimizer_options`; the default ACT
bound is 10 days for daily and 5 days for monthly calibration. Optimization runs are
for calibration; no production forecasting workflow was added.

## Dependencies and verification

The wheel now includes `utils`, which contains the existing Hydro SQL client. The
`workflow` package extra installs its Azure and SQL dependencies. The dev container
still installs `merge-downloader` from the Git branch already used by the project.
External providers are constructed lazily, so creating the workflow does not open
a database connection or start a download.

Tests use small synthetic geodata and fake sources. They cover the contribution-area
sum and version filtering, date boundaries, daily and monthly preparation, discharge
aggregation, saved-data reuse, disjoint train/test dates, a short real optimization,
map colors, missing rainfall, monthly discharge refresh, and calibration invalidation
after refresh. The checks run without calling MERGE or Hydro. The full pytest suite
(11 tests), targeted Ruff
checks for changed Python files, strict mypy for `src/cn3s` and `Stations`, and a wheel
build passed. Repository-wide Ruff still reports 119 existing issues across exploratory
notebooks and older copied utility modules; this iteration did not rewrite those files.
Live network and Azure authentication were not exercised.
