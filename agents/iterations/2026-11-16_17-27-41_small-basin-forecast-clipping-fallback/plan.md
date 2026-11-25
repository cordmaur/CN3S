# Small-basin forecast clipping fallback

## Plan

Implement the diagnosed intersecting-cell fallback locally in RainfallForecast.prepare_data.
Clip forecast, hindcast and mapped climatology together using the original cell-centre
selection first. Retry with all_touched=True only for NoDataInBounds. Keep native MERGE
clipping and existing basin correction unchanged. Record the selection rule in dataset
metadata and explain the coarse single-cell limitation in notebook 07. Preserve the
current Timbo_SE configuration and execute the complete notebook, saving fresh outputs.

## Verification

Run full repository-configured Ruff lint and format checks on changed Python/notebook
files, strict mypy on the changed module, and actual fresh-kernel execution of notebook
07. Use temporary checks for all nine models/four months, finite basin products,
consistent coarse masks, preserved native MERGE means, and numerical parity of clipping
where centres are present. Verify fully out-of-domain geometry still raises. Inspect
rendered maps/charts. No formal test suite or new dependencies.

## Session record

Implemented the fallback in src/hydro/rainfall.py without a new helper, class or
configuration option. Forecast, hindcast and mapped climatology are combined before
one Dataset rio.clip call. Only NoDataInBounds triggers a second call with
all_touched=True. All three variables therefore use the same spatial mask. Native
MERGE processing and correction arithmetic remain unchanged. Dataset metadata stores
basin_cell_selection as cell_center or all_touched and propagates it to regional maps.

Documented selection, equal intersecting-cell weights and the single 1° cell limitation
in notebook 07. Preserved every configuration value and all existing exploration.
Fresh execution revealed a second single-cell issue in the final automatic hindcast
plot: xarray squeezes its 1-by-1 field to a scalar and raises TypeError. That cell now
prints the mean hindcast value for a single cell and retains its spatial plot otherwise.
Only source cells 5, 24 and 25 changed (apart from existing trailing blank formatting).
Saved fresh outputs from all original cells after successful verification.

Validation completed:

- Executed all notebook 07 cells in a fresh kernel with the actual Timbo_SE basin,
  nine centres, October 2026 initialization, 2026-10-28 reference and four months.
  The resulting notebook contains five Plotly figures and three PNG figures, no
  saved exceptions or warning streams. Inspected both anomaly maps visually.
- Confirmed all nine models/four months retain one coarse cell at (-37.5, -10.5),
  use all_touched metadata, and contain finite rainfall, climatology, ratios,
  corrections and basin anomalies. Selected raw values exactly match direct
  intersecting-cell clipping.
- Verified correction arithmetic, unchanged October MERGE basin means (8.375 mm
  observed and approximately 32.7562 mm climatology), and identical Dataset versus
  old per-variable clipping for actual grids with centre-containing geometry.
- Confirmed fully out-of-domain geometry still raises NoDataInBounds with either
  selection rule. No unrelated exception handling was introduced.
- Median basin rainfall is approximately 14.60, 22.55, 21.36 and 43.21 mm for
  October 2026 through January 2027. Mean hindcast exploration prints 43.47 mm/30 days.
- Notebook schema, preserved configuration, full Ruff check, ruff format --check,
  and git diff --check pass for both changed files.
- Strict mypy (with cache disabled) reports one pre-existing ax annotation error,
  now at src/hydro/rainfall.py:712. Running the same check on git HEAD's original
  module reproduces it at line 704; no new mypy findings. Installed mypy also warns
  that the existing strict_equality_for_none setting is unrecognized. The initial
  cached run hit an internal mypy cache serialization error; disabling the cache
  allowed a complete diagnostic run. Left unrelated plotting annotations and
  repository/type-checker configuration untouched.
- Temporary assertions, baseline module, failed-run notebook and map previews were
  kept outside the repository and removed after review. No formal tests or new
  dependencies were added. Other existing user changes were preserved.

## Proposed method-call examples

```python
rainfall = RainfallForecast(basin, DATA_DIR, name=BASIN_NAME)
rainfall.prepare_data(start_month="10", year=2026, as_of="2026-10-28", months=4)
rainfall.data["forecast"].attrs["basin_cell_selection"]
rainfall.plot_rainfall_anomaly_map(unit="%", model="median", states=states)
```
